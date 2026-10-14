import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from athenz.evaluation import evaluate_decisions, _wilson_interval
from athenz.cli import main
from athenz.experience import ExperienceStore
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
        self.store = ExperienceStore(Path(self.temp.name) / 'private')
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
        self.assertNotIn('Training scenario', sent)  # unrelated training evidence is excluded
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

    def test_repeated_answer_options_are_refused_before_model_call(self):
        row_id = self.store.add_decision('Distinct synthetic decision about review gates?',
            'Approve', 'Private scenario rationale', source='synthetic',
            options=['Approve', 'Reject'], split='test', approved=True)
        # Normal owner entry already rejects duplicate choices; simulate a
        # legacy/corrupted local row to exercise scoring's independent guard.
        self.store.db.execute('UPDATE decisions SET options_json=? WHERE id=?',
            (json.dumps(['Approve', 'APPROVE ', 'Reject']), row_id))
        self.store.db.commit()
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'invalid held-out options'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_protected_prompt_assembly_has_no_model_or_extra_owner_text(self):
        from athenz.evaluation import _heldout_prompt_messages, _heldout_rows
        self.store.add_decision('Should we use the isolated build?', 'Yes',
            'Private gold rationale', source='synthetic', options=['Yes','No'],
            split='test', approved=True)
        item = _heldout_rows(self.store, 'test', 5)[0]
        messages, shuffled = _heldout_prompt_messages(self.store, item, 42)
        self.assertEqual(len(messages), 4)
        self.assertEqual(sorted(shuffled), ['No', 'Yes'])
        self.assertNotIn('Private gold rationale', str(messages))
        self.assertEqual(messages[3]['role'], 'user')

    def test_later_heldout_reference_leak_prevents_all_model_calls(self):
        self.store.add_decision('Could we archive the reviewed sample?', 'Yes',
            'Synthetic first rationale', source='synthetic', options=['Yes','No'],
            split='test', approved=True)
        self.store.add_decision('Should this second secret prompt remain private?', 'Yes',
            'Synthetic private second rationale', source='synthetic', options=['Yes','No'],
            split='test', approved=True)
        self.store.propose('style', 'Should this second secret prompt remain private?',
                           source='owner', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'contaminated'):
            evaluate_decisions(self.store, model, split='test')
        self.assertEqual(model.calls, [])

    def test_later_invalid_choices_prevent_earlier_model_calls(self):
        first = self.store.add_decision('Could we safely rebuild the local sample?', 'Yes',
            'Synthetic first reason', source='synthetic', options=['Yes','No'],
            split='test', approved=True)
        second = self.store.add_decision('Should a malformed question be evaluated?', 'Yes',
            'Synthetic second reason', source='synthetic', options=['Yes','No'],
            split='test', approved=True)
        self.store.db.execute('UPDATE decisions SET options_json=? WHERE id=?',
                              (json.dumps(['Yes','YES ', 'No']), second))
        self.store.db.commit()
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'invalid held-out options'):
            evaluate_decisions(self.store, model, split='test')
        self.assertEqual(model.calls, [])

    def test_approved_training_decision_overlap_blocks_heldout_scoring(self):
        self.store.add_decision('Should we deploy code without verification?',
            'No', 'A training reason', source='synthetic', approved=True)
        self.store.add_decision('Should we deploy code without verification!',
            'No', 'Held-out reason', source='synthetic',
            options=['Yes', 'No'], split='test', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'overlap evaluation splits'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_calibration_case_duplicate_in_test_blocks_scoring(self):
        self.store.add_decision('Does the owner require a rollback plan?',
            'Yes', 'Synthetic calibration reason', source='synthetic',
            options=['Yes', 'No'], split='calibration', approved=True)
        self.store.add_decision('Does the owner require a rollback plan!',
            'Yes', 'Private held-out reason', source='synthetic',
            options=['Yes', 'No'], split='test', approved=True)
        with self.assertRaisesRegex(ValueError, 'overlap evaluation splits'):
            evaluate_decisions(self.store, Stub(), split='calibration')

    def test_high_overlap_scenarios_crossing_splits_are_rejected(self):
        self.store.add_decision(
            'Would the owner authorize deployment after all automated validation checks pass today?',
            'No', 'Synthetic training rationale',
            source='synthetic', approved=True)
        self.store.add_decision(
            'Would the owner authorize deployment after all automated local validation checks pass today?',
            'No', 'Synthetic held-out rationale',
            source='synthetic', options=['Yes', 'No'],
            split='test', approved=True)
        stub = Stub()
        with self.assertRaisesRegex(ValueError, 'overlap evaluation splits'):
            evaluate_decisions(self.store, stub)
        self.assertEqual(stub.calls, [])

    def test_same_split_punctuation_duplicates_refused_before_inference(self):
        scenario = 'Would the owner verify backups before deploying the updated system?'
        self.store.add_decision(scenario, 'Yes', 'Synthetic review reason',
                                source='synthetic', options=['Yes', 'No'],
                                split='test', approved=True)
        self.store.add_decision(scenario[:-1] + '!', 'Yes', 'Different private reason',
                                source='synthetic', options=['Yes', 'No'],
                                split='test', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'Repeated held-out'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_same_split_long_near_duplicate_refused_before_inference(self):
        self.store.add_decision(
            'Would the owner approve this experimental release after the security review passes today?',
            'No', 'First reason', source='synthetic', options=['Yes', 'No'],
            split='calibration', approved=True)
        self.store.add_decision(
            'Would the owner approve this experimental release after the local security review passes today?',
            'No', 'Second reason', source='synthetic', options=['Yes', 'No'],
            split='calibration', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'Repeated held-out'):
            evaluate_decisions(self.store, model, split='calibration')
        self.assertEqual(model.calls, [])

    def test_approved_within_split_duplicate_added_midflight_refuses_score(self):
        scenario = 'Would the owner check restore evidence before releasing a new build?'
        self.store.add_decision(scenario, 'Yes', 'Owner only evidence',
                                source='synthetic', options=['Yes', 'No'],
                                split='test', approved=True)
        store = self.store
        class MutatingModel(Stub):
            def generate(self, messages, **kwargs):
                result = super().generate(messages, **kwargs)
                store.add_decision(scenario[:-1] + '!', 'Yes',
                                   'Second synthetic reason', source='synthetic',
                                   options=['Yes', 'No'], split='test',
                                   approved=True)
                return result
        model = MutatingModel()
        with self.assertRaisesRegex(ValueError, 'Repeated held-out'):
            evaluate_decisions(self.store, model)
        self.assertEqual(len(model.calls), 1)

    def test_pending_duplicate_is_not_scored_as_correlated_approved_case(self):
        scenario = 'Would the owner confirm private snapshot safety before release?'
        self.store.add_decision(scenario, 'Yes', 'Approved rationale',
                                source='synthetic', options=['Yes', 'No'],
                                split='test', approved=True)
        self.store.add_decision(scenario[:-1] + '!', 'Yes', 'Pending rationale',
                                source='synthetic', options=['Yes', 'No'],
                                split='test')
        model = Stub()
        report = evaluate_decisions(self.store, model)
        self.assertEqual(report['total'], 1)
        self.assertEqual(len(model.calls), 1)

    def test_distinct_scenarios_with_shared_lead_in_remain_evaluable(self):
        self.store.add_decision(
            'Would the owner authorize deployment after all automated validation checks pass today?',
            'No', 'Training choice',
            source='synthetic', approved=True)
        self.store.add_decision(
            'Would the owner authorize deployment after all automated security scans fail today?',
            'No', 'Independent held-out choice',
            source='synthetic', options=['Yes', 'No'],
            split='test', approved=True)
        stub = Stub()
        outcome = evaluate_decisions(self.store, stub)
        self.assertEqual(outcome['total'], 1)
        self.assertEqual(len(stub.calls), 1)

    def test_unapproved_overlapping_decision_does_not_block(self):
        self.store.add_decision('Should we keep all test cases separate?',
            'Yes', 'Pending, not yet approved', source='synthetic')
        self.store.add_decision('Should we keep all test cases separate!',
            'Yes', 'Private held-out answer', source='synthetic',
            options=['Yes', 'No'], split='test', approved=True)
        model = Stub()
        result = evaluate_decisions(self.store, model)
        self.assertEqual(result['total'], 1)
        self.assertEqual(len(model.calls), 1)

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

    def test_approved_episode_cannot_expose_heldout_scenario(self):
        scenario = 'Should the pilot ship a patch without verification?'
        self.store.add_decision(scenario, 'Wait', 'Unreleased gold rationale',
            source='synthetic', approved=True, options=['Ship', 'Wait'], split='test')
        episode = self.store.observe('Patch verification habit',
            scenario + ' The preferred answer is Wait.', tags=['verification'],
            source='synthetic')
        self.store.review_episode(episode, 'approved')
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'contaminated'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_heldout_rationale_collision_blocks_scoring(self):
        private_rationale = 'UNIQUE PRIVATE RATIONALE SHOULD NOT APPEAR'
        self.store.add_decision('Can we proceed with an unreviewed change?',
            'Wait', private_rationale, source='synthetic', approved=True,
            options=['Proceed', 'Wait'], split='test')
        self.store.propose('style', 'Owner explanation: ' + private_rationale,
                           source='synthetic', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'contaminated'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_punctuation_variant_of_heldout_scenario_blocks_evaluation(self):
        scenario = 'Should the operator approve a patch without passing tests?'
        self.store.add_decision(scenario, 'Wait', 'Private held-out reason',
            source='synthetic', options=['Approve', 'Wait'],
            split='test', approved=True)
        # Neither the literal held-out sentence nor private gold rationale
        # appears exactly in the approved profile.
        self.store.propose('preference',
            'Should the operator approve a patch WITHOUT-PASSING tests! '
            'The reviewed choice was Wait.',
            source='synthetic', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'contaminated'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_normalized_private_rationale_collision_blocks_evaluation(self):
        reason = 'Review deployment after integration checks are green'
        self.store.add_decision('Is there a safe time to deploy a patch?',
            'Wait', reason, source='synthetic',
            options=['Ship', 'Wait'], split='test', approved=True)
        self.store.propose('preference',
            'Review deployment AFTER integration-checks are green!',
            source='synthetic', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'contaminated'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_unapproved_episode_is_not_prompt_contamination(self):
        scenario = 'Should a candidate be promoted without evidence?'
        self.store.add_decision(scenario, 'No', 'Keep review gate', source='synthetic',
            approved=True, options=['Yes', 'No'], split='test')
        self.store.observe('Unreviewed source', scenario + ' No', tags=['promotion'],
                           source='synthetic')
        model = Stub()
        result = evaluate_decisions(self.store, model)
        self.assertEqual(result['total'], 1)
        self.assertEqual(len(model.calls), 1)

    def test_contamination_check_reads_reference_not_format_instruction(self):
        scenario = 'Does the owner ship a failing code review?'
        self.store.add_decision(scenario, 'Wait', 'Do not leak private gold',
            source='synthetic', options=['Ship', 'Wait'],
            split='test', approved=True)
        self.store.propose('preference', scenario + ' Owner chooses Wait.',
                           source='synthetic', approved=True)
        model = Stub()
        with self.assertRaisesRegex(ValueError, 'contaminated'):
            evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

    def test_uncertainty_metrics_and_invalid_model_letters(self):
        empty = evaluate_decisions(self.store, Stub())
        self.assertIsNone(empty['accuracy_interval_95'])
        self.assertEqual(empty['invalid_predictions'], 0)
        self.store.add_decision('Unexpected model response case', 'Wait',
            'Synthetic rationale', source='synthetic', approved=True,
            options=['Go', 'Wait'], split='test')
        result = evaluate_decisions(self.store, Stub(choice='Z'))
        self.assertEqual(result['correct'], 0)
        self.assertEqual(result['invalid_predictions'], 1)
        self.assertIsNone(result['cases'][0]['predicted'])
        self.assertEqual(result['accuracy_interval_95'], _wilson_interval(0, 1))
        self.assertAlmostEqual(result['accuracy_interval_95'][1], 0.79345068562)

    def test_wilson_intervals_are_deterministic(self):
        self.assertIsNone(_wilson_interval(0, 0))
        self.assertAlmostEqual(_wilson_interval(1, 1)[0], 0.206549314377)
        self.assertAlmostEqual(_wilson_interval(1, 2)[0], 0.094531205734)
        self.assertEqual(_wilson_interval(2, 2)[1], 1.0)

    def test_unexpected_reference_prompt_structure_fails_closed(self):
        self.store.add_decision('Synthetic held-out question', 'Wait', 'Gold',
            source='synthetic', approved=True, options=['Ship', 'Wait'], split='test')
        messages = [{'role': 'system', 'content': 'policy'},
                    {'role': 'system', 'content': 'unexpected reference format'},
                    {'role': 'user', 'content': 'question'}]
        model = Stub()
        with mock.patch('athenz.evaluation.build_messages', return_value=messages):
            with self.assertRaisesRegex(ValueError, 'reference context changed'):
                evaluate_decisions(self.store, model)
        self.assertEqual(model.calls, [])

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
