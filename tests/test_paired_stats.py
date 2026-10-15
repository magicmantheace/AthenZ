"""Count-only, synthetic statistical benchmark tests."""
import unittest

from athenz.paired_stats import (
    ConfidenceAccumulator, exact_paired_sign_test, discordant_win_interval,
)


class PairedStatsTests(unittest.TestCase):
    def test_exact_two_sided(self):
        self.assertIsNone(exact_paired_sign_test(0, 0))
        self.assertEqual(exact_paired_sign_test(1, 0), 1.0)
        self.assertEqual(exact_paired_sign_test(5, 0), 0.0625)
        self.assertEqual(exact_paired_sign_test(6, 0), 0.03125)
        self.assertEqual(exact_paired_sign_test(4, 4), 1.0)
        self.assertEqual(exact_paired_sign_test(2, 8), 0.109375)
        self.assertEqual(exact_paired_sign_test(8, 2), 0.109375)

    def test_large_case_limit_is_numerically_stable(self):
        p = exact_paired_sign_test(1000, 0)
        self.assertGreater(p, 0)
        self.assertLess(p, 1e-250)
        self.assertEqual(exact_paired_sign_test(500, 500), 1.0)

    def test_interval_reports_discordant_win_rate_only(self):
        self.assertIsNone(discordant_win_interval(0, 0))
        low, high = discordant_win_interval(6, 0)
        self.assertGreater(low, 0.5)
        self.assertEqual(high, 1.0)
        low, high = discordant_win_interval(2, 8)
        self.assertLess(low, 0.2)
        self.assertGreater(high, 0.2)

    def test_refuses_invalid_counts(self):
        for args in ((-1, 2), (3, -1), (1001, 0), (True, 1), (1.0, 1)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    exact_paired_sign_test(*args)
                with self.assertRaises(ValueError):
                    discordant_win_interval(*args)

    def test_confidence_bins_and_metrics_are_aggregate_only(self):
        metric = ConfidenceAccumulator()
        self.assertEqual(metric.report()["samples"], 0)
        self.assertIsNone(metric.report()["chosen_answer_brier_score"])
        metric.add(1.0, correct=True)
        metric.add(0.0, correct=False)
        report = metric.report()
        self.assertEqual(report["samples"], 2)
        self.assertEqual(report["chosen_answer_brier_score"], 0.0)
        self.assertEqual(report["expected_calibration_error_10bins"], 0.0)
        self.assertNotIn("cases", report)
        self.assertNotIn("bins", report)

    def test_overconfident_wrong_choice_has_maximum_error(self):
        metric = ConfidenceAccumulator()
        metric.add(1.0, correct=False)
        result = metric.report()
        self.assertEqual(result["chosen_answer_brier_score"], 1.0)
        self.assertEqual(result["expected_calibration_error_10bins"], 1.0)

    def test_confidence_validation_rejects_invalid_types_and_values(self):
        for prob in (True, False, None, -0.1, 1.01, "0.5",
                     float("nan"), float("inf"), float("-inf")):
            with self.subTest(prob=prob):
                with self.assertRaises(ValueError):
                    ConfidenceAccumulator().add(prob, correct=True)
        with self.assertRaises(ValueError):
            ConfidenceAccumulator().add(0.5, correct=1)


if __name__ == '__main__':
    unittest.main()
