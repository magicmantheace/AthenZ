import json
import tempfile
import unittest
from pathlib import Path

from athenz.coding import allowed_file, propose, diff_for, change_status, run_tests
from athenz.learning import LearningStore


class FakeModel:
    def __init__(self, changes):
        self.changes = changes
        self.calls = []
    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return json.dumps({'summary': 'Proposed only', 'changes': self.changes})


class CodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.store = LearningStore(self.root / 'private')
        self.addCleanup(self.store.close)
        (self.repo / 'calc.py').write_text('def add(x,y):\n    return x-y\n', encoding='utf-8')

    def test_review_apply_compile_undo_and_reject_approval_after_undo(self):
        model = FakeModel([{'path': 'calc.py', 'new_content': 'def add(x,y):\n    return x+y\n'}])
        pid = propose(self.store, model, str(self.repo), 'Fix add', ['calc.py'])
        self.assertTrue(model.calls[0][1]['json_mode'])
        self.assertIn('+    return x+y', diff_for(self.store, pid))
        self.assertIn('return x-y', (self.repo / 'calc.py').read_text())
        self.assertEqual(change_status(self.store, pid), 1)
        code, out = run_tests(self.store, pid, 'compile')
        self.assertEqual(code, 0, out)
        lesson = self.store.list_items('experiences')[0]
        self.assertEqual(lesson['status'], 'pending')
        with self.assertRaisesRegex(ValueError, 'Syntax parsing'):
            self.store.set_review('experiences', lesson['id'], 'approved')
        self.assertEqual(self.store.approved_experiences(), [])
        self.assertEqual(change_status(self.store, pid, undo=True), 1)
        self.assertIn('return x-y', (self.repo / 'calc.py').read_text())
        self.assertEqual(self.store.approved_experiences(), [])
        with self.assertRaises(ValueError):
            self.store.set_review('experiences', lesson['id'], 'approved')

    def test_out_of_scope_duplicate_and_stale_changes(self):
        model = FakeModel([{'path': 'different.py', 'new_content': 'x=3'}])
        with self.assertRaises(ValueError):
            propose(self.store, model, str(self.repo), 'malicious', ['calc.py'])
        model.changes = [{'path': 'calc.py', 'new_content': 'x=3'}]
        pid = propose(self.store, model, str(self.repo), 'change code', ['calc.py'])
        (self.repo / 'calc.py').write_text('different data', encoding='utf-8')
        with self.assertRaises(ValueError):
            change_status(self.store, pid)
        self.assertEqual(self.store.get_proposal(pid)['status'], 'proposed')

    def test_extended_secret_names_are_not_exposed_to_model(self):
        from athenz.coding import protected_repository_path
        names = ['.env.local', 'credentials.json', 'secrets.yaml',
                 'config/service.pem', '.aws/credentials', '.kube/config',
                 'data/owner.sqlite3', '.git-credentials', 'ID_RSA.backup']
        for name in names:
            with self.subTest(name=name):
                path = self.repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('SYNTHETIC_PRIVATE_CONTENT')
                with self.assertRaises(ValueError):
                    allowed_file(self.repo, name)
        self.assertTrue(protected_repository_path(('config', 'secrets.yaml')))
        self.assertFalse(protected_repository_path(('src', 'main.py')))

    def test_hardlinked_external_file_is_not_approved_for_model_prompt(self):
        import os
        external = self.root / 'synthetic-private-source'
        external.write_text('SYNTHETIC SECRET')
        linked = self.repo / 'ordinary.py'
        try:
            os.link(external, linked)
        except (OSError, NotImplementedError):
            self.skipTest('Hard links unavailable on this test runner')
        with self.assertRaises(ValueError):
            allowed_file(self.repo, 'ordinary.py')

    def test_protects_secrets_traversal_and_symlinks(self):
        (self.repo / '.env').write_text('TOKEN=SECRET')
        with self.assertRaises(ValueError):
            allowed_file(self.repo, '.env')
        with self.assertRaises(ValueError):
            allowed_file(self.repo, '../escape.py')
        folder = self.repo / 'linked.py'
        try:
            folder.symlink_to(self.repo / 'calc.py')
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(ValueError):
                allowed_file(self.repo, 'linked.py')

    def test_rejects_unapproved_arbitrary_test_commands(self):
        model = FakeModel([{'path': 'calc.py', 'new_content': 'x=1'}])
        pid = propose(self.store, model, str(self.repo), 'task', ['calc.py'])
        with self.assertRaises(ValueError):
            run_tests(self.store, pid, 'unittest')
        change_status(self.store, pid)
        with self.assertRaises(ValueError):
            run_tests(self.store, pid, 'rm -rf /')
        self.assertEqual(self.store.list_items('test_runs'), [])
        (self.repo / 'tests').mkdir()
        with self.assertRaisesRegex(ValueError, 'Host tests disabled'):
            run_tests(self.store, pid, 'unittest')


if __name__ == '__main__':
    unittest.main()
