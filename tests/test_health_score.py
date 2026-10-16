import unittest
from datetime import datetime, timezone, timedelta

from backend.health_score import calculate_project_health


class ProjectHealthScoreTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)

    def test_full_score_is_deterministic_and_bounded(self):
        data = {
            "top_contributor_pct": 20,
            "contributor_count": 10,
            "last_pushed_at": self.now - timedelta(days=1),
            "open_issue_count": 2,
            "tracked_issue_count": 20,
            "latest_release_at": self.now - timedelta(days=10),
        }
        first = calculate_project_health(data, self.now)
        second = calculate_project_health(data, self.now)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["score"], 0)
        self.assertLessEqual(first["score"], 100)
        self.assertEqual(len(first["factors"]), 5)

    def test_missing_factors_are_renormalized(self):
        result = calculate_project_health(
            {"top_contributor_pct": 75, "contributor_count": 1}, self.now
        )
        self.assertEqual(result["available_weight_pct"], 45.0)
        self.assertEqual(result["score"], 23)
        self.assertEqual(len(result["factors"]), 2)

    def test_no_data_returns_none_not_a_fake_zero(self):
        result = calculate_project_health({}, self.now)
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage"], "0 of 5 factors available")

    def test_future_timestamps_are_clamped_to_zero_days(self):
        result = calculate_project_health(
            {"last_pushed_at": self.now + timedelta(days=2)}, self.now
        )
        self.assertEqual(result["factors"][0]["score"], 100)


if __name__ == "__main__":
    unittest.main()
