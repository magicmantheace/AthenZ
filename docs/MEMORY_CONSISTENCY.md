# Read-only approved-memory consistency audit

AthenZ's memory-management workflow keeps owner changes reviewable and
provenance-linked. Different approved records can nonetheless repeat or
appear to disagree. The **memory audit** exposes a few specific candidates
for an owner's inspection; it **does not** decide what is true.

Run either:

```sh
athenz memory-audit
athenz memory-audit --limit 40
```

Or open **Desktop → Review memory → Find possible duplicates…**.
The desktop lists pairs by ID and generic reason, and lets you inspect
both complete private records and source details. Resolve any genuine issue
manually via **Manage approved**, where corrections become *pending* and
need separate reapproval; revocation/forgetting remain explicit owner
actions. If a candidate changed since the audit, the desktop rechecks its
current approval before showing details.

## What the detector finds

- **Normalized duplicate**: same-kind, same text after case, Unicode
  compatibility, whitespace and punctuation normalization.
- **Possible polarity conflict**: same-kind, opposite first-person
  `I prefer/like/want/enjoy X` versus `I do not / don't / no longer
  prefer/like/want/enjoy X`, with exactly matching object phrase.

These patterns are only *review hints*, never verified contradictions.
For example, a person may change preferences over time, or quote a
fictional claim. The detector does not resolve time, context, sarcasm,
exception rules, synonyms or general natural-language contradictions.
It does not match different memory kinds. Records with no recognized
pattern are **not demonstrated to be mutually consistent**.

The audit streams/reads a consistent SQLite snapshot of **approved**
identity memories only. It refuses a corpus larger than 5,000 approved
records rather than silently implying the rest is clean. At most 80
candidate pairs are returned; aggregate counts include omitted pairs.
The CLI returns IDs, counts and generic kinds only, no memory text,
training rows, paths or model-generated language. The desktop shows
full private text **only after explicit owner inspection**.

This feature never starts Ollama, modifies identity rows, revokes consent,
trains weights, writes audit content to files, or calls other projects.
Approval remains the owner-controlled source of truth. Deleting from the
live database has the ordinary SQLite/WAL/offline-backup limitations.
