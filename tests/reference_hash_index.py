"""Regression test for the independent FIFO fingerprint's temporary price index.

A simple scan-based oracle checks that the optimization changes neither
side/price/FIFO order nor the full-book and per-locate digest values.
"""
from __future__ import annotations

from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from reference_replay import FNV_OFFSET, FNV_PRIME, MASK, ReferenceBook


def slow_digest(book: ReferenceBook, locates: list[int]) -> str:
    value = FNV_OFFSET
    for locate in locates:
        for side in "BS":
            prices = sorted(
                (price for key_locate, key_side, price in book.levels
                 if key_locate == locate and key_side == side),
                reverse=(side == "B"),
            )
            for price in prices:
                for ref, shares in book.levels[(locate, side, price)].items():
                    for octet in struct.pack("<QQQQQ", locate, ord(side), price, ref, shares):
                        value = ((value ^ octet) * FNV_PRIME) & MASK
    return format(value, "x")


def main() -> None:
    book = ReferenceBook()
    assert book.digest() == format(FNV_OFFSET, "x")
    assert book.locate_digests() == {}
    order_ref = 1000
    removed = []
    for locate in range(1, 181):
        for side in "BS":
            for tick in range(9):
                price = 950000 + tick * 1000 + (locate % 7) * 10
                for _ in range(2):
                    order_ref += 1
                    book._insert(order_ref, (locate, side, price, 5 + order_ref % 19))
                    if order_ref % 13 == 0:
                        removed.append(order_ref)

    for ref in removed:
        book._remove(ref)

    all_locates = sorted({locate for locate, _, _ in book.levels})
    assert len(all_locates) == 180
    assert book.digest() == slow_digest(book, all_locates)
    all_digests = book.locate_digests()
    assert len(all_digests) == 180
    for locate in (1, 2, 17, 64, 179, 180):
        expected = slow_digest(book, [locate])
        assert all_digests[str(locate)] == expected
        assert book._digest_locations([locate]) == expected

    for subset in ([1, 17, 180], [2, 64], [179], []):
        assert book._digest_locations(subset) == slow_digest(book, subset)
    print("reference hash index matches scan-based full-book and per-locate oracle")


if __name__ == "__main__":
    main()
