# Twin context relevance and reviewed writing style (v0.7 increment)

AthenZ Twin Mode remains a **consented simulation of the owner's preferences
and communication style**, never a literal human identity or memory copy.
The implementation in `athenz/prompting.py` changes only which existing
approved evidence enters a local prompt. It does not train or update a model.

## What changes

- Retain up to five globally approved `style`/`value`/`preference` records as a general
  communication backbone, prioritizing topic overlap, owner-assigned
  confidence and recency. Other approved identity/preference records must
  match the query lexically (except explicit profile/background questions).
- Select relevant **approved training-split** decisions using overlap of the
  owner's question with the recorded scenario and rationale. Do not send
  unrelated newest decisions simply because they were entered recently.
  Calibration and test decisions are never allowed into Twin prompt examples.
- On Twin Mode only, add up to three explicitly approved writing samples,
  represented as short *style excerpts* with provenance. Pending and
  rejected writing samples are excluded. Agent Mode does not gain access to
  Twin-only writing samples.
- Continue to include owner-reviewed relevant episodes (except unresolved
  disputes); Agent Mode may use independently test-backed work lessons.
- Bound every section and the full JSON profile. Long records that cannot
  fit are **omitted whole** rather than truncating JSON or silently changing
  an approved fact. The total serialized profile stays under 15,900
  characters; the full system message adds the reference heading.
- Hold the same strict local permission boundary: approved personal records
  are reference **data**, not executable instructions or tool authority.
  Without relevant evidence, Twin policy requires expressed uncertainty,
  not invented personal opinions.

## Known limits

This is deterministic **lexical overlap**, not an embedding search,
semantic understanding, validated personality fidelity, or a learned
psychological model. All approved identity records, training decisions and
writing samples are streamed from private SQLite without the previous
latest-200 candidate window. The selected top-K heaps and final JSON context
remain bounded regardless of database size; no persistent embedding index
or retrieval log is created. Relevant reviewed episodes were already
searched across their whole approved table, excluding disputed episodes.

The query itself and the lexical terms are not stored. SQLite scans are
linear in the number and length of approved records and can become slow on
large profiles; there is currently no indexed semantic search. Rare older
facts can still lose ranking to many newer equal-scoring examples, and
overly large records are intentionally skipped at JSON packing. These are
known retrieval-ranking limits, not evidence that the older fact was deleted.

Run `python -m athenz.twin_retrieval_benchmark` to check a disposable
synthetic fixture. It reports exact target retrieval over three scenarios,
historical latest-200 candidate-window recall, JSON/consent separation,
determinism, and revocation propagation. This is strictly an **offline
retrieval regression benchmark** with synthetic records. It does not call
Ollama, score decision correctness, measure real personality similarity,
or inspect the owner's profile.

Adding or approving new writing, including entries not selected for a
particular prompt, now changes the protected Twin reference fingerprint.
Episode disputes also invalidate it. When neither new evidence category is
present, the fingerprint retains the historical three-table representation
so existing clean-profile reviews are not invalidated merely by upgrading.
**All** approved human
records are checked for literal/normalized lexical contamination with
held-out decisions, even when a particular query prunes those records.
These checks are deliberately conservative; they detect neither semantic
paraphrase leakage nor memorization in model weights.

## Next acceptance gates

1. Benchmark latency and ranking performance with much larger private
   synthetic corpora; only introduce a local index if it preserves revocation,
   fail-closed updates, determinism and the held-out privacy boundary.
2. Capture owner-reviewed style/decision examples in private test profiles,
   including correction, exceptions, changes over time and uncertainty.
3. Freeze **independent** decision-accuracy and writing-style benchmarks.
   Report coverage, unsupported assertions and regressions, not only
   subjective similarity. Keep private test examples out of GitHub CI.
4. Validate actual local Ollama inference and Windows/RTX 3060 Twin sessions
   with owner approval; synthetic retrieval tests do not validate fidelity.

## Offline retrieval acceptance benchmark

Run `python -m athenz.twin_benchmark` locally to create a **disposable,
entirely synthetic** private profile, place a relevant identity record behind
260 newer unrelated records, and verify that relevant retrieval works while
unrelated and subsequently revoked evidence is absent. Output contains only
aggregate counts, no private excerpts. CI also runs the same acceptance check
via `tests/test_twin_benchmark.py`.

This tests retrieval mechanics and owner revocation, **not** real owner style
fidelity, semantic memory quality or model reasoning. Those require an
independent, explicitly approved local evaluation dataset.
