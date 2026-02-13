"""
Stage 3 tests — detector.py

All tests construct synthetic Word-line data (no real PDF required).
Tests cover competition-header parsing, uniform and mixed section
detection, 72-arrow half-rounds, and graceful handling of unknown
section titles.
"""

import sys
import os
import logging
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.reader import Word
from archery_parser.detector import (
    RawSection,
    _parse_competition_header,
    _is_column_header_line,
    _extract_distances_from_line,
    _match_after_arrows,
    _starts_with_positive_int,
    detect_sections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_line(*texts: str, y: float = 0.0) -> list[Word]:
    """Build a logical line of Word objects from plain text tokens."""
    words = []
    x = 10.0
    for text in texts:
        words.append(Word(text=text, x0=x, y0=y, x1=x + len(text) * 6, y1=y + 10.0))
        x += len(text) * 6 + 4
    return words


def _make_full_stream(
    competition_lines: list[list[Word]],
    sections: list[dict],
) -> list[list[Word]]:
    """
    Build a complete synthetic line stream from competition header lines
    and a list of section descriptors.

    Each section dict has:
        arrow_count: int
        title_tokens: list[str]         e.g. ["Sportvibu", "Mehed"]
        col_hdr_rows: list[list[str]]   e.g. [["70m-1","70m-2","Tot."],
                                               ["70m-3","70m-4","Tot."],
                                               ["Tot.","10+X","X"]]
        athlete_rows: list[list[str]]   e.g. [["1","2-001A","RIST",...],
                                               ["314","313","627",...]]
    """
    lines = list(competition_lines)
    for s in sections:
        lines.append(make_line("After", str(s["arrow_count"]), "Arrows"))
        lines.append(make_line(*s["title_tokens"]))
        for row in s["col_hdr_rows"]:
            lines.append(make_line(*row))
        for row in s["athlete_rows"]:
            lines.append(make_line(*row))
    return lines


# Standard competition header lines used by most tests.
_COMP_HEADER = [
    make_line("Puiatu", "CUP", "2025"),
    make_line("Vana-Võidu", "Vibuklubi/Viljandi", "SK", "(25VV03)"),
    make_line("Puiatu", "Vibukeskus,", "From", "13-09-2025", "to", "14-09-2025"),
]


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------

class TestMatchAfterArrows(unittest.TestCase):

    def test_exact_match_144(self):
        self.assertEqual(_match_after_arrows(["After", "144", "Arrows"]), 144)

    def test_exact_match_72(self):
        self.assertEqual(_match_after_arrows(["After", "72", "Arrows"]), 72)

    def test_no_match_returns_none(self):
        self.assertIsNone(_match_after_arrows(["Sportvibu", "Mehed"]))

    def test_partial_match_returns_none(self):
        self.assertIsNone(_match_after_arrows(["After", "144"]))


class TestIsColumnHeaderLine(unittest.TestCase):

    def test_recognises_70m_tokens(self):
        self.assertTrue(_is_column_header_line(["70m-1", "70m-2", "Tot."]))

    def test_recognises_mixed_distances(self):
        self.assertTrue(_is_column_header_line(["40m-1", "40m-2", "Tot."]))

    def test_rejects_totals_header(self):
        self.assertFalse(_is_column_header_line(["Tot.", "10+X", "X"]))

    def test_rejects_athlete_line(self):
        self.assertFalse(_is_column_header_line(["1", "2-001A", "RIST", "Martin"]))


class TestExtractDistancesFromLine(unittest.TestCase):

    def test_uniform_70m(self):
        self.assertEqual(
            _extract_distances_from_line(["70m-1", "70m-2", "Tot."]),
            ["70m", "70m"],
        )

    def test_mixed_30m(self):
        self.assertEqual(
            _extract_distances_from_line(["30m-3", "30m-4", "Tot."]),
            ["30m", "30m"],
        )

    def test_skips_non_distance_tokens(self):
        self.assertEqual(
            _extract_distances_from_line(["Tot.", "10+X", "X"]),
            [],
        )


class TestStartsWithPositiveInt(unittest.TestCase):

    def test_position_1(self):
        self.assertTrue(_starts_with_positive_int(["1", "2-001A", "RIST"]))

    def test_position_12(self):
        self.assertTrue(_starts_with_positive_int(["12", "1-003B", "KASK"]))

    def test_tot_line_false(self):
        self.assertFalse(_starts_with_positive_int(["Tot.", "10+X", "X"]))

    def test_empty_false(self):
        self.assertFalse(_starts_with_positive_int([]))

    def test_distance_token_false(self):
        self.assertFalse(_starts_with_positive_int(["70m-1", "70m-2"]))


# ---------------------------------------------------------------------------
# Required test: competition header parsing
# ---------------------------------------------------------------------------

class TestParseCompetitionHeader(unittest.TestCase):

    def test_parses_competition_name(self):
        meta = _parse_competition_header(_COMP_HEADER)
        self.assertEqual(meta.name, "Puiatu CUP 2025")

    def test_parses_organiser(self):
        meta = _parse_competition_header(_COMP_HEADER)
        self.assertIn("Vana-Võidu", meta.organiser)

    def test_parses_event_code(self):
        meta = _parse_competition_header(_COMP_HEADER)
        self.assertEqual(meta.event_code, "25VV03")

    def test_parses_venue(self):
        meta = _parse_competition_header(_COMP_HEADER)
        self.assertIn("Puiatu", meta.venue)

    def test_parses_date_start(self):
        meta = _parse_competition_header(_COMP_HEADER)
        self.assertEqual(meta.date_start, date(2025, 9, 13))

    def test_parses_date_end(self):
        meta = _parse_competition_header(_COMP_HEADER)
        self.assertEqual(meta.date_end, date(2025, 9, 14))

    def test_single_day_event_date_start_equals_end(self):
        """When only one date appears, date_start == date_end."""
        single_day_header = [
            make_line("Spring", "Cup", "2025"),
            make_line("TestClub", "(TC01)"),
            make_line("Venue,", "From", "01-05-2025"),
        ]
        meta = _parse_competition_header(single_day_header)
        self.assertEqual(meta.date_start, meta.date_end)
        self.assertEqual(meta.date_start, date(2025, 5, 1))


# ---------------------------------------------------------------------------
# Required test: uniform 4×70m section detection
# ---------------------------------------------------------------------------

class TestDetectsUniformSection(unittest.TestCase):

    def _build_stream(self):
        return _make_full_stream(
            _COMP_HEADER,
            [{
                "arrow_count": 144,
                "title_tokens": ["Sportvibu", "Mehed"],
                "col_hdr_rows": [
                    ["70m-1", "70m-2", "Tot."],
                    ["70m-3", "70m-4", "Tot."],
                    ["Tot.", "10+X", "X"],
                ],
                "athlete_rows": [
                    ["1", "2-001A", "RIST", "Martin", "M", "VVVK", "318", "293", "611"],
                    ["314", "313", "627", "1,238", "26", "10"],
                ],
            }],
        )

    def test_returns_one_section(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(len(sections), 1)

    def test_bow_type_recurve(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.bow_type, "Recurve")

    def test_age_class_adult(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.age_class, "Adult")

    def test_gender_men(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.gender, "Men")

    def test_arrow_count_144(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.arrow_count, 144)

    def test_distances_four_70m(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.distances, ["70m", "70m", "70m", "70m"])

    def test_half_labels(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.half_labels, ["2x70m", "2x70m"])

    def test_total_label(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.total_label, "4x70m")

    def test_athlete_lines_collected(self):
        _, sections = detect_sections(self._build_stream())
        # 2 printed lines (start + continuation)
        self.assertEqual(len(sections[0].lines), 2)


# ---------------------------------------------------------------------------
# Required test: mixed round (2×40m + 2×30m)
# ---------------------------------------------------------------------------

class TestDetectsMixedSection(unittest.TestCase):

    def _build_stream(self):
        return _make_full_stream(
            _COMP_HEADER,
            [{
                "arrow_count": 144,
                "title_tokens": ["Sportvibu", "U15", "Poisid"],
                "col_hdr_rows": [
                    ["40m-1", "40m-2", "Tot."],
                    ["30m-3", "30m-4", "Tot."],
                    ["Tot.", "10+X", "X"],
                ],
                "athlete_rows": [
                    ["1", "1-014C", "GROSS", "Märt", "U15M", "SAG", "Sagittarius", "294", "298", "592"],
                    ["316", "338", "654", "1,246", "35", "14"],
                ],
            }],
        )

    def test_distances_mixed(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.distances, ["40m", "40m", "30m", "30m"])

    def test_half_labels_mixed(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.half_labels, ["2x40m", "2x30m"])

    def test_total_label_mixed(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.total_label, "2x40m+2x30m")

    def test_age_class_u15(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.age_class, "U15")

    def test_gender_men(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.gender, "Men")


# ---------------------------------------------------------------------------
# Required test: 72-arrow section → arrow_count=72, no half_labels
# ---------------------------------------------------------------------------

class TestDetects72ArrowSection(unittest.TestCase):

    def _build_stream(self):
        return _make_full_stream(
            _COMP_HEADER,
            [{
                "arrow_count": 72,
                "title_tokens": ["Sportvibu", "Veteranid", "Mehed"],
                "col_hdr_rows": [
                    ["60m-1", "60m-2", "Tot."],
                    ["Tot.", "10+X", "X"],
                ],
                "athlete_rows": [
                    ["1", "3-002B", "TAMM", "Jüri", "50M", "VVVK", "301", "310", "611", "12", "3"],
                ],
            }],
        )

    def test_arrow_count_72(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.arrow_count, 72)

    def test_distances_two_60m(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.distances, ["60m", "60m"])

    def test_no_half_labels(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.half_labels, [])

    def test_total_label_2x60m(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.total_label, "2x60m")

    def test_age_class_plus50(self):
        _, sections = detect_sections(self._build_stream())
        self.assertEqual(sections[0].context.age_class, "+50")


# ---------------------------------------------------------------------------
# Required test: unknown section title logs warning and continues
# ---------------------------------------------------------------------------

class TestUnknownSectionLogsWarningAndContinues(unittest.TestCase):

    def _build_stream_with_unknown_then_known(self):
        """Stream with one unknown bow type, then one valid section."""
        return _make_full_stream(
            _COMP_HEADER,
            [
                {
                    "arrow_count": 144,
                    "title_tokens": ["Vibu", "Mehed"],          # "Vibu" unknown
                    "col_hdr_rows": [["70m-1", "70m-2", "Tot."]],
                    "athlete_rows": [
                        ["1", "1-001A", "NOBODY", "Test", "M", "TST", "300", "300", "600"],
                    ],
                },
                {
                    "arrow_count": 144,
                    "title_tokens": ["Plokkvibu", "Naised"],     # known
                    "col_hdr_rows": [
                        ["50m-1", "50m-2", "Tot."],
                        ["50m-3", "50m-4", "Tot."],
                        ["Tot.", "10+X", "X"],
                    ],
                    "athlete_rows": [
                        ["1", "2-005C", "ILVES", "Kristi", "W", "VVVK", "340", "345", "685"],
                        ["350", "355", "705", "1,390", "42", "18"],
                    ],
                },
            ],
        )

    def test_warning_logged_for_unknown_section(self):
        with self.assertLogs("archery_parser.detector", level="WARNING") as cm:
            _, sections = detect_sections(self._build_stream_with_unknown_then_known())
        self.assertTrue(any("Unknown bow type" in msg for msg in cm.output))

    def test_valid_section_still_parsed(self):
        _, sections = detect_sections(self._build_stream_with_unknown_then_known())
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].context.bow_type, "Compound")

    def test_unknown_class_code_skips_section(self):
        """A section with a known bow type but unparseable gender still skips."""
        stream = _make_full_stream(
            _COMP_HEADER,
            [{
                "arrow_count": 144,
                "title_tokens": ["Sportvibu", "UnknownWord"],
                "col_hdr_rows": [["70m-1", "70m-2", "Tot."]],
                "athlete_rows": [
                    ["1", "1-001A", "TEST", "Person", "M", "TST", "300", "300", "600"],
                ],
            }],
        )
        with self.assertLogs("archery_parser.detector", level="WARNING") as cm:
            _, sections = detect_sections(stream)
        self.assertEqual(len(sections), 0)
        self.assertTrue(any("class code" in msg.lower() or "Cannot determine" in msg for msg in cm.output))


