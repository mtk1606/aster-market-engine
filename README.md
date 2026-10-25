# Aster Market Engine

A C++20 market-data replay engine built around Nasdaq TotalView-ITCH 5.0. It reads historical messages, applies order updates to a full-depth limit order book, and makes the resulting state inspectable.

I started with the feed and the book rather than the trading strategy. If the parser misses a boundary, or a cancel silently changes the wrong order, everything built on top of that data is suspect. This repository is an attempt to make those failures visible and testable before adding execution research.

**Status:** v0.8.3, offline research software. It does not connect to an exchange, place orders, model hidden liquidity, or infer the true queue position of a hypothetical order.

## What works today

- **ITCH framing and decoding.** Reads the two-byte length prefixes used by common historical ITCH files. Decodes adds (`A`, `F`), executions (`E`, `C`), cancels (`X`), deletes (`D`), and replacements (`U`). Checks known message lengths and stops on malformed input instead of guessing the next boundary.
- **Full-depth displayed book.** Tracks bid/ask price levels, remaining size, and order references for multiple stock locates. Within each level, orders stay in observed FIFO order; partial reductions retain priority, and replacements join at the back.
- **Two file readers.** A read-only `mmap` path and a bounded `read()` path that handles records split between chunks. Both feed the same message decoder and book implementation.
- **Inspecting state.** Emits JSON counters, top-of-book quotes, optional full-depth snapshots, and a deterministic digest of the final live book. A non-mutating depth walk estimates the displayed average price for a requested quantity.
- **Session-level validation.** Uses stock-directory messages to resolve session-specific locates, checks the stock field against the directory for new orders, recognizes opening/closing system events, audits per-type totals and timestamp regressions, and can require a complete day. Identical stock-directory reannouncements are accepted and counted; conflicting mappings or reference-data fields still fail. An optional two-byte BinaryFILE terminator is supported in complete-session mode.
- **Independent replay cross-check.** A separate Python decoder and `OrderedDict` FIFO book produce intermediate checkpoints, per-locate book fingerprints, and full-depth symbol snapshots. Both C++ I/O paths must agree with it. A mismatched stock book is now identifiable without dumping the entire book.
- **Tests that compare behavior, not just exit codes.** C++ unit tests, seeded randomized sequences checked against a separate Python book model, and an acceptance/rejection matrix exercised against both C++ readers and the Python decoder. Clang fuzz targets are included for the framing and book mutation surfaces.

This is *displayed-book reconstruction*, not a complete exchange simulator. Non-book messages are checked for structure but do not update trade statistics. ITCH file framing alone cannot establish network-level sequence continuity.

## Full-session benchmark and source verification

For a published Nasdaq sample session, see [real-feed procedure](docs/real-feed-experiment.md) and the [October 25, 2026 local replay report](docs/real-feed-replay-2026-10-25.md). `tools/prepare_session.py` validates the compressed archive against an optional vendor MD5 sidecar and writes a SHA-256 receipt for its uncompressed bytes. On a contributor's WSL2 machine, v0.8.1 decoded and replayed the complete January 30, 2019 recording, and `mmap` and buffered `read()` agreed. **This does not establish independent full-day book correctness**: the Python oracle has yet to process that recording; the vendor MD5 sidecar was unavailable.

To check real-message FIFO state without loading a full-day Python book into limited RAM, `tools/verify_prefix.py` compares a bounded number of real input messages at intermediate checkpoints against the independent Python model. It does not validate the rest of the day. The Python fingerprint routine groups price levels once per checkpoint, with canonical ordering checked against a simple scan-based reference. For later trading periods, `tools/verify_symbol.py` independently reconstructs one selected stock from frame one to a requested checkpoint and compares its full-depth FIFO queues with the C++ engine, without retaining other stocks in Python. It cannot independently certify unselected stocks. To distinguish basic field decoding from full FIFO reconstruction, `aster-replay --decode-only` checks every record and can still audit the session without mutating the book. `tools/bench_stages.py` compares the decode and full-replay pipelines using both input readers. It alternates experiment order, records input and executable hashes, reports process CPU and peak memory, and refuses inconsistent replays. On a genuine file:

```bash
python3 tools/bench_stages.py /path/to/uncompressed.itch \
  --binary build/aster-replay --complete --repetitions 5 --output bench.json
```

The measured difference is **not** an isolated book-update latency distribution. See [QSE comparison requirements](docs/qse-comparison.md). A separate, authorized QSE build has now been benchmarked on the common add/delete contract; these figures do not compare full market-data or strategy-engine capability.

## Reproducible book-only comparison protocol

There is now a separately timed add/delete book-kernel path (`aster-book-bench`) and an independent Python reference for exact FIFO state. This makes it possible to check a common operation workload without confusing Aster's ITCH decoding with another project's strategy engine:

```bash
python3 tools/compare_books.py --aster build/aster-book-bench \
  --operations 200000 --depth 1024 --repetitions 5
```

The supplied QSE source has a restrictive license; an authorized local build was used for a narrow, book-only comparison. **No QSE implementation or binary is included here.** The independent adapter in `bench/qse_book_driver.cpp` is compiled by an authorized user against their own QSE checkout. Aster and QSE matched the Python FIFO oracle on the measured input. See the [QSE comparison report](docs/qse-book-comparison-2026-10-14.md), [methodology](docs/qse-comparison.md), and the original [Aster-only baseline](docs/book-benchmark.md) before quoting performance.

## Build and run

Requirements: Linux, CMake 3.20+, a C++20 compiler, and Python 3 for integration tests.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
```

Replay an **uncompressed**, legally obtained historical ITCH file:

```bash
# Replay everything and check final book invariants
./build/aster-replay /path/to/session.itch --validate

