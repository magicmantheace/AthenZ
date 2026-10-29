"""No-real-owner-data tests for consented, disposable Twin/Agent smoke."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.synthetic_chat_smoke import (
    check_synthetic_chat, SyntheticChatSmokeError, main,
)


class FakeModel:
    calls: list[list[dict]] = []
    def __init__(self, *, model=None, endpoint=None):
        self.model = model or "synthetic:1"

    def generate(self, messages, **kw):
        FakeModel.calls.append(messages)
        return "A synthetic local model reply for a fictional project."


class SyntheticChatSmokeTests(unittest.TestCase):
    def setUp(self):
        FakeModel.calls = []

    def test_confirmation_and_tag_validation_precede_any_file_or_model_work(self):
        with mock.patch("athenz.synthetic_chat_smoke.tempfile.TemporaryDirectory",
                        side_effect=AssertionError("created scratch files")), \
             mock.patch("athenz.desktop.OllamaClient",
                        side_effect=AssertionError("model loaded")):
            with self.assertRaises(SyntheticChatSmokeError):
                check_synthetic_chat(model="synthetic:1")
            for bad in (True, None, "", "../secret", "x" * 129,
                        "http://evil.test", "bad tag", 1):
                with self.subTest(bad=bad), self.assertRaises(SyntheticChatSmokeError):
                    check_synthetic_chat(model=bad, confirmed=True)

    def test_two_real_desktop_turns_are_isolated_and_disposable(self):
        created = []
        original = tempfile.TemporaryDirectory

        def wrapped(*args, **kwargs):
            context = original(*args, **kwargs)
            created.append(context.name)
            return context

        with mock.patch("athenz.desktop.OllamaClient", FakeModel), \
             mock.patch("athenz.synthetic_chat_smoke.tempfile.TemporaryDirectory",
                        side_effect=wrapped):
            report = check_synthetic_chat(model="synthetic:1", confirmed=True)
        self.assertEqual(report["status"], "synthetic-chat-roundtrip-observed")
        self.assertTrue(report["twin_reply_saved"])
        self.assertTrue(report["agent_reply_saved"])
        self.assertTrue(report["mode_isolation_verified"])
        self.assertTrue(report["synthetic_approved_context_verified"])
        self.assertTrue(report["temporary_profile_removed"])
        self.assertEqual(report["inference_calls_attempted"], 2)
        self.assertEqual(len(FakeModel.calls), 2)
        self.assertIn("Twin mode", FakeModel.calls[0][0]["content"])
        self.assertIn("Agent mode", FakeModel.calls[1][0]["content"])
        self.assertIn("fictional software projects", FakeModel.calls[0][1]["content"])
        self.assertTrue(all(
            "fictional" in m[-1]["content"].lower() for m in FakeModel.calls))
        self.assertTrue(all(not Path(d).exists() for d in created))
        for flag in ("owner_profile_opened", "owner_data_sent",
                     "local_model_downloaded", "training_performed",
                     "gpu_validated", "real_twin_fidelity_validated"):
            self.assertFalse(report[flag])
        serialized = json.dumps(report)
        for prohibited in ("synthetic:1", "fictional software", "SYNTHETIC PRIVATE",
                           "athenz-synthetic-chat-", "A synthetic local model reply"):
            self.assertNotIn(prohibited, serialized)

    def test_opt_in_twin_lifecycle_uses_five_real_service_turns(self):
        with mock.patch("athenz.desktop.OllamaClient", FakeModel):
            report = check_synthetic_chat(
                model="synthetic:1", confirmed=True, twin_lifecycle=True)
        self.assertEqual(report["status"], "synthetic-twin-lifecycle-observed")
        self.assertTrue(report["temporary_profile_removed"])
        self.assertEqual(report["inference_calls_attempted"], 5)
        self.assertEqual(len(FakeModel.calls), 5)
        self.assertTrue(report["session_reopened"])
        self.assertTrue(report["pending_correction_excluded_from_approved_context"])
        self.assertTrue(report["approved_correction_in_approved_context"])
        self.assertTrue(report["revoked_memory_excluded_from_approved_context"])
        self.assertTrue(report["lifecycle_conversation_persisted"])
        self.assertFalse(report["model_answer_quality_measured"])
        self.assertIn("I prefer a review before release",
                      FakeModel.calls[0][1]["content"])
        self.assertNotIn("I prefer a review before release",
                         FakeModel.calls[2][1]["content"])
        self.assertIn("I prefer staged review before release",
                      FakeModel.calls[3][1]["content"])
        self.assertNotIn("I prefer staged review before release",
                         FakeModel.calls[4][1]["content"])
        self.assertNotIn("synthetic:1", json.dumps(report))
        self.assertNotIn("staged review before release", json.dumps(report))

    def test_lifecycle_failure_is_bounded_and_sanitized(self):
        class FailsFourth(FakeModel):
            def generate(self, messages, **kw):
                FakeModel.calls.append(messages)
                if len(FakeModel.calls) == 4:
                    raise RuntimeError("PRIVATE SYNTHETIC MODEL SECRET")
                return "Synthetic local response"
        with mock.patch("athenz.desktop.OllamaClient", FailsFourth):
            report = check_synthetic_chat(
                model="synthetic:1", confirmed=True, twin_lifecycle=True)
        self.assertEqual(report["status"], "local-smoke-unavailable")
        self.assertEqual(report["inference_calls_attempted"], 4)
        self.assertFalse(report["real_twin_fidelity_validated"])
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("SECRET", json.dumps(report))

    def test_lifecycle_flag_requires_boolean_and_owner_confirmation(self):
        with mock.patch("athenz.synthetic_chat_smoke.tempfile.TemporaryDirectory",
                        side_effect=AssertionError("should not create scratch")):
            with self.assertRaises(SyntheticChatSmokeError):
                check_synthetic_chat(
                    model="synthetic:1", confirmed=False, twin_lifecycle=True)
            with self.assertRaises(SyntheticChatSmokeError):
                check_synthetic_chat(
                    model="synthetic:1", confirmed=True, twin_lifecycle="yes")

    def test_second_inference_failure_does_not_expose_model_error(self):
        class FailsSecond(FakeModel):
            def generate(self, messages, **kw):
                FakeModel.calls.append(messages)
                if len(FakeModel.calls) == 2:
                    raise RuntimeError("PRIVATE PROMPT EXCEPTION AND PATH SECRET")
                return "Synthetic first reply"
        with mock.patch("athenz.desktop.OllamaClient", FailsSecond):
            report = check_synthetic_chat(model="synthetic:1", confirmed=True)
        self.assertEqual(report["status"], "local-smoke-unavailable")
        self.assertFalse(report["temporary_profile_removed"])
        self.assertTrue(report["twin_reply_saved"])
        self.assertFalse(report["agent_reply_saved"])
        self.assertEqual(report["inference_calls_attempted"], 2)
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("SECRET", json.dumps(report))

    def test_failure_on_first_inference_is_sanitized(self):
        class FailsFirst(FakeModel):
            def generate(self, *args, **kw):
                raise RuntimeError("PRIVATE OWNER PROFILE")
        with mock.patch("athenz.desktop.OllamaClient", FailsFirst):
            report = check_synthetic_chat(model="synthetic:1", confirmed=True)
        self.assertEqual(report["inference_calls_attempted"], 1)
        self.assertFalse(report["twin_reply_saved"])
        self.assertFalse(report["agent_reply_saved"])
        self.assertFalse(report["real_twin_fidelity_validated"])
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_synthetic_private_profile_never_uses_environment_home(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / "owner-actual"
            sentinel.mkdir()
            (sentinel / "secret.txt").write_text("PRIVATE OWNER MEMORIES")
            with mock.patch.dict("os.environ", {"ATHENZ_HOME": str(sentinel)}), \
                 mock.patch("athenz.desktop.OllamaClient", FakeModel):
                result = check_synthetic_chat(model="synthetic:1", confirmed=True)
            self.assertEqual(result["status"], "synthetic-chat-roundtrip-observed")
            self.assertEqual(list(sentinel.iterdir()), [sentinel / "secret.txt"])
            self.assertNotIn("PRIVATE OWNER MEMORIES", json.dumps(FakeModel.calls))

    def test_failed_prompt_assembly_never_starts_any_inference(self):
        with mock.patch("athenz.prompting.build_messages",
                        side_effect=RuntimeError("SECRET OWNER TEXT")), \
             mock.patch("athenz.desktop.OllamaClient", FakeModel):
            result = check_synthetic_chat(model="synthetic:1", confirmed=True)
        self.assertEqual(result["status"], "local-smoke-unavailable")
        self.assertEqual(result["inference_calls_attempted"], 0)
        self.assertEqual(FakeModel.calls, [])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_cli_confirmation_and_success_are_json_without_private_text(self):
        with mock.patch("athenz.desktop.OllamaClient", FakeModel), \
             mock.patch("builtins.print") as printer:
            main(["--model", "synthetic:1", "--confirm"])
        result = json.loads(printer.call_args.args[0])
        self.assertEqual(result["status"], "synthetic-chat-roundtrip-observed")
        self.assertEqual(result["inference_calls_attempted"], 2)
        with mock.patch("builtins.print"):
            with self.assertRaises(SyntheticChatSmokeError):
                main(["--model", "synthetic:1"])

    def test_cli_extended_twin_lifecycle_reports_only_sanitized_flags(self):
        with mock.patch("athenz.desktop.OllamaClient", FakeModel), \
             mock.patch("builtins.print") as printer:
            main(["--model", "synthetic:1", "--twin-lifecycle", "--confirm"])
        report = json.loads(printer.call_args.args[0])
        self.assertEqual(report["status"], "synthetic-twin-lifecycle-observed")
        self.assertEqual(report["inference_calls_attempted"], 5)
        self.assertTrue(report["temporary_profile_removed"])
        self.assertNotIn("fictional software projects", json.dumps(report))

    def test_cli_exits_nonzero_on_unavailable_model(self):
        with mock.patch("athenz.synthetic_chat_smoke.check_synthetic_chat",
                        return_value={"status": "local-smoke-unavailable"}), \
             mock.patch("builtins.print"):
            with self.assertRaises(SystemExit) as context:
                main(["--model", "synthetic:1", "--confirm"])
        self.assertEqual(context.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
