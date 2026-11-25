# Large displayed midpoint jumps on Nasdaq, January 30, 2019

## Question

What changes in displayed depth immediately before the largest single-update midpoint moves on Nasdaq? The study is motivated by Menkveld, Saru and Yu’s work on price dislocations in EuroSTOXX 50 futures. Here the unit of observation is an update to an individual equity’s Nasdaq book. [When Prices Dislocate](https://albertjmenkveld.com/blog/2025-11-06-price-dislocations/)

## Definition

A jump is a change in the displayed midpoint from immediately before to immediately after a single book update, in ITCH frame order. Its signed size is `10,000 × (mid_after − mid_before) / mid_before` in basis points. Both a **25 bp** absolute move and a **$0.05** absolute midpoint move are required. Updates are counted separately, so several qualifying changes in the same symbol can form one episode. Ranking uses absolute basis points, with earlier feed frames first on ties.

The screen uses **09:35:00 through 15:54:59.999999999 Eastern Time** to avoid the regular opening and closing transitions. It requires a two-sided unlocked, uncrossed quote on both sides of the update, an explicit ITCH trading state `T`, and five seconds since entry into that state. Halted, paused, quote-only and unknown states are excluded, including the first five seconds of trading after resumption. Opening and closing auction prints are outside the displayed-update definition. The rule was fixed before examining the jump output. [Nasdaq TotalView-ITCH 5.0 specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification_5.0.pdf)

## Data and method

Aster reconstructed the complete January 30, 2019 TotalView-ITCH 5.0 sample from the first frame and validated its final book and session lifecycle. The SHA-256 of the decompressed input was `1d0972ffc25b35902ccc3f9069aae517da56903d5795f872902b8697315f30c3`. The screen considered eligible updates across all stock locates in the feed. [Nasdaq sample directory](https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/)

For each of the largest 20 moves, the receipt gives the triggering message, both near-touch quotes, and per-side order-flow counts and shares over the five preceding clock seconds plus the elapsed part of the event’s clock second. The trigger itself is excluded from the flow totals. Earlier frames with the same timestamp are included. The last observed quote in each populated bucket records best bid and ask sizes. Imbalance is `(bid shares − ask shares) / (bid shares + ask shares)` at the best prices. A replacement contributes one removal and one addition on its resting side. `E` and `C` are displayed executions, `X` is a partial cancellation, `D` is a deletion, and `A` and `F` are additions.

## Findings

- Replay consumed **368,366,634 frames** and **11,245,883,092 bytes**, with **363,118,215 displayed-book updates**.
- **3,407,024 jumps** among **332,933,325 eligible updates**.
- **590** post-update crossed observations across **3 locates** and **65** locked observations. Of the crossed observations, **529** across **3 locates** were outside trading state `T`, including **0** in state `H` across **0 locates**.

| Stock | Time ET | Frame | Δ bps | Bid / ask (mid) before | Bid / ask (mid) after |
|---|---|---:|---:|---|---|
| CFFAW | 13:21:09.542261148 | 199,356,838 | -9998.35 | 0.0070 / 6112.1400 (3056.07350) | 0.0070 / 1.0000 (0.50350) |
| ANDAU | 15:14:06.013517986 | 309,337,484 | -9146.03 | 10.0200 / 323.1300 (166.57500) | 10.0200 / 18.4300 (14.22500) |
| ARYAW | 13:28:02.171426021 | 203,204,460 | -9043.14 | 0.4800 / 17.6000 (9.04000) | 0.4800 / 1.2500 (0.86500) |
| CFFA | 13:20:21.766564081 | 198,656,574 | -8807.83 | 9.6100 / 154.8800 (82.24500) | 9.6100 / 10.0000 (9.80500) |
| ALGRR | 10:37:59.539513894 | 85,216,412 | -8300.16 | 0.3010 / 3.9700 (2.13550) | 0.3010 / 0.4250 (0.36300) |

Flow counts are bid side · ask side. Each side is in the order add, cancel, delete, execute, replace out, replace in.

| Stock / frame | Trigger | Bid / ask shares before | Imbalance before | Flow counts |
|---|---|---:|---:|---|
| CFFAW / 199,356,838 | A/S | 200 / 200 | +0.000 | 0/0/0/0/0/0 · 0/0/0/0/0/0 |
| ANDAU / 309,337,484 | F/S | 25,000 / 100 | +0.992 | 1/0/1/0/0/0 · 414/0/417/0/247/247 |
| ARYAW / 203,204,460 | A/S | 100 / 100 | +0.000 | 0/0/0/0/0/0 · 0/0/0/0/0/0 |
| CFFA / 198,656,574 | A/S | 1,000 / 200 | +0.667 | 0/0/0/0/0/0 · 0/0/0/0/0/0 |
| ALGRR / 85,216,412 | F/S | 900 / 100 | +0.800 | 0/0/0/0/0/0 · 0/0/5/0/0/0 |

Trigger types across the retained set are 12 `A`, 7 `F`, 1 `U`.

Nineteen of the 20 largest moves were adds and one was a replacement. The biggest, CFFAW, came from a sell addition that reset the best ask from $6,112.14 to $1.00 while the bid stayed at $0.007. There were no displayed updates for that symbol in the measured pre-event window. For ANDAU, an ask addition also drove the move, after a window with hundreds of ask-side additions, deletions and replacements. These extremes show how a new displayed quote can reset an unusually wide midpoint.

## Limits

This is a one-day, single-venue study of displayed depth. The fixed cutoff can select changes in wide or thin books and the ranking does not require a subsequent trade, persistence or confirmation elsewhere. Repeated jumps can come from the same symbol or episode. Quote transitions and preceding flow describe the visible mechanics of each event. They do not identify motives, participants, hidden liquidity or a causal effect. Existing independent Python checks cover a 20-million-frame prefix and two late, selected-symbol snapshots. The full-day screen uses Aster’s reconstruction.

## Reproduction

From the repo root, with the sample already in ignored `data/`:

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel 2
ctest --test-dir build-release --output-on-failure
sha256sum data/01302019.NASDAQ_ITCH50.gz data/01302019.NASDAQ_ITCH50
tools/price_jumps/run.sh ./build-release/aster-replay \
  data/01302019.NASDAQ_ITCH50 data/price-jumps.json
python3 tools/price_jumps/report.py data/price-jumps.json
python3 tools/price_jumps/report.py data/price-jumps.json --rows 20
```

The same script accepts the original `.gz` and streams the decompressed bytes into Aster. The analysis run used that path to fit the available disk space. To verify the extracted-file hash from the archive alone, run `gzip -dc data/01302019.NASDAQ_ITCH50.gz | sha256sum`. The JSON contains the per-second quote and flow buckets for all retained events. Feed bytes and receipts can stay in `data/`.
