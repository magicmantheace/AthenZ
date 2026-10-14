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
psychological model. It ranks a bounded candidate pool: `context()`
currently returns the latest 200 approved identity and 200 approved
training decisions, and approved writing samples are sampled from the
latest 200. Older records outside those limits may still be missed.
A later milestone must improve complete-history retrieval with revocation
and independent accuracy/latency evaluation.

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

1. Improve recall across the full approved memory corpus without sending
   unrelated private facts, followed by adversarial retrieval tests.
2. Capture owner-reviewed style/decision examples in private test profiles,
   including correction, exceptions, change over time and uncertainty.
3. Freeze independent decision and writing-style benchmarks. Report coverage,
   errors, unsupported assertions and regressions, not just subjective
   similarity. Never upload private test cases to public GitHub CI.
4. Conduct actual local Ollama and Windows/RTX 3060 Twin sessions with owner
   approval; synthetic unit tests alone do not validate fidelity.
