"""Smaller synthetic fixtures exercise all four benchmark modes, not market rates."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from crosscheck import scenario

ROOT = Path(__file__).resolve().parent.parent
BINARY = os.environ["ASTER_BINARY"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "synthetic.itch"
        data, count = scenario(314159)
        path.write_bytes(data)
        bench = subprocess.run([
            sys.executable, str(ROOT / "tools" / "bench_stages.py"),
            str(path), "--binary", BINARY, "--complete", "--warmups", "0",
            "--repetitions", "2", "--chunk", "7"],
            text=True, capture_output=True, check=True)
        report = json.loads(bench.stdout)
        assert bench.stderr.count("[bench] starting measurement") == 8
        assert bench.stderr.count("[bench] finished measurement") == 8
        assert report["parity"]["replay_frames"] == count
        assert report["parity"]["read_vs_mmap"]
        assert len(report["result"]) == 4
        for item in report["result"].values():
            assert item["samples"] == 2 and item["median_frames_per_second"] > 0
        p = subprocess.run([BINARY, str(path), "--decode-only", "--validate"],
                           capture_output=True, text=True)
        assert p.returncode != 0 and "incompatible" in p.stderr
        for io in ("mmap", "read"):
            command = [BINARY, str(path), "--decode-only", "--complete", "--io", io]
            if io == "read":
                command += ["--chunk", "1"]
            result = json.loads(subprocess.check_output(command, text=True))
            assert result["frames"] == count and result["applied"] == 0
            assert result["mode"] == "decode" and result["audit"]["closed"]
        bad = root / "bad.itch"
        bad.write_bytes(b"\x00\x03Z\x00\x00")
        proc = subprocess.run([BINARY, str(bad), "--decode-only"], capture_output=True, text=True)
        assert proc.returncode != 0
        print("stage benchmark and decode-only validation passed")


if __name__ == "__main__":
    main()
