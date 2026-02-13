"""
Stage 6 tests — CLI and integration.

Integration test runs the full pipeline end-to-end against the real
Puiatu CUP 2025 PDF fixture.  If the fixture is absent the test is
skipped with a clear message rather than failing.

Place the fixture at:
    tests/fixtures/Puiatu-CUP-2025.pdf

CLI unit tests (no PDF required) verify argument parsing, --dry-run,
--verbose, --output, and --append flag wiring.
"""

import csv
import io
import logging
import logging.handlers
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archery_parser.cli import main, _build_parser, _configure_logging
from archery_parser.assembler import assemble_athletes
from archery_parser.detector import detect_sections
from archery_parser.reader import extract_lines
from archery_parser.transformer import transform
from archery_parser.writer import write_csv

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

FIXTURES_DIR  = Path(__file__).parent / "fixtures"
FIXTURE_PDF   = FIXTURES_DIR / "Puiatu-CUP-2025.pdf"
HAS_FIXTURE   = FIXTURE_PDF.exists()
SKIP_MSG      = (
    f"Integration fixture not found: {FIXTURE_PDF}\n"
    "Place Puiatu-CUP-2025.pdf in tests/fixtures/ to enable these tests."
)

# Expected spot-check values from Section 12 Stage 6 Prompt
SPOT_CHECKS = [
    # (athlete_name_as_in_csv,  total_label,         expected_grand_total)
    ("Martin Rist",   "4x70m",          1238),
    ("Kristi Ilves",  "4x50m",          1345),
    ("Paul Villemi",  "4x50m",          1134),
    ("Kalju Baumann", "4x50m",           717),
    ("Lovisa Lember", "4x30m",          1204),
]


# ---------------------------------------------------------------------------
# CLI unit tests (no PDF required)
# ---------------------------------------------------------------------------

