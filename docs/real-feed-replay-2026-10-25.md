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

Next, cross-check an initial bounded prefix with the *separate* Python FIFO model, without starting an all-day Python replay on a memory-constrained WSL2 instance:

```bash
python3 tools/verify_prefix.py "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --binary build-release/aster-replay --limit 250000 \
  --checkpoint-interval 50000 \
  --output "$HOME/itch-data/prefix-verification.json"
```

This compares intermediate digests and full audit fields on the selected prefix, not on the remaining trading day. Any mismatch should be investigated without weakening input validation.

## Interpretation and remaining checks

- Both C++ readers use the **same decoder and book implementation**. Agreement proves I/O path consistency on this recording but **not** correctness against an independent full-day oracle.
- The final order book is empty, so the identical final FNV digest alone carries little evidence about intermediate FIFO correctness. Intermediate checkpoints are essential.
- A vendor-published checksum has **not** been matched, and no externally sourced book snapshot has been validated.
- Throughput covers the **entire file-processing/replay loop**, not the isolated book update cost or message latency percentiles.
- The separate authorized Aster/QSE synthetic add/delete microbenchmark must **not** be described as a comparison of real Nasdaq-feed end-to-end systems.
- Peak replay-process RSS was not collected in this run; post-run `free -h` is not peak-process memory.

The next acceptance goals are prefix/reference matches at multiple checkpoints, wider representative windows under measured memory constraints, a full-day independent replay when practical, and third-party/vendor spot checks.
