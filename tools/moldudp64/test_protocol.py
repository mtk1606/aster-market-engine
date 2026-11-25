import io
import unittest

from protocol import (
    DEFAULT_SESSION, END, MAX_SEQUENCE, Assembly, Packet, batches, block,
    encode_request, read_binaryfile, recovery_response,
)

SESSION = DEFAULT_SESSION.encode("ascii")


class FramingTest(unittest.TestCase):
    def test_known_downstream_bytes(self):
        wire = SESSION + bytes.fromhex("0000000000000102 0002 0001 41 0002 4243")
        packet = Packet(SESSION, 258, 2, (b"A", b"BC"))
        self.assertEqual(packet.encode(), wire)
        self.assertEqual(Packet.decode(wire), packet)

    def test_heartbeat_end_and_empty_message(self):
        for count in (0, END):
            packet = Packet(SESSION, 11, count)
            self.assertEqual(len(packet.encode()), 20)
            self.assertEqual(Packet.decode(packet.encode()), packet)
        packet = Packet(SESSION, 1, 1, (b"",))
        self.assertEqual(Packet.decode(packet.encode()), packet)

    def test_malformed_frames(self):
        wire = Packet(SESSION, 1, 2, (b"A", b"BC")).encode()
        for malformed in (wire[:19], wire[:20], wire[:-1], wire + b"x",
                          SESSION + b"\0" * 10,
                          SESSION + bytes.fromhex("ffffffffffffffff 0001 0001 41")):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                Packet.decode(malformed)
        with self.assertRaises(ValueError):
            Packet(SESSION, MAX_SEQUENCE, 1, (b"A",)).encode()

    def test_binaryfile_and_batch_limits(self):
        framed = block(b"A") + block(b"BC") + block(b"DEF")
        self.assertEqual(list(read_binaryfile(io.BytesIO(framed), 2)), [b"A", b"BC"])
        self.assertEqual(list(batches(read_binaryfile(io.BytesIO(framed)), 27, 10)),
                         [(b"A", b"BC"), (b"DEF",)])
        self.assertEqual(list(batches((b"A", b"BC"), 27, 1)), [(b"A",), (b"BC",)])
        for malformed in (b"\x00", b"\x00\x00", b"\x00\x02A"):
            with self.assertRaises(ValueError):
                list(read_binaryfile(io.BytesIO(malformed)))
        with self.assertRaises(ValueError):
            list(batches((b"ABC",), 24, 1))


class RecoveryTest(unittest.TestCase):
    def test_request_layout_and_partial_reply(self):
        cache = {7: b"AB", 8: b"CD", 9: b"EF"}
        request = encode_request(SESSION, 7, 3)
        self.assertEqual(request, SESSION + bytes.fromhex("0000000000000007 0003"))
        self.assertEqual(Packet.decode(recovery_response(request, SESSION, cache, 24)),
                         Packet(SESSION, 7, 1, (b"AB",)))
        request = encode_request(SESSION, 8, 2)
        self.assertEqual(Packet.decode(recovery_response(request, SESSION, cache, 28)),
                         Packet(SESSION, 8, 2, (b"CD", b"EF")))

    def test_request_rejections(self):
        for request in (b"short", encode_request(SESSION, 2, 1),
                        encode_request(b"DIFFERENT1", 1, 1),
                        SESSION + bytes.fromhex("0000000000000001 0000"),
                        SESSION + bytes.fromhex("ffffffffffffffff ffff")):
            self.assertIsNone(recovery_response(request, SESSION, {1: b"A"}, 1400))

    def test_gap_repair_then_multicast_reordering(self):
        output = io.BytesIO()
        state = Assembly(SESSION, output, window=16)
        state.ingest(Packet(SESSION, 1, 0))
        state.ingest(Packet(SESSION, 4, 1, (b"D",)))
        self.assertEqual(state.missing, 3)
        self.assertEqual(state.first_gap, [1, 4])
        self.assertEqual(state.request(), encode_request(SESSION, 1, 3))
        state.ingest(Packet(SESSION, 1, 1, (b"A",)), repair=True)
        self.assertEqual(state.request(), encode_request(SESSION, 2, 2))
        state.ingest(Packet(SESSION, 2, 2, (b"B", b"C")))
        state.ingest(Packet(SESSION, 4, 1, (b"D",)))
        state.ingest(Packet(SESSION, 5, END))
        self.assertTrue(state.complete)
        self.assertEqual((state.missing, state.gap_events, state.out_of_order_packets,
                          state.duplicate_messages, state.recovered_messages), (0, 1, 2, 1, 1))
        self.assertEqual(output.getvalue(), b"".join(block(bytes([value])) for value in b"ABCD"))

    def test_heartbeat_and_end_announce_a_missing_tail(self):
        state = Assembly(SESSION, io.BytesIO(), window=2)
        state.ingest(Packet(SESSION, 2, 0))
        state.ingest(Packet(SESSION, 2, END))
        self.assertFalse(state.complete)
        self.assertEqual(state.request(), encode_request(SESSION, 1, 1))
        with self.assertRaises(ValueError):
            state.ingest(Packet(SESSION, 3, END))
        state.ingest(Packet(SESSION, 1, 1, (b"A",)), repair=True)
        self.assertTrue(state.complete)

    def test_reorder_window_and_session_guard(self):
        state = Assembly(SESSION, io.BytesIO(), window=2)
        with self.assertRaisesRegex(ValueError, "session mismatch"):
            state.ingest(Packet(b"DIFFERENT1", 1, 0))
        with self.assertRaisesRegex(ValueError, "window exceeded"):
            state.ingest(Packet(SESSION, 3, 1, (b"A",)))


if __name__ == "__main__":
    unittest.main()
