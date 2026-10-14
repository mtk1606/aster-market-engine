# Real-session validation runbook

A passing synthetic test is not evidence of conformance to a complete Nasdaq historical feed. These are the steps I intend to use when I have a full recording that can legally be replayed and its results discussed.

## Data receipt

Record the market date, feed/product name, downloadable framing type, acquisition URL or provider, license or permitted-use terms, compressed and uncompressed sizes, and SHA-256 of the **uncompressed** file. Store the original data outside this repository. Do not publish a proprietary session or excerpts without permission.

## Build and verify

From a clean checkout, record the exact commit, operating system, compiler version, build mode, and Python version. Use the following commands (the file must be uncompressed):

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
python3 tools/verify_session.py /secure/path/session.itch \
  --binary build/aster-replay --independent \
  --checkpoint-interval 1000000 --output /secure/path/validation-report.json
```

If a full-session check fails, preserve the exact byte offset and message type, then inspect that region against the corresponding specification version before relaxing an invariant. Do not discard unmatched order references or invent replacement orders to make the run complete. For a failure that appears only in one reader, use a smaller `--chunk` value to test split framing. For a book-state mismatch, locate the first differing checkpoint and narrow the interval, then inspect the per-locate fingerprints and one full snapshot (`--symbol`).

## Evidence required to close the milestone

- A complete licensed session replayed to the terminator/end with no missing records or unhandled book updates.
- Identical `mmap` and bounded `read()` counters, byte counts, whole-book digest, and per-locate digests.
- Agreement with the separately written Python book on all compared checkpoints and nonempty locates, including handling of corrections/replacements.
- Independent comparison against a **third** feed decoder or vendor/reference snapshots for at least one sampled time window. Python/C++ parity alone can share a specification misunderstanding.
- A reproducible sanitized verification record that contains source hash, commands, software revision, counters, and observed discrepancies, **without** distributing unlicensed feed data.

### What this repository proves today

Version 0.5 ships a synthetic rejection matrix, a differential book fixture with deep resting liquidity, per-locate fingerprints, and file identity guards. No complete Nasdaq session or third-party oracle is included. The QSE source revision is also not available in this repository, so comparative latency, throughput and correctness claims remain out of scope.
