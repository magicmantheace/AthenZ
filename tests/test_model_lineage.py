"""Synthetic, private-only audit of adapter -> GGUF -> Ollama -> review -> routing."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from athenz.adapters import register_adapter, select_for_review
from athenz.conversion import prepare_conversion, execute_conversion
from athenz.evaluation import _reference_fingerprint
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.model_gate import save_report, _heldout_fingerprint
from athenz.model_lineage import inspect_model_lineage, LineageAuditError
from athenz.ollama_import import prepare_import, import_local
from athenz.runtime import activate, checked_active_tag, rollback, RoutingError
from athenz.training import build_dataset

BASE = 'a' * 64
CANDIDATE = 'b' * 64
TAG = 'athenz-test:one'


class ModelLineageAuditTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        base = self.root / 'base'
        base.mkdir()
        (base / 'config.json').write_text('{"model_type":"qwen2"}')
        (base / 'tokenizer.json').write_text('{}')
        (base / 'model.safetensors').write_bytes(b'fictional weights')
        self.store.add_message('synthetic', 'agent', 'user', 'Synthetic task request')
        mid = self.store.add_message('synthetic', 'agent', 'assistant', 'Synthetic response')
        self.store.add_feedback(mid, 'up')
        self.pair = self.store.db.execute('SELECT id FROM train_pairs LIMIT 1').fetchone()[0]
        self.store.set_review('train_pairs', self.pair, 'approved')
        self.dataset = build_dataset(self.store, confirmed=True)['sha256']
        run = create_run(self.store, self.dataset, base, confirmed=True)
        self.run_id = run['run_id']
        def trainer(recipe, folder, data, *, resume):
            adapter = folder / 'adapter'
            adapter.mkdir()
            (adapter / 'adapter_model.safetensors').write_bytes(b'synthetic adapter')
            (adapter / 'adapter_config.json').write_text(json.dumps({
                'peft_type': 'LORA', 'base_model_name_or_path': str(base.resolve())}))
            return {'adapter_dir': str(adapter), 'examples_used': 1}
        execute_run(self.store, self.run_id, backend=trainer, confirmed=True)
        register_adapter(self.store, self.run_id, TAG, confirmed=True)
        for n in range(12):
            self.store.add_decision(
                'Separate synthetic approval case ' + str(n),
                'yes', 'PRIVATE_EXAMPLE_NOT_FOR_OUTPUT',
                source='synthetic', options=['yes', 'no'],
                split='calibration', approved=True)
        self.converter = self.root / 'convert_hf_to_gguf.py'
        self.converter.write_text(
            '# Synthetic converter, never execute.\n'
            'def convert():\n    return "fake"\n', encoding='utf-8')
        self.converter_sha = hashlib.sha256(self.converter.read_bytes()).hexdigest()
        self.gguf = self.root / 'manually-merged.gguf'
        self.gguf.write_bytes(b'GGUF' + (3).to_bytes(4, 'little') + b'S' * 48)
        self.tags = {'base': BASE, TAG: CANDIDATE}

    def _converted(self):
        prepare_conversion(self.store, self.run_id, self.converter,
                           converter_sha256=self.converter_sha,
                           confirmed=True, trust_converter=True)
        def converter(recipe, adapter, script, directory):
            output = directory / 'merged-f16.gguf'
            output.write_bytes(b'GGUF' + (3).to_bytes(4, 'little') + b'Z' * 48)
            return output
        completed = execute_conversion(
            self.store, self.run_id, backend=converter, confirmed=True)
        return Path(completed['artifact']['path'])

    def _imported(self, source):
        prepare_import(self.store, self.run_id, source,
                       candidate_tag=TAG, confirmed=True, acknowledge_merge=True)
        with mock.patch('athenz.ollama_import.shutil.which', return_value='ollama'), \
             mock.patch('athenz.ollama_import._not_installed'), \
             mock.patch('athenz.ollama_import.subprocess.run',
                        return_value=subprocess.CompletedProcess(['ollama'], 0)), \
             mock.patch('athenz.ollama_import.model_digest', return_value=CANDIDATE):
            imported = import_local(self.store, self.run_id, confirmed=True)
        self.assertEqual(imported['status'], 'complete')
        return imported

    def _reviewed(self):
        ids = [r[0] for r in self.store.db.execute(
            "SELECT id FROM decisions WHERE split='calibration' ORDER BY id")]
        report = {
            'schema': 1, 'dataset_sha256': self.dataset,
            'split': 'calibration', 'candidate': TAG,
            'baseline': 'base', 'cases': 12,
            'candidate_digest': CANDIDATE, 'baseline_digest': BASE,
            'eligible_for_review': True, 'accuracy_gain': 0.2,
            'attestation': 'local-model-observation-only',
            'promotion': 'not-authorized',
            'case_ids_sha256': hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
            'heldout_fingerprint': _heldout_fingerprint(self.store, 'calibration', 12),
            'reference_fingerprint': _reference_fingerprint(self.store)}
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag: self.tags[tag]):
            sha = save_report(self.store, report, confirmed=True)['sha256']
        select_for_review(self.store, self.run_id, sha,
                          expected_revision=0, confirmed=True,
                          lineage_acknowledged=True)
        return sha

    def _activated(self):
        class Stub:
            def generate(self, messages, **kwargs):
                return 'Synthetic short greeting.'
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag, **kw: self.tags[tag]):
            activate(self.store, baseline_tag='base', expected_revision=0,
                     confirmed=True, smoke_model_factory=lambda tag: Stub())

    def _audit(self, check=False):
        with mock.patch('athenz.model_lineage.model_digest',
                        side_effect=lambda tag: self.tags[tag]):
            return inspect_model_lineage(
                self.store, self.run_id, check_ollama=check)

    def test_approved_adapter_only_is_not_misrepresented_as_full_lineage(self):
        with mock.patch('athenz.model_lineage.model_digest',
                        side_effect=AssertionError('No unsolicited inventory')):
            found = inspect_model_lineage(self.store, self.run_id)
        self.assertEqual(found['stages']['adapter'], 'verified')
        self.assertEqual(found['stages']['conversion'], 'not-recorded')
        self.assertEqual(found['stages']['import'], 'not-recorded')
        self.assertEqual(found['stages']['evaluation'], 'not-linked')
        self.assertFalse(found['complete_local_record_chain'])
        self.assertFalse(found['all_recorded_local_stages_current'])
        self.assertFalse(found['model_called'])
        self.assertFalse(found['routing_changed'])
        self.assertNotIn(self.run_id, json.dumps(found))
        self.assertNotIn('PRIVATE_EXAMPLE', json.dumps(found))

    def test_full_local_conversion_import_review_runtime_chain(self):
        converted = self._converted()
        self._imported(converted)
        self._reviewed()
        self._activated()
        offline = self._audit()
        self.assertEqual(offline['provenance'], 'local-conversion-observed')
        self.assertTrue(offline['complete_local_record_chain'])
        self.assertFalse(offline['all_recorded_local_stages_current'])
        self.assertEqual(offline['stages']['ollama_candidate'], 'not-checked')
        observed = self._audit(check=True)
        self.assertTrue(observed['all_recorded_local_stages_current'])
        self.assertTrue(observed['installed_candidate_digest_matches'])
        self.assertEqual(observed['next_step'], 'all-recorded-local-stages-current')
        self.assertFalse(observed['independently_proven_model_derivation'])
        self.assertNotIn(str(converted), json.dumps(observed))
        self.assertNotIn(CANDIDATE, json.dumps(observed))

    def test_activation_pins_exact_recorded_import_and_rolls_back(self):
        gguf = self._converted()
        self._imported(gguf)
        self._reviewed()
        self._activated()
        from athenz.runtime import status
        routed = status(self.store)
        imported = self.store.get_checkpoint('ollama_import_' + self.run_id)
        self.assertEqual(routed['lineage_policy'], 'recorded-local-import')
        self.assertEqual(routed['import_revision'], imported['revision'])
        self.assertEqual(routed['gguf_sha256'], imported['state']['gguf_sha256'])
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag, **kw: self.tags[tag]):
            self.assertEqual(checked_active_tag(self.store), TAG)
            self.assertEqual(rollback(
                self.store, expected_revision=routed['revision'],
                confirmed=True)['active_tag'], 'base')

    def test_import_gguf_tamper_pauses_routing_but_not_baseline_rollback(self):
        gguf = self._converted()
        self._imported(gguf)
        self._reviewed()
        self._activated()
        gguf.write_bytes(b'GGUF' + (3).to_bytes(4, 'little') + b'D'*48)
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag, **kw: self.tags[tag]):
            with self.assertRaisesRegex(RoutingError, 'import'):
                checked_active_tag(self.store)
            self.assertEqual(rollback(
                self.store, expected_revision=1, confirmed=True)['active_tag'], 'base')

    def test_modified_import_evidence_during_smoke_does_not_activate(self):
        self._imported(self.gguf)
        self._reviewed()
        store, run_id = self.store, self.run_id
        class ChangingLocalModel:
            def generate(self, messages, **kwargs):
                cp = store.get_checkpoint('ollama_import_' + run_id)
                store.checkpoint(
                    'ollama_import_' + run_id, cp['task'], cp['state'],
                    status='paused', expected_revision=cp['revision'])
                return 'synthetic greeting'
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag, **kw: self.tags[tag]):
            with self.assertRaisesRegex(RoutingError, 'import'):
                activate(self.store, baseline_tag='base', expected_revision=0,
                         confirmed=True, smoke_model_factory=lambda tag: ChangingLocalModel())
        self.assertIsNone(self.store.get_checkpoint('ollama_runtime'))

    def test_tampered_import_digest_prevents_activation(self):
        self._imported(self.gguf)
        self._reviewed()
        cp = self.store.get_checkpoint('ollama_import_' + self.run_id)
        self.store.checkpoint('ollama_import_' + self.run_id, cp['task'],
                              {**cp['state'], 'candidate_digest': 'f'*64},
                              status='complete', expected_revision=cp['revision'])
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag, **kw: self.tags[tag]):
            with self.assertRaisesRegex(RoutingError, 'import'):
                activate(self.store, baseline_tag='base', expected_revision=0,
                         confirmed=True, smoke_model_factory=lambda tag: None)
        self.assertIsNone(self.store.get_checkpoint('ollama_runtime'))

    def test_manual_merge_can_never_claim_observed_local_conversion(self):
        self._imported(self.gguf)
        self._reviewed()
        self._activated()
        evidence = self._audit(check=True)
        self.assertEqual(evidence['provenance'], 'owner-attested-manual-merge')
        self.assertEqual(evidence['stages']['import'], 'verified')
        self.assertTrue(evidence['installed_candidate_digest_matches'])
        self.assertFalse(evidence['complete_local_record_chain'])
        self.assertFalse(evidence['all_recorded_local_stages_current'])
        self.assertEqual(evidence['next_step'],
                         'manual-merge-is-not-locally-conversion-verified')

    def test_prepared_or_interrupted_import_is_not_a_completed_artifact(self):
        staged = self._converted()
        prepare_import(self.store, self.run_id, staged,
                       candidate_tag=TAG, confirmed=True,
                       acknowledge_merge=True)
        found = self._audit(check=True)
        self.assertEqual(found['stages']['import'], 'not-complete')
        self.assertFalse(found['installed_candidate_digest_matches'])
        self.assertFalse(found['complete_local_record_chain'])

    def test_gguf_tampering_invalidates_conversion_and_import(self):
        converted = self._converted()
        self._imported(converted)
        converted.write_bytes(b'GGUF' + (3).to_bytes(4, 'little') + b'Y'*48)
        found = self._audit()
        self.assertEqual(found['stages']['conversion'], 'invalid')
        self.assertEqual(found['stages']['import'], 'invalid')
        self.assertFalse(found['complete_local_record_chain'])

    def test_wrong_installed_digest_is_not_reported_as_model_match(self):
        self._imported(self.gguf)
        self._reviewed()
        self._activated()
        self.tags[TAG] = 'f'*64
        observed = self._audit(check=True)
        self.assertEqual(observed['stages']['ollama_candidate'], 'digest-mismatch')
        self.assertFalse(observed['all_recorded_local_stages_current'])

    def test_review_mismatch_with_import_digest_rejected(self):
        self._imported(self.gguf)
        self._reviewed()
        cp = self.store.get_checkpoint('ollama_import_' + self.run_id)
        bad = {**cp['state'], 'candidate_digest': 'f'*64}
        self.store.checkpoint('ollama_import_' + self.run_id, cp['task'], bad,
                              status='complete', expected_revision=cp['revision'])
        result = self._audit()
        self.assertEqual(result['stages']['evaluation'], 'invalid')
        self.assertFalse(result['complete_local_record_chain'])

    def test_revoked_training_consent_is_not_bypassed(self):
        converted = self._converted()
        self._imported(converted)
        self._reviewed()
        self._activated()
        self.store.set_review('train_pairs', self.pair, 'rejected')
        audited = self._audit(check=True)
        self.assertEqual(audited['stages']['adapter'], 'invalid-or-missing')
        self.assertFalse(audited['complete_local_record_chain'])
        self.assertFalse(audited['installed_candidate_digest_matches'])

    def test_invalid_identifiers_and_flags_rejected(self):
        for run_id in ('../data', 'invalid', True, None):
            with self.subTest(value=run_id):
                with self.assertRaises(LineageAuditError):
                    inspect_model_lineage(self.store, run_id)
        with self.assertRaises(LineageAuditError):
            inspect_model_lineage(self.store, self.run_id, check_ollama=1)

    def test_cli_is_aggregate_only_and_does_not_trigger_model_or_export(self):
        self._converted()
        from athenz.train_cli import main, parser
        self.assertEqual(
            parser().parse_args(['lineage-audit', self.run_id]).command,
            'lineage-audit')
        with mock.patch('athenz.model_lineage.model_digest',
                        side_effect=AssertionError('Should not inspect Ollama')), \
             mock.patch('athenz.train_cli.OllamaClient',
                        side_effect=AssertionError('Should not infer')), \
             mock.patch('builtins.print') as printing:
            main(['--home', str(self.store.home), 'lineage-audit', self.run_id])
        response = json.loads(printing.call_args.args[0])
        self.assertEqual(response['stages']['conversion'], 'verified')
        self.assertFalse(response['model_called'])
        self.assertFalse(response['promotion_authorized'])
        self.assertNotIn(str(self.store.home), json.dumps(response))
        self.assertNotIn(self.run_id, json.dumps(response))


if __name__ == '__main__':
    unittest.main()
