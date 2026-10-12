"""Differential replay test: independent Python state model vs C++ CLI."""
import json
import os
import random
import struct
import subprocess
import tempfile
from pathlib import Path

BIN = os.environ["ASTER_BINARY"]


def frame(kind: str, *, locate=7, order=0, side="B", shares=0,
          price=0, new_order=0):
    size = {"S": 12, "A": 36, "F": 40, "E": 31, "C": 36,
            "X": 23, "D": 19, "U": 35, "P": 44}[kind]
    p = bytearray(size)
    p[0] = ord(kind)
    struct.pack_into(">H", p, 1, locate)
    p[5:11] = (12_000_000_000).to_bytes(6, "big")
    if kind in "AF":
        struct.pack_into(">Q", p, 11, order)
        p[19] = ord(side)
        struct.pack_into(">I", p, 20, shares)
        p[24:32] = b"TEST    "
        struct.pack_into(">I", p, 32, price)
    elif kind in "ECXD":
        struct.pack_into(">Q", p, 11, order)
        if kind != "D":
            struct.pack_into(">I", p, 19, shares)
        if kind == "C":
            struct.pack_into(">I", p, 32, price)
    elif kind == "U":
        struct.pack_into(">Q", p, 11, order)
        struct.pack_into(">Q", p, 19, new_order)
        struct.pack_into(">I", p, 27, shares)
        struct.pack_into(">I", p, 31, price)
    return struct.pack(">H", size) + p


def expected_levels(live, priority, locate, side):
    price_levels = {}
    for order_id, (symbol, order_side, price, shares) in live.items():
        if symbol == locate and order_side == side:
            price_levels.setdefault(price, []).append((priority[order_id], order_id, shares))
    result = []
    for price in sorted(price_levels, reverse=(side == "B")):
        ordered = sorted(price_levels[price])
        result.append({"price4": price, "shares": sum(qty for _, _, qty in ordered),
                       "orders": [[order_id, qty] for _, order_id, qty in ordered]})
    return result


def expected_top(live, locate):
    bids, asks = {}, {}
    for (symbol, side, price, shares) in live.values():
        if symbol != locate:
            continue
        book = bids if side == "B" else asks
        book[price] = book.get(price, 0) + shares
    bid = max(bids) if bids else None
    ask = min(asks) if asks else None
    return bid, bids.get(bid, 0), ask, asks.get(ask, 0)


def run(seed):
    rng = random.Random(seed)
    records = [frame("S", locate=0), frame("P")]
    live = {}
    priority = {}
    ticket = 0
    next_id = 1
    applied = 0
    for _ in range(2500):
        locate = rng.choice([7, 8, 9])
        eligible = [k for k, v in live.items() if v[0] == locate]
        if not eligible or rng.random() < 0.55:
            side = rng.choice("BS")
            price = rng.randrange(10_000, 20_000)
            shares = rng.randrange(1, 5000)
            records.append(frame(rng.choice("AF"), locate=locate,
                                 order=next_id, side=side, shares=shares, price=price))
            live[next_id] = (locate, side, price, shares)
            priority[next_id] = ticket
            ticket += 1
            next_id += 1
        else:
            key = rng.choice(eligible)
            symbol, side, price, shares = live[key]
            kind = rng.choice("ECXDU")
            if kind == "U":
                new_qty = rng.randrange(1, 4000)
                new_price = rng.randrange(10_000, 20_000)
                records.append(frame("U", locate=locate, order=key, new_order=next_id,
                                     shares=new_qty, price=new_price))
                del live[key]
                del priority[key]
                live[next_id] = (locate, side, new_price, new_qty)
                priority[next_id] = ticket
                ticket += 1
                next_id += 1
            elif kind == "D":
                records.append(frame("D", locate=locate, order=key))
                del live[key]
                del priority[key]
            else:
                qty = rng.randrange(1, shares + 1)
                records.append(frame(kind, locate=locate, order=key,
                                     shares=qty, price=price))
                if qty == shares:
                    del live[key]
                    del priority[key]
                else:
                    live[key] = (symbol, side, price, shares - qty)
        applied += 1
    with tempfile.TemporaryDirectory() as tmp:
        filepath = Path(tmp) / "feed.itch"
        filepath.write_bytes(b"".join(records))
        expected_total_bytes = sum(len(record) for record in records)
        canonical = {}
        for locate in (7, 8, 9):
            proc = subprocess.run([BIN, str(filepath), "--locate", str(locate),
                                   "--snapshot", "--validate"],
                                  text=True, capture_output=True, check=True)
            result = json.loads(proc.stdout)
            assert result["frames"] == len(records), result
            assert result["bytes_consumed"] == expected_total_bytes, result
            assert result["applied"] == applied, result
            assert result["ignored"] == 2, result
            assert result["live_orders"] == len(live), result
            assert (result["bid4"], result["bid_shares"],
                    result["ask4"], result["ask_shares"]) == expected_top(live, locate), result
            for name, side in (("bids", "B"), ("asks", "S")):
                assert result["snapshot"][name] == expected_levels(live, priority, locate, side), (
                    seed, locate, side, result["snapshot"][name]
                )
            canonical[locate] = result
            # Explicitly exercise carry-over when records cross read() boundaries.
            chunks = [7] if seed else [1, 2, 3, 7, 31, 64, 4096, 65536]
            for chunk in chunks if locate == 7 else [7]:
                via_read = json.loads(subprocess.check_output(
                    [BIN, str(filepath), "--io", "read", "--chunk", str(chunk),
                     "--locate", str(locate), "--snapshot", "--validate"], text=True))
                for field in ("frames", "bytes_consumed", "applied", "ignored", "live_orders",
                              "digest", "bid4", "bid_shares", "ask4", "ask_shares", "snapshot"):
                    assert via_read[field] == result[field], (seed, locate, chunk, field)
        truncated = Path(tmp) / "truncated.itch"
        truncated.write_bytes(b"".join(records)[:-1])
        for io_opts in ([], ["--io", "read", "--chunk", "1"]):
            bad = subprocess.run([BIN, str(truncated), *io_opts], text=True,
                                 capture_output=True)
            assert bad.returncode != 0 and "truncated frame payload" in bad.stderr
            # Stray trailing byte is a partial length prefix, never silent EOF.
            stray = Path(tmp) / "stray.itch"
            stray.write_bytes(b"".join(records) + b"\x00")
            bad = subprocess.run([BIN, str(stray), *io_opts], text=True,
                                 capture_output=True)
            assert bad.returncode != 0 and "truncated frame length" in bad.stderr
            assert f"byte {expected_total_bytes}:" in bad.stderr
            # Reject zero length consistently at the exact byte offset.
            zero = Path(tmp) / "zero.itch"
            zero.write_bytes(b"".join(records) + b"\x00\x00")
            bad = subprocess.run([BIN, str(zero), *io_opts], text=True,
                                 capture_output=True)
            assert bad.returncode != 0 and "zero-length frame" in bad.stderr
            assert f"byte {expected_total_bytes}:" in bad.stderr
            # A limit intentionally processes only a prefix.
            limited = json.loads(subprocess.check_output(
                [BIN, str(filepath), *io_opts, "--limit", "2"], text=True))
            assert limited["frames"] == 2 and limited["bytes_consumed"] == (
                len(records[0]) + len(records[1]))
        again = json.loads(subprocess.check_output([BIN, str(filepath)], text=True))
        assert again["digest"] == canonical[7]["digest"]



if __name__ == "__main__":
    for seed in (0, 1, 7, 42, 2026):
        run(seed)
    print("5 deterministic trials passed (12,500 transitions, full FIFO depth and streaming parity)")
