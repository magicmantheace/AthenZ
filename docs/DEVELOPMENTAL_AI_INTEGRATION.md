# Developmental AI integration contract and release gates

**Status: D2 AthenZ-side synthetic envelope, source reviews, durable outbox, authenticated stream framing and mutual-key handshake prototypes exist; live cross-repo transport, real owner identity and protected key provisioning are not implemented.** Created 2026-10-14 to align
[AthenZ](https://github.com/magicmantheace/AthenZ),
Developmental AI (separate private repository) and
[Synveil](https://github.com/magicmantheace/Synveil) for the February 9, 2029
integrated research target.

The bounded synthetic contract fixture is documented in [DEVELOPMENTAL_AI_BRIDGE_D2.md](DEVELOPMENTAL_AI_BRIDGE_D2.md). This plan remains an acceptance checklist, **not**
evidence that these repositories currently communicate. Developmental AI
already has separate synthetic simulators, tabular policies, latent dynamics,
stepwise change detection, memory experiments, quarantined candidates and
held-out predictive review. Its draft
integration contract (`docs/INTEGRATION_CONTRACT.md` in the separate repository)
is specification-only. Actual cross-repository transports and trusted
runtime integration remain unimplemented.

## Single-agent architecture

AthenZ is the **owner-facing persistent executive**, interaction and
permission boundary. Developmental AI is **the one adaptive learning core**,
not an independent conversational character, a replacement for an LLM, or
a privileged process. AthenZ may load or consult specialized modules for
coding, language, planning, perception, navigation or speech, but these
modules do **not** form independent owner-facing identities and cannot
authorize their own permissions. This is a unified identity/decision process,
not a requirement that all computation use one neural network.

The AthenZ Twin is a *consented simulation* of the person's documented
preferences, decisions and expression; Agent Mode is a distinct assistant
role of the same authorized agent, not the source person. Private
human-origin records are never relabeled as agent-experienced events.
Simulated experiences do not become autobiographical statements about the
person. Synveil is an optional future host for bounded system interfaces.
The same research engine must run headless on Windows/WSL2 or generic Linux.

The narrow, working Developmental AI experiments currently do not justify
claims of brain emulation, consciousness, human-equivalent intelligence,
independent goal invention, safety calibrated to a specified real-world
error rate, or successful lifelong autonomous learning.

## Ownership of data and authority

| Responsibility | Source of truth | May receive | May not do |
| --- | --- | --- | --- |
| Human-origin consent, memories, corrections, identity, deletion | AthenZ private profile | Owner-reviewed, scope-limited imported records | Export all personal history into model-training or research logs by default |
| Agent episodes and outcomes | AthenZ provenance store, using verified Developmental AI receipts | Bounded action-proposal/result events | Present simulator activity as human history |
| Simulation policy, world-model and memory-control state | Developmental AI versioned private checkpoints | Synthetic observations or explicitly approved redacted features | Inspect AthenZ SQLite directly or install/promote its own weights |
| Coding tools and system changes | AthenZ explicit review gates; later Synveil deterministic host policy | Typed, time-limited proposed actions | Execute shell, privileged commands, deploy, commit/push or publish merely because a learned policy proposed them |
| Runtime model selection and rollback | AthenZ reviewed model registry, lineage and owner confirmation | Audited candidate evaluation receipts | Treat a benchmark hash as owner consent or silently promote a model |

### Four distinct learning mechanisms

- **Immediate context:** AthenZ retrieves approved, revocable memories for
  response conditioning without claiming a model-weight update.
- **Verified episodic/procedural learning:** bounded agent work episodes and
  independently observed results produce reviewable lessons; reverse any
  derived lessons on a revoked or rolled-back source.
- **Experiential adaptive learning:** Developmental AI experiments learn
  policies, attention/memory control and latent world models in an isolated
  simulator; unsafe or degraded candidates remain quarantined.
- **Neural fine-tuning:** existing AthenZ local QLoRA and comparative held-out
  evidence requires explicit owner approvals, recorded provenance and an
  independently checked rollback path. A Developmental AI candidate alone
  does not approve a language-model change.

Do not collapse any mechanism into an unqualified "continuous self-training"
metric. Report what actually changed: context, private lesson, simulator
policy/world model, or local neural weights.

## D2: Minimum viable trusted local bridge (first implementation)

The initial bridge shall be **off by default** and use in-process calls or
local-only IPC on the user's machine; no network listener reachable beyond
loopback and no remote cloud dependency. The specific transport shall be
chosen by implementation tests (Windows/WSL2 and Linux must work) rather
than assuming an operating system or Unix-only socket. A process that
can spoof the local address must not be treated as authenticated merely
because it is local.

Require a bounded, versioned envelope with:

- `schema_version`, `event_id`, `conversation_or_task_id`, monotonic
  sequence/revision, origin (human/agent/simulation/system), owner-granted
  purpose/scope, explicit environment namespace, event kind, payload type,
  payload digest, creation time and producer/session authenticity information.
- A strict **allowlist** of non-executable event kinds:
  `observation`, `goal_proposed`, `action_proposed`, `outcome`,
  `checkpoint`, `learning_candidate`, `evaluation_receipt`,
  `revocation`, `pause` and `resume`. No prompt field may specify a
  new event permission or executable command.
- Size/count/time limits, numeric/Unicode validation, schema negotiation,
  idempotence and durable deduplication; reject unknown fields that affect
  authority. Treat malformed versions and replayed/reordered events as
  no-op or explicit failure, never as a grant.
- Opaque references to private AthenZ content rather than dumping personal
  text into the learning engine. Consent is checked when reading an item
  **and again before derived memory or model state is committed**.
- Explicit origin tagging: `human_record`, `agent_experience`,
  `simulation_episode` and `system_telemetry` stay distinct in all
  storage, retrieval, evaluation and UI paths.

When the learner is unavailable, AthenZ chat and supervised coding still
function with their last owner-approved state. Malformed event streams,
transport loss, model-bank mismatches or ambiguous consent fail closed;
the operator can pause and inspect without destroying historical evidence.

**D2 acceptance:** a synthetic AthenZ → Developmental AI → AthenZ round trip
records one observation, one bounded proposal, one explicitly approved
outcome and a non-authoritative learning receipt; proves restart replay,
duplicate suppression, forged-origin rejection, source-revocation fences,
separate human/agent/simulation timelines, and graceful learner-off
behavior on Linux and Windows.

## D3–D6: Research and supervised learning gates

1. **Frozen independent generalization (D3).** Compare transferred
   policies against untrained, random, hand-coded heuristic and privileged
   oracle references on unseen task families, changed observation meanings
   and unfamiliar sensor failures. Metrics must include success, wrong
   decisions, abstention/coverage, predictive likelihood and retention
   regression. Do not tune on those held-out outcomes. Known seeds
   17/23/41 and 1009/1013/1031 have already been inspected in Developmental
   AI and cannot be relabeled blind.
2. **Reusable skills (D4).** A single executive loads versioned capability
   manifests with explicit allowed inputs, outputs, side effects, budgets,
   ownership and confidence/reliability evidence. Transfer and skill
   rollback require regression benchmarks; skills cannot broaden their
   own privileges.
3. **Owner-bounded sandbox goal selection (D5).** Develop goals from
   agent experience, not hallucinated personal identity; limit simulations,
   tokens, time, cost and retry rate, with halt/interrupt and human
   intervention points. A successful sandbox plan can become an action
   proposal, never a self-authorized real tool invocation.
4. **Lifelong adaptation (D6).** A single restart-safe
   perception → memory → goal proposal → sandbox outcome → candidate update →
   independent evaluation cycle. Quarantine new models/policies, retain old
   snapshots and test for catastrophic forgetting after regime shifts. Use
   AthenZ provenance and revocation to invalidate derived improvements.
   Model promotion requires a separate owner review, not a hash alone.

**D3–D6 acceptance:** all important outcomes are independently reproducible
from private synthetic fixtures, positive and negative results survive
restart, and the previously approved system remains usable after candidate
rejection, rollback and learner crash. Existing narrow simulator gains
are groundwork, not a pass of these gates.

## D7–D10: Integration, hosting, durability and release target

- **D7, 2028 Q2:** Embed the approved learning bridge in AthenZ behind one
  persistent local executive/session identity. Keep private human biography,
  agent experiences and simulation episodes segregated; test source
  correction, consent expiry and derived-data deletion across all stores.
- **D8, 2028 Q3:** Provide a separately installable Synveil adapter for
  typed observations and permission-checked action proposals. No learned
  plan may change Synveil policy; system boot, desktop, fallback and rollback
  work with the learner disabled. Generic Linux and Windows/WSL2 remain
  supported without Synveil.
- **D9, 2028 Q4:** Demonstrate at least 30 days of supervised continuous
  runtime with planned restarts, bounded resource use, failure injection,
  privacy checks, retention and regression metrics, with no unauthorized
  execution or automatic model promotion. Publish all failures.
- **D10, 2029-02-09:** Demonstrate a single persistent, independent
  *digital research agent* using owner-consented AthenZ context and its
  own developing memories, with measured bounded learning and clear
  simulation-vs-human provenance; document hardware limits and unsafe or
  unimplemented abilities. This milestone does **not** certify a mind copy,
  consciousness, subjective continuity or equivalence to a living person.

## Cross-repo implementation order

1. Add identical versioned D2 contracts and synthetic fixtures in both
   AthenZ and Developmental AI; implement the minimum event validator.
2. Implement an AthenZ-issued, revocable, scope-limited authority for
   *reading features* and recording an agent episode; verify provenance,
   deduplication and time-of-use consent at both ends.
3. Integrate one selected Developmental AI simulator through a headless
   adapter; display/review agent episodes in AthenZ without merging them
   with owner biography or invoking real tools.
4. Add restart/replay, offline learner fallback and feature-flag controls;
   exercise tampering, missing resources and synthetic revocation in
   cross-platform automated tests.
5. Only then attempt a supervised continuous sandbox learning cycle,
   held-out generalization and optional Synveil host adapter.

**Source hygiene:** Private SQLite, owner voice/chats, biometric profiles,
identity facts, training examples, unpublished model weights, tokens, keys
and production authentication material stay out of all Git repositories
and hosted Actions logs. CI tests use synthetic data. A hash binds bytes
but is not an authentication signature or evidence of user permission.
