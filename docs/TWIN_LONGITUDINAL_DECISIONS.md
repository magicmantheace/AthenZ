# Private longitudinal decision observations

**Experimental, opt-in and owner-reported. This is not a model evaluation.**

The paired Twin benchmark tests the model's prediction of independent held-out
decisions. It deliberately prevents reuse of the same underlying family across
different held-out samples. Separately, a human's preferences can change over
time, and apparently conflicting choices may reflect different contexts rather
than a bad model prediction.

This offline journal records **explicitly owner-confirmed** time-separated
observations without feeding the information into AthenZ chat, Twin memory,
train/calibration/test benchmarks, agent feedback or neural training. It does
not validate the person's identity or authenticate historical dates.

## Local owner-only commands

First create a normal AthenZ private profile directory (for example with
\`athenz init\`). Do not choose a path inside a Git repository.

\`\`\`sh
athenz-decision-timeline init --confirm
athenz-decision-timeline record --family fictional_route --choice north_path --context usual --on 2026-01-01 --confirm
athenz-decision-timeline record --family fictional_route --choice north_path --context usual --on 2026-01-20 --confirm
athenz-decision-timeline report --min-days 7
\`\`\`

\`--home /trusted/private/path\` before the command chooses an existing private
profile. AthenZ creates \`decision-timeline.json\` with owner-only permissions.
No model, service, network connection, scheduler or SQLite database is opened.

Use lowercase, simple **3–64 character** identifiers for each owner-reviewed
decision **family**, choice and context. Use one family for recurring decisions
that truly represent the same question, one choice code for the same actual
option over time, and a shared context code only where the circumstances are
meaningfully comparable. Enter the true observation date in \`YYYY-MM-DD\`.
Backfilled self-reports are possible but **are not independently attested**.

The journal rejects a second observation for the same family, context and
calendar day. To correct a mistaken entry, securely edit the private file
with an owner-controlled editor, or create a fresh journal; there is no silent
overwrite or automatic correction/promotion mechanism. All file writes are
explicit, owner-confirmed, bounded and atomic; a concurrent writer's lock or
an unexpected source change refuses an update rather than clobbering it.

## Interpretation

The report sorts observations by date within each family/context group and
compares **consecutive** choices whose recorded dates are separated by at
least \`--min-days\` (default 7, permitted 1–365). It counts how often the
owner-reported choice label was identical. Observations with a different
context are *never* directly paired; adjacent observations too close in time
do not qualify. Repeated comparisons, even over several dates, are
correlated. No p-values or independent accuracy intervals are supplied.

To prevent overly specific summaries, aggregate metrics are **suppressed**
until there are at least five qualifying consecutive pairs across at least
three distinct decision families. No family names, choice labels, exact
dates, contexts, individual changes, or per-family statistics are returned.

An observed choice change may reflect preference evolution, context not
captured by the owner label, an observation mistake or simple human
variability. Stable self-reports do not prove that the Twin would predict
them accurately. This tool does **not** modify the original held-out
evaluation, inspect private model prompts, auto-import data into training,
or assert psychological/identity continuity.

## Security boundaries

- Only \`~/.athenz/decision-timeline.json\` or the chosen \`ATHENZ_HOME\` copy
  contains the owner observations. Never commit, upload, or share it.
- Directories and files must be private; symlinks, hardlinks, unexpected
  schema/fields and oversized journals are rejected.
- \`record\` uses a local exclusive lock, checks the current journal,
  fsyncs a private temporary file and replaces the original atomically.
  The lock should only be manually recovered after verifying no writer
  remains. The filesystem is not a security sandbox against a malicious
  concurrent user with equivalent owner access.
- \`report\` is read-only and all output is aggregate, with small cohorts
  suppressed. It does not contact Ollama or external providers.
- The journal is separate from the normal profile SQLite database. Profile
  SQLite purge/backup operations do not automatically erase or back up this
  separate file; owners must include it explicitly in private data lifecycle
  procedures.

A later owner-device study may use this as a contextual human-consistency
reference **only after** additional independent review and source provenance.
It must not be treated as model-quality evidence on its own.
