"""Synthetic QLoRA -> merged GGUF import boundary; no Ollama/GPU activity."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from athenz.adapters import register_adapter
from athenz.experience import ExperienceStore
from athenz.finetune import create_run, execute_run
from athenz.ollama_import import (ImportErrorLocal, prepare_import, verify_import,
                                  import_local, _not_installed)
from athenz.training import build_dataset


TAG = 'athenz-trial:one'
CANDIDATE_DIGEST = 'a' * 64


class ImportTests(unittest.TestCase):
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
        (base / 'model.safetensors').write_bytes(b'synthetic')
        self.store.add_message('t','agent','user','a synthetic prompt')
        mid=self.store.add_message('t','agent','assistant','a synthetic answer')
        self.store.add_feedback(mid,'up')
        self.pair=self.store.db.execute('SELECT id FROM train_pairs').fetchone()[0]
        self.store.set_review('train_pairs',self.pair,'approved')
        dataset=build_dataset(self.store, confirmed=True)['sha256']
        r=create_run(self.store,dataset,base,confirmed=True)
        self.run_id=r['run_id']
        def backend(recipe,folder,dataset_path,*,resume):
            adapter=folder/'adapter'
            adapter.mkdir()
            (adapter/'adapter_model.safetensors').write_bytes(b'synthetic-adapter')
            (adapter/'adapter_config.json').write_text(json.dumps({
                'peft_type':'LORA','base_model_name_or_path':str(base.resolve())}))
            return {'adapter_dir':str(adapter),'examples_used':1}
        execute_run(self.store,self.run_id,backend=backend,confirmed=True)
        register_adapter(self.store,self.run_id,TAG,confirmed=True)
        self.gguf=self.root/'merged.gguf'
        self.gguf.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'X'*48)

    def prepare(self):
        return prepare_import(self.store,self.run_id,self.gguf,candidate_tag=TAG,
                              confirmed=True,acknowledge_merge=True)

    def test_prepare_requires_ack_and_does_not_execute_or_route(self):
        with self.assertRaisesRegex(ImportErrorLocal, 'ack-merge'):
            prepare_import(self.store,self.run_id,self.gguf,candidate_tag=TAG,confirmed=True)
        with mock.patch('athenz.ollama_import.subprocess.run') as runner:
            data=self.prepare()
            runner.assert_not_called()
        self.assertEqual(data['deployment'],'not-imported')
        self.assertTrue(Path(data['modelfile']).resolve().is_relative_to(self.store.home.resolve()))
        self.assertIn('FROM ',Path(data['modelfile']).read_text())
        self.assertNotIn('ADAPTER ',Path(data['modelfile']).read_text())
        self.assertEqual(self.prepare()['revision'],1)
        self.assertEqual(verify_import(self.store,self.run_id)['status'],'paused')
        with self.assertRaisesRegex(ImportErrorLocal,'not been imported'):
            verify_import(self.store,self.run_id,verify_ollama=True)

    def test_changed_gguf_manifest_and_adapter_consent_rejected(self):
        data=self.prepare()
        self.gguf.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'Y'*48)
        with self.assertRaisesRegex(ImportErrorLocal,'changed'):
            verify_import(self.store,self.run_id)
        self.gguf.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'X'*48)
        Path(data['modelfile']).write_text('FROM /tmp/untrusted.gguf\n')
        with self.assertRaisesRegex(ImportErrorLocal,'Modelfile'):
            verify_import(self.store,self.run_id)
        Path(data['modelfile']).write_text('FROM '+json.dumps(str(self.gguf.resolve()))+'\n')
        self.store.set_review('train_pairs',self.pair,'rejected')
        with self.assertRaises(Exception):
            verify_import(self.store,self.run_id)

    def test_path_injection_bad_header_and_candidate_mismatch(self):
        with self.assertRaisesRegex(ImportErrorLocal,'tag must match'):
            prepare_import(self.store,self.run_id,self.gguf,candidate_tag='athenz-other:two',
                           confirmed=True,acknowledge_merge=True)
        self.gguf.write_bytes(b'ADAPTER'+b'X'*45)
        with self.assertRaisesRegex(ImportErrorLocal,'header'):
            self.prepare()
        self.gguf.unlink()
        try:
            self.gguf.symlink_to(self.root/'base'/'config.json')
        except (OSError, NotImplementedError):
            return  # Some Windows runners do not grant symlink privileges.
        with self.assertRaisesRegex(ImportErrorLocal,'symlink'):
            self.prepare()

    def test_execute_requires_confirm_and_no_replacement(self):
        self.prepare()
        with self.assertRaisesRegex(ImportErrorLocal,'confirm'):
            import_local(self.store,self.run_id)
        with mock.patch('athenz.ollama_import.shutil.which',return_value='ollama'), \
             mock.patch('athenz.ollama_import._not_installed',side_effect=ImportErrorLocal('Candidate tag already exists')), \
             mock.patch('athenz.ollama_import.subprocess.run') as run:
            with self.assertRaisesRegex(ImportErrorLocal,'already exists'):
                import_local(self.store,self.run_id,confirmed=True)
            run.assert_not_called()
        self.assertEqual(verify_import(self.store,self.run_id)['status'],'paused')

    def test_execute_local_only_pins_digest_and_never_activates(self):
        self.prepare()
        def fake_process(argv, **kwargs):
            self.assertEqual(argv[:2],['ollama','create'])
            self.assertEqual(argv[2],TAG)
            self.assertEqual(kwargs['env']['OLLAMA_HOST'],'127.0.0.1:11434')
            self.assertNotIn('HTTPS_PROXY',kwargs['env'])
            self.assertNotIn('OLLAMA_MODELS',kwargs['env'])
            return subprocess.CompletedProcess(argv,0,stdout='created',stderr='')
        with mock.patch.dict('os.environ', {'OLLAMA_HOST':'evil.example','HTTPS_PROXY':'evil'}), \
             mock.patch('athenz.ollama_import.shutil.which',return_value='/bin/ollama'), \
             mock.patch('athenz.ollama_import._not_installed'), \
             mock.patch('athenz.ollama_import.subprocess.run',side_effect=fake_process) as process, \
             mock.patch('athenz.ollama_import.model_digest',return_value=CANDIDATE_DIGEST):
            result=import_local(self.store,self.run_id,confirmed=True)
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['candidate_digest'],CANDIDATE_DIGEST)
            again=import_local(self.store,self.run_id,confirmed=True)
            self.assertEqual(again['revision'],result['revision'])
            self.assertEqual(process.call_count,1)
        self.assertIsNone(self.store.get_checkpoint('ollama_runtime'))

    def test_interrupted_import_requires_manual_recovery(self):
        self.prepare()
        with mock.patch('athenz.ollama_import.shutil.which',return_value='/bin/ollama'), \
             mock.patch('athenz.ollama_import._not_installed'), \
             mock.patch('athenz.ollama_import.subprocess.run',side_effect=subprocess.TimeoutExpired('ollama',60)):
            with self.assertRaisesRegex(ImportErrorLocal,'interrupted'):
                import_local(self.store,self.run_id,confirmed=True)
        self.assertEqual(verify_import(self.store,self.run_id)['status'],'running')
        with self.assertRaisesRegex(ImportErrorLocal,'underway'):
            import_local(self.store,self.run_id,confirmed=True)

    def test_inventory_checks_missing_without_conflating_malformed_existing(self):
        class Reply:
            def __init__(self,rows): self.rows=rows
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def read(self,*_): return json.dumps({'models':self.rows}).encode()
        opener=mock.Mock()
        opener.open.return_value=Reply([])
        with mock.patch('urllib.request.build_opener',return_value=opener):
            _not_installed(TAG,endpoint=None)
        opener.open.return_value=Reply([{'name':TAG}])
        with mock.patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaisesRegex(ImportErrorLocal,'already exists'):
                _not_installed(TAG,endpoint=None)
        opener.open.return_value=Reply(['malformed'])
        with mock.patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaisesRegex(ImportErrorLocal,'Malformed'):
                _not_installed(TAG,endpoint=None)

if __name__=='__main__':
    unittest.main()
