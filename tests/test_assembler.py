"""
Stage 4 tests — assembler.py

All tests use synthetic Word/RawSection data — no real PDF required.
Covers all required test cases from the Stage 4 prompt plus edge cases.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.reader import Word
from archery_parser.models import SectionContext, AthleteRecord
from archery_parser.detector import RawSection
from archery_parser.assembler import (
    assemble_athletes,
    _parse_scores,
    _parse_club,
    _collect_integers,
    _is_positive_int,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_word(text: str, x: float = 0.0, y: float = 0.0) -> Word:
    return Word(text=text, x0=x, y0=y, x1=x + len(text) * 6.0, y1=y + 10.0)


def make_line(*texts: str, y: float = 0.0) -> list[Word]:
    """Build a line of Words from plain text tokens, auto-spaced."""
    words = []
    x = 10.0
    for text in texts:
        words.append(make_word(text, x=x, y=y))
        x += len(text) * 6.0 + 4.0
    return words


def make_section(
    bow_type: str = "Recurve",
    age_class: str = "Adult",
    gender: str = "Men",
    arrow_count: int = 144,
    distances: list[str] | None = None,
    half_labels: list[str] | None = None,
    total_label: str = "4x70m",
    lines: list[list[Word]] | None = None,
) -> RawSection:
    if distances is None:
        distances = ["70m", "70m", "70m", "70m"]
    if half_labels is None:
        half_labels = ["2x70m", "2x70m"]
    ctx = SectionContext(
        bow_type=bow_type,
        age_class=age_class,
        gender=gender,
        arrow_count=arrow_count,
        distances=distances,
        half_labels=half_labels,
        total_label=total_label,
    )
    return RawSection(context=ctx, lines=lines or [])


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------

class TestIsPositiveInt(unittest.TestCase):

    def test_positive(self):
        self.assertTrue(_is_positive_int("1"))
        self.assertTrue(_is_positive_int("12"))

    def test_zero_false(self):
        self.assertFalse(_is_positive_int("0"))

    def test_text_false(self):
        self.assertFalse(_is_positive_int("RIST"))

    def test_target_code_false(self):
        self.assertFalse(_is_positive_int("2-001A"))


class TestCollectIntegers(unittest.TestCase):

    def test_plain_integers(self):
        self.assertEqual(_collect_integers(["318", "293", "611"]), [318, 293, 611])

    def test_thousands_separator(self):
        self.assertEqual(_collect_integers(["1,238"]), [1238])

    def test_skips_non_numeric(self):
        self.assertEqual(_collect_integers(["RIST", "Martin", "318"]), [318])

    def test_empty(self):
        self.assertEqual(_collect_integers([]), [])


class TestParseScores(unittest.TestCase):
    """Tests for the internal _parse_scores() helper."""

    # 2-end (72-arrow) athlete: 5 integers total
    def test_2_end_grand_total(self):
        end_scores, half_totals, grand_total = _parse_scores([301, 310, 611, 12, 3])
        self.assertEqual(grand_total, 611)

    def test_2_end_end_scores(self):
        end_scores, half_totals, grand_total = _parse_scores([301, 310, 611, 12, 3])
        self.assertEqual(end_scores, [301, 310])

    def test_2_end_no_half_totals(self):
        end_scores, half_totals, grand_total = _parse_scores([301, 310, 611, 12, 3])
        self.assertEqual(half_totals, [])

    # 4-end (144-arrow) athlete: 9 integers total
    def test_4_end_grand_total(self):
        end_scores, half_totals, grand_total = _parse_scores(
            [318, 293, 611, 314, 313, 627, 1238, 26, 10]
        )
        self.assertEqual(grand_total, 1238)

    def test_4_end_end_scores(self):
        end_scores, half_totals, grand_total = _parse_scores(
            [318, 293, 611, 314, 313, 627, 1238, 26, 10]
        )
        self.assertEqual(end_scores, [318, 293, 314, 313])

    def test_4_end_half_totals(self):
        end_scores, half_totals, grand_total = _parse_scores(
            [318, 293, 611, 314, 313, 627, 1238, 26, 10]
        )
        self.assertEqual(half_totals, [611, 627])

    # 8-end (288-arrow) athlete
    def test_8_end_grand_total(self):
        # 8 ends × 3 groups of [end, end, sub] + grand + 10+X + X = 8+4+1+2 = 15
        ints = [
            300, 295, 595,   # ends 1-2, sub1
            310, 305, 615,   # ends 3-4, sub2
            298, 302, 600,   # ends 5-6, sub3
            308, 312, 620,   # ends 7-8, sub4
            2430, 30, 12     # grand, 10+X, X
        ]
        end_scores, half_totals, grand_total = _parse_scores(ints)
        self.assertEqual(grand_total, 2430)
        self.assertEqual(len(end_scores), 8)
        self.assertEqual(end_scores, [300, 295, 310, 305, 298, 302, 308, 312])
        self.assertEqual(half_totals, [595, 615, 600, 620])


class TestParseClub(unittest.TestCase):

    # Required: code only (4-char all-caps → club_code, club_name None)
    def test_club_code_only_4chars(self):
        code, name = _parse_club(["VVVK"])
        self.assertEqual(code, "VVVK")
        self.assertIsNone(name)

    # Required: name only (longer token → club_name, club_code None)
    def test_club_name_only_longer_token(self):
        code, name = _parse_club(["Sagittarius"])
        self.assertIsNone(code)
        self.assertEqual(name, "Sagittarius")

    # Required: both fields (two tokens → code + name)
    def test_club_both_two_tokens(self):
        code, name = _parse_club(["SAG", "Sagittarius"])
        self.assertEqual(code, "SAG")
        self.assertEqual(name, "Sagittarius")

    # Multi-word club name after a code
    def test_club_code_and_multiword_name(self):
        code, name = _parse_club(["TLVK", "Tallinna", "Vibukool"])
        self.assertEqual(code, "TLVK")
        self.assertEqual(name, "Tallinna Vibukool")

    # 3-char code (e.g. SAG)
    def test_club_code_3chars(self):
        code, name = _parse_club(["SAG"])
        self.assertEqual(code, "SAG")
        self.assertIsNone(name)

    # Empty tokens
    def test_empty_tokens(self):
        code, name = _parse_club([])
        self.assertIsNone(code)
        self.assertIsNone(name)

    # Mixed-case single token → name only
    def test_mixed_case_single_token(self):
        code, name = _parse_club(["VibuKlubi"])
        self.assertIsNone(code)
        self.assertEqual(name, "VibuKlubi")


# ---------------------------------------------------------------------------
# Required test: 1-line athlete (2 ends, 72-arrow half-round)
# ---------------------------------------------------------------------------

class TestOneLine(unittest.TestCase):

    def _build(self):
        section = make_section(
            bow_type="Recurve",
            age_class="+50",
            gender="Men",
            arrow_count=72,
            distances=["60m", "60m"],
            half_labels=[],
            total_label="2x60m",
            lines=[
                make_line("1", "3-002B", "TAMM", "Jüri", "50M", "VVVK", "301", "310", "611", "12", "3", y=50.0),
            ],
        )
        return assemble_athletes([section])

    def test_1_line_athlete_produces_one_record(self):
        records = self._build()
        self.assertEqual(len(records), 1)

    def test_1_line_two_end_scores(self):
        records = self._build()
        self.assertEqual(records[0].end_scores, [301, 310])

    def test_1_line_no_half_totals(self):
        records = self._build()
        self.assertEqual(records[0].half_totals, [])

    def test_1_line_grand_total(self):
        records = self._build()
        self.assertEqual(records[0].grand_total, 611)

    def test_1_line_tens_plus_x(self):
        records = self._build()
        self.assertEqual(records[0].tens_plus_x, 12)

    def test_1_line_x_count(self):
        records = self._build()
        self.assertEqual(records[0].x_count, 3)


# ---------------------------------------------------------------------------
# Required test: 2-line athlete (4 ends, 144-arrow)
# ---------------------------------------------------------------------------

class TestTwoLine(unittest.TestCase):

    def _build(self):
        section = make_section(lines=[
            make_line("1", "2-001A", "RIST", "Martin", "M", "VVVK",
                      "318", "293", "611", y=50.0),
            make_line("314", "313", "627", "1,238", "26", "10", y=62.0),
        ])
        return assemble_athletes([section])

    def test_2_line_athlete_produces_one_record(self):
        records = self._build()
        self.assertEqual(len(records), 1)

    def test_2_line_four_end_scores(self):
        records = self._build()
        self.assertEqual(records[0].end_scores, [318, 293, 314, 313])

    def test_2_line_half_totals(self):
        records = self._build()
        self.assertEqual(records[0].half_totals, [611, 627])

    def test_2_line_grand_total(self):
        records = self._build()
        self.assertEqual(records[0].grand_total, 1238)

    def test_2_line_thousands_separator_handled(self):
        """Grand total "1,238" parses to integer 1238."""
        records = self._build()
        self.assertEqual(records[0].grand_total, 1238)

    def test_2_line_position(self):
        records = self._build()
        self.assertEqual(records[0].position, 1)

    def test_2_line_firstname_lastname(self):
        records = self._build()
        self.assertEqual(records[0].firstname, "Martin")
        self.assertEqual(records[0].lastname, "RIST")


# ---------------------------------------------------------------------------
# Required test: 4-line athlete (8 ends, 288-arrow)
# ---------------------------------------------------------------------------

class TestFourLine(unittest.TestCase):

    def _build(self):
        ints = [
            "300", "295", "595",
            "310", "305", "615",
            "298", "302", "600",
            "308", "312", "620",
            "2,430", "30", "12",
        ]
        section = make_section(
            arrow_count=288,
            distances=["70m"] * 8,
            half_labels=["2x70m"] * 4,
            total_label="8x70m",
            lines=[
                make_line("1", "1-001A", "KASK", "Jaan", "M", "VVVK",
                          ints[0], ints[1], ints[2], y=10.0),
                make_line(ints[3], ints[4], ints[5], y=22.0),
                make_line(ints[6], ints[7], ints[8], y=34.0),
                make_line(ints[9], ints[10], ints[11], ints[12], ints[13], ints[14], y=46.0),
            ],
        )
        return assemble_athletes([section])

    def test_4_line_eight_end_scores(self):
        records = self._build()
        self.assertEqual(len(records[0].end_scores), 8)

    def test_4_line_end_scores_values(self):
        records = self._build()
        self.assertEqual(records[0].end_scores, [300, 295, 310, 305, 298, 302, 308, 312])

    def test_4_line_four_half_totals(self):
        records = self._build()
        self.assertEqual(records[0].half_totals, [595, 615, 600, 620])

    def test_4_line_grand_total(self):
        records = self._build()
        self.assertEqual(records[0].grand_total, 2430)


# ---------------------------------------------------------------------------
# Required test: target code stripped from name
# ---------------------------------------------------------------------------

class TestTargetCodeStripped(unittest.TestCase):

    def _build(self):
        section = make_section(lines=[
            make_line("1", "2-001A", "RIST", "Martin", "M", "VVVK",
                      "318", "293", "611", y=50.0),
            make_line("314", "313", "627", "1,238", "26", "10", y=62.0),
        ])
        return assemble_athletes([section])[0]

    def test_target_code_not_in_lastname(self):
        record = self._build()
        self.assertNotIn("2-001A", record.lastname)

    def test_target_code_not_in_firstname(self):
        record = self._build()
        self.assertNotIn("2-001A", record.firstname)

    def test_target_code_stored(self):
        """Target code is stored on the record for debugging."""
        record = self._build()
        self.assertEqual(record.target_code, "2-001A")

    def test_lastname_is_rist(self):
        record = self._build()
        self.assertEqual(record.lastname, "RIST")

    def test_firstname_is_martin(self):
        record = self._build()
        self.assertEqual(record.firstname, "Martin")


# ---------------------------------------------------------------------------
# Required test: club_code only
# ---------------------------------------------------------------------------

class TestClubCodeOnly(unittest.TestCase):

    def _build(self):
        section = make_section(lines=[
            make_line("1", "2-001A", "RIST", "Martin", "M", "VVVK",
                      "318", "293", "611", y=50.0),
            make_line("314", "313", "627", "1,238", "26", "10", y=62.0),
        ])
        return assemble_athletes([section])[0]

    def test_club_code_set(self):
        self.assertEqual(self._build().club_code, "VVVK")

    def test_club_name_none(self):
        self.assertIsNone(self._build().club_name)


# ---------------------------------------------------------------------------
# Required test: club name only
# ---------------------------------------------------------------------------

class TestClubNameOnly(unittest.TestCase):

    def _build(self):
        # Single token "Sagittarius" — mixed-case → full name, no code
        section = make_section(lines=[
            make_line("1", "1-014C", "GROSS", "Märt", "U15M", "Sagittarius",
                      "294", "298", "592", y=50.0),
            make_line("316", "338", "654", "1,246", "35", "14", y=62.0),
        ])
        return assemble_athletes([section])[0]

    def test_club_code_none(self):
        self.assertIsNone(self._build().club_code)

    def test_club_name_set(self):
        self.assertEqual(self._build().club_name, "Sagittarius")


# ---------------------------------------------------------------------------
# Required test: club with both code and name
# ---------------------------------------------------------------------------

class TestClubBoth(unittest.TestCase):

    def _build(self):
        # External club: "SAG Sagittarius"
        section = make_section(lines=[
            make_line("1", "1-014C", "GROSS", "Märt", "U15M",
                      "SAG", "Sagittarius",
                      "294", "298", "592", y=50.0),
            make_line("316", "338", "654", "1,246", "35", "14", y=62.0),
        ])
        return assemble_athletes([section])[0]

    def test_club_code_set(self):
        self.assertEqual(self._build().club_code, "SAG")

    def test_club_name_set(self):
        self.assertEqual(self._build().club_name, "Sagittarius")


# ---------------------------------------------------------------------------
# Required test: last athlete in section is not dropped
# ---------------------------------------------------------------------------

class TestLastAthleteInSectionFinalised(unittest.TestCase):

    def test_three_athletes_all_captured(self):
        section = make_section(lines=[
            make_line("1", "2-001A", "RIST",  "Martin", "M", "VVVK",
                      "318", "293", "611", y=10.0),
            make_line("314", "313", "627", "1,238", "26", "10", y=22.0),
            make_line("2", "2-002B", "KASK",  "Jaan",   "M", "VVVK",
                      "290", "285", "575", y=34.0),
            make_line("280", "295", "575", "1,150", "15", "5",  y=46.0),
            make_line("3", "2-003C", "TAMM",  "Peeter", "M", "VVVK",
                      "270", "275", "545", y=58.0),
            make_line("260", "265", "525", "1,070", "10", "3",  y=70.0),
        ])
        records = assemble_athletes([section])
        self.assertEqual(len(records), 3)

    def test_last_athlete_grand_total_correct(self):
        section = make_section(lines=[
            make_line("1", "2-001A", "RIST", "Martin", "M", "VVVK",
                      "318", "293", "611", y=10.0),
            make_line("314", "313", "627", "1,238", "26", "10", y=22.0),
            make_line("2", "2-002B", "KASK", "Jaan", "M", "VVVK",
                      "290", "285", "575", y=34.0),
            make_line("280", "295", "575", "1,150", "15", "5", y=46.0),
        ])
        records = assemble_athletes([section])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1].grand_total, 1150)


# ---------------------------------------------------------------------------
# Additional integration-level tests
# ---------------------------------------------------------------------------

class TestMultipleSections(unittest.TestCase):

    def test_athletes_across_two_sections(self):
        s1 = make_section(
            bow_type="Recurve", gender="Men",
            lines=[
                make_line("1", "2-001A", "RIST",  "Martin", "M", "VVVK",
                          "318", "293", "611", y=10.0),
                make_line("314", "313", "627", "1,238", "26", "10", y=22.0),
            ],
        )
        s2 = make_section(
            bow_type="Compound", gender="Women",
            lines=[
                make_line("1", "2-005C", "ILVES", "Kristi", "W", "VVVK",
                          "340", "345", "685", y=10.0),
                make_line("350", "355", "705", "1,390", "42", "18", y=22.0),
            ],
        )
        records = assemble_athletes([s1, s2])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].lastname, "RIST")
        self.assertEqual(records[1].lastname, "ILVES")

    def test_section_context_attached(self):
        """Each AthleteRecord's .section references the correct SectionContext."""
        s1 = make_section(bow_type="Recurve", gender="Men",
            lines=[
                make_line("1", "2-001A", "RIST", "Martin", "M", "VVVK",
                          "318", "293", "611", y=10.0),
                make_line("314", "313", "627", "1,238", "26", "10", y=22.0),
            ],
        )
        records = assemble_athletes([s1])
        self.assertEqual(records[0].section.bow_type, "Recurve")
        self.assertEqual(records[0].section.gender, "Men")