# ---------------------------------------------------------------------------
# Additional integration-style tests
# ---------------------------------------------------------------------------

class TestMultipleSections(unittest.TestCase):
    """detect_sections correctly handles two consecutive sections."""

    def _build_two_section_stream(self):
        return _make_full_stream(
            _COMP_HEADER,
            [
                {
                    "arrow_count": 144,
                    "title_tokens": ["Sportvibu", "Mehed"],
                    "col_hdr_rows": [
                        ["70m-1", "70m-2", "Tot."],
                        ["70m-3", "70m-4", "Tot."],
                        ["Tot.", "10+X", "X"],
                    ],
                    "athlete_rows": [
                        ["1", "2-001A", "RIST", "Martin", "M", "VVVK", "318", "293", "611"],
                        ["314", "313", "627", "1,238", "26", "10"],
                        ["2", "2-002B", "KASK", "Jaan", "M", "VVVK", "290", "285", "575"],
                        ["280", "295", "575", "1,150", "15", "5"],
                    ],
                },
                {
                    "arrow_count": 144,
                    "title_tokens": ["Plokkvibu", "Naised"],
                    "col_hdr_rows": [
                        ["50m-1", "50m-2", "Tot."],
                        ["50m-3", "50m-4", "Tot."],
                        ["Tot.", "10+X", "X"],
                    ],
                    "athlete_rows": [
                        ["1", "2-005C", "ILVES", "Kristi", "W", "VVVK", "340", "345", "685"],
                        ["350", "355", "705", "1,390", "42", "18"],
                    ],
                },
            ],
        )

    def test_two_sections_returned(self):
        _, sections = detect_sections(self._build_two_section_stream())
        self.assertEqual(len(sections), 2)

    def test_section_one_recurve(self):
        _, sections = detect_sections(self._build_two_section_stream())
        self.assertEqual(sections[0].context.bow_type, "Recurve")
        self.assertEqual(sections[0].context.gender, "Men")

    def test_section_two_compound(self):
        _, sections = detect_sections(self._build_two_section_stream())
        self.assertEqual(sections[1].context.bow_type, "Compound")
        self.assertEqual(sections[1].context.gender, "Women")

    def test_athlete_lines_per_section(self):
        _, sections = detect_sections(self._build_two_section_stream())
        self.assertEqual(len(sections[0].lines), 4)   # 2 athletes × 2 lines each
        self.assertEqual(len(sections[1].lines), 2)   # 1 athlete × 2 lines


