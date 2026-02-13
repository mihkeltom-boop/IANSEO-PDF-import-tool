"""
Stage 5 tests — transformer.py

All tests use synthetic AthleteRecord / CompetitionMeta data.
Covers all required test cases from the Stage 5 prompt.
"""

import sys
import os
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.models import AthleteRecord, CompetitionMeta, CSVRow, SectionContext
from archery_parser.transformer import (
    transform,
    _format_date,
    _format_name,
    _format_club,
    _expand_athlete,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_meta(
    name: str = "Puiatu CUP 2025",
    date_end: date = date(2025, 9, 14),
) -> CompetitionMeta:
    return CompetitionMeta(
        name=name,
        organiser="VVVK",
        event_code="25VV03",
        venue="Puiatu",
        date_start=date(2025, 9, 13),
        date_end=date_end,
    )


def make_section(
    bow_type: str = "Recurve",
    age_class: str = "Adult",
    gender: str = "Men",
    arrow_count: int = 144,
    distances: list[str] | None = None,
    half_labels: list[str] | None = None,
    total_label: str = "4x70m",
) -> SectionContext:
    if distances is None:
        distances = ["70m", "70m", "70m", "70m"]
    if half_labels is None:
        half_labels = ["2x70m", "2x70m"]
    return SectionContext(
        bow_type=bow_type,
        age_class=age_class,
        gender=gender,
        arrow_count=arrow_count,
        distances=distances,
        half_labels=half_labels,
        total_label=total_label,
    )


def make_record(
    firstname: str = "Martin",
    lastname: str = "RIST",
    class_code: str = "M",
    club_code: str | None = "VVVK",
    club_name: str | None = None,
    end_scores: list[int] | None = None,
    half_totals: list[int] | None = None,
    grand_total: int = 1238,
    tens_plus_x: int = 26,
    x_count: int = 10,
    section: SectionContext | None = None,
) -> AthleteRecord:
    if end_scores is None:
        end_scores = [318, 293, 314, 313]
    if half_totals is None:
        half_totals = [611, 627]
    if section is None:
        section = make_section()
    return AthleteRecord(
        position=1,
        target_code="2-001A",
        firstname=firstname,
        lastname=lastname,
        class_code=class_code,
        club_code=club_code,
        club_name=club_name,
        end_scores=end_scores,
        half_totals=half_totals,
        grand_total=grand_total,
        tens_plus_x=tens_plus_x,
        x_count=x_count,
        section=section,
    )


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------

class TestFormatDate(unittest.TestCase):

    def test_formats_correctly(self):
        self.assertEqual(_format_date(date(2025, 9, 14)), "14.09.2025")

    def test_zero_pads_day_and_month(self):
        self.assertEqual(_format_date(date(2025, 1, 5)), "05.01.2025")


class TestFormatName(unittest.TestCase):

    def test_reverses_and_title_cases(self):
        self.assertEqual(_format_name("Martin", "RIST"), "Martin Rist")

    def test_all_caps_lastname_title_cased(self):
        self.assertEqual(_format_name("Jaan", "KASK"), "Jaan Kask")

    def test_already_title_case(self):
        self.assertEqual(_format_name("Kristi", "Ilves"), "Kristi Ilves")

    def test_firstname_title_cased(self):
        self.assertEqual(_format_name("märt", "GROSS"), "Märt Gross")


class TestFormatClub(unittest.TestCase):

    def test_code_only(self):
        self.assertEqual(_format_club("VVVK", None), "VVVK")

    def test_name_only(self):
        self.assertEqual(_format_club(None, "Sagittarius"), "Sagittarius")

    def test_both(self):
        self.assertEqual(_format_club("TLVK", "Tallinna Vibukool"), "TLVK Tallinna Vibukool")

    def test_neither(self):
        self.assertEqual(_format_club(None, None), "")


# ---------------------------------------------------------------------------
# Required test: 2-end athlete expands to 3 rows
# ---------------------------------------------------------------------------

class TestExpands2EndTo3Rows(unittest.TestCase):

    def _build(self):
        ctx = make_section(
            arrow_count=72,
            distances=["60m", "60m"],
            half_labels=[],
            total_label="2x60m",
        )
        record = make_record(
            end_scores=[301, 310],
            half_totals=[],
            grand_total=611,
            section=ctx,
        )
        return _expand_athlete(record, make_meta())

    def test_exactly_3_rows(self):
        self.assertEqual(len(self._build()), 3)

    def test_row_distances(self):
        rows = self._build()
        self.assertEqual(rows[0].distance, "60m")
        self.assertEqual(rows[1].distance, "60m")
        self.assertEqual(rows[2].distance, "2x60m")

    def test_row_results(self):
        rows = self._build()
        self.assertEqual(rows[0].result, 301)
        self.assertEqual(rows[1].result, 310)
        self.assertEqual(rows[2].result, 611)

    def test_no_half_subtotal_row(self):
        rows = self._build()
        distances = [r.distance for r in rows]
        # There should be no intermediate "2x…" — the only "2x60m" is the grand total
        self.assertEqual(distances.count("2x60m"), 1)
        self.assertEqual(rows[2].distance, "2x60m")  # grand total


# ---------------------------------------------------------------------------
# Required test: 4-end athlete expands to 7 rows
# ---------------------------------------------------------------------------

class TestExpands4EndTo7Rows(unittest.TestCase):

    def _build(self):
        return _expand_athlete(make_record(), make_meta())

    def test_exactly_7_rows(self):
        self.assertEqual(len(self._build()), 7)

    def test_row_distances_in_order(self):
        rows = self._build()
        expected = ["70m", "70m", "2x70m", "70m", "70m", "2x70m", "4x70m"]
        self.assertEqual([r.distance for r in rows], expected)

    def test_row_results_in_order(self):
        rows = self._build()
        expected = [318, 293, 611, 314, 313, 627, 1238]
        self.assertEqual([r.result for r in rows], expected)

    def test_grand_total_last(self):
        rows = self._build()
        self.assertEqual(rows[-1].distance, "4x70m")
        self.assertEqual(rows[-1].result, 1238)


# ---------------------------------------------------------------------------
# Required test: mixed round (2×40m + 2×30m) → 7 rows, correct labels
# ---------------------------------------------------------------------------

class TestExpands4EndMixedRound(unittest.TestCase):

    def _build(self):
        ctx = make_section(
            age_class="U15",
            distances=["40m", "40m", "30m", "30m"],
            half_labels=["2x40m", "2x30m"],
            total_label="2x40m+2x30m",
        )
        record = make_record(
            firstname="Märt",
            lastname="GROSS",
            class_code="U15M",
            club_code="SAG",
            club_name="Sagittarius",
            end_scores=[294, 298, 316, 338],
            half_totals=[592, 654],
            grand_total=1246,
            section=ctx,
        )
        return _expand_athlete(record, make_meta())

    def test_exactly_7_rows(self):
        self.assertEqual(len(self._build()), 7)

    def test_distances(self):
        rows = self._build()
        expected = ["40m", "40m", "2x40m", "30m", "30m", "2x30m", "2x40m+2x30m"]
        self.assertEqual([r.distance for r in rows], expected)

    def test_results(self):
        rows = self._build()
        expected = [294, 298, 592, 316, 338, 654, 1246]
        self.assertEqual([r.result for r in rows], expected)


# ---------------------------------------------------------------------------
# Required test: name reformatted
# ---------------------------------------------------------------------------

class TestNameReformatted(unittest.TestCase):

    def test_all_caps_lastname_title_cased(self):
        rows = _expand_athlete(make_record(firstname="Martin", lastname="RIST"), make_meta())
        self.assertTrue(all(r.athlete == "Martin Rist" for r in rows))

    def test_firstname_first(self):
        rows = _expand_athlete(make_record(firstname="Kristi", lastname="ILVES"), make_meta())
        self.assertEqual(rows[0].athlete, "Kristi Ilves")


# ---------------------------------------------------------------------------
# Required test: club field permutations
# ---------------------------------------------------------------------------

class TestClubCodeOnly(unittest.TestCase):

    def test_club_field(self):
        rows = _expand_athlete(
            make_record(club_code="VVVK", club_name=None), make_meta()
        )
        self.assertTrue(all(r.club == "VVVK" for r in rows))


class TestClubBoth(unittest.TestCase):

    def test_club_field_code_and_name(self):
        rows = _expand_athlete(
            make_record(club_code="SAG", club_name="Sagittarius"), make_meta()
        )
        self.assertTrue(all(r.club == "SAG Sagittarius" for r in rows))


class TestClubNameOnly(unittest.TestCase):

    def test_club_field_name_only(self):
        rows = _expand_athlete(
            make_record(club_code=None, club_name="Sagittarius"), make_meta()
        )
        self.assertTrue(all(r.club == "Sagittarius" for r in rows))


# ---------------------------------------------------------------------------
# Required test: all bow type lookups produce correct Bow Type column
# ---------------------------------------------------------------------------

class TestAllBowTypeLookups(unittest.TestCase):

    BOW_TYPES = ["Recurve", "Compound", "Barebow", "Longbow"]

    def test_all_bow_types(self):
        for bt in self.BOW_TYPES:
            with self.subTest(bow_type=bt):
                ctx = make_section(bow_type=bt)
                record = make_record(section=ctx)
                rows = _expand_athlete(record, make_meta())
                self.assertTrue(all(r.bow_type == bt for r in rows))


# ---------------------------------------------------------------------------
# Required test: all age class lookups
# ---------------------------------------------------------------------------

class TestAllAgeClassLookups(unittest.TestCase):

    AGE_CLASSES = ["Adult", "U21", "U18", "U15", "U13", "U10", "+50"]

    def test_all_age_classes(self):
        for ac in self.AGE_CLASSES:
            with self.subTest(age_class=ac):
                ctx = make_section(age_class=ac)
                record = make_record(section=ctx)
                rows = _expand_athlete(record, make_meta())
                self.assertTrue(all(r.age_class == ac for r in rows))


# ---------------------------------------------------------------------------
# Date and Competition columns
# ---------------------------------------------------------------------------

class TestDateAndCompetitionColumns(unittest.TestCase):

    def test_date_is_end_date(self):
        meta = make_meta(date_end=date(2025, 9, 14))
        rows = _expand_athlete(make_record(), meta)
        self.assertTrue(all(r.date == "14.09.2025" for r in rows))

    def test_competition_name_repeated(self):
        meta = make_meta(name="Puiatu CUP 2025")
        rows = _expand_athlete(make_record(), meta)
        self.assertTrue(all(r.competition == "Puiatu CUP 2025" for r in rows))


# ---------------------------------------------------------------------------
# transform() public API
# ---------------------------------------------------------------------------

class TestTransformPublicAPI(unittest.TestCase):

    def test_multiple_athletes_flat_list(self):
        meta = make_meta()
        records = [make_record(firstname="Martin", lastname="RIST"),
                   make_record(firstname="Jaan",   lastname="KASK")]
        rows = transform(records, meta)
        # Each 4-end athlete → 7 rows; 2 athletes → 14
        self.assertEqual(len(rows), 14)

    def test_empty_records(self):
        self.assertEqual(transform([], make_meta()), [])

    def test_all_rows_are_csv_row_instances(self):
        rows = transform([make_record()], make_meta())
        self.assertTrue(all(isinstance(r, CSVRow) for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
