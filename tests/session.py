"""Protocol/session fixtures: generated from ITCH 5.0 field offsets, not real exchange data."""
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path

BIN = os.environ["ASTER_BINARY"]


def msg(kind, *, locate=0, timestamp=1, order=0, stock="TEST", side="B", shares=5,
        price=1_250_000, code=None):
    lengths = {"S": 12, "R": 39, "A": 36, "F": 40, "E": 31, "X": 23,
               "D": 19, "U": 35}
    p = bytearray(lengths[kind])
    p[0] = ord(kind)
    struct.pack_into(">H", p, 1, locate)
    p[5:11] = timestamp.to_bytes(6, "big")
    if kind == "S":
        p[11] = ord(code)
    if kind == "R":
        p[11:19] = stock.encode().ljust(8, b" ")
    if kind in "AF":
        struct.pack_into(">Q", p, 11, order)
        p[19] = ord(side)
        struct.pack_into(">I", p, 20, shares)
        p[24:32] = stock.encode().ljust(8, b" ")
        struct.pack_into(">I", p, 32, price)
    if kind in "EXD":
        struct.pack_into(">Q", p, 11, order)
        if kind != "D":
            struct.pack_into(">I", p, 19, shares)
    return struct.pack(">H", len(p)) + p


def replay(contents, flags, expected_error=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.itch"
        path.write_bytes(contents)
        variants = [[], ["--io", "read", "--chunk", "1"],
                    ["--io", "read", "--chunk", "7"]]
        results = []
        for io in variants:
            p = subprocess.run([BIN, str(path), *io, *flags], capture_output=True, text=True)
            if expected_error is not None:
                assert p.returncode != 0 and expected_error in p.stderr, (io, p.stderr)
            else:
                assert p.returncode == 0, (io, p.stderr)
                results.append(json.loads(p.stdout))
        if expected_error is not None:
            return None
        keys = ("frames", "applied", "ignored", "digest", "live_orders", "audit",
                "locate", "symbol", "bid4", "bid_shares", "ask4", "ask_shares", "snapshot")
        for value in results[1:]:
            for key in keys:
                assert value.get(key) == results[0].get(key), (key, value, results[0])
        return results[0]


def main():
    start = msg("S", code="O", timestamp=1)
    directory = msg("R", locate=7, stock="TEST", timestamp=2)
    second_directory = msg("R", locate=8, stock="OTHER", timestamp=3)
    a = msg("A", locate=7, order=101, stock="TEST", timestamp=4, shares=25)
    b = msg("F", locate=8, order=102, stock="OTHER", timestamp=5, shares=75, side="S")
    execute = msg("E", locate=7, order=101, timestamp=6, shares=10)
    end = msg("S", code="C", timestamp=7)
    data = start + directory + second_directory + a + b + execute + end
    result = replay(data, ["--complete", "--symbol", "TEST", "--snapshot", "--validate"])
    assert result["frames"] == 7 and result["applied"] == 3
    assert result["symbol"] == "TEST" and result["locate"] == 7
    assert result["bid4"] == 1_250_000 and result["bid_shares"] == 15
    assert result["audit"]["directories"] == 2 and result["audit"]["closed"]
    assert result["audit"]["types"] == {"S": 2, "R": 2, "A": 1, "F": 1, "E": 1}
    assert result["audit"]["timestamp_regressions"] == 0
    assert result["snapshot"]["bids"][0]["orders"] == [[101, 15]]
    # Cross-reader report binds replay results to a SHA-256 of the exact bytes.
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "session.itch"
        fixture.write_bytes(data)
        script = Path(__file__).parent.parent / "tools" / "verify_session.py"
        report = json.loads(subprocess.check_output(
            ["python3", str(script), str(fixture), "--binary", BIN, "--chunk", "7"], text=True))
        assert report["state_equivalent"] and report["mapped"]["frames"] == 7
        assert report["source_size_bytes"] == len(data)
    terminated = replay(data + b"\x00\x00",
                        ["--complete", "--symbol", "TEST", "--snapshot", "--validate"])
    assert terminated["digest"] == result["digest"]
    assert terminated["bytes_consumed"] == len(data) + 2
    replay(data + b"\x00\x00", ["--audit"], "zero-length frame")
    replay(data + b"\x00\x00X", ["--complete"],
           "bytes after zero-length terminator")
    other = replay(data, ["--complete", "--symbol", "OTHER", "--snapshot"])
    assert other["ask_shares"] == 75 and other["symbol"] == "OTHER"
    replay(data, ["--symbol", "ABSENT"], "symbol not found")
    replay(data, ["--complete", "--limit", "5"], "--complete cannot be used with --limit")
    replay(start + directory + a, ["--complete"], "session missing end-of-messages event")
    replay(directory + start, ["--audit"], "stock directory before start")
    replay(start + directory + directory, ["--audit"], "duplicate stock locate")
    replay(start + directory + msg("R", locate=9, stock="TEST", timestamp=3),
           ["--audit"], "duplicate stock symbol")
    replay(start + directory + msg("A", locate=7, stock="WRONG", order=10, timestamp=3),
           ["--audit"], "order add stock differs")
    replay(start + msg("A", locate=7, order=10, timestamp=3),
           ["--audit"], "unknown stock locate")
    replay(start + directory + a + end + b,
           ["--audit"], "message after end of messages")
    replay(start + directory + a + msg("S", code="Z", timestamp=5),
           ["--audit"], "unknown system event code")
    replay(start + directory + msg("A", locate=7, order=10, timestamp=1) + end,
           ["--complete"], "decreasing timestamps")
    incomplete = replay(start + directory + a, ["--audit"])
    assert incomplete["audit"]["opened"] and not incomplete["audit"]["closed"]
    print("session audit fixtures passed (both I/O paths, 3 chunk sizes)")


if __name__ == "__main__":
    main()
