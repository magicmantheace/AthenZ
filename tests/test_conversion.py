"""Synthetic conversion lifecycle; no heavy libraries, GPU or converter execution."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from athenz.adapters import register_adapter
from athenz.conversion import (ConversionError, conversion_status, _backend,
                               execute_conversion, prepare_conversion,
                               pause_conversion)
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.training import build_dataset
from athenz.train_cli import parser
from athenz.ollama_import import prepare_import, verify_import, ImportErrorLocal


class ConversionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.store=ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        base=self.root / 'qwen-base'
        base.mkdir()
        (base/'config.json').write_text('{"model_type":"qwen2"}')
        (base/'tokenizer.json').write_text('{}')
        (base/'model.safetensors').write_bytes(b'synthetic')
        self.store.add_message('s','agent','user','Example question')
        mid=self.store.add_message('s','agent','assistant','Example reply')
        self.store.add_feedback(mid,'up')
        row=self.store.db.execute('SELECT id FROM train_pairs').fetchone()[0]
        self.store.set_review('train_pairs',row,'approved')
        self.pair=row
        sha=build_dataset(self.store,confirmed=True)['sha256']
        self.run_id=create_run(self.store,sha,base,confirmed=True)['run_id']
        def training_backend(recipe,folder,data,*,resume):
            dest=folder/'adapter'
            dest.mkdir()
            (dest/'adapter_model.safetensors').write_bytes(b'fake weights')
            (dest/'adapter_config.json').write_text(json.dumps({
                'peft_type':'LORA','base_model_name_or_path':str(base.resolve())}))
            return {'adapter_dir':str(dest),'examples_used':1}
        execute_run(self.store,self.run_id,backend=training_backend,confirmed=True)
        register_adapter(self.store,self.run_id,'athenz-test:one',confirmed=True)
        self.converter=self.root/'convert_hf_to_gguf.py'
        self.converter.write_text('''# Synthetic trusted conversion fixture. Does not execute.\n'''+"def convert():\n    return 'not invoked'\n")
        self.sha=hashlib.sha256(self.converter.read_bytes()).hexdigest()

    def prepare(self):
        return prepare_conversion(self.store,self.run_id,self.converter,
                                  converter_sha256=self.sha,confirmed=True,trust_converter=True)

    def fake_backend(self,recipe,adapter,converter,destination):
        self.assertTrue((adapter/'adapter_model.safetensors').exists())
        self.assertEqual(converter,self.converter.resolve())
        path=destination/'merged-f16.gguf'
        path.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'Z'*40)
        return path

    def test_prepare_requires_owner_acknowledgement_and_does_not_run(self):
        with self.assertRaisesRegex(ConversionError,'trust-converter'):
            prepare_conversion(self.store,self.run_id,self.converter,converter_sha256=self.sha,
                               confirmed=True)
        with mock.patch('athenz.conversion.subprocess.run') as run:
            state=self.prepare()
            run.assert_not_called()
        self.assertEqual(state['status'],'queued')
        self.assertEqual(self.prepare()['status'],'queued')
        self.assertFalse((self.store.home/'conversions').exists() and any(
            (self.store.home/'conversions').iterdir()))

    def test_success_is_reproducible_and_immutable(self):
        self.prepare()
        with self.assertRaisesRegex(ConversionError,'confirm'):
            execute_conversion(self.store,self.run_id,backend=self.fake_backend)
        result=execute_conversion(self.store,self.run_id,confirmed=True,backend=self.fake_backend)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['attempts'],1)
        self.assertTrue(Path(result['artifact']['path']).exists())
        self.assertEqual(result['artifact']['status'],'local-merge-claimed-not-gpu-verified')
        self.assertEqual(result['deployment'],'not-imported')
        with self.assertRaises(ConversionError):
            execute_conversion(self.store,self.run_id,confirmed=True,backend=self.fake_backend)
        Path(result['artifact']['path']).write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'Y'*40)
        with self.assertRaisesRegex(ConversionError,'changed'):
            conversion_status(self.store,self.run_id)

    def test_input_consent_revocation_blocks_prepared_run(self):
        self.prepare()
        self.store.set_review('train_pairs',self.pair,'rejected')
        with self.assertRaises(Exception):
            execute_conversion(self.store,self.run_id,confirmed=True,backend=self.fake_backend)
        self.assertEqual(self.store.get_checkpoint('convert_'+self.run_id)['status'],'queued')

    def test_script_tampering_blocks_run(self):
        self.prepare()
        self.converter.write_text('# different code, no longer trusted, synthetic mutation\n'+'pass\n')
        with self.assertRaisesRegex(ConversionError,'digest'):
            execute_conversion(self.store,self.run_id,confirmed=True,backend=self.fake_backend)

    def test_pause_cli_revokes_conversion_and_requires_fresh_resume(self):
        self.prepare()
        with self.assertRaisesRegex(ConversionError, 'confirm'):
            pause_conversion(self.store, self.run_id)
        paused = pause_conversion(self.store, self.run_id, confirmed=True)
        self.assertEqual(paused['status'], 'paused')
        self.assertFalse(paused['backend_interrupted'])
        self.assertFalse(paused['output_adopted'])
        self.assertTrue(paused['resume_requires_confirmation'])
        with self.assertRaisesRegex(ConversionError, 'resumable'):
            execute_conversion(self.store, self.run_id, confirmed=True,
                               backend=self.fake_backend)
        completed = execute_conversion(self.store, self.run_id, confirmed=True,
                                       resume=True, backend=self.fake_backend)
        self.assertEqual(completed['status'], 'complete')
        self.assertEqual(completed['attempts'], 1)
        with self.assertRaisesRegex(ConversionError, 'cannot be paused'):
            pause_conversion(self.store, self.run_id, confirmed=True)

    def test_pause_inside_cpu_backend_discards_output_then_new_attempt(self):
        self.prepare()
        def owner_pauses(recipe, adapter, converter, destination):
            result = self.fake_backend(recipe, adapter, converter, destination)
            status = pause_conversion(self.store, self.run_id, confirmed=True)
            self.assertEqual(status['status'], 'paused')
            return result
        with self.assertRaisesRegex(ConversionError, 'authorization changed'):
            execute_conversion(self.store, self.run_id, confirmed=True,
                               backend=owner_pauses)
        checkpoint = self.store.get_checkpoint('convert_' + self.run_id)
        self.assertEqual(checkpoint['status'], 'paused')
        self.assertIsNone(checkpoint['state']['artifact'])
        finished = execute_conversion(self.store, self.run_id, confirmed=True,
                                      resume=True, backend=self.fake_backend)
        self.assertEqual(finished['attempts'], 2)
        self.assertIn('attempt-2', finished['artifact']['path'])
        self.assertTrue((self.store.home/'conversions'/
                         ('merge-'+self.run_id)/'attempt-1'/'merged-f16.gguf').exists())

    def test_owner_pause_during_conversion_discards_late_success(self):
        self.prepare()
        key = 'convert_' + self.run_id
        def pause_while_merging(recipe, adapter, converter, destination):
            produced = self.fake_backend(recipe, adapter, converter, destination)
            current = self.store.get_checkpoint(key)
            self.store.checkpoint(key, current['task'], current['state'],
                                  status='paused', expected_revision=current['revision'])
            return produced
        with self.assertRaisesRegex(ConversionError, 'authorization changed'):
            execute_conversion(self.store, self.run_id, confirmed=True,
                               backend=pause_while_merging)
        checkpoint = self.store.get_checkpoint(key)
        self.assertEqual(checkpoint['status'], 'paused')
        self.assertEqual(checkpoint['state']['attempts'], 1)
        self.assertIsNone(checkpoint['state']['artifact'])
        self.assertEqual(checkpoint['revision'], 3)

    def test_late_failing_conversion_cannot_overwrite_newer_revision(self):
        self.prepare()
        key = 'convert_' + self.run_id
        def newer_running_generation(*args):
            current = self.store.get_checkpoint(key)
            changed = dict(current['state'])
            changed['new_owner_update'] = 'synthetic-only'
            self.store.checkpoint(key, current['task'], changed,
                                  status='running', expected_revision=current['revision'])
            raise RuntimeError('synthetic old conversion failed')
        with self.assertRaisesRegex(RuntimeError, 'old conversion'):
            execute_conversion(self.store, self.run_id, confirmed=True,
                               backend=newer_running_generation)
        current = self.store.get_checkpoint(key)
        self.assertEqual(current['status'], 'running')
        self.assertEqual(current['state']['new_owner_update'], 'synthetic-only')
        self.assertEqual(current['revision'], 3)

    def test_pause_wins_over_late_converter_exception(self):
        self.prepare()
        key = 'convert_' + self.run_id
        def pause_then_fail(*args):
            current = self.store.get_checkpoint(key)
            self.store.checkpoint(key, current['task'], current['state'],
                                  status='paused', expected_revision=current['revision'])
            raise RuntimeError('late converter error')
        with self.assertRaisesRegex(RuntimeError, 'late converter'):
            execute_conversion(self.store, self.run_id, confirmed=True,
                               backend=pause_then_fail)
        self.assertEqual(self.store.get_checkpoint(key)['status'], 'paused')

    def test_failed_attempt_requires_explicit_resume_without_overwrite(self):
        self.prepare()
        def fail(*a):
            raise RuntimeError('synthetic backend failure')
        with self.assertRaises(RuntimeError):
            execute_conversion(self.store,self.run_id,confirmed=True,backend=fail)
        self.assertEqual(conversion_status(self.store,self.run_id)['status'],'failed')
        with self.assertRaisesRegex(ConversionError,'resumable'):
            execute_conversion(self.store,self.run_id,confirmed=True,backend=self.fake_backend)
        result=execute_conversion(self.store,self.run_id,confirmed=True,resume=True,
                                  backend=self.fake_backend)
        self.assertEqual(result['attempts'],2)
        root=Path(result['artifact']['path']).parent.parent
        self.assertTrue((root/'attempt-1').exists())
        self.assertTrue((root/'attempt-2').exists())

    def test_crash_state_can_resume_without_replacing_old_attempt(self):
        self.prepare()
        key='convert_'+self.run_id
        cp=self.store.get_checkpoint(key)
        state=dict(cp['state'])
        state['attempts']=1
        self.store.checkpoint(key,cp['task'],state,status='running',expected_revision=cp['revision'])
        # Previous attempts have persisted files after an unexpected process exit.
        folder=self.store.home/'conversions'/('merge-'+self.run_id)/'attempt-1'
        folder.mkdir(parents=True)
        (folder/'partial.bin').write_bytes(b'old')
        result=execute_conversion(self.store,self.run_id,confirmed=True,resume=True,
                                  backend=self.fake_backend)
        self.assertEqual(result['attempts'],2)
        self.assertEqual((folder/'partial.bin').read_bytes(),b'old')

    def test_invalid_converter_and_path_fails_closed(self):
        with self.assertRaisesRegex(ConversionError,'SHA-256'):
            prepare_conversion(self.store,self.run_id,self.converter,converter_sha256='0',
                               confirmed=True,trust_converter=True)
        with self.assertRaisesRegex(ConversionError,'digest'):
            prepare_conversion(self.store,self.run_id,self.converter,converter_sha256='0'*64,
                               confirmed=True,trust_converter=True)
        with mock.patch('athenz.conversion._cpu_merge',side_effect=AssertionError('should not invoke')):
            self.prepare()

    def test_completed_conversion_links_exact_gguf_to_import(self):
        self.prepare()
        observed=execute_conversion(self.store,self.run_id,confirmed=True,
                                    backend=self.fake_backend)
        gguf=Path(observed['artifact']['path'])
        staged=prepare_import(self.store,self.run_id,gguf,
                             candidate_tag='athenz-test:one',confirmed=True,
                             acknowledge_merge=True)
        self.assertIn('local-conversion-observed',staged['lineage'])
        self.assertEqual(verify_import(self.store,self.run_id)['status'],'paused')
        # Revoking consent invalidates the completed lineage and the import.
        self.store.set_review('train_pairs',self.pair,'rejected')
        with self.assertRaises(Exception):
            verify_import(self.store,self.run_id)

    def test_incomplete_conversion_cannot_be_misrepresented_as_verified(self):
        self.prepare()
        gguf=self.root/'other.gguf'
        gguf.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'Q'*40)
        with self.assertRaisesRegex(ImportErrorLocal,'completed local conversion'):
            prepare_import(self.store,self.run_id,gguf,
                           candidate_tag='athenz-test:one',confirmed=True,
                           acknowledge_merge=True)

    def test_trusted_converter_uses_fixed_offline_argv_and_no_proxy(self):
        self.prepare()
        recipe=self.store.get_checkpoint('convert_'+self.run_id)['state']
        from athenz.finetune import verify_run, _run_path
        real_recipe, _, _ = verify_run(self.store,self.run_id)
        with tempfile.TemporaryDirectory() as work:
            destination=Path(work)
            def fake_merge(recipe,adapter,merged):
                self.assertTrue(merged.is_dir())
                (merged/'config.json').write_text('{"model_type":"qwen2"}')
            def fake_run(argv,**kwargs):
                self.assertEqual(argv[1],'-I')
                self.assertEqual(argv[2],str(self.converter.resolve()))
                self.assertEqual(argv[-4:-2],['--outfile',str(destination/'merged-f16.gguf')])
                self.assertEqual(argv[-2:],['--outtype','f16'])
                self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'],'1')
                self.assertEqual(kwargs['env']['TRANSFORMERS_OFFLINE'],'1')
                self.assertNotIn('HTTPS_PROXY',kwargs['env'])
                self.assertNotIn('OLLAMA_HOST',kwargs['env'])
                self.assertEqual(kwargs['cwd'],destination)
                (destination/'merged-f16.gguf').write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'G'*40)
                return subprocess.CompletedProcess(argv,0,'','')
            with mock.patch.dict(os.environ,{'HTTPS_PROXY':'http://example.invalid','OLLAMA_HOST':'external:11434'}), \
                 mock.patch('athenz.conversion._cpu_merge',side_effect=fake_merge), \
                 mock.patch('athenz.conversion.subprocess.run',side_effect=fake_run) as process:
                got=_backend(real_recipe,_run_path(self.store,self.run_id)/'adapter',
                             self.converter.resolve(),destination)
                self.assertEqual(got,destination/'merged-f16.gguf')
                process.assert_called_once()

    def test_cli_commands_explicit_and_no_unattended_training(self):
        opts=parser()._subparsers._group_actions[0].choices
        self.assertIn('prepare-conversion',opts)
        self.assertIn('run-conversion',opts)
        self.assertIn('verify-conversion',opts)

if __name__=='__main__':
    unittest.main()
