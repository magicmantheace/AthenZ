import json
import tempfile
import unittest
from pathlib import Path

from athenz.evaluation import evaluate_decisions
from athenz.cli import main
from athenz.learning import LearningStore
from athenz.prompting import build_messages


class Stub:
    model = 'fake-local-model'
    def __init__(self, choice='A'):
        self.choice = choice
        self.calls = []
    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return json.dumps({'choice_letter': self.choice})


class DecisionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LearningStore(Path(self.temp.name) / 'private')
        self.addCleanup(self.store.close)

    def test_heldout_gold_and_rationale_never_enter_prompt(self):
        self.store.add_decision('Training scenario', 'Develop tests', 'Quality',
                                source='owner', approved=True)
        did = self.store.add_decision('Should we ship despite failing checks?', 'Wait',
            'PRIVATE GOLD REASON NOT TO LEAK', source='owner', approved=True,
            options=['Ship', 'Wait'], split='test')
        prompt = str(build_messages(self.store, 'What now?', mode='twin'))
        self.assertNotIn('Should we ship', prompt)
        self.assertNotIn('PRIVATE GOLD REASON', prompt)
        stub = Stub()
        report = evaluate_decisions(self.store, stub)
        self.assertEqual(report['total'], 1)
        self.assertEqual(report['cases'][0]['id'], did)
        sent = str(stub.calls)
        self.assertIn('Should we ship', sent)
        self.assertNotIn('PRIVATE GOLD REASON', sent)
        self.assertIn('Training scenario', sent)
        self.assertEqual(stub.calls[0][1]['temperature'], 0.0)
        self.assertEqual(stub.calls[0][1]['seed'], 42)

    def test_test_set_excludes_unapproved_and_repeatable(self):
        self.store.add_decision('Unapproved question', 'A', 'Because', source='owner',
                                options=['A', 'B'], split='test')
        self.assertEqual(evaluate_decisions(self.store, Stub())['total'], 0)
        self.store.add_decision('Approved question', 'B', 'Because', source='owner',
                                options=['A', 'B'], split='test', approved=True)
        model = Stub(choice='A')
        r1 = evaluate_decisions(self.store, model)
        r2 = evaluate_decisions(self.store, model)
        self.assertEqual(r1, r2)
        self.assertEqual(r1['chance_expected'], .5)

    def test_duplicate_scenarios_and_bad_options_rejected(self):
        self.store.add_decision('One choice', 'X', 'Reason', source='owner')
        with self.assertRaises(ValueError):
            self.store.add_decision('one choice', 'Y', 'Reason', source='owner',
                                    options=['X', 'Y'], split='test')
        with self.assertRaises(ValueError):
            self.store.add_decision('Another scenario', 'other', 'Reason', source='owner',
                                    options=['X', 'Y'], split='test')
        with self.assertRaises(ValueError):
            self.store.add_decision('Yet another scenario', 'X', 'Reason', source='owner',
                                    split='test')

    def test_cli_create_heldout_case(self):
        main(['--home', str(self.store.home), 'decision', 'CLI test scenario', 'Wait',
              'Important synthetic reason', '--option', 'Ship', '--option', 'Wait',
              '--split', 'test'])
        row = self.store.list_items('decisions')[0]
        self.assertEqual(row['split'], 'test')
        self.assertEqual(row['status'], 'pending')
        self.assertNotIn('CLI test scenario', str(build_messages(self.store, 'Now?', 'twin')))

    def test_calibration_and_test_scoring_separate(self):
        a = self.store.add_decision('Q1', 'A', 'R', source='owner',
                                    options=['A', 'B'], split='calibration', approved=True)
        b = self.store.add_decision('Q2', 'A', 'R', source='owner',
                                    options=['A', 'B'], split='test', approved=True)
        self.assertEqual(evaluate_decisions(self.store, Stub(), split='calibration')['cases'][0]['id'], a)
        self.assertEqual(evaluate_decisions(self.store, Stub(), split='test')['cases'][0]['id'], b)
        with self.assertRaises(ValueError):
            evaluate_decisions(self.store, Stub(), split='train')


    def test_revoked_heldout_decision_during_model_generation_fails(self):
        did = self.store.add_decision('Do not ship a pending patch?', 'Wait', 'Private gold reason',
            source='synthetic', approved=True, options=['Ship', 'Wait'], split='test')
        class RevokingModel(Stub):
            def generate(inner, messages, **kwargs):
                self.store.decision_status(did, 'rejected')
                return super().generate(messages, **kwargs)
        with self.assertRaisesRegex(ValueError, 'Held-out decision changed'):
            evaluate_decisions(self.store, RevokingModel())

    def test_changed_gold_rationale_midflight_fails_without_leaking_it(self):
        did = self.store.add_decision('Synthetic question', 'Wait', 'Original private reason',
            source='synthetic', approved=True, options=['Ship', 'Wait'], split='test')
        class UpdatingModel(Stub):
            def generate(inner, messages, **kwargs):
                self.store.db.execute("UPDATE decisions SET rationale=? WHERE id=?",
                                      ('Revised sensitive rationale', did))
                self.store.db.commit()
                return super().generate(messages, **kwargs)
        with self.assertRaisesRegex(ValueError, 'Held-out decision changed') as caught:
            evaluate_decisions(self.store, UpdatingModel())
        self.assertNotIn('Revised sensitive rationale', str(caught.exception))

    def test_approved_prompt_reference_change_midflight_fails(self):
        self.store.add_decision('A heldout question', 'A', 'Gold not transmitted',
            source='synthetic', approved=True, options=['A', 'B'], split='test')
        class AlteringModel(Stub):
            def generate(inner, messages, **kwargs):
                self.store.propose('style', 'Newly reviewed approved preference',
                                   source='synthetic', approved=True)
                return super().generate(messages, **kwargs)
        with self.assertRaisesRegex(ValueError, 'reference evidence changed'):
            evaluate_decisions(self.store, AlteringModel())

    def test_safe_prediction_parsing_for_non_object_json(self):
        self.store.add_decision('Test invalid JSON output', 'A', 'Private gold',
            source='synthetic', approved=True, options=['A', 'B'], split='test')
        stub = Stub()
        stub.generate = lambda *args, **kwargs: '[]'
        report = evaluate_decisions(self.store, stub)
        self.assertEqual(report['correct'], 0)
        self.assertIsNone(report['cases'][0]['predicted'])

    def test_invalid_seed_and_limit_inputs_rejected(self):
        for kwargs in ({'seed': True}, {'seed': -1}, {'seed': 2**32},
                       {'limit': True}, {'limit': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                evaluate_decisions(self.store, Stub(), **kwargs)


if __name__ == '__main__':
    unittest.main()
