"""Verify buffered stdio flush and unusable sender after partial delivery."""
from io import BytesIO
import unittest

from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_frames import SyntheticFrameSession


class BufferedFrameTests(unittest.TestCase):
    def setUp(self):
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.config = dict(
            session_id="6" * 32, producer_keys=self.keys,
            frame_keys={"athenz": b"f" * 32, "learner": b"g" * 32},
            revision_check=lambda ref, rev: ref == "synthetic:flush" and rev == 1,
            enabled=True)
        self.send = SyntheticFrameSession(**self.config)
        self.recv = SyntheticFrameSession(**self.config)

    def event(self, seq=1):
        return synthetic_event(
            producer="athenz", task_id="flush", seq=seq,
            kind="observation", source_ref="synthetic:flush", source_revision=1,
            payload={"signal": "trace_sha256", "value": "a" * 64},
            secret=self.keys["athenz"])

    def test_buffered_sink_delivered_before_send_returns(self):
        class Buffered:
            def __init__(self):
                self.pending = bytearray()
                self.wire = BytesIO()
                self.flushes = 0
            def write(self, data):
                self.pending.extend(data)
                return len(data)
            def flush(self):
                self.wire.write(self.pending)
                self.pending.clear()
                self.flushes += 1
        stream = Buffered()
        event = self.event()
        self.send.send(stream, event)
        self.assertEqual(stream.flushes, 1)
        self.assertFalse(stream.pending)
        self.assertEqual(
            self.recv.receive(BytesIO(stream.wire.getvalue()),
                              expected_producer="athenz"), event)

    def test_failed_flush_does_not_expose_exception_and_poisons_session(self):
        class Broken:
            def write(self, data):
                return len(data)
            def flush(self):
                raise OSError("never disclose caller stream detail")
        with self.assertRaisesRegex(BridgeError, "flush failed") as failure:
            self.send.send(Broken(), self.event())
        self.assertNotIn("caller stream detail", str(failure.exception))
        with self.assertRaisesRegex(BridgeError, "new session"):
            self.send.pack(self.event(2))

    def test_short_write_poisons_session(self):
        class Partial:
            def write(self, data):
                return len(data) - 1
        with self.assertRaisesRegex(BridgeError, "Short"):
            self.send.send(Partial(), self.event())
        with self.assertRaisesRegex(BridgeError, "new session"):
            self.send.send(BytesIO(), self.event(2))

    def test_missing_flush_is_not_counted_as_delivery(self):
        class NoFlush:
            def write(self, data):
                return len(data)
        with self.assertRaisesRegex(BridgeError, "flush failed"):
            self.send.send(NoFlush(), self.event())
        self.assertTrue(self.send._send_broken)

    def test_invalid_event_does_not_poison_unused_session(self):
        invalid = self.event()
        invalid["scope"] = "execute"
        with self.assertRaises(BridgeError):
            self.send.send(BytesIO(), invalid)
        self.assertFalse(self.send._send_broken)
        self.send.send(BytesIO(), self.event())
        self.assertEqual(self.send._out_seq["athenz"], 1)


if __name__ == "__main__":
    unittest.main()
