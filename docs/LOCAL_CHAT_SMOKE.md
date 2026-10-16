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
