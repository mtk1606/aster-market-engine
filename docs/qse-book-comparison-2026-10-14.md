# Aster and QSE: a narrow add/delete comparison

**Measured October 14, 2026.** This is a comparison of two exposed book-update interfaces, not of the full trading systems. A QSE collaborator reported permission to use the supplied code for benchmarking. The copyrighted QSE source and resulting binary are not redistributed here.

## Workload and method

- One instrument; 200,000 reproducible `A id side price4 shares` and `D id` operations (seed `6007`), with 1,024 live resting orders at the end.
- Orders distribute across bid and ask price levels. Deletes remove arbitrary live IDs, not necessarily FIFO heads.
- Both programs use GNU C++ 14.2.0, C++20, `-O3 -DNDEBUG`, on the same Linux x86-64 container reporting an AMD EPYC 9V74 CPU.
- One warmup and five new-process measured runs, alternating engine order.
- Parsing the common workload and checking the final state are **outside** the timed loop. C++ book-update dispatch, QSE string IDs, QSE queue-ID adapter lookup and QSE empty-level cleanup are **inside** the timed loop.
- Both final states matched the independent Python `OrderedDict` oracle: **`5d4a9d95742a6a77`**; all 200,000 operations accepted and 1,024 orders remained. The QSE adapter obtains the actual FIFO contents and quantities from its public consume-at-price API **after timing**; it does not simply hash a shadow copy of input events.

| Metric (median of 5) | Aster | QSE |
| --- | ---: | ---: |
| Operations/second | **12,012,946** | **716,052** |
| Book-loop time for 200,000 operations | **0.01665 s** | **0.27931 s** |
| Measured throughput ratio on this workload | **16.8×** Aster / QSE | — |

Individual observations, workload and executable hashes, and process counters are in the [JSON report](qse-book-comparison-2026-10-14.json). Host scheduling causes visible variation; no confidence interval or p99 claim is made. The reported `ru_maxrss` values are process-level peak RSS observations and do not isolate book allocations.

## Reproduction

Build Aster in the normal manner, then build the independent adapter against an **authorized local QSE checkout**. The QSE source is never copied into this repository.

```bash
QSE_DIR=/absolute/path/to/authorized/QSE-checkout
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel

g++ -std=c++20 -O3 -DNDEBUG -I "$QSE_DIR/include" \
  bench/qse_book_driver.cpp "$QSE_DIR/src/data/OrderBookFullDepth.cpp" \
  -o /tmp/qse-book-bench

python3 tools/compare_books.py \
  --aster build-release/aster-book-bench --qse-driver /tmp/qse-book-bench \
  --operations 200000 --depth 1024 --seed 6007 \
  --warmups 1 --repetitions 5 --output comparison.json
```

## What this does not show

QSE's book models hypothetical strategy orders alongside quote-driven liquidity, while Aster models observed ITCH order references. QSE stores string IDs, and its public cancellation API takes queue IDs, which adds adapter bookkeeping. Its cancellation path searches price levels and adjusts queue positions; Aster maintains a different index. The measured ratio is conditional on those exposed APIs, implementation choices and this add/delete distribution. Other workloads could produce different results.

The comparison **does not** cover binary ITCH decoding, executions, partial reductions, order replacement, queue uncertainty, backtesting, statistical research, p99 latency, or a genuine exchange-data session. It is not evidence that Aster is 16.8× faster than QSE as a product or research platform. Both versions need new tests on the same machine and several realistic event mixes before any broad conclusion.
