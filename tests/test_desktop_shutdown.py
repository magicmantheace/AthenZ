"""Virtual-display integration: closing UI discards an in-flight response."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from athenz.desktop import launch, DesktopService


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'),
                     'Requires graphical desktop or Xvfb; no automatic display startup')
class DesktopShutdownTests(unittest.TestCase):
    def test_closing_window_discards_pending_model_reply(self):
        from tkinter import Tk

        started, release = threading.Event(), threading.Event()

        class FakeSlowModel:
            model = 'synthetic-local-only'
            def __init__(self, *args, **kwargs):
                pass
            def generate(self, *args, **kwargs):
                started.set()
                if not release.wait(3):
                    raise RuntimeError('Synthetic model failed to finish')
                return 'Synthetic generated response'

        def explore(node):
            yield node
            for child in node.winfo_children():
                yield from explore(child)

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'private'

            def interact(root):
                controls = list(explore(root))
                buttons = [widget for widget in controls
                           if widget.winfo_class() == 'TButton']
                send = next(button for button in buttons if button.cget('text') == 'Send')
                cancel = next(button for button in buttons if button.cget('text') == 'Cancel reply')
                self.assertEqual(str(cancel.cget('state')), 'disabled')
                draft = next(widget for widget in send.master.winfo_children()
                             if widget.winfo_class() == 'TEntry')
                draft.insert(0, 'Synthetic private question')
                send.invoke()
                try:
                    self.assertTrue(started.wait(3), 'Synthetic model not reached')
                    self.assertEqual(str(cancel.cget('state')), 'normal')
                    script = root.protocol('WM_DELETE_WINDOW')
                    self.assertTrue(script, 'Window close must install cancellation callback')
                    root.tk.call(script)
                finally:
                    release.set()

            with patch('athenz.desktop.OllamaClient', FakeSlowModel), \
                 patch.object(Tk, 'mainloop', interact):
                launch(home)
            worker = next((t for t in threading.enumerate()
                           if t.name == 'athenz-local-inference'), None)
            if worker is not None:
                worker.join(3)
                self.assertFalse(worker.is_alive(), 'Synthetic inference thread did not exit')
            self.assertEqual(DesktopService(home).history('desktop', 'agent'), [])


if __name__ == '__main__':
    unittest.main()
