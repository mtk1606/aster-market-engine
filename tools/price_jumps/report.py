"""Render the derived replay summary as Markdown, leaving the JSON local."""

import argparse
import json
from collections import Counter
from pathlib import Path

FLOW_TYPES = ("add", "cancel", "delete", "execute", "replace out", "replace in")


def clock(nanoseconds):
    second, fraction = divmod(nanoseconds, 10**9)
    hour, remainder = divmod(second, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}.{fraction:09d}"


def near_touch(quote):
    bid, ask = quote["bid4"], quote["ask4"]
    mid = (bid + ask) / 20_000
    return f"{bid / 10_000:.4f} / {ask / 10_000:.4f} ({mid:.5f})"


def flow_window(jump):
    entries = []
    for side in ("bid", "ask"):
        counts = [
            sum(bucket[side][i][0] for bucket in jump["preceding_flow"])
            for i in range(len(FLOW_TYPES))
        ]
        entries.append("/".join(str(count) for count in counts))
    return " · ".join(entries)


def render(receipt, rows):
    analysis = receipt["price_jumps"]
    print(f"- Replay consumed **{receipt['frames']:,} frames** and "
          f"**{receipt['bytes_consumed']:,} bytes**, with "
          f"**{receipt['applied']:,} displayed-book updates**.")
    print(f"- **{analysis['jump_count']:,} jumps** among "
          f"**{analysis['eligible_updates']:,} eligible updates**.")
    print(f"- **{analysis['crossed_updates']:,}** post-update crossed observations across "
          f"**{analysis['crossed_locates']:,} locates** and "
          f"**{analysis['locked_updates']:,}** locked observations. Of the crossed observations, "
          f"**{analysis['crossed_nontrading_updates']:,}** across "
          f"**{analysis['crossed_nontrading_locates']:,} locates** were outside trading state "
          f"`T`, including **{analysis['crossed_halted_updates']:,}** in state `H` across "
          f"**{analysis['crossed_halted_locates']:,} locates**.")
    print()
    top = analysis["top"][:rows]
    if not top:
        return
    print("| Stock | Time ET | Frame | Δ bps | Bid / ask (mid) before | Bid / ask (mid) after |")
    print("|---|---|---:|---:|---|---|")
    for jump in top:
        print(f"| {jump['symbol']} | {clock(jump['timestamp_ns'])} | {jump['frame']:,} | "
              f"{jump['bps']:+.2f} | {near_touch(jump['before'])} | "
              f"{near_touch(jump['after'])} |")
    print()
    print("Flow counts are bid side · ask side. Each side is in the order "
          + ", ".join(FLOW_TYPES) + ".")
    print()
    print("| Stock / frame | Trigger | Bid / ask shares before | Imbalance before | Flow counts |")
    print("|---|---|---:|---:|---|")
    for jump in top:
        before = jump["before"]
        print(f"| {jump['symbol']} / {jump['frame']:,} | {jump['message']}/{jump['side']} | "
              f"{before['bid_shares']:,} / {before['ask_shares']:,} | "
              f"{before['imbalance']:+.3f} | {flow_window(jump)} |")
    print()
    counts = Counter(jump["message"] for jump in analysis["top"])
    print("Trigger types across the retained set are "
          + ", ".join(f"{count} `{kind}`" for kind, count in sorted(counts.items())) + ".")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--rows", type=int, default=5, choices=range(1, 21), metavar="1–20")
    args = parser.parse_args()
    with args.receipt.open(encoding="utf-8") as source:
        render(json.load(source), args.rows)


if __name__ == "__main__":
    main()
