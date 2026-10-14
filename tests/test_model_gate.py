"""Synthetic aggregate model-benchmark gates; never call Ollama or train."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.experience import ExperienceStore
from athenz.model_gate import (BenchmarkError, compare_models, save_report,
                               inspect_heldout_readiness)
from athenz.evaluation import _fingerprint, _heldout_rows, _reference_fingerprint
from athenz.training import build_dataset


class Model:
    def __init__(self, name):
        self.model = name


class EvaluationGateTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        digest_patch = mock.patch('athenz.runtime.model_digest', side_effect=lambda tag: 'a'*64 if tag in {'base', 'base-local'} else 'b'*64)
        digest_patch.start()
        self.addCleanup(digest_patch.stop)
        self.store = ExperienceStore(Path(t.name) / 'private')
        self.addCleanup(self.store.close)
        self.store.add_message('s', 'agent', 'user', 'synthetic training question')
        response = self.store.add_message('s', 'agent', 'assistant', 'synthetic response')
        self.store.add_feedback(response, 'up')
        row = self.store.db.execute('SELECT id FROM train_pairs').fetchone()
        self.store.set_review('train_pairs', row['id'], 'approved')
        self.pair = row['id']
        self.sha = build_dataset(self.store, confirmed=True)['sha256']
        for i in range(12):
            self.store.add_decision(f'synthetic held-out scenario {i}', 'yes', 'synthetic reason',
                                    source='synthetic', options=['yes','no'], split='calibration',
                                    approved=True)

    def observations(self, first=5, second=9, offset=0, limit=100):
        ids = [r['id'] for r in self.store.db.execute(
            "SELECT id FROM decisions WHERE split='calibration' ORDER BY id LIMIT ?",
            (limit,))]
        heldout_sha = _fingerprint(_heldout_rows(self.store, 'calibration', limit))
        reference_sha = _reference_fingerprint(self.store)
        def one(correct, tweak=0):
            return {'heldout_sha256': heldout_sha, 'reference_sha256': reference_sha,
                    'total':len(ids), 'correct':correct, 'accuracy':correct/len(ids),
                    'chance_expected':0.5, 'cases':[{'id':i + tweak,'expected':'A',
                    'predicted':'A' if index < correct else 'B',
                    'correct': index < correct} for index, i in enumerate(ids)]}
        return [one(first), one(second, offset)]

    def test_readonly_preflight_flags_duplicate_calibration_samples_privately(self):
        self.store.add_decision('synthetic held-out scenario 0!', 'yes',
                                'DO NOT DISCLOSE private duplicate reason',
                                source='synthetic', options=['yes', 'no'],
                                split='calibration', approved=True)
        report = inspect_heldout_readiness(self.store, min_cases=10)
        self.assertEqual(report['selected_cases'], 13)
        self.assertFalse(report['selected_cases_independent'])
        self.assertFalse(report['ready_for_owner_review'])
        self.assertTrue(report['minimum_cases_met'])
        self.assertTrue(report['split_independence_check'] == 'lexical-pass')
        self.assertNotIn('DO NOT DISCLOSE', json.dumps(report))
        self.assertFalse(report['model_called'])

    def test_comparison_refuses_duplicates_before_model_inventory_calls(self):
        self.store.add_decision('synthetic held-out scenario 0!', 'yes',
                                'Private rationale', source='synthetic',
                                options=['yes', 'no'], split='calibration',
                                approved=True)
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('No model inventory before preflight')):
            with self.assertRaisesRegex(ValueError, 'Repeated held-out'):
                compare_models(self.store, Model('base'), Model('candidate'),
                               self.sha)
 
    def test_comparison_save_refuses_duplicate_benchmarks_after_review(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha)
        first = self.store.db.execute(
            "SELECT scenario FROM decisions WHERE status='approved' AND split='calibration' "
            "ORDER BY id LIMIT 1").fetchone()['scenario']
        last_id = self.store.db.execute(
            "SELECT id FROM decisions WHERE status='approved' AND split='calibration' "
            "ORDER BY id DESC LIMIT 1").fetchone()['id']
        self.store.db.execute('UPDATE decisions SET scenario=? WHERE id=?',
                              (first + '!', last_id))
        self.store.db.commit()
        # Isolate the new evaluation-sample check from the independent
        # dataset-consent guard, which would also reject the changed source.
        with mock.patch('athenz.model_gate.verify_dataset'):
            with self.assertRaisesRegex(BenchmarkError, 'independence failed'):
                save_report(self.store, report, confirmed=True)

    def test_candidate_comparison_has_no_personal_text_and_no_promotion(self):
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations()) as ev:
            report = compare_models(self.store, Model('base-local'), Model('candidate-local'),
                                    self.sha, min_cases=10)
        self.assertEqual(ev.call_count, 2)
        self.assertTrue(all(call.kwargs['seed'] == 42 and call.kwargs['split'] == 'calibration'
                            for call in ev.call_args_list))
        self.assertTrue(report['eligible_for_review'])
        self.assertEqual(report['promotion'], 'not-authorized')
        self.assertEqual(report['cases'], 12)
        self.assertEqual(report['baseline_digest'], 'a'*64)
        self.assertEqual(report['candidate_digest'], 'b'*64)
        self.assertNotIn('synthetic held-out scenario', str(report))
        with self.assertRaisesRegex(BenchmarkError, 'confirm'):
            save_report(self.store, report)
        saved = save_report(self.store, report, confirmed=True)
        self.assertTrue(Path(saved['path']).resolve().is_relative_to(self.store.home.resolve()))
        self.assertEqual(hashlib.sha256(Path(saved['path']).read_bytes()).hexdigest(), saved['sha256'])
        self.assertEqual(save_report(self.store, report, confirmed=True), saved)

    def test_full_approved_population_is_bound_to_comparison(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha, limit=100)
        self.assertEqual(report['requested_case_limit'], 100)
        self.assertEqual(report['approved_split_total'], 12)
        self.assertEqual(len(report['approved_split_sha256']), 64)
        self.assertEqual(report['cases'], 12)
        self.assertTrue(save_report(self.store, report, confirmed=True))

    def test_appended_unscored_heldout_case_invalidates_report(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha, limit=12)
        self.assertEqual(report['requested_case_limit'], 12)
        self.assertEqual(report['approved_split_total'], 12)
        self.store.add_decision(
            'Should the owner separately audit an unrelated review ledger?',
            'yes', 'PRIVATE GOLD NEW CASE',
            source='synthetic', options=['yes', 'no'], split='calibration',
            approved=True)
        with self.assertRaisesRegex(BenchmarkError, 'population changed'):
            save_report(self.store, report, confirmed=True)
        self.assertFalse((self.store.home / 'datasets' / 'evaluations').exists())

    def test_appended_out_of_window_case_mid_comparison_is_rejected(self):
        reports = self.observations()
        count = {'calls': 0}
        def inject(*args, **kwargs):
            count['calls'] += 1
            result = reports[count['calls'] - 1]
            if count['calls'] == 2:
                self.store.add_decision(
                    'Will a separate synthetic review verify immutable labels?',
                    'yes', 'PRIVATE GOLD OUT OF WINDOW',
                    source='synthetic', options=['yes', 'no'],
                    split='calibration', approved=True)
            return result
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=inject):
            with self.assertRaisesRegex(BenchmarkError, 'population changed'):
                compare_models(self.store, Model('base'), Model('candidate'),
                               self.sha, limit=12)
        self.assertEqual(count['calls'], 2)

    def test_unscored_heldout_evidence_edit_invalidates_saved_report(self):
        outside = self.store.add_decision(
            'Should another independent owner audit precede the optional release?',
            'yes', 'PRIVATE OUTSIDE WINDOW GOLD', source='synthetic',
            options=['yes', 'no'], split='calibration', approved=True)
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations(limit=12)):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha, limit=12)
        self.assertEqual(report['cases'], 12)
        self.assertEqual(report['approved_split_total'], 13)
        with self.store.db:
            self.store.db.execute('UPDATE decisions SET rationale=? WHERE id=?',
                                  ('CHANGED PRIVATE OUTSIDE WINDOW', outside))
        with self.assertRaisesRegex(BenchmarkError, 'population changed'):
            save_report(self.store, report, confirmed=True)
        self.assertFalse((self.store.home / 'datasets' / 'evaluations').exists())

    def test_forged_population_metadata_never_persists(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha)
        mutations = ({'requested_case_limit': True},
                     {'requested_case_limit': 1},
                     {'approved_split_total': 8},
                     {'approved_split_total': False},
                     {'approved_split_sha256': 'bad-digest'})
        for change in mutations:
            with self.subTest(change=change):
                with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
                    save_report(self.store, {**report, **change}, confirmed=True)
        with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
            save_report(self.store,
                        {k: v for k, v in report.items() if k != 'requested_case_limit'},
                        confirmed=True)

    def test_new_reports_require_population_and_paired_metadata(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha)
        self.assertEqual(report['schema'], 2)
        for removed in ('requested_case_limit', 'approved_split_total',
                        'approved_split_sha256', 'baseline_correct',
                        'paired_improved', 'baseline_digest'):
            with self.subTest(removed=removed):
                altered = {k: v for k, v in report.items() if k != removed}
                with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
                    save_report(self.store, altered, confirmed=True)
        with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
            save_report(self.store, {**report, 'schema': True}, confirmed=True)

    def test_comparison_carries_aggregate_uncertainty_only(self):
        reports = self.observations()
        reports[0]['accuracy_interval_95'] = [0.15, 0.72]
        reports[1]['accuracy_interval_95'] = [0.46, 0.94]
        reports[0]['invalid_predictions'] = 2
        for case in reports[0]['cases'][-2:]:
            case['predicted'] = None
        reports[1]['invalid_predictions'] = 0
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=reports):
            result = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha)
        self.assertEqual(result['baseline_accuracy_interval_95'], [0.15, 0.72])
        self.assertEqual(result['candidate_accuracy_interval_95'], [0.46, 0.94])
        self.assertEqual(result['baseline_invalid_predictions'], 2)
        self.assertEqual(result['candidate_invalid_predictions'], 0)
        self.assertNotIn('synthetic held-out scenario', str(result))
        self.assertEqual(result['promotion'], 'not-authorized')

    def test_save_report_rejects_invalid_accuracy_gain(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            original = compare_models(self.store, Model('base'),
                                      Model('candidate'), self.sha)
        for value in (float('nan'), float('inf'), -float('inf'), True, 1.5):
            with self.subTest(value=str(value)):
                altered = {**original, 'accuracy_gain': value}
                with self.assertRaisesRegex(BenchmarkError, 'Invalid observed accuracy gain'):
                    save_report(self.store, altered, confirmed=True)

    def test_paired_candidate_evidence_and_exact_probability(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations(5, 9)):
            result = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        self.assertEqual((result['paired_improved'], result['paired_regressed'],
                          result['paired_unchanged']), (4, 0, 8))
        self.assertEqual(result['paired_one_sided_p_value'], 0.0625)
        self.assertTrue(result['eligible_for_review'])
        self.assertEqual(result['promotion'], 'not-authorized')
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations(9, 5)):
            worse = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        self.assertEqual((worse['paired_improved'], worse['paired_regressed']), (0, 4))
        self.assertEqual(worse['paired_one_sided_p_value'], 1.0)

    def test_inconsistent_observed_case_totals_refused(self):
        for change in ('wrong_correct', 'wrong_accuracy', 'false_case',
                       'invalid_prediction_count', 'boolean_seed'):
            cases = self.observations()
            if change == 'wrong_correct':
                cases[1]['correct'] = 100
            elif change == 'wrong_accuracy':
                cases[1]['accuracy'] = 0.01
            elif change == 'false_case':
                cases[1]['cases'][0]['correct'] = False
            elif change == 'invalid_prediction_count':
                cases[1]['invalid_predictions'] = 1
            with self.subTest(change=change):
                with mock.patch('athenz.model_gate.evaluate_decisions',
                                side_effect=cases):
                    with self.assertRaisesRegex(BenchmarkError,
                                                 'evaluation|Evaluation|sample count'):
                        compare_models(self.store, Model('base'),
                                       Model('candidate'), self.sha,
                                       seed=True if change == 'boolean_seed' else 42)

    def test_paired_probability_no_discordance(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations(8, 8)):
            report = compare_models(self.store, Model('base'),
                                    Model('candidate'), self.sha)
        self.assertEqual(report['paired_improved'], 0)
        self.assertEqual(report['paired_regressed'], 0)
        self.assertEqual(report['paired_one_sided_p_value'], 1.0)

    def test_saved_comparison_rejects_inconsistent_calculated_evidence(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            valid = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        cases = [
            {**valid, 'baseline_correct': 11},
            {**valid, 'candidate_accuracy': 0.999},
            {**valid, 'accuracy_gain': 0.2},
            {**valid, 'paired_regressed': valid['paired_regressed'] + 1},
            {**valid, 'paired_one_sided_p_value': 0.000001},
            {**valid, 'paired_unchanged': -1},
        ]
        for modified in cases:
            with self.subTest(fields=[key for key in modified if modified[key] != valid.get(key)]):
                with self.assertRaisesRegex(BenchmarkError, 'inconsistent'):
                    save_report(self.store, modified, confirmed=True)

    def test_new_cross_split_overlap_before_saving_requires_reevaluation(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        self.store.add_decision('Synthetic held-out scenario 1!',
            'yes', 'Private split contamination', source='synthetic',
            options=['yes', 'no'], split='test', approved=True)
        with self.assertRaisesRegex(BenchmarkError, 'partitions overlap'):
            save_report(self.store, report, confirmed=True)

    def test_report_persistence_rejects_forged_case_identity_digest(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            valid = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        forged = {**valid, 'case_ids_sha256': '0' * 64}
        with self.assertRaisesRegex(BenchmarkError, 'case identities changed'):
            save_report(self.store, forged, confirmed=True)

    def test_report_persistence_rejects_partial_or_identical_model_digests(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            valid = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        for altered in (
                {**valid, 'candidate_digest': 'a' * 64},
                {**valid, 'candidate_digest': 'not-a-digest'},
                {key: value for key, value in valid.items() if key != 'baseline_digest'}):
            with self.subTest(altered=altered.get('candidate_digest')):
                with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
                    save_report(self.store, altered, confirmed=True)

    def test_legacy_comparison_rejects_one_sided_model_digest(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            full = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        legacy = {key: value for key, value in full.items()
                  if key not in ('baseline_correct', 'candidate_correct',
                                 'baseline_accuracy', 'candidate_accuracy',
                                 'paired_improved', 'paired_regressed',
                                 'paired_unchanged', 'paired_one_sided_p_value')}
        # Genuine historical schema-one records predate paired statistics.
        legacy['schema'] = 1
        self.assertTrue(save_report(self.store, legacy, confirmed=True))
        malformed = {key: value for key, value in legacy.items()
                     if key != 'candidate_digest'}
        with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
            save_report(self.store, malformed, confirmed=True)

    def test_save_refuses_model_tag_replaced_after_evaluation(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha)
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag: 'a' * 64 if tag == 'base' else 'c' * 64):
            with self.assertRaisesRegex(BenchmarkError, 'digest changed'):
                save_report(self.store, report, confirmed=True)
        self.assertFalse(list((self.store.home / 'datasets' / 'evaluations').glob(
            'eval-*.json')) if (self.store.home / 'datasets' / 'evaluations').exists() else [])

    def test_save_refuses_fabricated_intervals_and_invalid_counts(self):
        from athenz.evaluation import _wilson_interval
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            valid = compare_models(self.store, Model('base'), Model('candidate'),
                                   self.sha)
        valid = {**valid, 'baseline_accuracy_interval_95':
                 _wilson_interval(valid['baseline_correct'], valid['cases']),
                 'candidate_accuracy_interval_95':
                 _wilson_interval(valid['candidate_correct'], valid['cases']),
                 'baseline_invalid_predictions': 1}
        self.assertTrue(save_report(self.store, valid, confirmed=True))
        for changed in (
            {'baseline_accuracy_interval_95': [0.0, 1.0]},
            {'candidate_accuracy_interval_95': [float('nan'), 1.0]},
            {'baseline_invalid_predictions': 12},
            {'candidate_invalid_predictions': True},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
                    save_report(self.store, {**valid, **changed}, confirmed=True)

    def test_comparison_rejects_conflicting_or_malformed_chance_baselines(self):
        for malformed in (float('nan'), float('inf'), -0.1, 0, 0.9, True):
            reports = self.observations()
            reports[1]['chance_expected'] = malformed
            with self.subTest(chance=malformed):
                with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=reports):
                    with self.assertRaisesRegex(BenchmarkError, 'chance baseline'):
                        compare_models(self.store, Model('base'), Model('candidate'),
                                       self.sha)
        reports = self.observations()
        reports[1]['chance_expected'] = 0.4
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=reports):
            with self.assertRaisesRegex(BenchmarkError, 'chance baselines disagree'):
                compare_models(self.store, Model('base'), Model('candidate'),
                               self.sha)

    def test_report_save_rejects_fabricated_chance_expected(self):
        with mock.patch('athenz.model_gate.evaluate_decisions',
                        side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'),
                                    self.sha)
        for invalid in (0, -0.1, 1.0, 'none', float('inf'), True):
            with self.subTest(chance=invalid):
                with self.assertRaisesRegex(BenchmarkError, 'metadata is inconsistent'):
                    save_report(self.store, {**report, 'chance_expected': invalid},
                                confirmed=True)

    def test_heldout_readiness_is_readonly_aggregate_and_bounded(self):
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('no Ollama access')):
            report = inspect_heldout_readiness(self.store)
        self.assertEqual((report['approved_cases'], report['selected_cases']), (12, 12))
        self.assertTrue(report['ready_for_owner_review'])
        self.assertFalse(report['model_called'])
        self.assertFalse(report['dataset_verified'])
        self.assertNotIn('synthetic held-out scenario', str(report))
        smaller = inspect_heldout_readiness(self.store, limit=5, min_cases=5)
        self.assertEqual(smaller['selected_cases'], 5)
        for args in ({'limit': 0}, {'min_cases': 1}, {'split': 'train'},
                     {'limit': 5, 'min_cases': 7}, {'limit': True}):
            with self.subTest(args=args), self.assertRaises(BenchmarkError):
                inspect_heldout_readiness(self.store, **args)

    def test_heldout_readiness_flags_cross_split_overlap_without_disclosing_case(self):
        self.store.add_decision('synthetic held-out scenario 1!', 'yes',
            'Private excluded case', source='synthetic', split='test',
            options=['yes', 'no'], approved=True)
        report = inspect_heldout_readiness(self.store)
        self.assertEqual(report['split_independence_check'], 'lexical-overlap')
        self.assertFalse(report['ready_for_owner_review'])
        self.assertNotIn('Private excluded', str(report))

    def test_heldout_inspection_cli_route_is_non_inferential(self):
        from athenz.train_cli import parser
        parsed = parser().parse_args(['inspect-heldout', '--split', 'test',
                                      '--limit', '25', '--min-cases', '5'])
        self.assertEqual((parsed.command, parsed.split, parsed.limit,
                          parsed.min_cases), ('inspect-heldout', 'test', 25, 5))

    def test_readiness_refuses_malformed_choices_without_model_calls(self):
        first_id = self.store.db.execute(
            "SELECT id FROM decisions WHERE split='calibration' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        self.store.db.execute(
            'UPDATE decisions SET options_json=? WHERE id=?',
            ('not-json', first_id))
        self.store.db.commit()
        report = inspect_heldout_readiness(self.store)
        self.assertFalse(report['heldout_options_valid'])
        self.assertFalse(report['ready_for_owner_review'])
        self.assertNotIn('not-json', str(report))

    def test_readiness_cli_prints_only_sanitized_counts(self):
        from athenz.train_cli import main
        with mock.patch('athenz.train_cli.OllamaClient',
                        side_effect=AssertionError('should not open local model')), \
             mock.patch('builtins.print') as display:
            main(['--home', str(self.store.home), 'inspect-heldout',
                  '--min-cases', '10'])
        obj = json.loads(display.call_args.args[0])
        self.assertEqual(obj['selected_cases'], 12)
        self.assertTrue(obj['heldout_options_valid'])
        self.assertFalse(obj['model_called'])
        self.assertFalse(obj['private_text_returned'])
        self.assertNotIn('synthetic held-out scenario', json.dumps(obj))

    def test_readonly_preflight_detects_approved_reference_contamination(self):
        self.store.propose('style', 'synthetic held-out scenario 1',
                           source='owner', approved=True)
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('no model inventory')):
            report = inspect_heldout_readiness(self.store)
        self.assertFalse(report['reference_profile_clean'])
        self.assertFalse(report['ready_for_owner_review'])
        self.assertTrue(report['evidence_snapshot_stable'])
        self.assertNotIn('synthetic held-out scenario 1', str(report))

    def test_preflight_refuses_ambiguous_answers_without_model(self):
        first = self.store.db.execute(
            "SELECT id FROM decisions WHERE split='calibration' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        self.store.db.execute('UPDATE decisions SET options_json=? WHERE id=?',
            (json.dumps(['yes', 'YES ', 'no']), first))
        self.store.db.commit()
        report = inspect_heldout_readiness(self.store)
        self.assertFalse(report['heldout_options_valid'])
        self.assertFalse(report['ready_for_owner_review'])

    def test_preflight_seed_validation_and_stale_reference_are_sanitized(self):
        with self.assertRaisesRegex(BenchmarkError, 'valid held-out split'):
            inspect_heldout_readiness(self.store, seed=True)
        with self.assertRaisesRegex(BenchmarkError, 'valid held-out split'):
            inspect_heldout_readiness(self.store, seed=-1)
        original = __import__('athenz.model_gate', fromlist=['_reference_fingerprint'])._reference_fingerprint
        count = {'n': 0}
        def drifting(store):
            count['n'] += 1
            return original(store) if count['n'] == 1 else 'f' * 64
        with mock.patch('athenz.model_gate._reference_fingerprint',
                        side_effect=drifting):
            report = inspect_heldout_readiness(self.store)
        self.assertFalse(report['evidence_snapshot_stable'])
        self.assertFalse(report['ready_for_owner_review'])

    def test_worse_candidate_not_ready(self):
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations(10, 8)):
            r = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        self.assertFalse(r['eligible_for_review'])
        self.assertLess(r['accuracy_gain'], 0)

    def test_mismatched_cases_rejected(self):
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations(offset=1)):
            with self.assertRaisesRegex(BenchmarkError, 'unequal'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)

    def test_too_few_cases_and_same_model_rejected(self):
        with self.assertRaisesRegex(BenchmarkError, 'distinct'):
            compare_models(self.store, Model('same'), Model('same'), self.sha)
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations()):
            with self.assertRaisesRegex(BenchmarkError, 'Insufficient'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha, min_cases=20)

    def test_modified_gold_choice_during_inference_blocks_benchmark(self):
        calls = iter(self.observations())
        def fake(*args, **kwargs):
            response = next(calls)
            if response['correct'] == 9:
                self.store.db.execute("UPDATE decisions SET choice='no' WHERE id=1")
                self.store.db.commit()
            return response
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=fake):
            with self.assertRaisesRegex(BenchmarkError, 'changed'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)

    def test_model_digest_drift_during_evaluation_is_rejected(self):
        count = {'candidate': 0}
        def digests(tag):
            if tag == 'candidate':
                count['candidate'] += 1
                return 'b'*64 if count['candidate'] == 1 else 'c'*64
            return 'a'*64
        with mock.patch('athenz.runtime.model_digest', side_effect=digests), \
             mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations()):
            with self.assertRaisesRegex(BenchmarkError, 'digest changed'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)

    def test_revocation_between_two_inferences_blocks_benchmark(self):
        calls = iter(self.observations())
        def fake(*args, **kwargs):
            next_result = next(calls)
            if next_result['correct'] == 9:
                self.store.set_review('train_pairs', self.pair, 'rejected')
            return next_result
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=fake):
            with self.assertRaisesRegex(Exception, 'stale'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)


    def test_modified_approved_reference_during_model_comparison_is_rejected(self):
        calls = iter(self.observations())
        def fake(*args, **kwargs):
            result = next(calls)
            if result['correct'] == 5:
                self.store.propose('style', 'A new approved writing preference',
                                   source='synthetic', approved=True)
            return result
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=fake):
            with self.assertRaisesRegex(BenchmarkError, 'reference evidence changed'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)

    def test_mismatched_reference_fingerprint_refused(self):
        cases = self.observations()
        cases[1]['reference_sha256'] = '0' * 64
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=cases):
            with self.assertRaisesRegex(BenchmarkError, 'stale evidence snapshots'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)

    def test_mismatched_heldout_provenance_refused(self):
        cases = self.observations()
        cases[1]['heldout_sha256'] = '0' * 64
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=cases):
            with self.assertRaisesRegex(BenchmarkError, 'stale evidence snapshots'):
                compare_models(self.store, Model('base'), Model('candidate'), self.sha)


    def test_saving_completed_comparison_refuses_newly_approved_reference(self):
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        self.store.propose('style', 'Changed owner reference', source='synthetic', approved=True)
        with self.assertRaisesRegex(BenchmarkError, 'evidence changed before saving'):
            save_report(self.store, report, confirmed=True)

    def test_saving_completed_comparison_refuses_changed_heldout_rationale(self):
        with mock.patch('athenz.model_gate.evaluate_decisions', side_effect=self.observations()):
            report = compare_models(self.store, Model('base'), Model('candidate'), self.sha)
        self.store.db.execute("UPDATE decisions SET rationale='different' WHERE split='calibration' AND id=1")
        self.store.db.commit()
        with self.assertRaisesRegex(BenchmarkError, 'evidence changed before saving'):
            save_report(self.store, report, confirmed=True)


if __name__ == '__main__':
    unittest.main()
