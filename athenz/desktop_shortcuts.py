"""Keyboard navigation for the foreground desktop, without action permissions.

Shortcuts move focus only. They never confirm reviews, arm tasks, publish, or
send a message; sensitive operations keep their own explicit confirmations.
"""
from __future__ import annotations


def install_navigation(root, notebook, tabs, focus_targets) -> None:
    """Set Ctrl+1..4 tab/focus shortcuts and Ctrl+L to focus chat input.

    Pure widget-wiring routine so keyboard behavior can be verified without
    initializing Tcl/Tk or reading private profile data.
    """
    if len(tabs) != 4 or len(focus_targets) != 4:
        raise ValueError('AthenZ navigation needs the four desktop tabs and focus targets')

    def choose(index):
        def handler(_event):
            notebook.select(tabs[index])
            focus_targets[index].focus_set()
            return 'break'
        return handler

    for number in range(1, 5):
        root.bind(f'<Control-Key-{number}>', choose(number - 1), add='+')
    root.bind('<Control-Key-l>', choose(0), add='+')
    # Tk's built-in notebook traversal supports Ctrl+Tab and Ctrl+Shift+Tab.
    notebook.enable_traversal()
