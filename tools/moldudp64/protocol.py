"""MoldUDP64 wire framing and single-session replay state."""

from dataclasses import dataclass
from struct import Struct

HEADER = Struct("!10sQH")
LENGTH = Struct("!H")
END = 0xffff
MAX_SEQUENCE = (1 << 64) - 1
MAX_UDP_PAYLOAD = 65507
DEFAULT_PAYLOAD = 1400
DEFAULT_GROUP = "239.192.0.64"
DEFAULT_PORT = 31640
DEFAULT_REQUEST_PORT = 31641
DEFAULT_INTERFACE = "127.0.0.1"
DEFAULT_SESSION = "ASTERDEMO1"


def session_bytes(value):
    if len(value) != 10 or not value.isascii() or not value.isalnum():
        raise ValueError("session must be exactly 10 ASCII letters or digits")
    return value.encode("ascii")


def block(payload):
    if len(payload) > 65535:
        raise ValueError("message length exceeds 16 bits")
    return LENGTH.pack(len(payload)) + payload


@dataclass(frozen=True)
class Packet:
    session: bytes
    sequence: int
    count: int
    messages: tuple = ()

    def encode(self):
        if len(self.session) != 10 or not 1 <= self.sequence <= MAX_SEQUENCE:
            raise ValueError("invalid downstream header")
        if not 0 <= self.count <= END:
            raise ValueError("invalid downstream count")
        expected = 0 if self.count == END else self.count
        if expected != len(self.messages) or self.sequence + expected > MAX_SEQUENCE:
            raise ValueError("invalid downstream range")
        return HEADER.pack(self.session, self.sequence, self.count) + b"".join(
            block(payload) for payload in self.messages
        )

    @classmethod
    def decode(cls, data):
        if len(data) < HEADER.size:
            raise ValueError("truncated downstream header")
        session, sequence, count = HEADER.unpack_from(data)
        expected = 0 if count == END else count
        if sequence == 0 or sequence + expected > MAX_SEQUENCE:
            raise ValueError("invalid downstream sequence range")
        offset = HEADER.size
        messages = []
        for _ in range(expected):
            if offset + LENGTH.size > len(data):
                raise ValueError("truncated message length")
            size, = LENGTH.unpack_from(data, offset)
            offset += LENGTH.size
            if offset + size > len(data):
                raise ValueError("truncated message payload")
            messages.append(data[offset:offset + size])
            offset += size
        if offset != len(data):
            raise ValueError("trailing bytes after downstream packet")
        return cls(session, sequence, count, tuple(messages))


def read_binaryfile(source, limit=None):
    """Yield ITCH bodies. A capped replay can end at a synthetic session boundary."""
    index = 0
    while limit is None or index < limit:
        prefix = source.read(LENGTH.size)
        if not prefix:
            return
        if len(prefix) != LENGTH.size:
            raise ValueError("truncated BinaryFILE length")
        size, = LENGTH.unpack(prefix)
        payload = source.read(size)
        if not size or len(payload) != size:
            raise ValueError("empty or truncated BinaryFILE payload")
        index += 1
        yield payload


def batches(messages, budget, count_limit):
    batch = []
    size = HEADER.size
    for payload in messages:
        block_size = LENGTH.size + len(payload)
        if HEADER.size + block_size > budget:
            raise ValueError("BinaryFILE message exceeds UDP payload budget")
        if len(batch) == count_limit or size + block_size > budget:
            yield tuple(batch)
            batch = []
            size = HEADER.size
        batch.append(payload)
        size += block_size
    if batch:
        yield tuple(batch)


def encode_request(session, sequence, count):
    if len(session) != 10 or not 1 <= sequence <= MAX_SEQUENCE:
        raise ValueError("invalid request header")
    if not 1 <= count <= 65535 or sequence + count > MAX_SEQUENCE:
        raise ValueError("invalid request range")
    return HEADER.pack(session, sequence, count)


def recovery_response(data, session, cache, budget):
    """Return one unicast downstream datagram for a valid cached request."""
    if len(data) != HEADER.size:
        return None
    requested_session, first, count = HEADER.unpack(data)
    if (requested_session != session or not first or not count
            or first + count > MAX_SEQUENCE or first not in cache):
        return None
    messages = []
    size = HEADER.size
    for sequence in range(first, first + min(count, END - 1)):
        payload = cache.get(sequence)
        if payload is None or size + LENGTH.size + len(payload) > budget:
            break
        size += LENGTH.size + len(payload)
        messages.append(payload)
    if not messages:
        return None
    return Packet(session, first, len(messages), tuple(messages)).encode()


class Assembly:
    def __init__(self, session, output, window):
        self.session = session
        self.output = output
        self.window = window
        self.next_sequence = 1
        self.high_water = 1
        self.multicast_high = 1
        self.final_sequence = None
        self.pending = {}
        self.gap_events = 0
        self.first_gap = None
        self.out_of_order_packets = 0
        self.duplicate_messages = 0
        self.recovered_messages = 0

    def ingest(self, packet, repair=False):
        if packet.session != self.session:
            raise ValueError("session mismatch")
        end = packet.sequence + len(packet.messages)
        if repair and (not packet.messages or end > self.high_water):
            raise ValueError("unexpected unicast response range")
        if self.final_sequence is not None and end > self.final_sequence:
            raise ValueError("packet extends past end of session")
        if packet.count == END:
            if packet.sequence < self.high_water or (
                self.final_sequence is not None and packet.sequence != self.final_sequence
            ):
                raise ValueError("inconsistent end of session")
            self.final_sequence = packet.sequence
        if not repair and packet.messages:
            if packet.sequence < self.multicast_high:
                self.out_of_order_packets += 1
            self.multicast_high = max(self.multicast_high, end)
        if packet.sequence > max(self.high_water, self.next_sequence):
            self.gap_events += 1
            if self.first_gap is None:
                self.first_gap = [max(self.high_water, self.next_sequence), packet.sequence]
        self.high_water = max(self.high_water, end)
        for sequence, payload in enumerate(packet.messages, packet.sequence):
            if not payload:
                raise ValueError("empty MoldUDP64 body cannot be handed off as ITCH")
            if sequence < self.next_sequence or sequence in self.pending:
                self.duplicate_messages += 1
                continue
            if sequence - self.next_sequence >= self.window:
                raise ValueError("receiver reorder window exceeded")
            self.pending[sequence] = payload
            self.recovered_messages += int(repair)
            while self.next_sequence in self.pending:
                self.output.write(block(self.pending.pop(self.next_sequence)))
                self.next_sequence += 1

    @property
    def complete(self):
        return self.final_sequence == self.next_sequence

    @property
    def missing(self):
        return self.high_water - self.next_sequence - len(self.pending)

    def request(self):
        if self.next_sequence < self.high_water:
            stop = min(self.pending, default=self.high_water)
            return encode_request(self.session, self.next_sequence,
                                  min(stop - self.next_sequence, 65535))
