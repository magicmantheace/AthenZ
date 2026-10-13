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
        # Existing tests exercise process commands with synthetic source trees.
        # Source completeness itself is exercised in test_source_inventory.py.
        completeness = patch('tools.source_inventory.check_complete', return_value={'complete': True})
        completeness.start()
        self.addCleanup(completeness.stop)
        for name in ('tests.yml', 'windows-portable.yml', 'docker-integration.yml'):
            (self.root / '.github' / 'workflows' / name).write_text(
                'name: test\non:\n  workflow_dispatch:\njobs:\n  noop:\n    runs-on: ubuntu-latest\n')

    def test_real_script_entrypoint_runs_policy_without_PYTHONPATH(self):
        # Regression: running tools/local_validation.py directly used to fail
        # `from tools.ci_budget import ...` before any local policy tests ran.
        import os
        import sys
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as cwd:
            env = os.environ.copy()
            env.pop('PYTHONPATH', None)
            completed = subprocess.run(
                [sys.executable, str(root / 'tools' / 'local_validation.py'),
                 '--root', str(root), '--mode', 'policy', '--timeout', '30'],
                cwd=cwd, env=env, capture_output=True, text=True, timeout=35)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"github_actions_invoked": false', completed.stdout)
        self.assertIn('"passed": true', completed.stdout)

    def test_policy_runs_explicit_local_unittest_only(self):
        with patch('tools.local_validation.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = validate(self.root)
        self.assertTrue(result['passed'])
        self.assertFalse(result['github_actions_invoked'])
        self.assertFalse(result['network_sandboxed'])
        self.assertFalse(result['source_inventory_complete'])
        self.assertEqual(result['workflows_audited'], 3)
        self.assertEqual(run.call_args.args[0][1:], ['-m', 'unittest', 'tests.test_ci_budget', '-q'])
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertEqual(run.call_args.kwargs['env']['PIP_NO_INDEX'], '1')
        self.assertNotEqual(run.call_args.kwargs['env']['ATHENZ_HOME'], str(Path.home() / '.athenz'))

    def test_full_and_wheel_use_fixed_commands(self):
        with patch('tools.local_validation.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = validate(self.root, mode='all')
        self.assertTrue(result['passed'])
        self.assertTrue(result['source_inventory_complete'])
        self.assertTrue(result['local_full_suite_completed'])
        self.assertFalse(result['release_gate_passed'])
        self.assertFalse(result['source_content_verified'])
        self.assertEqual([c['check'] for c in result['checks']],
                         ['policy-unit-tests', 'full-unit-suite', 'wheel-no-index'])
        self.assertEqual(run.call_count, 3)
        wheel_cmd = run.call_args.args[0]
        self.assertIn('--no-index', wheel_cmd)
        self.assertIn('--no-build-isolation', wheel_cmd)
        self.assertIn('--no-deps', wheel_cmd)
        self.assertNotEqual(run.call_args.kwargs['cwd'], self.root)
        self.assertTrue((self.root / 'athenz' / '__init__.py').exists())

    def test_focused_mode_runs_only_reviewed_named_local_tests(self):
        (self.root / 'tests' / 'test_profile_health.py').write_text('pass\n')
        (self.root / 'tests' / 'test_local_validation.py').write_text('pass\n')
        with patch('tools.local_validation.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 0)) as run:
            result = validate(self.root, mode='focused',
                              tests=('tests.test_profile_health', 'tests.test_local_validation'))
        self.assertTrue(result['passed'])
        self.assertFalse(result['source_inventory_complete'])
        self.assertEqual(result['checks'][0]['check'], 'focused-unit-tests')
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1:], ['-m', 'unittest', 'tests.test_profile_health',
                                   'tests.test_local_validation', '-q'])
        self.assertNotEqual(run.call_args.kwargs['env']['ATHENZ_HOME'],
                            str(Path.home() / '.athenz'))

    def test_focused_mode_rejects_arbitrary_commands_and_missing_files(self):
        for value in ('tests.test_missing', 'os.system', 'tests.test_example.some_method',
                      '../unsafe', 'tests.test_foo;exit'):
            with self.subTest(value=value):
                with patch('tools.local_validation.subprocess.run',
                           side_effect=AssertionError('not called')):
                    with self.assertRaises(LocalValidationError):
                        validate(self.root, mode='focused', tests=(value,))

    def test_focused_mode_requires_nonempty_distinct_bounded_test_selection(self):
        testname = 'tests.test_ci_budget'
        (self.root / 'tests' / 'test_ci_budget.py').write_text('pass\n')
        for options in ((), (testname, testname), (testname,) * 13):
            with self.assertRaises(LocalValidationError):
                validate(self.root, mode='focused', tests=options)
        with self.assertRaises(LocalValidationError):
            validate(self.root, mode='policy', tests=(testname,))

    def test_focused_mode_rejects_symlinked_test_module(self):
        filename = self.root / 'tests' / 'test_ci_budget.py'
        try:
            filename.symlink_to(self.root / 'pyproject.toml')
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable on this Windows runner')
        with self.assertRaisesRegex(LocalValidationError, 'unsafe'):
            validate(self.root, mode='focused', tests=('tests.test_ci_budget',))

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

    def test_available_mode_runs_partial_checkout_without_full_claim(self):
        with patch('tools.source_inventory.inspect_sources', return_value={
                'complete': False, 'missing': ['athenz/other.py', 'tests/test_other.py']}), \
             patch('tools.local_validation.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 0)) as run, \
             patch('tools.local_validation.shutil.which', return_value=None):
            result = validate(self.root, mode='available')
        self.assertTrue(result['passed'])
        self.assertFalse(result['release_gate_passed'])
        self.assertFalse(result['source_inventory_complete'])
        self.assertEqual(result['source_files_missing'], 2)
        self.assertEqual(result['checks'][0]['check'], 'available-unit-suite')
        self.assertEqual(run.call_args.args[0][1:],
                         ['-m', 'unittest', 'discover', '-s', 'tests', '-q'])

    def test_available_mode_uses_xvfb_to_exercise_headless_gui(self):
        with patch('tools.source_inventory.inspect_sources', return_value={
                'complete': False, 'missing': []}), \
             patch('tools.local_validation._virtual_display_available', return_value=True), \
             patch('tools.local_validation.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 0)) as run:
            result = validate(self.root, mode='available')
        self.assertTrue(result['virtual_display_used'])
        self.assertEqual(run.call_args.args[0][:2], ['xvfb-run', '-a'])
        self.assertFalse(result['release_gate_passed'])

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