class TestArgParser(unittest.TestCase):

    def setUp(self):
        self.parser = _build_parser()

    def test_requires_at_least_one_input(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_single_input(self):
        args = self.parser.parse_args(["input.pdf"])
        self.assertEqual(args.input, ["input.pdf"])

    def test_multiple_inputs(self):
        args = self.parser.parse_args(["a.pdf", "b.pdf", "c.pdf"])
        self.assertEqual(len(args.input), 3)

    def test_output_flag(self):
        args = self.parser.parse_args(["input.pdf", "--output", "results.csv"])
        self.assertEqual(args.output, "results.csv")

    def test_output_short_flag(self):
        args = self.parser.parse_args(["input.pdf", "-o", "out.csv"])
        self.assertEqual(args.output, "out.csv")

    def test_append_flag(self):
        args = self.parser.parse_args(["input.pdf", "--append", "existing.csv"])
        self.assertEqual(args.append, "existing.csv")

    def test_verbose_flag(self):
        args = self.parser.parse_args(["input.pdf", "--verbose"])
        self.assertTrue(args.verbose)

    def test_verbose_short_flag(self):
        args = self.parser.parse_args(["input.pdf", "-v"])
        self.assertTrue(args.verbose)

    def test_dry_run_flag(self):
        args = self.parser.parse_args(["input.pdf", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_log_flag(self):
        args = self.parser.parse_args(["input.pdf", "--log", "run.log"])
        self.assertEqual(args.log, "run.log")

    def test_encoding_flag(self):
        args = self.parser.parse_args(["input.pdf", "--encoding", "utf-8"])
        self.assertEqual(args.encoding, "utf-8")

    def test_defaults(self):
        args = self.parser.parse_args(["input.pdf"])
        self.assertIsNone(args.output)
        self.assertIsNone(args.append)
        self.assertFalse(args.verbose)
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.log)
        self.assertEqual(args.encoding, "utf-8")

    def test_default_output_derives_from_input(self):
        """When --output not given, output path should be input with .csv suffix."""
        args = self.parser.parse_args(["Puiatu-CUP-2025.pdf"])
        # The CLI derives the default in main(), not in parse_args(), so just
        # verify that args.output is None (meaning the default will be used).
        self.assertIsNone(args.output)


class TestDryRun(unittest.TestCase):
    """--dry-run should parse without writing any file."""

    def test_dry_run_nonexistent_pdf_exits_1(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["nonexistent_file.pdf", "--dry-run"])
        self.assertEqual(ctx.exception.code, 1)


# ---------------------------------------------------------------------------
# Integration tests (require the Puiatu CUP 2025 PDF fixture)
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FIXTURE, SKIP_MSG)
class TestFullPipelineIntegration(unittest.TestCase):
    """
    End-to-end pipeline test against the real Puiatu CUP 2025 PDF.

    Runs once per test class (setUpClass) so the PDF is only parsed once.
    """

    _rows    = None   # list[CSVRow]
    _meta    = None   # CompetitionMeta
    _records = None   # list[AthleteRecord]
    _warnings: list[str] = []

    @classmethod
    def setUpClass(cls):
        """Parse the PDF and store results for all tests in this class."""
        # Capture WARNING-level log messages during the run
        warning_messages: list[str] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    warning_messages.append(record.getMessage())

        capturing = CapturingHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(capturing)
        root_logger.setLevel(logging.DEBUG)

        try:
            lines   = extract_lines(FIXTURE_PDF)
            meta, sections = detect_sections(lines)
            records = assemble_athletes(sections)
            rows    = transform(records, meta)
        finally:
            root_logger.removeHandler(capturing)

        cls._meta    = meta
        cls._records = records
        cls._rows    = rows
        cls._warnings = warning_messages

    # -----------------------------------------------------------------------
    # Competition metadata
    # -----------------------------------------------------------------------

    def test_competition_name(self):
        self.assertIn("Puiatu", self._meta.name)

    def test_event_code_parsed(self):
        self.assertTrue(len(self._meta.event_code) > 0)

    # -----------------------------------------------------------------------
    # Zero arithmetic warnings
    # -----------------------------------------------------------------------

    def test_zero_arithmetic_verification_warnings(self):
        """All subtotals and grand totals in the PDF must be internally consistent."""
        arith_warnings = [w for w in self._warnings if "Mismatch" in w]
        self.assertEqual(
            len(arith_warnings), 0,
            msg=f"Arithmetic mismatches found:\n" + "\n".join(arith_warnings),
        )

    # -----------------------------------------------------------------------
    # Spot-checks (Section 12 Stage 6 Prompt)
    # -----------------------------------------------------------------------

    def _find_grand_total_row(self, athlete_name: str, total_label: str):
        """Return the grand-total CSVRow for a given athlete and total_label."""
        matches = [
            r for r in self._rows
            if r.athlete == athlete_name and r.distance == total_label
        ]
        return matches[0] if matches else None

    def test_spot_martin_rist(self):
        name, label, expected = "Martin Rist", "4x70m", 1238
        row = self._find_grand_total_row(name, label)
        self.assertIsNotNone(row, f"{name} not found in output")
        self.assertEqual(row.result, expected,
                         f"{name} grand total: expected {expected}, got {row.result}")

    def test_spot_kristi_ilves(self):
        name, label, expected = "Kristi Ilves", "4x50m", 1345
        row = self._find_grand_total_row(name, label)
        self.assertIsNotNone(row, f"{name} not found in output")
        self.assertEqual(row.result, expected)

    def test_spot_paul_villemi(self):
        name, label, expected = "Paul Villemi", "4x50m", 1134
        row = self._find_grand_total_row(name, label)
        self.assertIsNotNone(row, f"{name} not found in output")
        self.assertEqual(row.result, expected)

    def test_spot_kalju_baumann(self):
        name, label, expected = "Kalju Baumann", "4x50m", 717
        row = self._find_grand_total_row(name, label)
        self.assertIsNotNone(row, f"{name} not found in output")
        self.assertEqual(row.result, expected)

    def test_spot_lovisa_lember(self):
        name, label, expected = "Lovisa Lember", "4x30m", 1204
        row = self._find_grand_total_row(name, label)
        self.assertIsNotNone(row, f"{name} not found in output")
        self.assertEqual(row.result, expected)

    # -----------------------------------------------------------------------
    # Distance labels conform to Section 7.4
    # -----------------------------------------------------------------------

    def test_all_distance_labels_valid(self):
        """
        Every Distance value in the output must conform to the spec.
        Valid forms:
          - plain distance:   "70m", "60m", "50m", "40m", "30m", "25m",
                              "20m", "15m", "10m"
          - half-subtotal:    "2xNm"  e.g. "2x70m"
          - grand total:      "NxDm"  or  "NxDm+NxDm"  e.g. "4x70m",
                              "2x40m+2x30m"
        """
        import re
        valid_plain   = re.compile(r"^\d+m$")
        valid_label   = re.compile(r"^\d+x\d+m(\+\d+x\d+m)*$")

        invalid = set()
        for row in self._rows:
            d = row.distance
            if not (valid_plain.match(d) or valid_label.match(d)):
                invalid.add(d)

        self.assertEqual(invalid, set(),
                         f"Invalid distance labels found: {invalid}")

    # -----------------------------------------------------------------------
    # Row count sanity
    # -----------------------------------------------------------------------

    def test_total_row_count_positive(self):
        """At minimum several hundred rows expected for a full competition."""
        self.assertGreater(len(self._rows), 100,
                           "Suspiciously few rows — likely a parsing failure")

    def test_row_count_consistent_with_records(self):
        """
        Every AthleteRecord should have contributed at least 3 rows
        (the minimum for a 2-end round).
        """
        min_expected = len(self._records) * 3
        self.assertGreaterEqual(len(self._rows), min_expected)

    # -----------------------------------------------------------------------
    # CSV output via write_csv
    # -----------------------------------------------------------------------

    def test_written_csv_row_count_matches(self):
        """write_csv returns the same count as the list passed to it."""
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as fh:
            path = fh.name
        try:
            count = write_csv(self._rows, path)
            self.assertEqual(count, len(self._rows))
        finally:
            os.unlink(path)

    def test_written_csv_has_correct_header(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as fh:
            path = fh.name
        try:
            write_csv(self._rows, path)
            with open(path, encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader)
            self.assertEqual(
                header,
                ["Date", "Athlete", "Club", "Bow Type", "Age Class",
                 "Gender", "Distance", "Result", "Competition"],
            )
        finally:
            os.unlink(path)


@unittest.skipUnless(HAS_FIXTURE, SKIP_MSG)
class TestCLIWithFixture(unittest.TestCase):
    """CLI end-to-end tests using the real PDF."""

    def test_cli_writes_output_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False
        ) as fh:
            out_path = fh.name
        try:
            main([str(FIXTURE_PDF), "--output", out_path])
            self.assertTrue(Path(out_path).exists())
            self.assertGreater(Path(out_path).stat().st_size, 0)
        finally:
            if Path(out_path).exists():
                os.unlink(out_path)

    def test_cli_dry_run_does_not_write(self):
        out_path = Path(tempfile.mktemp(suffix=".csv"))
        try:
            main([str(FIXTURE_PDF), "--output", str(out_path), "--dry-run"])
            self.assertFalse(out_path.exists(), "dry-run should not create output file")
        finally:
            if out_path.exists():
                out_path.unlink()

    def test_cli_append_mode(self):
        """Running twice with --append should double the data rows (one header)."""
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False
        ) as fh:
            out_path = fh.name
        try:
            main([str(FIXTURE_PDF), "--output", out_path])
            with open(out_path, encoding="utf-8", newline="") as fh:
                first_count = sum(1 for _ in csv.reader(fh))

            main([str(FIXTURE_PDF), "--append", out_path])
            with open(out_path, encoding="utf-8", newline="") as fh:
                second_count = sum(1 for _ in csv.reader(fh))

            # One header + data rows; append adds data rows only
            data_rows = first_count - 1          # exclude header
            expected  = first_count + data_rows  # header + 2× data
            self.assertEqual(second_count, expected)
        finally:
            if Path(out_path).exists():
                os.unlink(out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    unittest.main(verbosity=2)
