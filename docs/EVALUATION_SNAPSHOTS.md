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

## v0.7 scoring integrity and uncertainty

The JSON-format system message is inserted before the approved reference
profile. Historical experimental builds inspected the wrong message when
checking for literal held-out leakage. The corrected evaluator checks the
reference profile itself and fails closed if its expected structure changes.
Any experimental scores produced before this fix require fresh evaluation.

The evaluator now returns a descriptive 95% Wilson binomial accuracy interval,
an invalid-prediction count, and the prior accuracy/chance fields. Invalid
letters count as incorrect and are represented as null predictions. Model
comparisons carry these aggregate metrics without persisting private prompts,
case predictions or gold choices. These intervals assume independent
observations and do not establish statistical significance for correlated
owner decisions, independently certify a model, or authorize promotion.

## Adapter review score validation

Private comparison reports must have a finite numeric accuracy gain within
the possible range of -1 to +1 before saving. Adapter review requires a
strictly positive finite gain and excludes booleans, NaN, infinity and values
above 1 even when an older on-disk report has a matching SHA-256 checksum.
This guards malformed score metadata, but SHA-256 still proves byte identity
only and does not independently attest benchmark execution or adapter lineage.

## Normalized lexical held-out collision guard

The evaluator now also rejects sufficiently distinctive held-out scenario or
rationale phrases when an approved reference contains the same word sequence
with different punctuation, spacing, case or Unicode compatibility forms.
Short or generic phrases still receive the previous exact literal check to
avoid claiming meaningful semantic similarity from a few shared words.
The guard is deliberately conservative and cannot detect paraphrases,
reorganized facts or memorization in model weights. No raw held-out content is
included in the error message or exported comparison report.

## SFT held-out punctuation variants

The private training dataset exporter also excludes approved instruction pairs
whose normalized Unicode word sequence exactly matches a calibration/test
scenario, even when spacing, punctuation, capitalization or hyphenation differ.
This affects only the held-out exclusion check, not exported text or ordinary
approved-pair conflict/deduplication semantics. Newly added held-out scenarios
invalidate an already exported dataset when its reviewable source selection
changes. The check is still lexical: true paraphrases and leaked facts in
otherwise different answers remain a v0.7 benchmark-data quality risk.

## Embedded held-out text in reviewed SFT training

Reviewed SFT pairs are withheld when their instruction or answer contains a
long, distinctive protected calibration/test scenario or private rationale,
including with changed punctuation, hyphenation, capitalization, or surrounding
prose. Short/common phrases are not used as substring triggers (four words and
20 nonspace characters required), but complete held-out instruction matches
still exclude short exact cases. This is a privacy-oriented conservative
lexical guard—not semantic paraphrase detection or proof against memorization.
The selection is recomputed during immutable dataset verification, so new
protected text invalidates previously built training snapshots. No held-out
texts or examples are logged by inspection reports.

## Consistent paired-model benchmark evidence

Both local model result sets are checked against their individual held-out
case outcomes before reporting accuracy gains. Invalid/contradictory case
flags, missing or inconsistent aggregate counts, impossible accuracy, and
invalid-prediction counts fail closed. Paired improvement/regression counts
and an exact one-sided sign-test probability are reported as aggregate-only
metadata without releasing owner prompts or case-level answers. The small
sample, case-dependence and possible repeated evaluation invalidate automatic
significance or promotion claims. Eligibility remains owner review only and
still requires a strictly positive observed accuracy gain; model selection
and training remain separate, explicitly approved operations.

## Aggregate comparison persistence integrity

New-format paired benchmark counts, rates, gains and exact paired statistics
are rechecked at report persistence and adapter-review read time. A report
with inconsistent, nonfinite, contradictory or partial aggregate metadata
is refused even when its byte checksum is valid. Historical aggregate-only
reports that predate these fields remain readable but are not independently
attested or statistically verified by these checks. A SHA-256 checksum guards
byte identity, not provenance, independent model execution or lineage.

