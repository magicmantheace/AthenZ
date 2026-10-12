# Held-out evaluation evidence snapshots (experimental)

`athenz.evaluation.evaluate_decisions` now captures two SHA-256 digests at the beginning of a locally requested held-out decision evaluation:

- `heldout_sha256` binds the reviewed held-out decision cases, including their source and rationale provenance. Gold choice and private rationale are **not included in the model prompt**.
- `reference_sha256` binds approved identity, training decisions and episodes used as private Twin reference evidence. Pending or rejected records do not supply authority.

The evaluator rechecks both the individual held-out case and the approved reference snapshot before sending a model prompt, and again after the response. It also rechecks the complete held-out case list and reference snapshot at the end. A revoked or edited record fails closed instead of producing a new score.

`athenz.model_gate.compare_models` requires the baseline and candidate reports to match both original fingerprints, and rechecks dataset approval and local model digests. Reports contain aggregate scores and cryptographic fingerprints, not held-out scenarios, private rationales, or generated text. **A local SHA-256 hash is evidence of consistent bytes only: it is not an independent evaluation attestation, model provenance proof, promotion permission, or hardware validation.**

A SQLite transaction is **not** held across potentially slow model requests. Concurrent edits can be detected but not prevented. Unapproved records must still be handled through their separate owner review gates. Real Ollama model comparison, RTX 3060 VRAM constraints and held-out benchmark quality remain unverified on the target PC.

**Compatibility:** Held-out SHA fingerprints now include case provenance as well as gold choices/options. Older experimental evaluation reports using choice-only fingerprints are intentionally stale for adapter review and should be regenerated after an owner-controlled benchmark; no older model is automatically activated or removed.

**Post-evaluation review gate:** Saving a comparison and later selecting an adapter both recheck current approved references and held-out case provenance. Historical experimental reports missing these stronger fingerprints cannot authorize new adapter selection; regenerate a reviewed comparison.

## Literal held-out context contamination guard (v0.7 groundwork)

Before inference, decision evaluation now fails closed if an approved reference
profile supplied to Twin Mode includes the held-out scenario verbatim or a
sufficiently distinctive held-out rationale. The held-out scenario is still
provided as the **user question**, while its gold choice and rationale remain
excluded from that question. Unapproved episodes remain excluded from prompts.
This guard does not detect semantic paraphrases, memorization in model weights,
or independently certify benchmark separation; those require stronger offline
provenance and evaluation controls.
