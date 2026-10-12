"""Session-only desktop font scaling; never changes user data or authorizations.

Tk named fonts power the local GUI. Font zoom is deliberately transient: it
does not save settings, run commands, or approve memory and coding tasks.
"""
from __future__ import annotations

ZOOM_LEVELS = (80, 90, 100, 110, 125, 150, 175, 200)
FONT_NAMES = ('TkDefaultFont', 'TkTextFont', 'TkHeadingFont', 'TkFixedFont',
              'TkMenuFont', 'TkCaptionFont', 'TkSmallCaptionFont')


def install_text_zoom(root, style, *, notify=None, fonts=None):
    """Ctrl+Plus/Equals, Ctrl+Minus and Ctrl+0 zoom common Tk fonts.

    A font map may be supplied for displayless tests; Tk itself is not imported
    until this installer runs in an already-created desktop window.
    """
    if fonts is None:
        from tkinter import font as tkfont
        fonts = {}
        for name in FONT_NAMES:
            try:
                fonts[name] = tkfont.nametofont(name, root=root)
            except Exception:
                # Some minimal Tcl/Tk builds omit optional named fonts.
                pass
    if not fonts:
        raise ValueError('No desktop named fonts are available for zoom')

    originals = {name: int(obj.cget('size')) for name, obj in fonts.items()}
    base_height = style.lookup('Treeview', 'rowheight')
    try:
        row_height = max(18, int(base_height))
    except (TypeError, ValueError):
        row_height = 22
    current = {'index': ZOOM_LEVELS.index(100)}

    def set_index(value: int):
        clamped = max(0, min(len(ZOOM_LEVELS) - 1, value))
        current['index'] = clamped
        level = ZOOM_LEVELS[clamped]
        for name, item in fonts.items():
            original = originals[name]
            if not original:
                continue
            sign = -1 if original < 0 else 1
            new_size = max(6, round(abs(original) * level / 100))
            item.configure(size=sign * new_size)
        style.configure('Treeview', rowheight=max(18, round(row_height * level / 100)))
        if notify is not None:
            notify(f'Display text size {level}% (this session only)')
        return 'break'

    def increase(_event):
        return set_index(current['index'] + 1)

    def decrease(_event):
        return set_index(current['index'] - 1)

    def reset(_event):
        return set_index(ZOOM_LEVELS.index(100))

    root.bind('<Control-Key-plus>', increase, add='+')
    root.bind('<Control-Key-equal>', increase, add='+')
    root.bind('<Control-Key-minus>', decrease, add='+')
    root.bind('<Control-Key-0>', reset, add='+')
    return {'increase': increase, 'decrease': decrease, 'reset': reset}
