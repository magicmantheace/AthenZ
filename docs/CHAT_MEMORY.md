# Owner-reviewed chat-to-memory proposals

**Experimental local-only feature.** This turns one actual **user-authored**
AthenZ message into a proposed, provenance-linked memory. It does not mine
conversations automatically, claim to infer what the user believes, or train
model weights. Never place actual owner chat or private memory in Git.

## In terminal chat

1. Chat normally using \`python -m athenz.chat --mode twin\` or the desktop.
2. Get the message ID from \`athenz list messages\` (the selected message must
   have \`role=user\`; assistant replies are explicitly refused).
3. Run \`athenz memory-preview <message-id>\`. The private terminal shows the
   **whole original message**, its session/mode and \`review_sha256\`.
4. Write a concise truthful summary in your own words and deliberately stage it:

   \`\`\`sh
   athenz memory-from-message <message-id> preference "My owner-written summary" --review-sha256 <preview-sha256> --confirm
   \`\`\`

5. Inspect the pending record with \`athenz list identity --status pending\`;
   use \`athenz status <pending-memory-id> approved\` only after independently
   verifying that the proposed text is accurate. Until approval it is
   **excluded from Twin/Agent prompts**. To reject it, use the same \`status\`
   command with \`rejected\`.

The source review hash includes message ID, session, mode, role and complete
original content. If any source field changes or the message is deleted,
submission fails and requires a fresh inspection. Only one derived memory
per source message is permitted. Input is a manually written 1–1200
character summary, not an LLM output.

## In the desktop

Open the Chat tab, select the correct session and mode, then choose
**Remember my message**. A dedicated dialog shows the full, read-only most
recent user-authored message from that session, plus the memory type and
an editable summary field. You must type the summary, confirm it, and
independently approve the resulting record on the **Review memory** tab.
The submit operation verifies the exact source and its session/mode under
a local SQLite transaction. It never contacts Ollama.

## Forgetting and provenance

These proposals store the app-only source label \`owner:chat-message\` with
\`source_ref=<message ID>\`, so removing a source through either of the
following cascades to its derived memory (pending **or** approved):

\`\`\`sh
athenz forget-runtime messages <message-id>
athenz delete-session <session>
\`\`\`

The memory's identity revision history is erased as well; unrelated
owner-written memories remain untouched. Explicitly deleting the identity
memory does not delete the original conversation. This linkage is
**application-level** (not a SQLite foreign key), so don't edit the private
database out-of-band.

All model responses remain assistant-authored and cannot be auto-promoted
to a person's personal biography. A user message might itself contain an
incorrect or joking claim, so the owner must inspect and independently
verify the text before approving it. This capability improves traceable,
reversible memory control; it does not establish identity continuity or
digital mind cloning.

Private SQLite/WAL and backups remain subject to existing retention
limitations. Removing an item in the live database does not erase every
offline backup or securely wipe SSD blocks.
