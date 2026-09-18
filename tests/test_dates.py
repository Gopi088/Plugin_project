"""Unit tests: deterministic date engine (stage 5 core)."""
import unittest
from datetime import date

from backend import dates as D

TODAY = date(2026, 9, 18)


class TestFindMentions(unittest.TestCase):
    def test_explicit_range(self):
        ms = D.find_mentions("Software Developer, Jan 2020 to June 2022", TODAY)
        self.assertEqual(len(ms), 1)
        self.assertEqual((ms[0]["start"], ms[0]["end"]), ((2020, 1), (2022, 6)))
        self.assertTrue(ms[0]["is_range"])

    def test_till_and_present(self):
        ms = D.find_mentions("Engineer, May 2025 till Sep 2025", TODAY)
        self.assertEqual((ms[0]["start"], ms[0]["end"]), ((2025, 5), (2025, 9)))
        ms = D.find_mentions("Engineer, Feb 2025 - Present", TODAY)
        self.assertEqual(ms[0]["end"], (2026, 9))
        self.assertTrue(ms[0]["is_present"])

    def test_numeric_and_year_only(self):
        ms = D.find_mentions("Role 05/2025 - Present", TODAY)
        self.assertEqual(ms[0]["start"], (2025, 5))
        # year-only input keeps year precision (interval engine expands it)
        ms = D.find_mentions("B.Tech 2013-2017", TODAY)
        rng = [m for m in ms if m["is_range"]]
        self.assertTrue(rng and rng[0]["precision"] == "year")

    def test_no_invention(self):
        self.assertEqual(D.find_mentions("loves hiking and open source", TODAY), [])
        self.assertEqual(D.find_mentions("", TODAY), [])

    def test_invalid_range_skipped(self):
        # end before start -> skipped, never fabricated
        self.assertEqual(D.find_mentions("June 2022 to Jan 2020", TODAY), [])

    def test_months_between_overlap(self):
        self.assertEqual(D.months_between((2022, 1), (2022, 6)), 5)
        self.assertLess(D.months_between((2022, 6), (2022, 1)), 0)


if __name__ == "__main__":
    unittest.main()
