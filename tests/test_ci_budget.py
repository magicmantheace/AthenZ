"""Tests for GitHub Actions quota protection; no external requests."""
from pathlib import Path
import tempfile
import unittest

from tools.ci_budget import (CIBudgetError, WORKFLOWS, TWIN_TEST_BRANCH,
                             audit_workflows, declared_events)


class CIBudgetTests(unittest.TestCase):
    def test_repo_workflows_are_scoped_to_owner_approved_twin_ci(self):
        root = Path(__file__).resolve().parents[1]
        result = audit_workflows(root)
        self.assertTrue(WORKFLOWS.issubset(result))
        self.assertEqual(result['tests.yml'], ('push', 'workflow_dispatch'))
        self.assertTrue(all(
            events == ('workflow_dispatch',) for path, events in result.items()
            if path != 'tests.yml'))

    def test_default_is_one_linux_job_and_full_remains_explicit(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/tests.yml').read_text()
        self.assertIn('default: smoke', text)
        self.assertIn("if: github.event_name == 'push' || inputs.coverage == 'smoke'", text)
        self.assertIn("      - " + TWIN_TEST_BRANCH, text)
        self.assertIn("inputs.coverage == 'full'", text)
        self.assertIn("contains(github.event.head_commit.message, '[full-ci]')", text)
        self.assertEqual(text.count('runs-on: ubuntu-latest'), 1)
        self.assertIn('os: windows-latest', text)

    def test_events_detected_without_confusing_other_keys(self):
        value = "name: sample\non:\n  workflow_dispatch:\n    inputs:\n      flavor:\n        default: smoke\njobs:\n  smoke:\n    runs-on: ubuntu-latest\n"
        self.assertEqual(declared_events(value), ('workflow_dispatch',))

    def test_automatic_events_and_duplicate_events_rejected(self):
        for bad in (
            'on:\n  pull_request:\n  workflow_dispatch:\n',
            'on:\n  workflow_dispatch:\n  push:\n',
            'on:\n  schedule:\n    - cron: "0 0 * * *"\n',
            'on:\n  workflow_call:\n',
            'on:\n  workflow_dispatch:\n  workflow_dispatch:\n',
            'on: [workflow_dispatch, push]\n',
            'on: workflow_dispatch\n',
            'on:\n  workflow_dispatch: yes\n',
            'on:\n  workflow_dispatch:\non:\n  pull_request:\n',
        ):
            with self.subTest(trigger=bad):
                with self.assertRaises(CIBudgetError):
                    events = declared_events(bad)
                    if events != ('workflow_dispatch',):
                        raise CIBudgetError('Unexpected event set')

    def test_scoped_twin_push_only_on_named_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / '.github' / 'workflows'
            directory.mkdir(parents=True)
            for name in WORKFLOWS:
                content = 'on:\n  workflow_dispatch:\n'
                if name == 'tests.yml':
                    content = (
                        'on:\n  push:\n    branches:\n      - ' +
                        TWIN_TEST_BRANCH + '\n  workflow_dispatch:\n')
                (directory / name).write_text(content)
            result = audit_workflows(Path(tmp))
            self.assertEqual(result['tests.yml'], ('push', 'workflow_dispatch'))
            for bad in ('main', '*', 'feature/*', TWIN_TEST_BRANCH + '-extra'):
                (directory / 'tests.yml').write_text(
                    'on:\n  push:\n    branches:\n      - ' + bad +
                    '\n  workflow_dispatch:\n')
                with self.subTest(branch=bad), self.assertRaises(CIBudgetError):
                    audit_workflows(Path(tmp))
            (directory / 'tests.yml').write_text(
                'on:\n  push:\n    branches:\n      - ' +
                TWIN_TEST_BRANCH + '\n      - main\n  workflow_dispatch:\n')
            with self.assertRaises(CIBudgetError):
                audit_workflows(Path(tmp))

    def test_audit_blocks_unrecognized_automatic_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / '.github' / 'workflows'
            directory.mkdir(parents=True)
            for name in WORKFLOWS:
                (directory / name).write_text('on:\n  workflow_dispatch:\n')
            (directory / 'surprise.yml').write_text('on:\n  push:\n')
            with self.assertRaisesRegex(CIBudgetError, 'Automatic trigger'):
                audit_workflows(Path(tmp))

    def test_audit_blocks_missing_required_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / '.github' / 'workflows'
            directory.mkdir(parents=True)
            (directory / 'tests.yml').write_text('on:\n  workflow_dispatch:\n')
            with self.assertRaisesRegex(CIBudgetError, 'missing'):
                audit_workflows(Path(tmp))


if __name__ == '__main__':
    unittest.main()
