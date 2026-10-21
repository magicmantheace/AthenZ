"""Synthetic-only bounded same-session recall and in-flight revocation tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.chat import LocalModelError, answer, context_snapshot
from athenz.chat_continuity import same_session_user_excerpts
from athenz.desktop import DesktopService
from athenz.experience import ExperienceStore


class CaptureModel:
    model = "synthetic-local"

    def __init__(self, callback=None):
        self.messages = []
        self.callback = callback

    def generate(self, messages, **kwargs):
        self.messages.append(messages)
        if self.callback:
            self.callback()
        return "Synthetic answer only"


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name) / "owner-private"
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)
        self.old_id = self.store.add_message(
            "work", "twin", "user",
            "For the fictional phoenix compiler, we planned an isolated adapter.")
        self.store.add_message(
            "work", "twin", "assistant",
            "ASSISTANT_INVENTED_MEMORY: The owner lived on a starship.")
        self.store.add_message(
            "other", "twin", "user",
            "OTHER_SESSION_PRIVATE: phoenix compiler was canceled.")
        self.store.add_message(
            "work", "agent", "user",
            "OTHER_MODE_PRIVATE: the phoenix compiler was canceled.")
        for n in range(12):
            self.store.add_message(
                "work", "twin", "user", f"Unrelated filler message number {n}")
        self.prompt = "What was our phoenix compiler plan?"

    def recent(self):
        return self.store.conversation("work", "twin", limit=10)

    def historical(self, *, session="work", mode="twin", prompt=None, recent=None):
        return same_session_user_excerpts(
            self.store, session=session, mode=mode,
            prompt=self.prompt if prompt is None else prompt,
            recent=self.recent() if recent is None else recent)

    def test_old_user_message_retrieved_without_cross_session_leak(self):
        context = self.historical()
        self.assertIsNotNone(context)
        self.assertIn("isolated adapter", context)
        self.assertIn("unreviewed conversational references", context)
        for excluded in ("ASSISTANT_INVENTED_MEMORY", "OTHER_SESSION_PRIVATE",
                         "OTHER_MODE_PRIVATE", "Unrelated filler"):
            self.assertNotIn(excluded, context)
        self.assertNotIn("approved", context.split("OLDER USER-WRITTEN")[0])

    def test_recent_message_not_duplicated_and_unrelated_not_disclosed(self):
        new_id = self.store.add_message(
            "work", "twin", "user", "Fictional phoenix compiler moved to tests.")
        self.assertNotIn("moved to tests", self.historical())
        self.assertIsNone(self.historical(prompt="orbital giant botanical orchids"))
        self.assertNotIn(str(new_id), self.historical())

    def test_twin_older_chat_recall_requires_real_subject_overlap(self):
        unrelated = self.store.add_message(
            "subject-precision", "twin", "user",
            "Which hydraulic tractor would I choose?")
        pertinent = self.store.add_message(
            "subject-precision", "twin", "user",
            "Which ceramic saucepan would I choose?")
        for i in range(12):
            self.store.add_message(
                "subject-precision", "twin", "user",
                "Neutral session filler " + str(i))
        recent = self.store.conversation(
            "subject-precision", "twin", limit=10)
        old = same_session_user_excerpts(
            self.store, session="subject-precision", mode="twin",
            prompt="Which ceramic saucepan would I choose?", recent=recent)
        self.assertIsNotNone(old)
        self.assertIn(str(pertinent), old)
        self.assertNotIn(str(unrelated), old)
        self.assertNotIn("hydraulic tractor", old)
        # With no subject at all, do not leak otherwise unrelated old chat.
        self.assertIsNone(same_session_user_excerpts(
            self.store, session="subject-precision", mode="twin",
            prompt="Which would I choose?", recent=recent))

    def test_context_snapshot_separates_approved_profile_and_older_untrusted(self):
        sig, messages = context_snapshot(
            self.store, self.prompt, "twin", self.recent(), "work")
        self.assertEqual(len(sig), 64)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("REFERENCE PROFILE", messages[1]["content"])
        self.assertIn("OLDER USER-WRITTEN", messages[2]["content"])
        self.assertIn("isolated adapter", messages[2]["content"])
        self.assertNotIn("ASSISTANT_INVENTED_MEMORY", messages[2]["content"])
        self.assertEqual(messages[3]["role"], "system")
        self.assertIn("RECENT SAME-SESSION CHAT", messages[3]["content"])
        self.assertIn("model-generated, not owner memories", messages[3]["content"])
        self.assertEqual(messages[4]["role"], "user")
        self.assertEqual(messages[-1]["content"], self.prompt)
        self.assertNotIn("isolated adapter", sig)
        no_session = context_snapshot(
            self.store, self.prompt, "twin", self.recent())[1]
        self.assertFalse(any("OLDER USER-WRITTEN" in m["content"]
                             for m in no_session))

    def test_recent_generated_assistant_claims_remain_unverified(self):
        history = self.recent()
        _, messages = context_snapshot(
            self.store, "Where did the owner grow up?", "twin", history, "work")
        self.assertIn("RECENT SAME-SESSION CHAT", str(messages))
        self.assertIn("Previous assistant replies are model-generated",
                      str(messages))
        self.assertNotIn("ASSISTANT_INVENTED_MEMORY",
                         messages[1]["content"])
        self.assertTrue(any(
            item["role"] == "user" and
            "Unrelated filler" in item["content"]
            for item in messages[4:-1]))
        self.assertIn("No topically matching approved owner fact",
                      messages[0]["content"])

    def test_mode_and_session_isolation_in_actual_desktop_request(self):
        messages = []
        class Fake:
            model = "synthetic-local"
            def __init__(self, **kwargs):
                pass
            def generate(self, prompt, **kwargs):
                messages.append(prompt)
                return "Synthetic response"
        service = DesktopService(self.home)
        with patch("athenz.desktop.OllamaClient", Fake):
            service.send("work", "twin", self.prompt, model="synthetic-local")
            service.send("work", "agent", self.prompt, model="synthetic-local")
            service.send("other", "twin", self.prompt, model="synthetic-local")
        self.assertIn("isolated adapter", json.dumps(messages[0]))
        self.assertNotIn("OTHER_MODE_PRIVATE", json.dumps(messages[0]))
        self.assertNotIn("OTHER_SESSION_PRIVATE", json.dumps(messages[0]))
        self.assertNotIn("isolated adapter", json.dumps(messages[1]))
        self.assertNotIn("isolated adapter", json.dumps(messages[2]))

    def test_edit_old_selected_message_during_inference_discards_reply(self):
        def mutate():
            other = ExperienceStore(self.home)
            try:
                with other.db:
                    other.db.execute(
                        "UPDATE messages SET content=? WHERE id=?",
                        ("The synthetic phoenix plan changed completely",
                         self.old_id))
            finally:
                other.close()
        model = CaptureModel(callback=mutate)
        with self.assertRaisesRegex(LocalModelError, "evidence changed"):
            answer(self.store, model, self.prompt,
                   "twin", self.recent(), "work")
        self.assertEqual(len(model.messages), 1)
        self.assertNotIn(
            "The synthetic phoenix plan changed completely",
            json.dumps(model.messages[0]))
        self.assertEqual(
            len(self.store.conversation("work", "twin")), 12)

    def test_deleting_old_selected_message_midflight_discards_reply(self):
        def remove():
            other = ExperienceStore(self.home)
            try:
                other.forget_runtime("messages", self.old_id)
            finally:
                other.close()
        model = CaptureModel(callback=remove)
        with self.assertRaises(LocalModelError):
            answer(self.store, model, self.prompt,
                   "twin", self.recent(), "work")

    def test_very_long_old_message_is_bounded_and_relevant_passage_found(self):
        long_id = self.store.add_message(
            "long", "twin", "user",
            ("synthetic irrelevant preamble " * 40) +
            "fictional nebula catalyst is shielded from rain " +
            ("synthetic end of message " * 400))
        part = same_session_user_excerpts(
            self.store, session="long", mode="twin",
            prompt="nebula catalyst shielding", recent=[])
        self.assertIn("nebula catalyst", part)
        self.assertLess(len(part), 1150)
        self.assertIn(str(long_id), part)

    def test_bounded_topk_prefers_more_relevant_old_messages(self):
        for i in range(10):
            self.store.add_message("rank", "agent", "user",
                                   f"Synthetic phoenix {i}")
        best = self.store.add_message(
            "rank", "agent", "user",
            "Synthetic phoenix compiler adapter plan")
        part = same_session_user_excerpts(
            self.store, session="rank", mode="agent",
            prompt="phoenix compiler adapter plan", recent=[])
        payload = part.split("\n")[-1]
        cases = json.loads(payload)
        self.assertLessEqual(len(cases), 4)
        self.assertIn(best, [x["message_id"] for x in cases])
        self.assertEqual([x["message_id"] for x in cases],
                         sorted(x["message_id"] for x in cases))

    def test_invalid_arguments_fail_without_any_cross_session_read(self):
        for arguments in (
            {"session": "", "mode": "twin", "prompt": "phoenix"},
            {"session": "work", "mode": "invalid", "prompt": "phoenix"},
            {"session": "work", "mode": "twin", "prompt": "X" * 4001},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                same_session_user_excerpts(self.store, **arguments)

    def test_no_new_personal_memory_or_training_rows(self):
        original = self.store.db.execute(
            "SELECT COUNT(*) FROM identity").fetchone()[0]
        model = CaptureModel()
        answer(self.store, model, self.prompt,
               "twin", self.recent(), "work")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity").fetchone()[0], original)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM train_pairs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
