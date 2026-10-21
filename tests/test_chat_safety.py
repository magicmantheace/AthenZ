"""Synthetic fail-closed local chat transport and transactional persistence tests."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from athenz.chat import LocalModelError, OllamaClient, MAX_RESPONSE_BYTES, MAX_REPLY_CHARS, main
from athenz.experience import ExperienceStore


class _FakeReply:
    def __init__(self, body: bytes):
        self.stream = io.BytesIO(body)
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, limit=-1): return self.stream.read(limit)


class ChatSafetyTests(unittest.TestCase):
    def test_large_local_reply_rejected_before_json_decode(self):
        probe = _FakeReply(b'{' + b'x' * (MAX_RESPONSE_BYTES + 500))
        with mock.patch('athenz.chat.safe_local_open', return_value=probe):
            with self.assertRaisesRegex(LocalModelError, 'invalid reply'):
                OllamaClient(model='synthetic:1').generate([{'role': 'user', 'content': 'SYNTHETIC'}])
        self.assertEqual(probe.stream.tell(), MAX_RESPONSE_BYTES + 1)

    def test_large_decoded_content_rejected_before_storage(self):
        body = json.dumps({'message': {'content': 'x' * (MAX_REPLY_CHARS + 1)}}).encode()
        with mock.patch('athenz.chat.safe_local_open', return_value=_FakeReply(body)):
            with self.assertRaisesRegex(LocalModelError, 'invalid reply'):
                OllamaClient(model='synthetic:1').generate([{'role': 'user', 'content': 'SYNTHETIC'}])

    def test_malformed_local_reply_never_leaks_sensitive_json_or_error(self):
        secret = 'PRIVATE-DIAGNOSTIC-TOKEN'
        for body in (b'{}', b'[]', json.dumps({'error': secret}).encode(),
                     b'{invalid', json.dumps({'message': {'content': None}}).encode()):
            with self.subTest(body=body[:16]), mock.patch('athenz.chat.safe_local_open', return_value=_FakeReply(body)):
                with self.assertRaises(LocalModelError) as error:
                    OllamaClient(model='synthetic:1').generate([{'role': 'user', 'content': 'SYNTHETIC'}])
            self.assertNotIn(secret, str(error.exception))

    def test_malformed_endpoint_port_always_raises_safe_error(self):
        for endpoint in ('http://127.0.0.1:notaport', 'http://[::1', 'http://localhost:65536', 'http://localhost:0'):
            with self.subTest(endpoint=endpoint), self.assertRaises(LocalModelError):
                OllamaClient(endpoint=endpoint)

    def test_cli_discards_reply_if_route_revoked_during_generation(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            output = io.StringIO()
            with mock.patch('athenz.runtime.checked_active_tag', side_effect=['candidate', 'candidate', 'replaced']), \
                 mock.patch('athenz.chat.safe_local_open', return_value=_FakeReply(b'{"message":{"content":"MODEL-SENTINEL"}}')), \
                 mock.patch('builtins.input', side_effect=['OWNER-SENTINEL', '/exit']), redirect_stdout(output):
                main(['--home', str(home), '--session', 'case'])
            store = ExperienceStore(home)
            try:
                self.assertEqual(store.conversation('case', 'agent'), [])
            finally:
                store.close()
            self.assertNotIn('MODEL-SENTINEL', output.getvalue())

    def test_cli_discards_reply_if_route_activated_from_none_during_generation(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            with mock.patch('athenz.runtime.checked_active_tag', side_effect=[None,None,'new_candidate']), \
                 mock.patch('athenz.chat.safe_local_open', return_value=_FakeReply(b'{"message":{"content":"SYNTHETIC"}}')), \
                 mock.patch('builtins.input', side_effect=['hello', '/exit']), redirect_stdout(io.StringIO()):
                main(['--home', str(home)])
            store = ExperienceStore(home)
            try: self.assertEqual(store.conversation('default', 'agent'), [])
            finally: store.close()

    def test_cli_second_insert_failure_rolls_back_first_and_hides_response(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            store = ExperienceStore(home)
            try:
                with store.db:
                    store.db.execute('''CREATE TRIGGER block_assistant BEFORE INSERT ON messages
                        WHEN NEW.role='assistant' BEGIN SELECT RAISE(FAIL, 'PRIVATE-SQL-ERROR'); END''')
            finally: store.close()
            output=io.StringIO()
            with mock.patch('athenz.chat.safe_local_open', return_value=_FakeReply(b'{"message":{"content":"MODEL-SENTINEL"}}')), \
                 mock.patch('builtins.input', side_effect=['USER-SENTINEL', '/exit']), redirect_stdout(output):
                main(['--home', str(home), '--model','synthetic:1', '--session','s'])
            check=ExperienceStore(home)
            try: self.assertEqual(check.conversation('s','agent'), [])
            finally: check.close()
            self.assertIn('Could not save complete conversation turn', output.getvalue())
            self.assertNotIn('MODEL-SENTINEL', output.getvalue())
            self.assertNotIn('PRIVATE-SQL-ERROR', output.getvalue())

    def test_valid_local_response_stored_as_complete_pair(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)
            with mock.patch('athenz.chat.safe_local_open', return_value=_FakeReply(b'{"message":{"content":"SUCCESS"}}')), \
                 mock.patch('builtins.input', side_effect=['USER-MESSAGE', '/exit']), redirect_stdout(io.StringIO()):
                main(['--home', str(home), '--model','synthetic:1'])
            check=ExperienceStore(home)
            try:
                self.assertEqual([(r['role'],r['content']) for r in check.conversation('default','twin')],
                                 [('user','USER-MESSAGE'),('assistant','SUCCESS')])
                self.assertEqual(check.conversation('default','agent'), [])
            finally:check.close()

if __name__ == '__main__':
    unittest.main()
