"""Synthetic aggregate model-benchmark gates; never call Ollama or train."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.experience import ExperienceStore
from athenz.model_gate import BenchmarkError, compare_models, save_report
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
        def one(correct, tweak=0):
            return {'total':len(ids), 'correct':correct, 'accuracy':correct/len(ids),
                    'chance_expected':0.5, 'cases':[{'id':i + tweak,'expected':'A',
                    'predicted':'A','correct': True} for i in ids]}
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


if __name__ == '__main__':
    unittest.main()
