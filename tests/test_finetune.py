"""No model weights, user data, CUDA or optional trainer packages are used."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from athenz.experience import ExperienceStore
from athenz.finetune import (TrainingError, _model_snapshot, create_run,
                            describe_run, encode_example, execute_run, verify_run)
from athenz.training import build_dataset


class MockTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        self.assert_unused = (tokenize, add_generation_prompt)
        return [10, 20] if len(messages) == 1 else [10, 20, 31, 32]


class FinetuneTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        self.model = self.root / 'qwen-local'
        self.model.mkdir()
        (self.model / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.model / 'tokenizer.json').write_text('{}')
        (self.model / 'model.safetensors').write_bytes(b'synthetic local model weights')
        self.store.add_message('s', 'agent', 'user', 'synthetic prompt')
        reply = self.store.add_message('s', 'agent', 'assistant', 'synthetic answer')
        self.store.add_feedback(reply, 'up')
        pair_id = self.store.db.execute('SELECT id FROM train_pairs').fetchone()[0]
        self.store.set_review('train_pairs', pair_id, 'approved')
        self.pair_id = pair_id
        self.sha = build_dataset(self.store, confirmed=True)['sha256']

    def prepare(self):
        return create_run(self.store, self.sha, self.model, max_steps=5, confirmed=True)

    def test_requires_confirmation_and_model_architecture(self):
        with self.assertRaisesRegex(TrainingError, 'confirm'):
            create_run(self.store, self.sha, self.model)
        (self.model / 'config.json').write_text('{"model_type":"other"}')
        with self.assertRaisesRegex(TrainingError, 'Only the reviewed'):
            self.prepare()
        self.assertFalse((self.store.home / 'runs').exists())

    def test_preparation_fingerprints_weights_and_private_checkpoint(self):
        prepared = self.prepare()
        self.assertFalse(prepared['training_started'])
        self.assertEqual(describe_run(self.store, prepared['run_id'])['status'], 'queued')
        recipe, checkpoint, folder = verify_run(self.store, prepared['run_id'])
        self.assertEqual(recipe['quantization'], 'nf4-4bit')
        self.assertEqual(recipe['gradient_accumulation'], 8)
        self.assertEqual(checkpoint['revision'], 1)
        self.assertTrue(folder.resolve().is_relative_to((self.store.home / 'runs').resolve()))
        self.assertFalse(list(self.root.glob('**/adapter_model.safetensors')))

    def test_no_symlink_or_changed_base_weights(self):
        prepared = self.prepare()
        (self.model / 'model.safetensors').write_bytes(b'tampered')
        with self.assertRaisesRegex(TrainingError, 'changed'):
            verify_run(self.store, prepared['run_id'])
        with self.assertRaises(TrainingError):
            execute_run(self.store, prepared['run_id'], confirmed=True, backend=Mock())
        self.assertEqual(self.store.get_checkpoint('train_' + prepared['run_id'])['status'], 'queued')

    def test_revocation_blocks_training(self):
        prepared = self.prepare()
        self.store.set_review('train_pairs', self.pair_id, 'rejected')
        with self.assertRaisesRegex(Exception, 'stale'):
            execute_run(self.store, prepared['run_id'], confirmed=True, backend=Mock())

    def test_bounded_recipe_and_unknown_run(self):
        for kw in [{'max_steps':0}, {'max_steps':501}, {'seq_length':1025}, {'seed':-1}]:
            with self.subTest(kw=kw), self.assertRaises(TrainingError):
                create_run(self.store, self.sha, self.model, confirmed=True, **kw)
        with self.assertRaises(TrainingError):
            verify_run(self.store, '../../etc/passwd')

    def test_no_implicit_backend_or_relaunch(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(TrainingError, 'confirm'):
            execute_run(self.store, prepared['run_id'])
        _, _, run_dir = verify_run(self.store, prepared['run_id'])
        def fake_backend(recipe, folder, data_path, *, resume):
            self.assertFalse(resume)
            self.assertTrue(data_path.is_file())
            out = folder / 'adapter'
            out.mkdir()
            (out / 'adapter_model.safetensors').write_bytes(b'approved synthetic adapter')
            (out / 'adapter_config.json').write_text('{}')
            return {'adapter_dir':str(out),'examples_used':1}
        result = execute_run(self.store, prepared['run_id'], confirmed=True, backend=fake_backend)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['promotion'], 'not-authorized')
        self.assertEqual(describe_run(self.store, prepared['run_id'])['status'], 'complete')
        with self.assertRaisesRegex(TrainingError, 'Completed'):
            execute_run(self.store, prepared['run_id'], confirmed=True, backend=fake_backend)
        self.assertEqual(run_dir.joinpath('adapter/adapter_model.safetensors').read_bytes(), b'approved synthetic adapter')

    def test_failure_requires_explicit_resume(self):
        prepared = self.prepare()
        def failed(*a, **kw):
            raise TrainingError('synthetic OOM')
        with self.assertRaisesRegex(TrainingError, 'synthetic OOM'):
            execute_run(self.store, prepared['run_id'], confirmed=True, backend=failed)
        self.assertEqual(self.store.get_checkpoint('train_' + prepared['run_id'])['status'], 'failed')
        with self.assertRaisesRegex(TrainingError, 'resume'):
            execute_run(self.store, prepared['run_id'], confirmed=True, backend=failed)
        seen=[]
        def resumed(recipe, folder, path, *, resume):
            seen.append(resume)
            (folder / 'adapter').mkdir()
            (folder / 'adapter' / 'adapter_model.safetensors').write_bytes(b'new')
            return {'adapter_dir':str(folder / 'adapter'),'examples_used':1}
        self.assertEqual(execute_run(self.store, prepared['run_id'], confirmed=True,
                                     resume=True, backend=resumed)['status'], 'complete')
        self.assertEqual(seen, [True])

    def test_tampered_recipe_or_missing_adapter_rejected(self):
        prepared = self.prepare()
        recipe, cp, folder = verify_run(self.store, prepared['run_id'])
        (folder / 'recipe.json').write_text('{}')
        with self.assertRaisesRegex(TrainingError, 'provenance'):
            verify_run(self.store, prepared['run_id'])

    def test_same_user_dataset_revoke_during_training_never_marks_success(self):
        prepared = self.prepare()
        def consent_changed(recipe, folder, data_path, *, resume):
            (folder / 'adapter').mkdir()
            (folder / 'adapter' / 'adapter_model.safetensors').write_bytes(b'synthetic')
            self.store.set_review('train_pairs', self.pair_id, 'rejected')
            return {'adapter_dir':str(folder / 'adapter'),'examples_used':1}
        with self.assertRaisesRegex(Exception, 'stale'):
            execute_run(self.store, prepared['run_id'], confirmed=True, backend=consent_changed)
        self.assertEqual(self.store.get_checkpoint('train_' + prepared['run_id'])['status'], 'failed')

    def test_owner_pause_during_training_cannot_be_overwritten(self):
        prepared = self.prepare()
        key = 'train_' + prepared['run_id']
        def paused(recipe, folder, data_path, *, resume):
            out = folder / 'adapter'
            out.mkdir()
            (out / 'adapter_model.safetensors').write_bytes(b'synthetic')
            current = self.store.get_checkpoint(key)
            self.store.checkpoint(key, current['task'], current['state'],
                                  status='paused',
                                  expected_revision=current['revision'])
            return {'adapter_dir': str(out), 'examples_used': 1}
        with self.assertRaisesRegex(TrainingError, 'authorization checkpoint changed'):
            execute_run(self.store, prepared['run_id'], confirmed=True,
                        backend=paused)
        current = self.store.get_checkpoint(key)
        self.assertEqual((current['status'], current['revision']), ('paused', 3))
        self.assertNotIn('adapter_sha256', current['state'])

    def test_newer_checkpoint_revision_remains_authoritative_on_failure(self):
        prepared = self.prepare()
        key = 'train_' + prepared['run_id']
        def interruption(recipe, folder, path, *, resume):
            current = self.store.get_checkpoint(key)
            self.store.checkpoint(key, current['task'],
                {**current['state'], 'owner_note': 'reviewed pause'},
                status='paused', expected_revision=current['revision'])
            raise TrainingError('Synthetic training interruption')
        with self.assertRaisesRegex(TrainingError, 'Synthetic training interruption'):
            execute_run(self.store, prepared['run_id'], confirmed=True,
                        backend=interruption)
        checkpoint = self.store.get_checkpoint(key)
        self.assertEqual(checkpoint['status'], 'paused')
        self.assertEqual(checkpoint['state']['owner_note'], 'reviewed pause')

    def test_invalid_example_count_is_never_marked_complete(self):
        for count in (0, -1, True, 50_001):
            with self.subTest(count=count):
                run = self.prepare()
                def backend(recipe, folder, path, *, resume):
                    out = folder / 'adapter'
                    out.mkdir()
                    (out / 'adapter_model.safetensors').write_bytes(b'synthetic')
                    return {'adapter_dir': str(out), 'examples_used': count}
                with self.assertRaisesRegex(TrainingError, 'invalid number'):
                    execute_run(self.store, run['run_id'], confirmed=True,
                                backend=backend)
                self.assertEqual(
                    self.store.get_checkpoint('train_' + run['run_id'])['status'],
                    'failed')

    def test_completion_masking_and_size_gate(self):
        enc = encode_example(MockTokenizer(), 'prompt', 'answer', 16)
        self.assertEqual(enc['labels'], [-100,-100,31,32])
        self.assertEqual(enc['attention_mask'], [1]*4)
        self.assertIsNone(encode_example(MockTokenizer(), 'prompt', 'answer', 3))

    def test_disallow_symlinked_model_inputs(self):
        # Windows may restrict symlinks on CI; skip in that case.
        source = self.model / 'model.safetensors'
        source.rename(self.model / 'real.safetensors')
        try:
            source.symlink_to(self.model / 'real.safetensors')
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(TrainingError, 'Symlink'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
