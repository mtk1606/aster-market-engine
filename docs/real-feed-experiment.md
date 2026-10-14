# Reproducing a historical Nasdaq session check

This is a procedure, **not a claim that the project has passed a real Nasdaq session**. At the time of this release, the environment used to build Aster could not retrieve the multi-gigabyte sample and no real-feed verification report has been produced. The independent Python decoder shares the published ITCH field definitions with the C++ implementation, so comparison with a third implementation or vendor checkpoints is still required.

## Choose and record the input

Nasdaq's public [sample directory](https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/) lists `01302019.NASDAQ_ITCH50.gz` (dated January 30, 2019, size listed as 4,764,426,091 compressed bytes) and an associated `.md5sum` sidecar. Confirm that the file remains available and that your use complies with the applicable data terms. The directory listing is not, by itself, an unrestricted redistribution license.

The commands below run on a Linux machine with enough space for **both** the compressed archive and its much larger uncompressed form. Plan for at least 40–60 GB free and check actual requirements before starting. Do not add downloaded sessions to Git.

```bash
mkdir -p "$HOME/itch-data" && cd "$HOME/itch-data"
BASE='https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH'
NAME='01302019.NASDAQ_ITCH50.gz'
curl -fL --retry 3 -C - -o "$NAME" "$BASE/$NAME"
curl -fL --retry 3 -o "$NAME.md5sum" "$BASE/$NAME.md5sum"

# Run these from the Aster repository root, adjusting the paths as needed.
python3 tools/prepare_session.py "$HOME/itch-data/$NAME" \
  --md5-file "$HOME/itch-data/$NAME.md5sum" \
  --output "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --receipt "$HOME/itch-data/receipt.json"
```

If the sidecar download is unavailable, the preparation tool can still calculate SHA-256 for both versions, but the receipt will correctly show `published_md5_verified: false`; do not describe it as source-authenticated. Do not disable failed checks or trim unknown messages to manufacture a pass.

## Replay and cross-check

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel
ctest --test-dir build-release --output-on-failure

python3 tools/verify_session.py "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --binary build-release/aster-replay --independent \
  --checkpoint-interval 1000000 \
  --output "$HOME/itch-data/verification.json"
```

A real recording may reveal feed-specific behavior not represented by the synthetic fixtures. If validation fails, capture the failing **offset and message type** locally, compare the file against the Nasdaq ITCH 5.0 and BinaryFILE specifications, and create a minimal, distribution-safe synthetic regression. Leave the full source recording private. The independent Python replay of hundreds of millions of messages can take substantially longer and use more memory than the C++ replay.

## Measure parsing and book reconstruction separately

```bash
python3 tools/bench_stages.py "$HOME/itch-data/01302019.NASDAQ_ITCH50" \
  --binary build-release/aster-replay --complete \
  --warmups 1 --repetitions 5 \
  --output "$HOME/itch-data/bench-stages.json"
```

This measures four combinations: `mmap` and buffered `read()`, each with decoding-only and full displayed-book updates. The results include end-to-end replay-loop time, process wall time, CPU time and Linux peak RSS. They **do not** supply isolated per-message p50/p99 latency, exact time spent solely in the book, or throughput claims comparable to QSE without running both engines on the same hardware and event stream.

## Evidence checklist

To close real-feed verification, retain the source listing and download date, vendor checksum/receipt, exact commit, build/compiler/platform, positive and negative reports, and one externally validated book snapshot or independent vendor decoder check. Publish only metadata and reproducible procedures that are permitted by the data license.
