#!/usr/bin/env python3
"""Independently compare one symbol's displayed FIFO book at a late ITCH frame.

Reads from frame 1 so resting orders and replacements predating the selected
checkpoint are incorporated. Python only retains orders of the chosen stock.
The C++ engine still validates/replays *all* stocks through the checkpoint.

This is a sampled-symbol check, NOT a full-session independent oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from reference_replay import FNV_OFFSET, ReferenceBook, ReferenceError, frames, symbol_field, u16


def prefix_sha256(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = size
        while remaining:
            data = stream.read(min(1 << 20, remaining))
            if not data:
                raise RuntimeError("recording shortened while computing prefix hash")
            digest.update(data)
            remaining -= len(data)
    return digest.hexdigest()


def selected_book(path: Path, symbol: str, limit: int) -> dict:
    """Stream the entire prefix; reconstruct only selected stock's FIFO state."""
    book = ReferenceBook()
    symbol_locate = None
    directory_fields = None
    duplicate_announcements = 0
    count = consumed = 0
    for offset, record in frames(path, complete=False, limit=limit):
        count += 1
        consumed = offset + len(record) + 2
        kind = chr(record[0])
        locate = u16(record, 1)
        if kind == "R":
            stock = symbol_field(record, 11)
            if stock == symbol:
                if symbol_locate is None:
                    symbol_locate, directory_fields = locate, record[11:]
                    if locate == 0:
                        raise ReferenceError("selected symbol uses locate zero")
                elif locate != symbol_locate or record[11:] != directory_fields:
                    raise ReferenceError("conflicting directory for selected symbol")
                else:
                    duplicate_announcements += 1
            elif symbol_locate is not None and locate == symbol_locate:
                raise ReferenceError("selected locate reused for another symbol")
        elif symbol_locate is not None and locate == symbol_locate:
            if kind in "AF":
                if symbol_field(record, 24) != symbol:
                    raise ReferenceError("selected add stock differs from directory")
                book.apply(record, locate)
            elif kind in "ECXDU":
                book.apply(record, locate)
    if count != limit:
        raise ReferenceError(f"requested {limit} frames but found {count}")
    if symbol_locate is None:
        raise ReferenceError(f"symbol {symbol!r} not announced by frame {limit}")
    return {
        "frames": count, "bytes_consumed": consumed,
        "locate": symbol_locate, "snapshot": book.snapshot(symbol_locate),
        "live_orders": len(book.live),
        "locate_digest": book._digest_locations([symbol_locate]),
        "selected_updates": book.applied,
        "directory_repeats": duplicate_announcements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare a late-frame full-depth symbol book without retaining other stocks in Python")
    parser.add_argument("file", type=Path)
    parser.add_argument("--binary", type=Path, default=Path("build-release/aster-replay"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit or args.limit > 368366634 * 100:
        parser.error("--limit must be a positive sensible frame count")
    if not args.file.is_file() or not args.binary.is_file():
        parser.error("recording and --binary must both exist")
    if args.file.suffix == ".gz":
        parser.error("use the uncompressed ITCH recording")
    source, binary = args.file.resolve(), args.binary.resolve()
    original_size = source.stat().st_size

    command = [
        str(binary), str(source), "--io", "read", "--chunk", "65536",
        "--audit", "--validate", "--symbol", args.symbol, "--snapshot",
        "--locate-digests", "--limit", str(args.limit),
    ]
    cpp_run = subprocess.run(command, text=True, capture_output=True)
    if cpp_run.returncode:
        raise RuntimeError(f"C++ replay failed: {cpp_run.stderr.strip()}")
    cpp = json.loads(cpp_run.stdout)
    py = selected_book(source, args.symbol, args.limit)

    cpp_locate_hash = cpp["locate_digests"].get(str(py["locate"]))
    # An empty stock is intentionally absent from the map of nonempty locates.
    if not py["live_orders"]:
        python_hash = None
    else:
        python_hash = py["locate_digest"]

    checks = {
        "frames": (cpp["frames"], py["frames"]),
        "bytes_consumed": (cpp["bytes_consumed"], py["bytes_consumed"]),
        "locate": (cpp["locate"], py["locate"]),
        "symbol": (cpp["symbol"], args.symbol),
        "snapshot": (cpp["snapshot"], py["snapshot"]),
        "locate_digest": (cpp_locate_hash, python_hash),
    }
    differences = [field for field, (a, b) in checks.items() if a != b]
    if source.stat().st_size != original_size:
        raise RuntimeError("source size changed during verification")
    digest = prefix_sha256(source, py["bytes_consumed"])
    report = {
        "format": "aster-sampled-symbol-reference-v1",
        "source_name": source.name,
        "source_size_bytes": original_size,
        "prefix_sha256": digest,
        "frames": args.limit,
        "prefix_bytes_consumed": py["bytes_consumed"],
        "symbol": args.symbol,
        "locate": py["locate"],
        "selected_updates_applied": py["selected_updates"],
        "selected_live_orders": py["live_orders"],
        "selected_directory_repeats": py["directory_repeats"],
        "selected_locate_digest": py["locate_digest"],
        "cpp_elapsed_seconds": cpp["elapsed_seconds"],
        "snapshot_matched": "snapshot" not in differences,
        "independent_match": not differences,
        "differences": differences,
        "note": (
            "Python reconstructs only the named stock but reads from frame 1. "
            "C++ validates all stocks through the requested frame. "
            "Does not independently validate other stocks or the whole day."
        ),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if differences:
        raise RuntimeError("C++/Python selected stock mismatch: " + ", ".join(differences))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ReferenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"sampled symbol verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
