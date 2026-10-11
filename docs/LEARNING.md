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
