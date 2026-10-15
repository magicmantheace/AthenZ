"""Count-only, synthetic statistical benchmark tests."""
import unittest

from athenz.paired_stats import exact_paired_sign_test, discordant_win_interval


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


if __name__ == '__main__':
    unittest.main()
