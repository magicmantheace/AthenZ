# Local synthetic Twin + Agent smoke

This experimental acceptance test checks that an **already installed local
Ollama model** can produce one Twin and one Agent reply through AthenZ's real
desktop-service pipeline, and that the replies persist to isolated chat modes.

It uses **fictional, public test text only**. It does not read your normal
AthenZ profile, test your personality or prove the model uses the GPU.

## Running

First install Ollama and an appropriate local model on your own computer.
Do not put personal records into a Git repository. Then use:

\`\`\`sh
athenz-chat-smoke --model qwen3.5:2b --confirm
\`\`\`

Alternatively, in **AthenZ Desktop → Setup**, click **Test Twin + Agent
(synthetic)…**, enter the installed model tag, and explicitly authorize the
two local generation calls. The app never starts this test automatically.
It does **not** perform a model pull, adapter install, training, Docker
command, publication, scheduler run or automatic permission grant.

AthenZ creates a new disposable OS temporary directory with a synthetic
approved preference, calls the real Twin/Agent prompt builder, then
\`DesktopService.send\` once in each mode using the same synthetic session
identifier. It verifies the two committed user/assistant pairs are separate
and the original synthetic requests were persisted. Finally, it closes the
private SQLite files and removes the temporary directory.

The report includes only fixed status codes and booleans. It never includes
the model response, profile paths, installed model tag, real owner memory,
hardware identifiers or raw exception strings. The command exits nonzero if
local inference or round-trip persistence fails. If the test fails, review
Ollama locally and rerun deliberately; never treat a failed test as
evidence about the owner's personal preferences.

## What a pass actually establishes

- A local model accepted two synthetic requests from AthenZ's real chat
  pipeline, returned nonempty responses, and stored two complete turns.
- A fictional approved preference reached Twin and Agent prompt assembly.
- Two chat modes persisted independently under one disposable profile.
- The normal owner profile was not inspected or used for inference.

A pass **does not establish** correct prediction of owner decisions, model
weights/lineage, use of the RTX 3060, CUDA/QLoRA training, Windows display
behavior, backup recovery, network isolation against a malicious local
service, secure erasure of a failed temporary profile, digital mind
continuity or readiness for unattended automation.

For a separate single-synthetic-prompt transport check, use
\`athenz-inference-check --model <installed-tag> --confirm\`. For GPU
inventory, CUDA and real private-owner fidelity tests, use their separate
consent-gated protocols. No owner's real private test data belongs in CI.


## Optional five-inference Twin memory lifecycle

To test more of the **real local Ollama** conversation and owner-review pipeline
without opening a private profile, use:

```sh
athenz-chat-smoke --model qwen3.5:2b --twin-lifecycle --confirm
```

This is **opt-in** and makes five local model requests, rather than the two
used by the default smoke. It begins with the ordinary disposable Twin and
Agent chat, then:

1. Opens the same Twin session through a new desktop-service object.
2. Stages a fictional preference correction; confirms that neither the old
   nor the pending replacement appears in the **approved profile context**.
3. Generates another Twin turn while the correction is pending.
4. Reviews/approves that correction; checks the new approved profile context
   and generates another Twin turn.
5. Revokes the fictional preference, checks the approved context again,
   generates a final Twin turn, and verifies that all four Twin chat turns
   and the separate Agent turn persisted across fresh service objects.

On successful completion the fixed status code is
`synthetic-twin-lifecycle-observed`. The sanitized report also exposes
which lifecycle checks succeeded. A failure returns a nonzero exit code.
All content, prompt text, model output, local profile path, and installed
model tag remain excluded from the report. The temporary profile is never
the ordinary owner profile. No model is installed, downloaded or fine-tuned.

**Important limitations:** The test verifies that pending and revoked text
is absent from **approved memory references**, not that an LLM cannot repeat
unverified earlier chat or infer a formerly approved fact. The model's reply
content is not semantically scored. It is neither proof of correct responses,
owner resemblance, predictive accuracy, secure erasure, GPU use nor performance.
A Windows/RTX 3060 run must occur on the actual computer to validate hardware.
