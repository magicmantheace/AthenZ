"""Keyboard font zoom is bounded and never authorizes work."""
from __future__ import annotations

import unittest

from athenz.desktop_zoom import ZOOM_LEVELS, install_text_zoom


class FakeFont:
    def __init__(self, size):
        self.size = size
        self.changes = []
    def cget(self, prop):
        assert prop == 'size'
        return self.size
    def configure(self, *, size):
        self.size = size
        self.changes.append(size)


class FakeStyle:
    def __init__(self):
        self.height = '24'
        self.changed = []
    def lookup(self, style, name):
        assert (style, name) == ('Treeview', 'rowheight')
        return self.height
    def configure(self, style, **kw):
        self.changed.append((style, kw))


class FakeRoot:
    def __init__(self):
        self.bindings = {}
    def bind(self, sequence, callback, add=None):
        assert add == '+'
        self.bindings[sequence] = callback


class ZoomTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.style = FakeStyle()
        self.fonts = {'default': FakeFont(10), 'text': FakeFont(-12),
                      'small': FakeFont(0)}
        self.notes = []
        self.actions = install_text_zoom(self.root, self.style, fonts=self.fonts,
                                         notify=self.notes.append)

    def test_no_change_or_private_action_until_keyboard_gesture(self):
        self.assertEqual(self.style.changed, [])
        self.assertEqual(self.notes, [])
        self.assertEqual((self.fonts['default'].size, self.fonts['text'].size), (10, -12))

    def test_increase_and_decrease_preserves_font_unit_sign(self):
        self.assertEqual(self.root.bindings['<Control-Key-equal>'](None), 'break')
        self.assertEqual(self.fonts['default'].size, 11)
        self.assertEqual(self.fonts['text'].size, -13)
        self.assertIn('110%', self.notes[-1])
        self.assertEqual(self.root.bindings['<Control-Key-minus>'](None), 'break')
        self.assertEqual(self.fonts['default'].size, 10)
        self.assertEqual(self.fonts['text'].size, -12)

    def test_zoom_is_bounded_and_reset_does_not_change_profile(self):
        for _ in range(100):
            self.actions['increase'](None)
        self.assertEqual(self.fonts['default'].size, 20)
        self.assertIn('200%', self.notes[-1])
        self.root.bindings['<Control-Key-0>'](None)
        self.assertEqual(self.fonts['default'].size, 10)
        for _ in range(100):
            self.actions['decrease'](None)
        self.assertEqual(self.fonts['default'].size, 8)
        self.assertIn('80%', self.notes[-1])

    def test_treeview_row_height_tracks_zoom(self):
        self.actions['increase'](None)
        self.assertEqual(self.style.changed[-1], ('Treeview', {'rowheight': 26}))
        self.actions['reset'](None)
        self.assertEqual(self.style.changed[-1], ('Treeview', {'rowheight': 24}))

    def test_empty_font_map_fails_without_binding_actions(self):
        root = FakeRoot()
        with self.assertRaisesRegex(ValueError, 'No desktop named fonts'):
            install_text_zoom(root, FakeStyle(), fonts={})
        self.assertEqual(root.bindings, {})

    def test_expected_safe_key_bindings(self):
        self.assertEqual(set(self.root.bindings),
                         {'<Control-Key-plus>', '<Control-Key-equal>',
                          '<Control-Key-minus>', '<Control-Key-0>'})
        self.assertTrue(100 in ZOOM_LEVELS)


if __name__ == '__main__':
    unittest.main()
