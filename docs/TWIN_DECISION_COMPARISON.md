# Paired local Twin decision-prediction benchmark

**Status: experimental implementation; no owner-hardware result yet.**

This benchmark asks whether AthenZ's *approved Twin context* improves its
prediction of the owner's held-out choices, relative to the same locally
installed Ollama model **without any owner-specific memory or writing style**.

Both arms receive **identical held-out scenarios, option order, temperature
0 and model seed**. The model only receives the scenario plus choice options.
It never receives the known correct choice, the owner rationale, the
train/calibration/test partition label, or other held-out metadata. Neutral
and personalized calls are interleaved in deterministic randomized order
per case. Gold answers remain strictly local to the evaluator.

## Owner-only usage

On the owner's trusted PC, approve independent **training** decisions
separately from untouched `calibration` or `test` decision cases. Review
every case before scoring. Never evaluate a training-split case.

```sh
athenz-decision-compare --split calibration --limit 12 --confirm
# Only after the calibration plan is fixed and frozen:
athenz-decision-compare --split test --limit 30 --confirm
# Optional exploratory uncertainty measurement, same rule for both arms:
athenz-decision-compare --split calibration --limit 30 --allow-abstain --confirm
# Separately assess subjective confidence (not calibrated prediction):
athenz-decision-compare --split calibration --limit 30 --score-confidence --confirm
```

Optional `--home /private/profile`, `--model installed-local-tag`
and `--seed 42` select a private profile and reproducible local evaluation
settings. `--confirm` is mandatory before opening a model inference session.
The local model's Ollama manifest digest and AthenZ's reviewed active route
are checked before and after each generation. Calls use loopback only; no
cloud LLM, external write, scheduled execution or model fine-tuning.

Abstention is an optional, *uncalibrated* model self-assessment; do not
interpret answering more often as being more correct. Fix the evaluation
settings using calibration data before touching a final test split. The
baseline keeps the same lack of owner evidence, and both arms share the
ABSTAIN rule when enabled. Default runs remain choice-only.

Alternatively, use `--score-confidence` to request a JSON choice plus the
model's own probability that its selected answer matches the owner's choice.
This mode **cannot** be combined with `--allow-abstain`: confidence and
abstention require separate experimental protocols. Both model arms receive
an equivalent confidence-format contract. Any missing, nonnumeric,
out-of-range, non-finite or additional output fields invalidate the answer.
A refusal or malformed response is never a valid scored probability.
The private evaluator accumulates **only** fixed-size numeric summaries;
it never retains or exports case-level confidence or outcomes.

The report contains **counts only**, source fingerprints and the local model
tag. It includes:

- Twin and neutral correct predictions over the *same* held-out cases
- Both-correct, Twin-only-correct, neutral-only-correct and both-wrong counts
- Invalid/unparseable predictions by arm
- The paired **accuracy difference** in percentage-point units (a fraction
  in the JSON), and chance expected from number of options
- Descriptive 95% Wilson intervals for each arm
- Discordant pair count, the Twin win fraction when the arms differ, its
  descriptive Wilson interval and a two-sided exact McNemar/binomial p-value
  for equal discordant win rates. The p-value is null if arms never differ,
  exploratory, and assumes independent held-out cases.
- With --allow-abstain, both arms may decline unsupported predictions. Those
  count as not-correct overall, but separately from malformed outputs. Report
  coverage and accuracy among answered cases; zero answered means null.
  Invalid outputs also reduce coverage, but are not intentional abstentions.
- In confidence mode, **samples**, mean claimed probability, correctness
  among scored predictions, **binary chosen-answer Brier score**, and fixed
  ten-bin **expected calibration error (ECE)** for each arm. Both error
  measures are better when lower; ECE is highly sample-size sensitive.
  These are **not** full multiclass probability-distribution scores. A zero
  sample count produces null metrics instead of a claim of calibration.

