import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.readiness_score import calculate


class TestReadinessScore(unittest.TestCase):
    def test_calculates_weighted_score_from_recovery_inputs(self):
        result = calculate(
            {
                "sleep_score": 90,
                "hrv": 60,
                "hrv_baseline_low": 50,
                "hrv_baseline_high": 60,
                "body_battery_high": 85,
                "resting_hr": 50,
                "resting_hr_7d_avg": 52,
                "acwr": 1.1,
            }
        )

        self.assertGreaterEqual(result.score, 80)
        self.assertLessEqual(result.score, 100)
        self.assertEqual(
            {"sleep", "hrv", "body_battery", "resting_hr", "training_load"},
            set(result.components),
        )

    def test_penalises_suppressed_recovery_and_high_load(self):
        result = calculate(
            {
                "sleep_score": 45,
                "hrv": 35,
                "hrv_baseline_low": 50,
                "hrv_baseline_high": 60,
                "body_battery_high": 30,
                "resting_hr": 62,
                "resting_hr_7d_avg": 54,
                "acwr": 1.7,
            }
        )

        self.assertLess(result.score, 45)

    def test_missing_data_returns_neutral_calculated_score(self):
        result = calculate(None)
        self.assertEqual(50, result.score)
        self.assertEqual({}, result.components)


if __name__ == "__main__":
    unittest.main()
