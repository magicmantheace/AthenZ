"""Offline first-run / portable readiness tests; no user data or network."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError

from athenz.preflight import installation_report, desktop_self_test, main
from athenz.desktop import main as desktop_main


class ReadinessTests(unittest.TestCase):
    def test_offline_smoke_keeps_profile_ephemeral_and_disabled(self):
        # Does not touch ~/.athenz or attempt to load user models.
        with mock.patch('athenz.chat.safe_local_open') as net, mock.patch('athenz.scheduler.OllamaClient') as model:
            desktop_self_test()
            net.assert_not_called()
            model.assert_not_called()

    def test_packaged_entrypoint_accepts_smoke_without_window(self):
        with mock.patch('athenz.desktop.launch') as gui, mock.patch(
                'athenz.preflight.desktop_self_test') as check:
            desktop_main(['--self-test'])
            check.assert_called_once_with()
            gui.assert_not_called()

    def test_diagnostics_default_never_uses_network_or_writes_memory(self):
        with mock.patch('athenz.chat.safe_local_open') as network, mock.patch(
                'athenz.preflight.bootstrap_private_home') as bootstrap:
            report = installation_report()
        network.assert_not_called()
        bootstrap.assert_not_called()
        self.assertEqual([x['name'] for x in report['checks']],
                         ['python', 'tk', 'git', 'docker'])
        self.assertFalse(report['hardware_validated'])
        self.assertFalse(report['startup_authorized'])
        self.assertNotIn('home', json.dumps(report).lower())

    def test_explicit_loopback_probe_reports_version_without_user_prompts(self):
        class FakeReply:
            def __enter__(self): return io.BytesIO(b'{"version":"0.1"}')
            def __exit__(self, *args): return False
        with mock.patch('athenz.chat.safe_local_open', return_value=FakeReply()) as opening:
            report = installation_report(probe_ollama=True)
        self.assertTrue(report['checks'][-1]['ok'])
        self.assertEqual(opening.call_args.args[0].full_url, 'http://127.0.0.1:11434/api/version')
        self.assertIsNone(opening.call_args.args[0].data)
        self.assertNotIn('0.1', json.dumps(report))

    def test_ollama_failure_is_sanitized(self):
        with mock.patch('athenz.chat.safe_local_open', side_effect=URLError('SECRET PATH')):
            result = installation_report(probe_ollama=True)
        self.assertFalse(result['checks'][-1]['ok'])
        self.assertNotIn('SECRET', str(result))

    def test_cli_output_contains_only_readiness_flags(self):
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            main([])
        result = json.loads(out.getvalue())
        self.assertFalse(result['private_data_collected'])
        self.assertEqual(len(result['checks']), 4)

    def test_portable_builder_has_no_release_or_auto_install(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/windows-portable.yml').read_text('utf-8')
        self.assertIn('windows-latest', workflow)
        self.assertIn('--self-test', workflow)
        self.assertIn('--onedir', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('retention-days: 7', workflow)
        self.assertNotIn('releases:', workflow)
        self.assertNotIn('signtool', workflow.lower())


if __name__ == '__main__':
    unittest.main()
