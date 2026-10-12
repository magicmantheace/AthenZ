"""Tkinter supervision panel for explicitly reviewed coding tasks.

All repository work and local inference runs on foreground-requested worker
threads; callbacks deliver results to Tk on its own thread. No timer-based
job execution, automatic acceptance, Git push or silent Docker fallback.
"""
from __future__ import annotations

import json
import queue
import threading

from .desktop_tasks import DesktopTasks, TaskUIError, parse_stages


def mount_task_panel(parent, window, service: DesktopTasks, notify) -> None:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog

    ttk.Label(parent, text='Owner-supervised Git worktrees · no automatic apply, push or training').pack(
        fill='x', pady=(0, 6))
    selector = ttk.Frame(parent)
    selector.pack(fill='both', expand=True)
    tree = ttk.Treeview(selector, columns=('key', 'phase', 'revision', 'task'),
                        show='headings', selectmode='browse', height=8)
    for name, size in [('key', 155), ('phase', 100), ('revision', 75), ('task', 550)]:
        tree.heading(name, text=name.title())
        tree.column(name, width=size, stretch=name == 'task')
    tree.pack(side='left', fill='both', expand=True)
    scrollbar = ttk.Scrollbar(selector, orient='vertical', command=tree.yview)
    scrollbar.pack(side='right', fill='y')
    tree.configure(yscrollcommand=scrollbar.set)

    detail = tk.Text(parent, height=9, wrap='word', state='disabled', padx=8, pady=8)
    detail.pack(fill='both', expand=True, pady=(8, 4))
    controls = ttk.Frame(parent)
    controls.pack(fill='x')
    footer = ttk.Frame(parent)
    footer.pack(fill='x', pady=(6, 0))
    scheduler_controls = ttk.Frame(parent)
    scheduler_controls.pack(fill='x', pady=(6, 0))
    buttons = []
    replies: queue.Queue = queue.Queue()
    active = {'busy': False}

    def show_text(value: str) -> None:
        detail.configure(state='normal')
        detail.delete('1.0', 'end')
        detail.insert('1.0', value)
        detail.configure(state='disabled')

    def selected_key() -> str:
        picked = tree.selection()
        if not picked:
            raise TaskUIError('Select a local coding task first')
        return str(tree.item(picked[0], 'values')[0])

    def on_error(error: str) -> None:
        # A background task may finish while the main window is closing.
        # Never try to open a modal dialog on a destroyed Tk root.
        if not window.winfo_exists():
            return
        notify('Coding task refused; see details')
        messagebox.showerror('AthenZ task', error, parent=window)

    def run(label, operation, *, done=None) -> None:
        if active['busy']:
            notify('A task operation is already running')
            return
        active['busy'] = True
        for button in buttons:
            button.configure(state='disabled')
        notify(label + '…')

        def execute() -> None:
            try:
                replies.put(('ok', label, operation(), done))
            except Exception as exc:
                replies.put(('error', label, str(exc), None))
        threading.Thread(target=execute, name='athenz-desktop-task', daemon=True).start()

    def poll() -> None:
        if not window.winfo_exists():
            return
        try:
            while True:
                kind, label, result, callback = replies.get_nowait()
                active['busy'] = False
                for button in buttons:
                    button.configure(state='normal')
                if kind == 'error':
                    on_error(result)
                else:
                    notify(label + ' completed')
                    if callback:
                        try:
                            callback(result)
                        except Exception as exc:
                            on_error(str(exc))
        except queue.Empty:
            pass
        if window.winfo_exists():
            window.after(100, poll)

    def fill_list(items, preserve=None) -> None:
        for child in tree.get_children():
            tree.delete(child)
        chosen = None
        for item in items:
            oid = tree.insert('', 'end', values=(item['task_key'], item['status'],
                     item['revision'], item['task'][:160]))
            if item['task_key'] == preserve:
                chosen = oid
        if chosen:
            tree.selection_set(chosen)
            tree.see(chosen)

    def refresh(keep=None) -> None:
        run('Refresh tasks', service.list_tasks,
            done=lambda rows: fill_list(rows, keep))

    def show(key=None) -> None:
        try:
            key = key or selected_key()
            run('Read task', lambda: service.detail(key),
                done=lambda data: show_text(json.dumps(data, ensure_ascii=False, indent=2)))
        except Exception as exc:
            on_error(str(exc))

    def create() -> None:
        dialog = tk.Toplevel(window)
        dialog.title('Create owner-scoped coding task')
        dialog.transient(window)
        dialog.geometry('670x420')
        fields = ttk.Frame(dialog, padding=12)
        fields.pack(fill='both', expand=True)
        entries = {}
        for title, name in [('Task key', 'key'), ('Trusted clean Git repository directory', 'repo'),
                            ('Task description', 'task')]:
            ttk.Label(fields, text=title).pack(anchor='w', pady=(4, 0))
            entry = ttk.Entry(fields)
            entry.pack(fill='x')
            entries[name] = entry
        ttk.Label(fields, text='Authorized Python file stages: comma within stage; semicolon between stages').pack(
            anchor='w', pady=(10, 0))
        stage_input = ttk.Entry(fields)
        stage_input.pack(fill='x')
        ttk.Label(fields, text='Example: calc.py,tests/test_calc.py; util.py', foreground='gray').pack(anchor='w')
        ttk.Label(fields, text=('Git worktrees separate working copies but are NOT a sandbox. '
                                'Only select repositories you trust.')).pack(anchor='w', pady=(12, 0))

        def confirm() -> None:
            key, repo, task = (entries[k].get().strip() for k in ('key', 'repo', 'task'))
            try:
                stages = parse_stages(stage_input.get())
                service._key(key)
                if not repo or not task:
                    raise TaskUIError('Provide a repository and task')
            except Exception as exc:
                messagebox.showerror('Invalid task', str(exc), parent=dialog)
                return
            summary = f'Create isolated worktree for:\n{repo}\n\n{task}\n\nAllowed files: {stages}'
            if not messagebox.askyesno('Confirm explicitly scoped task', summary, parent=dialog):
                return
            dialog.destroy()
            run('Create reviewed task', lambda: service.create(key, repo, task, stages, confirmed=True),
                done=lambda _: refresh(key))

        ttk.Button(fields, text='Create worktree', command=confirm).pack(anchor='e', pady=12)
        entries['key'].focus_set()

    def review() -> None:
        try:
            key = selected_key()
        except Exception as exc:
            on_error(str(exc)); return

        def open_review(result) -> None:
            dialog = tk.Toplevel(window)
            dialog.title(f"Review stage {result['stage']} — proposal #{result['proposal_id']}")
            dialog.geometry('950x670')
            dialog.transient(window)
            ttk.Label(dialog, text='The FULL proposal follows. No change occurs until you enter its exact SHA-256.',
                      padding=8).pack(anchor='w')
            digest = result['sha256']
            ttk.Label(dialog, text='SHA-256: ' + digest, padding=(8, 0)).pack(anchor='w')
            text = tk.Text(dialog, wrap='none', padx=8, pady=8)
            text.pack(fill='both', expand=True, padx=8, pady=8)
            text.insert('1.0', result['diff'])
            text.configure(state='disabled')
            ttk.Label(dialog, text='Paste the exact SHA-256 above to authorize these replacement bytes:',
                      padding=(8, 2)).pack(anchor='w')
            entered = ttk.Entry(dialog)
            entered.pack(fill='x', padx=8)

            def apply_review() -> None:
                if entered.get().strip() != digest:
                    messagebox.showerror('Approval rejected', 'Hash must match the current proposal exactly',
                                         parent=dialog)
                    return
                if not messagebox.askyesno('Final confirmation',
                        'Apply ONLY this SHA-256-reviewed patch inside the disposable worktree?', parent=dialog):
                    return
                dialog.destroy()
                run('Apply reviewed patch', lambda: service.apply(key, digest, confirmed=True),
                    done=lambda data: (show_text(json.dumps(data, indent=2)), refresh(key)))

            ttk.Button(dialog, text='Apply exact reviewed patch', command=apply_review).pack(
                anchor='e', padx=8, pady=10)
        run('Load full patch review', lambda: service.review(key), done=open_review)

    def selected_action(name, operation, message=None, *, post=True) -> None:
        try:
            key = selected_key()
        except Exception as exc:
            on_error(str(exc)); return
        if message and not messagebox.askyesno('Confirm ' + name, message, parent=window):
            return
        run(name, lambda: operation(key), done=lambda data: (
            show_text(json.dumps(data, indent=2, ensure_ascii=False)),
            refresh(key) if post else None))

    def test() -> None:
        try:
            key = selected_key()
        except Exception as exc:
            on_error(str(exc)); return
        image = simpledialog.askstring('Trusted Docker image',
            'Enter the installed, trusted digest-pinned image (name@sha256:64hex):', parent=window)
        if image is None:
            return
        if not messagebox.askyesno('Execute tests in container',
            f'Run fixed unittest discovery inside Docker with network disabled?\nImage: {image}\n'
            'This runs project code; containers are not a perfect security boundary.', parent=window):
            return
        run('Sandbox unit tests', lambda: service.test(key, image, confirmed=True),
            done=lambda data: (show_text(json.dumps(data, indent=2)), refresh(key)))

    def cancel() -> None:
        try:
            key = selected_key()
        except Exception as exc:
            on_error(str(exc)); return
        discard = messagebox.askyesno('Discard reviewed work?',
            'Should AthenZ permanently discard changes in the isolated worktree?\n'
            'Choose No to cancel only if the worktree is clean. Choose Yes to discard edits.', parent=window)
        if not messagebox.askyesno('Confirm task cancellation',
            f"Cancel task '{key}'?" + (' This will DISCARD its isolated edits.' if discard else
                                       ' Dirty worktrees will be preserved and cancellation refused.'),
            parent=window):
            return
        run('Cancel task', lambda: service.cancel(key, discard_changes=discard, confirmed=True),
            done=lambda data: (show_text(json.dumps(data, indent=2)), refresh()))

    def button(label, action, *, secondary=False, scheduled=False):
        destination = scheduler_controls if scheduled else (footer if secondary else controls)
        control = ttk.Button(destination, text=label, command=action)
        control.pack(side='left', padx=(0, 6), pady=2)
        buttons.append(control)

    button('New scoped task', create)
    button('Refresh', lambda: refresh())
    button('Details', show)
    button('Prepare proposed patch', lambda: selected_action(
        'Prepare model proposal', lambda key: service.prepare(key)))
    button('Review / approve patch', review)
    button('Syntax check', lambda: selected_action('Syntax check', service.syntax), secondary=True)
    button('Advance stage', lambda: selected_action('Advance stage',
        lambda key: service.advance(key, confirmed=True),
        'Accept the current syntax-validated stage? This is not behavioral verification.'), secondary=True)
    button('Recover checkpoint', lambda: selected_action('Recover checkpoint', service.recover), secondary=True)
    button('Container test', test, secondary=True)
    button('Export private patch', lambda: selected_action('Export private patch',
        lambda key: service.export(key, confirmed=True),
        'Write the immutable combined review patch to your private AthenZ directory?'), secondary=True)
    button('Cancel / discard', cancel, secondary=True)
    # These controls deliberately do not run automatically when the desktop
    # launches. A scheduled proposal still requires normal SHA-256 review.
    def queue_proposal() -> None:
        try:
            key = selected_key()
        except Exception as exc:
            on_error(str(exc)); return
        model = simpledialog.askstring('Local proposal model',
            'Explicit Ollama model tag for this task (local only):',
            initialvalue='qwen3.5:2b', parent=window)
        if model is None:
            return
        if not messagebox.askyesno('Create PAUSED proposal queue',
            f'Queue task {key} with model {model}?\n'
            'The queue starts PAUSED. No patch will be applied automatically.', parent=window):
            return
        run('Queue proposal', lambda: service.schedule_add(key, model, confirmed=True),
            done=lambda data: (show_text(json.dumps(data, indent=2)), refresh(key)))

    button('Queue (paused)', queue_proposal, scheduled=True)
    button('Arm next stage', lambda: selected_action('Arm next proposal',
        lambda key: service.schedule_arm(key, confirmed=True),
        'Authorize ONE new local model proposal for the selected ready stage?\n'
        'No patch will be applied without your review.'), scheduled=True)
    button('Pause queue', lambda: selected_action('Pause scheduled proposal',
        service.schedule_pause, 'Pause this proposal queue? In-flight inference may finish.'), scheduled=True)
    button('Run queued once', lambda: (
        run('Run one queued proposal', lambda: service.schedule_tick(confirmed=True),
            done=lambda data: (show_text(json.dumps(data, ensure_ascii=False, indent=2)), refresh()))
        if messagebox.askyesno('Run one proposal',
            'Prepare at most ONE owner-armed proposal using local Ollama?\n'
            'This does not approve or apply code.', parent=window) else None), scheduled=True)
    button('Remove queue', lambda: selected_action('Remove paused proposal queue',
        lambda key: service.schedule_remove(key, confirmed=True),
        'Delete this PAUSED queue entry? Existing worktrees and proposals are retained.'), scheduled=True)
    button('Recover stopped job', lambda: selected_action('Reconcile stopped scheduler',
        lambda key: service.schedule_recover(key, confirmed=True),
        'ONLY continue if no other scheduler process is still generating this proposal.\n'
        'Reconcile the interrupted lease without automatically rerunning inference?'), scheduled=True)
    tree.bind('<Double-1>', lambda _: show())
    # Polling drives only UI delivery; it never schedules coding or model work.
    window.after(100, poll)
    refresh()
