"""Check ITCH 5.0 message sizes and Operational Halt replay with synthetic data."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from reference_replay import SIZE

# Nasdaq TotalView-ITCH 5.0 payload lengths, excluding BinaryFILE framing.
SPEC = {
    "S": 12,  # 1.1
    "R": 39, "H": 25, "Y": 20, "L": 26,  # 1.2.1–1.2.4
    "V": 35, "W": 12,  # 1.2.5
    "K": 28, "J": 35, "h": 21,  # 1.2.6–1.2.8
    "A": 36, "F": 40,  # 1.3.1–1.3.2
    "E": 31, "C": 36, "X": 23, "D": 19, "U": 35,  # 1.4.1–1.4.5
    "P": 44, "Q": 40, "B": 19,  # 1.5.1–1.5.3
    "I": 50, "N": 20, "O": 48,  # 1.6–1.8
}


def frame(payload):
    return struct.pack(">H", len(payload)) + payload


def main():
    assert SIZE == SPEC, (SIZE, SPEC)
    system_event = struct.pack(">cHH6sc", b"S", 0, 0, (1).to_bytes(6, "big"), b"O")
    operational_halt = struct.pack(
        ">cHH6s8scc", b"h", 7, 0, (2).to_bytes(6, "big"), b"TEST    ", b"Q", b"H"
    )

    with tempfile.TemporaryDirectory() as tmp:
        valid = Path(tmp) / "halt.itch"
        invalid = Path(tmp) / "short-halt.itch"
        valid.write_bytes(frame(system_event) + frame(operational_halt))
        invalid.write_bytes(frame(system_event) + frame(operational_halt[:-1]))

        binary = os.environ["ASTER_BINARY"]
        for mode in ([], ["--decode-only"]):
            result = json.loads(subprocess.check_output([binary, str(valid), *mode], text=True))
            assert (result["frames"], result["ignored"]) == (2, 2), result
            rejected = subprocess.run(
                [binary, str(invalid), *mode], capture_output=True, text=True
            )
            assert rejected.returncode != 0, rejected
            assert "ITCH type 'h' length 20, expected 21" in rejected.stderr, rejected

        reference = [sys.executable, str(TOOLS / "reference_replay.py"), "--allow-incomplete"]
        result = json.loads(subprocess.check_output([*reference, str(valid)], text=True))
        assert result["audit"]["types"] == {"S": 1, "h": 1}, result
        rejected = subprocess.run([*reference, str(invalid)], capture_output=True, text=True)
        assert rejected.returncode != 0, rejected
        assert "incorrectly sized message 'h'" in rejected.stderr, rejected


if __name__ == "__main__":
    main()
