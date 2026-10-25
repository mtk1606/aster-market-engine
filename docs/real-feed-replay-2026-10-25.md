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

## Interpretation and remaining checks

- Both C++ readers use the **same decoder and book implementation**. Agreement proves I/O path consistency on this recording but **not** correctness against an independent full-day oracle.
- The final order book is empty, so the identical final FNV digest alone carries little evidence about intermediate FIFO correctness. Intermediate checkpoints are essential.
- A vendor-published checksum has **not** been matched, and no externally sourced book snapshot has been validated.
- Throughput covers the **entire file-processing/replay loop**, not the isolated book update cost or message latency percentiles.
- The separate authorized Aster/QSE synthetic add/delete microbenchmark must **not** be described as a comparison of real Nasdaq-feed end-to-end systems.
- Peak replay-process RSS was not collected in this run; post-run `free -h` is not peak-process memory.

The next acceptance goals are prefix/reference matches at multiple checkpoints, wider representative windows under measured memory constraints, a full-day independent replay when practical, and third-party/vendor spot checks.
