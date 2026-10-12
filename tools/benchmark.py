#!/usr/bin/env python3
"""Generate reproducible synthetic order churn, benchmark replay, report environment.

Not an exchange-feed benchmark: the event distribution is intentionally synthetic.
"""
import argparse
import json
import platform
import statistics
import struct
import subprocess
import tempfile
from pathlib import Path


def frame(kind, order, *, new=0, shares=0, price=0, locate=7):
    sizes = {'A': 36, 'E': 31, 'X': 23, 'D': 19, 'U': 35}
    body = bytearray(sizes[kind])
    body[0] = ord(kind)
    struct.pack_into('>H', body, 1, locate)
    body[5:11] = (43_200_000_000_000).to_bytes(6, 'big')
    struct.pack_into('>Q', body, 11, order)
    if kind == 'A':
        body[19] = ord('B' if order % 2 else 'S')
        struct.pack_into('>I', body, 20, shares)
        body[24:32] = b'TEST    '
        struct.pack_into('>I', body, 32, price)
    elif kind in 'EX':
        struct.pack_into('>I', body, 19, shares)
    elif kind == 'U':
        struct.pack_into('>Q', body, 19, new)
        struct.pack_into('>I', body, 27, shares)
        struct.pack_into('>I', body, 31, price)
    return struct.pack('>H', len(body)) + body


def generate(path, count):
    with open(path, 'wb') as dest:
        for i in range(1, count + 1):
            price = 10_000 + (i % 1_000)
            dest.write(frame('A', i, shares=300, price=price))
            dest.write(frame('E', i, shares=100))
            dest.write(frame('X', i, shares=50))
            dest.write(frame('U', i, new=i+count, shares=150, price=price+1))
            dest.write(frame('D', i+count))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path, help='path to Release-built aster-replay')
    parser.add_argument('--orders', type=int, default=100_000)
    parser.add_argument('--repetitions', type=int, default=5)
    args = parser.parse_args()
    if args.orders < 1 or args.repetitions < 2:
        parser.error('require --orders >=1 and --repetitions >=2')
    if args.orders > (2**64 - 1) // 2:
        parser.error('order IDs would overflow')
    with tempfile.TemporaryDirectory() as tmp:
        feed = Path(tmp) / 'synthetic.itch'
        generate(feed, args.orders)
        # Warmup is excluded. Each CLI process starts fresh.
        cmd = [str(args.binary.resolve()), str(feed), '--validate']
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        samples = [json.loads(subprocess.check_output(cmd, text=True))
                   for _ in range(args.repetitions)]
        assert all(sample['frames'] == 5 * args.orders and
                   sample['applied'] == 5 * args.orders and
                   sample['live_orders'] == 0 for sample in samples)
        assert len({sample['digest'] for sample in samples}) == 1
        print(json.dumps({
            'workload': 'synthetic-serial-churn-v1',
            'order_lifecycles': args.orders,
            'frames': 5 * args.orders,
            'feed_bytes': feed.stat().st_size,
            'repetitions': args.repetitions,
            'compiler_binary': str(args.binary),
            'system': platform.platform(),
            'machine': platform.machine(),
            'python': platform.python_version(),
            'median_frames_per_sec': statistics.median(
                x['frames_per_second'] for x in samples),
            'min_frames_per_sec': min(x['frames_per_second'] for x in samples),
            'max_frames_per_sec': max(x['frames_per_second'] for x in samples),
            'digest': samples[0]['digest'],
        }, indent=2))


if __name__ == '__main__':
    main()
