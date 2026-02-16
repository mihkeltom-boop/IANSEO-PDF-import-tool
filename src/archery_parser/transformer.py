"""
Module 4 — Transformer.

Converts AthleteRecord objects into CSVRow objects by:
  - Reformatting "LASTNAME Firstname" → "Firstname Lastname" (title case)
  - Merging club_code / club_name into a single Club string
  - Applying BOW_TYPE, AGE_CLASS, GENDER lookup tables
  - Formatting CompetitionMeta.date_end as DD.MM.YYYY
  - Expanding each athlete into one row per end score, one per
    half-subtotal (if any), and one grand-total row

Row expansion rules (from Section 4.2.1):
  2-end (72 arrow)  → 3 rows : end1, end2, grand_total
  4-end (144 arrow) → 7 rows : end1, end2, sub1, end3, end4, sub2, grand_total
  N-end in general  → N + N/2 + 1 rows

Distance labels used per row come from the athlete's SectionContext:
  Individual end row : context.distances[end_index]
  Half-subtotal row  : context.half_labels[half_index]
  Grand-total row    : context.total_label

Public API:
    transform(records, meta) -> list[CSVRow]
"""

from __future__ import annotations

import logging
from datetime import date

from archery_parser.lookups import AGE_CLASS, BOW_TYPE, GENDER
from archery_parser.models import AthleteRecord, CompetitionMeta, CSVRow

logger = logging.getLogger(__name__)


def _format_date(d: date) -> str:
    """Format a date as DD.MM.YYYY."""
    return d.strftime("%d.%m.%Y")


def _format_name(firstname: str, lastname: str) -> str:
    """
    Reformat "LASTNAME Firstname" storage into "Firstname Lastname" title case.
    Both parts are run through str.title() to normalise all-caps lastnames.
    """
    return f"{firstname.title()} {lastname.title()}".strip()


def _format_club(club_code: str | None, club_name: str | None) -> str:
    """
    Produce the CSV Club field from the two optional components.

      Both present  → "{code} {name}"
      Code only     → "{code}"
      Name only     → "{name}"
      Neither       → ""
    """
    if club_code and club_name:
        return f"{club_code} {club_name}"
    if club_code:
        return club_code
    if club_name:
        return club_name
    return ""


def _expand_athlete(record: AthleteRecord, meta: CompetitionMeta) -> list[CSVRow]:
    """
    Expand one AthleteRecord into a sequence of CSVRow objects.

    The expansion order mirrors the printed score sheet:
      For each pair of ends (half):
        row: end_score_a  distance = context.distances[i]
        row: end_score_b  distance = context.distances[i+1]
        row: half_total   distance = context.half_labels[half_idx]  (omitted for 2-end rounds)
      Final row: grand_total  distance = context.total_label

    Args:
        record: A fully parsed AthleteRecord.
        meta:   CompetitionMeta supplying the date and competition name.

    Returns:
        Ordered list of CSVRow objects for this athlete.
    """
    ctx = record.section

    # Shared descriptor fields — identical across all rows for this athlete.
    date_str    = _format_date(meta.date_end)
    athlete_str = _format_name(record.firstname, record.lastname)
    club_str    = _format_club(record.club_code, record.club_name)
    bow_type    = ctx.bow_type
    age_class   = ctx.age_class
    gender      = ctx.gender
    competition = meta.name

    def _get_distance(index: int) -> str:
        """
        Get distance label for a given end index.

        If distances list is empty or index is out of range, return a
        generic label based on the index.
        """
        if not ctx.distances:
            return f"End-{index + 1}"
        if index < len(ctx.distances):
            return ctx.distances[index]
        # Repeat last distance for overflow
        return ctx.distances[-1]

    def _row(distance: str, result: int) -> CSVRow:
        return CSVRow(
            date=date_str,
            athlete=athlete_str,
            club=club_str,
            bow_type=bow_type,
            age_class=age_class,
            gender=gender,
            distance=distance,
            result=result,
            competition=competition,
        )

    rows: list[CSVRow] = []
    n_ends = len(record.end_scores)

    if n_ends == 0:
        # Degenerate: no end scores parsed — emit only the grand total row.
        rows.append(_row(ctx.total_label, record.grand_total))
        return rows

    if ctx.half_labels:
        # Multi-half round: groups of two ends followed by a half-subtotal.
        half_idx = 0
        end_idx  = 0
        for half_idx, half_label in enumerate(ctx.half_labels):
            # Two end rows
            for _ in range(2):
                if end_idx < n_ends:
                    rows.append(_row(_get_distance(end_idx), record.end_scores[end_idx]))
                    end_idx += 1
            # Half-subtotal row
            if half_idx < len(record.half_totals):
                rows.append(_row(half_label, record.half_totals[half_idx]))

        # Any remaining end scores (shouldn't happen in standard rounds, but
        # be defensive for 6/8-end rounds where half_labels may be shorter).
        while end_idx < n_ends:
            rows.append(_row(_get_distance(end_idx), record.end_scores[end_idx]))
            end_idx += 1
    else:
        # 2-end round: just the two end rows (no half-subtotals).
        for i, score in enumerate(record.end_scores):
            rows.append(_row(_get_distance(i), score))

    # Grand-total row always last.
    rows.append(_row(ctx.total_label, record.grand_total))

    return rows


def transform(
    records: list[AthleteRecord],
    meta: CompetitionMeta,
) -> list[CSVRow]:
    """
    Convert a list of AthleteRecord objects into a flat list of CSVRow objects.

    Each AthleteRecord expands into multiple rows per the Section 4.2.1 rules.
    Lookup tables from lookups.py are applied via the SectionContext already
    stored on each record (populated by the Detector).

    Args:
        records: Output of assembler.assemble_athletes().
        meta:    CompetitionMeta for date and competition-name fields.

    Returns:
        Flat list of CSVRow objects in document order.
    """
    rows: list[CSVRow] = []
    for record in records:
        athlete_rows = _expand_athlete(record, meta)
        rows.extend(athlete_rows)
        logger.debug(
            "transformer  %s → %d rows",
            f"{record.firstname} {record.lastname}",
            len(athlete_rows),
        )
    logger.info("transformer  Total rows produced: %d", len(rows))
    return rows
