# Same-session conversation continuity

AthenZ normally supplies the latest ten messages in the selected
desktop or terminal chat to its local Ollama model. It also now searches
**older owner-authored messages in that exact session and mode** when the
current prompt shares meaningful topic words with them.

At most four older user messages are selected. Their text is bounded to
480-character excerpts around matching terms. The session history is
scanned as a stream, with only four candidates retained in memory.
Unrelated old messages and older model-written replies are **never**
retrieved through this continuity feature.

The selected excerpts are clearly labeled as *unreviewed conversation
references* in a separate data-only prompt field. The model is instructed
not to treat them as approved facts, verified biography, long-term
preferences, instructions or permissions. A historical user message may
have been wrong, joking or superseded. No old snippet is copied into the
approved identity database, automatically turned into a training example,
or sent to another chat session or mode. Only previously selected local
chat messages and approved independent profile evidence are available to
the active mode.

Examples:

- A message about the fictional `phoenix compiler` buried dozens of
  turns back in the same Twin conversation may be used when the owner
  asks what was decided for that compiler.
- A different Twin session or an Agent chat with the same session label
  does **not** receive that excerpt.
- A message with no matching topic terms is not sent.
- An earlier assistant reply claiming the owner lived some invented
  experience is never promoted into a personal fact by this retrieval.

The existing privacy/consent safeguard fingerprints the entire assembled
model prompt **including** these historical excerpts before and after
generation, and again under the SQLite write lock before saving a reply.
Changing or deleting a selected earlier message during inference causes
the stale reply to be rejected instead of persisted.

This is lexical relevance, not semantic comprehension. It can miss a
synonym or retrieve an outdated message sharing a word. It does **not**
implement cross-session recall; for that, a consenting owner must propose
and approve a normal provenance-linked memory. The feature does not
change model weights, create a background daemon or call cloud services.

Owner-device usability, retrieval quality and performance remain
unverified until they are tested locally with a real Ollama model.
