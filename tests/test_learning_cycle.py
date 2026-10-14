"""Synthetic end-to-end offline learning planning: no real model or personal data."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.experience import ExperienceStore
from athenz.learning_cycle import LearningCycleError, inspect_learning_cycle
from athenz.training import build_dataset


class LearningCycleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ExperienceStore(Path(tmp.name) / 'private')
        self.addCleanup(self.store.close)

    def approve_pair(self, instruction='Synthetic verified task request',
                     answer='Synthetic approved implementation'):
        self.store.add_message('synthetic', 'agent', 'user', instruction)
        mid = self.store.add_message('synthetic', 'agent', 'assistant', 'synthetic original')
        self.store.add_feedback(mid, 'down', answer)
        row = self.store.db.execute('SELECT id FROM train_pairs ORDER BY id DESC LIMIT 1').fetchone()
        self.store.set_review('train_pairs', row['id'], 'approved')
        return row['id']

    def fill_heldout(self, *, count=10):
        for n in range(count):
            self.store.add_decision(
                f'Would an owner keep synthetic test batch number {n} separate from training?',
                'Wait', 'PRIVATE-EVAL-REASON-NOT-TO-PRINT',
                source='synthetic', options=['Wait', 'Proceed'],
                split='calibration', approved=True)

    def test_approved_dataset_fingerprint_streams_bounded_rows(self):
        from athenz.training import _render
        self.approve_pair(instruction='Synthetic first sample', answer='First response')
        self.approve_pair(instruction='Synthetic second sample', answer='Second response')
        with mock.patch('athenz.learning_cycle._render', wraps=_render) as renderer:
            report = inspect_learning_cycle(self.store)
        self.assertTrue(report['training_sources_eligible'])
        self.assertEqual(report['training']['included'], 2)
        self.assertGreaterEqual(renderer.call_count, 4)  # before and after
        self.assertTrue(all(len(call.args[0]) == 1
                            for call in renderer.call_args_list))

    def test_empty_plan_is_a_sanitized_blocker_without_dataset_directory(self):
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('No model requests')):
            result = inspect_learning_cycle(self.store)
        self.assertEqual(result['next_step'], 'approve-distinct-training-examples')
        self.assertEqual(result['training']['included'], 0)
        self.assertEqual(result['dataset_snapshot'], 'not-selected')
        self.assertFalse(result['ready_for_manual_model_comparison'])
        self.assertFalse(result['training_started'])
        self.assertFalse(result['promotion_authorized'])
        self.assertFalse((self.store.home / 'datasets').exists())

    def test_heldout_shortage_blocks_a_ready_training_source(self):
        self.approve_pair()
        result = inspect_learning_cycle(self.store)
        self.assertTrue(result['training_sources_eligible'])
        self.assertEqual(result['next_step'], 'review-heldout-evaluation-cases')
        self.assertFalse(result['heldout']['minimum_cases_met'])
        self.assertEqual(result['dataset_snapshot'], 'not-selected')

    def test_training_and_heldout_ready_but_snapshot_requires_owner_action(self):
        self.approve_pair()
        self.fill_heldout()
        report = inspect_learning_cycle(self.store)
        self.assertTrue(report['heldout']['ready_for_owner_review'])
        self.assertTrue(report['source_snapshot_stable'])
        self.assertEqual(report['next_step'], 'export-reviewed-dataset-with-explicit-confirmation')
        self.assertFalse(report['dataset_verified'])
        self.assertFalse(report['ready_for_manual_model_comparison'])
        self.assertFalse((self.store.home / 'datasets').exists())
        self.assertNotIn('PRIVATE-EVAL-REASON', json.dumps(report))

    def test_valid_existing_snapshot_allows_manual_comparison_only(self):
        self.approve_pair()
        self.fill_heldout()
        saved = build_dataset(self.store, confirmed=True)
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('No network model inventory')), \
             mock.patch('athenz.finetune.execute_run',
                        side_effect=AssertionError('No training')):
            result = inspect_learning_cycle(self.store, dataset_sha256=saved['sha256'])
        self.assertEqual(result['dataset_snapshot'], 'verified')
        self.assertTrue(result['dataset_verified'])
        self.assertTrue(result['ready_for_manual_model_comparison'])
        self.assertEqual(result['next_step'], 'owner-may-compare-installed-local-models')
        self.assertFalse(result['model_called'])
        self.assertFalse(result['model_selected'])
        self.assertNotIn(saved['sha256'], json.dumps(result))
        self.assertNotIn(str(self.store.home), json.dumps(result))
        self.assertNotIn('Synthetic verified task request', json.dumps(result))

    def test_missing_snapshot_does_not_create_dataset_folder(self):
        self.approve_pair()
        self.fill_heldout()
        result = inspect_learning_cycle(self.store, dataset_sha256='f' * 64)
        self.assertEqual(result['dataset_snapshot'], 'missing-or-stale')
        self.assertEqual(result['next_step'], 'repair-or-rebuild-reviewed-dataset')
        self.assertFalse((self.store.home / 'datasets').exists())

    def test_changed_dataset_or_revoked_review_is_sanitized_and_fails_closed(self):
        pair = self.approve_pair()
        self.fill_heldout()
        saved = build_dataset(self.store, confirmed=True)
        path = Path(saved['path'])
        path.write_text('CORRUPTED PRIVATE SAMPLE', encoding='utf-8')
        result = inspect_learning_cycle(self.store, dataset_sha256=saved['sha256'])
        self.assertEqual(result['dataset_snapshot'], 'missing-or-stale')
        self.assertFalse(result['ready_for_manual_model_comparison'])
        self.assertNotIn('CORRUPTED', json.dumps(result))
        path.write_bytes(b'')  # No further access to the now-invalid snapshot
        self.store.set_review('train_pairs', pair, 'rejected')
        result = inspect_learning_cycle(self.store, dataset_sha256=saved['sha256'])
        self.assertFalse(result['training_sources_eligible'])
        self.assertEqual(result['next_step'], 'approve-distinct-training-examples')

    def test_conflicts_block_readiness_even_with_heldout_examples(self):
        self.approve_pair(answer='Synthetic safe response')
        self.approve_pair(answer='Synthetic different response')
        self.fill_heldout()
        result = inspect_learning_cycle(self.store)
        self.assertGreater(result['training']['conflicts'], 0)
        self.assertEqual(result['next_step'], 'resolve-reviewed-training-conflicts')
        self.assertFalse(result['ready_for_manual_model_comparison'])

    def test_duplicate_heldout_cases_do_not_enable_model_comparison(self):
        self.approve_pair()
        self.fill_heldout()
        self.store.add_decision(
            'Would an owner keep synthetic test batch number 0 separate from training!',
            'Wait', 'PRIVATE-DUPLICATE-REASON', source='synthetic',
            options=['Wait', 'Proceed'], split='calibration', approved=True)
        result = inspect_learning_cycle(self.store)
        self.assertFalse(result['heldout']['selected_cases_independent'])
        self.assertFalse(result['heldout']['ready_for_owner_review'])
        self.assertEqual(result['next_step'], 'review-heldout-evaluation-cases')
        self.assertNotIn('PRIVATE-DUPLICATE-REASON', json.dumps(result))

    def test_changed_evidence_during_preflight_never_reports_ready(self):
        self.approve_pair()
        self.fill_heldout()
        from athenz.learning_cycle import _review_snapshot
        original = _review_snapshot
        called = {'count': 0}
        def drifting(*args, **kwargs):
            snapshot = original(*args, **kwargs)
            called['count'] += 1
            return snapshot if called['count'] == 1 else ('drift', *snapshot[1:])
        with mock.patch('athenz.learning_cycle._review_snapshot', side_effect=drifting):
            report = inspect_learning_cycle(self.store)
        self.assertEqual(called['count'], 2)
        self.assertFalse(report['source_snapshot_stable'])
        self.assertEqual(report['next_step'], 'repeat-preflight-after-source-changes')

    def test_cli_is_offline_and_exposes_aggregates_only(self):
        self.approve_pair()
        self.fill_heldout()
        from athenz.train_cli import main, parser
        args = parser().parse_args(['learning-plan', '--min-cases', '10'])
        self.assertEqual(args.command, 'learning-plan')
        with mock.patch('athenz.train_cli.OllamaClient',
                        side_effect=AssertionError('No Ollama')), \
             mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('No model inventory')), \
             mock.patch('builtins.print') as printing:
            main(['--home', str(self.store.home), 'learning-plan'])
        report = json.loads(printing.call_args.args[0])
        self.assertTrue(report['training_sources_eligible'])
        self.assertFalse(report['ready_for_manual_model_comparison'])
        self.assertNotIn('PRIVATE-', json.dumps(report))

    def test_invalid_inputs_rejected_without_creating_dataset_artifacts(self):
        for kwargs in ({'seed': True}, {'limit': 0}, {'min_cases': 1},
                       {'limit': 10, 'min_cases': 11}, {'split': 'train'},
                       {'dataset_sha256': 'not a digest'},
                       {'dataset_sha256': 123}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(LearningCycleError):
                    inspect_learning_cycle(self.store, **kwargs)
        self.assertFalse((self.store.home / 'datasets').exists())


if __name__ == '__main__':
    unittest.main()
