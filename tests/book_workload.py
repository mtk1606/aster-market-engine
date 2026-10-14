"""Aster's order-only adapter agrees with an independent Python FIFO model."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import compare_books as comparison

binary = Path(os.environ["ASTER_BOOK_BINARY"]).resolve()
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    workload = temp / "orders.tsv"
    for seed, count, depth in [(1, 37, 8), (6, 300, 25), (91, 1500, 90), (10, 4000, 210)]:
        comparison.generate(workload, seed, count, depth)
        expected = comparison.reference(workload)
        result = json.loads(subprocess.check_output([str(binary), str(workload)], text=True))
        comparison.validate(result, expected, "aster")
    workload.write_text("A 1 B 1000100 10\nA 1 B 1000100 10\n")
    invalid = subprocess.run([str(binary), str(workload)], capture_output=True)
    assert invalid.returncode != 0 and b"duplicate" in invalid.stderr
    workload.write_text("A -1 B 1000100 10\n")
    invalid = subprocess.run([str(binary), str(workload)], capture_output=True)
    assert invalid.returncode != 0
    workload.write_text("D 700\n")
    invalid = subprocess.run([str(binary), str(workload)], capture_output=True)
    assert invalid.returncode != 0
    report = comparison.execute(comparison.argparse.Namespace(
        aster=binary, qse_driver=None, operations=1500, depth=100, seed=10,
        repetitions=2, warmups=0))
    assert not report["qse_executed"] and report["oracle"]["operations"] == 1500
print("standalone book workload and independent reference passed")
