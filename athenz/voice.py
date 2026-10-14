"""Owner-triggered, private, offline speech-to-text for an EXISTING WAV file.

No microphone, OS listener, server, uploads, downloads, chat submission, or
training storage. Only a trusted locally installed CTranslate2 faster-whisper
model is allowed and inference is never performed on startup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
import stat
import wave

MAX_AUDIO_BYTES = 24 * 1024 * 1024
MAX_MODEL_BYTES = 12 * 1024**3
MAX_SECONDS = 90
MAX_TRANSCRIPT_CHARS = 16000
MAX_SEGMENTS = 500
MAX_REFERENCE_BYTES = 16 * 1024
MAX_EVAL_WORDS = 1100
MAX_EVAL_CHARS = 4096


class VoiceError(ValueError):
    """Refused unsafe audio/model input or unavailable offline transcription."""


def _local_regular(path: Path, *, max_bytes: int) -> tuple[Path, int]:
    candidate = Path(path).expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise VoiceError('Select an existing regular local file, not a symbolic link')
    resolved = candidate.resolve(strict=True)
    try:
        info = resolved.stat()
    except OSError:
        raise VoiceError('Local input is unavailable') from None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or not 0 < info.st_size <= max_bytes):
        raise VoiceError('Local input is linked, empty or outside the size bound')
    return resolved, info.st_size


def inspect_wav(path: Path) -> dict:
    """Check bounds and PCM WAV format; return metadata only, no audio content."""
    p, length = _local_regular(path, max_bytes=MAX_AUDIO_BYTES)
    if p.suffix.lower() != '.wav':
        raise VoiceError('Only existing PCM WAV audio is supported')
    try:
        # Do not re-open a mutable path through wave.open(filename). Use the
        # original name via a no-follow descriptor, then verify its identity.
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(p, flags), 'rb') as handle:
            before = os.fstat(handle.fileno())
            named = p.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                    or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                    or before.st_size != length):
                raise VoiceError('Selected PCM WAV changed before inspection')
            with wave.open(handle, 'rb') as stream:
                channels = stream.getnchannels()
                rate = stream.getframerate()
                samples = stream.getnframes()
                width = stream.getsampwidth()
                compression = stream.getcomptype()
            after = os.fstat(handle.fileno())
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                raise VoiceError('Selected PCM WAV changed during inspection')
    except VoiceError:
        raise
    except (wave.Error, OSError, EOFError, ValueError):
        raise VoiceError('Invalid or unreadable PCM WAV file') from None
    if (compression != 'NONE' or width != 2 or channels not in (1, 2)
            or rate not in (8000, 16000, 22050, 32000, 44100, 48000)
            or not 1 <= samples <= rate * MAX_SECONDS):
        raise VoiceError('WAV must be bounded 16-bit PCM mono/stereo at a supported sample rate')
    duration = samples / rate
    return {'schema': 1, 'format': 'pcm16-wav', 'channels': channels,
            'sample_rate_hz': rate, 'duration_seconds': round(duration, 2),
            'file_bytes': length, 'private_audio_in_output': False,
            'audio_uploaded': False, 'microphone_accessed': False,
            'transcription_started': False, 'file_modified': False}


def _audio_fingerprint(path: Path) -> str:
    """Bounded, no-follow audio digest, never returned or persisted."""
    try:
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            initial = os.fstat(stream.fileno())
            named = path.lstat()
            if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1
                    or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                    or (initial.st_dev, initial.st_ino) != (named.st_dev, named.st_ino)
                    or not 0 < initial.st_size <= MAX_AUDIO_BYTES):
                raise VoiceError('Selected audio is linked or outside the size bound')
            h = hashlib.sha256()
            count = 0
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                count += len(block)
                if count > MAX_AUDIO_BYTES:
                    raise VoiceError('Selected audio exceeds the size bound')
                h.update(block)
            final = os.fstat(stream.fileno())
            if (count != initial.st_size or
                    (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
                    != (initial.st_dev, initial.st_ino,
                        initial.st_size, initial.st_mtime_ns)):
                raise VoiceError('Selected audio changed during local read')
            return h.hexdigest()
    except OSError:
        raise VoiceError('Selected audio could not be rechecked') from None


def _local_model_dir(path: Path) -> Path:
    model = Path(path).expanduser().absolute()
    if model.is_symlink() or not model.is_dir():
        raise VoiceError('Select an existing local faster-whisper model directory')
    root = model.resolve(strict=True)
    total = 0
    for name in ('config.json', 'model.bin'):
        target = root / name
        if target.is_symlink() or not target.is_file():
            raise VoiceError('Local speech model is missing required offline files')
        info = target.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VoiceError('Local speech model contains unsafe linked files')
        total += info.st_size
        if total > MAX_MODEL_BYTES:
            raise VoiceError('Local speech model exceeds permitted size')
    return root


def _model_files_observed(root: Path) -> tuple:
    """Freeze the local runtime file identities without recording private paths.

    Ordinary concurrent file replacement/rewrites invalidate a transcript;
    this is not a model-content hash or adversarial-same-user attestation.
    """
    if root.is_symlink() or not root.is_dir():
        raise VoiceError('Local speech model changed during transcription')
    rows = []
    total = 0
    for name in ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.json'):
        file = root / name
        mandatory = name in ('config.json', 'model.bin')
        if not file.exists() and not file.is_symlink():
            if mandatory:
                raise VoiceError('Local speech model changed during transcription')
            continue
        try:
            if file.is_symlink():
                raise VoiceError('Local speech model changed during transcription')
            info = file.stat()
        except OSError:
            raise VoiceError('Local speech model changed during transcription') from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size < 1:
            raise VoiceError('Local speech model changed during transcription')
        total += info.st_size
        if total > MAX_MODEL_BYTES:
            raise VoiceError('Local speech model exceeds permitted size')
        rows.append((name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
    return tuple(rows)


def inspect_local_model(path: Path) -> dict:
    """Read-only local CTranslate2 model scope inspection without importing it."""
    root = _local_model_dir(path)
    observed = _model_files_observed(root)
    return {'schema': 1, 'scope': 'existing-local-ctranslate2-whisper',
            'required_files_present': True, 'selected_files': len(observed),
            'selected_bytes': sum(record[3] for record in observed),
            'native_backend_loaded': False, 'inference_observed': False,
            'accuracy_validated': False, 'cuda_validated': False,
            'model_downloaded': False, 'owner_path_in_output': False}


def _load_engine(model_dir: Path, *, device: str):
    try:
        from faster_whisper import WhisperModel
    except (ImportError, OSError):
        raise VoiceError('Install trusted faster-whisper locally before transcription') from None
    # Explicit absolute directory and local_files_only forbid model downloads.
    try:
        return WhisperModel(str(model_dir), device=device,
                            compute_type='int8' if device == 'cpu' else 'float16',
                            local_files_only=True)
    except Exception:
        raise VoiceError('Local offline speech model failed to load') from None


def transcribe_wav(path: Path, model_dir: Path, *,
                   confirmed: bool = False, device: str = 'cpu',
                   language: str = 'en') -> dict:
    """Transcribe in the foreground; transcript returned only to consenting owner.

    Does not write owner audio, transcripts, profiles or training pairs.
    CPU is the safe default; CUDA must be separately selected and tested.
    """
    if confirmed is not True:
        raise VoiceError('Explicit --confirm required to process private speech')
    if device not in ('cpu', 'cuda'):
        raise VoiceError('Explicitly choose cpu or cuda device')
    if language not in ('en', 'fr', 'es', 'de'):
        raise VoiceError('Choose an explicitly supported transcription language')
    evidence = inspect_wav(path)
    model = _local_model_dir(model_dir)
    before_model = _model_files_observed(model)
    audio = Path(path).expanduser().absolute().resolve(strict=True)
    before_audio = _audio_fingerprint(audio)
    engine = _load_engine(model, device=device)
    try:
        segments, _ = engine.transcribe(str(audio), language=language, beam_size=1,
                                        vad_filter=False, word_timestamps=False,
                                        condition_on_previous_text=False)
        parts = []
        length = 0
        for index, segment in enumerate(segments):
            if index >= MAX_SEGMENTS:
                raise VoiceError('Transcription exceeds bounded segment count')
            content = segment.text
            if not isinstance(content, str):
                raise VoiceError('Local speech model returned an invalid segment')
            text = content.strip()
            length += len(text) + 1
            if length > MAX_TRANSCRIPT_CHARS:
                raise VoiceError('Transcript exceeds output privacy bound')
            if text:
                parts.append(text)
    except VoiceError:
        raise
    except Exception:
        # A model/backend exception may include owner speech, local paths or
        # CUDA identifiers. None may escape through a returned error message.
        raise VoiceError('Local offline speech transcription failed') from None
    if _audio_fingerprint(audio) != before_audio:
        # Do not return speech inferred from bytes that changed while the
        # optional native decoder or model was reading the selected file.
        raise VoiceError('Selected audio changed during local transcription')
    if _model_files_observed(model) != before_model:
        # This also catches replacement or deletion of optional tokenizer
        # sidecars during inference. It is not proof of model provenance.
        raise VoiceError('Local speech model changed during transcription')
    result = ' '.join(parts)
    return {'schema': 1, 'status': 'transcribed' if result else 'no-speech',
            'audio_fingerprint_stable': True, 'model_files_stable': True,
            'transcript': result, 'device_requested': device,
            'language_requested': language,
            'model_downloaded': False, 'audio_uploaded': False,
            'microphone_accessed': False, 'submitted_to_chat': False,
            'stored_in_profile': False, 'training_authorized': False,
            'private_text_in_output': bool(result),
            'duration_seconds': evidence['duration_seconds']}


def _private_reference(path: Path, *, allow_empty: bool = False) -> str:
    """Bounded, no-follow owner reference read without returning paths or bytes.

    Reading is only permitted after explicit evaluation consent. The caller
    must never put the text into generated reports, memory or public logs.
    """
    selected = Path(path).expanduser().absolute()
    try:
        if selected.is_symlink() or selected.suffix.lower() != '.txt':
            raise VoiceError('Select a private local UTF-8 .txt reference file')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(selected, flags), 'rb') as handle:
            opened = os.fstat(handle.fileno())
            named = selected.lstat()
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                    or opened.st_size > MAX_REFERENCE_BYTES
                    or (opened.st_size == 0 and not allow_empty)):
                raise VoiceError('Reference must be a bounded private regular file')
            payload = handle.read(MAX_REFERENCE_BYTES + 1)
            final = os.fstat(handle.fileno())
            if (len(payload) != opened.st_size
                    or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                    != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)):
                raise VoiceError('Reference text changed during local inspection')
        text = payload.decode('utf-8-sig', errors='strict')
        if any(ord(char) < 32 and char not in '\n\r\t' for char in text):
            raise VoiceError('Reference contains unsupported control characters')
        return text
    except VoiceError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise VoiceError('Private reference text is unavailable or malformed') from None


def _word_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize('NFKC', text).casefold()
    # Word scoring ignores case/punctuation, preserves internal apostrophes.
    # This tokenizer targets supported whitespace-delimited European speech,
    # not languages without conventional word boundaries.
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", normalized, re.UNICODE)
    if len(words) > MAX_EVAL_WORDS or len(' '.join(words)) > MAX_EVAL_CHARS:
        raise VoiceError('Transcript evaluation exceeds its bounded word/character scope')
    return words


def _edit_counts(reference: list[str] | str, hypothesis: list[str] | str) -> tuple[int, int, int, int]:
    """Rolling-row Levenshtein: total edits and substitution/deletion/insertion."""
    # Only 1100 words/4096 characters per input are accepted by the caller.
    previous = [(i, 0, i, 0) for i in range(len(reference) + 1)]
    for token in hypothesis:
        row = [(previous[0][0] + 1, 0, 0, previous[0][3] + 1)]
        for j, gold in enumerate(reference, 1):
            if gold == token:
                match = previous[j - 1]
            else:
                d = previous[j - 1]
                match = (d[0] + 1, d[1] + 1, d[2], d[3])
            deleted = row[j - 1]
            deleted = (deleted[0] + 1, deleted[1], deleted[2] + 1, deleted[3])
            inserted = previous[j]
            inserted = (inserted[0] + 1, inserted[1], inserted[2], inserted[3] + 1)
            row.append(min((match, deleted, inserted),
                           key=lambda item: item[0]))
        previous = row
    return previous[-1]


def score_transcript(reference: str, hypothesis: str) -> dict:
    """Return privacy-safe WER/CER counts; no text, audio or model operations."""
    if not isinstance(reference, str) or not isinstance(hypothesis, str):
        raise VoiceError('Evaluation needs two local text strings')
    gold, actual = _word_tokens(reference), _word_tokens(hypothesis)
    if not gold:
        raise VoiceError('Reference must contain at least one spoken word')
    words = _edit_counts(gold, actual)
    gold_chars, actual_chars = ' '.join(gold), ' '.join(actual)
    characters = _edit_counts(gold_chars, actual_chars)
    return {'schema': 1, 'metric': 'normalized-word-and-character-error',
            'reference_words': len(gold), 'hypothesis_words': len(actual),
            'word_substitutions': words[1], 'word_deletions': words[2],
            'word_insertions': words[3], 'word_errors': words[0],
            'wer_percent': round(100 * words[0] / len(gold), 2),
            'reference_characters': len(gold_chars),
            'character_errors': characters[0],
            'cer_percent': round(100 * characters[0] / len(gold_chars), 2),
            'case_and_punctuation_ignored': True,
            'text_in_output': False, 'reference_persisted': False,
            'independent_accuracy_certification': False}


def score_text_files(reference: Path, hypothesis: Path, *,
                     confirmed: bool = False) -> dict:
    """Compare two private local transcripts without loading audio or a model."""
    if confirmed is not True:
        raise VoiceError('Explicit --confirm required to read private reference text')
    gold = _private_reference(reference)
    text = _private_reference(hypothesis, allow_empty=True)
    # Simple repeat-read fence prevents reporting scores about files replaced
    # while the other owner-selected transcript was being read. No digest is
    # published or added to the owner's memory.
    if (hashlib.sha256(_private_reference(reference).encode('utf-8')).digest()
            != hashlib.sha256(gold.encode('utf-8')).digest()
            or hashlib.sha256(_private_reference(hypothesis, allow_empty=True).encode('utf-8')).digest()
            != hashlib.sha256(text.encode('utf-8')).digest()):
        raise VoiceError('Private transcript input changed during evaluation')
    result = score_transcript(gold, text)
    return {**result, 'evaluation_status': 'scored-private-local-text',
            'reference_and_hypothesis_stable': True,
            'native_backend_loaded': False, 'audio_read': False,
            'model_called': False, 'text_files_modified': False,
            'training_authorized': False}


def evaluate_wav(path: Path, model_dir: Path, reference: Path, *,
                 confirmed: bool = False, device: str = 'cpu',
                 language: str = 'en') -> dict:
    """Score a privately transcribed WAV without ever emitting its transcript."""
    if confirmed is not True:
        raise VoiceError('Explicit --confirm required to evaluate private speech')
    # Refuse an unsafe, absent or malformed owner reference BEFORE starting
    # optional native model inference and its associated GPU work.
    gold = _private_reference(reference)
    if not _word_tokens(gold):
        raise VoiceError('Reference must contain at least one spoken word')
    observed = transcribe_wav(path, model_dir, confirmed=True,
                             device=device, language=language)
    # A human may edit a reference while a slow native model transcribes.
    # Do not issue a seemingly valid score against a superseded reference.
    if hashlib.sha256(_private_reference(reference).encode('utf-8')).digest() != (
            hashlib.sha256(gold.encode('utf-8')).digest()):
        raise VoiceError('Private reference changed during local transcription')
    metrics = score_transcript(gold, observed['transcript'])
    return {**metrics, 'evaluation_status': 'scored-local-speech',
            'device_requested': device, 'language_requested': language,
            'audio_fingerprint_stable': observed['audio_fingerprint_stable'],
            'model_files_stable': observed['model_files_stable'],
            'transcript_returned': False, 'reference_stable': True,
            'audio_uploaded': False,
            'model_downloaded': False, 'training_authorized': False}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog='athenz-voice', description='Offline, opt-in transcription of an existing local WAV')
    sub = parser.add_subparsers(dest='command', required=True)
    view = sub.add_parser('inspect', help='Read only audio format metadata')
    view.add_argument('wav', type=Path)
    model = sub.add_parser('inspect-model',
                           help='Read existing local model file counts and size without loading inference')
    model.add_argument('--model', type=Path, required=True)
    work = sub.add_parser('transcribe', help='Opt-in private local speech transcription')
    work.add_argument('wav', type=Path)
    work.add_argument('--model', type=Path, required=True,
                      help='Existing locally installed CTranslate2 whisper model directory')
    work.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    work.add_argument('--language', choices=['en', 'fr', 'es', 'de'], default='en')
    work.add_argument('--confirm', action='store_true')
    compare = sub.add_parser('score-text',
                              help='Compare two local UTF-8 .txt transcripts without audio/model inference')
    compare.add_argument('--reference', type=Path, required=True)
    compare.add_argument('--hypothesis', type=Path, required=True)
    compare.add_argument('--confirm', action='store_true')
    score = sub.add_parser('evaluate',
                           help='Private WAV/reference accuracy scores; NEVER print speech or reference text')
    score.add_argument('wav', type=Path)
    score.add_argument('--model', type=Path, required=True)
    score.add_argument('--reference', type=Path, required=True,
                       help='Owner-written local UTF-8 .txt transcript reference')
    score.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    score.add_argument('--language', choices=['en', 'fr', 'es', 'de'], default='en')
    score.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'inspect':
        report = inspect_wav(args.wav)
    elif args.command == 'inspect-model':
        report = inspect_local_model(args.model)
    elif args.command == 'evaluate':
        report = evaluate_wav(args.wav, args.model, args.reference,
                              confirmed=args.confirm, device=args.device,
                              language=args.language)
    elif args.command == 'score-text':
        report = score_text_files(args.reference, args.hypothesis,
                                  confirmed=args.confirm)
    else:
        report = transcribe_wav(args.wav, args.model, confirmed=args.confirm,
                                device=args.device, language=args.language)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
