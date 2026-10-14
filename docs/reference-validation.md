# Cross-checking the replay engine

The most useful question for a feed handler isn't whether it finishes a file. It's whether it builds the same book as an implementation that made different choices.

The C++ `mmap` and buffered `read()` paths share a decoder and an order book. Their agreement catches I/O framing mistakes, but neither can catch a shared error in interpreting an ITCH field or maintaining FIFO state. For that reason, there is now a separate Python replay in `tools/reference_replay.py`.

## What is independent

The reference uses `struct.unpack_from`, an explicit wire-length table, a sequential buffered reader, Python dictionaries for live orders, and `OrderedDict` for FIFO priority at each price. Its data structures and update logic do not call into the C++ library. It reconstructs a canonical digest from all currently resting orders, with symbol/side/price/reference/quantity and observed priority in the digest. The digest format intentionally agrees with the C++ output so it can be compared byte for byte.

Both implementations still follow the same ITCH specification and make the same *modeling* choice to reconstruct only visible order messages (`A/F/E/C/X/D/U`). This is an independent implementation check, not independent proof of the exchange's true state or actual execution queue position.

## Run it

Build the project normally, then run:

```bash
python3 tools/verify_session.py /path/to/your.itch \
  --binary build/aster-replay --independent \
  --checkpoint-interval 100000 --symbol AAPL \
  --output session-report.json
```

The `--independent` verifier now compares a separate FIFO-sensitive fingerprint for **every nonempty stock locate** at EOF, in addition to intermediate whole-book checkpoints. This makes a disagreement attributable to a stock locate, without requiring a huge JSON snapshot for every ticker. With `--symbol`, the final full-depth FIFO queue, per-level sizes, and best bid/ask for that ticker are also compared. Stock locates are resolved from the session's `R` messages rather than assumed from an earlier day.

`--checkpoint-interval` produces an ordered list of intermediate state summaries. These checkpoints show *where* two implementations first disagree, rather than only whether their final states match. For a very large feed, a small interval can be expensive: both the C++ and Python implementations walk the entire live book to compute every checkpoint. Choose a longer interval for initial sessions, then narrow a mismatch with a shorter replay. The script also compares total frame counts, applied/ignored records, full-session auditing counters, and exact bytes consumed. A SHA-256 of the source is recorded for repeatability; verification also checks the file hash before and after both replay paths and the independent replay to reject a changing input. This is not a cryptographic signature or protection against adversarial file replacement. Raw feed bytes are never written to the report.

To inspect the separate implementation without invoking C++:

```bash
python3 tools/reference_replay.py /path/to/your.itch --interval 100000 --symbol AAPL
```

Use `--allow-incomplete` in both scripts only when deliberately replaying a fragment or a generated partial fixture. Complete mode requires the exchange's opening and closing system events and nondecreasing ITCH timestamps. No assumption of network packet sequence continuity is possible from a historical BinaryFILE stream alone.

## What has actually been tested

The `aster-independent` test generates three fixed-seed sessions with three symbols each, thousands of live orders, partial executions, cancellations, deletes, price changes, replacements, and unrelated messages. It checks three stock snapshots and two buffered chunk sizes against the independent Python book at every 137 frames and at EOF. Corrupt framing is rejected instead of resynchronized. The `aster-rejection-matrix` suite adds 21 invalid and two valid generated sessions and requires the C++ `mmap`/`read()` readers and Python model to accept or reject the same inputs. The test records no synthetic performance claims.

This is broader than the original short-lifecycle churn benchmark, but it remains generated data. Real Nasdaq historical session validation and a comparison against a separately maintained exchange reference are not complete. The QSE source is also required before a fair QSE-versus-Aster result can be published.

## Failure and scope

- An independent mismatch is fatal and lists the differing fields. The report is not stamped as verified.
- The independent Python model is intentionally slow relative to C++. It is a validation tool, not a throughput baseline.
- The canonical digest is not cryptographic; it is only a deterministic state fingerprint. SHA-256 is reserved for input identity.
- The decoder doesn't infer undelivered packets, hidden liquidity, or true fills, and currently doesn't update market statistics from non-order messages.
- A full day's ITCH recording can be very large. Keep raw sessions out of Git and retain their provenance and license terms alongside local reports.
