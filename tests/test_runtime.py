"""Synthetic tests: private approval, pinned local tag routing and rollback."""
import hashlib
import json
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest import mock

from athenz.adapters import register_adapter, select_for_review
from athenz.chat import LocalModelError
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.model_gate import save_report, _heldout_fingerprint
from athenz.evaluation import _reference_fingerprint
from athenz.runtime import (RoutingError, activate, checked_active_tag,
                            model_digest, rollback, status, inspect_rollback_readiness,
                            rehearse_rollback)
from athenz.train_cli import parser
from athenz.training import build_dataset


BASE = 'a' * 64
CANDIDATE = 'b' * 64


class FakeModel:
    def __init__(self, response='hello'):
        self.response = response
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


class RoutingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.s = ExperienceStore(self.root / 'private')
        self.addCleanup(self.s.close)
        self.model_dir = self.root / 'model'
        self.model_dir.mkdir()
        (self.model_dir / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.model_dir / 'tokenizer.json').write_text('{}')
        (self.model_dir / 'model.safetensors').write_bytes(b'synthetic')
        self.s.add_message('s', 'agent', 'user', 'hello')
        msg = self.s.add_message('s', 'agent', 'assistant', 'hello')
        self.s.add_feedback(msg, 'up')
        self.pair = self.s.db.execute('SELECT id FROM train_pairs').fetchone()[0]
        self.s.set_review('train_pairs', self.pair, 'approved')
        self.dataset = build_dataset(self.s, confirmed=True)['sha256']
        for i in range(12):
            self.s.add_decision('calibration sample ' + str(i), 'yes', 'reason',
                                source='synthetic', options=['yes', 'no'],
                                split='calibration', approved=True)
        run = create_run(self.s, self.dataset, self.model_dir, confirmed=True)
        self.run_id = run['run_id']

        def backend(recipe, folder, dataset_path, *, resume):
            adapter = folder / 'adapter'
            adapter.mkdir()
            (adapter / 'adapter_model.safetensors').write_bytes(b'synthetic adapter')
            (adapter / 'adapter_config.json').write_text(json.dumps({
                'peft_type': 'LORA', 'base_model_name_or_path': str(self.model_dir.resolve())}))
            return {'adapter_dir': str(adapter), 'examples_used': 1}

        execute_run(self.s, self.run_id, backend=backend, confirmed=True)
        register_adapter(self.s, self.run_id, 'candidate-a', confirmed=True)
        ids = [r[0] for r in self.s.db.execute('SELECT id FROM decisions ORDER BY id')]
        report = {'schema': 1, 'dataset_sha256': self.dataset, 'split': 'calibration',
                  'candidate': 'candidate-a', 'baseline': 'base', 'cases': 12,
                  'candidate_digest': CANDIDATE, 'baseline_digest': BASE,
                  'eligible_for_review': True, 'accuracy_gain': 0.2,
                  'attestation': 'local-model-observation-only', 'promotion': 'not-authorized',
                  'case_ids_sha256': hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
                  'heldout_fingerprint': _heldout_fingerprint(self.s, 'calibration', 12),
                  'reference_fingerprint': _reference_fingerprint(self.s)}
        self.seen = {'base': BASE, 'candidate-a': CANDIDATE}
        self.digest_patcher = mock.patch('athenz.runtime.model_digest', side_effect=self._digest)
        self.digest_patcher.start()
        self.addCleanup(self.digest_patcher.stop)
        self.report_sha = save_report(self.s, report, confirmed=True)['sha256']
        self.probe = FakeModel()

    def _digest(self, tag, **kwargs):
        if tag not in self.seen:
            raise RoutingError('No local model')
        return self.seen[tag]

    def select(self):
        select_for_review(self.s, self.run_id, self.report_sha, expected_revision=0,
                          confirmed=True, lineage_acknowledged=True)

    def activate(self, *, revision=0):
        return activate(self.s, expected_revision=revision, baseline_tag='base',
                        confirmed=True, smoke_model_factory=lambda tag: self.probe,
                        ack_legacy_lineage=True)

    def test_default_routing_uses_existing_configuration(self):
        self.assertIsNone(checked_active_tag(self.s))
        self.assertEqual(status(self.s)['revision'], 0)

    def test_activation_requires_selection_and_exact_baseline(self):
        with self.assertRaisesRegex(RoutingError, 'Select'):
            self.activate()
        self.select()
        with self.assertRaisesRegex(RoutingError, 'confirm'):
            activate(self.s, expected_revision=0, baseline_tag='base')
        with self.assertRaisesRegex(RoutingError, 'revision'):
            self.activate(revision=1)
        with self.assertRaisesRegex(RoutingError, 'identities'):
            activate(self.s, expected_revision=0, baseline_tag='other', confirmed=True)

    def test_new_activation_requires_import_or_explicit_legacy_ack(self):
        self.select()
        with self.assertRaisesRegex(RoutingError, 'ack-legacy-lineage'):
            activate(self.s, expected_revision=0, baseline_tag='base',
                     confirmed=True, smoke_model_factory=lambda tag: self.probe)
        self.assertEqual(self.probe.calls, [])
        self.assertEqual(status(self.s)['revision'], 0)
        active = self.activate()
        self.assertEqual(active['lineage_policy'], 'legacy-owner-attested')
        self.assertIsNone(active['import_revision'])
        self.assertEqual(checked_active_tag(self.s), 'candidate-a')
        self.assertEqual(rollback(self.s, expected_revision=1,
                                  confirmed=True)['active_tag'], 'base')

    def test_invalid_existing_import_cannot_fallback_to_legacy(self):
        self.select()
        self.s.checkpoint(
            'ollama_import_' + self.run_id,
            'Incomplete synthetic import', {'status': 'incomplete'},
            status='paused', expected_revision=0)
        with self.assertRaisesRegex(RoutingError, 'import'):
            self.activate()
        self.assertEqual(self.probe.calls, [])
        self.assertEqual(status(self.s)['revision'], 0)

    def test_legacy_acknowledgment_must_be_explicit_boolean(self):
        self.select()
        with self.assertRaisesRegex(RoutingError, 'Invalid legacy-lineage'):
            activate(self.s, expected_revision=0, baseline_tag='base',
                     confirmed=True, ack_legacy_lineage='yes',
                     smoke_model_factory=lambda tag: self.probe)
        self.assertEqual(self.probe.calls, [])
        self.assertEqual(status(self.s)['revision'], 0)

    def test_pre_gate_active_checkpoint_remains_rollback_capable(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        old = {k: v for k, v in cp['state'].items()
               if k not in ('routing_schema', 'lineage_policy', 'import_revision', 'gguf_sha256')}
        self.s.checkpoint('ollama_runtime', cp['task'], old,
                          status='paused', expected_revision=cp['revision'])
        self.assertEqual(checked_active_tag(self.s), 'candidate-a')
        self.assertEqual(rollback(self.s, expected_revision=2,
                                  confirmed=True)['active_tag'], 'base')

    def test_new_provenance_missing_policy_blocks_routing(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        changed = {k: v for k, v in cp['state'].items()
                   if k != 'lineage_policy'}
        self.s.checkpoint('ollama_runtime', cp['task'], changed,
                          status='paused', expected_revision=cp['revision'])
        with self.assertRaisesRegex(RoutingError, 'provenance marker'):
            checked_active_tag(self.s)
        self.assertEqual(rollback(
            self.s, expected_revision=2, confirmed=True)['active_tag'], 'base')

    def test_baseline_changed_during_candidate_smoke_blocks_activation(self):
        self.select()
        before = self.s.get_checkpoint('ollama_runtime')
        seen = self.seen
        class MutatingSyntheticModel:
            def generate(self, messages, **kwargs):
                seen['base'] = 'f'*64
                return 'synthetic greeting'
        with self.assertRaisesRegex(RoutingError, 'Baseline tag changed'):
            activate(self.s, expected_revision=0, baseline_tag='base',
                     confirmed=True, ack_legacy_lineage=True,
                     smoke_model_factory=lambda tag: MutatingSyntheticModel())
        self.assertEqual(self.s.get_checkpoint('ollama_runtime'), before)

    def test_candidate_smoke_failure_suppresses_private_exception(self):
        self.select()
        class FailingSyntheticModel:
            def generate(self, messages, **kwargs):
                raise RuntimeError('PRIVATE_LOCAL_USER_CONTENT_DO_NOT_SHOW')
        with self.assertRaisesRegex(RoutingError, 'inference failed') as caught:
            activate(self.s, expected_revision=0, baseline_tag='base',
                     confirmed=True, ack_legacy_lineage=True,
                     smoke_model_factory=lambda tag: FailingSyntheticModel())
        self.assertNotIn('PRIVATE_LOCAL_USER_CONTENT_DO_NOT_SHOW',
                         ''.join(traceback.format_exception(caught.exception)))
        self.assertEqual(status(self.s)['revision'], 0)

    def test_successful_activation_pins_tag_and_baseline_then_rollback(self):
        self.select()
        active = self.activate()
        self.assertEqual((active['revision'], active['active_tag'], active['active_digest']),
                         (1, 'candidate-a', CANDIDATE))
        self.assertEqual(checked_active_tag(self.s), 'candidate-a')
        self.assertEqual(self.probe.calls[0][0][0]['content'], 'Reply with a short greeting.')
        with self.assertRaisesRegex(RoutingError, 'Roll back'):
            self.activate(revision=1)
        with self.assertRaisesRegex(RoutingError, 'revision'):
            rollback(self.s, expected_revision=0, confirmed=True)
        restored = rollback(self.s, expected_revision=1, confirmed=True)
        self.assertEqual(restored['active_tag'], 'base')
        self.assertIsNone(restored['active_run_id'])
        self.assertEqual(checked_active_tag(self.s), 'base')
        with self.assertRaisesRegex(RoutingError, 'No current'):
            rollback(self.s, expected_revision=2, confirmed=True)

    def test_unbenchmarked_replaced_candidate_is_rejected_before_smoke(self):
        self.select()
        self.seen['candidate-a'] = 'f' * 64
        with self.assertRaisesRegex(RoutingError, 'differ from evaluated'):
            self.activate()
        self.assertEqual(status(self.s)['revision'], 0)
        self.assertEqual(self.probe.calls, [])

    def test_digest_drift_fails_closed_and_rollback_ignores_missing_candidate(self):
        self.select()
        self.activate()
        self.seen['candidate-a'] = 'c' * 64
        with self.assertRaisesRegex(RoutingError, 'digest changed'):
            checked_active_tag(self.s)
        del self.seen['candidate-a']
        self.assertEqual(rollback(self.s, expected_revision=1, confirmed=True)['active_tag'], 'base')

    def test_private_consent_revocation_blocks_routing_but_allows_rollback(self):
        self.select()
        self.activate()
        self.s.set_review('train_pairs', self.pair, 'rejected')
        with self.assertRaisesRegex(Exception, 'stale'):
            checked_active_tag(self.s)
        self.assertEqual(rollback(self.s, expected_revision=1, confirmed=True)['active_tag'], 'base')

    def test_inference_failure_and_tag_change_do_not_install_pointer(self):
        self.select()
        self.probe.response = ''
        with self.assertRaisesRegex(RoutingError, 'no text'):
            self.activate()
        self.assertEqual(status(self.s)['revision'], 0)
        self.probe.response = 'hello'
        actual = self._digest
        calls = {'count': 0}
        def drift(tag, **kwargs):
            if tag == 'candidate-a':
                calls['count'] += 1
                return CANDIDATE if calls['count'] == 1 else 'c' * 64
            return actual(tag)
        with mock.patch('athenz.runtime.model_digest', side_effect=drift):
            with self.assertRaisesRegex(RoutingError, 'changed during'):
                self.activate()
        self.assertEqual(status(self.s)['revision'], 0)

    def test_changed_heldout_gold_fails_closed(self):
        self.select()
        self.activate()
        self.s.db.execute("UPDATE decisions SET choice='no' WHERE id=1")
        self.s.db.commit()
        with self.assertRaisesRegex(Exception, 'stale'):
            checked_active_tag(self.s)
        rollback(self.s, expected_revision=1, confirmed=True)

    def test_baseline_digest_drift_blocks_rollback(self):
        self.select()
        self.activate()
        self.seen['base'] = 'd' * 64
        with self.assertRaisesRegex(RoutingError, 'baseline digest changed'):
            rollback(self.s, expected_revision=1, confirmed=True)
        self.assertEqual(status(self.s)['active_tag'], 'candidate-a')

    def test_rollback_preflight_requires_explicit_read_only_inventory(self):
        self.select()
        self.activate()
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('Unexpected offline inventory')):
            offline = inspect_rollback_readiness(self.s)
        self.assertEqual(offline['revision'], 1)
        self.assertTrue(offline['candidate_active'])
        self.assertTrue(offline['baseline_record_valid'])
        self.assertFalse(offline['ready_for_manual_rollback'])
        self.assertFalse(offline['local_inventory_checked'])
        self.assertEqual(status(self.s)['revision'], 1)
        checked = inspect_rollback_readiness(self.s, check_ollama=True)
        self.assertTrue(checked['baseline_digest_matches'])
        self.assertTrue(checked['ready_for_manual_rollback'])
        self.assertEqual(checked['next_step'], 'owner-may-confirm-runtime-rollback')
        self.assertFalse(checked['routing_changed'])
        self.assertEqual(status(self.s)['active_tag'], 'candidate-a')

    def test_rollback_preflight_ignores_revoked_candidate(self):
        self.select()
        self.activate()
        self.s.set_review('train_pairs', self.pair, 'rejected')
        del self.seen['candidate-a']
        checked = inspect_rollback_readiness(self.s, check_ollama=True)
        self.assertTrue(checked['ready_for_manual_rollback'])
        self.assertEqual(status(self.s)['revision'], 1)
        self.assertEqual(rollback(self.s, expected_revision=1, confirmed=True)['active_tag'], 'base')
        self.assertEqual(inspect_rollback_readiness(self.s, check_ollama=True)['next_step'],
                         'no-active-candidate')

    def test_rollback_readiness_fails_closed_on_baseline_digest_drift(self):
        self.select()
        self.activate()
        self.seen['base'] = 'f'*64
        result = inspect_rollback_readiness(self.s, check_ollama=True)
        self.assertFalse(result['ready_for_manual_rollback'])
        self.assertFalse(result['baseline_digest_matches'])
        self.assertEqual(result['next_step'], 'restore-or-review-pinned-baseline')
        self.assertEqual(status(self.s)['active_tag'], 'candidate-a')
        del self.seen['base']
        self.assertFalse(inspect_rollback_readiness(self.s, check_ollama=True)['ready_for_manual_rollback'])

    def test_rollback_readiness_refuses_malformed_checkpoint_without_mutation(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        state = {**cp['state'], 'baseline_digest': 'invalid'}
        self.s.checkpoint('ollama_runtime', cp['task'], state,
                          expected_revision=cp['revision'])
        with mock.patch('athenz.runtime.model_digest',
                        side_effect=AssertionError('Unsafe inventory access')):
            check = inspect_rollback_readiness(self.s, check_ollama=True)
        self.assertFalse(check['baseline_record_valid'])
        self.assertFalse(check['local_inventory_checked'])
        self.assertFalse(check['ready_for_manual_rollback'])

    def test_rollback_rehearsal_checks_actual_baseline_and_discards_checkpoint(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        before = self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        model = FakeModel('synthetic-greeting-only')
        result = rehearse_rollback(
            self.s, expected_revision=1, confirmed=True,
            smoke_model_factory=lambda tag: model)
        self.assertEqual(result['revision'], 1)
        self.assertTrue(result['baseline_smoke_passed'])
        self.assertTrue(result['projected_checkpoint_tested'])
        self.assertTrue(result['checkpoint_unchanged'])
        self.assertFalse(result['routing_changed'])
        self.assertTrue(result['ready_for_owner_rollback'])
        self.assertNotIn('synthetic-greeting-only', json.dumps(result))
        self.assertEqual(model.calls[0][0],
                         [{'role':'user','content':'Reply with a short greeting.'}])
        self.assertEqual(self.s.get_checkpoint('ollama_runtime'), cp)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                         before)
        self.assertEqual(checked_active_tag(self.s), 'candidate-a')
        self.assertEqual(rollback(self.s, expected_revision=1, confirmed=True)['active_tag'],
                         'base')

    def test_rollback_rehearsal_rejects_no_consent_without_smoke(self):
        self.select()
        self.activate()
        model = FakeModel()
        before = self.s.get_checkpoint('ollama_runtime')
        with self.assertRaisesRegex(RoutingError, 'confirm'):
            rehearse_rollback(
                self.s, expected_revision=1, smoke_model_factory=lambda tag: model)
        self.assertEqual(model.calls, [])
        self.assertEqual(self.s.get_checkpoint('ollama_runtime'), before)

    def test_rollback_rehearsal_works_with_revoked_or_deleted_candidate(self):
        self.select()
        self.activate()
        self.s.set_review('train_pairs', self.pair, 'rejected')
        del self.seen['candidate-a']
        model = FakeModel()
        result = rehearse_rollback(
            self.s, expected_revision=1, confirmed=True,
            smoke_model_factory=lambda tag: model)
        self.assertTrue(result['ready_for_owner_rollback'])
        self.assertEqual(model.calls[0][0][0]['content'], 'Reply with a short greeting.')
        self.assertEqual(status(self.s)['active_tag'], 'candidate-a')
        self.assertEqual(rollback(self.s, expected_revision=1, confirmed=True)['active_tag'],
                         'base')

    def test_rollback_rehearsal_fails_closed_on_missing_baseline(self):
        self.select()
        self.activate()
        del self.seen['base']
        with self.assertRaisesRegex(RoutingError, 'No local model'):
            rehearse_rollback(
                self.s, expected_revision=1, confirmed=True,
                smoke_model_factory=lambda tag: FakeModel())
        self.assertEqual(status(self.s)['revision'], 1)

    def test_rollback_rehearsal_rejects_model_change_during_smoke(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        original = self._digest
        seen = {'reads':0}
        def drift(tag, **kwargs):
            if tag == 'base':
                seen['reads'] += 1
                return BASE if seen['reads'] == 1 else 'f' * 64
            return original(tag)
        with mock.patch('athenz.runtime.model_digest', side_effect=drift):
            with self.assertRaisesRegex(RoutingError, 'changed during rehearsal'):
                rehearse_rollback(
                    self.s, expected_revision=1, confirmed=True,
                    smoke_model_factory=lambda tag: FakeModel())
        self.assertEqual(self.s.get_checkpoint('ollama_runtime'), cp)

    def test_rollback_rehearsal_suppresses_private_backend_exceptions(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        class Failing:
            def generate(self, messages, **kwargs):
                raise RuntimeError('PRIVATE_SIMULATED_OWNER_PROMPT')
        with self.assertRaisesRegex(RoutingError, 'Baseline smoke inference failed') as caught:
            rehearse_rollback(
                self.s, expected_revision=1, confirmed=True,
                smoke_model_factory=lambda tag: Failing())
        self.assertNotIn('PRIVATE_SIMULATED_OWNER_PROMPT',
                         ''.join(traceback.format_exception(caught.exception)))
        self.assertEqual(self.s.get_checkpoint('ollama_runtime'), cp)

    def test_rollback_rehearsal_restores_savepoint_on_staged_failure(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        before = self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        actual = self.s.checkpoint
        def fail_after_write(*args, **kwargs):
            result = actual(*args, **kwargs)
            raise ValueError('Synthetic error after staged checkpoint')
        with mock.patch.object(self.s, 'checkpoint', side_effect=fail_after_write):
            with self.assertRaisesRegex(RoutingError, 'Rollback rehearsal failed') as caught:
                rehearse_rollback(
                    self.s, expected_revision=1, confirmed=True,
                    smoke_model_factory=lambda tag: FakeModel())
        self.assertNotIn('Synthetic error after staged checkpoint',
                         ''.join(traceback.format_exception(caught.exception)))
        self.assertEqual(self.s.get_checkpoint('ollama_runtime'), cp)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                         before)

    def test_rollback_rehearsal_rejects_changed_revision_after_smoke(self):
        self.select()
        self.activate()
        cp = self.s.get_checkpoint('ollama_runtime')
        store = self.s
        class Mutating:
            def generate(self, messages, **kwargs):
                store.checkpoint('ollama_runtime', cp['task'], cp['state'],
                                 expected_revision=cp['revision'])
                return 'hello'
        with self.assertRaisesRegex(RoutingError, 'revision changed'):
            rehearse_rollback(
                self.s, expected_revision=1, confirmed=True,
                smoke_model_factory=lambda tag: Mutating())
        self.assertEqual(status(self.s)['revision'], 2)
        self.assertEqual(status(self.s)['active_tag'], 'candidate-a')

    def test_runtime_cli_commands_present(self):
        actions = parser()._subparsers._group_actions[0].choices
        self.assertTrue({'runtime-activate', 'runtime-status', 'runtime-rollback',
                         'runtime-rehearse-rollback'} <= set(actions))


class APIInventoryTests(unittest.TestCase):
    def test_tag_list_and_missing_or_malformed_digest(self):
        class Resp:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return self.data
        class Opener:
            def __init__(self, result): self.result = result
            def open(self, request, timeout):
                self.last_url = request.full_url
                return Resp(self.result)
        good = Opener(json.dumps({'models':[{'name':'base:latest','digest':BASE}]}).encode())
        with mock.patch('athenz.runtime.build_opener', return_value=good):
            self.assertEqual(model_digest('base'), BASE)
            self.assertEqual(good.last_url, 'http://127.0.0.1:11434/api/tags')
        bad = Opener(b'{"models":[{"name":"base:latest","digest":"not-a-hash"}]}')
        with mock.patch('athenz.runtime.build_opener', return_value=bad):
            with self.assertRaisesRegex(RoutingError, 'missing, ambiguous'):
                model_digest('base')
        with self.assertRaisesRegex(RoutingError, 'explicit'):
            model_digest('evil/path')
        with self.assertRaises(LocalModelError):
            model_digest('base', endpoint='https://example.com:443')


if __name__ == '__main__':
    unittest.main()
