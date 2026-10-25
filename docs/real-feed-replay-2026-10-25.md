# Full-session Nasdaq ITCH replay on a local WSL2 host — 2026-10-25

**Status: C++ full-day replay and reader parity passed. Full-day independent Python/book validation is pending.**

This is a record of outputs supplied from a local Ubuntu WSL2 host on October 25, 2026. The multi-gigabyte source recording remains on the contributor's machine; these results were not rerun in the project publishing environment. The market-data bytes are not included or redistributed.

## Recording and provenance

| Field | Value |
| --- | --- |
| Source | Nasdaq sample historical TotalView-ITCH 5.0 archive |
| Session date | 2019-01-30 |
| Archive | `01302019.NASDAQ_ITCH50.gz` |
| Compressed bytes | 4,764,426,091 |
| Uncompressed bytes | 11,245,883,092 |
| Compressed SHA-256 | `8c97b5b13bc451c012c2466fb7e258da134dab29aa47b67fe7b0088c78e870be` |
| Uncompressed SHA-256 | `1d0972ffc25b35902ccc3f9069aae517da56903d5795f872902b8697315f30c3` |
| Published MD5 verified? | No: published sidecar download returned HTTP 404 |
| Compression integrity | Standard gzip extraction completed, SHA-256 receipt generated |
| Engine revision | v0.8.1, `909a118e33120eae1bfdb5d6a842847e7c53e82e` |

The hashes establish consistent identity of the locally used bytes, **not** independently verified Nasdaq authenticity. Source-use and redistribution rights must be assessed separately.

## Local environment

- Intel Core i7-13620H CPU, Ubuntu 24.04 under Windows Subsystem for Linux 2 (WSL2).
- WSL2 reported approximately 7.6 GiB RAM and 2 GiB swap.
- GNU C++ 13.3, CMake Release build; eight CTest suites passed.
- The real session was replayed on the laptop using the `aster-replay` executable. Neither the GPU nor QSE participated in these runs.

## Decoding and C++ replay

All recorded runs consumed 11,245,883,092 source bytes and recognized 368,366,634 ITCH frames.

| Run | Time inside engine (s) | Frames/s | Applied book updates |
| --- | ---: | ---: | ---: |
| Buffered read, decode-only, strict complete audit | 35.647348 | 10,333,633.66 | 0 |
| Buffered read, full replay, validation | 220.829998 | 1,668,100.52 | 363,118,215 |
| `mmap`, full replay, session verifier | 257.499601 | 1,430,551.28 | 363,118,215 |
| Buffered read, full replay, session verifier | 250.193794 | 1,472,330.01 | 363,118,215 |

The last two runs were invoked by `tools/verify_session.py` (without `--independent`). That tool also checked source-file hashes and found `state_equivalent: true`. The standalone full replay and the verification runs are **single measurements**, not controlled speed trials; their timing differences do not establish a faster I/O strategy.

The local session audit reported:

- 8,713 distinct stock locates, 8,714 stock-directory records, and one exactly identical directory reannouncement.
- Six system events, opened and closed session, and zero timestamp regressions.
- 363,118,215 applied order updates, 5,248,419 non-book messages.
- `live_orders: 0`, final digest `cbf29ce484222325`.
- Exit status zero, empty error log, and internal order-book invariant validation passed.

The repeated `R` message was for locate 1335 (`CFG-D`) at byte offset 51,681,596, with earlier matching directory data at byte offset 54,855. v0.8.1 accepts only an identical directory body, preserving rejection of conflicting symbols, locates or other directory fields.

## Reproduction commands

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel 2
ctest --test-dir build-release --output-on-failure

./build-release/aster-replay "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --io read --chunk 65536 --audit --complete --validate \
  > "$HOME/itch-data/full-replay.json"

python3 tools/verify_session.py "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --binary build-release/aster-replay \
  --output "$HOME/itch-data/verification.json"
```

The initial bounded prefix has been cross-checked against the *separate* Python FIFO model without starting an all-day Python replay on a memory-constrained WSL2 instance:

```bash
python3 tools/verify_prefix.py "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --binary build-release/aster-replay --limit 250000 \
  --checkpoint-interval 50000 \
  --output "$HOME/itch-data/prefix-verification.json"
