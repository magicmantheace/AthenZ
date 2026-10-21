"""Synthetic terminal-chat routing: Twin first, Agent explicitly selectable.

No Ollama, network, private owner profile or interactive generated response.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from athenz.chat import main


class TerminalTwinDefaultTests(unittest.TestCase):
    def _exit_without_inference(self, options):
        with TemporaryDirectory(prefix="athenz-terminal-test-") as scratch:
            home = Path(scratch) / "fictional-private"
            argv = ["--home", str(home), "--model", "synthetic-local", *options]
            with patch("athenz.chat.OllamaClient") as client, \
                 patch("builtins.input", return_value="/exit"), \
                 patch("builtins.print") as output:
                client.return_value.model = "synthetic-local"
                main(argv)
                client.assert_called_once_with(model="synthetic-local")
                client.return_value.generate.assert_not_called()
                return " ".join(
                    str(c.args[0]) for c in output.call_args_list if c.args
                )

    def test_default_terminal_chat_is_twin(self):
        text = self._exit_without_inference([])
        self.assertIn("AthenZ local twin chat", text)

    def test_explicit_agent_terminal_chat_remains_available(self):
        text = self._exit_without_inference(["--mode", "agent"])
        self.assertIn("AthenZ local agent chat", text)


if __name__ == "__main__":
    unittest.main()