No per-case scenario, correct answer, rationale, model response or choice
letter is returned or persisted. Results should be kept private because the
aggregate still reflects owner-specific preferences. No model action or
training promotion is authorized by a benchmark score.

## Independent owner-reviewed decision families (optional)

The lexical preflight cannot detect meaning-preserving paraphrases. To add
**human-reviewed semantic grouping**, first run:

```sh
athenz-decision-compare --family-template --confirm
```

This creates an owner-only `decision-family-audit.json` under the local private
AthenZ home directory. Its schema v2 contains the **private original
scenario texts**, current splits, scenario fingerprints and a full approved
decision evidence fingerprint, plus empty `family` and
`category` labels. Never commit, upload, or share this file. Assign the same
lowercase family identifier to every scenario representing the same underlying
decision, even if phrased differently, and choose a category from `work`,
`relationships`, `planning`, `creative`, or `other`.
Use distinct family identifiers for independent scenarios. The template
is created **only once**; after adding or revoking approved decisions,
the owner must review and regenerate a replacement private manifest.

To validate all reviewed labels **offline without loading Ollama**, then
enforce the completed review before a model run:

```sh
athenz-decision-compare --family-check --confirm
athenz-decision-compare --split test --limit 100 --family-audit --confirm
```

The offline check returns only validity, version and approved record count.
Any change in an approved decision's choice, rationale, provenance, split or
scenario after template creation requires explicit re-review and regeneration
of the private manifest, even when the scenario wording itself is unchanged.
A prior schema-v1 template is considered stale and must also be regenerated.
Never silently overwrite a completed family manifest.

All approved decisions across train, calibration and test must have complete,
unchanged manifest entries; **cross-split family reuse** or **two held-out
decisions sharing one family** fails closed before any inference.
The input file and all approved decision revisions are checked for changes
before and after every model call. The model never sees the category, family
identifier, held-out answer, or reviewer annotations.

A private aggregate report includes category accuracy only for categories
with **at least five** selected cases. Smaller categories and all raw owner
family names are suppressed. The audit is *optional* for backwards
compatibility and has no claim to automatic semantic understanding:
misclassified relationships, external pretraining contamination, and
non-independent decisions can still survive manual review.

## Fail-closed conditions

Before the first inference, scan all selected held-out scenarios for strong
cross-split duplicates, repeated held-out cases, literal/normalized owner
reference collisions and malformed choice options. If any case is suspect,
the entire run is refused without contacting the model with those cases.
Recheck the complete approved reference and held-out source fingerprints,
individual case data and model identity before/after each inference; a
withdrawn or altered item invalidates the whole run.

These are **lexical** contamination checks and cannot catch semantic
paraphrases, retained model-weight memorization, source-profile import
errors or adversarially forged approvals.

## What this can and cannot tell us

A reproducible Twin advantage over neutral on unseen, consented owner
decisions would be **evidence of personalization value** in a narrow set
of test cases. The exact paired test does not repair correlated tasks,
small samples, post-hoc threshold tuning, selection bias or unverified labels.
It does **not** demonstrate general intelligence, the
owner's consciousness, a mind transfer or an accurate digital copy of
the person. Decisions may vary over time, and owner-labeled examples may
contain uncertainty. Report sample size, options per question, failure
rates, family-level diversity and owner-device latency separately.

Self-reported probabilities are uncalibrated model statements, not objective
certainty. The scoring tools measure evidence of calibration but do not
produce or validate a learned correction rule. Never tune the confidence
policy or thresholds using the untouched test split: use calibration
examples only, then assess the frozen protocol on new independent test
examples and report selection and sample-size limitations.

A credible v1.0 decision-fidelity claim still requires larger frozen,
independently reviewed scenarios; multiple runs and models; explicit
abstention/uncertainty evaluation; semantic overlap audits; and actual
on-device inference with the owner's consent. This implementation provides
the measurement mechanism, not the missing experimental evidence.
