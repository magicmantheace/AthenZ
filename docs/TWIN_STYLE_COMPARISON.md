# Private blinded Twin writing-style comparison

**Experimental pilot. No claim of personality accuracy or identity equivalence.**

AthenZ already separates approved writing into train/calibration/test. This
new workflow estimates whether the owner *prefers Twin-personalized writing*
over a neutral answer by comparing two outputs from the **same installed
local Ollama model**, given the same owner-authored writing task.

The Twin arm receives the existing approved Twin reference profile (which
contains only approved training writing). The baseline arm receives no
personal context. Neither receives owner test/calibration writing or any
test reference text. The two outputs are randomly labelled A/B, and the
mapping is not shown before the owner rates them.

This is an *owner-blinded pairwise preference pilot*, not an objective
similarity benchmark. The owner knows their own style; no independent panel,
semantic leakage screening or gold-answer scoring is present yet.

## Prepare private data

Review at least three independent, owner-authored `train` and `test`
writing samples and check `athenz style-readiness`. Do not use sample
text as a writing-task prompt and do not approve near-duplicate test
examples. There is only a normalized **exact** overlap guard; semantic
paraphrases and long transformed quotations are not caught.

## Run an explicitly approved local comparison

```sh
athenz-style-compare start "Write a friendly note about a neighbor's garden." --confirm
athenz-style-compare show 1
athenz-style-compare rate 1 A --confirm
athenz-style-compare report
athenz-style-compare delete 1 --confirm
```

Use `--home /path/to/private/athenz-profile` before the subcommand if
the profile is not in the default private directory. `start` optionally
accepts `--model` for an explicitly installed local model. If no model
is specified, it respects AthenZ's reviewed active model routing or the
local Ollama default. The model tag is checked against the installed local
manifest before and after generation. No remote inference or tool
execution is involved.

`show` reveals only the task and unlabeled A/B texts; it never identifies
which arm was personalized. `rate` records A, B or tie, once, and requires
`--confirm`. `report` provides only aggregate results: Twin vs neutral
preferences, ties, a non-tie preference rate, an illustrative Wilson
interval, counts of unrated or stale cases, and an explicit warning that
personality accuracy is **not** measured or certified. It sets an
illustrative minimum of five non-tie choices but that is far too small
for a credible fidelity claim.

### Revocation, provenance and restart safety

Completed pairs live in `~/.athenz/twin-style-comparisons.sqlite3`,
outside the main identity database and Git repositories. The private
database holds the owner task and two raw outputs **unencrypted**;
protect the device and private backups accordingly. Pairs are never
automatically imported into train data or model weights.

Each comparison snapshots the approved training-reference fingerprint,
approved held-out writing fingerprint, and local Ollama model digest.
Source approvals and model identity are rechecked after *both* model
calls and before saving. Failure leaves no result. If approved evidence
later changes, old ratings are marked stale and excluded from the
current aggregate. A stale unrated comparison refuses rating until a new
one is created; deleting a pair removes its saved task and text from the
comparison database. SQLite deletion does not guarantee secure erasure
of backups, sectors or filesystem snapshots.

Local checks cannot prove human evaluation blindness or prevent a
malicious host process from manipulating local SQLite. The heuristic
that rejects copy/pasted held-out writing tasks is lexical rather
than semantic and does not guarantee contamination-free evaluation.
No private owner datasets, outputs or identifiers are included in
public CI; tests use synthetic fixture prose only.

## Next gate

Build a validated owner task bank independent of held-out writing,
add adjudicated hidden references or an independent blind reviewer,
and compare Twin and neutral responses over sufficiently numerous
unseen tasks. Track qualitative style similarity, factual invention,
uncertainty, decision accuracy and inference cost separately.

## Reviewed independent writing-task bank (Twin-first follow-up)

The earlier `start "task" --confirm` flow remains available for exploratory
personalization checks. For more reproducible evaluation, prepare independent
writing prompts **before** inference and approve them separately from writing
examples:

```sh
athenz-style-compare task-add "Write a sincere apology for missing a meeting." --confirm
athenz-style-compare task-add "Write a short welcoming note to a new neighbor." --confirm
athenz-style-compare tasks
athenz-style-compare task-review 1 approved --confirm
athenz-style-compare task-review 2 approved --confirm
athenz-style-compare start-next --confirm
athenz-style-compare show 1
athenz-style-compare rate 1 A --confirm
athenz-style-compare report
```

The task bank uses the **same** private comparison SQLite archive. New tasks
are pending until explicitly approved; unapproved/rejected tasks never reach
the model. Approval checks the independently approved train/test sample
readiness and refuses obvious direct copies of withheld writing. An approved
task is bound to both training-evidence and withheld-evidence fingerprints;
changes invalidate its approval for current use until the owner reviews it
again. The oldest currently approved, unused task is selected. Results are
linked to the approved task in the same SQLite commit, preventing reuse or
silently labeling an old ad hoc comparison as independent study evidence.

`tasks` returns **counts only**, never owner prose; the report also
distinguishes rated, approved task-bank cases from exploratory ad hoc cases.
After starting a comparison, the owner still sees **unlabeled A/B responses**
and must explicitly rate them. Using multiple tasks, hiding model identity
and saving consistent prompts reduces bias but **does not ensure scientific
blinding, task independence, objective style similarity or model reliability**.
The same owner prepares and reviews tasks, and the heuristic contamination
check does not detect paraphrased test-writing leakage.

Use `athenz-style-compare task-review TASK_ID rejected --confirm` to withdraw
an unused task. `athenz-style-compare task-delete TASK_ID --confirm` removes
the private task text **and any linked generated pair/rating**. Deleting
private SQLite content is not guaranteed forensic erasure; backup snapshots
and filesystem copies may preserve old bytes. Previous ad hoc tasks stay
exploratory even if someone later approves an identical task for the bank.

The task bank has no connection to AthenZ training datasets and does not
auto-promote a model, add a memory or alter Twin policy. Actual on-device
pilot evaluations and independent human judgments remain outstanding.


## Evaluation-integrity checks (2026-10-15)

Writing task approval and the inference preflight now reject **substantial
lexical near-copies** of either approved training writing or protected
test/calibration writing. This reduces two biases: inadvertently revealing
withheld source prose to the comparison model, and letting the personalized
arm win by echoing a training example that appears inside the task. The
screen checks normalized Unicode and words, long contiguous passages and
large overlapping word-bigram sets. Owner review also rejects near-duplicate
writing that crosses training/test/calibration splits. The safeguards remain
lexical: they **cannot** detect all semantic paraphrases, translations,
conceptual overlap, or leakage already embedded in model weights.

An A/B study uses **one exact recorded model identity** (local model tag
plus its SHA-256 digest). Multiple models or model versions can now coexist
in the private archive without being silently pooled. The aggregate report
continues to show descriptive preference totals but **suppresses a combined
win rate and confidence interval across different model cohorts**. It
provides a list of anonymized cohort-level rates/intervals and reviewed-bank
versus exploratory ratings. Cohort IDs are truncated SHA-256 fingerprints of
recorded model identities; raw model tags, digests and owner writing are
not exposed in the aggregate. Unrated and stale records do not create an
active rated cohort.

`report` is still an offline read-only operation. It **does not call Ollama
or independently reverify that model weights still match their recorded
digest**. The local model is checked at comparison-generation time, not
when reporting. Cohort-specific preference counts are experimental evidence,
not proof of an owner's identity, objective style accuracy or consciousness.
