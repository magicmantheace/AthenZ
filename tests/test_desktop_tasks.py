"""Synthetic desktop task actions; no Ollama, external Git, or Docker daemon."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from athenz.desktop_tasks import DesktopTasks, TaskUIError, parse_stages
from athenz.experience import ExperienceStore
from athenz.worker import WorktreeError
from athenz.sequencer import SequenceError


def git(directory, *args):
    return subprocess.run(['git', '-C', str(directory), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


class Model:
    def __init__(self, bad_first=False):
        self.calls = 0
        self.bad_first = bad_first

    def generate(self, messages, **kwargs):
        self.calls += 1
        files = json.loads(messages[-1]['content'])['files']
        changes = []
        for name in files:
            content = 'def value():\n    return 42\n'
            if self.bad_first and self.calls == 1:
                content = 'def bad(:\n  pass\n'
            changes.append({'path': name, 'new_content': content})
        return json.dumps({'summary': 'Synthetic task proposal', 'changes': changes})


class DesktopTaskServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        for rel in ('calc.py', 'util.py'):
            (self.repo / rel).write_text('def value():\n    return 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'fixture')
        self.home = self.root / 'private'
        self.gui = DesktopTasks(self.home)
        self.key = 'demo'

    def start(self, stages=None):
        self.gui.create(self.key, self.repo, 'Fix local synthetic math',
                        stages or [['calc.py'], ['util.py']], confirmed=True)

    def test_stage_input_is_owner_selected_and_bounded(self):
        self.assertEqual(parse_stages(' calc.py , util.py ; util.py '),
                         [['calc.py', 'util.py'], ['util.py']])
        for malformed in ('', 'calc.py;', 'file.txt', 'a.py,a.py',
                          ';a.py', 'a.py,b.py,c.py,d.py,e.py', 'a.py;;;;;b.py'):
            with self.subTest(malformed=malformed), self.assertRaises(TaskUIError):
                parse_stages(malformed)
        with self.assertRaises(TaskUIError):
            self.gui.create('demo', self.repo, 'task', [['calc.py']])
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')

    def test_no_repo_changes_without_review_and_matching_digest(self):
        self.start()
        model = Model()
        proposal = self.gui.prepare(self.key, model=model)
        self.assertEqual(proposal['stage'], 1)
        self.assertEqual(model.calls, 1)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        self.assertEqual(self.gui.detail(self.key)['phase'], 'awaiting_review')
        self.assertIn('calc.py', self.gui.review(self.key)['diff'])
        with self.assertRaises(TaskUIError):
            self.gui.apply(self.key, proposal['sha256'])
        with self.assertRaises(SequenceError):
            self.gui.apply(self.key, '0' * 64, confirmed=True)
        self.assertEqual(self.gui.apply(self.key, proposal['sha256'], confirmed=True)['changed_files'], 1)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        result = self.gui.syntax(self.key)
        self.assertTrue(result['passed'])
        with self.assertRaises(TaskUIError):
            self.gui.advance(self.key)
        self.gui.advance(self.key, confirmed=True)
        self.assertEqual(self.gui.detail(self.key)['phase'], 'ready')
        self.assertEqual(self.gui.detail(self.key)['stage'], 2)
        self.gui.cancel(self.key, discard_changes=True, confirmed=True)

    def test_multi_stage_export_and_restart_keeps_original_clean(self):
        self.start()
        for _ in range(2):
            review = self.gui.prepare(self.key, model=Model())
            self.gui.apply(self.key, review['sha256'], confirmed=True)
            self.assertTrue(self.gui.syntax(self.key)['passed'])
            self.gui.advance(self.key, confirmed=True)
        recovered = DesktopTasks(self.home)
        self.assertEqual(recovered.detail(self.key)['phase'], 'complete')
        with self.assertRaises(TaskUIError):
            recovered.export(self.key)
        bundle = recovered.export(self.key, confirmed=True)
        self.assertEqual(bundle['verification'], 'syntax-only')
        self.assertIn('calc.py', Path(bundle['path']).read_text())
        self.assertIn('util.py', Path(bundle['path']).read_text())
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        recovered.cancel(self.key, discard_changes=True, confirmed=True)
        self.assertTrue(Path(bundle['path']).exists())
        with self.assertRaises(WorktreeError):
            recovered.detail(self.key)

    def test_syntax_failure_rolls_back_and_requires_new_approval(self):
        self.start([['calc.py']])
        bad_model = Model(bad_first=True)
        first = self.gui.prepare(self.key, model=bad_model)
        self.gui.apply(self.key, first['sha256'], confirmed=True)
        result = self.gui.syntax(self.key)
        self.assertFalse(result['passed'])
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(self.gui.detail(self.key)['failures'], 1)
        second = self.gui.prepare(self.key, model=bad_model)
        self.assertNotEqual(first['sha256'], second['sha256'])
        with self.assertRaises(SequenceError):
            self.gui.apply(self.key, first['sha256'], confirmed=True)
        self.gui.apply(self.key, second['sha256'], confirmed=True)
        self.assertTrue(self.gui.syntax(self.key)['passed'])
        self.gui.cancel(self.key, discard_changes=True, confirmed=True)

    def test_checkpoint_recovery_and_detects_unexpected_edits(self):
        self.start([['calc.py']])
        proposal = self.gui.prepare(self.key, model=Model())
        self.assertEqual(DesktopTasks(self.home).review(self.key)['sha256'], proposal['sha256'])
        self.gui.apply(self.key, proposal['sha256'], confirmed=True)
        store = ExperienceStore(self.home)
        try:
            path = Path(store.get_checkpoint(self.key)['state']['workspace'])
        finally:
            store.close()
        (path / 'rogue.txt').write_text('unapproved')
        with self.assertRaises(SequenceError):
            self.gui.recover(self.key)
        with self.assertRaises(SequenceError):
            self.gui.syntax(self.key)
        with self.assertRaises(SequenceError):
            self.gui.cancel(self.key, confirmed=True)
        self.gui.cancel(self.key, discard_changes=True, confirmed=True)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')

    def test_unsupported_legacy_checkpoints_do_not_gain_code_permissions(self):
        store = ExperienceStore(self.home)
        try:
            store.checkpoint('legacy', 'Sensitive note', {'foo': 'bar'})
        finally:
            store.close()
        items = self.gui.list_tasks()
        self.assertEqual(items[0]['type'], 'other')
        self.assertNotIn('bar', str(items))
        with self.assertRaises(WorktreeError):
            self.gui.detail('legacy')
        with self.assertRaises(WorktreeError):
            self.gui.prepare('legacy', model=Model())

    def test_container_testing_requires_confirmation_and_fails_closed(self):
        self.start([['calc.py']])
        proposal = self.gui.prepare(self.key, model=Model())
        self.gui.apply(self.key, proposal['sha256'], confirmed=True)
        self.gui.syntax(self.key)
        self.gui.advance(self.key, confirmed=True)
        with self.assertRaises(TaskUIError):
            self.gui.test(self.key, 'python@sha256:' + 'a'*64)
        with mock.patch('athenz.verification.shutil.which', return_value=None):
            with self.assertRaisesRegex(WorktreeError, 'Docker is unavailable'):
                self.gui.test(self.key, 'python@sha256:' + 'a'*64, confirmed=True)
        self.assertEqual(self.gui.export(self.key, confirmed=True)['verification'], 'syntax-only')
        self.gui.cancel(self.key, discard_changes=True, confirmed=True)

    def test_explicit_cancel_preserves_dirty_tree_by_default(self):
        self.start([['calc.py']])
        proposal = self.gui.prepare(self.key, model=Model())
        self.gui.apply(self.key, proposal['sha256'], confirmed=True)
        with self.assertRaises(TaskUIError):
            self.gui.cancel(self.key, discard_changes=True)
        with self.assertRaises(SequenceError):
            self.gui.cancel(self.key, confirmed=True)
        self.assertEqual(self.gui.detail(self.key)['phase'], 'applied')
        self.gui.cancel(self.key, discard_changes=True, confirmed=True)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')


if __name__ == '__main__':
    unittest.main()
