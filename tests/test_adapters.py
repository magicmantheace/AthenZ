"""Synthetic, local-only adapter registry and selection tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.adapters import (AdapterError, _read_review, inspect_adapter, register_adapter,
                            verified_registry_entry, selection, select_for_review,
                            rollback_selection)
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.training import build_dataset
from athenz.model_gate import save_report, _heldout_fingerprint, _approved_heldout_population
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
        ids = [r[0] for r in self.store.db.execute(
            'SELECT id FROM decisions ORDER BY id LIMIT 12')]
        obj={'schema':1,'dataset_sha256':self.dataset,'split':'calibration',
             'candidate':model,'baseline':'base','cases':12,
             'eligible_for_review':eligible,'accuracy_gain':gain,
             'attestation':'local-model-observation-only','promotion':'not-authorized',
             'case_ids_sha256':hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
             'heldout_fingerprint':_heldout_fingerprint(self.store,'calibration',12),
             'reference_fingerprint':_reference_fingerprint(self.store)}
        return save_report(self.store,obj,confirmed=True)['sha256']

    def schema_two_report(self):
        """Build synthetic new-schema evidence without contacting Ollama."""
        old_sha = self.report()
        folder = self.store.home / 'datasets' / 'evaluations'
        old = json.loads((folder / ('eval-' + old_sha + '.json')).read_text())
        total, population_sha = _approved_heldout_population(self.store, 'calibration')
        new = {**old, 'schema': 2,
               'requested_case_limit': 12, 'approved_split_total': total,
               'approved_split_sha256': population_sha,
               'baseline_digest': 'a' * 64, 'candidate_digest': 'b' * 64,
               'baseline_correct': 5, 'candidate_correct': 9,
               'baseline_accuracy': 5 / 12, 'candidate_accuracy': 9 / 12,
               'accuracy_gain': round(4 / 12, 8), 'chance_expected': 0.5,
               'paired_improved': 4, 'paired_regressed': 0,
               'paired_unchanged': 8, 'paired_one_sided_p_value': 0.0625}
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=lambda tag: 'a' * 64 if tag == 'base' else 'b' * 64):
            return save_report(self.store, new, confirmed=True)['sha256']

    def test_new_schema_report_survives_review_only_while_population_matches(self):
        sha = self.schema_two_report()
        original = _read_review(self.store, sha)
        self.assertEqual(original['schema'], 2)
        self.assertEqual(original['approved_split_total'], 12)
        self.store.add_decision(
            'Would the owner approve a completely different synthetic task?',
            'yes', 'PRIVATE NEW CASE', source='synthetic',
            split='calibration', options=['yes', 'no'], approved=True)
        with self.assertRaisesRegex(AdapterError, 'population changed'):
            _read_review(self.store, sha)

    def test_new_schema_detects_out_of_window_case_content_edits(self):
        extra_id = self.store.add_decision(
            'Would an owner perform an entirely new optional synthetic audit?',
            'yes', 'PRIVATE EVIDENCE BEYOND TWELVE',
            source='synthetic', split='calibration',
            options=['yes', 'no'], approved=True)
        sha = self.schema_two_report()
        report = _read_review(self.store, sha)
        self.assertEqual(report['cases'], 12)
        self.assertEqual(report['approved_split_total'], 13)
        with self.store.db:
            self.store.db.execute(
                'UPDATE decisions SET rationale=? WHERE id=?',
                ('CHANGED PRIVATE EVIDENCE BEYOND TWELVE', extra_id))
        with self.assertRaisesRegex(AdapterError, 'population changed'):
            _read_review(self.store, sha)

    def test_new_schema_review_rejects_tampered_population_fields(self):
        sha = self.schema_two_report()
        directory = self.store.home / 'datasets' / 'evaluations'
        original = json.loads((directory / ('eval-' + sha + '.json')).read_text())
        for drop in ('approved_split_total', 'approved_split_sha256',
                     'requested_case_limit', 'baseline_correct', 'paired_improved'):
            with self.subTest(drop=drop):
                altered = {k: v for k, v in original.items() if k != drop}
                body = (json.dumps(altered, sort_keys=True,
                                   separators=(',', ':')) + '\n').encode()
                tampered_sha = hashlib.sha256(body).hexdigest()
                (directory / ('eval-' + tampered_sha + '.json')).write_bytes(body)
                with self.assertRaisesRegex(AdapterError, 'metadata is inconsistent'):
                    _read_review(self.store, tampered_sha)

    def test_schema_one_legacy_review_still_readable_without_claiming_new_freshness(self):
        sha = self.report()
        legacy = _read_review(self.store, sha)
        self.assertEqual(legacy['schema'], 1)
        self.assertNotIn('approved_split_total', legacy)

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

    def test_new_cross_split_overlap_blocks_existing_adapter_report(self):
        report_sha = self.report()
        self.store.add_decision('heldout 1!',
            'yes', 'Different approved test partition reason',
            source='synthetic', options=['yes', 'no'],
            split='test', approved=True)
        with self.assertRaisesRegex(AdapterError, 'partitions overlap'):
            _read_review(self.store, report_sha)

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

    def test_registry_metadata_tamper_fails_closed(self):
        run = self.completed()
        register_adapter(self.store, run, 'candidate-a', confirmed=True)
        key = 'adapter_' + run
        row = self.store.db.execute(
            'SELECT state_json FROM checkpoints WHERE task_key=?', (key,)).fetchone()
        original = json.loads(row['state_json'])
        modifications = (
            {'candidate_model': 'candidate-b'},
            {'candidate_model': ''},
            {'lineage': 'automatically-proven'},
            {'deployment': 'activated'},
            {'extra_authority': 'unreviewed'},
            {'dataset_sha256': 'f' * 64},
        )
        for delta in modifications:
            with self.subTest(modification=delta):
                forged = {**original, **delta}
                with self.store.db:
                    self.store.db.execute(
                        'UPDATE checkpoints SET state_json=? WHERE task_key=?',
                        (json.dumps(forged), key))
                with self.assertRaisesRegex(AdapterError, 'stale or tampered'):
                    verified_registry_entry(self.store, run)
        with self.store.db:
            self.store.db.execute(
                'UPDATE checkpoints SET state_json=? WHERE task_key=?',
                (json.dumps(original), key))
        self.assertEqual(verified_registry_entry(self.store, run), original)

    def test_registry_event_anchor_is_idempotent_and_append_only(self):
        run = self.completed()
        original = register_adapter(self.store, run, 'candidate-a', confirmed=True)
        self.assertEqual(register_adapter(
            self.store, run, 'candidate-a', confirmed=True), original)
        record = self.store.get_checkpoint('adapter_' + run)
        rows = self.store.db.execute(
            "SELECT operation FROM events WHERE subject_type='checkpoints' "
            "AND subject_id=? AND operation LIKE 'adapter-registration:%'",
            (record['id'],)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['operation'].startswith('adapter-registration:'))
        with self.assertRaises(Exception):
            with self.store.db:
                self.store.db.execute(
                    "UPDATE events SET operation='forged' WHERE operation=?",
                    (rows[0]['operation'],))

    def test_conflicting_extra_registry_anchor_fails_closed(self):
        run = self.completed()
        register_adapter(self.store, run, 'candidate-a', confirmed=True)
        record = self.store.get_checkpoint('adapter_' + run)
        with self.store.db:
            self.store._event('adapter-registration:' + 'f' * 64,
                              'checkpoints', record['id'])
        with self.assertRaisesRegex(AdapterError, 'stale or tampered'):
            verified_registry_entry(self.store, run)
        with self.assertRaisesRegex(AdapterError, 'immutable'):
            register_adapter(self.store, run, 'candidate-a', confirmed=True)

    def test_legacy_registration_requires_explicit_anchor_reconfirmation(self):
        run = self.completed()
        evidence = inspect_adapter(self.store, run)
        legacy = {**evidence, 'candidate_model': 'candidate-a',
                  'lineage': 'owner-label-unverified', 'deployment': 'none'}
        self.store.checkpoint('adapter_' + run,
                              'Private adapter registry entry; not a deployed model',
                              legacy, status='complete')
        with self.assertRaisesRegex(AdapterError, 'stale or tampered'):
            verified_registry_entry(self.store, run)
        with self.assertRaisesRegex(AdapterError, 'confirm'):
            register_adapter(self.store, run, 'candidate-a')
        upgraded = register_adapter(self.store, run, 'candidate-a', confirmed=True)
        self.assertEqual(upgraded, legacy)
        self.assertEqual(verified_registry_entry(self.store, run), legacy)
        with self.assertRaisesRegex(AdapterError, 'immutable'):
            register_adapter(self.store, run, 'candidate-b', confirmed=True)

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
