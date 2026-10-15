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
