# Comparing book kernels without changing the question

The QSE archive supplied for this review contains an `OrderBookFullDepth` with price-level FIFO queues, volume accounting, front/back insertion and quote-driven synthetic liquidity. Aster's book stores observed ITCH order references and reconstructs displayed depth. These systems overlap, but they are **not** replacements for one another.

The supplied QSE archive identifies its original copyright holder and carries an **All Rights Reserved** license. A project collaborator has confirmed authorization to benchmark the supplied source. For this report QSE was compiled in a separate, local directory using `bench/qse_book_driver.cpp` as an independently written adapter; no QSE source, binaries, or modified implementation are included in Aster. Anyone reproducing the QSE run needs their own authorized copy.

## Comparable operation subset

To avoid equating a binary decoder with a backtester, `tools/compare_books.py` generates a single-instrument workload containing only:

- `A id side price4 shares` — add one fully displayed resting order to the back of its price-level queue.
- `D id` — delete one complete existing order by its reference ID.

The generator maintains approximately `--depth` outstanding orders after the initial fill, uses multiple bid and ask levels, and selects cancellation victims reproducibly. No partial cancels, executions, replacements, synthetic quotes, strategy signals, network messages, or ITCH framing are part of the timed workload. The price scale is 10,000, and all amounts are integers in the shared protocol.

**Adapter semantics matter:** QSE's public interface uses string order IDs and an allocated queue ID to cancel an order. It also offers a separate `remove_level_if_empty` operation. Any authorized QSE adapter must resolve the original order reference to its queue ID, perform the complete cancellation, clean up empty levels, and exclude parsing/setup/state checks from its timed interval. Aster uses numeric ITCH order references and directly applies the delete event. The wrappers may have different costs, so results describe a common *operation contract*, not identical internals.

## Run the available independent Aster baseline

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel
ctest --test-dir build-release --output-on-failure
python3 tools/compare_books.py --aster build-release/aster-book-bench \
  --operations 200000 --depth 1024 --seed 6007 \
  --warmups 1 --repetitions 5 --output book-report.json
```

The generator writes the same workload every time for the given seed. An independent Python `OrderedDict`-based book calculates the expected full-depth FIFO state, including quantity at each level and order priority. Every executable result must match this reference: exact operation count, live-order count, bid/ask and available shares, and a deterministic FIFO-sensitive `state_hash`. Any mismatch aborts the run instead of creating a plausible speed ratio.

The optional **separately authorized** executable can be compared on exactly the same workload:

```bash
python3 tools/compare_books.py \
  --aster build-release/aster-book-bench \
  --qse-driver /path/to/authorized-qse-book-driver \
  --operations 200000 --depth 1024 --repetitions 5
```

An independently written compatible driver is provided at `bench/qse_book_driver.cpp`. Compile it against an authorized local QSE source checkout; it accepts one positional TSV workload path. Its stdout is one JSON object with `schema: "order-book-comparison-v1"`, `engine: "qse"`, `operations`, `live_orders`, `elapsed_seconds`, `state_hash`, `bid4`, `ask4`, `bid_shares`, and `ask_shares`. `state_hash` uses FNV-1a 64-bit beginning at `14695981039346656037`; mix each field as **8 little-endian bytes**, in this order: for sides `B` then `S`, mix ASCII side and number of nonempty price levels; iterate levels best-price-first and mix price4, aggregate shares, number of queued orders, and then every `(numeric ID, remaining shares)` in FIFO order. QSE adapter code is not bundled here.

## Interpretation

The comparison report contains the workload SHA-256, binary SHA-256 values, machine details, individual process wall/CPU/RSS observations and medians of book-loop throughput. Aster's raw local baseline appears in [book benchmark](book-benchmark.md). This is a CPU-local **add/delete book-kernel microbenchmark**. It is neither a replay of Nasdaq data nor a measurement of strategy behavior or execution realism. It does not establish lower p99 latency, superior backtesting results, or a general speed advantage.

An authorized QSE measurement now exists for the add/delete workload. See [the dated comparison](qse-book-comparison-2026-10-14.md) and [raw results](qse-book-comparison-2026-10-14.json). These results are not a general ranking of the engines: the adapters exercise different internal APIs, the implementation objectives differ, and full market-data reconstruction was not benchmarked against QSE.
