"""Synthetic tests for owner-private time-separated decision observations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.decision_longitudinal import (
    initialize, main, record, summarize,
)


class LongitudinalDecisionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "private"
        self.home.mkdir(mode=0o700)
        initialize(self.home)
        self.file = self.home / "decision-timeline.json"

    def add(self, family, choice, day, context="usual"):
        record(self.home, family=family, choice=choice,
               context=context, observed_on=day)

    def fill(self):
        for family in ("work_case", "planning_case", "creative_case"):
            for date_str, choice in (
                ("2026-01-01", "choice_a"),
                ("2026-01-12", "choice_a"),
                ("2026-01-26", "choice_b" if family == "creative_case" else "choice_a"),
            ):
                self.add(family, choice, date_str)

    def test_init_nonoverwrite_and_private_mode(self):
        self.assertEqual(json.loads(self.file.read_text())["observations"], [])
        with self.assertRaisesRegex(ValueError, "exists"):
            initialize(self.home)
        if os.name != "nt":
            self.assertEqual(self.file.stat().st_mode & 0o077, 0)
        self.assertFalse((self.home / "identity.sqlite3").exists())

    def test_report_is_suppressed_for_small_cohorts(self):
        self.add("work_case", "choice_a", "2026-01-01")
        self.add("work_case", "choice_b", "2026-01-16")
        result = summarize(self.home)
        self.assertEqual(result["status"], "insufficient-coverage")
        self.assertIsNone(result["compared_adjacent_pairs"])
        self.assertIsNone(result["matching_choices"])
        self.assertNotIn("work_case", json.dumps(result))
        self.assertNotIn("choice_a", json.dumps(result))
        self.assertNotIn("2026-01-16", json.dumps(result))
        self.assertFalse(result["twin_predictive_fidelity_measured"])

    def test_sufficient_time_separated_agreement_counts(self):
        self.fill()
        result = summarize(self.home)
        self.assertEqual(result["status"], "reportable")
        self.assertEqual(result["compared_adjacent_pairs"], 6)
        self.assertEqual(result["independent_families"], 3)
        self.assertEqual(result["matching_choices"], 5)
        self.assertAlmostEqual(result["observed_agreement"], 5 / 6)
        self.assertFalse(result["names_choices_dates_or_contexts_in_report"])
        self.assertFalse(result["owner_decisions_independently_attested"])
        for marker in ("work_case", "planning_case", "creative_case",
                       "choice_a", "choice_b", "2026-01-01"):
            self.assertNotIn(marker, json.dumps(result))

    def test_min_day_gap_ignores_nearby_observations(self):
        self.fill()
        self.assertEqual(summarize(self.home, min_days=14)["status"],
                         "insufficient-coverage")
        self.assertEqual(summarize(self.home, min_days=7)["status"], "reportable")
        for value in (0, 366, True, "7", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize(self.home, min_days=value)

    def test_context_changes_do_not_count_as_instability(self):
        for family in ("work_case", "planning_case", "creative_case"):
            self.add(family, "choice_a", "2026-01-01")
            self.add(family, "choice_b", "2026-01-20", context="emergency")
            self.add(family, "choice_a", "2026-02-01")
        report = summarize(self.home)
        self.assertEqual(report["status"], "insufficient-coverage")

    def test_duplicate_same_context_day_fails_with_original_intact(self):
        self.add("work_case", "choice_a", "2026-01-01")
        before = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, "Already recorded"):
            self.add("work_case", "choice_b", "2026-01-01")
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse((self.home / "decision-timeline.lock").exists())

    def test_invalid_owner_labels_or_dates_fail_without_write(self):
        before = self.file.read_bytes()
        for name in ("Work Case", "", "../secrets", "école", "a" * 70, "a"):
            with self.subTest(family=name), self.assertRaises(ValueError):
                self.add(name, "choice_a", "2026-01-01")
        for day in ("2026-02-30", "2026-1-1", "20260101", "", "2026/01/01"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                self.add("work_case", "choice_a", day)
        self.assertEqual(self.file.read_bytes(), before)

    def test_json_tampering_and_unknown_fields_are_rejected(self):
        originals = self.file.read_bytes()
        payloads = (
            '{"schema":2,"observations":[]}',
            '{"schema":1,"observations":{} }',
            '{"schema":1,"observations":[{"family":"valid_id","choice":"choice_a","context":"usual","observed_on":"2026-01-01","secret":"x"}]}',
            '{"schema":1,"observations":[{"family":"valid_id","choice":"choice_a","context":"usual","observed_on":"2026-01-01"},{"family":"valid_id","choice":"choice_b","context":"usual","observed_on":"2026-01-01"}]}',
            '{"schema":true,"observations":[]}',
            'not json',
        )
        for payload in payloads:
            with self.subTest(payload=payload[:30]):
                self.file.write_text(payload, encoding="utf-8")
                self.file.chmod(0o600)
                with self.assertRaises(ValueError):
                    summarize(self.home)
                with self.assertRaises(ValueError):
                    self.add("work_case", "choice_a", "2026-01-01")
        self.file.write_bytes(originals)

    def test_world_readable_symlink_or_lock_fails_closed(self):
        if os.name != "nt":
            self.file.chmod(0o644)
            with self.assertRaises(ValueError):
                summarize(self.home)
            self.file.chmod(0o600)
        self.file.unlink()
        target = self.root / "external"
        target.write_text("owner-only outside journal", encoding="utf-8")
        try:
            self.file.symlink_to(target)
        except (NotImplementedError, OSError):
            return
        with self.assertRaises(ValueError):
            self.add("work_case", "choice_a", "2026-01-01")
        self.assertEqual(target.read_text(encoding="utf-8"),
                         "owner-only outside journal")
        self.assertFalse((self.home / "decision-timeline.lock").exists())

    def test_concurrent_lock_prevents_mutation(self):
        lock = self.home / "decision-timeline.lock"
        lock.write_text("", encoding="utf-8")
        old = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, "locked"):
            self.add("work_case", "choice_a", "2026-01-01")
        self.assertEqual(self.file.read_bytes(), old)
        lock.unlink()

    def test_atomic_swap_failure_preserves_old_journal(self):
        old = self.file.read_bytes()
        with patch("athenz.decision_longitudinal.os.replace",
                   side_effect=OSError("private sensitive path")):
            with self.assertRaises(OSError):
                self.add("work_case", "choice_a", "2026-01-01")
        self.assertEqual(self.file.read_bytes(), old)
        self.assertFalse((self.home / "decision-timeline.lock").exists())
        self.assertFalse(list(self.home.glob(".timeline-*")))

    def test_cli_requires_confirm_and_never_loads_ollama(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main(["--home", str(self.home), "record",
                      "--family", "work_case", "--choice", "choice_a",
                      "--context", "usual", "--on", "2026-01-01"])
        with patch("athenz.chat.OllamaClient") as model:
            with patch("builtins.print") as printer:
                main(["--home", str(self.home), "record", "--family",
                      "work_case", "--choice", "choice_a", "--context",
                      "usual", "--on", "2026-01-01", "--confirm"])
                main(["--home", str(self.home), "report"])
            model.assert_not_called()
        self.assertNotIn("work_case", str(printer.call_args_list))
        self.assertFalse((self.home / "identity.sqlite3").exists())

    def test_refuse_location_under_source_checkout(self):
        checkout = self.root / "project"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "Git checkout"):
            initialize(checkout)


if __name__ == "__main__":
    unittest.main()
