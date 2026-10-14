"""Synthetic benchmarking must be reproducible and never inspect owner data."""
import json
import unittest
from unittest.mock import patch

from athenz.twin_retrieval_benchmark import main, run_synthetic_benchmark


class SyntheticTwinRetrievalBenchmarkTests(unittest.TestCase):
    def test_full_history_regression_fixture_retrieval_and_consent(self):
        report = run_synthetic_benchmark()
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["cases"], 3)
        self.assertEqual(report["full_history_recall_at_prompt"], 1.0)
        self.assertEqual(report["latest_200_candidate_window_recall"], 0.0)
        self.assertTrue(report["approval_and_heldout_isolation_passed"])
        self.assertTrue(report["deterministic_results"])
        self.assertTrue(report["revocation_propagates"])
        self.assertFalse(report["model_called"])
        self.assertFalse(report["private_profile_accessed"])
        self.assertFalse(report["real_owner_personality_accuracy_measured"])
        self.assertNotIn("ASTRONOMY_OLD_TARGET", json.dumps(report))

    def test_entrypoint_reports_aggregate_only(self):
        with patch("builtins.print") as output:
            self.assertEqual(main(), 0)
        self.assertEqual(len(output.call_args_list), 1)
        report = json.loads(output.call_args.args[0])
        self.assertEqual(report["cases"], 3)
        self.assertNotIn("GYROSCOPE_OLD_TARGET", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