class TestExternalClubMultiword(unittest.TestCase):
    """Athletes from clubs with multi-word full names parse correctly."""

    def test_tlvk_tallinna_vibukool(self):
        section = make_section(lines=[
            make_line("1", "1-003A", "SEPP", "Tiina", "W",
                      "TLVK", "Tallinna", "Vibukool",
                      "330", "325", "655", y=10.0),
            make_line("320", "315", "635", "1,290", "38", "15", y=22.0),
        ])
        records = assemble_athletes([section])
        self.assertEqual(records[0].club_code, "TLVK")
        self.assertEqual(records[0].club_name, "Tallinna Vibukool")


class TestClassCodes(unittest.TestCase):
    """Verify various class codes are correctly parsed."""

    def _make_athlete(self, class_code: str) -> AthleteRecord:
        section = make_section(lines=[
            make_line("1", "1-001A", "TEST", "Person", class_code, "VVVK",
                      "300", "300", "600", y=10.0),
            make_line("300", "300", "600", "1,200", "20", "5", y=22.0),
        ])
        return assemble_athletes([section])[0]

    def test_class_code_m(self):
        self.assertEqual(self._make_athlete("M").class_code, "M")

    def test_class_code_w(self):
        self.assertEqual(self._make_athlete("W").class_code, "W")

    def test_class_code_u18m(self):
        self.assertEqual(self._make_athlete("U18M").class_code, "U18M")

    def test_class_code_50m(self):
        self.assertEqual(self._make_athlete("50M").class_code, "50M")

    def test_class_code_hm(self):
        self.assertEqual(self._make_athlete("HM").class_code, "HM")


if __name__ == "__main__":
    unittest.main(verbosity=2)
