"""Unit tests: deterministic interval engine (stage 9 core)."""
import unittest

from backend import intervals as I


class TestIntervals(unittest.TestCase):
    def test_union_overlap(self):
        u = I.union([((2020, 1), (2021, 6)), ((2021, 3), (2022, 1))])
        self.assertEqual(u, [((2020, 1), (2022, 1))])

    def test_union_adjacent(self):
        u = I.union([((2020, 1), (2020, 6)), ((2020, 7), (2020, 12))])
        self.assertEqual(len(u), 1)

    def test_union_disjoint(self):
        u = I.union([((2020, 1), (2020, 6)), ((2021, 1), (2021, 6))])
        self.assertEqual(len(u), 2)

    def test_no_double_count(self):
        u = I.union([((2020, 1), (2022, 1)), ((2020, 6), (2021, 6))])
        self.assertEqual(I.total_months(u), 25)  # inclusive Jan20..Jan22

    def test_year_precision_expands(self):
        self.assertEqual(I.normalize_interval((2013, 2013), (2017, 2017), "year"),
                         ((2013, 1), (2017, 12)))

    def test_uncovered(self):
        cov = [((2020, 1), (2020, 6)), ((2021, 1), (2021, 6))]
        gaps = I.uncovered(cov, (2020, 1), (2021, 6))
        self.assertEqual(gaps, [((2020, 7), (2020, 12))])


if __name__ == "__main__":
    unittest.main()