class TestHarrastajadSection(unittest.TestCase):
    """Harrastajad bow type maps to Recurve with HM/HW class codes."""

    def _build_stream(self, gender_token: str, expected_gender: str):
        return _make_full_stream(
            _COMP_HEADER,
            [{
                "arrow_count": 144,
                "title_tokens": ["Harrastajad", gender_token],
                "col_hdr_rows": [
                    ["30m-1", "30m-2", "Tot."],
                    ["30m-3", "30m-4", "Tot."],
                    ["Tot.", "10+X", "X"],
                ],
                "athlete_rows": [
                    ["1", "1-001A", "LEMBER", "Lovisa", "HW" if gender_token == "Naised" else "HM",
                     "VVVK", "300", "305", "605"],
                    ["310", "315", "625", "1,230", "20", "8"],
                ],
            }],
        )

    def test_harrastajad_men_recurve(self):
        _, sections = detect_sections(self._build_stream("Mehed", "Men"))
        self.assertEqual(sections[0].context.bow_type, "Recurve")
        self.assertEqual(sections[0].context.gender, "Men")
        self.assertEqual(sections[0].context.age_class, "Adult")

    def test_harrastajad_women_recurve(self):
        _, sections = detect_sections(self._build_stream("Naised", "Women"))
        self.assertEqual(sections[0].context.bow_type, "Recurve")
        self.assertEqual(sections[0].context.gender, "Women")


class TestCompetitionMetaReturnedCorrectly(unittest.TestCase):

    def test_meta_name_from_detect_sections(self):
        stream = _make_full_stream(_COMP_HEADER, [])
        meta, _ = detect_sections(stream)
        self.assertEqual(meta.name, "Puiatu CUP 2025")

    def test_meta_date_end(self):
        stream = _make_full_stream(_COMP_HEADER, [])
        meta, _ = detect_sections(stream)
        self.assertEqual(meta.date_end, date(2025, 9, 14))


if __name__ == "__main__":
    unittest.main(verbosity=2)
