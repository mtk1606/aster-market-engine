# QSE comparison: required evidence

The original Quantitative Strategy Engine (QSE) implementation has not been located in the connected source repositories. QSE features described in a career document are not enough to reconstruct an equivalent executable. Aster's synthetic throughput cannot be used to claim a win against it.

## Valid comparison design

Pin **both source revisions** and compiler flags, and run them on the same machine with the same event-ordering semantics, instrument identities, visible FIFO book assumptions and fees/latency settings. Explicitly distinguish:

1. Binary framing and decoding (Aster can now benchmark this with `--decode-only`).
2. Full ITCH decode plus FIFO book update (Aster without `--decode-only`).
3. Equivalent normalized event *book-only* workloads, which require a QSE adapter that uses its existing update path, not an independently reimplemented substitute.
4. Execution model and research outcomes; compare only after matching the assumptions and data sources.

Aster's `tools/bench_stages.py` checks input bytes and reader consistency, but it **cannot** establish (3) or (4) without the original QSE source and an adapter. Raw messages include directory/system events that a QSE normalized book may never consume, so naive messages-per-second comparisons would be misleading. Compare the number of applied book mutations and state snapshots at fixed event numbers, not just wall time.

Capture exact software versions, CPU topology, scaling, turbo/thermal conditions, cache status, thread count, memory limits, samples, warmups, run-to-run spread and raw results. Separate full-run latency from per-event p50/p99 distributions. Report failures and performance regressions.

**Blocking input:** Original QSE source repository or archive and a pinned commit. Until then, no numerical QSE comparison is published.
