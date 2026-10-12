"""Owner-operated Tk review of competing private episodes; no automatic action.

All Tk construction is lazy. The underlying adjudicator checks the complete
review fingerprint again inside the SQLite write transaction.
"""
from __future__ import annotations

import re
from .conflict_review import ConflictReviewError, preview, adjudicate

_SHA = re.compile(r'[a-f0-9]{64}\Z')


def checked_decision(digest: str, decision: str, predecessor_text: str) -> dict:
    """Validate manual form input before any private write or confirmation."""
    if not isinstance(digest, str) or not _SHA.fullmatch(digest.strip()):
        raise ConflictReviewError('Enter the exact 64-character review SHA-256')
    if decision not in ('keep-both', 'supersede', 'reject'):
        raise ConflictReviewError('Choose a supported review decision')
    if not isinstance(predecessor_text, str):
        raise ConflictReviewError('Invalid predecessor ID')
    text = predecessor_text.strip()
    if decision == 'supersede':
        if not re.fullmatch(r'[1-9][0-9]{0,17}', text):
            raise ConflictReviewError('Enter one approved overlapping predecessor ID')
        predecessor_id = int(text)
    else:
        if text:
            raise ConflictReviewError('Clear the predecessor ID unless superseding')
        predecessor_id = None
    return {'digest': digest.strip(), 'decision': decision, 'predecessor_id': predecessor_id}


def mount_conflict_review_button(toolbar, window, tree, home, on_changed):
    """Add an explicit, private, full-record review path for pending episodes."""
    import json
    import tkinter as tk
    from tkinter import ttk, messagebox

    def open_review():
        chosen = tree.selection()
        if not chosen:
            messagebox.showinfo('Choose an episode', 'Select a pending episode first.', parent=window)
            return
        kind, selected_id, _ = tree.item(chosen[0], 'values')
        if kind != 'episodes':
            messagebox.showinfo('Choose an episode', 'Conflict review applies to pending episodes.', parent=window)
            return
        if not messagebox.askyesno('View private episode records?',
                                   'Display the full private candidate and any approved episodes with shared tags? '
                                   'Matching tags do NOT prove a contradiction. No decisions are made automatically.',
                                   parent=window):
            return
        try:
            report = preview(home, int(selected_id), confirmed=True)
        except (ConflictReviewError, ValueError):
            messagebox.showerror('Review unavailable', 'Episode changed or could not be reviewed.', parent=window)
            on_changed()
            return
        modal = tk.Toplevel(window)
        modal.title('Episode conflict review — owner confirmation required')
        modal.geometry('860x620')
        modal.transient(window)
        panel = ttk.Frame(modal, padding=12)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='Private candidate and approved topical overlaps — NOT an automatic contradiction verdict').pack(anchor='w')
        viewport = ttk.Frame(panel)
        viewport.pack(fill='both', expand=True, pady=(6, 8))
        details = tk.Text(viewport, wrap='word', padx=8, pady=8)
        details.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=details.yview)
        scrollbar.pack(side='right', fill='y')
        details.configure(yscrollcommand=scrollbar.set)
        details.insert('1.0', json.dumps(report, indent=2, ensure_ascii=False))
        details.config(state='disabled')
        ttk.Label(panel, text='After reading every record above, enter the complete review SHA-256 to approve a choice.').pack(anchor='w')
        entered_digest = ttk.Entry(panel, width=68)
        entered_digest.pack(fill='x', pady=(3, 6))
        opts = ttk.Frame(panel)
        opts.pack(fill='x')
        ttk.Label(opts, text='Decision').pack(side='left')
        selected = tk.StringVar(value='reject')
        ttk.Combobox(opts, state='readonly', textvariable=selected,
                     values=('reject', 'keep-both', 'supersede'), width=16).pack(side='left', padx=(6, 14))
        ttk.Label(opts, text='Predecessor ID (supersede only)').pack(side='left')
        old_id = ttk.Entry(opts, width=12)
        old_id.pack(side='left', padx=(6, 0))
        actions = ttk.Frame(panel)
        actions.pack(fill='x', pady=(10, 0))

        def submit():
            try:
                values = checked_decision(entered_digest.get(), selected.get(), old_id.get())
            except ConflictReviewError as exc:
                messagebox.showerror('Review input', str(exc), parent=modal)
                return
            description = ('Reject this pending episode' if values['decision'] == 'reject'
                           else 'Keep this episode and all existing approved evidence' if values['decision'] == 'keep-both'
                           else f"Approve this episode and reject predecessor #{values['predecessor_id']}")
            if not messagebox.askyesno('Confirm exact reviewed action',
                                       description + '? Changes cannot be automatically undone.', parent=modal):
                return
            try:
                adjudicate(home, int(selected_id), confirmed=True, **values)
            except ConflictReviewError:
                messagebox.showerror('Review changed',
                                     'Records changed or the selected action is invalid. Reopen the complete review.',
                                     parent=modal)
                on_changed()
                return
            modal.destroy()
            on_changed()
        ttk.Button(actions, text='Close without action', command=modal.destroy).pack(side='right', padx=(6, 0))
        ttk.Button(actions, text='Confirm reviewed decision…', command=submit).pack(side='right')

    button = ttk.Button(toolbar, text='Review episode conflicts…', command=open_review)
    button.pack(side='right', padx=(0, 6))
    return button
