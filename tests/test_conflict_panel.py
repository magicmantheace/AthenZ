"""Headless safety of the Tk conflict-review input boundary."""
import unittest
from unittest.mock import patch
from athenz.conflict_panel import checked_decision, mount_conflict_review_button
from athenz.conflict_review import ConflictReviewError


class ConflictPanelTests(unittest.TestCase):
    def test_requires_exact_sha_and_manual_decision(self):
        for hash_text in ('', 'a'*63, 'z'*64, 'A'*64, 'x'*64):
            with self.assertRaises(ConflictReviewError):
                checked_decision(hash_text, 'reject', '')
        with self.assertRaises(ConflictReviewError):
            checked_decision('a'*64, 'model-approved', '')
        self.assertEqual(checked_decision('a'*64, 'reject', '')['decision'], 'reject')

    def test_predecessor_must_be_specific_only_for_supersession(self):
        for invalid in ('', '0', '-1', '01', 'abc', '1.0', '1'*20):
            with self.assertRaises(ConflictReviewError):
                checked_decision('f'*64, 'supersede', invalid)
        self.assertEqual(checked_decision('f'*64, 'supersede', ' 12 ')['predecessor_id'], 12)
        with self.assertRaises(ConflictReviewError):
            checked_decision('f'*64, 'keep-both', '12')

    def test_native_button_only_opens_on_user_action(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            window = tk.Tk()
        except (ImportError, tk.TclError) as exc:
            self.skipTest(f'No graphical Tk session: {type(exc).__name__}')
        try:
            toolbar = ttk.Frame(window)
            toolbar.pack()
            tree = ttk.Treeview(window, columns=('kind','id','preview'), show='headings')
            tree.pack()
            with patch('athenz.conflict_panel.preview', side_effect=AssertionError('automatic private read')), \
                 patch('athenz.conflict_panel.adjudicate', side_effect=AssertionError('automatic mutation')):
                button = mount_conflict_review_button(toolbar, window, tree, None, lambda: None)
                self.assertIn('Review episode', button.cget('text'))
                window.update_idletasks()
        finally:
            window.destroy()

    def test_import_only_does_not_read_memory_or_launch_window(self):
        with patch('athenz.conflict_panel.adjudicate', side_effect=AssertionError('mutation')):
            self.assertTrue(callable(mount_conflict_review_button))
            self.assertTrue(callable(checked_decision))


if __name__ == '__main__':
    unittest.main()
