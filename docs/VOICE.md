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
`local_files_only=True`. English is the default language; the owner can explicitly select French,
Spanish or German with `--language fr`, `es` or `de` (no automatic language
identification or network requests).
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

### Selected audio stability

During confirmed transcription AthenZ computes an in-memory SHA-256 digest of
the local WAV before the model runs and rechecks the same selected bytes after
inference. If the file was modified mid-run, AthenZ refuses to release the
transcript. The digest is not printed, logged or stored; it is not a model
provenance attestation and cannot protect against an actively malicious
same-user process reverting the exact bytes between checks.

WAV hashing uses bounded no-follow file handles and verifies a stable local
inode, byte length and modification timestamp before releasing the result.
The optional faster-whisper constructor is tested to require an absolute
pre-existing model directory with `local_files_only=True` for both CPU and
CUDA. No model weights or source audio are included in the public tests.

### Local model-file stability during transcription

On explicit transcription, AthenZ captures the local speech-model file
identities, byte lengths and modification timestamps for required CTranslate2
configuration/weights and any present tokenizer or vocabulary sidecars.
It verifies the same local files after speech inference before returning the
owner transcript. A file replacement, deletion, symlink, or rewrite during the
operation refuses the private result rather than reporting it as generated
by a stable local model. No model paths, transcript text or these metadata
identifiers are persisted as audit data. These checks are not independent
cryptographic provenance, cannot defeat a privileged same-user adversary,
and do not certify accuracy or model licensing.

### No-follow WAV metadata inspection

WAV inspection now opens the selected local file through a bounded,
non-symlink-following descriptor where supported and compares its open-file
identity, inode, size and modification time with the named file. This refuses
common file replacement and torn-header races between initial path validation
and parsing. The inspection still returns only format metadata—no audio
samples, model request, upload, transcription or owner transcript. Native
Windows filesystem semantics and adversarial same-user directory races are
not independently security-certified.

### Read-only model inventory

```powershell
athenz-voice inspect-model --model C:\\PrivateModels\\whisper-ct2
```

This requires no speech input, owner transcript consent, model import, GPU
setup, native inference or network request. It checks that the existing
CTranslate2 configuration and weights are ordinary, non-hardlinked local
files, and returns only aggregate file count and byte size (including optional
recognized tokenizer/vocabulary sidecars). It never prints the private model
path, filename list or model bytes. A successful inventory is **not** an
inference, accuracy, provenance or CUDA-readiness certification.

## Reference-based offline speech quality evaluation

The owner can supply a short, **private, manually verified UTF-8** reference
transcript for an existing WAV file and request local Whisper inference plus
word/character error-rate measurement in one operation:

```powershell
athenz-voice evaluate C:\\PrivateAudio\\sample.wav --model C:\\PrivateModels\\whisper-ct2 --reference C:\\PrivateAudio\\sample-reference.txt --confirm
```

This is a **separate owner-consent action**, not part of automatic transcription
or chat. The evaluation calls the same bounded offline speech decoder; it
compares its *in-memory* transcript to the locally read owner reference and
prints only aggregate normalized WER/CER percentages, substitution/deletion/
insertion counts, and privacy indicators. Neither text, paths, audio data,
model output, reference content, case-level examples nor model weights are
written to AthenZ's private database or the public repository.

Normalization uses Unicode NFKC, case-folding and punctuation-insensitive
whitespace-delimited word tokens, with apostrophes retained. WER and CER are
Levenshtein edit errors divided by reference word and character counts,
respectively, so results can exceed 100% for excessive insertions. Empty
spoken references are refused, while a missing hypothesis is scored as
100% deletion error. The reference must be a non-symlinked, non-hardlinked,
size-bounded regular UTF-8 `.txt` file. A malicious or outdated owner
reference can yield misleading numbers; an observed score is **not**
independent accuracy certification, speaker identity evidence, or universal
quality validation. Private plaintext is still held in memory while scoring.

### Comparing existing private text transcripts without native inference

Use `athenz-voice score-text --reference C:\\PrivateAudio\\reference.txt --hypothesis C:\\PrivateAudio\\hypothesis.txt --confirm` to measure
WER/CER without reading a WAV, loading faster-whisper, initializing GPU
libraries or contacting Ollama. The two owner-selected, bounded UTF-8 text
files are read locally after explicit confirmation. Only numerical aggregate
results are printed; neither text, input paths nor private metadata are
persisted by AthenZ. This can compare different speech systems using the same
reference, but models must be tested on the same recorded audio to make
results comparable. The model-backed `evaluate` command also validates the
reference *before* starting optional native inference.

Reference stability is checked twice around local native inference. A user
editing the owner-authored reference during a transcription cannot silently
change its score; the evaluation fails with a fixed local error and never
returns the private transcript. Text-only scoring likewise rechecks both
locally selected text files before publishing numeric results. These bounded
repeat-read checks do not defeat a privileged same-user adversary who swaps
bytes and restores them between observations.

An **empty hypothesis file** is allowed in text-only scoring and correctly
reports 100% deletion error against a nonempty spoken reference. An empty
reference remains invalid because WER/CER would have no denominator.
