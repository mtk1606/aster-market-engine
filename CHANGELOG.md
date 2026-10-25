# Changelog

## 1.0.0 — 2026-10-25 (portfolio release preparation)

- Package the previously completed offline Nasdaq TotalView-ITCH 5.0 decoding, session auditing and displayed FIFO book engine for a scoped public portfolio release.
- Publish contributor-supplied three-trial measurements for the complete 2019-01-30 session, including raw run samples, throughput, wall time, Linux RSS and limitations.
- Publish exact independent Python/C++ comparison milestones: 20M-frame whole-book prefix, 120M-frame AAPL full-depth snapshot, 300M-frame MSFT full-depth snapshot.
- Document architecture, reproducibility, data rights and unfinished independent/vendor checks.
- No strategy, order-routing, exchange certification or live-feed features added.

## 0.8.3

- Add sampled-stock, later-frame Python reference checking and synthetic tests.
- Add readable progress reporting to the full-session benchmark driver.

## 0.8.2

- Replace repeated global price-level scans in independent Python checkpoint fingerprints with a per-checkpoint locate/side price index; verify hash compatibility against a simpler model.

## 0.8.1

- Accept and count exactly identical stock-directory reannouncements after encountering one in the real 2019-01-30 ITCH recording, while still rejecting conflicting fields.

Earlier engineering changes are documented in Git history.
