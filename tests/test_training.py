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

    def test_punctuation_only_heldout_variant_is_not_exported(self):
        self.pair('Should the operator deploy WITHOUT-checking?', 'Unsafe response')
        self.pair('An unrelated instruction?', 'Reviewed response')
        self.store.add_decision(
            'Should the operator deploy without checking!',
            'No', 'Run checks first', source='synthetic', split='test',
            options=['Yes', 'No'])
        report = inspect_dataset(self.store)
        self.assertEqual(report['heldout_excluded'], 1)
        self.assertEqual(report['included'], 1)
        output = build_dataset(self.store, confirmed=True)
        self.assertNotIn('Unsafe response', Path(output['path']).read_text())

    def test_new_heldout_punctuation_variant_invalidates_prior_export(self):
        self.pair('Should the operator merge WITHOUT-tests?', 'Private reviewed answer')
        output = build_dataset(self.store, confirmed=True)
        self.store.add_decision(
            'Should the operator merge without tests!',
            'No', 'Private rationale', source='synthetic',
            split='calibration', options=['Yes', 'No'])
        with self.assertRaisesRegex(DatasetError, 'stale'):
            verify_dataset(self.store, output['sha256'])

    def test_embedded_heldout_scenario_in_training_prompt_is_withheld(self):
        self.pair('Please answer this: Should we bypass the validation checks before deploying? Explain.',
                  'Approval should wait')
        self.pair('Unrelated operator instruction?', 'Safe response')
        self.store.add_decision('Should we bypass the validation checks before deploying?',
            'No', 'Wait for evidence', source='synthetic', split='test',
            options=['Yes', 'No'])
        report = inspect_dataset(self.store)
        self.assertEqual(report['heldout_excluded'], 1)
        result = build_dataset(self.store, confirmed=True)
        self.assertNotIn('Approval should wait', Path(result['path']).read_text())

    def test_distinctive_heldout_rationale_in_training_answer_is_withheld(self):
        private_reason = 'Distinct private fallback policy requires supervisor verification'
        self.pair('Explain the local workflow?', 'The answer cites: ' + private_reason + '.')
        self.pair('Another unrelated topic?', 'Safe reviewed content')
        self.store.add_decision('Would the operator authorize this exception?',
            'Wait', private_reason, source='synthetic', split='test',
            options=['Allow', 'Wait'])
        report = inspect_dataset(self.store)
        self.assertEqual(report['heldout_excluded'], 1)
        result = build_dataset(self.store, confirmed=True)
        self.assertNotIn(private_reason, Path(result['path']).read_text())

    def test_new_heldout_rationale_invalidates_existing_dataset(self):
        private_reason = 'Unique validated remediation protocol must be followed'
        self.pair('Routine explanation?', 'Contains ' + private_reason)
        result = build_dataset(self.store, confirmed=True)
        self.store.add_decision('How do we handle the new exception?',
            'Wait', private_reason, source='synthetic', split='calibration',
            options=['Allow', 'Wait'])
        with self.assertRaisesRegex(DatasetError, 'stale'):
            verify_dataset(self.store, result['sha256'])

    def test_short_common_words_do_not_block_unrelated_training(self):
        self.pair('What should we run after edits?', 'Please run tests')
        self.store.add_decision('Run tests', 'Yes', 'Run tests',
            source='synthetic', split='test', options=['Yes', 'No'])
        report = inspect_dataset(self.store)
        self.assertEqual((report['included'], report['heldout_excluded']), (1, 0))

    def test_shared_prefix_without_full_protected_phrase_is_allowed(self):
        self.pair('Should we bypass the validation checks before training?',
                  'Do not alter actual evaluation cases')
        self.store.add_decision('Should we bypass the validation checks before deploying?',
            'No', 'Wait for the proper deployment gate',
            source='synthetic', split='calibration', options=['Yes', 'No'])
        report = inspect_dataset(self.store)
        self.assertEqual((report['included'], report['heldout_excluded']), (1, 0))

    def test_indexed_embedded_leak_with_multiple_protected_cases(self):
        self.pair('Write a summary: Should the operator deploy without verification? Then explain.',
                  'Not a safe training response')
        self.pair('Safe distinct instruction?', 'Safe distinct response')
        for number in range(30):
            self.store.add_decision(f'Distinct unrelated scenario with tag {number}',
                'No', f'Unrelated rationale for synthetic case number {number}',
                source='synthetic', split='test', options=['Yes', 'No'])
        self.store.add_decision('Should the operator deploy without verification?',
            'No', 'Unique private holdout rationale requiring review',
            source='synthetic', split='test', options=['Yes', 'No'])
        report = inspect_dataset(self.store)
        self.assertEqual((report['included'], report['heldout_excluded']), (1, 1))

    def test_near_duplicate_heldout_question_is_withheld_from_training(self):
        self.pair(
            'Would the owner authorize deployment after all automated validation checks pass today?',
            'Private answer should not train')
        self.pair('Independent instruction?', 'Safe response')
        self.store.add_decision(
            'Would the owner authorize deployment after all automated local validation checks pass today?',
            'No', 'Private held-out rationale',
            source='synthetic', options=['Yes', 'No'], split='test')
        report = inspect_dataset(self.store)
        self.assertEqual((report['included'], report['heldout_excluded']), (1, 1))
        exported = build_dataset(self.store, confirmed=True)
        self.assertNotIn('Private answer should not train', Path(exported['path']).read_text())

    def test_new_near_duplicate_private_rationale_revokes_existing_export(self):
        self.pair(
            'Independent operation question?',
            'Only approvals signed by two separate senior reviewers may authorize emergency deployment today')
        export = build_dataset(self.store, confirmed=True)
        self.store.add_decision(
            'May the operator approve this exception?', 'Wait',
            'Only approvals signed by two separate reviewers may authorize emergency deployment today',
            source='synthetic', options=['Allow', 'Wait'], split='calibration')
        with self.assertRaisesRegex(DatasetError, 'stale'):
            verify_dataset(self.store, export['sha256'])

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
        self.assertEqual(set(commands), {'inspect', 'inspect-heldout', 'learning-plan', 'session-start', 'session-baseline', 'session-status', 'session-link-run', 'session-link-report', 'session-close', 'session-cancel', 'build', 'verify', 'delete', 'compare', 'prepare-qlora', 'verify-qlora', 'run-qlora', 'register-adapter', 'selection', 'select-adapter', 'rollback-adapter', 'runtime-status', 'runtime-rollback-readiness', 'runtime-rehearse-rollback', 'runtime-activate', 'runtime-rollback', 'prepare-import', 'verify-import', 'lineage-audit', 'import-local', 'prepare-conversion', 'run-conversion', 'pause-conversion', 'verify-conversion'})


if __name__ == '__main__':
    unittest.main()
