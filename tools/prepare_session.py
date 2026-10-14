#!/usr/bin/env python3
"""Verify a downloaded ITCH gzip archive and safely expand it to an output file.

This deliberately does not download market data or make licensing decisions.
Use a vendor-published checksum when one is available and keep raw files out
of the Git repository.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

CHUNK = 4 * 1024 * 1024


def inspect_archive(path: Path) -> tuple[str, str, int]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK), b""):
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return sha256.hexdigest(), md5.hexdigest(), size


def read_sidecar(path: Path, archive: Path) -> str:
    # Accept GNU md5sum (`hash  filename`) and plain hash-only files.
    tokens = path.read_text(encoding="ascii").strip().split()
    if not tokens or len(tokens[0]) != 32 or any(c not in "0123456789abcdefABCDEF" for c in tokens[0]):
        raise ValueError("MD5 sidecar does not begin with a 32-character hexadecimal digest")
    if len(tokens) > 1 and Path(tokens[1].lstrip("* ")).name != archive.name:
        raise ValueError("MD5 sidecar filename does not match downloaded archive")
    return tokens[0].lower()


def prepare(archive: Path, output: Path, checksum: Path | None) -> dict:
    archive = archive.resolve()
    output = output.resolve()
    if not archive.is_file() or archive.suffix != ".gz":
        raise ValueError("expected an existing .gz archive")
    if output.exists():
        raise ValueError("refusing to overwrite existing output")
    output.parent.mkdir(parents=True, exist_ok=True)
    compressed_sha, compressed_md5, compressed_bytes = inspect_archive(archive)
    expected_md5 = read_sidecar(checksum, archive) if checksum else None
    if expected_md5 and expected_md5 != compressed_md5:
        raise ValueError("published compressed MD5 does not match; refusing to expand")
    # ISIZE in gzip headers wraps at 4 GiB, so it is not a safe disk estimate.
    # Display the actual free space, but do not incorrectly treat it as a bound.
    free = shutil.disk_usage(output.parent).free
    temporary = output.with_name(output.name + ".partial")
    if temporary.exists():
        raise ValueError("partial output already exists; inspect/remove it before retrying")
    expanded_digest = hashlib.sha256()
    expanded_bytes = 0
    try:
        with gzip.open(archive, "rb") as source, temporary.open("xb") as target:
            while chunk := source.read(CHUNK):
                target.write(chunk)
                expanded_digest.update(chunk)
                expanded_bytes += len(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "format": "aster-session-receipt-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "archive_name": archive.name,
        "compressed_bytes": compressed_bytes,
        "compressed_sha256": compressed_sha,
        "compressed_md5": compressed_md5,
        "published_md5_verified": expected_md5 is not None,
        "uncompressed_name": output.name,
        "uncompressed_bytes": expanded_bytes,
        "uncompressed_sha256": expanded_digest.hexdigest(),
        "free_bytes_before_expansion": free,
        "note": "A successful checksum/decompression does not certify market-data license, session completeness, or decoder correctness.",
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare and fingerprint a downloaded historical ITCH archive")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Uncompressed destination, must not exist")
    parser.add_argument("--md5-file", type=Path, help="Published vendor checksum sidecar")
    parser.add_argument("--receipt", type=Path, help="Optional JSON receipt; avoid committing local file paths")
    args = parser.parse_args()
    report = prepare(args.archive, args.output, args.md5_file)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        if args.receipt.exists():
            parser.error("refusing to overwrite an existing receipt")
        args.receipt.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, EOFError, gzip.BadGzipFile) as exc:
        print(f"preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
