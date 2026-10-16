# Desktop chat sessions: browse, resume, and delete safely

AthenZ Desktop's **Chat → Browse sessions…** displays saved local
conversations, one entry per **session name and mode**. Selecting
`research / twin` is different from selecting `research / agent`.

To resume a conversation, choose it and click **Open selected**, or
double-click it. The transcript reloads from the private SQLite database.
Typing a new valid session name into the normal Chat field creates a new
conversation only when you send the first message. Session names are
1–64 letters, digits, hyphens, dots or underscores, starting with a
letter or digit.

To delete a conversation, select it and click **Review deletion…**.
The dialog shows the exact mode/name, total message count, and up to eight
recent **excerpts**. The digest used for confirmation is computed over
**all** session messages, including their full private text, provenance
and timestamps, but only the hash is used for the final comparison.
After you explicitly confirm, AthenZ checks the digest again under an
exclusive SQLite write transaction. Changes to old or new messages
invalidate a stale review.

Deletion from the desktop affects **only the selected mode**. It also
removes any identity memories explicitly derived from that mode's user
messages, those identity revision records, feedback tied to removed
messages and associated training examples. Independent owner memories,
all other conversations, and the other mode of the same session name
are left alone. If an inference is currently running in this UI, the
session manager refuses deletion or switching until it completes or
cancels. A separate process attempting to persist an outdated chat
turn will be refused by the existing session/context drift guard.

Desktop deletion review is bounded to 5,000 messages per session/mode;
larger histories require an owner-controlled external workflow rather
than an unbounded UI operation. Session listing returns the latest
100 entries by default, up to 200 when invoked from the service.

**Important:** The existing CLI `athenz delete-session <name>` affects
both modes. The new mode-specific desktop operation does not change
that command. Deleted SQLite records are not secure wiping of SSD
blocks, WAL files, historic backup archives, exported datasets or
other copies. Check your private backup policy before deleting chats.
Do not commit screenshots, personal messages or database files to Git.

All session controls are local. Browsing, switching, reviewing and
deleting do not contact Ollama, run background work, install models,
promote training, or approve personal identity claims.
