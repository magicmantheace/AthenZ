"""Synthetic WAV and fake backend tests: never record, upload or import speech models."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import wave

from athenz.voice import (VoiceError, inspect_wav, inspect_local_model,
                          transcribe_wav, main)


class VoiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wav = self.root / 'synthetic.wav'
        self.model = self.root / 'offline-model'
        self.model.mkdir()
        (self.model / 'config.json').write_text('{"model":"synthetic"}')
        (self.model / 'model.bin').write_bytes(b'fictional-private-weights')
        with wave.open(str(self.wav), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b'\x00\x00' * 16000)

    def fake_engine(self, *segments):
        class Engine:
            def transcribe(self, path, **kwargs):
                self.calls = (path, kwargs)
                return (iter(segments), {'language': 'en'})
        return Engine()

    def test_evaluation_refuses_reference_changed_during_native_inference(self):
        from athenz.voice import evaluate_wav
        ref = self.root / 'owner-reference.txt'
        ref.write_text('Owner said the original sentence')
        def replace_while_decoding(*args, **kwargs):
            ref.write_text('Owner corrected the reference after audio started')
            return {'transcript': 'original sentence',
                    'audio_fingerprint_stable': True,
                    'model_files_stable': True}
        with mock.patch('athenz.voice.transcribe_wav',
                        side_effect=replace_while_decoding):
            with self.assertRaisesRegex(VoiceError, 'reference changed') as caught:
                evaluate_wav(self.wav, self.model, ref, confirmed=True)
        self.assertNotIn('Owner corrected', str(caught.exception))
        self.assertNotIn(str(ref), str(caught.exception))

    def test_text_score_refuses_second_pass_changed_hypothesis(self):
        from athenz.voice import score_text_files
        ref = self.root / 'stable-reference.txt'
        hyp = self.root / 'hypothesis.txt'
        ref.write_text('synthetic private reference')
        hyp.write_text('synthetic private hypothesis')
        original = __import__('athenz.voice', fromlist=['_private_reference'])._private_reference
        calls = {'n': 0}
        def changed_on_verify(path, **kwargs):
            calls['n'] += 1
            if calls['n'] == 3:
                return 'PRIVATE modified reference'
            return original(path, **kwargs)
        with mock.patch('athenz.voice._private_reference',
                        side_effect=changed_on_verify):
            with self.assertRaisesRegex(VoiceError, 'input changed'):
                score_text_files(ref, hyp, confirmed=True)
        self.assertEqual(calls['n'], 3)

    def test_invalid_reference_refuses_before_native_transcription(self):
        from athenz.voice import evaluate_wav
        malformed = self.root / 'broken-reference.txt'
        malformed.write_bytes(bytes([0xff, 0xfe, 0x00]))
        with mock.patch('athenz.voice.transcribe_wav',
                        side_effect=AssertionError('native inference must not start')):
            with self.assertRaisesRegex(VoiceError, 'reference'):
                evaluate_wav(self.wav, self.model, malformed, confirmed=True)
        malformed.write_text('!', encoding='utf-8')
        with mock.patch('athenz.voice.transcribe_wav',
                        side_effect=AssertionError('native inference must not start')):
            with self.assertRaisesRegex(VoiceError, 'at least one'):
                evaluate_wav(self.wav, self.model, malformed, confirmed=True)

    def test_text_score_accepts_empty_hypothesis_as_full_deletion(self):
        from athenz.voice import score_text_files
        reference = self.root / 'ref.txt'
        hypothesis = self.root / 'empty.txt'
        reference.write_text('one two three', encoding='utf-8')
        hypothesis.write_bytes(b'')
        result = score_text_files(reference, hypothesis, confirmed=True)
        self.assertEqual(result['hypothesis_words'], 0)
        self.assertEqual(result['word_deletions'], 3)
        self.assertEqual(result['wer_percent'], 100.0)
        self.assertEqual(result['cer_percent'], 100.0)
        reference.write_bytes(b'')
        with self.assertRaisesRegex(VoiceError, 'Reference'):
            score_text_files(reference, hypothesis, confirmed=True)

    def test_score_text_only_is_explicit_and_never_accesses_model_audio_or_private_paths(self):
        from athenz.voice import score_text_files
        reference = self.root / 'private-reference.txt'
        hypothesis = self.root / 'private-hypothesis.txt'
        reference.write_text('Welcome to AthenZ.', encoding='utf-8')
        hypothesis.write_text('Welcome AthenZ.', encoding='utf-8')
        with mock.patch('athenz.voice._load_engine',
                        side_effect=AssertionError('model must not load')), \
             mock.patch('athenz.voice.inspect_wav',
                        side_effect=AssertionError('no audio metadata')):
            with self.assertRaisesRegex(VoiceError, 'confirm'):
                score_text_files(reference, hypothesis)
            result = score_text_files(reference, hypothesis, confirmed=True)
        self.assertEqual(result['word_deletions'], 1)
        self.assertEqual(result['wer_percent'], 33.33)
        self.assertFalse(result['native_backend_loaded'])
        self.assertFalse(result['model_called'])
        self.assertFalse(result['audio_read'])
        self.assertNotIn('Welcome', json.dumps(result))
        with mock.patch('builtins.print') as printed, \
             mock.patch('athenz.voice.transcribe_wav',
                        side_effect=AssertionError('native inference must not start')):
            main(['score-text', '--reference', str(reference),
                  '--hypothesis', str(hypothesis), '--confirm'])
        body = printed.call_args.args[0]
        self.assertEqual(json.loads(body)['wer_percent'], 33.33)
        self.assertNotIn(str(reference), body)
        self.assertNotIn(str(hypothesis), body)
        self.assertNotIn('Welcome', body)

    def test_numeric_wer_cer_and_insertions_without_text_output(self):
        from athenz.voice import score_transcript
        perfect = score_transcript("Hello, WORLD!", "hello world")
        self.assertEqual(perfect['word_errors'], 0)
        self.assertEqual(perfect['wer_percent'], 0.0)
        self.assertEqual(perfect['cer_percent'], 0.0)
        self.assertFalse(perfect['text_in_output'])
        miss = score_transcript("hello brave world", "hello world")
        self.assertEqual(miss['word_deletions'], 1)
        self.assertEqual(miss['word_errors'], 1)
        self.assertEqual(miss['wer_percent'], 33.33)
        extra = score_transcript('bonjour', 'bonjour bonjour')
        self.assertEqual(extra['word_insertions'], 1)
        self.assertEqual(extra['wer_percent'], 100.0)
        changed = score_transcript("I like apples", "I love apples")
        self.assertEqual(changed['word_substitutions'], 1)
        self.assertEqual(changed['wer_percent'], 33.33)
        self.assertNotIn('apples', json.dumps(changed))

    def test_score_rejects_empty_reference_and_excessively_long_text(self):
        from athenz.voice import score_transcript, MAX_EVAL_WORDS
        with self.assertRaisesRegex(VoiceError, 'at least one'):
            score_transcript('!!!', 'something')
        with self.assertRaisesRegex(VoiceError, 'bounded'):
            score_transcript('hello', ('word ' * (MAX_EVAL_WORDS + 1)))
        missing = score_transcript('hello world', '')
        self.assertEqual(missing['word_deletions'], 2)
        self.assertEqual(missing['wer_percent'], 100.0)

    def test_evaluate_wav_emits_aggregate_only_and_never_stores_transcript(self):
        from types import SimpleNamespace
        from athenz.voice import evaluate_wav
        reference = self.root / 'private-reference.txt'
        reference.write_text('private origin hello world', encoding='utf-8')
        engine = self.fake_engine(SimpleNamespace(text='hello world'))
        with mock.patch('athenz.voice._load_engine', return_value=engine):
            result = evaluate_wav(self.wav, self.model, reference, confirmed=True)
        self.assertEqual(result['wer_percent'], 50.0)
        self.assertTrue(result['audio_fingerprint_stable'])
        self.assertFalse(result['transcript_returned'])
        self.assertFalse(result['reference_persisted'])
        self.assertNotIn('private origin', json.dumps(result))
        self.assertNotIn(str(reference), json.dumps(result))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['offline-model', 'private-reference.txt', 'synthetic.wav'])

    def test_evaluate_cli_never_prints_private_words(self):
        from types import SimpleNamespace
        reference = self.root / 'reference.txt'
        reference.write_text('PRIVATE_REFERENCE_WORDS', encoding='utf-8')
        engine = self.fake_engine(SimpleNamespace(text='private reference words'))
        with mock.patch('athenz.voice._load_engine', return_value=engine), \
             mock.patch('builtins.print') as printed:
            main(['evaluate', str(self.wav), '--model', str(self.model),
                  '--reference', str(reference), '--confirm'])
        data = json.loads(printed.call_args.args[0])
        self.assertEqual(data['wer_percent'], 0.0)
        self.assertNotIn('PRIVATE_', printed.call_args.args[0])
        self.assertNotIn('reference.txt', printed.call_args.args[0])

    def test_reference_consent_before_open_and_no_symlink_or_bad_utf8(self):
        from athenz.voice import evaluate_wav
        private = self.root / 'PRIVATE-reference.txt'
        private.write_text('private speech')
        with mock.patch('athenz.voice._private_reference',
                        side_effect=AssertionError('reference should stay unread')):
            with self.assertRaisesRegex(VoiceError, 'confirm'):
                evaluate_wav(self.wav, self.model, private)
        link = self.root / 'reference-link.txt'
        try:
            link.symlink_to(private)
        except (OSError, NotImplementedError):
            self.skipTest('No symlinks')
        with mock.patch('athenz.voice.transcribe_wav',
                        return_value={'transcript': 'hi',
                                      'audio_fingerprint_stable': True,
                                      'model_files_stable': True}):
            with self.assertRaises(VoiceError):
                evaluate_wav(self.wav, self.model, link, confirmed=True)
            private.write_bytes(bytes([0xff, 0xfe]))
            with self.assertRaises(VoiceError) as exc:
                evaluate_wav(self.wav, self.model, private, confirmed=True)
            self.assertNotIn(str(private), str(exc.exception))

    def test_model_inspection_is_metadata_only_and_never_loads_backend(self):
        with mock.patch('athenz.voice._load_engine',
                        side_effect=AssertionError('No native model import allowed')):
            report = inspect_local_model(self.model)
        self.assertTrue(report['required_files_present'])
        self.assertEqual(report['selected_files'], 2)
        self.assertEqual(report['selected_bytes'], sum(
            (self.model / name).stat().st_size for name in ('config.json', 'model.bin')))
        self.assertFalse(report['native_backend_loaded'])
        self.assertFalse(report['inference_observed'])
        self.assertFalse(report['model_downloaded'])
        self.assertNotIn(str(self.model), json.dumps(report))

    def test_model_inspection_cli_has_no_audio_or_runtime_side_effects(self):
        with mock.patch('athenz.voice._load_engine',
                        side_effect=AssertionError('Native model must not load')), \
             mock.patch('athenz.voice.inspect_wav',
                        side_effect=AssertionError('Audio must not be read')), \
             mock.patch('builtins.print') as output:
            main(['inspect-model', '--model', str(self.model)])
        report = json.loads(output.call_args.args[0])
        self.assertTrue(report['required_files_present'])
        self.assertFalse(report['cuda_validated'])
        self.assertFalse(report['accuracy_validated'])
        self.assertNotIn(str(self.model), output.call_args.args[0])

    def test_local_model_inspection_rejects_linked_optional_sidecar(self):
        tokenizer = self.model / 'tokenizer.json'
        try:
            tokenizer.symlink_to(self.model / 'config.json')
        except (OSError, NotImplementedError):
            self.skipTest('Synthetic runner cannot create symlinks')
        with self.assertRaisesRegex(VoiceError, 'model changed'):
            inspect_local_model(self.model)

    def test_metadata_inspection_is_readonly_and_does_not_access_model(self):
        from types import SimpleNamespace
        with mock.patch('athenz.voice._load_engine',
                        side_effect=AssertionError('No model should be loaded')):
            report = inspect_wav(self.wav)
        self.assertEqual(report['format'], 'pcm16-wav')
        self.assertEqual(report['sample_rate_hz'], 16000)
        self.assertEqual(report['duration_seconds'], 1)
        self.assertFalse(report['microphone_accessed'])
        self.assertFalse(report['transcription_started'])
        self.assertNotIn(str(self.wav), json.dumps(report))
        self.assertFalse((self.root / 'identity.sqlite3').exists())

    def test_wav_inspection_uses_no_follow_handle_after_initial_selection(self):
        from athenz.voice import _local_regular
        original = _local_regular
        def change_name_before_open(path, *, max_bytes):
            selected = original(path, max_bytes=max_bytes)
            self.wav.unlink()
            try:
                self.wav.symlink_to(self.model / 'model.bin')
            except (OSError, NotImplementedError):
                self.skipTest('No symlink privilege for synthetic replacement race')
            return selected
        with mock.patch('athenz.voice._local_regular',
                        side_effect=change_name_before_open):
            with self.assertRaises(VoiceError):
                inspect_wav(self.wav)

    def test_wav_inspection_rejects_changed_open_file_identity(self):
        from athenz.voice import _local_regular
        original = _local_regular
        def modify_selected_file(path, *, max_bytes):
            chosen = original(path, max_bytes=max_bytes)
            self.wav.write_bytes(b'RIFFPRIVATE-CORRUPT-WAV')
            return chosen
        with mock.patch('athenz.voice._local_regular',
                        side_effect=modify_selected_file):
            with self.assertRaises(VoiceError):
                inspect_wav(self.wav)

    def test_explicit_consent_precedes_any_private_audio_or_model_access(self):
        with mock.patch('athenz.voice.inspect_wav',
                        side_effect=AssertionError('Private audio accessed')):
            with self.assertRaisesRegex(VoiceError, 'confirm'):
                transcribe_wav(self.wav, self.model)
        with self.assertRaisesRegex(VoiceError, 'cpu or cuda'):
            transcribe_wav(self.wav, self.model, confirmed=True, device='gpu-auto')

    def test_fake_local_engine_yields_owner_visible_nonpersisted_transcript(self):
        from types import SimpleNamespace
        engine = self.fake_engine(SimpleNamespace(text=' Hello '),
                                  SimpleNamespace(text=' local world '))
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        with mock.patch('athenz.voice._load_engine', return_value=engine) as load:
            report = transcribe_wav(self.wav, self.model, confirmed=True)
        load.assert_called_once_with(self.model.resolve(), device='cpu')
        self.assertEqual(engine.calls[0], str(self.wav.resolve()))
        self.assertEqual(engine.calls[1]['language'], 'en')
        self.assertFalse(engine.calls[1]['word_timestamps'])
        self.assertEqual(report['transcript'], 'Hello local world')
        self.assertTrue(report['audio_fingerprint_stable'])
        self.assertTrue(report['model_files_stable'])
        self.assertFalse(report['stored_in_profile'])
        self.assertFalse(report['audio_uploaded'])
        self.assertFalse(report['submitted_to_chat'])
        self.assertFalse(report['training_authorized'])
        self.assertTrue(report['private_text_in_output'])
        self.assertEqual(sorted(str(p.relative_to(self.root))
                                for p in self.root.rglob('*')), before)

    def test_trusted_factory_cannot_request_remote_model_download(self):
        import sys
        from types import SimpleNamespace
        from athenz.voice import _load_engine
        seen = []
        class FakeModel:
            def __init__(self, path, **kwargs):
                seen.append((path, kwargs))
        with mock.patch.dict(sys.modules, {'faster_whisper':
                                           SimpleNamespace(WhisperModel=FakeModel)}):
            _load_engine(self.model.resolve(), device='cpu')
            _load_engine(self.model.resolve(), device='cuda')
        self.assertEqual(len(seen), 2)
        for name, opts in seen:
            self.assertEqual(name, str(self.model.resolve()))
            self.assertIs(opts['local_files_only'], True)
        self.assertEqual(seen[0][1]['compute_type'], 'int8')
        self.assertEqual(seen[1][1]['compute_type'], 'float16')

    def test_local_engine_import_failure_cannot_trigger_network(self):
        import sys
        from athenz.voice import _load_engine
        with mock.patch.dict(sys.modules, {'faster_whisper': None}):
            with self.assertRaisesRegex(VoiceError, 'Install trusted'):
                _load_engine(self.model.resolve(), device='cpu')

    def test_language_scope_can_choose_french_without_any_upload(self):
        from types import SimpleNamespace
        engine = self.fake_engine(SimpleNamespace(text='Bonjour le monde'))
        with mock.patch('athenz.voice._load_engine', return_value=engine):
            result = transcribe_wav(self.wav, self.model, confirmed=True,
                                    language='fr')
        self.assertEqual(result['language_requested'], 'fr')
        self.assertEqual(engine.calls[1]['language'], 'fr')
        self.assertFalse(result['audio_uploaded'])
        with self.assertRaisesRegex(VoiceError, 'language'):
            transcribe_wav(self.wav, self.model, confirmed=True,
                           language='auto-network')

    def test_model_file_change_during_transcription_never_releases_transcript(self):
        from types import SimpleNamespace
        voice_model = self.model / 'model.bin'
        class EditingEngine:
            def transcribe(inner, wav, **kwargs):
                voice_model.write_bytes(b'OTHER-LOCAL-MODEL-WEIGHTS')
                os.utime(voice_model, None)
                return iter([SimpleNamespace(text='PRIVATE-TRANSCRIPT-BLOCKED')]), None
        with mock.patch('athenz.voice._load_engine', return_value=EditingEngine()):
            with self.assertRaisesRegex(VoiceError, 'model changed') as caught:
                transcribe_wav(self.wav, self.model, confirmed=True)
        self.assertNotIn('PRIVATE-', str(caught.exception))

    def test_optional_tokenizer_change_or_symlink_is_refused(self):
        from types import SimpleNamespace
        tokenizer = self.model / 'tokenizer.json'
        tokenizer.write_text('{"synthetic":true}')
        class EditingEngine:
            def transcribe(inner, wav, **kwargs):
                tokenizer.write_text('{"synthetic":false}')
                return iter([SimpleNamespace(text='PRIVATE-SPEECH')]), None
        with mock.patch('athenz.voice._load_engine', return_value=EditingEngine()):
            with self.assertRaisesRegex(VoiceError, 'model changed'):
                transcribe_wav(self.wav, self.model, confirmed=True)
        tokenizer.unlink()
        try:
            tokenizer.symlink_to(self.model / 'config.json')
        except (OSError, NotImplementedError):
            self.skipTest('No symlink privilege available')
        with mock.patch('athenz.voice._load_engine',
                        side_effect=AssertionError('Must refuse before model load')):
            with self.assertRaisesRegex(VoiceError, 'model changed'):
                transcribe_wav(self.wav, self.model, confirmed=True)

    def test_changed_audio_during_transcription_refuses_private_result(self):
        from types import SimpleNamespace
        class MutatingEngine:
            def transcribe(inner, audio, **kwargs):
                # A concurrent editor changes the same PCM bytes after
                # inference starts. No transcript may be emitted.
                with wave.open(str(self.wav), 'wb') as writer:
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(16000)
                    writer.writeframes(b'\\x01\\x00' * 16000)
                return (iter([SimpleNamespace(text='PRIVATE-OLD-AUDIO')]), None)
        with mock.patch('athenz.voice._load_engine', return_value=MutatingEngine()):
            with self.assertRaisesRegex(VoiceError, 'audio changed') as error:
                transcribe_wav(self.wav, self.model, confirmed=True)
        self.assertNotIn('PRIVATE-OLD-AUDIO', str(error.exception))

    def test_no_speech_is_not_automatically_stored(self):
        from types import SimpleNamespace
        with mock.patch('athenz.voice._load_engine',
                        return_value=self.fake_engine(SimpleNamespace(text='  '))):
            r = transcribe_wav(self.wav, self.model, confirmed=True, device='cuda')
        self.assertEqual(r['status'], 'no-speech')
        self.assertEqual(r['transcript'], '')
        self.assertFalse(r['private_text_in_output'])
        self.assertEqual(r['device_requested'], 'cuda')

    def test_model_errors_cannot_expose_owner_audio_or_paths(self):
        engine = self.fake_engine()
        def fail(*args, **kwargs):
            raise RuntimeError('PRIVATE-PROMPT-FROM-LOCAL-DRIVER')
        engine.transcribe = fail
        with mock.patch('athenz.voice._load_engine', return_value=engine):
            with self.assertRaises(VoiceError) as caught:
                transcribe_wav(self.wav, self.model, confirmed=True)
        self.assertNotIn('PRIVATE-', str(caught.exception))
        self.assertIn('offline speech transcription failed', str(caught.exception))
        with mock.patch('athenz.voice._load_engine',
                        side_effect=VoiceError('PRIVATE-LOW-LEVEL-OWNER-PATH')):
            # An already categorized VoiceError raised by a mocked loader is
            # intentionally not converted by the backend segment fence.
            with self.assertRaises(VoiceError):
                transcribe_wav(self.wav, self.model, confirmed=True)

    def test_segment_count_and_transcript_size_bound(self):
        from types import SimpleNamespace
        long = SimpleNamespace(text='S' * 16001)
        with mock.patch('athenz.voice._load_engine',
                        return_value=self.fake_engine(long)):
            with self.assertRaisesRegex(VoiceError, 'privacy bound'):
                transcribe_wav(self.wav, self.model, confirmed=True)
        many = [SimpleNamespace(text='x') for _ in range(501)]
        with mock.patch('athenz.voice._load_engine',
                        return_value=self.fake_engine(*many)):
            with self.assertRaisesRegex(VoiceError, 'segment count'):
                transcribe_wav(self.wav, self.model, confirmed=True)

    def test_non_wav_and_malformed_pcm_are_refused_without_model_call(self):
        fake = self.root / 'synthetic.mp3'
        fake.write_bytes(b'not a WAV')
        for file in (fake, self.root / 'missing.wav'):
            with self.assertRaises(VoiceError):
                inspect_wav(file)
        not_pcm = self.root / 'bad.wav'
        not_pcm.write_bytes(b'garbage')
        with self.assertRaisesRegex(VoiceError, 'Invalid'):
            inspect_wav(not_pcm)
        stereo_bad = self.root / 'bad-format.wav'
        with wave.open(str(stereo_bad), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(1)
            stream.setframerate(16000)
            stream.writeframes(b'\x00' * 16000)
        with self.assertRaisesRegex(VoiceError, '16-bit PCM'):
            inspect_wav(stereo_bad)

    def test_audio_symlink_and_hardlink_cannot_be_processed(self):
        link = self.root / 'linked.wav'
        try:
            link.symlink_to(self.wav)
        except (OSError, NotImplementedError):
            self.skipTest('No symbolic link privilege')
        with self.assertRaises(VoiceError):
            inspect_wav(link)
        hard = self.root / 'hardlinked.wav'
        try:
            os.link(self.wav, hard)
        except (OSError, NotImplementedError):
            self.skipTest('No hardlink support')
        with self.assertRaisesRegex(VoiceError, 'linked'):
            inspect_wav(self.wav)

    def test_model_must_be_existing_local_regular_files(self):
        from types import SimpleNamespace
        with mock.patch('athenz.voice._load_engine',
                        side_effect=AssertionError('Unexpected model initialization')):
            with self.assertRaisesRegex(VoiceError, 'directory'):
                transcribe_wav(self.wav, self.root / 'missing', confirmed=True)
            (self.model / 'model.bin').unlink()
            with self.assertRaisesRegex(VoiceError, 'offline files'):
                transcribe_wav(self.wav, self.model, confirmed=True)

    def test_cli_explicit_inspect_and_transcribe_routes(self):
        with mock.patch('builtins.print') as printed:
            main(['inspect', str(self.wav)])
        inspected = json.loads(printed.call_args.args[0])
        self.assertFalse(inspected['private_audio_in_output'])
        from types import SimpleNamespace
        with mock.patch('athenz.voice._load_engine',
                        return_value=self.fake_engine(SimpleNamespace(text='PRIVATE TEXT'))), \
             mock.patch('builtins.print') as printed:
            main(['transcribe', str(self.wav), '--model', str(self.model),
                  '--confirm'])
        report = json.loads(printed.call_args.args[0])
        self.assertEqual(report['transcript'], 'PRIVATE TEXT')
        self.assertFalse(report['stored_in_profile'])


if __name__ == '__main__':
    unittest.main()
