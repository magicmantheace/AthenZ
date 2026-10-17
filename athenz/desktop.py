"""Local-only AthenZ desktop shell with explicit human approval controls.

Tkinter is imported only when launching the graphical application. A pure
service layer lets CI test privacy boundaries without a display server.
No automatic daemon, model training, unrestricted Docker or Git publishing.
The supervised proposal queue remains paused until the owner acts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import queue
import re
import threading

from .chat import OllamaClient, answer, context_snapshot
from .chat_cancel import ReplyCancelled, ReplyCancelGate
from .experience import ExperienceStore
from .runtime import checked_active_tag

SESSION = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z')
PENDING_TABLES = ('identity', 'episodes', 'decisions', 'train_pairs', 'writing_samples', 'experiences')


class DesktopError(ValueError):
    """A desktop workflow tried to exceed owner-controlled permissions."""


def _review_digest(row: dict) -> str:
    """Pin owner approval to all displayed record content and provenance."""
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode('utf-8')).hexdigest()


def _validate_session(session: str, mode: str) -> None:
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        raise DesktopError('Session key must have 1–64 letters, numbers, dots, dashes or underscores')
    if mode not in ('agent', 'twin'):
        raise DesktopError('Mode must be Agent or Twin')


class DesktopService:
    """Small UI-independent facade; every operation has its own SQLite handle.

    Creating/closing DB handles inside each method prevents sharing SQLite
    connections between Tk's main thread and Ollama inference workers.
    """
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home is not None else None

    def history(self, session: str, mode: str, *, limit: int = 40) -> list[dict]:
        _validate_session(session, mode)
        if not 1 <= limit <= 100:
            raise DesktopError('History limit must be 1..100')
        store = ExperienceStore(self.home)
        try:
            return store.conversation(session, mode, limit=limit)
        finally:
            store.close()

    def sessions(self, *, limit: int = 100) -> list[dict]:
        """Owner-only metadata for recent chat sessions, without message text."""
        if type(limit) is not int or not 1 <= limit <= 200:
            raise DesktopError('Choose a session list limit of 1–200')
        store = ExperienceStore(self.home)
        try:
            rows = store.db.execute(
                "SELECT session,mode,COUNT(*) AS messages,MAX(id) AS latest_id "
                "FROM messages WHERE mode IN ('twin','agent') "
                "GROUP BY session,mode ORDER BY latest_id DESC LIMIT ?",
                (limit,)).fetchall()
            return [
                {'session': row['session'], 'mode': row['mode'],
                 'messages': int(row['messages']), 'latest_id': int(row['latest_id'])}
                for row in rows
            ]
        finally:
            store.close()

    @staticmethod
    def _session_snapshot(store: ExperienceStore, session: str,
                          mode: str) -> dict:
        """Pin ALL message content and provenance without exposing it in digest.

        Limit deletion reviews to a bounded number of messages; large
        histories require explicit CLI/manual data handling, not an
        unbounded in-memory GUI query.
        """
        _validate_session(session, mode)
        rows = store.db.execute(
            "SELECT id,role,content,created_at FROM messages "
            "WHERE session=? AND mode=? ORDER BY id LIMIT 5001",
            (session, mode)).fetchall()
        if not rows:
            raise DesktopError('Selected chat no longer exists')
        if len(rows) > 5000:
            raise DesktopError('Session is too large for desktop deletion review')
        hash_ = hashlib.sha256()
        hash_.update(json.dumps(
            ['athenz-session-review-v1', session, mode],
            ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        for row in rows:
            hash_.update(json.dumps(
                [row['id'], row['role'], row['content'], row['created_at']],
                ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        return {
            'session': session,
            'mode': mode,
            'messages': len(rows),
            'latest_id': int(rows[-1]['id']),
            'recent_excerpts': [
                {'role': row['role'], 'excerpt': row['content'][:240]}
                for row in rows[-8:]
            ],
            'review_sha256': hash_.hexdigest(),
        }

    def session_review(self, session: str, mode: str) -> dict:
        """Read-only owner review. No model, network or background work."""
        _validate_session(session, mode)
        store = ExperienceStore(self.home)
        try:
            return self._session_snapshot(store, session, mode)
        finally:
            store.close()

    def delete_mode_history(self, session: str, mode: str, *,
                            review_sha256: str, confirmed: bool = False) -> dict:
        """Delete only one mode after a fresh full-history fingerprint check.

        The write lock covers the recheck and cascaded deletion, preventing
        concurrent AthenZ session writes from being silently deleted.
        """
        _validate_session(session, mode)
        if (confirmed is not True or type(review_sha256) is not str
                or re.fullmatch('[a-f0-9]{64}', review_sha256) is None):
            raise DesktopError('Review this entire chat and explicitly confirm deletion')
        store = ExperienceStore(self.home)
        try:
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                current = self._session_snapshot(store, session, mode)
                if current['review_sha256'] != review_sha256:
                    raise DesktopError('Chat changed since inspection; review it again')
                deleted = store.delete_mode_session(session, mode)
                if deleted != current['messages']:
                    raise DesktopError('Chat changed during deletion; no messages removed')
            return {'session': session, 'mode': mode,
                    'messages_deleted': deleted,
                    'linked_memories_revoked': True,
                    'other_mode_unchanged': True}
        finally:
            store.close()

    def send(self, session: str, mode: str, prompt: str, *, model: str | None = None,
             cancel_gate: ReplyCancelGate | None = None) -> dict:
        """Synchronous worker-thread operation; only successful replies persist.

        This method never calls GUI functions. The routed tag is revalidated
        after inference to reject stale model selections during a slow reply.
        """
        _validate_session(session, mode)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise DesktopError('Enter a prompt of 1–4000 characters')
        if cancel_gate is not None:
            cancel_gate.checkpoint()
        store = ExperienceStore(self.home)
        try:
            chosen = checked_active_tag(store) if model is None else None
            local = OllamaClient(model=model or chosen)
            recent = store.conversation(session, mode, limit=10)
            snapshot = context_snapshot(
                store, prompt.strip(), mode, recent, session)[0]
            reply = answer(
                store, local, prompt.strip(), mode, recent, session)
            if model is None and checked_active_tag(store) != chosen:
                raise DesktopError('Selected model changed during inference; reply discarded')
            if not isinstance(reply, str) or not reply.strip():
                raise DesktopError('Local model returned no usable reply')
            # Commit both messages together; a failed response never writes a
            # partial conversation. All parameters are bound SQL values.
            from .store import utc_now
            from contextlib import nullcontext
            # Cancellation and the entire SQLite turn commit share one lock;
            # no partial conversation turn can be left behind.
            guard = cancel_gate.commit_guard() if cancel_gate is not None else nullcontext()
            with guard:
                with store.db:
                    store.db.execute("BEGIN IMMEDIATE")
                    if (store.conversation(session, mode, limit=10) != recent
                            or context_snapshot(
                                store, prompt.strip(), mode, recent, session)[0] != snapshot):
                        raise DesktopError(
                            'Approved context or session changed; reply discarded')
                    if model is None and checked_active_tag(store) != chosen:
                        raise DesktopError(
                            'Selected model changed during inference; reply discarded')
                    store.db.execute('''INSERT INTO messages(session,mode,role,content,created_at)
                                    VALUES (?,?,?,?,?)''',
                                     (session, mode, 'user', prompt.strip(), utc_now()))
                    saved = store.db.execute('''INSERT INTO messages(session,mode,role,content,created_at)
                                            VALUES (?,?,?,?,?)''',
                                             (session, mode, 'assistant', reply, utc_now()))
            return {'reply': reply, 'reply_id': int(saved.lastrowid), 'model': local.model,
                    'session': session, 'mode': mode}
        finally:
            store.close()

    def pending(self, *, limit: int = 200) -> list[dict]:
        if not 1 <= limit <= 300:
            raise DesktopError('Pending limit must be 1..300')
        store = ExperienceStore(self.home)
        try:
            result = []
            for table in PENDING_TABLES:
                rows = store.list_items(table, 'pending', limit)
                for item in rows:
                    preview = (item.get('text') or item.get('topic') or
                               item.get('scenario') or item.get('instruction') or
                               item.get('lesson') or '')
                    result.append({'table': table, 'id': int(item['id']),
                                   'preview': str(preview)[:180]})
                    if len(result) >= limit:
                        return result
            return result
        finally:
            store.close()

    def review_detail(self, table: str, item_id: int) -> dict:
        # Present the ENTIRE reviewed item, rather than approving a truncated preview.
        if table not in PENDING_TABLES or not isinstance(item_id, int) or item_id <= 0:
            raise DesktopError('Invalid pending review selection')
        store = ExperienceStore(self.home)
        try:
            row = store.db.execute('SELECT * FROM '+table+' WHERE id=?', (item_id,)).fetchone()
            if row is None or row['status'] != 'pending':
                raise DesktopError('Review record is no longer pending')
            result = dict(row)
            result['review_sha256'] = _review_digest(result)
            return result
        finally:
            store.close()

    def memory_consistency_audit(self, *, limit: int = 80) -> dict:
        """Manual read-only review hints, never auto-reject or publish data."""
        from .memory_consistency import audit_approved_memories
        store = ExperienceStore(self.home)
        try:
            return audit_approved_memories(store, limit=limit)
        finally:
            store.close()

    def approved_memories(self, *, limit: int = 100) -> list[dict]:
        """Private, bounded owner-management view; never exposes pending claims as facts."""
        if type(limit) is not int or not 1 <= limit <= 200:
            raise DesktopError('Choose an approved-memory list limit of 1–200')
        store = ExperienceStore(self.home)
        try:
            return [
                {'id': int(r['id']), 'kind': r['kind'],
                 'preview': r['text'][:180], 'source': r['source']}
                for r in store.db.execute(
                    "SELECT id,kind,text,source FROM identity WHERE status='approved' "
                    "ORDER BY updated_at DESC,id DESC LIMIT ?", (limit,))
            ]
        finally:
            store.close()

    def approved_memory_detail(self, memory_id: int) -> dict:
        """Read complete approved identity metadata for exact owner review."""
        if type(memory_id) is not int or memory_id <= 0:
            raise DesktopError('Choose a valid approved memory')
        store = ExperienceStore(self.home)
        try:
            record = store.db.execute(
                "SELECT * FROM identity WHERE id=? AND status='approved'",
                (memory_id,)).fetchone()
            if record is None:
                raise DesktopError('Approved memory no longer exists')
            detail = dict(record)
            detail['review_sha256'] = _review_digest(detail)
            return detail
        finally:
            store.close()

    def manage_approved_memory(self, memory_id: int, action: str, *,
                               review_sha256: str, confirmed: bool = False,
                               new_text: str = '', reason: str = '') -> dict:
        """Revise, revoke, or forget exactly the entire owner-reviewed record.

        A correction returns to pending and cannot enter the Twin prompt until
        a separate approval. Revocation is reversible but excludes the memory
        from prompts; forgetting deletes it and any identity revision history
        from the live SQLite database.
        """
        if (type(memory_id) is not int or memory_id <= 0
                or action not in ('revise', 'revoke', 'forget')
                or confirmed is not True
                or not isinstance(review_sha256, str)
                or not re.fullmatch('[a-f0-9]{64}', review_sha256)):
            raise DesktopError('Inspect the approved record and explicitly confirm an action')
        if action == 'revise' and (
                type(new_text) is not str or not new_text.strip()
                or len(new_text) > 1200 or type(reason) is not str
                or not reason.strip() or len(reason) > 500):
            raise DesktopError('Correction and reason must be provided (1200/500 characters max)')
        store = ExperienceStore(self.home)
        try:
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute(
                    "SELECT * FROM identity WHERE id=? AND status='approved'",
                    (memory_id,)).fetchone()
                if row is None or _review_digest(dict(row)) != review_sha256:
                    raise DesktopError('Memory changed after inspection; review the full record again')
                if action == 'revise':
                    if new_text.strip() == row['text']:
                        raise DesktopError('A correction must change the memory')
                    store.revise(memory_id, new_text, reason)
                    outcome = 'pending-review'
                elif action == 'revoke':
                    store.status(memory_id, 'rejected')
                    outcome = 'revoked'
                else:
                    store.delete('identity', memory_id)
                    outcome = 'forgotten-from-live-database'
            return {'id': memory_id, 'result': outcome}
        finally:
            store.close()

    def memory_source_preview(self, session: str, mode: str, message_id: int) -> dict:
        """Inspect the full owner-authored message under this session/mode."""
        _validate_session(session, mode)
        store = ExperienceStore(self.home)
        try:
            row = store.memory_source_preview(message_id)
            if row["session"] != session or row["mode"] != mode:
                raise DesktopError("Source does not belong to this chat session")
            return row
        finally:
            store.close()

    def propose_message_memory(self, session: str, mode: str, message_id: int,
                               kind: str, summary: str, *, review_sha256: str,
                               confirmed: bool = False) -> int:
        """Stage an owner-written memory as pending, never auto-approve."""
        _validate_session(session, mode)
        store = ExperienceStore(self.home)
        try:
            try:
                return store.propose_message_memory(
                    message_id, kind, summary, review_sha256=review_sha256,
                    confirmed=confirmed, expected_session=session, expected_mode=mode)
            except ValueError:
                raise DesktopError(
                    'Memory source, summary or owner review changed; inspect again') from None
        finally:
            store.close()

    def feedback(self, session: str, mode: str, message_id: int, rating: str,
                 correction: str = '') -> dict:
        # Only a reply from this same local session/mode can be rated.
        _validate_session(session, mode)
        if rating not in ('up', 'down') or not isinstance(message_id, int) or message_id <= 0:
            raise DesktopError('Select a stored assistant reply and rating')
        if len(correction) > 4000:
            raise DesktopError('Correction must contain no more than 4000 characters')
        store = ExperienceStore(self.home)
        try:
            row = store.db.execute("SELECT id FROM messages WHERE id=? AND session=? AND mode=? AND role='assistant'",
                                   (message_id, session, mode)).fetchone()
            if row is None:
                raise DesktopError('Reply does not exist in this session and mode')
            feedback_id = store.add_feedback(message_id, rating, correction)
            return {'feedback_id': feedback_id, 'training': 'pending-owner-review'}
        finally:
            store.close()

    def review(self, table: str, item_id: int, state: str, *,
               review_sha256: str | None = None) -> bool:
        """Approve ONLY the full record whose bytes the owner just inspected.

        BEGIN IMMEDIATE protects the recheck-and-review transaction against a
        concurrent UI or CLI writer changing the underlying record mid-review.
        """
        if table not in PENDING_TABLES or not isinstance(item_id, int) or item_id <= 0:
            raise DesktopError('Choose a pending reviewed item')
        if state not in ('approved', 'rejected'):
            raise DesktopError('Choose an explicit approval or rejection')
        if not isinstance(review_sha256, str) or not re.fullmatch('[0-9a-f]{64}', review_sha256):
            raise DesktopError('Inspect the full record and provide its exact review digest')
        store = ExperienceStore(self.home)
        try:
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute('SELECT * FROM '+table+' WHERE id=?', (item_id,)).fetchone()
                if row is None or row['status'] != 'pending':
                    raise DesktopError('Item changed since review list loaded')
                if _review_digest(dict(row)) != review_sha256:
                    raise DesktopError('Item content or provenance changed after review; inspect again')
                if table == 'identity':
                    return store.status(item_id, state)
                if table == 'episodes':
                    return store.review_episode(item_id, state)
                if table == 'decisions':
                    return store.decision_status(item_id, state)
                return store.set_review(table, item_id, state)
        finally:
            store.close()

    def tasks(self, *, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 300:
            raise DesktopError('Task limit must be 1..300')
        store = ExperienceStore(self.home)
        try:
            return [{'task_key': r['task_key'], 'task': r['task'],
                     'status': r['status'], 'revision': int(r['revision'])}
                    for r in store.db.execute(
                        'SELECT task_key,task,status,revision FROM checkpoints '
                        'ORDER BY updated_at DESC,id DESC LIMIT ?', (limit,))]
        finally:
            store.close()


def owner_requested_readiness(*, probe_ollama: bool = False, probe_gpu: bool = False,
                              gpu_confirmed: bool = False) -> dict:
    """Never run local GPU probing from the GUI without explicit owner consent.

    Basic checks and the independent Ollama probe cannot opt into nvidia-smi.
    """
    if probe_gpu and not gpu_confirmed:
        raise DesktopError('Explicit GPU probe confirmation is required')
    from .preflight import installation_report
    return installation_report(probe_ollama=probe_ollama, probe_gpu=probe_gpu,
                               confirmed=probe_gpu and gpu_confirmed)


def bootstrap_private_home(home: Path | None = None) -> None:
    """Migrate private state BEFORE chat/review/task UI workers can race.

    SQLite migrations are forward-only and must finish serially at desktop
    startup on a fresh profile. Queue creation itself grants no permissions.
    """
    store = ExperienceStore(home)
    try:
        pass  # Opening the handle completes v1-v4 migrations.
    finally:
        store.close()
    from .scheduler import ProposalScheduler
    ProposalScheduler(home)  # Creates a paused-only queue table, no work.


def launch(home: Path | None = None, *, smoke_duration_ms: int | None = None) -> None:
    """Start a foreground Tk interface; it makes no operations on its own."""
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox, simpledialog
    except ImportError as exc:
        raise DesktopError('Tkinter is unavailable; install Tk support for Python') from exc

    bootstrap_private_home(home)
    service = DesktopService(home)
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        raise DesktopError('No graphical display is available') from exc
    if smoke_duration_ms is not None and not 100 <= smoke_duration_ms <= 5000:
        window.destroy()
        raise DesktopError('GUI smoke duration must be 100–5000 milliseconds')
    window.title('AthenZ — Local AI')
    window.minsize(820, 540)
    window.geometry('1040x690')
    style = ttk.Style(window)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    status = tk.StringVar(value='Local only · No background actions')
    book = ttk.Notebook(window)
    book.pack(fill='both', expand=True, padx=12, pady=(12, 4))
    chat_tab, review_tab, tasks_tab, setup_tab = (ttk.Frame(book, padding=12) for _ in range(4))
    book.add(chat_tab, text='Chat')
    book.add(review_tab, text='Review memory')
    book.add(tasks_tab, text='Coding tasks')
    book.add(setup_tab, text='Setup')

    chat_controls = ttk.Frame(chat_tab)
    chat_controls.pack(fill='x')
    ttk.Label(chat_controls, text='Mode').pack(side='left', padx=(0, 6))
    mode = tk.StringVar(value='agent')
    modes = ttk.Combobox(chat_controls, values=('agent', 'twin'), width=9,
                         state='readonly', textvariable=mode)
    modes.pack(side='left', padx=(0, 12))
    ttk.Label(chat_controls, text='Session').pack(side='left', padx=(0, 6))
    session = tk.StringVar(value='desktop')
    session_box = ttk.Entry(chat_controls, textvariable=session, width=24)
    session_box.pack(side='left', padx=(0, 8))
    sessions_button = ttk.Button(chat_controls, text='Browse sessions…')
    sessions_button.pack(side='left')
    transcript_frame = ttk.Frame(chat_tab)
    transcript_frame.pack(fill='both', expand=True, pady=8)
    transcript = tk.Text(transcript_frame, wrap='word', state='disabled', padx=10, pady=10)
    transcript.pack(side='left', fill='both', expand=True)
    transcript_scroll = ttk.Scrollbar(transcript_frame, orient='vertical', command=transcript.yview)
    transcript_scroll.pack(side='right', fill='y')
    transcript.configure(yscrollcommand=transcript_scroll.set)
    send_row = ttk.Frame(chat_tab)
    send_row.pack(fill='x')
    prompt = ttk.Entry(send_row)
    prompt.pack(side='left', fill='x', expand=True, padx=(0, 8))
    send_button = ttk.Button(send_row, text='Send')
    send_button.pack(side='left')
    cancel_button = ttk.Button(send_row, text='Cancel reply', state='disabled')
    cancel_button.pack(side='left', padx=(6, 0))
    response_queue: queue.Queue = queue.Queue()
    active = {'pending': False, 'gate': None, 'sent_prompt': None}

    def set_status(message: str) -> None:
        status.set(message)

    def set_transcript(rows: list[dict]) -> None:
        transcript.config(state='normal')
        transcript.delete('1.0', 'end')
        for row in rows:
            title = 'You' if row['role'] == 'user' else 'AthenZ'
            transcript.insert('end', f"{title}: {row['content']}\n\n")
        transcript.see('end')
        transcript.config(state='disabled')

    def refresh_history(*_) -> None:
        if active['pending']:
            return
        try:
            set_transcript(service.history(session.get(), mode.get()))
            set_status('Chat ready · Ollama uses local loopback only')
        except Exception as exc:
            set_status(str(exc))

    def browse_sessions() -> None:
        """Owner-initiated session switch/review/deletion, without inference."""
        if active['pending']:
            set_status('Finish or cancel the active reply before managing sessions')
            return
        popup = tk.Toplevel(window)
        popup.title('Your local Twin and Agent sessions')
        popup.geometry('750x480')
        popup.transient(window)
        ttk.Label(popup, text=(
            'Select a chat to open it or review deletion. '
            'Deleting one mode does NOT remove the same name in the other mode.'),
            padding=12).pack(anchor='w')
        tree = ttk.Treeview(popup, columns=('session', 'mode', 'messages'),
                            show='headings', selectmode='browse')
        for col, width in (('session', 420), ('mode', 100), ('messages', 110)):
            tree.heading(col, text=col.title())
            tree.column(col, width=width, stretch=col == 'session')
        tree.pack(fill='both', expand=True, padx=12, pady=8)
        indexed = {}

        def reload_sessions() -> None:
            try:
                tree.delete(*tree.get_children())
                indexed.clear()
                for i, item in enumerate(service.sessions()):
                    key = str(i)
                    indexed[key] = item
                    tree.insert('', 'end', iid=key,
                                values=(item['session'], item['mode'],
                                        item['messages']))
            except Exception:
                messagebox.showerror('Session list unavailable',
                                     'Could not inspect local session metadata.',
                                     parent=popup)

        def chosen() -> dict | None:
            selected = tree.selection()
            if not selected:
                messagebox.showinfo('Select a chat',
                                    'Choose one existing session first.',
                                    parent=popup)
                return None
            return indexed.get(selected[0])

        def open_selected() -> None:
            if active['pending']:
                messagebox.showerror('Chat busy',
                                     'Finish or cancel the active reply first.',
                                     parent=popup)
                return
            row = chosen()
            if row is None:
                return
            session.set(row['session'])
            mode.set(row['mode'])
            popup.destroy()
            refresh_history()

        def review_delete() -> None:
            if active['pending']:
                messagebox.showerror('Chat busy',
                                     'Finish or cancel the active reply first.',
                                     parent=popup)
                return
            row = chosen()
            if row is None:
                return
            try:
                snapshot = service.session_review(row['session'], row['mode'])
            except Exception:
                messagebox.showerror('Chat changed',
                                     'Could not review that chat. Refresh sessions.',
                                     parent=popup)
                reload_sessions()
                return
            review = tk.Toplevel(popup)
            review.title('Review chat deletion')
            review.geometry('700x500')
            review.transient(popup)
            ttk.Label(review, text=(
                f"Delete {snapshot['messages']} messages in "
                f"{snapshot['session']} / {snapshot['mode']} only?"),
                padding=12).pack(anchor='w')
            ttk.Label(review, text=(
                'Recent excerpts only; the deletion fingerprint covers ALL '
                'messages. Derived memories, feedback and training examples '
                'linked to deleted messages are also removed. Backups remain.'),
                wraplength=660, padding=(12, 4)).pack(anchor='w')
            preview = tk.Text(review, wrap='word', height=12)
            preview.pack(fill='both', expand=True, padx=12, pady=(8, 12))
            for message in snapshot['recent_excerpts']:
                preview.insert('end', message['role'].title() + ': ' +
                               message['excerpt'] + '\n\n')
            preview.config(state='disabled')
            controls = ttk.Frame(review, padding=12)
            controls.pack(fill='x')

            def delete_reviewed() -> None:
                if active['pending']:
                    messagebox.showerror('Chat busy',
                                         'Finish or cancel the active reply first.',
                                         parent=review)
                    return
                if not messagebox.askyesno(
                        'Confirm permanent local deletion',
                        'Delete this mode-specific chat and memories derived '
                        'from its messages from the LIVE private database? '
                        'Offline backups are not erased.',
                        parent=review):
                    return
                try:
                    result = service.delete_mode_history(
                        snapshot['session'], snapshot['mode'],
                        review_sha256=snapshot['review_sha256'],
                        confirmed=True)
                except Exception:
                    messagebox.showerror('Deletion refused',
                                         'Chat changed or could not be removed. '
                                         'Review the current chat again.',
                                         parent=review)
                    reload_sessions()
                    return
                review.destroy()
                reload_sessions()
                if ((session.get(), mode.get()) ==
                        (snapshot['session'], snapshot['mode'])):
                    refresh_history()
                reload_reviews()
                set_status(f"Removed {result['messages_deleted']} "
                           "reviewed messages from the selected mode")

            ttk.Button(controls, text='Cancel',
                       command=review.destroy).pack(side='right', padx=4)
            ttk.Button(controls, text='Delete reviewed mode',
                       command=delete_reviewed).pack(side='right', padx=4)

        bar = ttk.Frame(popup, padding=12)
        bar.pack(fill='x')
        ttk.Button(bar, text='Close',
                   command=popup.destroy).pack(side='right')
        ttk.Button(bar, text='Review deletion…',
                   command=review_delete).pack(side='right', padx=6)
        ttk.Button(bar, text='Open selected',
                   command=open_selected).pack(side='right', padx=6)
        ttk.Button(bar, text='Refresh', command=reload_sessions).pack(
            side='right', padx=6)
        tree.bind('<Double-1>', lambda _: open_selected())
        reload_sessions()

    sessions_button.config(command=browse_sessions)
    modes.bind('<<ComboboxSelected>>', refresh_history)
    session_box.bind('<Return>', refresh_history)

    def send(*_) -> None:
        if active['pending']:
            return
        user_text = prompt.get()
        chosen_session, chosen_mode = session.get(), mode.get()
        try:
            _validate_session(chosen_session, chosen_mode)
            if not user_text.strip() or len(user_text) > 4000:
                raise DesktopError('Enter a message of 1–4000 characters')
        except DesktopError as exc:
            messagebox.showerror('Cannot send', str(exc))
            return
        gate = ReplyCancelGate()
        active.update(pending=True, gate=gate, sent_prompt=user_text)
        send_button.config(state='disabled')
        cancel_button.config(state='normal')
        set_status('Generating locally…')
        def do_inference() -> None:
            try:
                outcome = service.send(chosen_session, chosen_mode, user_text, cancel_gate=gate)
                response_queue.put(('ok', outcome))
            except ReplyCancelled:
                response_queue.put(('cancelled', None))
            except Exception as exc:
                response_queue.put(('error', str(exc)))
        threading.Thread(target=do_inference, name='athenz-local-inference', daemon=True).start()

    def cancel_reply() -> None:
        gate = active['gate']
        if active['pending'] and gate is not None:
            requested = gate.request_cancel()
            cancel_button.config(state='disabled')
            if requested:
                set_status('Reply discard requested; waiting for the local model call to finish')
            else:
                set_status('Reply already committed; cancellation was too late')

    cancel_button.config(command=cancel_reply)

    def drain() -> None:
        try:
            while True:
                state, value = response_queue.get_nowait()
                sent_prompt = active['sent_prompt']
                active.update(pending=False, gate=None, sent_prompt=None)
                send_button.config(state='normal')
                cancel_button.config(state='disabled')
                if state == 'cancelled':
                    set_status('Reply discarded; no new conversation messages stored')
                elif state == 'error':
                    set_status('Local inference failed')
                    messagebox.showerror('AthenZ', value)
                else:
                    if prompt.get() == sent_prompt:
                        prompt.delete(0, 'end')
                    if (value['session'], value['mode']) == (session.get(), mode.get()):
                        refresh_history()
                    set_status(f"Reply #{value['reply_id']} from {value['model']}; feedback requires review")
        except queue.Empty:
            pass
        window.after(100, drain)

    def rate_reply(rating: str) -> None:
        try:
            rows = service.history(session.get(), mode.get(), limit=10)
            last = next((r for r in reversed(rows) if r['role'] == 'assistant'), None)
            if last is None:
                raise DesktopError('This session has no assistant reply to rate')
            correction = ''
            if rating == 'down':
                entered = simpledialog.askstring('Correct AthenZ',
                    'What should the answer have been? Leave blank for negative feedback only.',
                    parent=window)
                if entered is None:
                    return
                correction = entered
            if not messagebox.askyesno('Confirm feedback',
                    f"Record {rating} feedback for reply #{last['id']}? Any training pair will remain pending review."):
                return
            result = service.feedback(session.get(), mode.get(), int(last['id']), rating, correction)
            set_status(f"Feedback #{result['feedback_id']} saved; training requires separate review")
            reload_reviews()
        except Exception as exc:
            messagebox.showerror('Feedback failed', str(exc))

    def remember_last_user_message() -> None:
        """Explicit visual full-source and summary review; no model extraction."""
        try:
            current_session, current_mode = session.get(), mode.get()
            rows = service.history(current_session, current_mode, limit=10)
            last = next((r for r in reversed(rows) if r['role'] == 'user'), None)
            if last is None:
                raise DesktopError('There is no owner-written message to remember')
            source = service.memory_source_preview(
                current_session, current_mode, int(last['id']))
        except Exception as exc:
            messagebox.showerror('Memory source unavailable', str(exc))
            return
        dialog = tk.Toplevel(window)
        dialog.title('Propose reviewed memory from your message')
        dialog.geometry('700x510')
        dialog.transient(window)
        ttk.Label(dialog, text='Inspect your entire original message (read-only):').pack(
            anchor='w', padx=12, pady=(12, 3))
        original = tk.Text(dialog, wrap='word', height=8, padx=8, pady=8)
        original.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        original.insert('1.0', source['content'])
        original.config(state='disabled')
        memory_controls = ttk.Frame(dialog, padding=(12, 4))
        memory_controls.pack(fill='x')
        ttk.Label(memory_controls, text='Memory type:').pack(side='left')
        memory_kind = tk.StringVar(value='preference')
        ttk.Combobox(memory_controls, textvariable=memory_kind,
                     values=('preference', 'style', 'value', 'knowledge',
                             'identity', 'skill', 'lesson'),
                     state='readonly', width=16).pack(side='left', padx=8)
        ttk.Label(dialog, text='Write your own summary (not automatically inferred):').pack(
            anchor='w', padx=12, pady=(8, 3))
        summary_field = tk.Text(dialog, wrap='word', height=5, padx=8, pady=8)
        summary_field.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        buttons = ttk.Frame(dialog, padding=12)
        buttons.pack(fill='x')

        def propose() -> None:
            summary = summary_field.get('1.0', 'end-1c').strip()
            if not summary or len(summary) > 1200:
                messagebox.showerror('Memory summary', 'Write a 1–1200 character summary.',
                                     parent=dialog)
                return
            if not messagebox.askyesno(
                    'Confirm memory proposal',
                    'Store this owner-written summary as PENDING? It will not '
                    'enter Twin memory until you separately approve it.',
                    parent=dialog):
                return
            try:
                mid = service.propose_message_memory(
                    current_session, current_mode, int(source['id']),
                    memory_kind.get(), summary,
                    review_sha256=source['review_sha256'], confirmed=True)
                dialog.destroy()
                reload_reviews()
                set_status(f'Memory #{mid} pending full review; not used by Twin yet')
            except Exception as exc:
                messagebox.showerror('Memory proposal refused', str(exc),
                                     parent=dialog)

        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right')
        ttk.Button(buttons, text='Propose pending memory', command=propose).pack(
            side='right', padx=8)

    ttk.Button(send_row, text='Good reply', command=lambda: rate_reply('up')).pack(side='left', padx=(8, 0))
    ttk.Button(send_row, text='Correct reply', command=lambda: rate_reply('down')).pack(side='left', padx=(8, 0))
    ttk.Button(send_row, text='Remember my message',
               command=remember_last_user_message).pack(side='left', padx=(8, 0))

    send_button.config(command=send)
    prompt.bind('<Return>', send)
    modes.bind('<<ComboboxSelected>>', refresh_history)
    session_box.bind('<Return>', refresh_history)
    ttk.Button(chat_controls, text='Load history', command=refresh_history).pack(side='left')

    review_toolbar = ttk.Frame(review_tab)
    review_toolbar.pack(fill='x', pady=(0, 8))
    ttk.Label(review_toolbar, text='Pending items stay private and require approval.').pack(side='left')
    review_list_frame = ttk.Frame(review_tab)
    review_list_frame.pack(fill='both', expand=True)
    review_tree = ttk.Treeview(review_list_frame, columns=('kind', 'id', 'preview'),
                               show='headings', selectmode='browse')
    for col, width in [('kind', 125), ('id', 65), ('preview', 620)]:
        review_tree.heading(col, text=col.title())
        review_tree.column(col, width=width, stretch=col=='preview')
    review_tree.pack(side='left', fill='both', expand=True)
    review_scroll = ttk.Scrollbar(review_list_frame, orient='vertical', command=review_tree.yview)
    review_scroll.pack(side='right', fill='y')
    review_tree.configure(yscrollcommand=review_scroll.set)

    def reload_reviews() -> None:
        try:
            review_tree.delete(*review_tree.get_children())
            for item in service.pending():
                review_tree.insert('', 'end', values=(item['table'], item['id'], item['preview']))
            set_status('Pending items loaded from private storage')
        except Exception as exc:
            messagebox.showerror('Review error', str(exc))

    def review_selected(state: str) -> None:
        selected = review_tree.selection()
        if not selected:
            messagebox.showinfo('Select an item', 'Select a pending item for full review first.')
            return
        table, number, _ = review_tree.item(selected[0], 'values')
        try:
            record = service.review_detail(str(table), int(number))
        except Exception as exc:
            messagebox.showerror('Review unavailable', str(exc))
            reload_reviews()
            return
        dialog = tk.Toplevel(window)
        dialog.title(f'Inspect {table} #{number}')
        dialog.geometry('700x480')
        dialog.transient(window)
        details = tk.Text(dialog, wrap='word', padx=12, pady=12)
        details.pack(fill='both', expand=True, padx=12, pady=8)
        details.insert('1.0', json.dumps(record, indent=2, ensure_ascii=False))
        details.config(state='disabled')
        controls = ttk.Frame(dialog, padding=12)
        controls.pack(fill='x')

        def decide() -> None:
            action = 'approve' if state == 'approved' else 'reject'
            if not messagebox.askyesno(f'Confirm {action}',
                    f'{action.title()} the FULL reviewed record {table} #{number}?', parent=dialog):
                return
            try:
                service.review(str(table), int(number), state,
                               review_sha256=record['review_sha256'])
                dialog.destroy()
                reload_reviews()
            except Exception as exc:
                messagebox.showerror('Review refused', str(exc), parent=dialog)

        ttk.Button(controls, text='Cancel', command=dialog.destroy).pack(side='right', padx=4)
        ttk.Button(controls, text='Confirm '+state, command=decide).pack(side='right', padx=4)

    def manage_existing_memories() -> None:
        """Owner-only list of approved records with complete read-before-edit."""
        manager = tk.Toplevel(window)
        manager.title('Manage approved memories')
        manager.geometry('790x480')
        manager.transient(window)
        ttk.Label(manager, text='Approved memories only. Corrections need separate reapproval.',
                  padding=12).pack(anchor='w')
        entries = ttk.Treeview(manager, columns=('id', 'kind', 'summary'),
                               show='headings', selectmode='browse')
        for name, width in [('id', 70), ('kind', 130), ('summary', 555)]:
            entries.heading(name, text=name.title())
            entries.column(name, width=width, stretch=name=='summary')
        entries.pack(fill='both', expand=True, padx=12, pady=8)

        def refresh() -> None:
            try:
                entries.delete(*entries.get_children())
                for memory in service.approved_memories():
                    entries.insert('', 'end', values=(
                        memory['id'], memory['kind'], memory['preview']))
            except Exception as exc:
                messagebox.showerror('Memory list unavailable', str(exc),
                                     parent=manager)

        def inspect() -> None:
            selected = entries.selection()
            if not selected:
                messagebox.showinfo('Choose a memory', 'Select an approved memory first.',
                                    parent=manager)
                return
            try:
                memory_id = int(entries.item(selected[0], 'values')[0])
                record = service.approved_memory_detail(memory_id)
            except Exception as exc:
                messagebox.showerror('Memory changed', str(exc), parent=manager)
                refresh()
                return
            details_window = tk.Toplevel(manager)
            details_window.title(f'Review memory #{memory_id}')
            details_window.geometry('760x620')
            details_window.transient(manager)
            ttk.Label(details_window,
                      text='Full current record and provenance (read-only):',
                      padding=(12, 8)).pack(anchor='w')
            full_record = tk.Text(details_window, wrap='word', height=10,
                                  padx=8, pady=8)
            full_record.pack(fill='both', expand=True, padx=12, pady=(0, 6))
            full_record.insert('1.0', json.dumps(record, indent=2, ensure_ascii=False))
            full_record.config(state='disabled')
            ttk.Label(details_window,
                      text='Correction text (only used by Stage correction):',
                      padding=(12, 4)).pack(anchor='w')
            replacement = tk.Text(details_window, wrap='word', height=4,
                                  padx=8, pady=8)
            replacement.pack(fill='both', expand=True, padx=12, pady=(0, 8))
            replacement.insert('1.0', record['text'])
            reason_row = ttk.Frame(details_window, padding=(12, 4))
            reason_row.pack(fill='x')
            ttk.Label(reason_row, text='Why this changed:').pack(side='left')
            reason_value = tk.StringVar()
            ttk.Entry(reason_row, textvariable=reason_value).pack(
                side='left', fill='x', expand=True, padx=(8, 0))
            buttons = ttk.Frame(details_window, padding=12)
            buttons.pack(fill='x')

            def take_action(action: str) -> None:
                new_text = replacement.get('1.0', 'end-1c').strip()
                reason = reason_value.get().strip()
                messages = {
                    'revise': ('Stage this correction as PENDING? The existing '
                               'approved wording stops being used immediately. '
                               'Approval must happen separately.'),
                    'revoke': ('Revoke this memory? It becomes rejected and is '
                               'excluded from future Twin prompts.'),
                    'forget': ('Forget this memory AND its revision history '
                               'from the live database? Existing backups and '
                               'the original chat source are not wiped.'),
                }
                if not messagebox.askyesno(
                        'Confirm memory action', messages[action],
                        parent=details_window):
                    return
                try:
                    result = service.manage_approved_memory(
                        memory_id, action, review_sha256=record['review_sha256'],
                        confirmed=True, new_text=new_text, reason=reason)
                    details_window.destroy()
                    refresh()
                    reload_reviews()
                    set_status(f"Memory #{memory_id}: {result['result']}")
                except Exception as exc:
                    messagebox.showerror('Memory change refused', str(exc),
                                         parent=details_window)

            ttk.Button(buttons, text='Close',
                       command=details_window.destroy).pack(side='right', padx=4)
            ttk.Button(buttons, text='Forget from DB',
                       command=lambda: take_action('forget')).pack(side='right', padx=4)
            ttk.Button(buttons, text='Revoke',
                       command=lambda: take_action('revoke')).pack(side='right', padx=4)
            ttk.Button(buttons, text='Stage correction',
                       command=lambda: take_action('revise')).pack(side='right', padx=4)

        toolbar = ttk.Frame(manager, padding=(12, 4))
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='Close', command=manager.destroy).pack(side='right')
        ttk.Button(toolbar, text='Inspect and manage selected',
                   command=inspect).pack(side='right', padx=8)
        ttk.Button(toolbar, text='Refresh', command=refresh).pack(side='right')
        refresh()

    from .memory_consistency_panel import mount_memory_consistency_button
    mount_memory_consistency_button(
        review_toolbar, window, service, set_status, manage_existing_memories)
    ttk.Button(review_toolbar, text='Manage approved',
               command=manage_existing_memories).pack(side='right', padx=4)
    ttk.Button(review_toolbar, text='Refresh', command=reload_reviews).pack(side='right', padx=4)
    ttk.Button(review_toolbar, text='Reject selected', command=lambda: review_selected('rejected')).pack(side='right', padx=4)
    ttk.Button(review_toolbar, text='Approve selected', command=lambda: review_selected('approved')).pack(side='right', padx=4)
    conflict_toolbar = ttk.Frame(review_tab)
    conflict_toolbar.pack(fill='x', pady=(0, 6))
    from .conflict_panel import mount_conflict_review_button
    mount_conflict_review_button(conflict_toolbar, window, review_tree, home, reload_reviews)

    from .desktop_tasks import DesktopTasks
    from .task_panel import mount_task_panel
    mount_task_panel(tasks_tab, window, DesktopTasks(home), set_status)

    # Static getting-started guidance; no model or hardware probing at startup.
    from .onboarding import guide_text
    # Local readiness screen; no external probes run automatically at startup.
    setup_view = ttk.Frame(setup_tab)
    setup_view.pack(fill='both', expand=True, pady=(10, 8))
    setup_text = tk.Text(setup_view, wrap='word', state='disabled', height=14,
                         padx=10, pady=10)
    setup_text.pack(side='left', fill='both', expand=True)
    setup_scroll = ttk.Scrollbar(setup_view, orient='vertical', command=setup_text.yview)
    setup_scroll.pack(side='right', fill='y')
    setup_text.configure(yscrollcommand=setup_scroll.set)
    setup_controls = ttk.Frame(setup_tab)
    setup_controls.pack(fill='x')
    setup_results: queue.Queue = queue.Queue()
    setup_busy = {'running': False}

    def show_guide() -> None:
        setup_text.config(state='normal')
        setup_text.delete('1.0', 'end')
        setup_text.insert('1.0', guide_text())
        setup_text.config(state='disabled')
        set_status('Getting started · No permissions granted and no probes run')

    def show_setup(report: dict) -> None:
        lines = ['LOCAL AthenZ READINESS (not GPU certification)', '']
        for check in report['checks']:
            lines.append(f"{'OK' if check['ok'] else 'NOT READY'}  {check['name']}: {check['note']}")
        lines.extend(['', 'Tests do not upload private content or install tools.',
                      'GPU, WSL2, Windows display scaling and model training remain unverified.'])
        setup_text.config(state='normal')
        setup_text.delete('1.0', 'end')
        setup_text.insert('1.0', '\n'.join(lines))
        setup_text.config(state='disabled')

    def refresh_setup(*, ollama: bool = False, gpu: bool = False, profile: bool = False,
                      backup_action: str | None = None,
                      smoke_model: str | None = None) -> None:
        if setup_busy['running']:
            return
        if profile and not messagebox.askyesno(
                'Allow private SQLite health inspection?',
                'Read local SQLite schema and quick-check metadata only? This does not '
                'read personal rows, send data, restore a backup or approve actions.',
                parent=window):
            return
        if gpu and not messagebox.askyesno(
                'Allow local NVIDIA VRAM check?',
                'Run read-only nvidia-smi on THIS computer to observe approximate '
                'GPU memory totals? No UUIDs, serial numbers, prompts, or model '
                'files will be collected. This does not validate CUDA or training.',
                parent=window):
            return
        if backup_action == 'create':
            if not messagebox.askyesno('Create private SQLite backup',
                    'Create a local PLAINTEXT SQLite-only backup in your private '
                    'AthenZ home? It contains personal records, is NOT encrypted, '
                    'and does NOT include models or training artifacts. No upload or restore.'):
                return
        if backup_action == 'bundle-create':
            if not messagebox.askyesno('Create unencrypted private profile bundle',
                    'Include the private SQLite database, datasets, evaluation/review artifacts, '
                    'adapter runs and model conversions in a local PLAINTEXT ZIP? The result '
                    'is NOT encrypted and can be large (up to 16 GiB). No upload or activation.'):
                return
        setup_busy['running'] = True
        for button in (setup_help, setup_basic, setup_ollama, setup_gpu,
                               setup_profile, setup_backup, setup_verify,
                               setup_bundle, setup_bundle_verify, setup_chat_smoke):
            button.config(state='disabled')
        set_status('Working locally… no automatic model or coding operations')
        def worker() -> None:
            try:
                if smoke_model is not None:
                    from .synthetic_chat_smoke import check_synthetic_chat
                    report = check_synthetic_chat(model=smoke_model, confirmed=True)
                    setup_results.put(('synthetic-chat-smoke', report))
                elif profile:
                    from .profile_setup import inspect_for_setup, format_for_setup
                    report = inspect_for_setup(home, confirmed=True)
                    setup_results.put(('profile-health', format_for_setup(report)))
                elif backup_action == 'create':
                    from .backup import create_backup
                    setup_results.put(('backup-created', create_backup(home, confirmed=True)))
                elif backup_action == 'verify':
                    from .backup import list_backups, verify_backup
                    ids = list_backups(home)
                    if not ids:
                        raise DesktopError('No local SQLite backups found')
                    setup_results.put(('backup-verified', verify_backup(home, ids[0])))
                elif backup_action == 'bundle-create':
                    from .profile_bundle import create_bundle
                    setup_results.put(('bundle-created', create_bundle(home, confirmed=True)))
                elif backup_action == 'bundle-verify':
                    from .profile_bundle import list_bundles, verify_bundle
                    ids = list_bundles(home)
                    if not ids:
                        raise DesktopError('No local profile bundles found')
                    setup_results.put(('bundle-verified', verify_bundle(home, ids[0])))
                else:
                    setup_results.put(('ok', owner_requested_readiness(probe_ollama=ollama, probe_gpu=gpu, gpu_confirmed=gpu)))
            except Exception:
                # No exception traceback or sensitive filesystem paths in UI.
                setup_results.put(('error', 'Local setup/backup operation failed; inspect private files'))
        threading.Thread(target=worker, name='athenz-local-setup', daemon=True).start()

    setup_help = ttk.Button(setup_controls, text='Getting started', command=show_guide)
    setup_help.pack(side='left', padx=(0, 8))
    setup_basic = ttk.Button(setup_controls, text='Check prerequisites',
                             command=lambda: refresh_setup())
    setup_basic.pack(side='left', padx=(0, 8))
    setup_ollama = ttk.Button(setup_controls, text='Probe Ollama (loopback only)',
                              command=lambda: refresh_setup(ollama=True))
    setup_ollama.pack(side='left')
    setup_gpu = ttk.Button(setup_controls, text='Probe NVIDIA VRAM…',
                           command=lambda: refresh_setup(gpu=True))
    setup_gpu.pack(side='left', padx=(8, 0))
    backup_controls = ttk.Frame(setup_tab)
    backup_controls.pack(fill='x', pady=(6, 0))
    setup_profile = ttk.Button(backup_controls, text='Check private SQLite health…',
                               command=lambda: refresh_setup(profile=True))
    setup_profile.pack(side='left', padx=(0, 8))
    setup_backup = ttk.Button(backup_controls, text='Back up private SQLite…',
                              command=lambda: refresh_setup(backup_action='create'))
    setup_backup.pack(side='left', padx=(8, 4))
    setup_verify = ttk.Button(backup_controls, text='Verify latest backup',
                              command=lambda: refresh_setup(backup_action='verify'))
    setup_verify.pack(side='left')
    bundle_controls = ttk.Frame(setup_tab)
    bundle_controls.pack(fill='x', pady=(6, 0))
    setup_bundle = ttk.Button(bundle_controls, text='Bundle selected private files…',
                              command=lambda: refresh_setup(backup_action='bundle-create'))
    setup_bundle.pack(side='left', padx=(0, 8))
    setup_bundle_verify = ttk.Button(bundle_controls, text='Verify latest bundle',
                                     command=lambda: refresh_setup(backup_action='bundle-verify'))
    setup_bundle_verify.pack(side='left')
    smoke_controls = ttk.Frame(setup_tab)
    smoke_controls.pack(fill='x', pady=(6, 0))

    def request_synthetic_chat_smoke() -> None:
        if setup_busy['running']:
            return
        tag = simpledialog.askstring(
            'Synthetic Twin + Agent smoke',
            'Enter an already installed local Ollama model tag '
            '(for example qwen3.5:2b). No model will be downloaded.',
            parent=window)
        if tag is None:
            return
        from .synthetic_chat_smoke import _MODEL
        if _MODEL.fullmatch(tag) is None or '://' in tag or '//' in tag:
            messagebox.showerror('Invalid model tag',
                                 'Choose a short installed local model tag.',
                                 parent=window)
            return
        if not messagebox.askyesno(
                'Authorize two synthetic Ollama replies?',
                'Run exactly one Twin and one Agent response through a '
                'disposable synthetic profile? This uses the local Ollama '
                'service and may consume compute. NO personal profile '
                'is read, no model is downloaded, and the temporary chat '
                'is deleted afterward. Not a GPU or digital-twin fidelity test.',
                parent=window):
            return
        refresh_setup(smoke_model=tag)

    setup_chat_smoke = ttk.Button(
        smoke_controls, text='Test Twin + Agent (synthetic)…',
        command=request_synthetic_chat_smoke)
    setup_chat_smoke.pack(side='left')
    ttk.Label(smoke_controls,
              text='Two authorized local model replies, no personal memory.').pack(
                  side='left', padx=(10, 0))

    ttk.Label(setup_tab, text='Ollama and GPU probes are manual and off by default; a GPU query requires confirmation.').pack(
        anchor='w', pady=(8, 0))

    show_guide()  # Display text only; do not run readiness checks.

    def drain_setup() -> None:
        try:
            while True:
                state, report = setup_results.get_nowait()
                setup_busy['running'] = False
                for button in (setup_help, setup_basic, setup_ollama, setup_gpu,
                               setup_profile, setup_backup, setup_verify,
                               setup_bundle, setup_bundle_verify, setup_chat_smoke):
                    button.config(state='normal')
                if state == 'ok':
                    show_setup(report)
                    set_status('Local readiness checked; no model or task started')
                elif state == 'backup-created':
                    set_status('Private SQLite-only plaintext backup created; verify before relying on it')
                elif state == 'backup-verified':
                    set_status('Latest private SQLite backup verified against checksum and integrity')
                elif state == 'synthetic-chat-smoke':
                    # Render only fixed observed flags. Never show model
                    # response, prompt text, path or backend exception.
                    observed = report.get('status') == 'synthetic-chat-roundtrip-observed'
                    lines = [
                        'SYNTHETIC TWIN / AGENT CHAT SMOKE',
                        '',
                        'Local synthetic round-trip: ' + ('PASS' if observed else 'NOT VERIFIED'),
                        'Twin synthetic reply: ' +
                            ('saved' if report.get('twin_reply_saved') is True else 'not verified'),
                        'Agent synthetic reply: ' +
                            ('saved' if report.get('agent_reply_saved') is True else 'not verified'),
                        'Mode separation: ' +
                            ('verified' if report.get('mode_isolation_verified') is True else 'not verified'),
                        '',
                        'No personal owner profile or examples used.',
                        'Disposable profile only. Real Twin fidelity, GPU,',
                        'training and long-term adaptation remain unverified.',
                    ]
                    setup_text.config(state='normal')
                    setup_text.delete('1.0', 'end')
                    setup_text.insert('1.0', '\n'.join(lines))
                    setup_text.config(state='disabled')
                    set_status('Synthetic Twin/Agent smoke ' +
                               ('passed' if observed else 'not verified'))
                elif state == 'profile-health':
                    setup_text.config(state='normal')
                    setup_text.delete('1.0', 'end')
                    setup_text.insert('1.0', report)
                    setup_text.config(state='disabled')
                    set_status('Owner-requested read-only private SQLite check complete')
                elif state == 'bundle-created':
                    set_status('Plaintext private profile bundle created; verify before relying on it')
                elif state == 'bundle-verified':
                    set_status('Latest private bundle verified; recovery requires separate CLI confirmation')
                else:
                    set_status(report)
        except queue.Empty:
            pass
        window.after(150, drain_setup)

    from .desktop_shortcuts import install_navigation
    install_navigation(window, book, (chat_tab, review_tab, tasks_tab, setup_tab),
                       (prompt, review_tree, tasks_tab, setup_basic))
    from .desktop_zoom import install_text_zoom
    install_text_zoom(window, style, notify=set_status)
    ttk.Label(window, textvariable=status, anchor='w').pack(fill='x', padx=16, pady=(0, 10))
    refresh_history()
    reload_reviews()
    window.after(100, drain)
    window.after(150, drain_setup)
    window.after_idle(prompt.focus_set)
    if smoke_duration_ms is not None:
        if len(book.tabs()) != 4:
            window.destroy()
            raise DesktopError('GUI smoke did not create the expected tabs')
        if 'Getting started with AthenZ' not in setup_text.get('1.0', 'end'):
            window.destroy()
            raise DesktopError('GUI smoke did not render offline setup guidance')
        if cancel_button.cget('text') != 'Cancel reply' or str(cancel_button.cget('state')) != 'disabled':
            window.destroy()
            raise DesktopError('GUI smoke did not start with reply cancellation disabled')
        window.after(smoke_duration_ms, window.destroy)
    def on_close() -> None:
        # Closing the UI withdraws consent to persist a reply still in flight.
        # The Ollama call itself may finish after the window disappears.
        gate = active['gate']
        if gate is not None:
            gate.request_cancel()
        window.destroy()

    window.protocol('WM_DELETE_WINDOW', on_close)
    window.mainloop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Local AthenZ desktop shell (no daemon)')
    parser.add_argument('--home', type=Path, default=None,
                        help='Private local AthenZ directory, outside Git')
    parser.add_argument('--gui-self-test', action='store_true',
                        help='Open real Tk desktop briefly using a disposable private profile')
    parser.add_argument('--self-test', action='store_true',
                        help='Offline throwaway-profile packaged-runtime smoke; do not open a window')
    args = parser.parse_args(argv)
    if args.self_test:
        from .preflight import desktop_self_test
        desktop_self_test()
        return
    if args.gui_self_test:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix='athenz-gui-smoke-') as scratch:
            launch(Path(scratch) / 'private', smoke_duration_ms=650)
        return
    launch(args.home)


if __name__ == '__main__':
    main()