# Inspect one stock locate and estimate a displayed-depth buy of 1,000 shares
./build/aster-replay /path/to/session.itch --locate 14 --walk B 1000 --snapshot

# Same replay through bounded reads, with an intentionally small chunk
./build/aster-replay /path/to/session.itch --io read --chunk 4096 --locate 14
```

Audit session boundaries and resolve a symbol from the file's own stock directory:

```bash
./build/aster-replay /path/to/session.itch --audit --complete --symbol AAPL --snapshot
python3 tools/verify_session.py /path/to/session.itch --binary build/aster-replay --output report.json
```

For a stronger check, run a separate Python replay and compare the state at intermediate checkpoints and for **every nonempty stock locate**:

```bash
python3 tools/verify_session.py /path/to/session.itch \
  --binary build/aster-replay --independent --checkpoint-interval 100000 \
  --symbol AAPL --output session-report.json
```

You can also inspect individual book fingerprints directly with `./build/aster-replay session.itch --locate-digests`. These hashes include price-time priority, not just best bid and ask, and use stock locates from that session. In `--independent` mode the verifier compares this map automatically.

This adds session checks and a source-file SHA-256 to the verification record. It does **not** mean a full real Nasdaq session has already passed independent comparison; that remains a separate acceptance step. The source file stays on your machine. See [session validation](docs/session-validation.md) for strict versus partial-session behavior and [reference validation](docs/reference-validation.md) for what the independent model does and does not establish.

The output is JSON. `bid4` and `ask4` use integer prices scaled by 10,000; `null` means that side has no displayed orders. `--snapshot` includes each price level and its order-reference FIFO. The digest describes the **final book state**, not the history of events that produced it. A depth walk uses visible shares only; it is not a prediction of an actual fill.

You can run the synthetic benchmark without downloading market data:

```bash
python3 tools/benchmark.py build/aster-replay --orders 100000 --repetitions 5
python3 tools/compare_io.py build/aster-replay --orders 100000 --repetitions 5
```

## How the pieces fit together

```text
Historical ITCH file
     |
     +-- mmap ------------------+
     |                          |
     +-- read + carry-over -----+--> frame decoding --> ITCH event decoding
                                                        |
                                                        v
                                             per-symbol FIFO order book
                                                        |
                                             +----------+----------+
                                             |          |          |
                                           quotes    snapshots   checks/digest
```

The core book is single-writer. Message order matters, and parallelizing updates to the same instrument without preserving that order would give a different book. Prices are kept as fixed-point integers rather than floating point. Bad references, duplicate IDs, invalid share reductions, and truncated records fail explicitly.

One deliberate choice: **the two file readers are separate implementations**. That gives the integration tests something real to compare. A common decoder still ensures the book sees identical events regardless of input strategy.

For exact invariants and data ownership rules, see [engineering notes](docs/engineering.md).

## Testing

`ctest` runs the C++ unit tests and Python integration suites, including the independent reference cross-check. The integration suite generates seeded order streams, applies them to a separate Python reference model, then compares full depth, quantities, FIFO order and the final digest. It also replays the same bytes through both I/O paths at chunk sizes from 1 byte to 64 KiB.

AddressSanitizer/UndefinedBehaviorSanitizer build:

```bash
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug -DASTER_SANITIZE=ON
cmake --build build-asan --parallel
ctest --test-dir build-asan --output-on-failure
```

Fuzzing with Clang:

```bash
cmake -S . -B build-fuzz -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_COMPILER=clang++ -DASTER_SANITIZE=ON -DASTER_FUZZ=ON
cmake --build build-fuzz --parallel
python3 fuzz/generate_seeds.py
./build-fuzz/aster-fuzz-frames -runs=1000 -max_len=4096 fuzz/corpus/frames
./build-fuzz/aster-fuzz-book -runs=1000 -max_len=4096
```

Short fuzz runs are useful smoke tests, not a substitute for longer campaigns or real-feed verification.

## Benchmarks, with context

The existing benchmark is a **synthetic churn test**: 500,000 ITCH-format records covering 100,000 short order lifecycles. A previous five-run test on a virtualized AMD EPYC system measured median rates around **15.5 million frames/s for `mmap`** and **15.9 million frames/s for `read()`**. Those medians are close, and the `read()` runs had a large outlier. I do not consider that evidence that either method is faster.

The workload keeps very few orders resting at once. It is useful for checking replay determinism and getting a baseline, but it is **not** a representative full-session throughput or latency measurement. The raw setup, commands and limitations are in [benchmark notes](docs/benchmarks.md).

## What is still missing

The next work is less about adding features and more about removing uncertainty:

1. Run a complete historical session with appropriate data rights through both engines, resolve any discrepancies, and compare against a separately maintained reference where available. Use the [validation runbook](docs/validation-runbook.md) to keep the evidence reproducible.
2. Extend fuzzing beyond smoke runs; keep minimized failing inputs as permanent regression tests.
3. Measure parser cost, book-update cost, memory use, and event latency separately on realistic book depths.
4. Broaden the authorized book-only QSE comparison to partial cancellations and executions when their semantics align, then separately design the feed-to-research event contract.
5. Only then extend execution simulations with explicit latency, queue uncertainty, and fee assumptions.

Aster was faster on one narrow, synthetic add/delete workload in the first authorized comparison; the result does **not** establish that Aster is faster or more correct than QSE as an overall system. Real-feed replay and execution behavior remain separate acceptance criteria.

## Data and licensing

The message layouts follow Nasdaq's [TotalView-ITCH 5.0 specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf). The two-byte prefix belongs to the historical file's framing, not to the ITCH message itself. No proprietary or licensed market-data recordings are included in this repository. Use your own data in accordance with its license.

MIT license. See [LICENSE](LICENSE).
