"""
Stage 5 tests — writer.py

Tests for arithmetic verification and CSV output.
Uses synthetic CSVRow data and a temporary file for CSV checks.
"""

import sys
import os
import csv
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.models import CSVRow
from archery_parser.writer import (
    write_csv,
    _verify_athlete_group,
    _group_by_athlete,
    _is_end_row,
    _is_half_subtotal_row,
    _is_grand_total_row,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_row(
    athlete: str = "Martin Rist",
    distance: str = "70m",
    result: int = 300,
    date: str = "14.09.2025",
    competition: str = "Puiatu CUP 2025",
    club: str = "VVVK",
    bow_type: str = "Recurve",
    age_class: str = "Adult",
    gender: str = "Men",
) -> CSVRow:
    return CSVRow(
        date=date,
        athlete=athlete,
        club=club,
        bow_type=bow_type,
        age_class=age_class,
        gender=gender,
        distance=distance,
        result=result,
        competition=competition,
    )


def make_athlete_rows_4end(
    athlete: str = "Martin Rist",
    e1: int = 318, e2: int = 293, s1: int = 611,
    e3: int = 314, e4: int = 313, s2: int = 627,
    grand: int = 1238,
) -> list[CSVRow]:
    """Build a correctly structured 7-row block for a 4-end athlete."""
    return [
        make_row(athlete=athlete, distance="70m",   result=e1),
        make_row(athlete=athlete, distance="70m",   result=e2),
        make_row(athlete=athlete, distance="2x70m", result=s1),
        make_row(athlete=athlete, distance="70m",   result=e3),
        make_row(athlete=athlete, distance="70m",   result=e4),
        make_row(athlete=athlete, distance="2x70m", result=s2),
        make_row(athlete=athlete, distance="4x70m", result=grand),
    ]


def make_athlete_rows_2end(
    athlete: str = "Martin Rist",
    e1: int = 301, e2: int = 310, grand: int = 611,
) -> list[CSVRow]:
    """Build a correctly structured 3-row block for a 2-end athlete."""
    return [
        make_row(athlete=athlete, distance="60m",  result=e1),
        make_row(athlete=athlete, distance="60m",  result=e2),
        make_row(athlete=athlete, distance="2x60m", result=grand),
    ]


# ---------------------------------------------------------------------------
# Row-type classifier helpers
# ---------------------------------------------------------------------------

class TestRowClassifiers(unittest.TestCase):

    def test_end_row_plain_distance(self):
        self.assertTrue(_is_end_row(make_row(distance="70m")))
        self.assertTrue(_is_end_row(make_row(distance="60m")))

    def test_half_subtotal_row_2x(self):
        self.assertTrue(_is_half_subtotal_row(make_row(distance="2x70m")))
        self.assertTrue(_is_half_subtotal_row(make_row(distance="2x40m")))

    def test_grand_total_4x_is_not_half(self):
        self.assertFalse(_is_half_subtotal_row(make_row(distance="4x70m")))

    def test_grand_total_mixed_is_not_half(self):
        self.assertFalse(_is_half_subtotal_row(make_row(distance="2x40m+2x30m")))

    def test_grand_total_row_4x(self):
        self.assertTrue(_is_grand_total_row(make_row(distance="4x70m")))

    def test_grand_total_row_mixed(self):
        self.assertTrue(_is_grand_total_row(make_row(distance="2x40m+2x30m")))

    def test_grand_total_2end_round(self):
        # For a 2-end round the grand total uses "2x60m"; since it has no
        # half-subtotals, _is_half_subtotal_row returns True for "2x60m".
        # The writer groups them correctly by context, not by label alone.
        # In a 2-end round there are NO half-subtotal rows — only end rows
        # and the "2x60m" grand total.  The writer handles this correctly.
        self.assertTrue(_is_half_subtotal_row(make_row(distance="2x60m")))

    # Fix #4 — 1440 mixed-distance half labels ("90m+70m") must be recognised
    # as half-subtotals, not grand totals.

    def test_1440_half_label_90m_70m_is_half(self):
        """'90m+70m' is a 1440-round half-subtotal label (contains '+', no 'x')."""
        self.assertTrue(_is_half_subtotal_row(make_row(distance="90m+70m")))

    def test_1440_half_label_50m_30m_is_half(self):
        """'50m+30m' is the second 1440-round half-subtotal label."""
        self.assertTrue(_is_half_subtotal_row(make_row(distance="50m+30m")))

    def test_1440_half_label_is_not_end_row(self):
        self.assertFalse(_is_end_row(make_row(distance="90m+70m")))

    def test_1440_half_label_is_not_grand_total(self):
        self.assertFalse(_is_grand_total_row(make_row(distance="90m+70m")))


# ---------------------------------------------------------------------------
# Required test: correct totals → no warnings
# ---------------------------------------------------------------------------

class TestWriterCorrectTotalsNoWarnings(unittest.TestCase):

    def test_4end_correct_no_warning(self):
        rows = make_athlete_rows_4end()
        with self.assertNoLogs("archery_parser.writer", level="WARNING"):
            mismatches = _verify_athlete_group(rows)
        self.assertEqual(mismatches, 0)

    def test_2end_correct_no_warning(self):
        rows = make_athlete_rows_2end()
        # 2-end rounds: _verify_athlete_group classifies "2x60m" as a
        # half-subtotal, so it checks 301+310 == 611 as the only subtotal,
        # and then there is no separate grand-total row to check.
        # Either way: no mismatches.
        mismatches = _verify_athlete_group(rows)
        self.assertEqual(mismatches, 0)


# ---------------------------------------------------------------------------
# Required test: subtotal mismatch → WARNING logged
# ---------------------------------------------------------------------------

class TestWriterSubtotalMismatchLogsWarning(unittest.TestCase):

    def test_subtotal_mismatch_logged(self):
        # Correct ends: 318 + 293 = 611, but we report 610.
        rows = make_athlete_rows_4end(s1=610)   # wrong subtotal
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            mismatches = _verify_athlete_group(rows)
        self.assertGreater(mismatches, 0)
        self.assertTrue(any("Mismatch" in msg for msg in cm.output))

    def test_subtotal_mismatch_contains_expected_and_actual(self):
        rows = make_athlete_rows_4end(s1=610)
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            _verify_athlete_group(rows)
        combined = " ".join(cm.output)
        # Expected value is 611 (318+293), actual is 610
        self.assertIn("611", combined)
        self.assertIn("610", combined)


# ---------------------------------------------------------------------------
# Required test: grand total mismatch → WARNING logged
# ---------------------------------------------------------------------------

class TestWriterGrandTotalMismatchLogsWarning(unittest.TestCase):

    def test_grand_total_mismatch_logged(self):
        # Correct grand: 611 + 627 = 1238, but we report 1240.
        rows = make_athlete_rows_4end(grand=1240)
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            mismatches = _verify_athlete_group(rows)
        self.assertGreater(mismatches, 0)
        self.assertTrue(any("Mismatch" in msg for msg in cm.output))

    def test_grand_total_mismatch_contains_values(self):
        rows = make_athlete_rows_4end(grand=1240)
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            _verify_athlete_group(rows)
        combined = " ".join(cm.output)
        self.assertIn("1238", combined)
        self.assertIn("1240", combined)


# ---------------------------------------------------------------------------
# Required test: write_csv produces valid UTF-8 CSV with header row
# ---------------------------------------------------------------------------

class TestWriterProducesValidCsvWithHeader(unittest.TestCase):

    def _write_and_read(self, rows: list[CSVRow]) -> list[list[str]]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        try:
            write_csv(rows, path)
            with open(path, encoding="utf-8", newline="") as fh:
                return list(csv.reader(fh))
        finally:
            os.unlink(path)

    def test_header_row_present(self):
        rows = make_athlete_rows_4end()
        data = self._write_and_read(rows)
        self.assertEqual(
            data[0],
            ["Date", "Athlete", "Club", "Bow Type", "Age Class", "Gender",
             "Distance", "Result", "Competition"],
        )

    def test_correct_row_count(self):
        rows = make_athlete_rows_4end()
        data = self._write_and_read(rows)
        # 1 header + 7 data rows
        self.assertEqual(len(data), 8)

    def test_data_row_values(self):
        rows = make_athlete_rows_4end(e1=318)
        data = self._write_and_read(rows)
        # First data row (index 1): result should be 318
        self.assertEqual(data[1][7], "318")    # Result column

    def test_returns_row_count(self):
        rows = make_athlete_rows_4end()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        try:
            count = write_csv(rows, path)
            self.assertEqual(count, 7)
        finally:
            os.unlink(path)

    def test_utf8_encoding(self):
        """Estonian characters in athlete name survive round-trip."""
        rows = [make_row(athlete="Märt Gross", distance="40m", result=294)]
        data = self._write_and_read(rows)
        self.assertEqual(data[1][1], "Märt Gross")


# ---------------------------------------------------------------------------
# Append mode
# ---------------------------------------------------------------------------

class TestWriterAppendMode(unittest.TestCase):

    def test_append_adds_rows_no_second_header(self):
        rows_a = make_athlete_rows_4end("Martin Rist")
        rows_b = make_athlete_rows_4end("Jaan Kask")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        try:
            write_csv(rows_a, path, append=False)
            write_csv(rows_b, path, append=True)
            with open(path, encoding="utf-8", newline="") as fh:
                data = list(csv.reader(fh))
            # 1 header + 7 + 7 data rows = 15 lines total
            self.assertEqual(len(data), 15)
            # Only one header row
            header_count = sum(1 for row in data if row[0] == "Date")
            self.assertEqual(header_count, 1)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Group-by-athlete helper
# ---------------------------------------------------------------------------

class TestGroupByAthlete(unittest.TestCase):

    def test_two_athletes_two_groups(self):
        rows = make_athlete_rows_4end("Martin Rist") + make_athlete_rows_4end("Jaan Kask")
        groups = _group_by_athlete(rows)
        self.assertEqual(len(groups), 2)

    def test_single_athlete_one_group(self):
        rows = make_athlete_rows_4end("Martin Rist")
        groups = _group_by_athlete(rows)
        self.assertEqual(len(groups), 1)

    def test_empty_returns_empty(self):
        self.assertEqual(_group_by_athlete([]), [])


# ---------------------------------------------------------------------------
# Rows are never suppressed even on mismatch
# ---------------------------------------------------------------------------

class TestMismatchedRowsStillWritten(unittest.TestCase):

    def test_all_rows_written_despite_mismatch(self):
        rows = make_athlete_rows_4end(s1=610, grand=1237)  # two mismatches
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        try:
            count = write_csv(rows, path)
            # All 7 rows must still be written
            self.assertEqual(count, 7)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Fix #4 — 1440-round arithmetic verifies correctly with mixed-distance halves
# ---------------------------------------------------------------------------

class Test1440RoundVerification(unittest.TestCase):
    """
    The 1440 round has four distances (90m, 70m, 50m, 30m), each shot once.
    The writer must recognise 'Nm+Mm' labels as half-subtotals so that:
      - half 1 check: end(90m) + end(70m) == subtotal(90m+70m)
      - half 2 check: end(50m) + end(30m) == subtotal(50m+30m)
      - grand total:  subtotal(90m+70m) + subtotal(50m+30m) == grand
    """

    def _make_1440_rows(
        self,
        e90: int = 320, e70: int = 310,
        h1: int = 630,
        e50: int = 295, e30: int = 280,
        h2: int = 575,
        grand: int = 1205,
        athlete: str = "Eve Suitsu",
    ) -> list[CSVRow]:
        return [
            make_row(athlete=athlete, distance="90m",      result=e90),
            make_row(athlete=athlete, distance="70m",      result=e70),
            make_row(athlete=athlete, distance="90m+70m",  result=h1),
            make_row(athlete=athlete, distance="50m",      result=e50),
            make_row(athlete=athlete, distance="30m",      result=e30),
            make_row(athlete=athlete, distance="50m+30m",  result=h2),
            make_row(athlete=athlete, distance="1x90m+1x70m+1x50m+1x30m", result=grand),
        ]

    def test_correct_1440_no_mismatch(self):
        rows = self._make_1440_rows()
        with self.assertNoLogs("archery_parser.writer", level="WARNING"):
            mismatches = _verify_athlete_group(rows)
        self.assertEqual(mismatches, 0)

    def test_1440_half1_mismatch_logged(self):
        rows = self._make_1440_rows(h1=629)  # should be 630
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            mismatches = _verify_athlete_group(rows)
        self.assertGreater(mismatches, 0)
        self.assertTrue(any("Mismatch" in msg for msg in cm.output))

    def test_1440_half2_mismatch_logged(self):
        rows = self._make_1440_rows(h2=574)  # should be 575
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            mismatches = _verify_athlete_group(rows)
        self.assertGreater(mismatches, 0)

    def test_1440_grand_total_mismatch_logged(self):
        rows = self._make_1440_rows(grand=1200)  # should be 1205
        with self.assertLogs("archery_parser.writer", level="WARNING") as cm:
            mismatches = _verify_athlete_group(rows)
        self.assertGreater(mismatches, 0)
        combined = " ".join(cm.output)
        self.assertIn("1205", combined)
        self.assertIn("1200", combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
