"""
Stage 2 tests — reader.py

Tests for the Word dataclass, _group_into_lines(), and the public
extract_lines() API.  All tests use synthetic Word data; no real PDF is
required.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.reader import Word, _group_into_lines, Y_TOLERANCE


def make_word(text: str, x0: float, y0: float, width: float = 20.0, height: float = 10.0) -> Word:
    """Helper: build a Word with computed x1/y1 from position and size."""
    return Word(text=text, x0=x0, y0=y0, x1=x0 + width, y1=y0 + height)


class TestWordDataclass(unittest.TestCase):
    """Verify the Word dataclass and its y_mid property."""

    def test_y_mid_is_midpoint(self):
        w = Word(text="foo", x0=10.0, y0=20.0, x1=30.0, y1=30.0)
        self.assertAlmostEqual(w.y_mid, 25.0)

    def test_y_mid_fractional(self):
        w = Word(text="bar", x0=0.0, y0=0.0, x1=10.0, y1=11.0)
        self.assertAlmostEqual(w.y_mid, 5.5)

    def test_fields_stored_correctly(self):
        w = Word(text="hello", x0=1.1, y0=2.2, x1=3.3, y1=4.4)
        self.assertEqual(w.text, "hello")
        self.assertAlmostEqual(w.x0, 1.1)
        self.assertAlmostEqual(w.y0, 2.2)
        self.assertAlmostEqual(w.x1, 3.3)
        self.assertAlmostEqual(w.y1, 4.4)


class TestGroupIntoLines(unittest.TestCase):
    """Tests for _group_into_lines() using synthetic Word objects."""

    # ------------------------------------------------------------------
    # Required test: y-midpoints 2pt apart → same line
    # ------------------------------------------------------------------
    def test_groups_same_line(self):
        """Two words whose y-midpoints differ by 2pt end up in one line."""
        # word A: y0=10, y1=20 → y_mid = 15.0
        # word B: y0=12, y1=22 → y_mid = 17.0   (diff = 2.0 < 4.0)
        w_a = Word(text="Hello", x0=10.0, y0=10.0, x1=50.0, y1=20.0)
        w_b = Word(text="World", x0=60.0, y0=12.0, x1=100.0, y1=22.0)
        lines = _group_into_lines([w_a, w_b])
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0]), 2)

    # ------------------------------------------------------------------
    # Required test: y-midpoints 10pt apart → different lines
    # ------------------------------------------------------------------
    def test_splits_different_lines(self):
        """Two words whose y-midpoints differ by 10pt end up in two lines."""
        # word A: y0=10, y1=20 → y_mid = 15.0
        # word B: y0=20, y1=30 → y_mid = 25.0   (diff = 10.0 ≥ 4.0)
        w_a = Word(text="Line1", x0=10.0, y0=10.0, x1=50.0, y1=20.0)
        w_b = Word(text="Line2", x0=10.0, y0=20.0, x1=50.0, y1=30.0)
        lines = _group_into_lines([w_a, w_b])
        self.assertEqual(len(lines), 2)

    # ------------------------------------------------------------------
    # Required test: words sorted left-to-right within a line
    # ------------------------------------------------------------------
    def test_sorts_left_to_right(self):
        """Words within the same line are sorted by x0 ascending."""
        # All on the same y (y_mid = 15) but different x positions.
        w_c = make_word("C", x0=200.0, y0=10.0)  # rightmost
        w_a = make_word("A", x0=10.0,  y0=10.0)  # leftmost
        w_b = make_word("B", x0=100.0, y0=10.0)  # middle
        lines = _group_into_lines([w_c, w_a, w_b])
        self.assertEqual(len(lines), 1)
        texts = [w.text for w in lines[0]]
        self.assertEqual(texts, ["A", "B", "C"])

    # ------------------------------------------------------------------
    # Required test: lines sorted top-to-bottom
    # ------------------------------------------------------------------
    def test_sorts_top_to_bottom(self):
        """Lines are ordered by mean y0, top to bottom."""
        # Three distinct rows well apart in y.
        row3 = [make_word("Row3", x0=10.0, y0=100.0)]
        row1 = [make_word("Row1", x0=10.0, y0=10.0)]
        row2 = [make_word("Row2", x0=10.0, y0=50.0)]
        # Feed them in reverse order.
        words = row3 + row2 + row1
        lines = _group_into_lines(words)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0][0].text, "Row1")
        self.assertEqual(lines[1][0].text, "Row2")
        self.assertEqual(lines[2][0].text, "Row3")

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------
    def test_empty_input_returns_empty(self):
        """Empty word list returns empty line list."""
        self.assertEqual(_group_into_lines([]), [])

    def test_single_word(self):
        """A single word forms one line."""
        w = make_word("Solo", x0=10.0, y0=10.0)
        lines = _group_into_lines([w])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0].text, "Solo")

    def test_tolerance_boundary_below_groups(self):
        """Words exactly 3.9pt apart in y_mid → same line (< 4.0 tolerance)."""
        w_a = Word(text="A", x0=0.0,  y0=10.0, x1=20.0, y1=20.0)  # y_mid=15.0
        w_b = Word(text="B", x0=30.0, y0=13.9, x1=50.0, y1=23.9)  # y_mid=18.9 (diff=3.9)
        lines = _group_into_lines([w_a, w_b])
        self.assertEqual(len(lines), 1)

    def test_tolerance_boundary_at_splits(self):
        """Words exactly 4.0pt apart in y_mid → different lines (not < 4.0)."""
        w_a = Word(text="A", x0=0.0,  y0=10.0, x1=20.0, y1=20.0)  # y_mid=15.0
        w_b = Word(text="B", x0=30.0, y0=14.0, x1=50.0, y1=24.0)  # y_mid=19.0 (diff=4.0)
        lines = _group_into_lines([w_a, w_b])
        self.assertEqual(len(lines), 2)

    def test_multiple_words_per_line_sorted(self):
        """Five words on the same line come back sorted left-to-right."""
        y = 10.0
        words = [
            make_word(str(x), x0=float(x), y0=y)
            for x in [50, 10, 90, 30, 70]
        ]
        lines = _group_into_lines(words)
        self.assertEqual(len(lines), 1)
        x_vals = [w.x0 for w in lines[0]]
        self.assertEqual(x_vals, sorted(x_vals))

    def test_custom_y_tolerance(self):
        """A custom tolerance of 2pt correctly splits words 3pt apart."""
        w_a = Word(text="A", x0=0.0,  y0=10.0, x1=20.0, y1=20.0)  # y_mid=15.0
        w_b = Word(text="B", x0=30.0, y0=13.0, x1=50.0, y1=23.0)  # y_mid=18.0 (diff=3.0)
        lines_default = _group_into_lines([w_a, w_b], y_tolerance=4.0)
        lines_tight   = _group_into_lines([w_a, w_b], y_tolerance=2.0)
        self.assertEqual(len(lines_default), 1)  # 3.0 < 4.0 → same line
        self.assertEqual(len(lines_tight), 2)    # 3.0 ≥ 2.0 → split

    def test_athlete_row_two_printed_lines(self):
        """
        Simulates a typical 2-line Ianseo athlete entry.

        Line 1 (y≈50):  '1', '2-001A', 'RIST', 'Martin', 'M', 'VVVK', '318', '293', '611'
        Line 2 (y≈62):  '314', '313', '627', '1,238', '26', '10'
        """
        y1, y2 = 50.0, 62.0
        tokens_line1 = ["1", "2-001A", "RIST", "Martin", "M", "VVVK", "318", "293", "611"]
        tokens_line2 = ["314", "313", "627", "1,238", "26", "10"]

        words = []
        for i, t in enumerate(tokens_line1):
            words.append(make_word(t, x0=float(10 + i * 50), y0=y1))
        for i, t in enumerate(tokens_line2):
            words.append(make_word(t, x0=float(10 + i * 50), y0=y2))

        lines = _group_into_lines(words)
        self.assertEqual(len(lines), 2)
        self.assertEqual([w.text for w in lines[0]], tokens_line1)
        self.assertEqual([w.text for w in lines[1]], tokens_line2)

    def test_page_boundary_words_not_merged(self):
        """
        Words from the bottom of one simulated page (y≈780) and top of the
        next (y≈50, offset by a new-page sentinel) must not be merged.

        In practice extract_lines() processes each page independently, so
        y values reset per page.  This test verifies _group_into_lines()
        itself handles large y gaps correctly.
        """
        bottom_of_page = make_word("Footer", x0=10.0, y0=780.0)
        top_of_next    = make_word("Header", x0=10.0, y0=50.0)
        lines = _group_into_lines([bottom_of_page, top_of_next])
        self.assertEqual(len(lines), 2)


class TestExtractLinesFileNotFound(unittest.TestCase):
    """extract_lines() raises FileNotFoundError for missing files."""

    def test_missing_file_raises(self):
        from archery_parser.reader import extract_lines
        with self.assertRaises(FileNotFoundError):
            extract_lines("/nonexistent/path/to/file.pdf")


if __name__ == "__main__":
    unittest.main(verbosity=2)
