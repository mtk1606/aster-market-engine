"""Independent C++/Python replay parity on deeper, changing synthetic books.

The generator is independent of both decoders. Its workload is deliberately
multi-symbol and leaves hundreds of resting orders, unlike the churn benchmark.
"""
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile

BINARY = Path(os.environ["ASTER_BINARY"]).resolve()
TOOLS = Path(__file__).resolve().parent.parent / "tools"


def frame(kind, locate=0, stamp=1, order=0, shares=100, price=1_000_000,
          side="B", stock="TEST", replacement=0, code="O"):
    lengths = {"S": 12, "R": 39, "H": 25, "A": 36, "F": 40, "E": 31,
               "C": 36, "X": 23, "D": 19, "U": 35}
    data = bytearray(lengths[kind])
    data[0] = ord(kind)
    struct.pack_into(">H", data, 1, locate)
    data[5:11] = stamp.to_bytes(6, "big")
    if kind == "S":
        data[11] = ord(code)
    if kind == "R":
        data[11:19] = stock.encode().ljust(8, b" ")
    if kind in "AF":
        struct.pack_into(">Q", data, 11, order)
        data[19] = ord(side)
        struct.pack_into(">I", data, 20, shares)
        data[24:32] = stock.encode().ljust(8, b" ")
        struct.pack_into(">I", data, 32, price)
    if kind in "ECXD U".replace(" ", ""):
        struct.pack_into(">Q", data, 11, order)
    if kind in "ECX":
        struct.pack_into(">I", data, 19, shares)
    if kind == "C":
        struct.pack_into(">I", data, 32, price)
    if kind == "U":
        struct.pack_into(">Q", data, 19, replacement)
        struct.pack_into(">I", data, 27, shares)
        struct.pack_into(">I", data, 31, price)
    return struct.pack(">H", len(data)) + data


def scenario(seed):
    rng = random.Random(seed)
    tickers = {7: "TEST", 8: "OTHER", 9: "THIRD"}
    stamp = 0
    records = []

    def send(kind, **kwargs):
        nonlocal stamp
        stamp += 1
        records.append(frame(kind, stamp=stamp, **kwargs))

    send("S", code="O")
    for locate, stock in tickers.items():
        send("R", locate=locate, stock=stock)
    live = {}
    next_ref = 10_000

    def add():
        nonlocal next_ref
        locate = rng.choice(list(tickers))
        side = rng.choice("BS")
        price = 950_000 + 1000 * rng.randrange(80)
        qty = rng.randint(1, 1500)
        next_ref += 1
        live[next_ref] = (locate, side, price, qty)
        send(rng.choice("AF"), locate=locate, stock=tickers[locate], side=side,
             price=price, shares=qty, order=next_ref)

    for _ in range(1800):
        add()
    for _ in range(3000):
        if rng.random() < 0.22 or not live:
            add()
        else:
            ref = rng.choice(tuple(live))
            locate, side, price, qty = live[ref]
            action = rng.choices(["E", "C", "X", "D", "U"], [15, 8, 24, 15, 38])[0]
            if action == "D":
                send("D", locate=locate, order=ref)
                del live[ref]
            elif action == "U":
                next_ref += 1
                new_qty = rng.randint(1, 1500)
                new_price = price if rng.random() < 0.5 else 950_000 + 1000 * rng.randrange(80)
                send("U", locate=locate, order=ref, replacement=next_ref,
                     shares=new_qty, price=new_price)
                del live[ref]
                live[next_ref] = (locate, side, new_price, new_qty)
            else:
                amount = rng.randint(1, qty)
                send(action, locate=locate, order=ref, shares=amount, price=price)
                if amount == qty:
                    del live[ref]
                else:
                    live[ref] = (locate, side, price, qty - amount)
        if rng.random() < 0.02:
            send("H", locate=rng.choice(list(tickers)))
    send("S", code="C")
    return b"".join(records), len(records)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for seed in (7, 42, 2026):
            source = Path(tmp) / f"scenario-{seed}.itch"
            payload, count = scenario(seed)
            source.write_bytes(payload)
            for symbol in ("TEST", "OTHER", "THIRD"):
                for chunk in (1, 4096):
                    command = [sys.executable, str(TOOLS / "verify_session.py"), str(source),
                               "--binary", str(BINARY), "--chunk", str(chunk),
                               "--independent", "--checkpoint-interval", "137",
                               "--symbol", symbol]
                    output = json.loads(subprocess.check_output(command, text=True))
                    assert output["mapped"]["frames"] == count
                    assert output["independent_reference"]["matched"]
                    assert output["mapped"]["live_orders"] > 800
            # The two decoders must reject the same corrupt protocol header.
            broken = Path(tmp) / "bad.itch"
            broken.write_bytes(payload[:2] + b"Z" + payload[3:])
            subprocess_run = subprocess.run([sys.executable, str(TOOLS / "verify_session.py"),
                                             str(broken), "--binary", str(BINARY),
                                             "--independent"], capture_output=True, text=True)
            assert subprocess_run.returncode != 0
        print("independent cross-check passed (3 deep books, 3 symbols, 2 buffered chunk sizes)")


if __name__ == "__main__":
    main()