```

This compares intermediate digests and full audit fields on the selected prefix, not on the remaining trading day. Any mismatch should be investigated without weakening input validation.

## Independent Python FIFO validation — initial prefix

After installing the bounded prefix checker from commit `a2f66b50039730c9e784c64e98b6d4158f15c97b`, the contributor ran the first 250,000 frames through both Aster's C++ book and the independent Python decoder/FIFO book. The checker compared book digest, live-order count, checkpoint snapshots (digests/counters), session audit and frame/byte totals.

| Field | Observed local result |
| --- | --- |
| Source size | 11,245,883,092 bytes |
| Prefix frames | 250,000 |
| Prefix bytes | 7,119,580 |
| Prefix SHA-256 | `8b6ce97578b7f48b1fc4719dbbdf9077cc41e64d9b0dec8f2feef2868f2541b4` |
| Checkpoint cadence | 50,000 frames |
| Checkpoint comparisons | 5 |
| `independent_match` | `true` |
| `differences` | `{}` |
| Exit status | 0 |
| C++ prefix replay time | 0.019744 s |

The output was supplied from the contributor's laptop, rather than reproduced in the GitHub CI runners, which do not contain Nasdaq's multi-gigabyte recording. **The comparison covers only the first 250,000 frames** (about 0.068% of the 368,366,634-frame session). It does not yet exercise most of the trading day or establish full-session independent correctness.

The subsequent 2,000,000-frame run has now passed as recorded below. Measure memory use before substantially increasing Python coverage.

## Independent Python FIFO validation — 2-million-frame prefix

On the same laptop, the contributor extended `tools/verify_prefix.py` from 250,000 to 2,000,000 input messages. The second comparison passed **all ten checkpoints** against the independently implemented Python decoder and FIFO book. C++ and Python agreed on frames, bytes consumed, update counts, live orders, book digest, checkpoints and complete *prefix* audit state.

| Field | Observed local result |
| --- | --- |
| Input frames compared | 2,000,000 |
| Prefix bytes consumed | 58,039,979 |
| Checked-prefix SHA-256 | `2aff5da8688f2c53790589efe6bfb8e09f679c60cb517baf0221610c2c8686e9` |
| Checkpoint interval | 200,000 frames |
| Checkpoints matched | 10 of 10 |
| `independent_match` | `true` |
| `differences` | `{}` |
| Exit status | 0 |
| C++ bounded replay time (not Python time) | 0.276063 seconds |

The checked byte range extends beyond the identical `CFG-D` directory reannouncement at byte 51,681,596. Consequently, **both the C++ validator and the independent Python validator accepted that real reannouncement consistently**, in addition to comparing live book states. The 2-million-frame prefix represents about 0.54% of the full recording's 368,366,634 frames. Full-day independent correctness, vendor MD5 validation and externally checked snapshots remain outstanding.

The subsequent 5,000,000-frame prefix comparison has now passed as recorded below. A longer contiguous prefix does not give independent coverage of later-day messages; additional sampled windows or a resource-managed full-day reference run would be needed.

## Independent Python FIFO validation — 5-million-frame prefix

A further laptop run used `tools/verify_prefix.py` with `--limit 5000000` and `--checkpoint-interval 1000000`, wrapped in GNU `/usr/bin/time -v` to record resource usage. The contributor's terminal output recorded:

| Field | Observed local result |
| --- | --- |
| Input frames compared | 5,000,000 |
| Prefix bytes consumed | 145,785,783 |
| Checked-prefix SHA-256 | `f4c8718b67e763f1e480881c6a8dc587ad67b0129bba0f5519c1c7914fdd779e` |
| Checkpoint interval | 1,000,000 frames |
| Matched intermediate checkpoints | 5 of 5 |
| `independent_match` | `true` |
| `differences` | `{}` |
| Exit status | 0 |
| C++ bounded prefix replay time | 0.69409 seconds |
| Whole checker wall time (`/usr/bin/time`) | 18.71 seconds |
| User CPU time | 18.06 seconds |
| Maximum reported resident set size | 36,172 KiB (~35.3 MiB) |

The 5-million-message prefix amounts to approximately 1.36% of the complete historical recording. The GNU time RSS figure covers the timed process, and is **not a direct peak-memory measurement of every process that may be spawned** by the checker or of the entire full-day C++ replay. Memory may increase as more orders are simultaneously live in later portions of the session.

To extend this test, use a 20-million-frame prefix with checkpoints every 2 million messages and measure resources again. The remaining day still requires independently checked later-session states or a complete independent reference pass before full-day correctness claims are justified.

## Reference replay performance investigation — later prefix

After the five-million-message success, a 20-million-frame independent prefix run was still active after approximately 34 minutes. A process diagnostic showed Python at about 102% CPU and 818 MiB resident memory, while 6.3 GiB system memory remained available, swap use was negligible, and reported memory pressure was zero. This is consistent with a CPU-bound reference-comparison bottleneck, not system-memory exhaustion.

Inspection found that the original Python reference digest scanned all global price levels once **per active stock locate** at each intermediate checkpoint. The v0.8.2 implementation creates a temporary `(locate, side)` price index for each checkpoint and retains the original canonical hash ordering. A dedicated scan-based regression test protects digest semantics. The 20-million-message attempt has **not** produced a passing report and cannot be cited as independently validated. Retry with a smaller incremental comparison before a larger run.

## Independent Python FIFO validation — 10-million-frame prefix (v0.8.2)

Following the Python reference digest optimization in commit `42ee22978d81474fb27bad27d7905ea65ffc05d8`, the contributor reran a bounded independent comparison on the same WSL2 laptop. All nine local test suites passed. The independent C++/Python prefix replay completed successfully and matched all five intermediate checkpoints.

| Field | Observed local result |
| --- | --- |
| Messages compared | 10,000,000 |
| Prefix bytes consumed | 314,608,616 |
| Prefix SHA-256 | `efdee1d09985f03297f07a5cb294ac4308484c14b4a77ae323518a31cb9db246` |
| Checkpoint interval | 2,000,000 messages |
| Checkpoints matched | 5 of 5 |
| `independent_match` | `true` |
| `differences` | `{}` |
| Exit status | 0 |
| C++ bounded replay elapsed (reported by checker) | 1.986348 s |
| Whole verification wall time (GNU time) | 24.18 s |
| User CPU time | 24.17 s |
| Maximum resident set size reported by GNU time | 230,296 KiB (~224.9 MiB) |

The checked prefix spans approximately 2.71% of all 368,366,634 frames. The GNU-time peak RSS refers to the measured Python checker process and does not establish peak C++ child-process memory. This run completed comfortably within a 600-second timeout, versus a **different-sized** pre-optimization 20-million-frame run still active after 34 minutes. These observations are consistent with an effective optimization, but are not a controlled same-input before/after speedup measurement.

The v0.8.2 optimized 20-million-frame rerun has since passed all ten independent checkpoints (details below). Prefix-only verification still leaves later-day intermediate order states unchecked.

## Independent Python FIFO validation — 20-million-frame prefix (v0.8.2)

The repeated bounded verification on the same WSL2 host completed with exit code 0 and all ten C++/Python checkpoints equal, following the earlier unsuccessful, CPU-bound run with the pre-optimization Python hash routine. The comparator reported `differences: {}` and `independent_match: true`.

| Field | Observed local result |
| --- | --- |
| Frames independently compared | 20,000,000 |
| Source bytes consumed by prefix | 637,953,260 |
| Prefix SHA-256 | `e24c84422e4b891bab714e89f935a82078f2bdf9e4f59cc023097bbcedee7ddb` |
| Checkpoint interval | 2,000,000 frames |
| Matching checkpoints | 10/10 |
| `independent_match` | `true` |
| `differences` | `{}` |
| Exit code | 0 |
| C++ bounded replay time | 8.309412 seconds |
| Full Python checker wall time (GNU `time`) | 97.35 seconds |
| Python checker user CPU time | 95.62 seconds |
| Maximum reported resident set size | 909,636 KiB (~888.3 MiB) |

This validates **the first 20 million frames (approximately 5.43% of this session)**, not arbitrary middle- or late-day order-book snapshots and not a full-session independent replay. The 97.35-second completion versus the earlier pre-optimization run still active after 34 minutes demonstrates markedly lower time-to-completion for the optimized reference in this setup, but the interrupted earlier run prevents computing an exact before/after speedup.

## Follow-on later-session methodology (v0.8.3)

A new `tools/verify_symbol.py` utility is available to sample live book state
at later frame boundaries without holding every listed company's resting
orders in Python memory. It streams **all frames from the start**, retains
only the selected stock's FIFO book, and compares the exact full-depth book
and selected-stock fingerprint against a validated C++ full-multi-stock replay
at the same frame. The first independent later-frame stock snapshot (AAPL at frame 120 million) has now passed, as recorded below. Sampled-stock agreement cannot prove full-day agreement for every security.

## Independent later-frame AAPL snapshot — 120-million-frame prefix (v0.8.3)

The contributor successfully executed `tools/verify_symbol.py` using `--symbol AAPL --limit 120000000` against the same uncompressed January 30, 2019 Nasdaq recording. The checker streamed every preceding message from the beginning, reconstructed AAPL's displayed FIFO book independently in Python, and compared its **exact full-depth snapshot** and stock-locate fingerprint with C++ after Aster had validated/replayed all symbols through the requested frame. The laptop also passed 10 of 10 local CTest suites.

| Field | Observed local result |
| --- | --- |
| Symbol / stock locate | `AAPL` / `14` |
| Frames traversed | 120,000,000 (32.58% of the 368,366,634-frame session) |
| Prefix bytes consumed | 3,671,028,994 |
| Prefix SHA-256 | `789e93d3811ad49e739cc16ccf055062183d0b470780fd3cf51ced85b886c529` |
| Independently reconstructed AAPL updates | 633,089 |
| AAPL resting orders at checkpoint | 39,826 |
| AAPL locate FIFO digest | `dcba309e8f6147c` |
| `snapshot_matched` | `true` |
| `independent_match` | `true` |
| `differences` | `[]` |
| Exit status | 0 |
| C++ bounded replay time | 69.750124 seconds |
| Full verifier elapsed wall time | 2:11.64 (131.64 seconds) |
| Measured peak resident set size | 315,652 KiB (308.3 MiB) |

**Scope:** AAPL's full visible resting queue and fingerprint agree at this frame, with all AAPL events from the start incorporated. The other stocks were replayed and internally validated in C++ but **not** independently reconstructed by Python. This is a sampled stock/state comparison, not independent whole-market correctness at frame 120 million. No vendor-authenticated MD5 or third-party book snapshot was used.

For a first public v1.0 portfolio milestone, the remaining work is to cross-check additional symbols and a later frame, collect controlled performance/memory measurements, and publish a reproducible and accurately scoped case study. A full-day independent all-symbol oracle and external vendor snapshots remain follow-on research work, not claims of this release.

## Interpretation and remaining checks

- Both C++ readers use the **same decoder and book implementation**. Agreement proves I/O path consistency on this recording but **not** correctness against an independent full-day oracle.
- The final order book is empty, so the identical final FNV digest alone carries little evidence about intermediate FIFO correctness. Intermediate checkpoints are essential.
- A vendor-published checksum has **not** been matched, and no externally sourced book snapshot has been validated.
- Throughput covers the **entire file-processing/replay loop**, not the isolated book update cost or message latency percentiles.
- The separate authorized Aster/QSE synthetic add/delete microbenchmark must **not** be described as a comparison of real Nasdaq-feed end-to-end systems.
- Peak replay-process RSS was not collected in this run; post-run `free -h` is not peak-process memory.

The next acceptance goals are selected-symbol independent snapshots at later session frames (using `tools/verify_symbol.py`), broader book and venue-specific spot checks, a full-day independent replay when practical, and third-party/vendor verification.
