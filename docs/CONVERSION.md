# Offline adapter merge and GGUF conversion (v0.5 experimental)

This feature **runs locally** against a completed, reviewed Qwen2/Qwen2.5
safetensors/PEFT training run and produces an FP16 **complete** GGUF model.
It never assumes Ollama can import a raw PEFT adapter. It does **not** train,
create an Ollama tag, activate AthenZ's chat model, or upload private data.
The real conversion path still needs testing against installed libraries,
llama.cpp versions and the owner's Windows/WSL2 hardware.

## Prerequisites and warnings

- A completed `athenz-training run-qlora` run and `register-adapter` record;
  the originally approved dataset and base model must still be available.
- Locally installed **trusted** PyTorch, Transformers, PEFT and Accelerate;
  no packages are downloaded by AthenZ.
- An owner-reviewed local checkout of llama.cpp's `convert_hf_to_gguf.py`
  and its import dependencies (normally the installed `gguf` Python package).
  **You are authorizing Python code on the host**. A SHA-256 of the converter
  script detects changes; it does not sandbox the script or verify its imports.
- Enough free **system RAM and disk** for a full CPU FP16 model, its merged
  Hugging Face files, conversion scratch space and the resulting GGUF.
  **12 GB VRAM alone does not ensure this step will fit.** The converter can
  take substantial time and disk space. Low-resource operation has not been
  validated. Run in an isolated disposable VM if the local toolchain is not
  fully trusted.
- A trusted local directory outside Git for `ATHENZ_HOME`.
  Base model, adapters and datasets can include private material.

## Owner-invoked workflow

```sh
# Fingerprint the exact converter you inspected; repeat after upgrades.
python -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' \
  /path/to/llama.cpp/convert_hf_to_gguf.py

athenz-training prepare-conversion RUN_ID \
  --converter /path/to/llama.cpp/convert_hf_to_gguf.py \
  --sha256 EXACT_SCRIPT_SHA256 --trust-converter --confirm

# Explicit owner action: full CPU merge, then external trusted converter.
athenz-training run-conversion RUN_ID --confirm
athenz-training verify-conversion RUN_ID

# Next use the returned artifact.path and your registered candidate tag:
athenz-training prepare-import RUN_ID /path/to/private/merged-f16.gguf \
  --candidate athenz-experiment:trial --ack-merge --confirm
athenz-training import-local RUN_ID --confirm
```

The converter command is fixed: `[current Python interpreter] -I
convert_hf_to_gguf.py merged-hf --outfile merged-f16.gguf --outtype f16`.
AthenZ sets offline environment flags and disables conventional proxy variables
but **is not an operating-system network sandbox**. Treat installed Python
packages and the converter checkout as executable local software with your
account's permissions. No browser/cloud fallback exists.

## Recovery and provenance

The conversion recipe pins the exact approved adapter artifact hash, source
training dataset, base-model fingerprint, and converter-script hash. A new
private attempt is recorded as `running` **before** model libraries execute.
Errors mark it `failed` and preserve partial output for inspection. After a
crash, `run-conversion RUN_ID --resume --confirm` uses a new attempt directory,
never replacing earlier output; at most three attempts are allowed. It does
not resume a half-finished model save in place.

On success, the GGUF's observed SHA-256, size, and absolute private path are
recorded in the checkpoint. `verify-conversion` rechecks current consent,
base model, adapter bytes, script digest, and GGUF file. When a conversion
checkpoint exists, `prepare-import` requires that **exact completed GGUF**;
a merely present file or manually asserted lineage is insufficient.

Hashes and local checkpoints establish **tamper evidence and locally observed
provenance**, not independently verified model correctness, successful
training or proof of a hardware-safe pipeline. Never treat a passing
conversion as sufficient to activate a candidate. Run held-out benchmarks
and explicit review first. There is no automatic cleanup or deletion of
private model artifacts; old attempts consume storage until manually managed.
