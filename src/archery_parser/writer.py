"""
Module 5 — Writer.

Performs arithmetic verification on every athlete's CSVRow group, then
writes a UTF-8 CSV file with a header row.

Arithmetic checks (per Section 6.5):
  1. Each half-subtotal row Result must equal the sum of the two individual
     end rows immediately above it.
  2. The grand-total row Result must equal the sum of all half-subtotal rows
     (or, for 2-end rounds with no half-subtotals, the sum of the two end rows).

On any mismatch a WARNING is logged with athlete name, distance label,
expected value, and actual value.  The row is never suppressed.

Public API:
    write_csv(rows, output_path, append=False) -> int   # returns row count written
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from archery_parser.models import CSVRow

logger = logging.getLogger(__name__)

# CSV column headers — must match CSVRow.COLUMNS order.
_HEADERS = [
    "Date",
    "Athlete",
    "Club",
    "Bow Type",
    "Age Class",
    "Gender",
    "Distance",
    "Result",
    "Competition",
]


def _is_end_row(row: CSVRow) -> bool:
    """
    Return True if this row represents an individual end score.

    An end row's distance label is a plain distance string (e.g. "70m"),
    as opposed to a half-subtotal ("2x70m") or grand-total ("4x70m",
    "2x40m+2x30m") label which contain "x" or "+".
    """
    return "x" not in row.distance and "+" not in row.distance


def _is_half_subtotal_row(row: CSVRow) -> bool:
    """
    Return True if this row is a half-subtotal row.

    Half-subtotal labels start with a digit and contain exactly one "x"
    but no "+".  e.g. "2x70m", "2x40m".
    Grand-total labels either have just one "x" AND no "+" (uniform),
    or have "+" (mixed).  We distinguish halves from grand-totals by
    checking whether the numeric prefix is 2.
    """
    d = row.distance
    # Must contain "x" but not "+"
    if "x" not in d or "+" in d:
        return False
    try:
        prefix = int(d.split("x")[0])
    except ValueError:
        return False
    return prefix == 2


def _is_grand_total_row(row: CSVRow) -> bool:
    """
    Return True if this row is the grand-total row.

    Grand-total labels contain "x" with a numeric prefix > 2 (e.g. "4x70m"),
    OR they contain "+" (mixed round, e.g. "2x40m+2x30m"),
    OR they are a plain "2xNm" for a 72-arrow round where the only subtotal
    IS the grand total.

    Simplest reliable heuristic: it is the grand total if it is NOT an
    end row and NOT a half-subtotal row.
    """
    return not _is_end_row(row) and not _is_half_subtotal_row(row)


def _verify_athlete_group(athlete_rows: list[CSVRow]) -> int:
    """
    Run arithmetic verification on one athlete's rows.

    Groups are expected to be in the order produced by the Transformer:
        [end, end, half_sub?, end, end, half_sub?, ..., grand_total]

    For each half-subtotal row: check it equals the sum of the two
    preceding end rows.

    For the grand-total row:
      - If half-subtotal rows exist: check it equals the sum of all halves.
      - If no half-subtotals (2-end round): check it equals the sum of the
        two end rows.

    Returns:
        Number of mismatches found (0 = all OK).
    """
    mismatches = 0
    athlete_name = athlete_rows[0].athlete if athlete_rows else "?"

    # Separate the row types, preserving order.
    end_rows:   list[CSVRow] = []
    half_rows:  list[CSVRow] = []
    grand_rows: list[CSVRow] = []

    for row in athlete_rows:
        if _is_grand_total_row(row):
            grand_rows.append(row)
        elif _is_half_subtotal_row(row):
            half_rows.append(row)
        else:
            end_rows.append(row)

    # Check each half-subtotal against the pair of ends above it.
    # We walk through athlete_rows in order, tracking pending ends.
    pending_ends: list[CSVRow] = []
    half_idx = 0

    for row in athlete_rows:
        if _is_grand_total_row(row):
            break
        if not _is_half_subtotal_row(row):
            pending_ends.append(row)
        else:
            # This is a half-subtotal row.
            if len(pending_ends) >= 2:
                expected = pending_ends[-2].result + pending_ends[-1].result
                if row.result != expected:
                    logger.warning(
                        "writer  Mismatch for %s %s: expected %d, got %d",
                        athlete_name, row.distance, expected, row.result,
                    )
                    mismatches += 1
            pending_ends = []
            half_idx += 1

    # Check grand total.
    if grand_rows:
        grand_row = grand_rows[0]
        if half_rows:
            expected_grand = sum(r.result for r in half_rows)
        else:
            # 2-end round: grand total should equal the sum of both end rows.
            expected_grand = sum(r.result for r in end_rows)

        if grand_row.result != expected_grand:
            logger.warning(
                "writer  Mismatch for %s %s: expected %d, got %d",
                athlete_name, grand_row.distance, expected_grand, grand_row.result,
            )
            mismatches += 1

    return mismatches


def _group_by_athlete(rows: list[CSVRow]) -> list[list[CSVRow]]:
    """
    Group consecutive rows by (athlete, competition, date) key.

    Rows for the same athlete are always contiguous (produced by the
    Transformer in athlete order), so a simple sequential grouping works.
    """
    if not rows:
        return []

    groups: list[list[CSVRow]] = []
    current_key = (rows[0].athlete, rows[0].competition, rows[0].date)
    current_group: list[CSVRow] = []

    for row in rows:
        key = (row.athlete, row.competition, row.date)
        if key == current_key:
            current_group.append(row)
        else:
            groups.append(current_group)
            current_group = [row]
            current_key = key

    groups.append(current_group)
    return groups


def write_csv(
    rows: list[CSVRow],
    output_path: str | Path,
    append: bool = False,
    encoding: str = "utf-8",
    strict: bool = False,
) -> int:
    """
    Verify all athlete row groups arithmetically, then write a CSV file.

    Args:
        rows:        List of CSVRow objects from transformer.transform().
        output_path: Destination file path.
        append:      If True, open in append mode and omit the header row.
                     If False (default), overwrite and write header.
        encoding:    Output file encoding (default: utf-8).
        strict:      If True, raise ValueError on arithmetic mismatches
                     instead of just logging warnings.

    Returns:
        Number of data rows written (excluding the header row).

    Raises:
        ValueError: In strict mode, if any arithmetic mismatches are found.
    """
    output_path = Path(output_path)

    # --- Arithmetic verification -------------------------------------------
    total_mismatches = 0
    for group in _group_by_athlete(rows):
        total_mismatches += _verify_athlete_group(group)

    if total_mismatches:
        msg = f"{total_mismatches} arithmetic mismatch(es) found"
        if strict:
            raise ValueError(f"writer  {msg} — aborting (strict mode).")
        logger.warning(
            "writer  %s — flagged rows still written.",
            msg,
        )

    # --- Write CSV -----------------------------------------------------------
    mode = "a" if append else "w"
    with open(output_path, mode, newline="", encoding=encoding) as fh:
        writer = csv.writer(fh)
        if not append:
            writer.writerow(_HEADERS)
        for row in rows:
            writer.writerow(row.as_row())

    written = len(rows)
    logger.info("writer  Written: %s (%d rows)", output_path, written)
    return written
