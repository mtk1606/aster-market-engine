# Design notes

These notes pin down the behavior I expect from the replay engine. They also explain a few choices that can look unusual if you only skim the code.

## The book is an event-ordered data structure

The input is an uncompressed historical ITCH file with two-byte, big-endian record lengths. ITCH defines the messages; the prefix comes from the historical file format. For known types the parser checks exact lengths before reading fields. Unknown or malformed frames stop replay and report their offset. There is no attempt to recover sync by searching ahead for a plausible message type.

The event decoder currently applies Add (`A`, `F`), Execute (`E`, `C`), Cancel (`X`), Delete (`D`) and Replace (`U`) to the displayed book. Administrative messages and separate trade messages do not create displayed orders.

An order reference indexes its stock locate, side, price and remaining shares. Price levels own FIFO lists. A partial cancel or execution leaves the order where it was. A replacement removes the old reference and appends the new reference to the relevant level. The stock-locate identifier is scoped to the feed session; it should not be treated as a permanent ticker mapping.

The book is single-writer by design. Running updates to the same instrument out of order changes queue priority and therefore changes the reconstructed state. Parallelism is only useful once message ordering is preserved explicitly.

## Invariants worth enforcing

- Every live reference is unique, and every queue entry resolves to exactly one live reference.
- An event that mutates an order must match that order's stock locate.
- Shares are positive for live orders. Cancels and executions cannot subtract more than remains.
- Each level's aggregate shares equal the sum of its queue entries.
- An order appears at exactly one level, under its own side and price.
- A digest is computed from a canonical ordering of locates, sides, levels and FIFO entries. It detects many regressions, but it is not a cryptographic proof.
- A depth walk can only use visible liquidity; it returns a partial result if the requested quantity exceeds available depth.

The Python reference book is useful because it doesn't share the C++ map and list implementation. Matching it across randomized tests catches some classes of bug, but two implementations can still agree on the same misunderstanding of the exchange specification. That is why a second real-feed reference remains on the roadmap.

## Two input paths

`mmap` keeps a read-only mapping of the historical file. It is simple to use because a record can be viewed as a continuous slice. The file must not be truncated while mapped. On Linux that can result in `SIGBUS`.

`read()` uses a caller-sized buffer and carries incomplete records into the next chunk. It must distinguish a clean EOF from a partial prefix or incomplete payload. Borrowed frame bytes from this reader are only valid until the next read advances the buffer; the decoder consumes them immediately.

The readers have independent framing code on purpose. They meet at the same ITCH decoder. Tests require identical event counts, exact bytes consumed, top quotes, full depth, FIFO order and errors across chunk sizes, including one-byte chunks.

## What a benchmark needs to say

A fast number without a workload description isn't useful. A replay result should include at least the feed hash or generation seed, compiler and flags, CPU, page-cache assumptions, number of repetitions, frame count, final digest and live-order count. Use Release builds and compare modes on the same input and host.

The churn fixture used by `tools/benchmark.py` is deliberately small in working-set size. Separately, a 368-million-message real-session run now measures decode-only and full-book replay pipelines with end-to-end wall time, CPU and per-process peak RSS; see [the report](real-feed-performance-2026-10-25.md). It does **not** isolate book-event p99 latency, CPU cycles or independently established exchange queue position. Hardware counters and sampled profiles should explain any speed difference.

## Limits of the current model

A historical displayed-order feed does not reveal hidden liquidity, a hypothetical order's actual place in queue or complete exchange matching behavior. The current `walk` is a displayed-depth calculation, not a fill simulator. The project has no live transport, order entry, broker integration or alpha claim.

## Work left to validate

1. Extend the now-completed full C++ session replay and sampled independent AAPL/MSFT checks to third-party/vendor-certified event counts and depth when available.
2. Longer coverage-guided fuzz runs; save and minimize each discovered failure.
3. Representative depth benchmarks with p50/p95/p99 event-processing costs and memory measurements.
4. A stable ITCH-to-QSE event contract and side-by-side deterministic replay.
5. Execution-research assumptions tested under different queue, latency, fee and slippage scenarios.

Better than QSE is a testable claim, not a label: the comparison needs pinned source revisions, equivalent workloads and independent correctness checks.

## Session boundary versus replay boundary

A file can be structurally decodable without being a complete trading session. The `SessionAudit` layer is opt-in to keep the hot book reconstruction path separate from per-day symbol identity. `--complete` enforces the session framing and timestamp-order contract; `--audit` alone is useful on partial sessions. See `docs/session-validation.md` for gaps and interpretation.
