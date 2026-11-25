"""Exercise jump thresholds, feed ordering, and halted/crossed exclusions."""
import struct

from session import msg, replay

NANOSECONDS = 1_000_000_000
START = (9 * 3600 + 35 * 60) * NANOSECONDS


def status(timestamp, state):
    payload = bytearray(25)
    payload[0] = ord("H")
    struct.pack_into(">H", payload, 1, 7)
    payload[5:11] = timestamp.to_bytes(6, "big")
    payload[11:19] = b"TEST    "
    payload[19] = ord(state)
    return struct.pack(">H", len(payload)) + payload


def update(kind, timestamp, order, **fields):
    return msg(kind, locate=7, timestamp=timestamp, order=order, **fields)


def main():
    event = START + NANOSECONDS
    contents = b"".join([
        msg("S", timestamp=1, code="O"),
        msg("R", timestamp=2, locate=7),
        status(3, "T"),
        update("A", START - 6 * NANOSECONDS, 1, price=990_000, shares=100),
        update("A", START - 6 * NANOSECONDS, 2, side="S", price=1_000_000, shares=100),
        update("A", START - 5 * NANOSECONDS, 3, side="S", price=1_010_000, shares=200),
        update("X", event, 1, shares=10),
        update("E", event, 2, shares=100),  # qualifies, with same-time cancel in its history
        update("A", event + 1, 4, price=1_010_000),  # locked
        update("D", event + 2, 4),  # invalid pre-quote
        status(event + 3, "H"),
        update("A", event + 4, 5, price=1_020_000),  # crossed while halted
        update("D", event + 5, 5),
        update("A", event + 6, 6, side="S", price=1_000_000),  # halted, otherwise qualifies
        status(event + 7, "T"),
        update("D", event + 8, 6),  # resumption cooldown
        update("A", event + 6 * NANOSECONDS, 7, side="S", price=1_009_900),  # below both thresholds
        msg("S", timestamp=event + 7 * NANOSECONDS, code="C"),
    ])
    result = replay(contents, ["--complete", "--validate", "--price-jumps"])
    analysis = result["price_jumps"]
    assert analysis["jump_count"] == 1
    assert analysis["locked_updates"] == 1
    assert analysis["crossed_halted_updates"] == analysis["crossed_halted_locates"] == 1
    jump, = analysis["top"]
    assert jump["frame"] == 8 and jump["timestamp_ns"] == event
    assert jump["symbol"] == "TEST" and jump["message"] == "E" and jump["side"] == "S"
    assert jump["before"]["ask4"] == 1_000_000 and jump["after"]["ask4"] == 1_010_000
    assert jump["before"]["bid_shares"] == 90 and jump["after"]["ask_shares"] == 200
    assert abs(jump["before"]["imbalance"] - (-1 / 19)) < 1e-11
    *previous, partial = jump["preceding_flow"]
    assert all(bucket["last_quote"] is None for bucket in previous)
    assert partial["bid"][1] == [1, 10]  # the earlier frame at the same timestamp
    assert partial["ask"][3] == [0, 0]  # the actual jump trigger is excluded


if __name__ == "__main__":
    main()
