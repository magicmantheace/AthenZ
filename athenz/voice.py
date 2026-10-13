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
from pathlib import Path
import stat
import wave

MAX_AUDIO_BYTES = 24 * 1024 * 1024
MAX_MODEL_BYTES = 12 * 1024**3
MAX_SECONDS = 90
MAX_TRANSCRIPT_CHARS = 16000
MAX_SEGMENTS = 500


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
        with wave.open(str(p), 'rb') as stream:
            channels = stream.getnchannels()
            rate = stream.getframerate()
            samples = stream.getnframes()
            width = stream.getsampwidth()
            compression = stream.getcomptype()
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
    """Private in-memory checksum only, never returned or persisted."""
    try:
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
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
                   confirmed: bool = False, device: str = 'cpu') -> dict:
    """Transcribe in the foreground; transcript returned only to consenting owner.

    Does not write owner audio, transcripts, profiles or training pairs.
    CPU is the safe default; CUDA must be separately selected and tested.
    """
    if confirmed is not True:
        raise VoiceError('Explicit --confirm required to process private speech')
    if device not in ('cpu', 'cuda'):
        raise VoiceError('Explicitly choose cpu or cuda device')
    evidence = inspect_wav(path)
    model = _local_model_dir(model_dir)
    audio = Path(path).expanduser().absolute().resolve(strict=True)
    before_audio = _audio_fingerprint(audio)
    engine = _load_engine(model, device=device)
    try:
        segments, _ = engine.transcribe(str(audio), language='en', beam_size=1,
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
    result = ' '.join(parts)
    return {'schema': 1, 'status': 'transcribed' if result else 'no-speech',
            'audio_fingerprint_stable': True,
            'transcript': result, 'device_requested': device,
            'model_downloaded': False, 'audio_uploaded': False,
            'microphone_accessed': False, 'submitted_to_chat': False,
            'stored_in_profile': False, 'training_authorized': False,
            'private_text_in_output': bool(result),
            'duration_seconds': evidence['duration_seconds']}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog='athenz-voice', description='Offline, opt-in transcription of an existing local WAV')
    sub = parser.add_subparsers(dest='command', required=True)
    view = sub.add_parser('inspect', help='Read only audio format metadata')
    view.add_argument('wav', type=Path)
    work = sub.add_parser('transcribe', help='Opt-in private local speech transcription')
    work.add_argument('wav', type=Path)
    work.add_argument('--model', type=Path, required=True,
                      help='Existing locally installed CTranslate2 whisper model directory')
    work.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    work.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    report = (inspect_wav(args.wav) if args.command == 'inspect'
              else transcribe_wav(args.wav, args.model, confirmed=args.confirm,
                                  device=args.device))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
