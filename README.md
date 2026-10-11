# AthenZ

**AthenZ** is a local-first digital twin, an approval-gated personal memory
system and a bounded coding assistant. Twin mode estimates the owner's style
and preferences without pretending to literally be the owner; Agent mode
works for the owner and learns from reviewed, test-backed work evidence.

**Status: v0.2 pre-release integration.** Identity, private conversation
persistence, feedback and training candidates, opt-in writing imports, and
scoped code proposals are implemented. No autonomous daemon, isolated coding
sandbox, self-directed training, LoRA model deployment or desktop app exists
yet. The target PC's Ollama inference remains unverified.

## Installation (Python 3.11+, local Ollama optional)

```sh
python -m pip install -e .
athenz init
athenz propose preference "Prefer tests before deployment"
athenz list identity --status pending
athenz status 1 approved
athenz context
python -m unittest discover -s tests -v

# For local conversations, install Ollama and fetch a model first:
ollama pull qwen3.5:2b
python -m athenz.chat --mode agent --session work
python -m athenz.chat --mode twin --session personal
```

Ollama only connects to explicit HTTP loopback (`127.0.0.1`, `::1`,
`localhost`). By default it uses `http://127.0.0.1:11434`.
Use `ATHENZ_OLLAMA_URL` and `ATHENZ_MODEL` to customize local inference.

## Learning and reviewed coding

```sh
# Messages are shown with reply IDs; give feedback on an assistant reply:
athenz feedback 2 down --correction "The answer I would actually give"
athenz list train_pairs --status pending
athenz review train_pairs 1 approved
athenz export-training ~/reviewed-training.json

# Preview personal writing samples, then explicitly import them as pending:
athenz import-chatgpt ~/Downloads/conversations.json --source-ref oct-2026
athenz import-chatgpt ~/Downloads/conversations.json --source-ref oct-2026 --confirm
athenz list writing_samples --status pending

# Review a model-proposed code patch before changing source files:
athenz code-propose /path/to/repo "Fix arithmetic" calc.py tests/test_calc.py
athenz code-diff 1
athenz code-apply 1
athenz code-test 1 --kind compile
athenz code-test 1 --kind unittest
athenz list experiences --status pending
athenz review experiences 1 approved
athenz code-undo 1
```

Only explicitly selected existing text files can be proposed. A human runs
`code-apply` and chooses when to test; the model cannot execute shell commands,
commit, push or deploy. `unittest` executes code from the specified repository
on the host — it is **not sandboxed**. Do not run it on untrusted repositories.
Test-backed experiences remain pending unless approved. A reverted proposal
revokes any approved lesson attached to it. Tests passing are observations,
not proof of code correctness.

## Privacy and limitations

Local data is held in `~/.athenz/identity.sqlite3` or `ATHENZ_HOME`. Do not
put this directory inside the Git repository. No personally identifiable
owner data, raw chat exports, conversation contents or training samples are
committed here. `athenz export ...` and `athenz export-training ...` refuse
paths inside detected Git working trees.

Use `athenz forget identity <id>`, `athenz forget-runtime messages <id>`,
`athenz delete-session <session>`, or `athenz purge-source <source> --source-ref
<ref>` for targeted deletion. SQLite/WAL and external backups can retain
remnants: encryption-at-rest and backup lifecycle controls are **not** done.
Never assume automatic learning has modified model weights.

## Project references

- [ROADMAP.md](ROADMAP.md) — v0.1–v1.0 acceptance criteria.
- [AGENTS.md](AGENTS.md) — development, privacy and safety constraints.
- [docs/LEARNING.md](docs/LEARNING.md) — detailed memory and coding controls.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — runtime component boundaries.

## v0.3 experience-learning foundation (experimental)

Reviewable episodic memory and non-executing task checkpoints are available:

```bash
athenz observe "Python testing" "Use mocks for network calls" --tag python --tag tests
athenz list episodes --status pending
athenz review-episode 1 approved
athenz recall "python tests"
athenz checkpoint-save parser-fix "Improve parser" --state-json '{"step":1}'
athenz checkpoint-show parser-fix
```

Approved episodes are retrieved only for matching topics, and recorded coding
lessons require current passing test evidence. See
[docs/LEARNING.md](docs/LEARNING.md) for conflict review, source purge, revision
checks, and limitations. This does **not** yet make AthenZ a self-training or
unattended autonomous agent. Checkpoints store data but cannot execute tasks.
