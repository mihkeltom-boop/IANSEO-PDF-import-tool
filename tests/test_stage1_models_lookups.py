"""
Stage 1 tests — scaffold, data models, and lookup tables.

Uses the stdlib unittest module (no pytest required) so tests run
in any environment.  When pytest is available, it will discover and
run these tests as well.
"""

import sys
import os
import unittest
from datetime import date

# Allow running directly: python tests/test_stage1_models_lookups.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.models import CompetitionMeta, SectionContext, AthleteRecord, CSVRow
from archery_parser.lookups import BOW_TYPE, AGE_CLASS, GENDER, build_distance_context


class TestPlaceholder(unittest.TestCase):
    """Scaffold sanity check."""

    def test_placeholder(self):
        """Confirms the test suite loads and runs."""
        self.assertTrue(True)


# ---------------------------------------------------------------------------
# CompetitionMeta
# ---------------------------------------------------------------------------

class TestCompetitionMeta(unittest.TestCase):

    def _make(self):
        return CompetitionMeta(
            name="Puiatu CUP 2025",
            organiser="Vana-Võidu Vibuklubi/Viljandi SK",
            event_code="25VV03",
            venue="Puiatu Vibukeskus",
            date_start=date(2025, 9, 13),
            date_end=date(2025, 9, 14),
        )

    def test_instantiation(self):
        meta = self._make()
        self.assertEqual(meta.name, "Puiatu CUP 2025")
        self.assertEqual(meta.event_code, "25VV03")
        self.assertEqual(meta.date_end, date(2025, 9, 14))
        self.assertEqual(meta.organiser, "Vana-Võidu Vibuklubi/Viljandi SK")
        self.assertEqual(meta.venue, "Puiatu Vibukeskus")


# ---------------------------------------------------------------------------
# SectionContext
# ---------------------------------------------------------------------------

class TestSectionContext(unittest.TestCase):

    def test_instantiation(self):
        ctx = SectionContext(
            bow_type="Recurve",
            age_class="Adult",
            gender="Men",
            arrow_count=144,
            distances=["70m", "70m", "70m", "70m"],
            half_labels=["2x70m", "2x70m"],
            total_label="4x70m",
        )
        self.assertEqual(ctx.bow_type, "Recurve")
        self.assertEqual(ctx.arrow_count, 144)
        self.assertEqual(ctx.total_label, "4x70m")
        self.assertEqual(ctx.half_labels, ["2x70m", "2x70m"])


# ---------------------------------------------------------------------------
# AthleteRecord
# ---------------------------------------------------------------------------

class TestAthleteRecord(unittest.TestCase):

    def _make_ctx(self):
        return SectionContext(
            bow_type="Recurve",
            age_class="Adult",
            gender="Men",
            arrow_count=144,
            distances=["70m", "70m", "70m", "70m"],
            half_labels=["2x70m", "2x70m"],
            total_label="4x70m",
        )

    def test_instantiation(self):
        athlete = AthleteRecord(
            position=1,
            target_code="2-001A",
            firstname="Martin",
            lastname="Rist",
            class_code="M",
            club_code="VVVK",
            club_name=None,
            end_scores=[318, 293, 314, 313],
            half_totals=[611, 627],
            grand_total=1238,
            tens_plus_x=26,
            x_count=10,
            section=self._make_ctx(),
        )
        self.assertEqual(athlete.grand_total, 1238)
        self.assertEqual(athlete.club_code, "VVVK")
        self.assertIsNone(athlete.club_name)
        self.assertEqual(len(athlete.end_scores), 4)

    def test_optional_club_fields(self):
        """club_code and club_name can both be set independently."""
        athlete = AthleteRecord(
            position=1,
            target_code="1-014C",
            firstname="Märt",
            lastname="Gross",
            class_code="U15M",
            club_code="SAG",
            club_name="Sagittarius",
            end_scores=[294, 298, 316, 338],
            half_totals=[592, 654],
            grand_total=1246,
            tens_plus_x=35,
            x_count=14,
            section=self._make_ctx(),
        )
        self.assertEqual(athlete.club_code, "SAG")
        self.assertEqual(athlete.club_name, "Sagittarius")


# ---------------------------------------------------------------------------
# CSVRow
# ---------------------------------------------------------------------------

class TestCSVRow(unittest.TestCase):

    def _make(self):
        return CSVRow(
            date="14.09.2025",
            athlete="Martin Rist",
            club="VVVK",
            bow_type="Recurve",
            age_class="Adult",
            gender="Men",
            distance="70m",
            result=318,
            competition="Puiatu CUP 2025",
        )

    def test_instantiation(self):
        row = self._make()
        self.assertEqual(row.result, 318)
        self.assertEqual(row.distance, "70m")

    def test_as_row_returns_9_elements(self):
        flat = self._make().as_row()
        self.assertEqual(len(flat), 9)

    def test_as_row_column_order(self):
        flat = self._make().as_row()
        self.assertEqual(flat[0], "14.09.2025")        # Date
        self.assertEqual(flat[1], "Martin Rist")       # Athlete
        self.assertEqual(flat[2], "VVVK")              # Club
        self.assertEqual(flat[3], "Recurve")           # Bow Type
        self.assertEqual(flat[4], "Adult")             # Age Class
        self.assertEqual(flat[5], "Men")               # Gender
        self.assertEqual(flat[6], "70m")               # Distance
        self.assertEqual(flat[7], 318)                 # Result
        self.assertEqual(flat[8], "Puiatu CUP 2025")   # Competition


