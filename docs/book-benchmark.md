# Synthetic order-book kernel: measured baseline

The first pinned comparison workload is **Aster-only**. It does not benchmark QSE and does not include binary ITCH parsing. See [comparison protocol](qse-comparison.md) for exact semantics and limitations.

- Generated operations: **200,000** (adds and full deletes only)
- Target simultaneous resting depth: **1,024** orders; final live orders: **1,024**
- Seed: `6007`; workload SHA-256: `d0d67f481d362507b6eca59a25aa48b3e0c5c01a8dcf6f20705269c704690689`
- CPU architecture: `x86_64`; system: `Linux-6.18.44-x86_64-with-glibc2.41`
- Binary SHA-256: `73416d02c0027e1cc615183408fa713b8dbfc22f040eeacc9de49752839480b8`
- One warmup, five measured runs, distinct process each time.
- Median measured book loop: **12,397,614 operations/second** (**81 ns/operation** amortized)
- Final FIFO state hash: `5d4a9d95742a6a77` — matches the independent reference model.
- Maximum observed child process RSS: **98,848 KiB**; not an incremental allocation measurement.

Measured runs:

- 11,638,046 operations/s (0.017185s kernel)
- 12,706,080 operations/s (0.015740s kernel)
- 12,397,614 operations/s (0.016132s kernel)
- 12,680,939 operations/s (0.015772s kernel)
- 10,718,003 operations/s (0.018660s kernel)

Command:

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j
python3 tools/compare_books.py --aster build-release/aster-book-bench \
  --operations 200000 --depth 1024 --seed 6007 \
  --warmups 1 --repetitions 5 --output book-report.json
```

The elapsed time excludes workload file parsing and the final full-depth correctness scan. It includes Aster's `Book::apply` dispatch and ordered-container operations. It is a single-threaded in-memory test in a virtualized container, not live-market throughput. Values fluctuate with host scheduling and warm-up. We have **no QSE result** to compare against and therefore make no speedup claim.
