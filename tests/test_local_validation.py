"""No-external-CI validation runner tests, synthetic subprocess results."""
from __future__ import annotations
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.local_validation import LocalValidationError, validate


class LocalValidationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'repository'
        (self.root / 'athenz').mkdir(parents=True)
        (self.root / 'tools').mkdir()
        (self.root / 'tests').mkdir()
        (self.root / '.github' / 'workflows').mkdir(parents=True)
        (self.root / 'pyproject.toml').write_text('[project]\nname="athenz-local"\nversion="0.1"\n')
        (self.root / 'athenz' / '__init__.py').write_text('')
        (self.root / 'tools' / 'ci_budget.py').write_text('')
        for name in ('tests.yml', 'windows-portable.yml', 'docker-integration.yml'):
            (self.root / '.github' / 'workflows' / name).write_text(
                'name: test\non:\n  workflow_dispatch:\njobs:\n  noop:\n    runs-on: ubuntu-latest\n')

    def test_policy_runs_explicit_local_unittest_only(self):
        with patch('tools.local_validation.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = validate(self.root)
        self.assertTrue(result['passed'])
        self.assertFalse(result['github_actions_invoked'])
        self.assertFalse(result['network_sandboxed'])
        self.assertEqual(result['workflows_audited'], 3)
        self.assertEqual(run.call_args.args[0][1:], ['-m', 'unittest', 'tests.test_ci_budget', '-q'])
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertEqual(run.call_args.kwargs['env']['PIP_NO_INDEX'], '1')
        self.assertNotEqual(run.call_args.kwargs['env']['ATHENZ_HOME'], str(Path.home() / '.athenz'))

    def test_full_and_wheel_use_fixed_commands(self):
        with patch('tools.local_validation.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = validate(self.root, mode='all')
        self.assertTrue(result['passed'])
        self.assertEqual([c['check'] for c in result['checks']],
                         ['policy-unit-tests', 'full-unit-suite', 'wheel-no-index'])
        self.assertEqual(run.call_count, 3)
        wheel_cmd = run.call_args.args[0]
        self.assertIn('--no-index', wheel_cmd)
        self.assertIn('--no-build-isolation', wheel_cmd)
        self.assertIn('--no-deps', wheel_cmd)
        self.assertNotEqual(run.call_args.kwargs['cwd'], self.root)
        self.assertTrue((self.root / 'athenz' / '__init__.py').exists())

    def test_failed_local_process_stops_checks(self):
        with patch('tools.local_validation.subprocess.run', return_value=subprocess.CompletedProcess([], 3)) as run:
            result = validate(self.root, mode='all')
        self.assertFalse(result['passed'])
        self.assertEqual(run.call_count, 1)

    def test_timeout_is_failure_and_not_swallowed(self):
        with patch('tools.local_validation.subprocess.run', side_effect=subprocess.TimeoutExpired('test', 1)):
            result = validate(self.root, mode='full')
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks'][0]['status'], 'unavailable-or-timeout')

    def test_rejects_auto_trigger_and_never_launches_process(self):
        (self.root / '.github' / 'workflows' / 'tests.yml').write_text('on:\n  push:\n')
        with patch('tools.local_validation.subprocess.run', side_effect=AssertionError('should not launch')):
            with self.assertRaisesRegex(ValueError, 'trigger'):
                validate(self.root)

    def test_rejects_bad_mode_timeout_and_symlinked_root(self):
        with self.assertRaises(LocalValidationError):
            validate(self.root, mode='manual-custom-command')
        with self.assertRaises(LocalValidationError):
            validate(self.root, timeout=0)
        with self.assertRaises(LocalValidationError):
            validate(self.root, timeout=True)
        link = self.root.parent / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(LocalValidationError):
            validate(link)

    def test_rejects_symlinked_package_source_before_wheel(self):
        bad = self.root / 'athenz' / 'import.py'
        bad.symlink_to(self.root / 'pyproject.toml')
        with patch('tools.local_validation.subprocess.run', side_effect=AssertionError('do not run')):
            with self.assertRaisesRegex(LocalValidationError, 'symlink'):
                validate(self.root, mode='wheel')


if __name__ == '__main__':
    unittest.main()
