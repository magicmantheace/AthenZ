# Opt-in local Ollama text generation check (experimental v0.6)

This is **not** a first-run or startup check. It sends **one synthetic,
non-personal prompt** to an already running local Ollama server and a named,
previously installed model. No identity profile, approved memories, history,
training examples or owner documents are read or transmitted.

```sh
athenz-inference-check --model qwen3.5:2b --confirm
# Or without installing the console script:
python -m athenz.inference_readiness --model qwen3.5:2b --confirm
```

The `--confirm` switch authorizes one local inference request, not model
installation, task automation, training, memory approval or deployment. A
`--timeout N` argument permits 1–60 seconds (default 20). Model names are
bounded to local Ollama tag characters and are never echoed in the result.

The existing transport accepts only a loopback HTTP host and port, refuses
HTTP redirects and ignores proxy settings. Its fixed text request is limited
to a short context and 12 predicted tokens. The reply is held in memory briefly
and discarded without logging, display, saving or storing conversation turns.
At most 16 KiB of response data is read; raw replies and errors never enter
reports. A result reports only a sanitized outcome and a coarse elapsed-time
bucket; absence or malformed responses result in a nonzero CLI exit status.

**Limitations:** Successfully generating text only establishes that this
particular local inference request completed. It does *not* prove that CUDA,
RTX 3060 acceleration, WSL2, QLoRA fine-tuning, dataset consent,
model identity, answer quality or performance under realistic context loads
works. An inference request may cause Ollama to load a model temporarily or
use system resources; AthenZ does not install or pull model weights and does
not attempt to forcibly terminate a server computation at its timeout.
The GPU readiness inventory and the local Ollama version probe remain
separate user actions.

## Synthetic instruction-following signal

The probe reports `inference_observed` separately from
`synthetic_instruction_followed`. The latter becomes true only when the
assistant message is exactly `READY` after trimming whitespace. Other
nonempty replies still demonstrate local text generation but do not pass
this deliberately narrow fixed-instruction check. Ollama replies with an
explicit error, an incomplete `done: false` marker, or a non-assistant
role are treated as invalid rather than counting as successful inference.
No reply text is logged or returned; an instruction-following success is
not representative model-quality, safety, acceleration or identity proof.
