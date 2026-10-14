"""Synthetic session evidence, no network or owner data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.adapters import register_adapter
from athenz.evaluation import _reference_fingerprint
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.learning_session import (
    LearningSessionError, start_session, session_status, link_completed_run,
    link_comparison, close_session, cancel_session)
from athenz.model_gate import (
    _approved_heldout_population, _heldout_fingerprint, save_report)
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

    def trained(self, session):
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
        base, cand = (5,9) if better else (9,5)
        report = {
            'schema':2, 'dataset_sha256':self.dataset, 'split':'calibration',
            'seed':42, 'cases':12, 'requested_case_limit':12,
            'approved_split_total':total, 'approved_split_sha256':population,
            'baseline':'base-local', 'candidate':'candidate-local',
            'baseline_digest':'a'*64, 'candidate_digest':'b'*64,
            'baseline_correct':base, 'candidate_correct':cand,
            'baseline_accuracy':base/12, 'candidate_accuracy':cand/12,
            'accuracy_gain':round((cand-base)/12,8),
            'paired_improved':4 if better else 0,
            'paired_regressed':0 if better else 4,
            'paired_unchanged':8,
            'paired_one_sided_p_value':0.0625 if better else 1.0,
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
