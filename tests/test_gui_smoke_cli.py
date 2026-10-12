"""GUI smoke must use a disposable profile, never the owner's home."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.desktop import main


class GuiSmokeCLITests(unittest.TestCase):
    def test_gui_smoke_is_disposable_even_with_home_override(self):
        with tempfile.TemporaryDirectory() as root:
            user_home = Path(root) / 'owner-private'
            with mock.patch('athenz.desktop.launch') as launcher:
                main(['--home', str(user_home), '--gui-self-test'])
                launcher.assert_called_once()
                args, kwargs = launcher.call_args
                self.assertEqual(kwargs, {'smoke_duration_ms': 650})
                self.assertNotEqual(args[0], user_home)
                self.assertFalse(Path(args[0]).exists())
                self.assertFalse(user_home.exists())

    def test_headless_smoke_still_does_not_launch_gui(self):
        with mock.patch('athenz.preflight.desktop_self_test') as check, \
             mock.patch('athenz.desktop.launch') as launcher:
            main(['--self-test'])
            check.assert_called_once_with()
            launcher.assert_not_called()


if __name__ == '__main__':
    unittest.main()
