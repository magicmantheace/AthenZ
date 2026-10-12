"""Owner-controlled reply discarding: no Ollama needed and no personal data."""
from __future__ import annotations

import threading
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.chat_cancel import ReplyCancelGate, ReplyCancelled
from athenz.desktop import DesktopService


class FakeModel:
    model = 'synthetic-test'
    def __init__(self, *args, **kwargs):
        pass


class CancelReplyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = DesktopService(Path(temp.name) / 'private')

    def test_cancel_before_call_never_initializes_local_ollama(self):
        gate = ReplyCancelGate()
        self.assertTrue(gate.request_cancel())
        with mock.patch('athenz.desktop.OllamaClient', side_effect=AssertionError('model started')):
            with self.assertRaises(ReplyCancelled):
                self.service.send('session', 'agent', 'hello', cancel_gate=gate)
        self.assertEqual(self.service.history('session', 'agent'), [])

    def test_cancel_during_model_inference_discards_entire_turn(self):
        gate, started, resume = ReplyCancelGate(), threading.Event(), threading.Event()
        class SlowModel(FakeModel):
            def generate(self, *args, **kwargs):
                started.set()
                if not resume.wait(3):
                    raise RuntimeError('Synthetic inference timed out')
                return 'Synthetic model reply'
        errors = []
        def run():
            try:
                self.service.send('session', 'agent', 'private synthetic question', cancel_gate=gate)
            except BaseException as exc:
                errors.append(exc)
        with mock.patch('athenz.desktop.OllamaClient', SlowModel):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                self.assertTrue(gate.request_cancel())
            finally:
                resume.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ReplyCancelled)
        self.assertEqual(self.service.history('session', 'agent'), [])

    def test_normal_success_with_gate_saves_complete_turn(self):
        gate = ReplyCancelGate()
        with mock.patch('athenz.desktop.OllamaClient', FakeModel), \
             mock.patch('athenz.desktop.answer', return_value='Synthetic answer'):
            result = self.service.send('session', 'twin', 'Synthetic question', cancel_gate=gate)
        self.assertEqual(result['reply'], 'Synthetic answer')
        self.assertEqual([x['role'] for x in self.service.history('session', 'twin')], ['user', 'assistant'])
        self.assertFalse(gate.request_cancel())

    def test_cancel_in_commit_guard_waits_until_transaction_finishes(self):
        gate, attempted, completed = ReplyCancelGate(), threading.Event(), threading.Event()
        def cancel_on_thread():
            attempted.set()
            gate.request_cancel()
            completed.set()
        thread = threading.Thread(target=cancel_on_thread)
        with gate.commit_guard():
            thread.start()
            self.assertTrue(attempted.wait(2))
            self.assertFalse(completed.wait(0.03))
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(completed.is_set())
        self.assertFalse(gate.request_cancel())

    def test_failed_transaction_gate_stays_cancellable(self):
        gate = ReplyCancelGate()
        with self.assertRaisesRegex(RuntimeError, 'Synthetic commit failure'):
            with gate.commit_guard():
                raise RuntimeError('Synthetic commit failure')
        self.assertTrue(gate.request_cancel())
        with self.assertRaises(ReplyCancelled):
            gate.checkpoint()

    def test_cancel_invalid_reply_does_not_approve_or_persist(self):
        gate = ReplyCancelGate()
        with mock.patch('athenz.desktop.OllamaClient', FakeModel), \
             mock.patch('athenz.desktop.answer', side_effect=lambda *_args: (gate.request_cancel(), 'unused')[1]):
            with self.assertRaises(ReplyCancelled):
                self.service.send('session', 'agent', 'Sensitive synthetic', cancel_gate=gate)
        self.assertEqual(self.service.history('session', 'agent'), [])


if __name__ == '__main__':
    unittest.main()
