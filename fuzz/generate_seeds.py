#!/usr/bin/env python3
"""Build a minimal deterministic corpus for structured framing mutations."""
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent / 'corpus' / 'frames'
ROOT.mkdir(parents=True, exist_ok=True)


def packet(kind, order=0, qty=0, price=0, new=0):
    sizes = {'S': 12, 'A': 36, 'E': 31, 'X': 23, 'D': 19, 'U': 35}
    payload = bytearray(sizes[kind])
    payload[0] = ord(kind)
    struct.pack_into('>H', payload, 1, 7)
    payload[5:11] = (42_000_000_000_000).to_bytes(6, 'big')
    if kind != 'S':
        struct.pack_into('>Q', payload, 11, order)
    if kind == 'A':
        payload[19] = ord('B')
        struct.pack_into('>I', payload, 20, qty)
        payload[24:32] = b'TEST    '
        struct.pack_into('>I', payload, 32, price)
    if kind in ('E', 'X'):
        struct.pack_into('>I', payload, 19, qty)
    if kind == 'U':
        struct.pack_into('>Q', payload, 19, new)
        struct.pack_into('>I', payload, 27, qty)
        struct.pack_into('>I', payload, 31, price)
    return struct.pack('>H', len(payload)) + payload


def store(name, blob):
    (ROOT / name).write_bytes(blob)


sequence = (packet('S') + packet('A', order=1, qty=100, price=1_000_000)
            + packet('E', order=1, qty=20)
            + packet('U', order=1, new=2, qty=80, price=1_000_001)
            + packet('X', order=2, qty=20)
            + packet('D', order=2))
store('valid-lifecycle', sequence)
store('short-prefix', b'\x00')
store('short-payload', sequence[:-1])
store('invalid-side', packet('A', order=8, qty=1, price=1_000_000).replace(b'B', b'Z'))
store('zero-length', b'\x00\x00')
store('unknown-type', b'\x00\x0c' + b'z' + b'\x00' * 11)
print('Corpus written:', ROOT)
