#!/usr/bin/env python3
"""Repeat a recorded ITCH replay with independent I/O paths and compare results.

Neither matching hashes nor a successful parse proves that the exchange feed is
complete, or that the book accurately models unobserved hidden liquidity.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from reference_replay import replay as independent_replay


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(binary, source, method, chunk, strict, interval=0, symbol=None):
    cmd = [str(binary), str(source), "--io", method, "--validate", "--audit"]
    if strict:
        cmd += ["--complete"]
    if interval:
        cmd += ["--checkpoint-interval", str(interval)]
    if symbol:
        cmd += ["--symbol", symbol, "--snapshot"]
    if method == "read":
        cmd += ["--chunk", str(chunk)]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError(f"{method} replay failed ({proc.returncode}): {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def compare(mapped, streamed):
    ignored = {"io", "elapsed_seconds", "frames_per_second"}
    a = {key: value for key, value in mapped.items() if key not in ignored}
    b = {key: value for key, value in streamed.items() if key not in ignored}
    if a != b:
        differing = sorted(key for key in set(a) | set(b) if a.get(key) != b.get(key))
        raise RuntimeError(f"mmap/read replay mismatch: {', '.join(differing)}")


def main():
    parser = argparse.ArgumentParser(description="Validate and fingerprint one uncompressed ITCH replay")
    parser.add_argument("file", type=Path, help="Uncompressed Nasdaq ITCH historical file")
    parser.add_argument("--binary", type=Path, default=Path("build/aster-replay"))
    parser.add_argument("--chunk", type=int, default=65536)
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="Allow partial sessions; full session validation is the default")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON verification record")
    parser.add_argument("--independent", action="store_true",
                        help="Also compare with a separate Python decoder and FIFO reference book")
    parser.add_argument("--checkpoint-interval", type=int, default=100000,
                        help="Frames between independently compared book digests (default: 100000)")
    parser.add_argument("--symbol", help="Include full independent FIFO snapshot of this symbol")
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error("input file does not exist")
    if args.file.suffix == ".gz":
        parser.error("decompress .gz to an uncompressed ITCH file first")
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"replay binary not found: {binary}")
    if not 1 <= args.chunk <= 8 * 1024 * 1024:
        parser.error("chunk must be between 1 and 8388608")

    if args.independent and args.checkpoint_interval < 1:
        parser.error("checkpoint interval must be positive")
    interval = args.checkpoint_interval if args.independent else 0
    mapped = run(binary, args.file, "mmap", args.chunk, not args.allow_incomplete,
                 interval, args.symbol)
    streamed = run(binary, args.file, "read", args.chunk, not args.allow_incomplete,
                   interval, args.symbol)
    compare(mapped, streamed)
    size = args.file.stat().st_size
    if mapped["bytes_consumed"] != size:
        raise RuntimeError("not all file bytes consumed")
    record = {
        "format": "aster-session-verification-v1",
        "source_sha256": sha256(args.file),
        "source_size_bytes": size,
        "complete_session_required": not args.allow_incomplete,
        "mapped": mapped,
        "streamed": streamed,
        "state_equivalent": True,
        "note": "Internal decoder parity is not independent exchange-data correctness validation.",
    }
    if args.independent:
        reference = independent_replay(args.file, interval, complete=not args.allow_incomplete,
                                       selected_symbol=args.symbol)
        differences = [key for key in reference if mapped.get(key) != reference[key]]
        if differences:
            raise RuntimeError("independent Python/C++ mismatch in: " + ", ".join(differences))
        record["independent_reference"] = {
            "matched": True,
            "engine": "separate Python struct decoder and ordered-dict FIFO book",
            "checkpoints": len(reference["checkpoints"]),
            "symbol_snapshot_compared": args.symbol,
        }
    payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
