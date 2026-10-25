"""Synthetic multi-symbol controls for later-frame sampled-symbol verification."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from crosscheck import frame

BIN = Path(os.environ["ASTER_BINARY"]).resolve()
CHECKER = Path(__file__).resolve().parents[1] / "tools" / "verify_symbol.py"


def invoke(path: Path, symbol: str, limit: int, success: bool = True):
    p = subprocess.run(
        [sys.executable, str(CHECKER), str(path),
         "--binary", str(BIN), "--symbol", symbol, "--limit", str(limit)],
        text=True, capture_output=True,
    )
    if success:
        assert p.returncode == 0, (p.stdout, p.stderr)
        report = json.loads(p.stdout)
        assert report["independent_match"] and report["snapshot_matched"]
        assert report["differences"] == []
        assert report["frames"] == limit
        return report
    assert p.returncode != 0, (p.stdout, p.stderr)


def main():
    records = [
        frame("S", stamp=1, code="O"),
        frame("R", locate=7, stock="ALPHA", stamp=2),
        frame("R", locate=8, stock="BETA", stamp=3),
        frame("A", locate=7, stock="ALPHA", order=11, shares=100, stamp=4),
        frame("A", locate=8, stock="BETA", order=21, shares=80, stamp=5),
        frame("F", locate=7, stock="ALPHA", order=12, side="S", price=1_010_000, stamp=6),
        frame("E", locate=7, order=11, shares=25, stamp=7),
        frame("D", locate=8, order=21, stamp=8),
        frame("U", locate=7, order=12, replacement=13, shares=30,
              price=1_020_000, stamp=9),
        frame("R", locate=7, stock="ALPHA", stamp=10),
        frame("S", stamp=11, code="C"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "session.itch"
        source.write_bytes(b"".join(records))
        assert invoke(source, "ALPHA", 4)["selected_live_orders"] == 1
        assert invoke(source, "ALPHA", 9)["selected_live_orders"] == 2
        after = invoke(source, "ALPHA", 11)
        assert after["selected_updates_applied"] == 4
        assert after["selected_directory_repeats"] == 1
        assert invoke(source, "BETA", 5)["selected_live_orders"] == 1
        assert invoke(source, "BETA", 11)["selected_live_orders"] == 0
        invoke(source, "MISSING", 11, success=False)
        invoke(source, "ALPHA", 12, success=False)
        mutated = bytearray(records[9])
        mutated[2 + 19] = ord("Q")
        source.write_bytes(b"".join(records[:9] + [bytes(mutated)] + records[10:]))
        invoke(source, "ALPHA", 11, success=False)
    print("sampled-symbol later-frame parity tests passed")


if __name__ == "__main__":
    main()
