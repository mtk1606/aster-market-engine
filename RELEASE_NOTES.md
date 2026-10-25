# Aster Market Engine — v1.0.0

**First portfolio release: reproducible, offline reconstruction of displayed Nasdaq ITCH 5.0 order books.**

The version marks the completion of the **stated engineering project scope**, not exchange certification, trading-system readiness, or comprehensive ITCH semantics beyond the documented displayed-book model.

## Included

- C++20 full-depth price-time FIFO book driven by Nasdaq `A/F/E/C/X/D/U` events, fixed-point prices, order reference checking and non-mutating depth walks.
- Independent `mmap` and bounded buffered `read()` file framing, with common validated ITCH event decoding.
- Stock-directory/session identity auditing, exact duplicate-directory reannouncement handling, system-event checks and complete-session acceptance mode.
- Deterministic book digests, full-depth snapshots, per-locate hashes, invariant checks and structured JSON reports.
- Independent Python decoder and FIFO oracle with bounded prefix checks and late-session selected-symbol comparisons.
- C++/Python tests (10 local CTest suites on the measured commit before release preparations), GitHub CI GCC/Clang with sanitizer configurations, and fuzz smoke tests.
- Real-session replay, sampled independent correctness and three-trial end-to-end performance evidence from a contributor's WSL2 laptop.

## Measured historical session

**2019-01-30 Nasdaq TotalView ITCH:** 368,366,634 messages, 11,245,883,092 bytes, 363,118,215 applied book updates.

Median of three measured full-file passes on an Intel Core i7-13620H WSL2 host:

| Configuration | Median throughput | Median process wall time | Highest reported RSS |
| --- | ---: | ---: | ---: |
| Buffered read, decode | 7.547M frames/s | 48.84 s | 26.1 MiB |
| Mapped, decode | 7.255M frames/s | 51.00 s | 7,166.8 MiB |
| Buffered read, full replay and invariants | 1.341M frames/s | 275.11 s | 243.0 MiB |
| Mapped, full replay and invariants | 1.354M frames/s | 273.02 s | 7,166.2 MiB |

`mmap` RSS includes resident file-backed mapped pages; it is not the size of the live book. Full per-trial measurements and the no-p99 / no-I/O-winner limitations: [docs/real-feed-performance-2026-10-25.md](docs/real-feed-performance-2026-10-25.md).

The complete C++ session passed both readers; the independent Python implementation matched the initial 20-million-message whole-book prefix, full-depth AAPL at frame 120 million and MSFT at frame 300 million. The data archive itself is **not** bundled.

## Boundaries and unresolved work

This engine reconstructs **visible orders only**, not the true exchange queue position, hidden liquidity, matching/execution economics or order entry. C++ reader parity shares a common C++ book; a complete independent all-symbol day has **not** been demonstrated. The official vendor MD5 sidecar could not be retrieved for verification; a third-party certified book snapshot has not been checked. There is no network sequence-gap detection or live-feed transport. Nothing here establishes profitability or production trading safety.

The authorized, synthetic QSE add/delete-only comparison is a separate workload, not a claim of generally better performance.

## Read next

- [README.md](README.md) — scope, build and commands
- [docs/architecture.md](docs/architecture.md) — data flow and structures
- [docs/real-feed-replay-2026-10-25.md](docs/real-feed-replay-2026-10-25.md) — correctness/provenance log
- [docs/real-feed-performance-2026-10-25.md](docs/real-feed-performance-2026-10-25.md) — benchmark measurements and caveats
- [docs/reference-validation.md](docs/reference-validation.md) — independent model and limits

**License:** MIT for this repository. Nasdaq recordings and third-party QSE code are not distributed; users must have their own applicable rights.
