"""Synthetic session evidence, no network or owner data."""
import hashlib
import json
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest import mock

from athenz.adapters import register_adapter
from athenz.evaluation import _reference_fingerprint
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.learning_session import (
    LearningSessionError, start_session, session_status, record_baseline,
    link_completed_run, link_comparison, close_session, cancel_session,
    session_comparison_context)
from athenz.model_gate import (
    _approved_heldout_population, _heldout_fingerprint, save_report,
    _case_outcome_fingerprint, compare_models)
from athenz.training import build_dataset


class LearningSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.store = ExperienceStore(root / 'private')
        self.addCleanup(self.store.close)
        self.store.add_message('synthetic', 'twin', 'user', 'Unrelated training input')
        message = self.store.add_message('synthetic', 'twin', 'assistant', 'Draft response')
        self.store.add_feedback(message, 'down', 'Reviewed corrected response')
        pair = self.store.db.execute('SELECT id FROM train_pairs LIMIT 1').fetchone()[0]
        self.store.set_review('train_pairs', pair, 'approved')
        self.pair = pair
        for i in range(12):
            self.store.add_decision(
                f'Would synthetic heldout case {i} need a separate owner review?',
                'yes', 'SYNTHETIC GOLD', source='synthetic',
                options=['yes', 'no'], split='calibration', approved=True)
        self.dataset = build_dataset(self.store, confirmed=True)['sha256']
        self.base = root / 'base'
        self.base.mkdir()
        (self.base / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.base / 'tokenizer.json').write_text('{}')
        (self.base / 'model.safetensors').write_bytes(b'synthetic')

    def begin(self):
        return start_session(self.store, self.dataset, limit=12, confirmed=True)

    def baselined(self, session):
        class LocalSyntheticModel:
            model = 'base-local'
            calls = []
            def generate(self, messages, **kwargs):
                self.calls.append((messages, kwargs))
                return json.dumps({'choice_letter': 'A'})
        model = LocalSyntheticModel()
        with mock.patch('athenz.runtime.model_digest', return_value='a'*64):
            result = record_baseline(
                self.store, session['session_id'], model,
                expected_revision=session['revision'], confirmed=True)
        self.assertEqual(result['stage'], 'baselined')
        self.assertTrue(result['baseline_observed'])
        self.assertEqual(len(model.calls), 12)
        self.assertFalse(result['baseline_model_installed_verified'])
        state = self.store.get_checkpoint(
            'learning_session_' + session['session_id'])['state']
        self.baseline_count = state['baseline_correct']
        self.baseline_outcome = state['baseline_outcome_sha256']
        self.assertEqual(len(state['baseline_outcome_key']), 64)
        self.assertTrue(result['baseline_outcomes_pinned'])
        self.assertNotIn(state['baseline_outcome_key'], json.dumps(result))
        return result

    def trained(self, session):
        session = self.baselined(session)
        run = create_run(self.store, self.dataset, self.base, confirmed=True)
        def backend(recipe, folder, dataset, *, resume):
            adapter = folder / 'adapter'
            adapter.mkdir()
            (adapter / 'adapter_model.safetensors').write_bytes(b'fake weights')
            (adapter / 'adapter_config.json').write_text(json.dumps({
                'peft_type':'LORA', 'base_model_name_or_path':str(self.base)}))
            return {'adapter_dir':str(adapter), 'examples_used':1}
        execute_run(self.store, run['run_id'], backend=backend, confirmed=True)
        register_adapter(self.store, run['run_id'], 'candidate-local', confirmed=True)
        return link_completed_run(
            self.store, session['session_id'], run['run_id'],
            expected_revision=session['revision'], confirmed=True)

    def report(self, better=True):
        ids = [r[0] for r in self.store.db.execute(
            "SELECT id FROM decisions WHERE status='approved' AND split='calibration' ORDER BY id")]
        total, population = _approved_heldout_population(self.store, 'calibration')
        base = self.baseline_count
        cand = base + 1 if better else base - 1
        self.assertTrue(0 <= cand <= 12)
        report = {
            'schema':2, 'dataset_sha256':self.dataset, 'split':'calibration',
            'seed':42, 'cases':12, 'requested_case_limit':12,
            'approved_split_total':total, 'approved_split_sha256':population,
            'baseline':'base-local', 'candidate':'candidate-local',
            'baseline_digest':'a'*64, 'candidate_digest':'b'*64,
            'baseline_outcome_sha256':self.baseline_outcome,
            'baseline_correct':base, 'candidate_correct':cand,
            'baseline_accuracy':base/12, 'candidate_accuracy':cand/12,
            'accuracy_gain':round((cand-base)/12,8),
            'paired_improved':1 if better else 0,
            'paired_regressed':0 if better else 1,
            'paired_unchanged':11,
            'paired_one_sided_p_value':0.5 if better else 1.0,
            'chance_expected':0.5, 'eligible_for_review':better,
            'case_ids_sha256':hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
            'heldout_fingerprint':_heldout_fingerprint(self.store, 'calibration', 12),
            'reference_fingerprint':_reference_fingerprint(self.store),
            'attestation':'local-model-observation-only', 'promotion':'not-authorized'}
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda name:'a'*64 if name == 'base-local' else 'b'*64):
            return save_report(self.store, report, confirmed=True)['sha256']

    def test_start_requires_confirmation_and_is_offline(self):
        with mock.patch('athenz.runtime.model_digest', side_effect=AssertionError('offline')):
            with self.assertRaisesRegex(LearningSessionError, 'confirm'):
                start_session(self.store, self.dataset, limit=12)
            session = self.begin()
            self.assertEqual(session_status(self.store, session['session_id']), session)
        self.assertEqual(session['stage'], 'prepared')
        self.assertEqual(session['revision'], 1)
        self.assertFalse(session['promotion_authorized'])
        self.assertNotIn(self.dataset, json.dumps(session))
        self.assertFalse(self.store.get_checkpoint('ollama_runtime'))

    def test_training_link_requires_baseline_and_old_revision_cannot_replay(self):
        session = self.begin()
        with self.assertRaisesRegex(LearningSessionError, 'awaiting'):
            link_completed_run(self.store, session['session_id'], '0'*24,
                               expected_revision=session['revision'], confirmed=True)
        baseline = self.baselined(session)
        with self.assertRaisesRegex(LearningSessionError, 'revision changed'):
            class Model:
                model = 'base-local'
            record_baseline(self.store, session['session_id'], Model(),
                            expected_revision=session['revision'], confirmed=True)
        self.assertEqual(baseline['revision'], 2)
        self.assertEqual(session_status(self.store, session['session_id'])['stage'],
                         'baselined')

    def test_baseline_is_explicit_and_never_sends_protected_gold(self):
        session = self.begin()
        class Fake:
            model = 'base-local'
            def __init__(self):
                self.calls = []
            def generate(self, messages, **kwargs):
                self.calls.append((messages, kwargs))
                return json.dumps({'choice_letter':'A'})
        model = Fake()
        with mock.patch('athenz.runtime.model_digest', return_value='a'*64):
            with self.assertRaisesRegex(LearningSessionError, 'confirm'):
                record_baseline(self.store, session['session_id'], model,
                                expected_revision=session['revision'])
            self.assertEqual(model.calls, [])
            result = record_baseline(self.store, session['session_id'], model,
                                     expected_revision=session['revision'], confirmed=True)
        self.assertTrue(result['evidence_current'])
        self.assertFalse(result['training_started'])
        self.assertFalse(result['promotion_authorized'])
        self.assertEqual(len(model.calls), 12)
        self.assertNotIn('SYNTHETIC GOLD', str(model.calls))
        self.assertTrue(all(call[1].get('seed') == 42 and
                            call[1].get('temperature') == 0.0
                            for call in model.calls))
        self.assertNotIn('base-local', json.dumps(result))

    def test_backend_failure_never_prints_protected_case_in_traceback(self):
        session = self.begin()
        class FailingLocalModel:
            model = 'base-local'
            def generate(self, messages, **kwargs):
                raise RuntimeError('PRIVATE_HELDOUT_PROMPT_DO_NOT_ECHO')
        with mock.patch('athenz.runtime.model_digest', return_value='a'*64):
            with self.assertRaisesRegex(LearningSessionError, 'Baseline evaluation failed') as caught:
                record_baseline(self.store, session['session_id'], FailingLocalModel(),
                                expected_revision=session['revision'], confirmed=True)
        self.assertNotIn('PRIVATE_HELDOUT_PROMPT_DO_NOT_ECHO',
                         ''.join(traceback.format_exception(caught.exception)))
        self.assertEqual(session_status(self.store, session['session_id'])['stage'],
                         'prepared')

    def test_baseline_changed_model_digest_never_advances(self):
        session = self.begin()
        class Fake:
            model = 'base-local'
            def generate(self, messages, **kwargs):
                return json.dumps({'choice_letter': 'A'})
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=['a'*64, 'b'*64]):
            with self.assertRaisesRegex(LearningSessionError, 'digest changed'):
                record_baseline(self.store, session['session_id'], Fake(),
                                expected_revision=session['revision'], confirmed=True)
        self.assertEqual(session_status(self.store, session['session_id'])['stage'],
                         'prepared')
        self.assertEqual(session_status(self.store, session['session_id'])['revision'], 1)

    def test_baseline_rejects_revocation_during_inference(self):
        session = self.begin()
        store = self.store
        class Fake:
            model = 'base-local'
            def generate(self, messages, **kwargs):
                store.set_review('train_pairs', self_pair, 'rejected')
                return json.dumps({'choice_letter': 'A'})
        self_pair = self.pair
        with mock.patch('athenz.runtime.model_digest', return_value='a'*64):
            with self.assertRaisesRegex(LearningSessionError, 'Baseline evaluation evidence changed'):
                record_baseline(self.store, session['session_id'], Fake(),
                                expected_revision=session['revision'], confirmed=True)
        self.assertEqual(session_status(self.store, session['session_id'])['stage'],
                         'prepared')

    def test_saved_comparison_must_match_pretraining_baseline(self):
        session = self.begin()
        trained = self.trained(session)
        digest = self.report()
        path = self.store.home / 'datasets' / 'evaluations' / ('eval-' + digest + '.json')
        evidence = json.loads(path.read_text())
        with mock.patch('athenz.learning_session._saved_report',
                        return_value={**evidence, 'baseline_correct':
                                      evidence['baseline_correct'] + 1}):
            with self.assertRaisesRegex(LearningSessionError,
                                        'different or outdated model evidence'):
                link_comparison(self.store, session['session_id'], digest,
                                expected_revision=trained['revision'], confirmed=True)
        self.assertEqual(session_status(self.store, session['session_id'])['stage'],
                         'trained')

    def test_baseline_state_is_offline_and_detects_heldout_mutation(self):
        session = self.baselined(self.begin())
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('No Ollama on status')):
            self.assertTrue(session_status(self.store, session['session_id'])['evidence_current'])
        row_id = self.store.db.execute(
            "SELECT id FROM decisions WHERE split='calibration' ORDER BY id LIMIT 1").fetchone()[0]
        with self.store.db:
            self.store.db.execute(
                'UPDATE decisions SET rationale=? WHERE id=?',
                ('synthetically-changed-protected-evidence', row_id))
        self.assertFalse(session_status(self.store, session['session_id'])['evidence_current'])

    def test_positive_and_negative_reports_both_recorded(self):
        for better in (True, False):
            session = self.begin()
            trained = self.trained(session)
            saved = self.report(better)
            observed = link_comparison(
                self.store, session['session_id'], saved,
                expected_revision=trained['revision'], confirmed=True)
            self.assertEqual(observed['stage'], 'evaluated')
            self.assertEqual(observed['observed_outcome'],
                             'candidate-improved-observed' if better else 'candidate-regressed-observed')
            closed = close_session(
                self.store, session['session_id'],
                expected_revision=observed['revision'], confirmed=True)
            self.assertEqual(closed['stage'], 'closed')
            self.assertTrue(closed['evidence_current'])
            self.assertFalse(closed['promotion_authorized'])
            self.assertFalse(self.store.get_checkpoint('ollama_runtime'))

    def test_schema_one_legacy_sessions_still_link_training_and_comparisons(self):
        started = self.begin()
        recent = self.trained(started)
        key = 'learning_session_' + started['session_id']
        checkpoint = self.store.get_checkpoint(key)
        run_id = checkpoint['state']['run_id']
        # Model a genuine historical schema-one prepared journal persisted
        # before baseline observations were introduced.
        old_state = {k: v for k, v in checkpoint['state'].items()
                     if not k.startswith('baseline_') and k not in (
                         'run_id', 'candidate_tag', 'adapter_sha256')}
        old_state.update(schema=1, stage='prepared')
        self.store.checkpoint(key, checkpoint['task'], old_state,
                              expected_revision=checkpoint['revision'])
        old_prepared = session_status(self.store, started['session_id'])
        self.assertEqual(old_prepared['stage'], 'prepared')
        self.assertFalse(old_prepared['baseline_observed'])
        linked = link_completed_run(
            self.store, started['session_id'], run_id,
            expected_revision=old_prepared['revision'], confirmed=True)
        self.assertEqual(linked['stage'], 'trained')
        evaluated = link_comparison(
            self.store, started['session_id'], self.report(),
            expected_revision=linked['revision'], confirmed=True)
        self.assertTrue(evaluated['evidence_current'])
        closed = close_session(
            self.store, started['session_id'],
            expected_revision=evaluated['revision'], confirmed=True)
        self.assertEqual(closed['stage'], 'closed')
        self.assertTrue(closed['evidence_current'])

    def test_keyed_fingerprint_distinguishes_same_score_different_predictions(self):
        key = bytes.fromhex('e5' * 32)
        before = [
            {'id':1, 'predicted':'A', 'expected':'A', 'correct':True},
            {'id':2, 'predicted':'A', 'expected':'B', 'correct':False}]
        after = [
            {'id':1, 'predicted':'B', 'expected':'A', 'correct':False},
            {'id':2, 'predicted':'B', 'expected':'B', 'correct':True}]
        self.assertEqual(sum(x['correct'] for x in before),
                         sum(x['correct'] for x in after))
        self.assertNotEqual(_case_outcome_fingerprint(before, key),
                            _case_outcome_fingerprint(after, key))
        self.assertEqual(_case_outcome_fingerprint(before, key),
                         _case_outcome_fingerprint(before, key))
        with self.assertRaisesRegex(ValueError, 'key'):
            _case_outcome_fingerprint(before, b'short')

    def test_session_comparison_uses_original_prediction_sequence(self):
        session = self.begin()
        trained = self.trained(session)
        key, expected = session_comparison_context(
            self.store, session['session_id'], expected_revision=trained['revision'],
            baseline='base-local', candidate='candidate-local',
            dataset_sha256=self.dataset, split='calibration', limit=12, seed=42)
        class Synthetic:
            def __init__(self, name, choice):
                self.model, self.choice = name, choice
            def generate(self, messages, **kwargs):
                return json.dumps({'choice_letter':self.choice})
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda name: 'a'*64 if name == 'base-local' else 'b'*64):
            compared = compare_models(
                self.store, Synthetic('base-local','A'), Synthetic('candidate-local','B'),
                self.dataset, split='calibration', limit=12, min_cases=10,
                seed=42, baseline_outcome_key=key)
            self.assertEqual(compared['baseline_outcome_sha256'], expected)
            saved = save_report(self.store, compared, confirmed=True)
        linked = link_comparison(
            self.store, session['session_id'], saved['sha256'],
            expected_revision=trained['revision'], confirmed=True)
        self.assertEqual(linked['stage'], 'evaluated')
        self.assertTrue(linked['evidence_current'])

    def test_unkeyed_comparison_cannot_link_to_keyed_session(self):
        session = self.begin()
        trained = self.trained(session)
        digest = self.report()
        path = self.store.home / 'datasets' / 'evaluations' / ('eval-' + digest + '.json')
        unkeyed = json.loads(path.read_text())
        unkeyed.pop('baseline_outcome_sha256')
        raw = (json.dumps(unkeyed, sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        sha = hashlib.sha256(raw).hexdigest()
        (path.parent / ('eval-' + sha + '.json')).write_bytes(raw)
        with self.assertRaisesRegex(LearningSessionError, 'different or outdated'):
            link_comparison(self.store, session['session_id'], sha,
                            expected_revision=trained['revision'], confirmed=True)

    def test_session_comparison_rejects_revision_and_consent_drift(self):
        session = self.begin()
        trained = self.trained(session)
        settings = dict(
            baseline='base-local', candidate='candidate-local',
            dataset_sha256=self.dataset, split='calibration', limit=12, seed=42)
        with self.assertRaisesRegex(LearningSessionError, 'revision changed'):
            session_comparison_context(
                self.store, session['session_id'],
                expected_revision=trained['revision'] - 1, **settings)
        with self.assertRaisesRegex(LearningSessionError, 'differs'):
            session_comparison_context(
                self.store, session['session_id'],
                expected_revision=trained['revision'],
                **{**settings, 'baseline':'different-local'})
        self.store.set_review('train_pairs', self.pair, 'rejected')
        with self.assertRaisesRegex(LearningSessionError, 'evidence changed'):
            session_comparison_context(
                self.store, session['session_id'],
                expected_revision=trained['revision'], **settings)

    def test_session_cli_refuses_equal_score_different_case_outcomes_before_save(self):
        from athenz.evaluation import _heldout_rows, _heldout_prompt_messages
        from athenz.train_cli import main
        session = self.begin()
        trained = self.trained(session)
        cases = _heldout_rows(self.store, 'calibration', 12)
        gold = []
        for item in cases:
            _, choices = _heldout_prompt_messages(self.store, item, 42)
            gold.append('ABCDEF'[choices.index(item[2])])
        correct_case = next(i for i, c in enumerate(gold) if c == 'A')
        wrong_case = next(i for i, c in enumerate(gold) if c == 'B')
        # Swap one previously correct and one previously wrong response: the
        # total score is unchanged, while exactly which cases fail differs.
        flips = {correct_case, wrong_case}
        class ScriptedLocal:
            def __init__(self, name):
                self.model = name
                self.index = 0
            def generate(self, messages, **kwargs):
                if self.model == 'base-local':
                    choice = 'B' if self.index in flips else 'A'
                else:
                    choice = 'B'
                self.index += 1
                return json.dumps({'choice_letter': choice})
        args = [
            '--home', str(self.store.home), 'compare', self.dataset,
            '--baseline', 'base-local', '--candidate', 'candidate-local',
            '--session', session['session_id'],
            '--revision', str(trained['revision']),
            '--split', 'calibration', '--limit', '12', '--seed', '42',
            '--confirm']
        with mock.patch('athenz.train_cli.OllamaClient',
                        side_effect=lambda **kw: ScriptedLocal(kw['model'])), \
             mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag: 'a'*64 if tag == 'base-local' else 'b'*64), \
             mock.patch('athenz.train_cli.save_report',
                        side_effect=AssertionError('Do not save drifting predictions')):
            with self.assertRaisesRegex(LearningSessionError,
                                        'Baseline predictions changed'):
                main(args)
        self.assertEqual(session_status(self.store, session['session_id'])['stage'],
                         'trained')
        self.assertFalse((self.store.home / 'datasets' / 'evaluations').exists())

    def test_cancel_and_revision_fencing(self):
        session = self.begin()
        ident, revision = session['session_id'], session['revision']
        with self.assertRaisesRegex(LearningSessionError, 'confirm'):
            cancel_session(self.store, ident, expected_revision=revision)
        with self.assertRaisesRegex(LearningSessionError, 'revision changed'):
            cancel_session(self.store, ident, expected_revision=revision + 1, confirmed=True)
        cancelled = cancel_session(self.store, ident, expected_revision=revision,
                                   confirmed=True)
        self.assertEqual(cancelled['stage'], 'cancelled')
        self.assertFalse(cancelled['evidence_current'])
        with self.assertRaisesRegex(LearningSessionError, 'already'):
            cancel_session(self.store, ident, expected_revision=cancelled['revision'],
                           confirmed=True)
        with self.assertRaisesRegex(LearningSessionError, 'awaiting'):
            link_completed_run(self.store, ident, '0'*24,
                               expected_revision=cancelled['revision'], confirmed=True)

    def test_review_revocation_fences_training_link(self):
        session = self.baselined(self.begin())
        self.store.set_review('train_pairs', self.pair, 'rejected')
        self.assertFalse(session_status(self.store, session['session_id'])['evidence_current'])
        with self.assertRaisesRegex(LearningSessionError, 'Source evidence changed'):
            link_completed_run(self.store, session['session_id'], '0'*24,
                               expected_revision=session['revision'], confirmed=True)
        self.assertEqual(session_status(self.store, session['session_id'])['revision'], 2)

    def test_unregistered_run_cannot_be_attached(self):
        session = self.baselined(self.begin())
        run = create_run(self.store, self.dataset, self.base, confirmed=True)
        with self.assertRaisesRegex(LearningSessionError, 'not verifiable'):
            link_completed_run(self.store, session['session_id'], run['run_id'],
                               expected_revision=session['revision'], confirmed=True)

    def test_population_change_fails_closed(self):
        session = self.begin()
        self.store.add_decision(
            'Would a distinct synthetic approval require another review?',
            'yes', 'NEW SYNTHETIC GOLD', source='synthetic',
            options=['yes','no'], split='calibration', approved=True)
        self.assertFalse(session_status(self.store, session['session_id'])['evidence_current'])

    def test_changed_saved_report_cannot_be_attached(self):
        session = self.begin()
        trained = self.trained(session)
        digest = self.report()
        path = self.store.home / 'datasets' / 'evaluations' / ('eval-' + digest + '.json')
        path.write_bytes(path.read_bytes() + b'modified')
        with self.assertRaisesRegex(LearningSessionError, 'integrity'):
            link_comparison(self.store, session['session_id'], digest,
                            expected_revision=trained['revision'], confirmed=True)
        self.assertEqual(session_status(self.store, session['session_id'])['stage'], 'trained')

    def test_closed_history_becomes_stale_after_revocation(self):
        session = self.begin()
        trained = self.trained(session)
        evaluated = link_comparison(
            self.store, session['session_id'], self.report(),
            expected_revision=trained['revision'], confirmed=True)
        closed = close_session(self.store, session['session_id'],
                               expected_revision=evaluated['revision'], confirmed=True)
        self.assertTrue(closed['evidence_current'])
        self.store.set_review('train_pairs', self.pair, 'rejected')
        self.assertFalse(session_status(self.store, session['session_id'])['evidence_current'])

    def test_cli_status_outputs_only_aggregate_without_model(self):
        session = self.begin()
        from athenz.train_cli import main, parser
        args = parser().parse_args(['session-status', session['session_id']])
        self.assertEqual(args.command, 'session-status')
        with mock.patch('athenz.train_cli.OllamaClient',
                        side_effect=AssertionError('no inference')), \
             mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('no local model inventory')), \
             mock.patch('builtins.print') as printing:
            main(['--home', str(self.store.home), 'session-status', session['session_id']])
        result = json.loads(printing.call_args.args[0])
        self.assertFalse(result['model_called'])
        self.assertNotIn('SYNTHETIC GOLD', json.dumps(result))
        self.assertNotIn(self.dataset, json.dumps(result))

    def test_invalid_session_identifier_is_rejected(self):
        for value in ('../outside', 'bad', 'f'*80, None, True):
            with self.subTest(value=value), self.assertRaises(LearningSessionError):
                session_status(self.store, value)


if __name__ == '__main__':
    unittest.main()
