"""Private-content-free, offline tests for the owner-confirmed inference check."""
from __future__ import annotations

import io
import json
from unittest import TestCase, mock
from urllib.error import URLError

from athenz.inference_readiness import check_inference, InferenceProbeError, main


class _Reply:
    def __init__(self, payload):
        self._stream = io.BytesIO(payload)
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, count): return self._stream.read(count)


class InferenceReadinessTests(TestCase):
    def test_unconfirmed_has_no_client_side_effects(self):
        with mock.patch('athenz.chat.OllamaClient', side_effect=AssertionError('client')), \
             mock.patch('athenz.chat.safe_local_open', side_effect=AssertionError('request')):
            with self.assertRaisesRegex(InferenceProbeError, 'confirm'):
                check_inference(model='qwen3.5:2b')

    def test_model_and_timeout_are_bounded(self):
        for value in ('', '../../secret', '\nmodel', 'a' * 129, None, 3):
            with self.subTest(model=value), self.assertRaises(InferenceProbeError):
                check_inference(model=value, confirmed=True)
        for value in (0, 61, False, 1.2):
            with self.subTest(timeout=value), self.assertRaises(InferenceProbeError):
                check_inference(model='synthetic:1', confirmed=True, timeout_seconds=value)

    def test_synthetic_request_never_contains_context(self):
        reply = _Reply(b'{"message":{"content":"READY"}}')
        with mock.patch('athenz.chat.safe_local_open', return_value=reply) as opener, \
             mock.patch('athenz.experience.ExperienceStore', side_effect=AssertionError('private')):
            result = check_inference(model='synthetic:1', confirmed=True)
        self.assertEqual(result['status'], 'local-text-generated')
        self.assertTrue(result['inference_observed'])
        self.assertFalse(result['gpu_validated'])
        self.assertFalse(result['conversation_saved'])
        self.assertNotIn('READY', json.dumps(result))
        self.assertNotIn('synthetic:1', json.dumps(result))
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(request.get_method(), 'POST')
        payload = json.loads(request.data)
        self.assertEqual(payload['messages'], [{'role': 'user', 'content': 'Reply with exactly the word READY.'}])
        self.assertEqual(payload['options']['num_predict'], 12)
        self.assertEqual(opener.call_args.kwargs, {'timeout': 20})

    def test_loopback_endpoint_validation_blocks_external_hosts(self):
        with mock.patch.dict('os.environ', {'ATHENZ_OLLAMA_URL': 'http://example.com:11434'}), \
             mock.patch('athenz.chat.safe_local_open') as opener:
            from athenz.chat import LocalModelError
            with self.assertRaises(LocalModelError):
                check_inference(model='synthetic:1', confirmed=True)
        opener.assert_not_called()

    def test_invalid_or_oversized_responses_are_sanitized(self):
        for payload in (b'not-json', b'[]', b'{"message":{"content":""}}',
                        b'{"message":{}}', b'X' * 16385):
            with self.subTest(payload=payload[:25]), mock.patch('athenz.chat.safe_local_open', return_value=_Reply(payload)):
                result = check_inference(model='synthetic:1', confirmed=True)
            self.assertEqual(result['status'], 'invalid-local-reply')
            self.assertNotIn('X' * 8, json.dumps(result))

    def test_synthetic_instruction_following_is_reported_separately(self):
        for answer, expected in [('READY', True), ('I am ready!', False),
                                 ('WRONG PRIVATE ANSWER', False)]:
            with self.subTest(answer=answer):
                payload = json.dumps({'done': True, 'message': {
                    'role': 'assistant', 'content': answer}}).encode('utf-8')
                with mock.patch('athenz.chat.safe_local_open',
                                return_value=_Reply(payload)):
                    report = check_inference(model='synthetic:1', confirmed=True)
                self.assertTrue(report['inference_observed'])
                self.assertEqual(report['synthetic_instruction_followed'], expected)
                self.assertNotIn(answer, json.dumps(report))
                self.assertFalse(report['quality_validated'])

    def test_explicit_ollama_errors_or_incomplete_replies_refused(self):
        bad = [
            {'done': False, 'message': {'content': 'READY'}},
            {'error': 'PRIVATE INTERNAL ERROR', 'message': {'content': 'READY'}},
            {'done': True, 'message': {'role': 'user', 'content': 'READY'}},
        ]
        for body in bad:
            with self.subTest(body=str(body)):
                with mock.patch('athenz.chat.safe_local_open',
                                return_value=_Reply(json.dumps(body).encode('utf-8'))):
                    report = check_inference(model='synthetic:1', confirmed=True)
                self.assertFalse(report['inference_observed'])
                self.assertFalse(report['synthetic_instruction_followed'])
                self.assertEqual(report['status'], 'invalid-local-reply')
                self.assertNotIn('PRIVATE', json.dumps(report))

    def test_network_exception_is_not_exposed(self):
        with mock.patch('athenz.chat.safe_local_open', side_effect=URLError('SECRET-PATH-PRIVATE-TOKEN')):
            report = check_inference(model='synthetic:1', confirmed=True)
        self.assertEqual(report['status'], 'local-model-unavailable')
        self.assertFalse(report['inference_observed'])
        self.assertNotIn('SECRET', json.dumps(report))

    def test_actual_loopback_http_transport_and_proxy_bypass(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import os
        import threading
        captured = []
        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                data = b'{"message":{"content":"READY"}}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *_):
                return
        server = HTTPServer(('127.0.0.1', 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.dict(os.environ, {
                    'ATHENZ_OLLAMA_URL': f'http://127.0.0.1:{server.server_port}',
                    'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1'}):
                report = check_inference(model='synthetic:1', confirmed=True, timeout_seconds=4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
        self.assertTrue(report['inference_observed'])
        self.assertEqual(captured[0][0], '/api/chat')
        self.assertEqual(captured[0][1]['messages'][0]['content'], 'Reply with exactly the word READY.')

    def test_redirect_does_not_visit_external_destination(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import os
        import threading
        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header('Location', 'https://example.com/exfiltrate')
                self.end_headers()
            def log_message(self, *_):
                return
        server = HTTPServer(('127.0.0.1', 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.dict(os.environ, {'ATHENZ_OLLAMA_URL': f'http://127.0.0.1:{server.server_port}'}):
                result = check_inference(model='synthetic:1', confirmed=True, timeout_seconds=4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
        self.assertEqual(result['status'], 'local-model-unavailable')
        self.assertNotIn('example.com', json.dumps(result))

    def test_cli_json_reports_status_without_reply_or_model(self):
        response = {'status': 'local-text-generated', 'inference_observed': True}
        with mock.patch('athenz.inference_readiness.check_inference', return_value=response) as probe, \
             mock.patch('builtins.print') as writer:
            main(['--model', 'local:1', '--confirm', '--timeout', '9'])
        probe.assert_called_once_with(model='local:1', confirmed=True, timeout_seconds=9)
        self.assertEqual(json.loads(writer.call_args.args[0]), response)

    def test_cli_fails_on_unavailable_model(self):
        with mock.patch('athenz.inference_readiness.check_inference', return_value={'inference_observed': False}), \
             mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as exc:
                main(['--model', 'local:1', '--confirm'])
        self.assertEqual(exc.exception.code, 1)


if __name__ == '__main__':
    import unittest
    unittest.main()
