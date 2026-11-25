"""Run the two-receiver synthetic loopback demo and verify both Aster snapshots."""

import argparse
import json
import select
import socket
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from protocol import DEFAULT_INTERFACE, block

CLI = Path(__file__).with_name("replay.py")


def sample():
    records = []
    for order in range(1, 7):
        body = struct.pack("!cHH6sQcI8sI", b"A", 7, order,
                           order.to_bytes(6, "big"), order, b"B", order,
                           b"TEST    ", 10000 + order)
        records.append(block(body))
    return b"".join(records)


def port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def require(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def snapshot(command):
    result = json.loads(subprocess.check_output(command, text=True, timeout=10))
    result.pop("elapsed_seconds", None)
    result.pop("frames_per_second", None)
    return result


def wait_until_joined(proc, name):
    ready = select.select([proc.stderr], [], [], 5)[0]
    require(ready and proc.stderr.readline().strip() == "READY",
            f"receiver {name} failed to join multicast")


def verify_unrecovered_tail(replay, original, network, directory):
    output = directory / "incomplete.itch"
    output.write_bytes(b"existing output")
    with subprocess.Popen(
        [*replay, "receive", str(output), *network, "--timeout", "0.5"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as receiver:
        try:
            wait_until_joined(receiver, "without repair")
            sender = subprocess.run(
                [*replay, "send", str(original), *network, "--packet-messages", "2",
                 "--drop-sequence", "5", "--grace", "0.2"],
                capture_output=True, text=True, timeout=10,
            )
            require(sender.returncode == 0, sender.stderr)
            stdout, stderr = receiver.communicate(timeout=10)
            require(receiver.returncode == 1 and "timed out" in stderr, (stdout, stderr))
            stats = json.loads(stdout)
            require(stats["missing_messages"] == 2 and stats["end_sequence"] == 7
                    and not stats["complete"], stats)
            require(output.read_bytes() == b"existing output", "incomplete run replaced output")
        finally:
            if receiver.poll() is None:
                receiver.kill()
    print("PASS: unrecovered tail reported and existing output preserved")


def run(binary, directory):
    original = directory / "original.itch"
    original.write_bytes(sample())
    multicast_port, request_port = port(), port()
    while multicast_port == request_port:
        request_port = port()
    network = ["--port", str(multicast_port), "--request-port", str(request_port)]
    replay = [sys.executable, str(CLI)]
    receivers = []
    # Validate both actual snapshots against the known synthetic fixture as well as each other.
    aster = [str(binary), str(original), "--locate", "7", "--validate", "--snapshot"]
    expected = snapshot(aster)
    require(expected["frames"] == expected["applied"] == expected["live_orders"] == 6,
            expected)
    require(expected["bid4"] == 10006 and expected["bid_shares"] == 6, expected)
    try:
        for name in ("one", "two"):
            output = directory / f"receiver-{name}.itch"
            proc = subprocess.Popen(
                [*replay, "receive", str(output), *network, "--request-host", DEFAULT_INTERFACE],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            receivers.append((proc, output))
            wait_until_joined(proc, name)
        sent = subprocess.run(
            [*replay, "send", str(original), *network, "--packet-messages", "2",
             "--drop-sequence", "1", "--swap-sequence", "3"],
            capture_output=True, text=True, timeout=10,
        )
        require(sent.returncode == 0, sent.stderr)
        sender = json.loads(sent.stdout)
        require(sender["injected_drops"] == sender["injected_swaps"] == 1, sender)
        print(f"Sender: {sent.stdout.strip()}")
        for index, (proc, output) in enumerate(receivers, 1):
            stdout, stderr = proc.communicate(timeout=10)
            require(proc.returncode == 0, f"receiver {index}: {stdout} {stderr}")
            stats = json.loads(stdout)
            require(stats["complete"] and stats["missing_messages"] == 0
                    and stats["messages"] == 6 and stats["recovered_messages"] == 2
                    and stats["out_of_order_packets"] == 1 and stats["first_gap"] == [1, 5],
                    stats)
            require(output.read_bytes() == original.read_bytes(), "BinaryFILE bytes differ")
            aster[1] = str(output)
            result = snapshot(aster)
            require(result == expected, "Aster replay result differs")
            print(f"Receiver {index}: {stdout.strip()}")
    finally:
        for proc, _ in receivers:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()
    print("PASS: two identical BinaryFILE handoffs and Aster snapshots")
    verify_unrecovered_tail(replay, original, network, directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aster_replay", type=Path, help="built aster-replay executable")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aster-moldudp64-") as temp:
        run(args.aster_replay.resolve(), Path(temp))
