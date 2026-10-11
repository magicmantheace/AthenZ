# Runtime learning (v0.2 integration)

AthenZ can **use new knowledge immediately** through reviewed context, but it does
not yet train or deploy a new neural network. Personal data stays under
`ATHENZ_HOME` or `~/.athenz` in `identity.sqlite3`; do not commit this data.

## Data flow and approvals

1. `python -m athenz.chat --mode agent --session programming` writes a complete
   user/assistant turn only after the local Ollama call succeeds. Twin history is
   separate from Agent history even for the same session identifier.
2. `athenz feedback <assistant-message-id> up|down --correction "..."` creates an
   owner-feedback record, and may create a **pending** training pair. A downvote
   without corrected text is feedback only, not a supervised training example.
3. `athenz list train_pairs --status pending`, then
   `athenz review train_pairs <id> approved` selects only trustworthy examples.
4. `athenz export-training ~/athenz-training-reviewed.json` outputs only approved
   examples **outside any Git repository**. It does not start training.
5. `athenz import-chatgpt conversations.json --source-ref my-export-2026` previews
   the number of user-authored samples. Add `--confirm` to store pending samples.
   Do not import other people's speech as if it were the owner's. A source pair
   can be purged with `athenz purge-source chatgpt:export --source-ref my-export-2026`.

## Reviewed code proposals

Choose up to four existing plain-text source files (no symlinks or protected paths):

```sh
athenz code-propose /path/to/repo "Fix the addition operation" calc.py tests/test_calc.py
athenz code-diff 1
athenz code-apply 1          # deliberate human action, no auto-commit or auto-push
athenz code-test 1 --kind compile
athenz code-test 1 --kind unittest
athenz list experiences --status pending
athenz review experiences 1 approved
athenz code-undo 1           # guarded by file hash; revokes previously approved lessons
```

`compile` is Python syntax checking; `unittest` runs repository test code on the
host and must only be used with trusted local source. There is **no container
sandbox or automatic iterative agent** yet: OS-isolated coding is a v0.4 gate.
Code-test stores the check command, exit code, output excerpt/hash and file
fingerprints; a passing check is not independent proof that a patch is correct.
Experience lessons start pending and can only be promoted to Agent prompt context
after owner review. Twin mode never treats an Agent's work as the owner's
personal lived experience.

## Deletion and limitations

- `athenz delete-session programming` purges that conversation and cascading
  feedback/training examples, including approved examples derived from it.
- `athenz forget-runtime proposals 1` removes linked test evidence and lessons.
- `athenz forget identity 1` and `athenz purge-source ...` retain their v0.1
  granular identity semantics.
- v0.2 does **not** encrypt SQLite/WAL at rest. Deleted SQLite content may remain
  in WAL files or backups until secure retention controls are added. Do not use
  high-sensitivity imports until storage/backup protections have been reviewed.
- Training-candidate export is deliberate; no background model adaptation,
  dataset mixing, external messaging, Git commit/push or model promotion happens.

## Held-out decision evaluation (v0.2 experimental baseline)

AthenZ can collect owner-selected decisions as `train`, `calibration` or `test`
records. Only approved **train** decisions enter routine Twin/Agent context;
calibration/test choices and rationales are excluded, even if approved.

```sh
athenz decision "Should I ship after a failed test?" "Fix it first" \
  "I prioritize verified changes" --option "Ship anyway" --option "Fix it first" \
  --split test --source owner:interview
athenz list decisions --status pending
athenz decision-status 1 approved
athenz evaluate-decisions --split test --seed 42
athenz evaluate-decisions --split test --seed 42 --report ~/private-eval.json
```

The local model is asked to select one option under a seeded, repeatable order.
Only scenario and shuffled options enter its input; the owner-selected correct
answer and rationale are scored afterward. A trivial chance baseline is shown
alongside exact-match accuracy. Training and held-out duplicate scenario titles
are rejected. Evaluation does not modify model weights or save training data.
A real owner-written held-out corpus and target-PC inference are still needed
before any identity-performance claim can be made.

## v0.3 reviewed episodic memory and resumable task checkpoints

Episodes are manually proposed observations, **not verified facts**. They remain
pending until owner review, and only relevant approved episodes enter the prompt.
Keyword/tag overlap is a conservative relevance filter; it does not perform
semantic contradiction detection. Topical overlaps are surfaced for review, and
an approved superseding episode rejects the older episode in one transaction.

```sh
athenz observe "Python testing preference" "Prefer regression tests" \
  --tag python --tag testing --source owner:cli --source-ref example
athenz list episodes --status pending
athenz conflicts 1
athenz review-episode 1 approved
athenz recall "python regression"
athenz observe "Python testing preference" "Prefer isolated regression tests" \
  --tag python --tag testing --supersedes 1
athenz review-episode 2 approved
athenz forget-episode 2
athenz purge-source owner:cli --source-ref example
```

Resumable task checkpoints only store private JSON data; the contents are **never
executed or treated as authorization**. Revision checks prevent stale workers
from overwriting newer state.

```sh
athenz checkpoint-save coding-task "Fix the parser" \
  --state-json '{"next_step":"review patch"}' --status paused
athenz checkpoint-show coding-task
athenz checkpoint-save coding-task "Fix the parser" \
  --state-json '{"next_step":"run scoped checks"}' --status running --revision 1
athenz checkpoint-forget coding-task
```

The SQLite database migrates forward to schema v4. Its event log records only
event names, record IDs and timestamps, with triggers preventing alteration.
Deleting episodes and checkpoints deletes their **content** while retaining
non-textual event metadata. Store `ATHENZ_HOME` outside Git. Checkpoints do not
run in the background, and there is no autonomous coding loop or model-weight
training yet. Existing verified code lessons are retrieved only when the
underlying patch remains applied, its test evidence is the newest passing run,
and the current question is topically relevant.

## v0.3 contradiction quarantine and artifact fingerprints

A topical overlap is only a possible conflict. To mark **two approved** episodes
as genuinely contradictory, explicitly record a dispute. Both memories are
immediately quarantined from Twin and Agent prompt retrieval until an owner
selects which approved memory is correct. Resolving a dispute rejects the other
memory; the record remains reviewable until explicitly deleted.

```sh
athenz dispute 3 4 --reason "The two approved instructions contradict each other"
athenz list episode_disputes
athenz resolve-dispute 1 4
```

For a recorded test run, AthenZ can attach a local file fingerprint (opaque ID,
SHA-256 and length only). The file bytes and local path **are not stored**:

```sh
athenz artifact-hash 1 local-unit-results ~/private-check-output.txt
athenz list evidence_artifacts
athenz artifact-verify 1 ~/private-check-output.txt
```

`artifact-verify` detects whether supplied local bytes still match the observed
fingerprint; it does not prove CI identity, execution provenance, or that the
result was correct. Merely attaching evidence does not approve an experience.
Deleting the linked proposal or test run cascades to its artifact metadata.
Migration to SQLite schema v5 is forward-only and preserves prior memories.
