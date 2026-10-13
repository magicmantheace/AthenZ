# Experimental opt-in offline speech transcription (v0.8)

AthenZ provides an owner-triggered **existing-file-only** PCM WAV speech
transcription CLI. It does not open a microphone, listen continually, run a
daemon, upload audio, use an API, start at boot, create chat messages, generate
training data, remember speech, or move a model into AthenZ inference.

## Commands

```powershell
athenz-voice inspect C:\\PrivateAudio\\note.wav
athenz-voice transcribe C:\\PrivateAudio\\note.wav --model C:\\PrivateModels\\whisper-ct2 --confirm
# Optional, only if the local GPU/backend is already configured and trusted:
athenz-voice transcribe C:\\PrivateAudio\\note.wav --model C:\\PrivateModels\\whisper-ct2 --device cuda --confirm
```

The first command reads **format metadata only** and prints sample rate, channels,
approximate duration and byte count. It never starts a transcription backend.
The second command prints the **private transcript into the current terminal**
only after explicit confirmation. Treat that terminal and its scrollback or
redirected output as private. AthenZ itself never saves the transcript or
adds it to Twin/Agent history. To use words in chat the owner must explicitly
paste or enter them separately.

Supported input is 16-bit uncompressed PCM WAV, mono or stereo, at common
sample rates from 8–48 kHz, up to 90 seconds and 24 MiB. Other formats must
be explicitly converted by the owner before use. Input WAV and model files
must be ordinary non-hardlinked, non-symlinked local files. This accepts
existing local speech models; it does not bundle, download or train models.

A trusted **local CTranslate2 faster-whisper** model must already exist with
at least `config.json` and `model.bin`, and a compatible `faster-whisper`
package must be installed separately. There is no dependency at routine AthenZ
startup. The model is opened by absolute directory path with
`local_files_only=True`. English is the fixed initial transcription language.
CPU is the default; CUDA is optional and may require separate native libraries.
The code refuses overlong transcripts and too many speech segments, and
returns sanitized fixed errors rather than GPU exceptions or audio paths.

## Limits and acceptance

Transcription can be inaccurate, especially with accents, background noise,
names and specialized terminology. **Synthetic tests** use mocked models and
generated silent WAV files; they do not prove accurate transcription or native
Windows/RTX 3060 performance. No live device test or audio privacy assessment
has yet been performed. WAV metadata inspection is not an audio consent bypass:
the file must still be deliberately selected. This experimental entry point
does **not** provide microphone capture, wake words, real-time voice chat, a
voice assistant, TTS, automatic action approval, or accessibility certification.
