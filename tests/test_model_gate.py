"""Synthetic aggregate model-benchmark gates; never call Ollama or train."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.experience import ExperienceStore
from athenz.model_gate import BenchmarkError, compare_models, save_report
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

    def observations(self, first=5, second=9, offset=0):
        ids = [r['id'] for r in self.store.db.execute(
            "SELECT id FROM decisions WHERE split='calibration' ORDER BY id")]
        heldout_sha = _fingerprint(_heldout_rows(self.store, 'calibration', 100))
        reference_sha = _reference_fingerprint(self.store)
        def one(correct, tweak=0):
            return {'heldout_sha256': heldout_sha, 'reference_sha256': reference_sha,
                    'total':len(ids), 'correct':correct, 'accuracy':correct/len(ids),
                    'chance_expected':0.5, 'cases':[{'id':i + tweak,'expected':'A',
                    'predicted':'A' if index < correct else 'B',
                    'correct': index < correct} for index, i in enumerate(ids)]}
        return [one(first), one(second, offset)]

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
