# Correcting, revoking and forgetting approved Twin memories

AthenZ only loads **approved** personal claims into the Twin/Agent prompt.
Owner mistakes, changing preferences, or stale records should be corrected
without making the assistant silently invent a replacement claim.

## Desktop workflow

1. Open the **Review memory** tab and click **Manage approved**.
2. Select one memory, then **Inspect and manage selected**. The dialog shows
   the *full* currently approved identity record, text, source provenance,
   dates and approval state. This is private local data.
3. Choose an action and explicitly confirm:
   - **Stage correction**: edit the memory text and provide a reason. It
     becomes **pending** immediately: the old approved wording stops being
     used in prompts, and the new text must be approved separately from the
     Review memory tab.
   - **Revoke**: mark it **rejected**, excluding the claim from all approved
     context selection. The text still exists in the local SQLite database,
     so this is not an erasure operation.
   - **Forget from DB**: delete the record and its previous revision history
     from the live SQLite database. The source chat (if any), independent
     memories, offline backups and old disk blocks are not erased.
4. Check the Review memory tab for pending corrections and inspect their
   complete text/provenance before any new approval.

Each action includes an exact owner-review hash of the full SQLite record.
A separate SQLite write transaction re-reads the row and refuses stale
hashes, deleted/rejected rows and changed provenance. The dialog cannot
approve its own revisions. This interface invokes no Ollama inference,
autonomous coding, model training, publication or remote service.

## Terminal equivalent

For explicit owner-controlled terminal workflows:

```sh
athenz list identity --status approved
athenz revise <memory-id> "Corrected owner-written statement" --reason "Why it changed"
athenz list identity --status pending
athenz status <memory-id> approved
athenz status <memory-id> rejected
athenz forget identity <memory-id>
```

The current CLI operations are explicit manual controls, but the **desktop**
manager adds full-record read-before-edit and stale-record verification.
Treat personal memory as sensitive information: do not put exported
records, screenshot dialogs or private SQLite/WAL files into a public repo.

## Security and evidence limits

A `rejected` record remains in the private database and can only become
approved again by an explicit later owner action. **Forgetting** removes a
live identity and all its revision history, but is not secure erasure from
backups, WAL, SSD blocks, logs outside this application or copies already
shared elsewhere. A reviewed memory is still an owner-approved assertion,
not proof of historical truth or a demonstration of digital-person identity.
