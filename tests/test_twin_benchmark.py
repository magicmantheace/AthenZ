"""Synthetic benchmark contract: no owner files or model inference."""
import unittest

from athenz.twin_benchmark import run_benchmark


class TwinBenchmarkTests(unittest.TestCase):
    def test_old_relevant_record_is_retrieved_and_revocation_takes_effect(self):
        result = run_benchmark()
        self.assertEqual(result["schema"], 1)
        self.assertTrue(result["synthetic_only"])
        self.assertEqual(result["cases"], 2)
        self.assertEqual(result["expected_retrievals_correct"], 2)
        self.assertEqual(result["irrelevant_evidence_exposures"], 0)
        self.assertEqual(result["revoked_evidence_exposures"], 0)
        self.assertFalse(result["real_personality_accuracy_measured"])


if __name__ == "__main__":
    unittest.main()
