"""Offline source-inventory acceptance checks on synthetic temporary trees."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.source_inventory import (BASELINE, REQUIRED, InventoryError,
                                    inspect_sources, check_complete, main)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'source'
        self.root.mkdir()

    def populate(self, names):
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic local source')

    def test_archive_inventory_includes_core_runtime_and_regression_suites(self):
        self.assertEqual(len(REQUIRED), len(set(REQUIRED)))
        self.assertGreaterEqual(len(REQUIRED), 109)
        # These files were present in the actual archive but missing from
        # the older preflight manifest. A missing one must now block full/wheel.
        for path in ('athenz/chat_cancel.py', 'athenz/recovery_drill.py',
                     'athenz/inference_readiness.py', 'tests/test_chat_cancel.py',
                     'tests/test_private_home_guards.py',
                     'tests/test_source_inventory.py', 'tools/source_inventory.py'):
            self.assertIn(path, REQUIRED)
        for p in ('athenz/evaluation.py', 'athenz/profile_bundle.py',
                  'athenz/desktop_zoom.py', 'athenz/portable_integrity.py',
                  'tests/test_scheduler.py', 'tools/ci_budget.py'):
            self.assertIn(p, REQUIRED)
        self.assertEqual(len(BASELINE), 40)

    def test_missing_new_archival_source_blocks_completeness(self):
        self.populate(p for p in REQUIRED if p != 'athenz/recovery_drill.py')
        report = inspect_sources(self.root)
        self.assertFalse(report['complete'])
        self.assertIn('athenz/recovery_drill.py', report['missing'])
        with self.assertRaises(InventoryError):
            check_complete(self.root)

    def test_incomplete_checkout_is_reported_before_subprocess(self):
        self.populate(['athenz/__init__.py', 'tools/ci_budget.py'])
        report = inspect_sources(self.root)
        self.assertFalse(report['complete'])
        self.assertIn('athenz/evaluation.py', report['missing'])
        self.assertFalse(report['content_verified'])
        self.assertFalse(report['current_remote_verified'])
        with self.assertRaisesRegex(InventoryError, 'Incomplete'):
            check_complete(self.root)

    def test_complete_baseline_permits_edits_and_additional_sources(self):
        self.populate(REQUIRED)
        (self.root / 'athenz' / 'desktop.py').write_text('changed by a developer')
        (self.root / 'athenz' / 'new_module.py').write_text('additional source')
        report = check_complete(self.root)
        self.assertTrue(report['complete'])
        self.assertFalse(report['content_verified'])
        self.assertEqual(report['expected_files'], len(REQUIRED))

    def test_symlinked_existing_source_is_unsafe(self):
        self.populate(REQUIRED)
        source = self.root / 'athenz' / 'evaluation.py'
        source.unlink()
        source.symlink_to(self.root / 'athenz' / '__init__.py')
        report = inspect_sources(self.root)
        self.assertIn('athenz/evaluation.py', report['unsafe'])
        self.assertFalse(report['complete'])
        with self.assertRaises(InventoryError):
            check_complete(self.root)

    def test_absent_symlink_target_is_never_called_safe_missing(self):
        self.populate(REQUIRED)
        source = self.root / 'athenz' / 'evaluation.py'
        source.unlink()
        source.symlink_to(self.root / 'missing')
        self.assertFalse(inspect_sources(self.root)['complete'])

    def test_local_validation_refuses_partial_checkout_before_running_full_suite(self):
        self.populate(['pyproject.toml', 'athenz/__init__.py', 'tools/ci_budget.py'])
        from tools.local_validation import validate
        with patch('tools.ci_budget.audit_workflows', return_value={'tests.yml': ('workflow_dispatch',)}), \
             patch('tools.local_validation.subprocess.run', side_effect=AssertionError('no tests launched')):
            with self.assertRaisesRegex(InventoryError, 'Incomplete'):
                validate(self.root, mode='full')

    def test_cli_is_offline_and_exits_nonzero_on_missing_source(self):
        with patch('builtins.print') as printed:
            with self.assertRaises(SystemExit) as result:
                main(['--root', str(self.root)])
        self.assertEqual(result.exception.code, 1)
        self.assertIn('missing', printed.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
