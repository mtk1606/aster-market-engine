"""Linux IPv4 multicast replay CLI. Run with --help for options."""

import argparse
import ipaddress
import json
import math
import os
import select
import socket
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from time import monotonic

from protocol import (
    DEFAULT_GROUP, DEFAULT_INTERFACE, DEFAULT_PAYLOAD, DEFAULT_PORT,
    DEFAULT_REQUEST_PORT, DEFAULT_SESSION, END, HEADER, MAX_UDP_PAYLOAD,
    Assembly, Packet, batches, read_binaryfile, recovery_response, session_bytes,
)


def multicast_sender(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                        socket.inet_aton(args.interface))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    except OSError:
        sock.close()
        raise
    return sock


def multicast_receiver(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((args.group, args.port))
        membership = socket.inet_aton(args.group) + socket.inet_aton(args.interface)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    except OSError:
        sock.close()
        raise
    return sock


def send(args):
    destination = (args.group, args.port)
    cache = OrderedDict()
    stats = dict(messages=0, multicast_data=0, injected_drops=0,
                 injected_swaps=0, repair_requests=0, repair_responses=0)
    held = None

    with (args.input.open("rb") as source, multicast_sender(args) as multicast,
          socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as repair):
        repair.bind((args.interface, args.request_port))

        def transmit(data):
            multicast.sendto(data, destination)
            stats["multicast_data"] += 1

        def serve_until(deadline):
            # Poll once even when unpaced so a busy sender can still serve repairs.
            while True:
                ready, _, _ = select.select([repair], [], [], max(0, deadline - monotonic()))
                if ready:
                    request, peer = repair.recvfrom(MAX_UDP_PAYLOAD)
                    stats["repair_requests"] += 1
                    response = recovery_response(request, args.session, cache, args.payload_bytes)
                    if response is not None:
                        repair.sendto(response, peer)
                        stats["repair_responses"] += 1
                if monotonic() >= deadline:
                    return

        sequence = 1
        multicast.sendto(Packet(args.session, sequence, 0).encode(), destination)
        for messages in batches(read_binaryfile(source, args.limit),
                                args.payload_bytes, args.packet_messages):
            data = Packet(args.session, sequence, len(messages), messages).encode()
            for index, message in enumerate(messages, sequence):
                cache[index] = message
                if len(cache) > args.cache_messages:
                    cache.popitem(last=False)
            stats["messages"] += len(messages)

            if sequence == args.drop_sequence:
                stats["injected_drops"] += 1
            elif held is not None:
                transmit(data)
                transmit(held)
                held = None
                stats["injected_swaps"] += 1
            elif sequence == args.swap_sequence:
                held = data
            else:
                transmit(data)
            sequence += len(messages)
            serve_until(monotonic() + args.packet_interval)

        if held is not None:
            transmit(held)
        if not stats["messages"]:
            raise ValueError("replay input contains no messages")
        if args.drop_sequence and not stats["injected_drops"]:
            raise ValueError("drop sequence did not match a packet start")
        if args.swap_sequence and not stats["injected_swaps"]:
            raise ValueError("swap sequence did not match a packet with a successor")

        terminal = Packet(args.session, sequence, END).encode()
        deadline = monotonic() + args.grace
        while True:
            multicast.sendto(terminal, destination)
            serve_until(min(deadline, monotonic() + 0.1))
            if monotonic() >= deadline:
                break
    print(json.dumps(stats, sort_keys=True))


def receive(args):
    counters = dict(multicast_packets=0, malformed_packets=0, foreign_session_packets=0,
                    repair_requests=0, repair_packets=0)
    # A failed run must not publish an incomplete BinaryFILE handoff.
    temp_path = None
    with (multicast_receiver(args) as multicast,
          socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as repair):
        sockets = [multicast]
        if args.request_host is not None:
            repair.bind((args.interface, 0))
            repair.connect((args.request_host, args.request_port))
            sockets.append(repair)
        try:
            with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as target:
                temp_path = Path(target.name)
                state = Assembly(args.session, target, args.window_messages)
                print("READY", file=sys.stderr, flush=True)
                last_progress = monotonic()
                next_request = last_progress
                while not state.complete:
                    now = monotonic()
                    deadline = last_progress + args.timeout
                    if now >= deadline:
                        raise TimeoutError("waiting for contiguous data or end of session timed out")
                    if len(sockets) == 2 and state.missing:
                        if now >= next_request:
                            try:
                                repair.send(state.request())
                            except ConnectionRefusedError:
                                pass
                            else:
                                counters["repair_requests"] += 1
                            next_request = now + args.retry_interval
                        deadline = min(deadline, next_request)
                    ready, _, _ = select.select(sockets, [], [], max(0, deadline - monotonic()))
                    for sock in ready:
                        try:
                            raw = sock.recv(MAX_UDP_PAYLOAD)
                        except ConnectionRefusedError:
                            # A late ICMP response does not invalidate the multicast stream.
                            continue
                        unicast = sock is repair
                        counters["repair_packets" if unicast else "multicast_packets"] += 1
                        try:
                            packet = Packet.decode(raw)
                        except ValueError:
                            counters["malformed_packets"] += 1
                            continue
                        if packet.session != args.session:
                            counters["foreign_session_packets"] += 1
                            continue
                        progress = state.next_sequence, state.high_water, state.final_sequence
                        had_gap = bool(state.missing)
                        state.ingest(packet, repair=unicast)
                        now = monotonic()
                        if progress != (state.next_sequence, state.high_water, state.final_sequence):
                            last_progress = now
                        if state.missing and not had_gap:
                            # Give a newly observed gap one retry interval to reorder naturally.
                            next_request = now + args.retry_interval
                        if state.complete:
                            break
            os.replace(temp_path, args.output)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
                print(json.dumps(
                    dict(counters, complete=state.complete, messages=state.next_sequence - 1,
                         gap_events=state.gap_events, first_gap=state.first_gap,
                         missing_messages=state.missing, end_sequence=state.final_sequence,
                         out_of_order_packets=state.out_of_order_packets,
                         duplicate_messages=state.duplicate_messages,
                         recovered_messages=state.recovered_messages), sort_keys=True,
                ))


def address(value):
    return str(ipaddress.IPv4Address(value))


def group_address(value):
    if not ipaddress.IPv4Address(value).is_multicast:
        raise ValueError("expected an IPv4 multicast group")
    return value


def integer(minimum, maximum):
    def parse(value):
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"expected an integer in [{minimum}, {maximum}]")
        return number
    return parse


