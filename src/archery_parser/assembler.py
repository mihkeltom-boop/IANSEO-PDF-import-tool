"""
Module 3 — Assembler.

Groups 1–4 printed lines per athlete using the position number + target code
as an anchor, then parses all fields (position, target code, name, class code,
club, and scores) into AthleteRecord objects.

Athlete boundary rules:
  START       — leftmost token is a positive integer AND second token matches
                the target-code pattern (\\d-\\d{3}[A-Z]).
  CONTINUATION— any other line (including lines starting with a score integer).

Score layout (after stripping trailing 10+X and X counts):
  2-end  (72 arrow):  [e1, e2, grand_total]
  4-end (144 arrow):  [e1, e2, sub1, e3, e4, sub2, grand_total]
  6-end (216 arrow):  [..., grand_total]
  8-end (288 arrow):  [..., grand_total]

General rule: groups of [end_a, end_b, subtotal] repeat, last value is
grand_total.  For 2-end rounds the subtotal is the grand total and there
are no separate half_total entries.

Public API:
    assemble_athletes(sections) -> list[AthleteRecord]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from archery_parser.detector import RawSection
from archery_parser.lookups import AGE_CLASS
from archery_parser.models import AthleteRecord
from archery_parser.reader import Word

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Target code: digit-NNNLetter  e.g. "2-001A", "1-014C"
_TARGET_CODE_RE = re.compile(r"^\d-\d{3}[A-Z]$")

# Club code: 2–6 uppercase ASCII letters (no digits, no lowercase)
_CLUB_CODE_RE = re.compile(r"^[A-Z]{2,6}$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_positive_int(token: str) -> bool:
    """Return True if token represents a positive integer."""
    try:
        return int(token) > 0
    except ValueError:
        return False


def _parse_int(token: str) -> int | None:
    """
    Parse a token as an integer, stripping thousands separators.
    Returns None if the token is not numeric.

    Both commas and periods are stripped because Ianseo PDFs may use
    either as a thousands separator depending on locale (e.g. "1,238"
    in English or "1.238" in European formats).  All score values in
    archery are integers, so there is no risk of misinterpreting
    decimal fractions.
    """
    cleaned = token.replace(",", "").replace(".", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


def _is_athlete_start(tokens: list[str]) -> bool:
    """
    Return True if this line is the start of a new athlete.

    A line is an ATHLETE START if:
      1. Its first token is a positive integer (the position number), AND
      2. Its second token matches the target-code pattern (\\d-\\d{3}[A-Z]).

    This two-condition check avoids false matches on continuation lines that
    also begin with a positive integer (a score value).
    """
    if len(tokens) < 2:
        return False
    return _is_positive_int(tokens[0]) and bool(_TARGET_CODE_RE.match(tokens[1]))


def _collect_integers(tokens: list[str]) -> list[int]:
    """
    Return all integer values from a token list, in order.
    Handles thousands-separator format like "1,238".
    """
    result = []
    for t in tokens:
        v = _parse_int(t)
        if v is not None:
            result.append(v)
    return result


def _parse_scores(all_integers: list[int]) -> tuple[list[int], list[int], int]:
    """
    Split a flat list of score integers into (end_scores, half_totals, grand_total).

    The last two values are always the 10+X and X counts — these are stripped
    first.  The remaining values follow a repeating pattern:

        [end_a, end_b, subtotal, end_c, end_d, subtotal, ..., grand_total]

    For 2-end rounds: [e1, e2, grand_total]   → no separate half_totals
    For 4-end rounds: [e1, e2, s1, e3, e4, s2, grand_total]
    ...

    Args:
        all_integers: Every score integer from the athlete's printed lines,
                      in document order.  Must NOT include the position number.

    Returns:
        (end_scores, half_totals, grand_total)
    """
    if len(all_integers) < 3:
        logger.warning("assembler  Too few score values: %s", all_integers)
        return [], [], 0

    scores = all_integers[:-2]   # drop last two (10+X, X)

    # Last remaining value is always grand_total
    grand_total = scores[-1]
    body = scores[:-1]

    end_scores: list[int] = []
    half_totals: list[int] = []

    if len(body) == 2:
        # 2-end round: body = [e1, e2], no intermediate subtotals
        end_scores = list(body)
        half_totals = []
    else:
        # 4+ end round: body consists of groups of [end_a, end_b, subtotal]
        for i in range(0, len(body), 3):
            group = body[i:i + 3]
            if len(group) == 3:
                end_scores.append(group[0])
                end_scores.append(group[1])
                half_totals.append(group[2])
            elif len(group) == 2:
                logger.warning("assembler  Incomplete score group: %s", group)
                end_scores.extend(group)
            elif len(group) == 1:
                logger.warning("assembler  Lone score value: %s", group)
                end_scores.append(group[0])

    return end_scores, half_totals, grand_total


def _parse_club(tokens: list[str]) -> tuple[str | None, str | None]:
    """
    Determine club_code and club_name from the non-numeric tokens between
    the class code and the first score column.

    Rules:
      - If the first token matches _CLUB_CODE_RE (2–6 uppercase letters),
        it is the club code; any remaining tokens form the club name.
      - If no token matches the code pattern, all tokens together are
        the club name and club_code is None.
      - If there are no tokens, both are None.

    Returns:
        (club_code, club_name) — either may be None.
    """
    if not tokens:
        return None, None

    if _CLUB_CODE_RE.match(tokens[0]):
        code = tokens[0]
        name = " ".join(tokens[1:]) if len(tokens) > 1 else None
        return code, name or None

    # No recognisable code — entire field is the name
    return None, " ".join(tokens)


def _parse_athlete_lines(
    lines: list[list[Word]],
    section: RawSection,
) -> AthleteRecord | None:
    """
    Parse a group of 1–4 printed lines belonging to one athlete.

    Score integers are collected separately per line:
    - Line 1 (start): only numeric tokens AFTER the non-numeric header fields
      (position, target code, name, class code, club) are treated as scores.
    - Continuation lines: all numeric tokens are scores.

    Args:
        lines:   The printed lines for this athlete (1 start + 0–3 continuations).
        section: The RawSection context.

    Returns:
        A populated AthleteRecord, or None if parsing fails fatally.
    """
    if not lines:
        return None

    # -----------------------------------------------------------------------
    # Parse header fields from line 1 (start line)
    # -----------------------------------------------------------------------
    line1_tokens = [w.text for w in lines[0]]
    tokens = list(line1_tokens)

    # Position
    position_str = tokens.pop(0)
    try:
        position = int(position_str)
    except ValueError:
        logger.warning("assembler  Expected position integer, got '%s'", position_str)
        return None

    # Target code
    target_code = ""
    if tokens and _TARGET_CODE_RE.match(tokens[0]):
        target_code = tokens.pop(0)

    # Lastname
    if not tokens:
        logger.warning("assembler  No name tokens for athlete at position %d", position)
        return None
    lastname = tokens.pop(0)

    # Firstname
    if not tokens:
        logger.warning("assembler  Only lastname found for athlete at position %d", position)
        firstname = ""
    else:
        firstname = tokens.pop(0)

    # Class code — next token if it's a known AGE_CLASS key
    class_code = ""
    if tokens and tokens[0] in AGE_CLASS:
        class_code = tokens.pop(0)
    else:
        # Scan forward for a known class code
        for i, t in enumerate(tokens):
            if t in AGE_CLASS:
                class_code = tokens.pop(i)
                break
        if not class_code:
            logger.warning(
                "assembler  No class code found for %s %s at position %d",
                lastname, firstname, position,
            )

    # Club — non-numeric tokens before the first score
    non_numeric: list[str] = []
    while tokens:
        v = _parse_int(tokens[0])
        if v is not None:
            break
        non_numeric.append(tokens.pop(0))

    club_code, club_name = _parse_club(non_numeric)

    # Score integers from line 1: only the remaining tokens (already past all
    # header fields — `tokens` now holds only the numeric score tokens).
    score_integers: list[int] = _collect_integers(tokens)

    # -----------------------------------------------------------------------
    # Collect score integers from continuation lines (all tokens are scores)
    # -----------------------------------------------------------------------
    for cont_line in lines[1:]:
        cont_tokens = [w.text for w in cont_line]
        score_integers.extend(_collect_integers(cont_tokens))

    # -----------------------------------------------------------------------
    # Parse scores
    # -----------------------------------------------------------------------
    if len(score_integers) < 3:
        logger.warning(
            "assembler  Insufficient score integers for %s %s: %s",
            lastname, firstname, score_integers,
        )
        end_scores, half_totals, grand_total = [], [], 0
        tens_plus_x, x_count = 0, 0
    else:
        tens_plus_x = score_integers[-2]
        x_count     = score_integers[-1]
        end_scores, half_totals, grand_total = _parse_scores(score_integers)

    return AthleteRecord(
        position=position,
        target_code=target_code,
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
        section=section.context,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_athletes(sections: list[RawSection]) -> list[AthleteRecord]:
    """
    Convert a list of RawSection objects into a flat list of AthleteRecord
    objects, one per athlete.

    For each section, printed lines are grouped using the position + target-code
    pattern as a start-of-athlete anchor.  Continuation lines (those that do
    NOT match the start pattern) are appended to the current athlete's buffer.
    At end-of-section the last accumulated athlete is finalised.

    Args:
        sections: Output of detector.detect_sections().

    Returns:
        Flat list of AthleteRecord objects across all sections, in document
        order.
    """
    records: list[AthleteRecord] = []

    for section in sections:
        section_start_idx = len(records)
        current_group: list[list[Word]] = []

        def _finalise(group: list[list[Word]], sec: RawSection = section) -> None:
            if not group:
                return
            record = _parse_athlete_lines(group, sec)
            if record is not None:
                records.append(record)

        for line in section.lines:
            tokens = [w.text for w in line]
            if not tokens:
                continue

            if _is_athlete_start(tokens):
                _finalise(current_group)
                current_group = [line]
            else:
                current_group.append(line)

        # Finalise the last athlete in the section
        _finalise(current_group)

        section_athlete_count = len(records) - section_start_idx
        logger.info(
            "assembler  Section %s/%s/%s → %d athletes",
            section.context.bow_type,
            section.context.age_class,
            section.context.gender,
            section_athlete_count,
        )

    return records
