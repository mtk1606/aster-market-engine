#!/usr/bin/env python3
"""Reproducible add/delete workload and verification for independent book engines.

The optional second executable must be supplied by a person authorized to use
it. This repository does not contain or compile the QSE implementation.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import resource
import statistics
import subprocess
import sys
import tempfile
import time

SCHEMA = "order-book-comparison-v1"
MASK = (1 << 64) - 1
BASE = 14695981039346656037
PRIME = 1099511628211


def mix(value: int, item: int) -> int:
    for _ in range(8):
        value = ((value ^ (item & 0xff)) * PRIME) & MASK
        item >>= 8
    return value


def generate(path: Path, seed: int, count: int, depth: int) -> None:
    rng = random.Random(seed)
    live: dict[int, tuple[str, int, int]] = {}
    next_id = 1
    with path.open("w", encoding="ascii", newline="\n") as file:
        file.write("# order-book-comparison-v1: A id side price4 shares | D id\n")
        for i in range(count):
            # Keep approximately `depth` simultaneously resting orders.
            # Once the book is full, remove a random live ID, then refill.
            delete = len(live) >= depth
            if delete:
                victim = rng.choice(tuple(live))
                file.write(f"D {victim}\n")
                del live[victim]
            else:
                side = "B" if rng.randrange(2) else "S"
                price4 = (1_000_000 if side == "B" else 1_000_500) + rng.randrange(45) * 10
                shares = rng.randrange(1, 700)
                file.write(f"A {next_id} {side} {price4} {shares}\n")
                live[next_id] = side, price4, shares
                next_id += 1


def reference(path: Path) -> dict:
    levels: dict[str, dict[int, OrderedDict[int, int]]] = {"B": {}, "S": {}}
    orders: dict[int, tuple[str, int, int]] = {}
    count = 0
    with path.open("r", encoding="ascii") as file:
        for line in file:
            if not line.strip() or line.startswith("#"):
                continue
            pieces = line.split()
            count += 1
            if pieces[0] == "A" and len(pieces) == 5:
                oid = int(pieces[1]); side = pieces[2]
                price = int(pieces[3]); size = int(pieces[4])
                if side not in levels or oid <= 0 or oid in orders or size <= 0 or price <= 0:
                    raise ValueError("invalid add")
                orders[oid] = side, price, size
                levels[side].setdefault(price, OrderedDict())[oid] = size
            elif pieces[0] == "D" and len(pieces) == 2:
                oid = int(pieces[1])
                side, price, _ = orders.pop(oid)
                queue = levels[side][price]
                del queue[oid]
                if not queue:
                    del levels[side][price]
            else:
                raise ValueError("invalid operation")
    state = BASE
    for side in "BS":
        state = mix(state, ord(side))
        prices = sorted(levels[side], reverse=(side == "B"))
        state = mix(state, len(prices))
        for price in prices:
            fifo = levels[side][price]
            state = mix(state, price)
            state = mix(state, sum(fifo.values()))
            state = mix(state, len(fifo))
            for oid, shares in fifo.items():
                state = mix(state, oid)
                state = mix(state, shares)
    def best(side: str) -> tuple[int | None, int]:
        prices = levels[side]
        if not prices: return None, 0
        price = max(prices) if side == "B" else min(prices)
        return price, sum(prices[price].values())
    bid, bid_shares = best("B")
    ask, ask_shares = best("S")
    return {"schema": SCHEMA, "operations": count, "live_orders": len(orders),
            "state_hash": f"{state:016x}", "bid4": bid, "ask4": ask,
            "bid_shares": bid_shares, "ask_shares": ask_shares}


def sha256(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            hash_.update(chunk)
    return hash_.hexdigest()


def invoke(binary: Path, workload: Path) -> tuple[dict, dict]:
    cmd = [str(binary), str(workload)]
    start = time.perf_counter()
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # The drivers must emit compact JSON only, and cannot fill a pipe.
    _, status, usage = os.wait4(process.pid, 0)
    wall = time.perf_counter() - start
    stdout = process.stdout.read() if process.stdout else b""
    stderr = process.stderr.read() if process.stderr else b""
    if process.stdout: process.stdout.close()
    if process.stderr: process.stderr.close()
    rc = os.waitstatus_to_exitcode(status)
    if rc != 0:
        raise RuntimeError(f"{binary.name} returned {rc}: {stderr.decode(errors='replace')[:1000]}")
    value = json.loads(stdout)
    elapsed = value.get("elapsed_seconds", 0)
    if type(elapsed) not in (int, float) or not 0 < elapsed <= wall * 5:
        raise RuntimeError(f"{binary.name} returned an invalid elapsed time")
    return value, {"engine_seconds": elapsed, "process_wall_seconds": wall,
                   "operations_per_second": value["operations"] / elapsed,
                   "max_rss_kib": usage.ru_maxrss,
                   "user_cpu_seconds": usage.ru_utime,
                   "system_cpu_seconds": usage.ru_stime}


def validate(result: dict, expected: dict, label: str) -> None:
    if result.get("schema") != SCHEMA or result.get("engine") != label:
        raise RuntimeError(f"{label}: protocol or engine identifier mismatch")
    for key, value in expected.items():
        if result.get(key) != value:
            raise RuntimeError(f"{label}: {key} mismatch: expected {value!r}, got {result.get(key)!r}")


def execute(args: argparse.Namespace) -> dict:
    if not 1 <= args.operations <= 10_000_000 or not 2 <= args.depth <= 100_000:
        raise ValueError("operations must be 1..10000000; depth 2..100000")
    if not 1 <= args.repetitions <= 20 or not 0 <= args.warmups <= 10:
        raise ValueError("repetitions must be 1..20; warmups 0..10")
    binaries = {"aster": args.aster.resolve()}
    if args.qse_driver:
        binaries["qse"] = args.qse_driver.resolve()
    if not all(p.is_file() and os.access(p, os.X_OK) for p in binaries.values()):
        raise ValueError("each driver must be an executable file")
    with tempfile.TemporaryDirectory(prefix="aster-book-") as tmp:
        path = Path(tmp) / "workload.tsv"
        generate(path, args.seed, args.operations, args.depth)
        expected = reference(path)
        workload_hash = sha256(path)
        measured: dict[str, list[dict]] = {name: [] for name in binaries}
        for attempt in range(args.repetitions + args.warmups):
            names = list(binaries) if attempt % 2 == 0 else list(reversed(binaries))
            for name in names:
                result, sample = invoke(binaries[name], path)
                validate(result, expected, name)
                if attempt >= args.warmups:
                    measured[name].append(sample)
        records = {}
        for name, runs in measured.items():
            records[name] = {
                "driver_sha256": sha256(binaries[name]),
                "median_operations_per_second": statistics.median(r["operations_per_second"] for r in runs),
                "median_engine_seconds": statistics.median(r["engine_seconds"] for r in runs),
                "max_observed_rss_kib": max(r["max_rss_kib"] for r in runs),
                "runs": runs,
            }
        # Do not claim an unconditional speedup from non-identical interfaces.
        return {
            "format": "aster-qse-comparison-v1",
            "utc": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(),
            "seed": args.seed, "requested_operations": args.operations,
            "target_depth": args.depth, "repetitions": args.repetitions,
            "warmups": args.warmups, "workload_sha256": workload_hash,
            "workload_definition": "single-instrument add and full delete only; no ITCH parsing, partial reductions, executions, or strategy logic",
            "oracle": expected, "drivers": records,
            "qse_executed": "qse" in records,
            "comparison_limitations": (
                "Requires a separately authorized QSE driver implementing the exact JSON and operation protocol. "
                "Aster uses numeric order IDs; a QSE adapter may require string and queue-ID bookkeeping. "
                "Only add and whole-order delete have agreed semantics; engine internal operations are not identical. "
                "Whole-loop throughput, not market-data end-to-end or tail latency."
            ),
        }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aster", type=Path, default=Path("build/aster-book-bench"))
    p.add_argument("--qse-driver", type=Path, help="separately authorized executable; never built or included here")
    p.add_argument("--operations", type=int, default=10000)
    p.add_argument("--depth", type=int, default=512)
    p.add_argument("--seed", type=int, default=6007)
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--warmups", type=int, default=1)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    try:
        report = execute(args)
        serialized = json.dumps(report, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        p.exit(1, f"comparison aborted: {exc}\n")


if __name__ == "__main__":
    main()