def seconds(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("expected finite nonnegative seconds")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sender = commands.add_parser("send")
    receiver = commands.add_parser("receive")
    for command in (sender, receiver):
        command.add_argument("--group", type=group_address, default=DEFAULT_GROUP)
        command.add_argument("--port", type=integer(1, 65535), default=DEFAULT_PORT)
        command.add_argument("--interface", type=address, default=DEFAULT_INTERFACE)
        command.add_argument("--session", type=session_bytes, default=DEFAULT_SESSION)
        command.add_argument("--request-port", type=integer(1, 65535), default=DEFAULT_REQUEST_PORT)
    sender.add_argument("input", type=Path)
    sender.add_argument("--limit", type=integer(1, (1 << 64) - 2))
    sender.add_argument("--payload-bytes", type=integer(HEADER.size + 3, MAX_UDP_PAYLOAD),
                        default=DEFAULT_PAYLOAD)
    sender.add_argument("--packet-messages", type=integer(1, END - 1), default=END - 1)
    sender.add_argument("--cache-messages", type=integer(1, 1_000_000), default=32768)
    sender.add_argument("--packet-interval", type=seconds, default=0.001)
    sender.add_argument("--grace", type=seconds, default=1.0)
    sender.add_argument("--drop-sequence", type=integer(1, (1 << 64) - 2))
    sender.add_argument("--swap-sequence", type=integer(1, (1 << 64) - 2))
    receiver.add_argument("output", type=Path)
    receiver.add_argument("--request-host", type=address)
    receiver.add_argument("--timeout", type=seconds, default=5.0)
    receiver.add_argument("--retry-interval", type=seconds, default=0.05)
    receiver.add_argument("--window-messages", type=integer(1, 1_000_000), default=32768)
    args = parser.parse_args()
    if args.command == "send" and args.drop_sequence is not None:
        if args.drop_sequence == args.swap_sequence:
            parser.error("drop and swap sequences must differ")
    if args.command == "receive" and (args.timeout <= 0 or args.retry_interval <= 0):
        parser.error("timeout and retry interval must be positive")
    try:
        (send if args.command == "send" else receive)(args)
    except (OSError, ValueError) as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
