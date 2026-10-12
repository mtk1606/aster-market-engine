#!/usr/bin/env python3
"""Compare mmap and chunked read with the same exact local ITCH file.

Provides same-host warm-cache throughput evidence. No per-event latency claim.
"""
import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import tempfile
from pathlib import Path

from benchmark import generate


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def once(command):
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def compare(binary, feed, runs, chunk, workload):
    common = [str(binary.resolve()), str(feed.resolve()), '--validate']
    variants = {
        'mmap': common + ['--io', 'mmap'],
        'read': common + ['--io', 'read', '--chunk', str(chunk)],
    }
    # Warm both code paths. Alternate the order to reduce systematic drift.
    for command in variants.values():
        once(command)
    samples = {'mmap': [], 'read': []}
    reference = None
    for i in range(runs):
        for label in (('mmap', 'read') if i % 2 == 0 else ('read', 'mmap')):
            result = once(variants[label])
            invariant = tuple(result[k] for k in
                              ('frames', 'bytes_consumed', 'applied', 'ignored',
                               'live_orders', 'digest'))
            if reference is None:
                reference = invariant
            if invariant != reference:
                raise AssertionError(f'logical replay mismatch in {label}: {invariant}')
            samples[label].append(result['frames_per_second'])
    return {
        'input': str(feed),
        'workload': workload,
        'input_sha256': sha256(feed),
        'input_bytes': feed.stat().st_size,
        'frames': reference[0],
        'state_digest': reference[5],
        'chunk_size': chunk,
        'repetitions': runs,
        'system': platform.platform(),
        'machine': platform.machine(),
        'results': {key: {
            'median_frames_per_second': statistics.median(values),
            'min_frames_per_second': min(values),
            'max_frames_per_second': max(values),
            'raw_frames_per_second': values,
        } for key, values in samples.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--input', type=Path, help='uncompressed historical ITCH file')
    group.add_argument('--orders', type=int, help='synthetic lifecycles')
    parser.add_argument('--repetitions', type=int, default=7)
    parser.add_argument('--chunk', type=int, default=65536)
    args = parser.parse_args()
    if args.repetitions < 2 or not (1 <= args.chunk <= 8 * 1024 * 1024):
        parser.error('repetitions >= 2; chunk 1..8388608')
    if args.orders is not None and args.orders < 1:
        parser.error('orders must be positive')
    with tempfile.TemporaryDirectory() as tmp:
        if args.input:
            feed = args.input
            workload = 'user-supplied-local-file'
        else:
            feed = Path(tmp) / 'synthetic.itch'
            generate(feed, args.orders)
            workload = 'synthetic-serial-churn-v1'
        print(json.dumps(compare(args.binary, feed, args.repetitions,
                                 args.chunk, workload), indent=2))


if __name__ == '__main__':
    main()