### Bounded SFT inspection at scale

The protected held-out scenarios and distinctive rationales are compiled once
into a four-token-prefix index before SFT export inspection. Training pairs
are scanned by consecutive normalized tokens and full-phrase confirmation,
not by repeatedly searching every held-out text in every training answer.
This reduces incidental work for larger reviewed histories without widening
semantic interpretation or changing ordinary short-expression handling.

## Cross-split approved scenario independence

Before and after held-out inference, AthenZ checks all approved decision
scenarios in the training, calibration and test partitions. A Unicode,
punctuation, whitespace or case-normalized duplicate crossing these splits
invalidates the benchmark without transmitting its private text to a model.
Unapproved records do not count as model training evidence. This prevents
trivial cross-split reuse but cannot detect near-paraphrases or contamination
of previously trained model weights, and does not prove independent test sets.

### Split evidence revalidation after inference

The same approved scenario cross-partition collision check is repeated at
confirmed evaluation report persistence and when an existing report is read
for adapter selection. A newly approved calibration/test or training duplicate
therefore revokes stale review evidence even when the specific case fingerprint
for the originally evaluated split has not changed. The checks refuse reports
without exposing the private collided scenarios. Semantic paraphrase detection
and independent model-execution attestations remain separate unsolved tasks.

### Immutable adapter registration metadata

An existing private adapter registry entry is now compared against the full
expected immutable registration, including its explicitly owner-registered
candidate tag, fixed unverified-lineage marker and no-deployment state. Earlier
checks verified artifact fingerprints but did not reject every extra or changed
non-weight field. This does not independently establish candidate lineage; it
prevents unreviewed changes to registry fields from influencing later manual
selection or runtime routing.

### Persisted held-out case identity and model digest checks

When a model comparison is saved for owner review, its reported aggregate
case-ID hash must match the current, ordered, approved held-out case IDs. The
report's optional baseline and candidate model digest fields must be either
both present with distinct well-formed SHA-256 values or both absent for a
legacy metadata-only report. This prevents mismatched or partial evaluated
model evidence from being accepted through the report API; it does not prove
that an Ollama model executed or independently verify a locally replaced tag.

### Adapter registration digest anchors

The candidate tag is not independently derivable from adapter weights, so
checking only canonical checkpoint fields cannot detect swapping one valid
tag for another. Each explicitly confirmed adapter registration now atomically
writes its immutable checkpoint and a SHA-256 commitment to its **entire**
registration into the append-only local metadata event ledger. Later adapter
reviews refuse a missing, duplicated or mismatched registration commitment.
Historical unanchored registrations require the owner to explicitly repeat
registration with the same data to create the anchor; no automated candidate
selection or repair is permitted. This detects accidental/unsanctioned SQLite
checkpoint changes but is not a cryptographic signature or protection against
a malicious actor who controls and can forge the entire local database.

### Strong lexical near-duplicates across evaluation splits

In addition to exact normalized case matches, approved training/calibration/
test decision scenarios are checked for unusually high token-set overlap
(Jaccard at least 0.88, at least eight distinct words, at least 48 characters
excluding spaces). An inverted-word index avoids a quadratic all-pairs scan;
only a private generic error is returned. This detects small insertion,
removal or reordered-word variants, not semantic synonyms. Shared introductory
phrases below the threshold remain eligible. Near matches may reflect genuine
separate choices; the owner must review and partition them before evaluation.

### Strong lexical near-matches in SFT export

A protected phrase index also screens approved training instructions and
answers for strongly similar held-out scenario or rationale word sets:
at least eight distinct words, 48 characters excluding spaces, and Jaccard
similarity of 0.88 or higher. Near matches are withheld before private JSONL
export and cause verification to reject old exports if new held-out evidence
appears. The heuristic can reject legitimate close wording and cannot find
conceptual paraphrases or claims memorized in weights; owner review remains
necessary to establish benchmark independence.

