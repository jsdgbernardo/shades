"""PRD F-15: wait only when a later time is at least 5 percentage points less sunny."""

import unittest

from app import recommend


def window(now, plus15, plus30):
    return [
        {"offset_minutes": 0, "time": "t0", "sun_percent": now},
        {"offset_minutes": 15, "time": "t15", "sun_percent": plus15},
        {"offset_minutes": 30, "time": "t30", "sun_percent": plus30},
    ]


class ComfortWindowTests(unittest.TestCase):
    def test_four_point_gain_says_walk_now(self):
        self.assertEqual(recommend(window(60, 56, 58))["recommendation"], "walk_now")

    def test_six_point_gain_says_wait_and_names_best_time(self):
        result = recommend(window(60, 57, 54))
        self.assertEqual(result["recommendation"], "wait")
        self.assertEqual(result["best_time"], "t30")

    def test_exactly_five_points_says_wait(self):
        self.assertEqual(recommend(window(60, 55, 59))["recommendation"], "wait")

    def test_best_time_is_the_lowest_score(self):
        self.assertEqual(recommend(window(80, 60, 70))["best_time"], "t15")

    def test_later_time_sunnier_says_walk_now(self):
        result = recommend(window(40, 50, 60))
        self.assertEqual((result["recommendation"], result["best_offset_minutes"]), ("walk_now", 0))


if __name__ == "__main__":
    unittest.main()
