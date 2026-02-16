"""
CLI entry point for archery_parser.

Wires all five pipeline modules together and exposes a command-line
interface via argparse.  Multiple input PDFs are supported; all rows
are combined into a single output CSV.

Usage:
    python -m archery_parser input.pdf
    python -m archery_parser file1.pdf file2.pdf --output results.csv
    python -m archery_parser input.pdf --append existing.csv
    python -m archery_parser input.pdf --dry-run --verbose

See Section 9 of the requirements document for full argument documentation.

Public API:
    main() -> None   # called by the console_scripts entry point
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from archery_parser.assembler import assemble_athletes
from archery_parser.detector import detect_sections
from archery_parser.reader import extract_lines
from archery_parser.transformer import transform
from archery_parser.writer import write_csv


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool, log_file: Path | None) -> None:
    """
    Configure the root logger.

    Always logs to stderr.  If --log is given, also logs to that file.
    Level is DEBUG when --verbose, INFO otherwise.
    """
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s %(levelname)s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archery_parser",
        description=(
            "Convert Ianseo archery competition result PDFs into "
            "arithmetically-verified CSV files."
        ),
    )
    parser.add_argument(
        "input",
        nargs="+",
        metavar="PDF",
        help="One or more Ianseo qualification protocol PDF files.",
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output", "-o",
        metavar="CSV",
        default=None,
        help=(
            "Output CSV file path.  Defaults to the name of the first "
            "input PDF with a .csv extension."
        ),
    )
    output_group.add_argument(
        "--append",
        metavar="CSV",
        default=None,
        help="Append rows to an existing CSV file instead of overwriting.",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print DEBUG-level log lines to stderr.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse all PDFs but do not write any output file.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit non-zero on arithmetic mismatches instead of just warning.",
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        default=None,
        help="Write log output to FILE in addition to stderr.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Output CSV encoding (default: utf-8).",
    )
    return parser


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Raised when a PDF cannot be parsed."""


def _process_pdf(pdf_path: Path) -> tuple:
    """
    Run the full reader → detector → assembler pipeline for one PDF.

    Returns:
        (CompetitionMeta, list[AthleteRecord])

    Raises:
        ParseError: On file-not-found or parsing failures.
    """
    if not pdf_path.exists():
        raise ParseError(f"File not found: {pdf_path}")

    try:
        lines = extract_lines(pdf_path)
        meta, sections = detect_sections(lines)
        records = assemble_athletes(sections)
    except ValueError as exc:
        raise ParseError(f"{pdf_path.name}: {exc}") from exc

    return meta, records


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """
    Parse arguments and run the full pipeline.

    Args:
        argv: Argument list (defaults to sys.argv[1:] when None).
    """
    parser = _build_parser()
    args   = parser.parse_args(argv)
    logger = logging.getLogger(__name__)

    # Configure logging before doing anything else.
    log_file = Path(args.log) if args.log else None
    _configure_logging(args.verbose, log_file)

    # Determine output path.
    if args.append:
        output_path = Path(args.append)
        append_mode = True
    elif args.output:
        output_path = Path(args.output)
        append_mode = False
    else:
        # Default: name of first input PDF with .csv extension.
        output_path = Path(args.input[0]).with_suffix(".csv")
        append_mode = False

    # Process each PDF in turn, collecting all CSVRows.
    all_rows = []
    first_meta = None

    for pdf_str in args.input:
        pdf_path = Path(pdf_str)
        try:
            meta, records = _process_pdf(pdf_path)
        except ParseError as exc:
            logger.error("FATAL  %s", exc)
            sys.exit(1)

        if first_meta is None:
            first_meta = meta

        rows = transform(records, meta)
        all_rows.extend(rows)
        logger.info(
            "cli  Processed %s → %d athletes, %d rows",
            pdf_path.name, len(records), len(rows),
        )

    if not all_rows:
        logger.warning("cli  No rows produced — output file not written.")
        return

    # Write (or skip in --dry-run mode).
    if args.dry_run:
        logger.info("cli  Dry-run: %d rows parsed, output not written.", len(all_rows))
    else:
        try:
            write_csv(
                all_rows, output_path,
                append=append_mode,
                encoding=args.encoding,
                strict=args.strict,
            )
        except ValueError as exc:
            logger.error("FATAL  %s", exc)
            sys.exit(1)
        logger.info("cli  Done. Output: %s", output_path)
