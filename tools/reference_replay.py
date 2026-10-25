#!/usr/bin/env python3
"""Deliberately separate ITCH 5.0 decoder and FIFO reference book.

This uses Python struct unpacking, ordered dictionaries and a streaming file reader,
not the C++ decoder or its book implementation. It is a correctness oracle for
supported displayed-book events, not an alternative production feed handler.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import json
from pathlib import Path
import struct

# ITCH message lengths in bytes including the one-byte message identifier,
# excluding the two-byte BinaryFILE record prefix.
SIZE = {
    "S": 12, "R": 39, "H": 25, "Y": 20, "L": 26, "V": 35,
    "W": 12, "K": 28, "J": 35, "h": 20, "A": 36, "F": 40,
    "E": 31, "C": 36, "X": 23, "D": 19, "U": 35, "P": 44,
    "Q": 40, "B": 19, "I": 50, "N": 20, "O": 48,
}
FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
MASK = (1 << 64) - 1
DAY_NS = 86_400_000_000_000


class ReferenceError(ValueError):
    pass


def u16(record: bytes, offset: int) -> int:
    return struct.unpack_from(">H", record, offset)[0]


def u32(record: bytes, offset: int) -> int:
    return struct.unpack_from(">I", record, offset)[0]


def u64(record: bytes, offset: int) -> int:
    return struct.unpack_from(">Q", record, offset)[0]


def symbol_field(record: bytes, offset: int) -> str:
    raw = record[offset:offset + 8]
    if any(v < 32 or v > 126 for v in raw):
        raise ReferenceError("stock symbol has non-printable characters")
    symbol = raw.decode("ascii").rstrip(" ")
    if not symbol or " " in symbol:
        raise ReferenceError("invalid stock symbol padding")
    return symbol


def frames(path: Path, complete: bool, limit: int | None):
    """Yield framed messages without loading the entire input into memory."""
    position = 0
    seen = 0
    with path.open("rb") as stream:
        while limit is None or seen < limit:
            prefix = stream.read(2)
            if not prefix:
                break
            if len(prefix) != 2:
                raise ReferenceError(f"truncated frame length at byte {position}")
            length, = struct.unpack(">H", prefix)
            if length == 0:
                if not complete:
                    raise ReferenceError(f"unexpected terminator at byte {position}")
                if stream.read(1):
                    raise ReferenceError("trailing bytes after terminator")
                position += 2
                break
            data = stream.read(length)
            if len(data) != length:
                raise ReferenceError(f"truncated frame at byte {position}")
            if not data:
                raise ReferenceError(f"empty payload at byte {position}")
            kind = chr(data[0])
            if kind not in SIZE or length != SIZE[kind]:
                raise ReferenceError(f"unknown or incorrectly sized message {kind!r} at byte {position}")
            seen += 1
            yield position, data
            position += length + 2
        # `bytes_consumed` is calculated independently of the event counters.
        # For limited replays, this is the position after the last yielded frame.
    return


class ReferenceBook:
    def __init__(self):
        # Order ref -> mutable record (locate, side, price4, remaining shares)
        self.live: dict[int, tuple[int, str, int, int]] = {}
        # (locate, side, price4) -> insertion-ordered order refs and sizes
        self.levels: dict[tuple[int, str, int], OrderedDict[int, int]] = {}
        self.applied = 0

    def _insert(self, ref: int, order: tuple[int, str, int, int]):
        if ref == 0 or ref in self.live:
            raise ReferenceError("duplicate or zero order reference")
        locate, side, price, qty = order
        if not price or not qty or side not in "BS":
            raise ReferenceError("invalid add/replace fields")
        key = (locate, side, price)
        self.live[ref] = order
        self.levels.setdefault(key, OrderedDict())[ref] = qty

    def _remove(self, ref: int):
        locate, side, price, _ = self.live.pop(ref)
        key = (locate, side, price)
        del self.levels[key][ref]
        if not self.levels[key]:
            del self.levels[key]

    def apply(self, data: bytes, locate: int):
        kind = chr(data[0])
        if kind in "AF":
            self._insert(u64(data, 11), (locate, chr(data[19]), u32(data, 32), u32(data, 20)))
        elif kind in "ECXDU":
            ref = u64(data, 11)
            if ref not in self.live:
                raise ReferenceError("unknown order reference")
            old_locate, side, price, existing = self.live[ref]
            if locate != old_locate:
                raise ReferenceError("order locate mismatch")
            if kind == "D":
                self._remove(ref)
            elif kind in "ECX":
                qty = u32(data, 19)
                if qty == 0 or qty > existing:
                    raise ReferenceError("invalid share reduction")
                if qty == existing:
                    self._remove(ref)
                else:
                    self.live[ref] = (locate, side, price, existing - qty)
                    self.levels[(locate, side, price)][ref] = existing - qty
            elif kind == "U":
                new_ref, new_qty, new_price = u64(data, 19), u32(data, 27), u32(data, 31)
                if new_ref == ref or new_ref == 0 or new_ref in self.live or not new_qty or not new_price:
                    raise ReferenceError("invalid replacement")
                self._remove(ref)
                self._insert(new_ref, (locate, side, new_price, new_qty))
        else:
            return False
        self.applied += 1
        return True

    def _level_prices(self) -> dict[tuple[int, str], list[int]]:
        # Build one temporary index per checkpoint instead of scanning *all*
        # price levels again for every stock locate. The previous approach was
        # O(number of locates * number of nonempty price levels), which made
        # real-session checkpoints disproportionately expensive.
        prices: dict[tuple[int, str], list[int]] = {}
        for locate, side, price in self.levels:
            prices.setdefault((locate, side), []).append(price)
        return prices

    def _digest_locations(
        self, locations: list[int],
        level_prices: dict[tuple[int, str], list[int]] | None = None,
    ) -> str:
        value = FNV_OFFSET
        # The book's wire-independent fingerprint serializes five uint64
        # fields per live order, in price-time sequence. This implementation
        # uses struct rather than the C++ bitwise mix loop.
        if level_prices is None:
            level_prices = self._level_prices()
        for locate in locations:
            for side in "BS":
                for price in sorted(level_prices.get((locate, side), ()),
                                    reverse=(side == "B")):
                    for ref, qty in self.levels[(locate, side, price)].items():
                        for octet in struct.pack("<QQQQQ", locate, ord(side), price, ref, qty):
                            value = ((value ^ octet) * FNV_PRIME) & MASK
        return format(value, "x")

    def digest(self) -> str:
        return self._digest_locations(sorted({key[0] for key in self.levels}))

    def locate_digests(self) -> dict[str, str]:
        level_prices = self._level_prices()
        locates = sorted({locate for locate, _ in level_prices})
        return {str(locate): self._digest_locations([locate], level_prices)
                for locate in locates}

    def snapshot(self, locate: int) -> dict:
        result: dict[str, list] = {}
        for side, name in (("B", "bids"), ("S", "asks")):
            prices = sorted((key[2] for key in self.levels if key[0] == locate and key[1] == side),
                            reverse=(side == "B"))
            result[name] = [
                {"price4": price,
                 "shares": sum(self.levels[(locate, side, price)].values()),
                 "orders": [[ref, qty] for ref, qty in self.levels[(locate, side, price)].items()]}
                for price in prices
            ]
        return result


def replay(path: Path, interval: int, complete: bool = True, limit: int | None = None,
           selected_symbol: str | None = None, locate_digests: bool = False):
    if not interval or interval < 0:
        raise ReferenceError("checkpoint interval must be positive")
    if complete and limit is not None:
        raise ReferenceError("cannot limit a complete session")
    book = ReferenceBook()
    by_locate: dict[int, str] = {}
    by_symbol: dict[str, int] = {}
    directory_fields: dict[int, bytes] = {}
    directory_repeats = 0
    types = Counter()
    opened = closed = False
    timestamps_decreased = 0
    previous_ts = None
    transitions = ignored = count = consumed = 0
    checkpoints = []
    for offset, data in frames(path, complete, limit):
        kind = chr(data[0])
        locate = u16(data, 1)
        timestamp = int.from_bytes(data[5:11], "big")
        if timestamp >= DAY_NS:
            raise ReferenceError(f"bad timestamp at {offset}")
        if previous_ts is not None and timestamp < previous_ts:
            timestamps_decreased += 1
        previous_ts = timestamp
        types[kind] += 1
        count += 1
        consumed = offset + len(data) + 2
        if closed:
            raise ReferenceError("message after end")
        if kind == "S":
            code = chr(data[11])
            if code not in "OSQMEC":
                raise ReferenceError("bad system event")
            if not opened and code != "O":
                raise ReferenceError("system event before open")
            if code == "O":
                if opened or count != 1:
                    raise ReferenceError("late/duplicate start")
                opened = True
            if code == "C":
                closed = True
            transitions += 1
            ignored += 1
        elif kind == "R":
            if not opened or locate == 0:
                raise ReferenceError("invalid stock directory")
            name = symbol_field(data, 11)
            if name in by_symbol or locate in by_locate:
                if by_locate.get(locate) != name or by_symbol.get(name) != locate:
                    raise ReferenceError("conflicting stock directory mapping")
                if directory_fields[locate] != data[11:]:
                    raise ReferenceError("conflicting stock directory fields")
                directory_repeats += 1
            else:
                by_locate[locate] = name
                by_symbol[name] = locate
                directory_fields[locate] = data[11:]
            ignored += 1
        elif kind in "AF":
            if locate not in by_locate or symbol_field(data, 24) != by_locate[locate]:
                raise ReferenceError("stock directory/order symbol mismatch")
            book.apply(data, locate)
        elif kind in "ECXDU":
            if locate not in by_locate:
                raise ReferenceError("order update on absent locate")
            book.apply(data, locate)
        else:
            if not opened:
                raise ReferenceError("message before open")
            ignored += 1
        if count % interval == 0:
            checkpoints.append({"frame": count, "applied": book.applied,
                                "live_orders": len(book.live), "digest": book.digest()})
    # A trailing 0-length terminator does not count as a frame.
    if complete and path.stat().st_size == consumed + 2:
        with path.open("rb") as f:
            f.seek(consumed)
            if f.read(2) == b"\0\0":
                consumed += 2
    if not checkpoints or checkpoints[-1]["frame"] != count:
        checkpoints.append({"frame": count, "applied": book.applied,
                            "live_orders": len(book.live), "digest": book.digest()})
    if complete and (not opened or not closed or timestamps_decreased):
        raise ReferenceError("incomplete session or decreasing timestamps")
    result = {
        "frames": count, "bytes_consumed": consumed,
        "applied": book.applied, "ignored": ignored,
        "live_orders": len(book.live), "digest": book.digest(),
        "checkpoints": checkpoints,
        "audit": {
            "directories": len(by_locate), "directory_repeats": directory_repeats,
            "system_events": transitions,
            "opened": opened, "closed": closed,
            "timestamp_regressions": timestamps_decreased,
            "last_timestamp_ns": previous_ts or 0,
            "types": dict(types),
        },
    }
    if locate_digests:
        result["locate_digests"] = book.locate_digests()
    if selected_symbol is not None:
        if selected_symbol not in by_symbol:
            raise ReferenceError(f"unknown stock: {selected_symbol}")
        locate = by_symbol[selected_symbol]
        snap = book.snapshot(locate)
        bid = snap["bids"][0] if snap["bids"] else None
        ask = snap["asks"][0] if snap["asks"] else None
        result.update({
            "locate": locate, "symbol": selected_symbol, "snapshot": snap,
            "bid4": bid["price4"] if bid else None,
            "bid_shares": bid["shares"] if bid else 0,
            "ask4": ask["price4"] if ask else None,
            "ask_shares": ask["shares"] if ask else 0,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="Independent Python ITCH displayed-book replay")
    parser.add_argument("file", type=Path)
    parser.add_argument("--interval", type=int, default=100_000)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--symbol")
    parser.add_argument("--locate-digests", action="store_true")
    args = parser.parse_args()
    print(json.dumps(replay(args.file, args.interval, complete=not args.allow_incomplete,
                            limit=args.limit, selected_symbol=args.symbol,
                            locate_digests=args.locate_digests), sort_keys=True))


if __name__ == "__main__":
    main()
