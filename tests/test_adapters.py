"""Synthetic, local-only adapter registry and selection tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from athenz.adapters import (AdapterError, _read_review, inspect_adapter, register_adapter,
                            verified_registry_entry, selection, select_for_review,
                            rollback_selection)
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.training import build_dataset
from athenz.model_gate import save_report, _heldout_fingerprint
from athenz.evaluation import _reference_fingerprint


class AdaptersTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        self.model_dir = self.root / 'base'
        self.model_dir.mkdir()
        (self.model_dir / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.model_dir / 'tokenizer.json').write_text('{}')
        (self.model_dir / 'model.safetensors').write_bytes(b'synthetic')
        self.store.add_message('s','agent','user','synthetic training')
        mid = self.store.add_message('s','agent','assistant','synthetic answer')
        self.store.add_feedback(mid,'up')
        self.pair = self.store.db.execute('SELECT id FROM train_pairs').fetchone()[0]
        self.store.set_review('train_pairs',self.pair,'approved')
        self.dataset = build_dataset(self.store,confirmed=True)['sha256']
        for i in range(12):
            self.store.add_decision(f'heldout {i}', 'yes', 'synthetic',source='test',
                split='calibration',options=['yes','no'],approved=True)

    def completed(self,tag='candidate-a'):
        run = create_run(self.store,self.dataset,self.model_dir,confirmed=True)
        def backend(recipe, folder, dataset_path, *, resume):
            out = folder / 'adapter'
            out.mkdir()
            (out / 'adapter_model.safetensors').write_bytes(b'bytes-'+tag.encode())
            (out / 'adapter_config.json').write_text(json.dumps({
                'peft_type':'LORA', 'base_model_name_or_path':str(self.model_dir)}))
            return {'adapter_dir':str(out),'examples_used':1}
        execute_run(self.store, run['run_id'], backend=backend, confirmed=True)
        return run['run_id']

    def report(self, model='candidate-a',gain=0.2, eligible=True):
        ids = [r[0] for r in self.store.db.execute('SELECT id FROM decisions ORDER BY id')]
        obj={'schema':1,'dataset_sha256':self.dataset,'split':'calibration',
             'candidate':model,'baseline':'base','cases':12,
             'eligible_for_review':eligible,'accuracy_gain':gain,
             'attestation':'local-model-observation-only','promotion':'not-authorized',
             'case_ids_sha256':hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
             'heldout_fingerprint':_heldout_fingerprint(self.store,'calibration',12),
             'reference_fingerprint':_reference_fingerprint(self.store)}
        return save_report(self.store,obj,confirmed=True)['sha256']

    def test_existing_nonfinite_review_reports_are_never_eligible(self):
        valid_sha = self.report()
        directory = self.store.home / 'datasets' / 'evaluations'
        valid = json.loads((directory / ('eval-' + valid_sha + '.json')).read_text())
        for value in (float('nan'), float('inf'), True):
            with self.subTest(value=str(value)):
                tampered = {**valid, 'accuracy_gain': value}
                payload = (json.dumps(tampered, sort_keys=True,
                                      separators=(',', ':')) + '\n').encode('utf-8')
                sha = hashlib.sha256(payload).hexdigest()
                (directory / ('eval-' + sha + '.json')).write_bytes(payload)
                with self.assertRaisesRegex(AdapterError, 'not eligible'):
                    _read_review(self.store, sha)

    def test_old_report_with_tampered_aggregate_is_rejected(self):
        legacy_sha = self.report()
        directory = self.store.home / 'datasets' / 'evaluations'
        original = json.loads((directory / ('eval-' + legacy_sha + '.json')).read_text())
        manipulated = {**original, 'baseline_correct': 5,
                       'candidate_correct': 9, 'baseline_accuracy': 0.8,
                       'candidate_accuracy': 0.75}
        payload = (json.dumps(manipulated, sort_keys=True,
                              separators=(',', ':')) + '\n').encode()
        sha = hashlib.sha256(payload).hexdigest()
        (directory / ('eval-' + sha + '.json')).write_bytes(payload)
        with self.assertRaisesRegex(AdapterError, 'metadata is inconsistent'):
            _read_review(self.store, sha)

    def test_completed_run_registration_requires_explicit_confirmation(self):
        run=self.completed()
        with self.assertRaisesRegex(AdapterError,'confirm'):
            register_adapter(self.store,run,'candidate-a')
        registered=register_adapter(self.store,run,'candidate-a',confirmed=True)
        self.assertEqual(registered['candidate_model'],'candidate-a')
        self.assertEqual(registered['deployment'],'none')
        self.assertEqual(register_adapter(self.store,run,'candidate-a',confirmed=True),registered)
        with self.assertRaisesRegex(AdapterError,'immutable'):
            register_adapter(self.store,run,'candidate-b',confirmed=True)

    def test_tampered_adapter_detected_at_registration_and_selection(self):
        run=self.completed()
        register_adapter(self.store,run,'candidate-a',confirmed=True)
        weights=self.store.home/'runs'/('qlora-'+run)/'adapter'/'adapter_model.safetensors'
        weights.write_bytes(b'tampered')
        with self.assertRaisesRegex(AdapterError, 'changed'):
            verified_registry_entry(self.store,run)
        with self.assertRaisesRegex(AdapterError, 'changed'):
            register_adapter(self.store,run,'candidate-a',confirmed=True)

    def test_report_approval_gate_and_revision_conflict(self):
        run=self.completed()
        register_adapter(self.store,run,'candidate-a',confirmed=True)
        sha=self.report()
        with self.assertRaisesRegex(AdapterError, 'Require'):
            select_for_review(self.store,run,sha,expected_revision=0,confirmed=True)
        active=select_for_review(self.store,run,sha,expected_revision=0,
                                  confirmed=True,lineage_acknowledged=True)
        self.assertEqual(active['active_run_id'],run)
        self.assertEqual(active['status'],'selected-for-manual-review')
        self.assertEqual(active['deployment'],'none')
        with self.assertRaisesRegex(AdapterError,'changed'):
            select_for_review(self.store,run,sha,expected_revision=0,
                              confirmed=True,lineage_acknowledged=True)

    def test_mismatched_candidate_and_unimproved_score_rejected(self):
        run=self.completed()
        register_adapter(self.store,run,'candidate-a',confirmed=True)
        with self.assertRaisesRegex(AdapterError,'does not match'):
            select_for_review(self.store,run,self.report(model='candidate-b'),
                              expected_revision=0,confirmed=True,lineage_acknowledged=True)
        with self.assertRaisesRegex(AdapterError,'eligible'):
            select_for_review(self.store,run,self.report(gain=-0.01,eligible=False),
                              expected_revision=0,confirmed=True,lineage_acknowledged=True)

    def test_revocation_or_stale_evaluation_blocks_selection(self):
        run=self.completed()
        register_adapter(self.store,run,'candidate-a',confirmed=True)
        report=self.report()
        self.store.db.execute("UPDATE decisions SET scenario='changed' WHERE id=1")
        self.store.db.commit()
        with self.assertRaisesRegex(AdapterError, 'stale'):
            select_for_review(self.store,run,report,expected_revision=0,
                              confirmed=True,lineage_acknowledged=True)
        self.store.set_review('train_pairs',self.pair,'rejected')
        with self.assertRaisesRegex(Exception,'stale'):
            verified_registry_entry(self.store,run)

    def test_reference_memory_change_blocks_old_adapter_review(self):
        run=self.completed()
        register_adapter(self.store,run,'candidate-a',confirmed=True)
        report=self.report()
        self.store.propose('style', 'new approved preference', source='synthetic', approved=True)
        with self.assertRaisesRegex(AdapterError,'reference evidence is stale'):
            select_for_review(self.store,run,report,expected_revision=0,
                              confirmed=True,lineage_acknowledged=True)

    def test_rollback_restores_prior_pointer_and_requires_revision(self):
        run=self.completed('candidate-a')
        run2=self.completed('candidate-b')
        register_adapter(self.store,run,'candidate-a',confirmed=True)
        register_adapter(self.store,run2,'candidate-b',confirmed=True)
        a=self.report('candidate-a')
        b=self.report('candidate-b')
        first=select_for_review(self.store,run,a,expected_revision=0,
                                confirmed=True,lineage_acknowledged=True)
        second=select_for_review(self.store,run2,b,expected_revision=first['revision'],
                                 confirmed=True,lineage_acknowledged=True)
        with self.assertRaisesRegex(AdapterError,'revision'):
            rollback_selection(self.store,expected_revision=1,confirmed=True)
        third=rollback_selection(self.store,expected_revision=second['revision'],confirmed=True)
        self.assertEqual(third['active_run_id'],run)
        fourth=rollback_selection(self.store,expected_revision=third['revision'],confirmed=True)
        self.assertIsNone(fourth['active_run_id'])
        with self.assertRaisesRegex(AdapterError,'No matching'):
            rollback_selection(self.store,expected_revision=fourth['revision'],confirmed=True)

    def test_missing_adapter_config_or_symlink_refused(self):
        run=self.completed()
        config=self.store.home/'runs'/('qlora-'+run)/'adapter'/'adapter_config.json'
        config.unlink()
        with self.assertRaisesRegex(AdapterError,'missing'):
            inspect_adapter(self.store,run)

if __name__=='__main__':
    unittest.main()
