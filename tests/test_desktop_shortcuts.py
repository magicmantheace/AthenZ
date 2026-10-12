"""Keyboard shortcuts never grant approval or execution authority."""
import unittest
from athenz.desktop_shortcuts import install_navigation


class Root:
    def __init__(self):
        self.handlers = {}
    def bind(self, sequence, callback, add=None):
        assert add == '+'
        self.handlers[sequence] = callback


class Notebook:
    def __init__(self):
        self.selected = None
        self.traversal_enabled = False
    def select(self, tab):
        self.selected = tab
    def enable_traversal(self):
        self.traversal_enabled = True


class Focus:
    def __init__(self):
        self.calls = 0
    def focus_set(self):
        self.calls += 1


class NavigationTests(unittest.TestCase):
    def test_tab_shortcuts_only_select_and_focus(self):
        root, notebook = Root(), Notebook()
        focus = [Focus() for _ in range(4)]
        tabs = ['chat', 'review', 'coding', 'setup']
        install_navigation(root, notebook, tabs, focus)
        self.assertTrue(notebook.traversal_enabled)
        for n, tab in enumerate(tabs, start=1):
            self.assertEqual(root.handlers[f'<Control-Key-{n}>'](object()), 'break')
            self.assertEqual(notebook.selected, tab)
            self.assertEqual(focus[n - 1].calls, 1)
        self.assertEqual(root.handlers['<Control-Key-l>'](object()), 'break')
        self.assertEqual(notebook.selected, 'chat')
        self.assertEqual(focus[0].calls, 2)
        self.assertEqual(set(root.handlers), {f'<Control-Key-{n}>' for n in range(1, 5)} | {'<Control-Key-l>'})

    def test_requires_all_four_tabs_and_focus_targets(self):
        with self.assertRaises(ValueError):
            install_navigation(Root(), Notebook(), [1, 2, 3], [Focus()] * 4)
        with self.assertRaises(ValueError):
            install_navigation(Root(), Notebook(), [1, 2, 3, 4], [Focus()] * 3)


if __name__ == '__main__':
    unittest.main()
