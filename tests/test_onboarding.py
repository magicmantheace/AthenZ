"""Pure guidance only: no Ollama, GPU, filesystem reads or personal content."""
import contextlib
import io
import json
import unittest
from unittest import mock

from athenz.onboarding import guide, guide_text, main


class OnboardingTests(unittest.TestCase):
    def test_read_only_first_run(self):
        with mock.patch('builtins.open', side_effect=AssertionError('No file reads')), \
             mock.patch('subprocess.run', side_effect=AssertionError('No process')), \
             mock.patch('socket.socket', side_effect=AssertionError('No socket')):
            report = guide()
            text = guide_text()
        self.assertEqual(report['schema'], 1)
        self.assertFalse(report['grants_consent'])
        self.assertFalse(report['starts_background_work'])
        self.assertFalse(report['initiates_hardware_probe'])
        self.assertEqual(len(report['steps']), 7)
        self.assertEqual(report['steps'][2]['title'], 'Try your Twin first')
        self.assertIn('Preview Twin evidence', text)
        self.assertIn('Agent Mode remains an explicit alternative', text)
        self.assertIn('SHA-256', text)
        self.assertIn('unencrypted', text)
        self.assertIn('off by default', text)

    def test_json_cli_is_nonpersonal(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(['--json'])
        data = json.loads(output.getvalue())
        self.assertEqual(data, guide())
        self.assertNotIn('username', output.getvalue().lower())
        self.assertNotIn('serial', output.getvalue().lower())

    def test_text_cli_and_unknown_flags(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main([])
        self.assertIn('Getting started', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(['--probe-gpu'])


if __name__ == '__main__':
    unittest.main()