## Owner-confirmed benchmark save requires current local model identity

For modern comparison reports that include evaluated baseline and candidate
Ollama SHA-256 digests, confirmed persistence rechecks both local tag digests
before writing the private immutable report. A tag replaced since evaluation
must be evaluated again, rather than persisting an apparently passing score
for different weights. Optional aggregate invalid-prediction counts are
bounded and any nonnull 95% Wilson accuracy intervals must agree with the
reported correct/total counts; fabricated confidence bounds fail closed.
Legacy reports without both model digests can still be inspected according
to their older metadata contract, but cannot establish model lineage or
independently attest candidate quality. Reports never initiate model pulling,
training, tagging or switching.

### Chance-baseline integrity in paired comparisons

Both model evaluation passes must report the same finite, plausible random
chance baseline for their identical held-out cases. Divergent, non-finite or
non-numeric chance baselines fail before a paired comparison can be saved.
The persisted aggregate chance estimate is also range-checked. This cannot
prove the model's statistical independence or that all benchmark choices are
appropriately balanced; it prevents obviously contradictory comparison
metadata from being mistaken for independent performance evidence.

## Read-only held-out benchmark readiness preflight

Run `athenz-training inspect-heldout --split calibration --limit 100 --min-cases 10`
to inspect private aggregate approved case counts, bounded selection size,
and whether the existing strict lexical train/calibration/test overlap check
passes. No Ollama requests, model imports, training, dataset export, scenario
text, expected choices or gold rationales are included in this report.
It does not verify a specific training dataset, detect semantic paraphrases
or attest to model accuracy. It is a preparation step only; `compare --confirm`
and any later reviewed model change remain separate explicit user decisions.

Readiness inspection now validates that each selected approved held-out case
has a decodable 2–6-choice list containing the stored gold answer. It reports
only the boolean `heldout_options_valid` without printing any option text or
private answer. Malformed cases are reported as not ready before local model
requests are made. This remains a limited preparatory check, not a promise
that real model inference or the full contamination gate will succeed.

### Exact protected held-out prompt construction

Both real evaluation and the read-only benchmark preflight reuse one prompt
assembler for the selected held-out scenario, seeded answer-option order and
Twin reference profile. This avoids divergent leakage checks between preflight
and inference. Ambiguous answer-choice lists (identical normalized choice
labels, including whitespace/case variants) are rejected before any model
request. Gold rationales remain excluded from model-visible prompts.

The held-out preflight also assembles the *exact* synthetic, seeded Twin
reference prompts without calling Ollama. It checks lexical exposure of
private held-out scenarios and distinctive rationales in the selected approved
reference context, verifies all answer options are unambiguous, and rejects
changed approval snapshots detected during inspection. Only boolean status
flags are returned; the prompts, answers and reference evidence never leave
the owner's private profile. This remains lexical rather than semantic proof.

### Batch-wide held-out privacy and integrity preflight

Before the first local model-generation call, decision evaluation now
assembles and checks the entire selected held-out batch using the same exact
private Twin prompt as real scoring. A leaked reference scenario, rationale
or ambiguous choice found in any later item blocks **all** model requests,
instead of discovering the leak after earlier cases have already been sent.
The reference and selected-case fingerprints are rechecked before starting
inference and still checked during and after each case. This extra local-only
read work is deliberate and does not constitute semantic paraphrase detection.

### CPU adapter merge/conversion checkpoint revision fencing

The owner-approved local CPU PEFT/GGUF conversion attempt now pins the exact
running checkpoint revision before invoking the optional long-running CPU
backend. If the owner pauses or changes that revision during conversion, an
old process may not report completion, install weights or overwrite the newer
checkpoint with a failed status. Any finished output remains an untrusted,
owner-reviewable attempt directory; it is not adopted as the active model.
The failure path also uses compare-and-swap only on the original running
revision. Re-arming after an interrupted conversion still requires explicit
owner approval and cannot silently overwrite an earlier attempt.

