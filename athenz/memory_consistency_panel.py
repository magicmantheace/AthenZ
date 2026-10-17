"""Owner-initiated, read-only memory consistency audit desktop panel."""
from __future__ import annotations

import json


def mount_memory_consistency_button(toolbar, window, service, set_status, manage_memories):
    """No audit/model/file activity at startup. Everything follows a click."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    def open_audit():
        try:
            audit = service.memory_consistency_audit()
        except Exception:
            messagebox.showerror(
                "Memory audit unavailable",
                "Could not complete a bounded approved-memory audit.",
                parent=window)
            return
        panel = tk.Toplevel(window)
        panel.title("Potential memory duplicates / conflicts")
        panel.geometry("750x510")
        panel.transient(window)
        intro = (
            f"Reviewed {audit['approved_records_scanned']} approved memories. "
            f"Possible matches: {sum(audit['candidate_counts'].values())}. "
            "A result is NOT proof that either memory is wrong. "
            "No approvals or records were changed."
        )
        ttk.Label(panel, text=intro, wraplength=715,
                  padding=12).pack(anchor="w")
        ttk.Label(panel,
                  text="Only exact normalized duplicates and simple 'I prefer' / "
                       "'I do not prefer' statements are detected. Other "
                       "contradictions may be missed.",
                  wraplength=715, padding=(12, 0)).pack(anchor="w")
        tree = ttk.Treeview(
            panel, columns=("kind", "first", "second"),
            show="headings", selectmode="browse")
        for col, width in (("kind", 400), ("first", 120), ("second", 120)):
            tree.heading(col, text=col.title())
            tree.column(col, width=width, stretch=col == "kind")
        tree.pack(fill="both", expand=True, padx=12, pady=10)
        indexed = {}
        for index, item in enumerate(audit["candidates"]):
            key = str(index)
            indexed[key] = item
            tree.insert("", "end", iid=key,
                        values=(item["kind"], item["first_id"], item["second_id"]))
        ttk.Label(
            panel,
            text=f"{audit['additional_candidates_not_shown']} additional "
                 "candidates not shown. Audit results can become stale; "
                 "reinspect the actual approved record before changing it.",
            wraplength=715, padding=(12, 0)).pack(anchor="w")

        def inspect():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("Select a pair",
                                    "Choose one candidate pair first.", parent=panel)
                return
            match = indexed.get(selection[0])
            if match is None:
                return
            try:
                first = service.approved_memory_detail(match["first_id"])
                second = service.approved_memory_detail(match["second_id"])
            except Exception:
                messagebox.showerror(
                    "Candidate has changed",
                    "One of these memories is no longer approved. Run a fresh audit.",
                    parent=panel)
                return
            detail = tk.Toplevel(panel)
            detail.title("Inspect both full approved records")
            detail.geometry("760x540")
            detail.transient(panel)
            ttk.Label(detail,
                      text="Read-only comparison. Resolve through Manage approved "
                           "after checking source and provenance.",
                      wraplength=730, padding=12).pack(anchor="w")
            text_area = tk.Text(detail, wrap="word")
            text_area.pack(fill="both", expand=True, padx=12, pady=8)
            text_area.insert("end", "FIRST MEMORY\n" +
                             json.dumps(first, indent=2, ensure_ascii=False) +
                             "\n\nSECOND MEMORY\n" +
                             json.dumps(second, indent=2, ensure_ascii=False))
            text_area.config(state="disabled")
            controls = ttk.Frame(detail, padding=12)
            controls.pack(fill="x")
            ttk.Button(controls, text="Close", command=detail.destroy).pack(
                side="right")
            ttk.Button(
                controls, text="Manage approved…",
                command=manage_memories).pack(side="right", padx=8)

        bar = ttk.Frame(panel, padding=12)
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=panel.destroy).pack(side="right")
        ttk.Button(bar, text="Inspect selected pair",
                   command=inspect).pack(side="right", padx=8)
        set_status("Memory consistency hints generated locally; no records changed")

    button = ttk.Button(toolbar, text="Find possible duplicates…",
                        command=open_audit)
    button.pack(side="right", padx=4)
    return button
