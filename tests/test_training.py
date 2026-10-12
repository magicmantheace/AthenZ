"""Synthetic owner-feedback SFT export gates; no real private data or training."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from athenz.experience import ExperienceStore
from athenz.training import (DatasetError, build_dataset, delete_dataset,
                             inspect_dataset, verify_dataset)
from athenz.train_cli import parser


class TrainingDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)

    def pair(self, instruction, answer, approved=True):
        mid = self.store.add_message('synthetic', 'twin', 'user', instruction)
        assistant = self.store.add_message('synthetic', 'twin', 'assistant', 'Bad output')
        self.store.add_feedback(assistant, 'down', answer)
        # Feedback creates pending training pairs; explicit approval is separate.
        row = self.store.db.execute('SELECT id FROM train_pairs ORDER BY id DESC LIMIT 1').fetchone()
        self.assertIsNotNone(row)
        if approved:
            self.store.set_review('train_pairs', row['id'], 'approved')
        return row['id']

    def test_only_approved_and_explicit_confirmation(self):
        self.pair('Synthetic introduction?', 'Reviewed synthetic response.')
        self.pair('Unreviewed question?', 'Never exported', approved=False)
        self.assertEqual(inspect_dataset(self.store)['included'], 1)
        with self.assertRaisesRegex(DatasetError, 'confirm'):
            build_dataset(self.store)
        result = build_dataset(self.store, confirmed=True)
        data = Path(result['path'])
        self.assertEqual(result['count'], 1)
        self.assertTrue(data.resolve().is_relative_to(self.store.home.resolve()))
        self.assertNotIn('Never exported', data.read_text())
        parsed = json.loads(data.read_text().splitlines()[0])
        self.assertEqual(parsed['messages'][1]['content'], 'Reviewed synthetic response.')
        self.assertEqual(hashlib.sha256(data.read_bytes()).hexdigest(), result['sha256'])
        self.assertTrue(verify_dataset(self.store, result['sha256'])['valid'])

    def test_normalized_heldout_overlap_is_withheld(self):
        self.pair('  Should    I   SHIP? ', 'Ship without checking')
        self.pair('Unrelated choice?', 'Check first')
        self.store.add_decision('should i ship?', 'No', 'Run tests', source='synthetic', split='test', options=['Yes', 'No'])
        report = inspect_dataset(self.store)
        self.assertEqual(report['heldout_excluded'], 1)
        self.assertEqual(report['included'], 1)
        built = build_dataset(self.store, confirmed=True)
        self.assertNotIn('Ship without checking', Path(built['path']).read_text())

    def test_conflicting_approved_replies_block_export(self):
        self.pair('What is rule?', 'Always test first')
        self.pair(' WHAT IS RULE? ', 'Never run tests')
        self.assertEqual(inspect_dataset(self.store)['conflicts'], 1)
        with self.assertRaisesRegex(DatasetError, 'conflicting'):
            build_dataset(self.store, confirmed=True)
        self.assertFalse((self.store.home / 'datasets').exists())

    def test_duplicate_same_target_deduplicates(self):
        self.pair('Say hello?', 'Hello there')
        self.pair('SAY    hello?', 'hello THERE')
        r = build_dataset(self.store, confirmed=True)
        self.assertEqual((r['count'], r['duplicates']), (1, 1))
        self.assertEqual(len(Path(r['path']).read_text().splitlines()), 1)

    def test_repeat_is_idempotent_and_changed_bytes_rejected(self):
        self.pair('First?', 'Approved')
        a = build_dataset(self.store, confirmed=True)
        b = build_dataset(self.store, confirmed=True)
        self.assertEqual(a['sha256'], b['sha256'])
        self.assertTrue(b['reused'])
        Path(a['path']).write_text('tampered\n')
        with self.assertRaisesRegex(DatasetError, 'changed'):
            verify_dataset(self.store, a['sha256'])
        with self.assertRaises(DatasetError):
            build_dataset(self.store, confirmed=True)

    def test_revoke_or_heldout_change_invalidates_existing_export(self):
        pair_id = self.pair('First task?', 'Reviewed')
        r = build_dataset(self.store, confirmed=True)
        self.store.set_review('train_pairs', pair_id, 'rejected')
        with self.assertRaisesRegex(DatasetError, 'stale'):
            verify_dataset(self.store, r['sha256'])
        self.store.set_review('train_pairs', pair_id, 'approved')
        self.assertTrue(verify_dataset(self.store, r['sha256'])['valid'])
        self.store.add_decision('first task?', 'N', 'synthetic', source='synthetic', split='calibration', options=['Y', 'N'])
        with self.assertRaisesRegex(DatasetError, 'stale'):
            verify_dataset(self.store, r['sha256'])

    def test_rejects_git_home_and_symlink_destination(self):
        # A `.git` directory makes a location unsuitable even when it is not
        # recognized as an initialized remote repository.
        risky = self.root / 'repo'
        risky.mkdir()
        (risky / '.git').mkdir()
        # Reject unsafe profile creation itself, before training can access it.
        with self.assertRaisesRegex(ValueError, 'Git checkout'):
            ExperienceStore(risky / 'data')
        self.assertFalse((risky / 'data').exists())
        self.pair('Normal?', 'Approval')
        try:
            (self.store.home / 'datasets').symlink_to(self.root)
        except (OSError, NotImplementedError):
            # Windows runners may not grant symlink creation privileges.
            return
        with self.assertRaisesRegex(DatasetError, 'symlink'):
            build_dataset(self.store, confirmed=True)

    def test_private_delete_scoped_and_opt_in(self):
        self.pair('One?', 'Yes')
        out = build_dataset(self.store, confirmed=True)
        with self.assertRaisesRegex(DatasetError, 'confirm'):
            delete_dataset(self.store, out['sha256'])
        with self.assertRaises(DatasetError):
            delete_dataset(self.store, '../invalid', confirmed=True)
        self.assertTrue(delete_dataset(self.store, out['sha256'], confirmed=True))
        self.assertFalse(delete_dataset(self.store, out['sha256'], confirmed=True))
        self.assertFalse(Path(out['path']).exists())
        self.assertFalse(Path(out['manifest']).exists())

    def test_cli_has_no_train_or_deploy_command(self):
        commands = parser()._subparsers._group_actions[0].choices
        self.assertEqual(set(commands), {'inspect', 'build', 'verify', 'delete', 'compare', 'prepare-qlora', 'verify-qlora', 'run-qlora', 'register-adapter', 'selection', 'select-adapter', 'rollback-adapter', 'runtime-status', 'runtime-activate', 'runtime-rollback', 'prepare-import', 'verify-import', 'import-local', 'prepare-conversion', 'run-conversion', 'verify-conversion'})


if __name__ == '__main__':
    unittest.main()
