# AthenZ

A local-first digital twin and coding agent that learns from approved personal context, feedback, and verified work.

**Status:** Initial repository bootstrap. The existing Adam Twin v0.1 prototype is being migrated here. Runtime inference on the target PC has not been verified.

## Product roles

- **Twin mode:** estimates the owner's communication and decisions, without claiming to literally be that person.
- **Agent mode:** completes explicitly scoped work, respecting the owner's working preferences and permissions.

## Learning model

1. Approved memory improves answers immediately.
2. Verified experiences generate reviewable procedural lessons.
3. Versioned LoRA training improves model weights only after evaluation and explicit promotion.

This repository must never contain the owner's unredacted chat exports, private database, API keys, tokens, or training datasets containing personal information.

See [ROADMAP.md](ROADMAP.md) for release goals and [AGENTS.md](AGENTS.md) for engineering and safety rules.
