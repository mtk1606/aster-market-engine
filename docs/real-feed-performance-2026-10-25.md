# Real-session replay performance — 2026-10-25

**Aster Market Engine v0.8.3 code, Release build; measured on a contributor's WSL2 laptop.** These observations are real-session measurements, not estimates or single-event latency claims. The underlying multi-gigabyte Nasdaq data remains local and is not distributed. The local source results have been supplied by the contributor, not rerun in public CI.

## Headline result

An entire historical Nasdaq TotalView-ITCH 5.0 session (January 30, 2019) was processed by both file readers with complete-session auditing and full-book invariant checking. The source contained **368,366,634 framed messages** over **11,245,883,092 bytes**. A full replay applied **363,118,215 displayed-book changes**. Across three repeated measurements per pipeline, median full-replay throughput was **1.341 million frames/s via buffered read** and **1.354 million frames/s via mmap**.

Source SHA-256: `1d0972ffc25b35902ccc3f9069aae517da56903d5795f872902b8697315f30c3`.

## Summary — three measured full-file passes per pipeline

| Pipeline | Median engine frames/s | Median process wall seconds | Maximum observed process RSS |
| --- | ---: | ---: | ---: |
| Buffered `read()`, decode only | 7.547 million | 48.84 | 26.1 MiB |
| `mmap`, decode only | 7.255 million | 51.00 | 7,166.8 MiB |
| Buffered `read()`, full replay and validate | 1.341 million | 275.11 | 243.0 MiB |
| `mmap`, full replay and validate | 1.354 million | 273.02 | 7,166.2 MiB |

The per-pipeline median is calculated over three measurements. The benchmark alternates stage order between rounds; there were **no separate warmups**. Decode-only still parses and audits messages but does not mutate the book. Replay invokes `--validate`, which performs an internal full-book invariant check; its cost is included. All four pipeline variants agreed on frame and byte totals; mapped and buffered readers agreed on every checked result field (`read_vs_mmap: true`). All twelve processes exited successfully. Ten local CTest suites also passed before benchmarking.

## All observed trials

These are user-supplied measurements from the benchmark progress log, not invented repetitions. Peak RSS is reported by Linux `wait4` for each child and given in **KiB**.

| Pipeline | Round | Engine seconds | Process wall seconds | Peak RSS (KiB) |
| --- | ---: | ---: | ---: | ---: |
| mmap / decode | 1 | 77.44 | 77.81 | 7,338,752 |
| read / decode | 1 | 48.81 | 48.84 | 26,752 |
| mmap / replay | 1 | 274.85 | 275.84 | 7,338,168 |
| read / replay | 1 | 278.27 | 278.89 | 248,700 |
| read / replay | 2 | 272.73 | 273.25 | 248,700 |
| mmap / replay | 2 | 231.77 | 232.72 | 7,328,824 |
| read / decode | 2 | 50.94 | 50.97 | 26,752 |
| mmap / decode | 2 | 50.13 | 50.40 | 7,329,280 |
| mmap / decode | 3 | 50.77 | 51.00 | 7,328,256 |
| read / decode | 3 | 46.74 | 46.77 | 26,752 |
| mmap / replay | 3 | 272.11 | 273.02 | 7,329,400 |
| read / replay | 3 | 274.60 | 275.11 | 248,832 |

## Interpreting the numbers

- **End-to-end throughput, not book-op nanoseconds:** The measured rate includes file framing, decoding, audit and, in replay mode, displayed-book updates and final invariant checking. It is measured in **input frames**, not just applied book updates. It does not give per-message p50/p95/p99 processing latency.
- **RSS is not allocated book memory:** On Linux, `mmap` brings file-backed pages into the process's resident set. The approximately 7 GiB mapped RSS is substantially influenced by the file mapping/page cache; it does **not** mean the live order book allocated 7 GiB. Buffered `read()` replay observed 243.0 MiB maximum RSS on this host, including runtime, decoder, audit and book.
- **No controlled I/O winner:** Mapped and buffered full-replay median frame rates differ by about one percent, while trials fluctuate substantially. Three runs on a single WSL2 host cannot establish a statistically meaningful winner or general performance ranking.
- **Machine and cache effects:** The host was an Intel Core i7-13620H laptop running Ubuntu 24.04 through WSL2, approximately 7.6 GiB WSL2 RAM and 2 GiB swap. Linux cache state and shared host scheduling were not tightly controlled. The first mapped decode trial (77.81 s) was slower than the subsequent two.
- **No external engine comparison:** The separate Aster/QSE book-only synthetic workload does not measure this file or establish that either engine is superior across their different capabilities.

## Reproduction

Run on a locally licensed **uncompressed** Nasdaq BinaryFILE-framed ITCH 5.0 recording. Do not commit the recording.

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel 2
ctest --test-dir build-release --output-on-failure

python3 tools/bench_stages.py \
  "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --binary build-release/aster-replay \
  --complete --warmups 0 --repetitions 3 \
  --output "$HOME/itch-data/bench-stages-final.json"
```

The script records source and binary SHA-256, process resource samples and distribution summaries in local JSON. It checks replay determinism and reader parity. **This public summary does not include the original complete local JSON report** (which has not been supplied as an artifact); it uses the user's full console trace and printed median values.

## Correctness evidence and caveats

The same recording passed the full-session C++ `read()` and `mmap` validation paths, an independent 20-million-frame full-market prefix comparison, and independent full-depth FIFO snapshots for AAPL at frame 120 million (39,826 live orders) and MSFT at frame 300 million (19,502 live orders). See [the session validation report](real-feed-replay-2026-10-25.md).

The vendor-published MD5 sidecar could not be checked, a full-day **independent** all-symbol replay has not been completed, and no third-party or vendor-supplied book snapshot has been compared. These are deliberately disclosed limitations, not certification claims.
