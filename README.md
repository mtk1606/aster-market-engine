# Aster Market Engine

**C++20 historical market-data replay and full-depth displayed limit-order-book reconstruction for Nasdaq TotalView-ITCH 5.0.**

Aster converts an uncompressed, BinaryFILE-framed historical ITCH feed into a deterministic price-time FIFO book with per-stock state inspection, session audits and independent Python reference checks. Built as an **offline research and systems-engineering project**: no live connectivity, orders, execution simulation or strategy claims.

**Version:** 1.0.0 — initial, scope-limited portfolio release. Source data is not included.

## Measured real-session results

Aster's full C++ replay processed the **January 30, 2019 Nasdaq TotalView-ITCH** sample: **368,366,634 framed messages**, **11.25 GB** of uncompressed input and **363,118,215 applied displayed-book updates**. Both file readers completed the whole trading day with internal invariant validation and identical result fields.

Three measured full-file passes per pipeline on an **Intel Core i7-13620H / Ubuntu 24.04 WSL2** laptop produced:

| Pipeline | Median end-to-end throughput | Median process wall time | Highest reported RSS |
| --- | ---: | ---: | ---: |
| Buffered `read()` — decode and audit | **7.547M frames/s** | 48.84 s | 26.1 MiB |
| `mmap` — decode and audit | 7.255M frames/s | 51.00 s | 7,166.8 MiB |
| Buffered `read()` — full book replay and validation | **1.341M frames/s** | 275.11 s | **243.0 MiB** |
| `mmap` — full book replay and validation | 1.354M frames/s | 273.02 s | 7,166.2 MiB |

**Interpretation matters:** Rates are whole-file *input frames per second*, not isolated book-update operations or p99 latencies. Linux `mmap` RSS includes resident file-backed mapping pages, not just heap/book memory. The two full-replay reader medians are close and do not establish an I/O winner. Measurements were provided by the contributor and have not been independently rerun in CI.

[All 12 trial measurements and caveats](docs/real-feed-performance-2026-10-25.md) · [Recording provenance and correctness checks](docs/real-feed-replay-2026-10-25.md)

## What has been validated

| Check | Evidence |
| --- | --- |
| Complete historical session | 368,366,634 messages accepted by buffered and mapped C++ replay, with session audit and book invariants |
| Independent multi-symbol reference | First **20 million** real frames matched Python FIFO book at **10 intermediate checkpoints** |
| Independent AAPL full depth | **39,826 live orders**, exact bid/ask price levels and FIFO queue matched at frame **120 million** |
| Independent MSFT full depth | **19,502 live orders**, exact bid/ask price levels and FIFO queue matched at frame **300 million** |
| Automated regression | **10 local CTest suites**, GCC/Clang CI jobs, sanitizer builds and fuzz smoke checks |
| Source identity | Locally computed SHA-256 of uncompressed input `1d0972ffc25b35902ccc3f9069aae517da56903d5795f872902b8697315f30c3` |

**Limits:** C++ reader parity does not independently prove decoder correctness; Python comparison is limited to a prefix and two late-frame selected-stock snapshots. The complete day has **not** passed an independent, all-stock Python replay, and no vendor-certified checksum or external book snapshot has been verified. The project's representation is **visible displayed depth**, not actual exchange queue priority or hidden liquidity.

## How it works

```text
Historical ITCH BinaryFILE recording
     |                                |
     +-- read-only mmap framing       +-- buffered read + split-record carry-over
                   \                  /
                    \                /
                 validated ITCH 5.0 decoder
                         /       \
           session audit        A/F/E/C/X/D/U events
                                |
                        single-writer FIFO book
                                |
                    quotes / depth / snapshots
                    state digests / invariants / JSON

     Separate Python decoder + OrderedDict FIFO reference
                       |
            checkpoint / selected-stock comparison
```

The event index maps order IDs to their stock locate, side, fixed-point price and remaining shares. Each price level maintains observed FIFO order. Partial executions/cancels preserve priority; replacement assigns a new reference and rejoins at the back. Prices use **integer units of 1/10,000** to avoid floating-point ambiguity.

[Architecture walkthrough](docs/architecture.md) · [Engineering decisions](docs/engineering.md)

## Build and test

Requires Linux, CMake 3.20+, a C++20 compiler and Python 3.

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel 2
ctest --test-dir build-release --output-on-failure
```

To replay an **uncompressed**, legally obtained historical ITCH file:

```bash
./build-release/aster-replay /path/to/day.itch \
  --io read --chunk 65536 --audit --complete --validate
```

To inspect full displayed depth for a stock resolved from the session's own directory:

```bash
./build-release/aster-replay /path/to/day.itch \
  --symbol AAPL --snapshot --audit
```

To run an independent *bounded* whole-market check against the Python reference:

```bash
python3 tools/verify_prefix.py /path/to/day.itch \
  --binary build-release/aster-replay \
  --limit 20000000 --checkpoint-interval 2000000
```

To reconstruct one stock independently far later in the session, while reading **from frame one** to preserve its preceding orders:

```bash
python3 tools/verify_symbol.py /path/to/day.itch \
  --binary build-release/aster-replay \
  --symbol MSFT --limit 300000000
```

To reproduce the full-session performance protocol (three measured repetitions for each of four stages, zero warmups; original source file stays local):

```bash
python3 tools/bench_stages.py /path/to/day.itch \
  --binary build-release/aster-replay --complete \
  --warmups 0 --repetitions 3 \
  --output bench-stages.json
```

All test fixtures are synthetic; cloning this repository does not require a Nasdaq download. The Python reference is a separate implementation of the same published message definitions; it cannot act as a vendor certificate.

## Verification and quality

- **Input checks:** strict known-type lengths, malformed/truncated frame errors, exact byte accounting, bounded buffered reads, session start/end checks and stock-directory consistency; exact duplicate directory reannouncements counted separately.
- **Book checks:** unique order references, non-negative remaining depth, correct aggregate sizes and FIFO membership, deterministic full-book and per-locate fingerprints, full-depth snapshots and visible-depth walking.
- **Testing:** randomized independently generated multi-symbol order sequences, separate Python decoder/book, protocol rejection matrix, ASan/UBSan jobs and Clang fuzz smoke runs. Test setup instructions appear in [reference validation](docs/reference-validation.md) and [session validation](docs/session-validation.md).

## Scope, provenance and licensing

Aster is not an exchange interface, backtester, order-placement system, execution simulator or profitability claim. Historical ITCH framing cannot prove network-level sequence continuity. Vendor MD5 authentication for the recorded Nasdaq session remains unavailable; the project publishes locally computed input hashes and precise limitations instead of distributing feed bytes.

A separate authorized Aster-versus-QSE comparison exercises **only** a synthetic, single-instrument add/delete book contract; it is **not** an end-to-end real-feed or product superiority claim. See [the restricted-scope comparison](docs/qse-book-comparison-2026-10-14.md).

Project code: [MIT License](LICENSE). Historical recordings and third-party proprietary QSE sources/binaries are **not** bundled. Use only market data for which you hold appropriate rights.

[Release notes](RELEASE_NOTES.md) · [Changelog](CHANGELOG.md) · [Real-feed reproduction guide](docs/real-feed-experiment.md)
