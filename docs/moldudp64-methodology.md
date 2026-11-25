# Aster MoldUDP64 multicast replay methodology

The experiment models a recorded market-data publisher, an IPv4 multicast feed and a recording client with sequence recovery. The completed recording feeds Aster's offline ITCH 5.0 decoder and displayed-book reconstruction. The reference application is a lab feed replay and capture harness for testing an order-book consumer. A comparison with a particular vendor ticker plant would require choosing that product, its configuration and equivalent measurement boundaries.

## Reproduce on Linux

Use Linux with IPv4 multicast on the loopback interface, Python 3.10 or newer, CMake 3.20 or newer and a C++20 compiler. From the repository root:

```sh
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel 2
ctest --test-dir build-release --output-on-failure
python3 tools/moldudp64/test_protocol.py
python3 tools/moldudp64/demo.py build-release/aster-replay
```

The demo generates six fictional Add Order messages in a temporary directory. It starts two receivers and waits for both to join `239.192.0.64` on `127.0.0.1`. The demo chooses unused UDP ports for multicast and unicast repair. Three data packets carry sequences 1–2, 3–4 and 5–6. The sender skips the first packet and sends the third before the second. Each receiver must recover two messages by unicast, observe one out-of-order multicast packet and finish with zero missing messages. It verifies BinaryFILE byte equality and compares the complete Aster result, excluding elapsed time and derived rate. Both books must contain six live orders, with a best bid of 10006 in ITCH price units and six shares at that price.

A second demo run skips the final data packet with repair disabled. The end-of-session packet makes those two missing messages visible. The demo verifies that the receiver returns an error and preserves an existing output file. The script exits zero only if both scenarios pass. The test fixtures are constructed in source.

## Replay a local recording

Use an uncompressed, legally obtained TotalView-ITCH 5.0 BinaryFILE recording. Start a receiver first and wait for `READY` on stderr. Additional receivers use the same group, port and session, with distinct output filenames. The commands below show a bounded prefix and use the default session `ASTERDEMO1`, multicast endpoint `239.192.0.64:31640` and loopback repair endpoint `127.0.0.1:31641`.

```sh
# Terminal 1
python3 tools/moldudp64/replay.py receive /tmp/aster-recovered.itch \
  --request-host 127.0.0.1
```

```sh
# Terminal 2, after READY
python3 tools/moldudp64/replay.py send /path/to/day.itch --limit 10000
```

```sh
# After the receiver reports completion
build-release/aster-replay /tmp/aster-recovered.itch --io read --validate
```

An uncapped run reads until EOF. For a verified complete trading day, add Aster's `--audit --complete` options. An end-of-session packet in this harness marks the end of the selected replay, which can be only a prefix of the original trading session. Keep captures and raw feed files outside the repository.

For an isolated LAN, set `--interface` to each machine's local IPv4 address and point each receiver's `--request-host` at the sender interface address. Use the same `--group`, `--port`, `--request-port` and `--session` across processes. Multicast TTL is one. Run a single sender per group, port and session, and use a different ten-character session for each concurrent experiment. The repair socket binds only the sender's selected IPv4 address. Keep this unauthenticated lab service on loopback or a trusted isolated network.

## Framing, recovery and output

The [Nasdaq MoldUDP64 protocol specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/moldudp64.pdf) defines the downstream and rerequest layouts. Each downstream UDP payload contains a ten-byte session, an eight-byte big-endian first sequence and a two-byte big-endian message count. Each message has a two-byte big-endian body length. Sequences start at one in this harness and advance per message. The sender emits an initial heartbeat with count zero and repeats a count-65535 end marker during its repair grace period. Both control packets advertise the next sequence. Packetization preserves recorded payloads and order, with a 1400-byte UDP payload budget and a 1 ms inter-packet pause by default. It uses fixed local pacing and has no recorded inter-arrival timing input.

A receiver waits one retry interval on discovering a gap to allow for packet reordering. It then requests the first missing contiguous range over a separate unicast socket, retrying after 50 ms by default. Responses carry as many consecutive cached messages as fit one packet. Subsequent requests fill the remainder. The sender keeps the most recent 32,768 messages and serves requests for one second after the last data packet by default. Receiver reordering is bounded to a 32,768-message sequence window. Adjust pacing, cache, window, retry interval, timeout and grace with the CLI options for a larger run. A lost range that has rolled out of the cache is unrecoverable in this harness.

The receiver writes only contiguous messages. It publishes the handoff with an atomic rename when it has both a terminal sequence and every preceding message. The output uses Aster's existing BinaryFILE representation, a two-byte big-endian length followed by the ITCH body. A timeout or a sequence window failure returns a nonzero status. A missing terminal packet can leave the true trailing loss unknown.

| JSON field | Meaning |
| --- | --- |
| Sender `multicast_data`, `injected_drops`, `injected_swaps` | Data datagrams sent, intentionally skipped, and swapped pairs. The initial heartbeat and end markers are excluded. |
| Receiver `gap_events`, `first_gap` | Jumps beyond the highest announced sequence so far, with the first gap as a half-open sequence interval. Reordering can produce a gap observation. |
| Receiver `out_of_order_packets`, `duplicate_messages` | Data multicasts whose first sequence is below the highest data end observed so far, and repeated messages across either path. A repeated data multicast can contribute to both. |
| Receiver `messages`, `recovered_messages`, `missing_messages` | Messages written in order, new messages accepted via unicast, and unreceived messages below the highest announced sequence at exit. |
| Receiver `end_sequence`, `complete` | Observed terminal sequence, or null if absent, and whether the stream arrived contiguously through the last data message. |

## Validation and a dedicated follow-up

The functional validation ran inside an x86-64 Linux executor reporting an Intel Xeon Platinum 8573C, Debian 13, Linux 6.18.57, GNU C++ 14.2.0, CMake 4.4.5 and Python 3.12.14. Sender and receivers used the same loopback interface. The skipped and swapped datagrams were software injections in the sender. This topology exercised framing, UDP multicast delivery, unicast recovery, output ordering and Aster book equivalence. It provided no dedicated host, external NIC, hardware timestamps, real trading-day transport run, throughput or latency result. The scenario counts are properties of the synthetic experiment and provide no estimate of natural packet loss.

For a physical-network experiment, use a dedicated sender and receiver on an isolated switch or direct link. Record the exact input SHA-256, commit, sender and receiver commands, CPU and core affinity, OS and kernel, NIC and driver, link speed, switch or direct-link topology, MTU, socket buffer settings and timestamp source. Record run duration and repeat the same load and fault pattern across trials. Report the sender and receiver JSON, any relevant kernel and NIC UDP drop counters and the Aster correctness comparison. Keep configured sender pacing, observed delivery and repair outcomes, and offline book processing as separate measurements. For one-way latency, first establish synchronized clocks and a defined send-to-receive timestamp boundary. Production latency and equivalence to a colocated Nasdaq feed-handler are outside this experiment.