# ---------------------------------------------------------------------------
# BOW_TYPE lookup (Section 7.1)
# ---------------------------------------------------------------------------

class TestBowTypeLookup(unittest.TestCase):

    CASES = [
        ("Sportvibu",   "Recurve"),
        ("Plokkvibu",   "Compound"),
        ("Vaistuvibu",  "Barebow"),
        ("Pikkvibu",    "Longbow"),
        ("Harrastajad", "Recurve"),
    ]

    def test_all_bow_types(self):
        for prefix, expected in self.CASES:
            with self.subTest(prefix=prefix):
                self.assertEqual(BOW_TYPE[prefix], expected)

    def test_completeness(self):
        self.assertEqual(
            set(BOW_TYPE.keys()),
            {"Sportvibu", "Plokkvibu", "Vaistuvibu", "Pikkvibu", "Harrastajad"},
        )


# ---------------------------------------------------------------------------
# AGE_CLASS lookup (Section 7.2)
# ---------------------------------------------------------------------------

class TestAgeClassLookup(unittest.TestCase):

    CASES = [
        ("M",    "Adult"),  ("W",    "Adult"),
        ("U21M", "U21"),    ("U21W", "U21"),
        ("U18M", "U18"),    ("U18W", "U18"),
        ("U15M", "U15"),    ("U15W", "U15"),
        ("U13M", "U13"),    ("U13W", "U13"),
        ("U10M", "U10"),    ("U10W", "U10"),
        ("50M",  "+50"),    ("50W",  "+50"),
        ("HM",   "Adult"),  ("HW",   "Adult"),
    ]

    def test_all_age_classes(self):
        for code, expected in self.CASES:
            with self.subTest(code=code):
                self.assertEqual(AGE_CLASS[code], expected)


# ---------------------------------------------------------------------------
# GENDER lookup (Section 7.3)
# ---------------------------------------------------------------------------

class TestGenderLookup(unittest.TestCase):

    CASES = [
        ("M",    "Men"),   ("W",    "Women"),
        ("U21M", "Men"),   ("U21W", "Women"),
        ("U18M", "Men"),   ("U18W", "Women"),
        ("U15M", "Men"),   ("U15W", "Women"),
        ("U13M", "Men"),   ("U13W", "Women"),
        ("U10M", "Men"),   ("U10W", "Women"),
        ("50M",  "Men"),   ("50W",  "Women"),
        ("HM",   "Men"),   ("HW",   "Women"),
    ]

    def test_all_genders(self):
        for code, expected in self.CASES:
            with self.subTest(code=code):
                self.assertEqual(GENDER[code], expected)

    def test_men_codes_end_with_m(self):
        men_codes = [k for k, v in GENDER.items() if v == "Men"]
        self.assertTrue(all(k.endswith("M") for k in men_codes))

    def test_women_codes_end_with_w(self):
        women_codes = [k for k, v in GENDER.items() if v == "Women"]
        self.assertTrue(all(k.endswith("W") for k in women_codes))


# ---------------------------------------------------------------------------
# build_distance_context (Section 7.4)
# ---------------------------------------------------------------------------

class TestBuildDistanceContext(unittest.TestCase):

    def test_uniform_4end_70m(self):
        result = build_distance_context(["70m", "70m", "70m", "70m"])
        self.assertEqual(result["half_labels"], ["2x70m", "2x70m"])
        self.assertEqual(result["total_label"], "4x70m")

    def test_mixed_4end_40m_30m(self):
        result = build_distance_context(["40m", "40m", "30m", "30m"])
        self.assertEqual(result["half_labels"], ["2x40m", "2x30m"])
        self.assertEqual(result["total_label"], "2x40m+2x30m")

    def test_2end_no_half_labels(self):
        result = build_distance_context(["60m", "60m"])
        self.assertEqual(result["half_labels"], [])
        self.assertEqual(result["total_label"], "2x60m")

    def test_uniform_4end_50m(self):
        result = build_distance_context(["50m", "50m", "50m", "50m"])
        self.assertEqual(result["half_labels"], ["2x50m", "2x50m"])
        self.assertEqual(result["total_label"], "4x50m")

    def test_mixed_u15_barebow_30m_15m(self):
        result = build_distance_context(["30m", "30m", "15m", "15m"])
        self.assertEqual(result["half_labels"], ["2x30m", "2x15m"])
        self.assertEqual(result["total_label"], "2x30m+2x15m")

    def test_mixed_u13_25m_15m(self):
        result = build_distance_context(["25m", "25m", "15m", "15m"])
        self.assertEqual(result["half_labels"], ["2x25m", "2x15m"])
        self.assertEqual(result["total_label"], "2x25m+2x15m")

    def test_harrastajad_4x30m(self):
        result = build_distance_context(["30m", "30m", "30m", "30m"])
        self.assertEqual(result["half_labels"], ["2x30m", "2x30m"])
        self.assertEqual(result["total_label"], "4x30m")

    def test_2end_10m_u10(self):
        result = build_distance_context(["10m", "10m"])
        self.assertEqual(result["half_labels"], [])
        self.assertEqual(result["total_label"], "2x10m")

    def test_odd_length_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_distance_context(["70m", "70m", "70m"])

    def test_4end_60m_u18(self):
        result = build_distance_context(["60m", "60m", "60m", "60m"])
        self.assertEqual(result["half_labels"], ["2x60m", "2x60m"])
        self.assertEqual(result["total_label"], "4x60m")


if __name__ == "__main__":
    unittest.main(verbosity=2)
