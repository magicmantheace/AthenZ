# Architecture

```text
athenz.cli / athenz.chat
        |
        v
IdentityStore + LearningStore  ---->  ~/.athenz/identity.sqlite3 (v2)
  | approved identity/decision facts   | conversation by mode/session
  | train/calibration/test decisions  | test gold excluded from prompts
  | pending owner writing samples      | owner feedback and reviewed pairs
  | reviewed experiences/tests         | scoped proposals, revisions
  v
Prompt builder (untrusted data only) ---> loopback Ollama model
                                      (no model-controlled tool access)

Code-propose: select 1-4 existing files -> model JSON -> diff -> human apply
             -> explicit compile/unittest -> pending evidence -> human review
             -> optional revert (revokes reviewed lessons)

Later v0.3–v1.0: retrieval, contradiction engine, worktree isolation,
training registry, LoRA, benchmark gate, desktop supervisor, secure retention.
```

The v2 migration preserves existing v1 identity/decision rows. SQLite is the
local state source of truth; Git is the source of truth for application code
and roadmap, never a personal-data store. No model weights change in current
versions. Git commits, network access and unsupervised shell execution are not
part of the local coding proposal tool.