To revoke the conversion checkpoint while an explicitly started CPU merge is
running, use `athenz-training pause-conversion <run-id> --confirm`. The pause
changes private checkpoint authority immediately and makes the original
worker's eventual output ineligible for adoption; it **does not terminate**
the underlying CPU process or delete its partial files. After inspecting and
stopping that process when necessary, the owner can explicitly run
`athenz-training run-conversion <run-id> --resume --confirm`, which reserves a
new numbered attempt directory and never overwrites the old one. Pausing a
completed/failed conversion is refused, and no Ollama model is automatically
selected or imported.


## v0.7 held-out within-split independence guard (2026-10-14)

The protected evaluator now checks the **selected approved calibration or test
cases** for repetitions before sending any case to a model. Exact scenarios
after Unicode NFKC, case and punctuation normalization are refused; long,
distinctive scenarios are also refused when their token sets reach the same
conservative 88% Jaccard near-match threshold as cross-split leakage checks.
Pending/unapproved records do not count as held-out observations. These are
lexical heuristics: paraphrases can still slip through, and diverse cases may
still be correlated in reality.

`athenz-training inspect-heldout` exposes a new
`selected_cases_independent` boolean without returning the underlying
scenarios. A false value also makes `ready_for_owner_review` false. The
actual evaluator rechecks selected-case independence after inference; the
candidate comparison checks it before consulting Ollama's installed-model
inventory, and immutable report persistence refuses corrupted or repeated
samples. The checker does not train models, infer private decisions from
metadata, authorize promotion or establish statistical independence.

Scores produced on duplicated previous samples should be rerun after owner
review and a distinct case set. The conventional Wilson interval assumes
independent observations and can be overconfident even after this lexical
guard passes.

## Held-out population freshness on owner-reviewed model comparisons (2026-10-14)

New comparisons record both the requested evaluation case limit and the
**entire approved split population** at the time of evaluation. The validator
rechecks that full count after the two model calls and before owner-confirmed
report persistence, including when the new case is outside the selected
limited sample. A newly approved, unscored decision no longer silently
preserves stale evaluation evidence. Both fields are aggregate numbers,
never scenario text or answer labels.

Historical reports without this metadata remain recognizable for compatibility
and do not gain retrospective full-population attestation. Rerun comparison
on a current independent held-out set when the approved evaluation population
changes. This adds freshness checks, not statistically independent evaluation
or permission to deploy models.

### Versioned learning evidence and downstream adapter validity

New paired `compare` outputs use report **schema 2**, requiring a complete
baseline/candidate aggregate, paired improvement counts/probability, pinned
installed-model digests, requested case limit and full approved split count.
A new schema-two report cannot silently discard these fields and still pass
owner review. Adapter review and routed runtime model validation also reject
a schema-two report if the approved held-out population changes later, even
when the new case lies beyond the originally scored limit.

Historical **schema 1** reports remain readable for continuity, but are not
retroactively claimed to be bound to the full approved population. Their
earlier consent, score, selected-case fingerprint and reference checks remain
in force. A new training/promotion decision should use a fresh schema-two
comparison rather than relying on an older report.

### Full-population private fingerprint

Count-only freshness is insufficient if someone edits a previously approved
but unscored held-out case. Schema-two reports therefore also retain an
in-memory-generated SHA-256 fingerprint of **all** approved cases in that
split, including source provenance, scenario, options, gold answer, rationale,
exceptions and record creation metadata. The private rows are length-delimited
and streamed in stable ID order; the report contains a digest, not those rows.
Comparison completion, report saving and subsequent adapter/runtime review
recompute this fingerprint. A changed out-of-window record invalidates the
previously approved benchmark without exposing its text.

This is tamper detection against accidental/stale owner changes, not a
cryptographic signature of who authored an observation or proof of independent
training lineage. Schema-one historical evidence is not retroactively
population-fingerprinted.
