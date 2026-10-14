# Session validation

This is an *offline replay validator*, not a market-data certification tool. The decoder recognizes every ITCH 5.0 message type in the pinned format, but only `A/F/E/C/X/D/U` change the displayed order book. The `R` and `S` messages are used by optional session auditing.

## Checks in v0.3

Run the command on a locally available, uncompressed historical file:

```bash
./build/aster-replay path/to/day.NASDAQ_ITCH50 --audit --complete --validate
python3 tools/verify_session.py path/to/day.NASDAQ_ITCH50 --binary build/aster-replay --output replay-report.json
```

`--audit` maintains the day's map of stock locates to tickers. A ticker is an 8-byte padded stock field; a locate is a *per-session identifier*, not a stable symbol ID. Auditing checks that each stock-directory mapping is unique, that added orders reference a declared locate and the same stock string, and that order updates refer to a declared locate. It records message-type frequencies and counts decreasing timestamps (instead of hiding them).

`--complete` additionally requires `S/O` Start of Messages as the first event, `S/C` End of Messages, and no timestamp regressions. It accepts an *optional trailing 2-byte zero-length BinaryFILE terminator*, but only when it is the last two bytes. Outside `--complete`, a zero-length frame remains an error to preserve strict prefix-replay behavior. `--complete` cannot be combined with `--limit`.

`--symbol AAPL` looks up a ticker from the `R` records in the file and displays its final top of book. It is not equivalent to filtering the feed by a ticker assumed to have a fixed locate across sessions.

The verification script makes a streaming SHA-256 fingerprint of the original file, runs full replay twice (`mmap` and bounded `read()`), runs book invariants, compares non-timing fields, verifies that all bytes were consumed, and emits a JSON report. The two paths share the same decoder and book, so agreement does **not** constitute independent validation of market-data semantics.

### Meaning of a failure

- **Missing directory**: the sample may begin partway through the day, or the file is not a complete native ITCH 5.0 session.
- **Missing start/end event**: intentionally truncated data or a feed delivery variant. Use `--audit` rather than `--complete` for exploratory partial sessions.
- **Timestamp regression**: reported as a count under `--audit` and a hard failure under `--complete`. Investigate against the original feed specification before assuming corruption.
- **Unknown order / quantity mismatch**: may signal incomplete input, incorrectly decoded protocol variants, or a bug in reconstruction. Do not silently repair missing state during validation.
- **Zero-length terminator with following bytes**: invalid trailing framing, rejected by both readers.

## Independent book cross-check

`tools/verify_session.py --independent --checkpoint-interval N` also runs a separately written Python decoder and price-time FIFO book. It checks the C++ intermediate state digests and final result, and can compare a full depth snapshot for one symbol with `--symbol`. This addresses shared state errors that two C++ I/O paths cannot expose. See [reference validation](reference-validation.md) for details and limitations.

## What is still missing

A full historical Nasdaq session has **not** been checked into this repository and is **not** claimed to have been independently validated. Before claiming real-feed conformance, acquire a file with suitable use rights; record its origin, date, format and SHA-256; run the script above; and cross-check a time-window's messages, depth and event counts against an *independently implemented* reference. Do not commit purchased or licensed market-data files to the repository.

Source format: Nasdaq TotalView-ITCH 5.0 specification, at `https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification_5.0.pdf`.
