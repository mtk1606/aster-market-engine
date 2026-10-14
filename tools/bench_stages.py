#!/usr/bin/env python3
"""Run and compare two replay pipelines on identical session bytes.

Runs are repeated and alternating. The elapsed time is end-to-end replay loop
wall time, not per-message tail latency. Linux wait4 supplies per-child max RSS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

STAGES = (("mmap", "decode"), ("read", "decode"),
          ("mmap", "replay"), ("read", "replay"))


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def invoke(binary: Path, path: Path, io: str, mode: str, chunk: int, complete: bool):
    command = [str(binary), str(path), "--io", io]
    if io == "read":
        command += ["--chunk", str(chunk)]
    if mode == "decode":
        command += ["--decode-only"]
    else:
        command += ["--validate"]
    if complete:
        command += ["--complete"]
    else:
        command += ["--audit"]
    # On Linux, wait4 provides a per-child RSS measurement. The child emits a
    # single compact JSON record, so it cannot fill the stdout pipe.
    start = time.perf_counter()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, status, stats = os.wait4(proc.pid, 0)
    wall = time.perf_counter() - start
    stdout, stderr = proc.stdout.read(), proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    proc.returncode = os.waitstatus_to_exitcode(status)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} exited {proc.returncode}: {stderr.decode('utf-8', 'replace')[:800]}")
    record = json.loads(stdout)
    if record["mode"] != mode or record["io"] != io:
        raise RuntimeError("unexpected replay mode or input path")
    return {
        "elapsed_seconds": record["elapsed_seconds"],
        "wall_seconds": wall,
        "frames_per_second": record["frames_per_second"],
        "max_rss_kib": stats.ru_maxrss,  # Linux: KiB
        "user_cpu_seconds": stats.ru_utime,
        "system_cpu_seconds": stats.ru_stime,
    }, record


def percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * percentile
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def summary(trials: list[dict]) -> dict:
    return {
        "samples": len(trials),
        "median_frames_per_second": statistics.median(t["frames_per_second"] for t in trials),
        "median_engine_seconds": statistics.median(t["elapsed_seconds"] for t in trials),
        "median_process_wall_seconds": statistics.median(t["wall_seconds"] for t in trials),
        "p10_process_wall_seconds": percentile([t["wall_seconds"] for t in trials], 0.10),
        "p90_process_wall_seconds": percentile([t["wall_seconds"] for t in trials], 0.90),
        "max_observed_rss_kib": max(t["max_rss_kib"] for t in trials),
        "measurements": trials,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ITCH framing/decoding and full book replay")
    parser.add_argument("file", type=Path, help="Uncompressed BinaryFILE ITCH file")
    parser.add_argument("--binary", type=Path, default=Path("build/aster-replay"))
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--chunk", type=int, default=65536)
    parser.add_argument("--complete", action="store_true", help="Require opened/closed session")
    parser.add_argument("--output", type=Path, help="Write reproducible JSON report")
    args = parser.parse_args()
    source = args.file.resolve()
    binary = args.binary.resolve()
    if not source.is_file() or not binary.is_file():
        parser.error("input file and replay binary must both exist")
    if source.suffix == ".gz":
        parser.error("decompress gzip before benchmarking; this measures replay, not decompression")
    if not 1 <= args.repetitions <= 30 or not 0 <= args.warmups <= 10:
        parser.error("repetitions must be 1..30 and warmups 0..10")
    if not 1 <= args.chunk <= 8 * 1024 * 1024:
        parser.error("chunk must be 1..8388608")

    size, checksum = source.stat().st_size, digest_file(source)
    actual: dict[tuple[str, str], list[dict]] = {stage: [] for stage in STAGES}
    observed: dict[tuple[str, str], dict] = {}
    # Different stage orders across rounds reduce systematic order bias.
    for attempt in range(args.warmups + args.repetitions):
        sequence = STAGES if attempt % 2 == 0 else tuple(reversed(STAGES))
        for io, mode in sequence:
            result, record = invoke(binary, source, io, mode, args.chunk, args.complete)
            if (io, mode) not in observed:
                observed[(io, mode)] = record
            else:
                prev = observed[(io, mode)]
                for key in ("frames", "bytes_consumed", "applied", "ignored", "digest", "audit"):
                    if prev[key] != record[key]:
                        raise RuntimeError(f"non-deterministic result: {io}/{mode} field {key}")
            if attempt >= args.warmups:
                actual[(io, mode)].append(result)
    # Reader parity per stage, and equal frame/byte coverage across modes.
    for mode in ("decode", "replay"):
        left = observed[("mmap", mode)]
        right = observed[("read", mode)]
        for field in ("frames", "bytes_consumed", "applied", "ignored", "digest", "audit"):
            if left[field] != right[field]:
                raise RuntimeError(f"reader mismatch in {mode}: {field}")
    if observed[("mmap", "decode")]["frames"] != observed[("mmap", "replay")]["frames"]:
        raise RuntimeError("decode and replay disagree on frame count")
    if observed[("mmap", "replay")]["bytes_consumed"] != size:
        raise RuntimeError("replay did not consume all file bytes")
    if source.stat().st_size != size or digest_file(source) != checksum:
        raise RuntimeError("input file changed during benchmark")
    report = {
        "format": "aster-stage-benchmark-v1",
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": source.name,
        "input_sha256": checksum,
        "input_size_bytes": size,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "replay_binary": str(binary),
        "replay_binary_sha256": digest_file(binary),
        "repetitions": args.repetitions,
        "warmups": args.warmups,
        "read_chunk_bytes": args.chunk,
        "complete_session_required": args.complete,
        "result": {f"{io}_{mode}": summary(actual[(io, mode)]) for io, mode in STAGES},
        "parity": {"read_vs_mmap": True, "decode_and_replay_frame_counts_equal": True,
                   "replay_frames": observed[("mmap", "replay")]["frames"],
                   "replay_digest": observed[("mmap", "replay")]["digest"]},
        "caveat": "Whole-run wall/CPU/RSS measurements, not per-event p99 latency. Decode-only bypasses order-book updates; the difference is not an isolated book update microbenchmark. File cache and host load may dominate.",
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as e:
        print(f"benchmark failed: {e}", file=sys.stderr)
        sys.exit(1)
