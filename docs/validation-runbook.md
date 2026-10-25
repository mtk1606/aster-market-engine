# Real-session validation runbook

A passing synthetic test alone is not evidence of conformance to a complete Nasdaq historical feed. A contributor subsequently completed the January 30, 2019 Nasdaq sample through both C++ paths and selected independent Python book comparisons. This document sets out how to **reproduce and extend** that evidence without distributing the recording. See the [real-feed session report](real-feed-replay-2026-10-25.md).

## Data receipt

Record the market date, feed/product name, downloadable framing type, acquisition URL or provider, license or permitted-use terms, compressed and uncompressed sizes, and SHA-256 of the **uncompressed** file. Store the original data outside this repository. Do not publish a proprietary session or excerpts without permission.

## Build and verify

From a clean checkout, record the exact commit, operating system, compiler version, build mode, and Python version. Use the following commands (the file must be uncompressed):

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
python3 tools/verify_session.py /secure/path/session.itch \
  --binary build/aster-replay --output /secure/path/reader-parity.json

# Resource-bounded independent initial-prefix book check
python3 tools/verify_prefix.py /secure/path/session.itch \
  --binary build/aster-replay --limit 20000000 \
  --checkpoint-interval 2000000 --output /secure/path/prefix-reference.json

# Independent single-stock full-depth state at a later frame
python3 tools/verify_symbol.py /secure/path/session.itch \
  --binary build/aster-replay --symbol AAPL --limit 120000000 \
  --output /secure/path/aapl-reference.json
```

If a full-session check fails, preserve the exact byte offset and message type, then inspect that region against the corresponding specification version before relaxing an invariant. Do not discard unmatched order references or invent replacement orders to make the run complete. For a failure that appears only in one reader, use a smaller `--chunk` value to test split framing. For a book-state mismatch, locate the first differing checkpoint and narrow the interval, then inspect the per-locate fingerprints and one full snapshot (`--symbol`).

## Evidence required to close the milestone

- A complete licensed session replayed to the terminator/end with no missing records or unhandled book updates.
- Identical `mmap` and bounded `read()` counters, byte counts, whole-book digest, and per-locate digests.
- Agreement with the separately written Python book on all compared checkpoints and nonempty locates, including handling of corrections/replacements.
- Independent comparison against a **third** feed decoder or vendor/reference snapshots for at least one sampled time window. Python/C++ parity alone can share a specification misunderstanding.
- A reproducible sanitized verification record that contains source hash, commands, software revision, counters, and observed discrepancies, **without** distributing unlicensed feed data.

### What this repository proves today

The initial portfolio v1.0 scope includes the real-feed C++ full-session success, a Python independent whole-book prefix and sampled AAPL/MSFT snapshots, 10 local test suites, and a controlled three-trial performance report. **It does not include** a full-day all-symbol independent reconstruction, a vendor checksum match, a third-party certified book snapshot or a representative end-to-end comparison with QSE. The authorized QSE synthetic book-only experiment is a separate, narrowly scoped benchmark. No source market-data recording is redistributed.
