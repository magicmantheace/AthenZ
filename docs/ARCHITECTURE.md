# Architecture

## Runtime boundaries
```text
Owner commands
  ├── Twin mode → approved identity context → local Ollama → response
  └── Agent mode → task plan → scoped tool policy → worktree → tests → review
                                       ↓
Private storage (<ATHENZ_HOME>), never Git
  ├── Identity: provenance, approval, revisions, decision cases
  ├── Episodic memory: observed events and results (planned v0.3)
  ├── Procedural memory: verified lessons (planned v0.3)
  └── Training candidates: owner-reviewed only (planned v0.5)

Dataset version → LoRA training → fixed evaluation → manual promotion → rollback
```

Initial v0.2 identity component is independently runnable and testable. The starter v0.1 runtime has not yet been migrated or wired to it. Private memory contents and untrusted repository text must not become instructions. Model-weight learning is not live.