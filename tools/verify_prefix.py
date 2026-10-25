#!/usr/bin/env python3
"""Check a bounded prefix of a real ITCH file against the independent Python book.

Partial sessions are deliberate here: a small prefix exercises live FIFO state
without allocating memory for hundreds of millions of Python order updates.
No source market-data bytes are copied or included in the resulting report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from reference_replay import replay as python_replay


FIELDS = (
    "frames", "bytes_consumed", "applied", "ignored",
    "live_orders", "digest", "checkpoints", "audit",
)


def prefix_sha256(source: Path, size: int) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        left = size
        while left:
            chunk = stream.read(min(1024 * 1024, left))
            if not chunk:
                raise RuntimeError("file shortened while hashing the checked prefix")
            digest.update(chunk)
            left -= len(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare bounded ITCH prefix against independent Python FIFO model")
    parser.add_argument("file", type=Path)
    parser.add_argument("--binary", type=Path, default=Path("build-release/aster-replay"))
    parser.add_argument("--limit", type=int, default=250000)
    parser.add_argument("--checkpoint-interval", type=int, default=50000)
    parser.add_argument("--io", choices=("read", "mmap"), default="read")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.limit < 1 or args.checkpoint_interval < 1:
        parser.error("--limit and --checkpoint-interval must be positive")
    if not args.file.is_file() or not args.binary.is_file():
        parser.error("file and --binary must both exist")
    if args.file.suffix == ".gz":
        parser.error("uncompress the ITCH recording before verification")

    source = args.file.resolve()
    binary = args.binary.resolve()
    before = source.stat().st_size
    cmd = [
        str(binary), str(source), "--io", args.io, "--audit", "--validate",
        "--limit", str(args.limit),
        "--checkpoint-interval", str(args.checkpoint_interval),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(f"C++ prefix replay failed: {completed.stderr.strip()}")
    cpp = json.loads(completed.stdout)
    if cpp["frames"] != args.limit:
        raise RuntimeError(
            f"recording has only {cpp['frames']} frames before the requested {args.limit}")

    ref = python_replay(
        source, args.checkpoint_interval, complete=False, limit=args.limit,
    )
    differences = {
        field: {"cpp": cpp[field], "python": ref[field]}
        for field in FIELDS if cpp[field] != ref[field]
    }
    if source.stat().st_size != before:
        raise RuntimeError("recording size changed during the check")
    report = {
        "format": "aster-real-feed-prefix-comparison-v1",
        "source_name": source.name,
        "source_size_bytes": before,
        "checked_prefix_sha256": prefix_sha256(source, cpp["bytes_consumed"]),
        "prefix_bytes_consumed": cpp["bytes_consumed"],
        "frames": args.limit,
        "checkpoint_interval": args.checkpoint_interval,
        "checkpoint_count": len(cpp["checkpoints"]),
        "io": args.io,
        "independent_match": not differences,
        "differences": differences,
        "cpp_elapsed_seconds": cpp["elapsed_seconds"],
        "note": (
            "Only the initial bounded prefix was compared. This is not independent "
            "verification of the remainder of the trading session."
        ),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if differences:
        raise RuntimeError("independent Python and C++ book state differ")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"prefix verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
