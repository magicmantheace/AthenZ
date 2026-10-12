# Owner-reviewed episode conflicts (experimental v0.3/v0.6)

AthenZ can surface **approved episodes with overlapping topic tags** when a new
private episode is pending. Shared tags do **not** prove that two memories
contradict each other. The local AI cannot approve, reject or supersede these
records. No model inference or external network request is used by this tool.

## Desktop

Open **Review memory**, select a **pending episode**, then choose **Review
episode conflicts…**. After confirming that you want to view *private*
content, AthenZ displays the full candidate, up to 50 approved overlapping
episodes, their source/provenance, shared tags and the exact review SHA-256.
Read those records before selecting a decision:

- **Reject** declines the pending candidate and leaves existing approvals alone.
- **Keep both** approves the candidate without silently invalidating existing
  evidence. It does not mean the statements are logically compatible.
- **Supersede** approves the candidate and rejects **one** explicitly selected
  approved predecessor, recording the supersession relationship.

You must manually enter the entire review SHA-256 shown in the dialog, specify
an approved overlapping predecessor for supersession, and confirm the action a
second time. A modified candidate, changed source attribution, new overlapping
approved episode, or changed predecessor makes the review hash stale. You must
reopen the review. There is **no batch/automatic conflict resolution**.

## Standalone CLI

```shell
# Shows private text on your local terminal, including full competing records.
athenz-conflicts --home /trusted/private/athenz preview 17 --confirm

# Recopy all 64 SHA-256 characters from THAT review.
athenz-conflicts --home /trusted/private/athenz decide 17 keep-both \
  --sha256 REVIEWED_64_CHARACTER_SHA256 --confirm

# Or explicitly supersede an approved conflicting predecessor:
athenz-conflicts --home /trusted/private/athenz decide 17 supersede \
  --predecessor 9 --sha256 REVIEWED_64_CHARACTER_SHA256 --confirm

# Or decline the new candidate without touching old memories:
athenz-conflicts --home /trusted/private/athenz decide 17 reject \
  --sha256 REVIEWED_64_CHARACTER_SHA256 --confirm
```

Never paste private CLI preview output into a public issue or attach it to a
repository. No private text is written by this feature to the source tree.
Both preview and decision require explicit confirmation. The decision is
committed in one SQLite write transaction along with metadata-only events.

## Limitations

This provides **explicit human adjudication**, not semantic matching. Tags may
miss real contradictions or surface unrelated entries. When more than 50
approved overlaps exist, it fails closed rather than showing a truncated
review. It does not infer which memory is true, analyze latent meaning, train
new model weights, grant coding permissions, or re-enable old scheduler jobs.
Full Windows accessibility and multi-process stress testing still remain part
of the v0.6 release acceptance work.
