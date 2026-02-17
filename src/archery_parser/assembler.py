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
from archery_parser.models import AthleteRecord, SectionContext
from archery_parser.reader import Word

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Target code: digit-NNNLetter  e.g. "2-001A", "1-014C"
_TARGET_CODE_RE = re.compile(r"^\d-\d{3}[A-Z]$")

# Split target code: some PDFs render the target code as two tokens,
# e.g. "1-" and "028B" instead of "1-028B".
_TARGET_PREFIX_RE = re.compile(r"^\d-$")       # e.g. "1-"
_TARGET_SUFFIX_RE = re.compile(r"^\d{3}[A-Z]$")  # e.g. "028B"

# Club code: 2–6 uppercase ASCII letters (no digits, no lowercase)
_CLUB_CODE_RE = re.compile(r"^[A-Z]{2,6}$")

# Compact rank token: score/rank packed without a space, e.g. "200/11",
# "260/10", "94/15".  These appear in some Ianseo PDFs instead of the
# normal "260/" + "10" (two tokens) layout.  Must be recognised as numeric
# to avoid bleeding into the club-name field.
_COMPACT_RANK_RE = re.compile(r"^\d+/\s*\d+$")


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
    Parse a token as an integer, stripping thousands separators and
    trailing rank indicators.
    Returns None if the token is not numeric.

    Both commas and periods are stripped because Ianseo PDFs may use
    either as a thousands separator depending on locale (e.g. "1,238"
    in English or "1.238" in European formats).  All score values in
    archery are integers, so there is no risk of misinterpreting
    decimal fractions.

    Trailing "/" is stripped because some Ianseo PDFs render end scores
    with rank suffixes (e.g. "311/" where the rank follows as a separate
    token).
    """
    cleaned = token.replace(",", "").replace(".", "").rstrip("/")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _is_athlete_start(tokens: list[str]) -> bool:
    """
    Return True if this line is the start of a new athlete.

    A line is an ATHLETE START if:
      1. Its first token is a positive integer (the position number), AND
      2. Its second token matches the target-code pattern (\\d-\\d{3}[A-Z]),
         OR tokens[1]+tokens[2] form a split target code ("1-" + "028B").

    This two-condition check avoids false matches on continuation lines that
    also begin with a positive integer (a score value).
    """
    if len(tokens) < 2:
        return False
    if not _is_positive_int(tokens[0]):
        return False
    # Full target code in one token
    if _TARGET_CODE_RE.match(tokens[1]):
        return True
    # Split target code across two tokens: "1-" + "028B"
    if len(tokens) >= 3 and _TARGET_PREFIX_RE.match(tokens[1]) and _TARGET_SUFFIX_RE.match(tokens[2]):
        return True
    return False


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


def _has_rank_format(lines: list[list[Word]]) -> bool:
    """
    Return True if any line contains rank-format score tokens.

    Rank format is indicated by:
      - Trailing-slash tokens like "311/" (score 311, rank follows as next token)
      - Compact rank tokens like "200/11" (score and rank packed in one token)

    Note: Check ALL lines including the first one, as some PDFs have all
    score data on a single line.
    """
    for line in lines:
        for w in line:
            if w.text.endswith("/"):
                return True
            if _COMPACT_RANK_RE.match(w.text):
                return True
    return False


def _collect_continuation_integers(tokens: list[str]) -> list[int]:
    """
    Collect score integers from a rank-format continuation line, skipping
    rank values.

    In rank format, end scores have a "/" suffix (e.g. "311/") and the
    next token is the rank (e.g. "1") which should be skipped.  Compact
    rank tokens (e.g. "200/11") encode score and rank in a single token —
    the score part before the "/" is extracted and the rank is discarded.

    Example: ["311/", "1", "293/", "2", "604"] → [311, 293, 604]
    Example: ["200/11", "220/10", "420"]        → [200, 220, 420]
    """
    result = []
    skip_next = False
    for t in tokens:
        if skip_next:
            skip_next = False
            continue
        m = _COMPACT_RANK_RE.match(t)
        if m:
            # Compact rank: extract score (before "/"), discard rank
            score_str = t.split("/")[0]
            try:
                result.append(int(score_str))
            except ValueError:
                pass
            # No skip_next — rank is in the same token
        elif t.endswith("/"):
            v = _parse_int(t)
            if v is not None:
                result.append(v)
            skip_next = True
        else:
            v = _parse_int(t)
            if v is not None:
                result.append(v)
    return result


def _parse_rank_line_scores(tokens: list[str]) -> tuple[list[int], int]:
    """
    Parse one rank-format continuation line into (end_scores, subtotal).

    Rank-format tokens have a "/" suffix (e.g. "285/"); the integer that
    immediately follows is the within-line rank and is skipped.  All other
    plain integers between the last ranked score and the end of the line are
    also skipped — they are structural artefacts (e.g. the two "0 0" values
    in Visa-HIng POST lines).  Only the **last** plain integer on the line
    is treated as the line subtotal.

    Example (Visa-HIng POST):
        ["285/", "4", "283/", "3", "0", "0", "568"] → ([285, 283], 568)

    Example (Puiatu-CUP PRE):
        ["318/", "1", "293/", "1", "611"] → ([318, 293], 611)
    """
    end_scores: list[int] = []
    last_plain: int | None = None
    skip_next = False
    for t in tokens:
        if skip_next:
            skip_next = False
            continue
        m = _COMPACT_RANK_RE.match(t)
        if m:
            # Compact rank: score/rank in one token, e.g. "200/11"
            score_str = t.split("/")[0]
            try:
                end_scores.append(int(score_str))
            except ValueError:
                pass
        elif t.endswith("/"):
            v = _parse_int(t)
            if v is not None:
                end_scores.append(v)
            skip_next = True
        else:
            v = _parse_int(t)
            if v is not None:
                last_plain = v          # keep overwriting; final value is subtotal
    return end_scores, (last_plain or 0)


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

    # Target code — may be a single token ("2-001A") or split ("1-" + "028B")
    target_code = ""
    if tokens and _TARGET_CODE_RE.match(tokens[0]):
        target_code = tokens.pop(0)
    elif (
        len(tokens) >= 2
        and _TARGET_PREFIX_RE.match(tokens[0])
        and _TARGET_SUFFIX_RE.match(tokens[1])
    ):
        target_code = tokens.pop(0) + tokens.pop(0)

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

    # Class code — next token if it's a known AGE_CLASS key.
    # If the class code is not immediately next, scan forward — any tokens
    # between the firstname and the class code are middle names (e.g.
    # "LEPIK Lisete Laureen W VVVK" → firstname becomes "Lisete Laureen").
    class_code = ""
    if tokens and tokens[0] in AGE_CLASS:
        class_code = tokens.pop(0)
    else:
        # Scan forward for a known class code
        for i, t in enumerate(tokens):
            if t in AGE_CLASS:
                # Tokens before the class code are middle names — absorb them
                # into firstname so they don't leak into the club field.
                middle_parts = [tokens.pop(0) for _ in range(i)]
                if middle_parts:
                    firstname = firstname + " " + " ".join(middle_parts)
                class_code = tokens.pop(0)
                break
        if not class_code:
            logger.debug(
                "assembler  No class code found for %s %s at position %d"
                " (will use section class)",
                lastname, firstname, position,
            )

    # Some athletes carry a second class code on the line (e.g. a U15
    # athlete competing in the U21 section: "U21W U15W").  Consume any
    # additional class code tokens so they don't leak into the club field.
    while tokens and tokens[0] in AGE_CLASS:
        tokens.pop(0)

    # Club — non-numeric tokens before the first score.
    # A token is considered "numeric" (= score boundary) if _parse_int()
    # succeeds OR if it matches the compact rank pattern "NNN/NN".
    non_numeric: list[str] = []
    while tokens:
        if _parse_int(tokens[0]) is not None:
            break
        if _COMPACT_RANK_RE.match(tokens[0]):
            break
        non_numeric.append(tokens.pop(0))

    club_code, club_name = _parse_club(non_numeric)

    # -----------------------------------------------------------------------
    # Detect score format and collect integers accordingly
    # -----------------------------------------------------------------------
    rank_format = _has_rank_format(lines)

    # Score integers from line 1: only the remaining tokens (already past all
    # header fields — `tokens` now holds only the numeric score tokens).
    # If rank format is detected, use rank-aware parsing even for header line.
    if rank_format:
        header_integers: list[int] = _collect_continuation_integers(tokens)
    else:
        header_integers: list[int] = _collect_integers(tokens)

    # Collect score integers from continuation lines
    cont_integers: list[int] = []
    for cont_line in lines[1:]:
        cont_tokens = [w.text for w in cont_line]
        if rank_format:
            cont_integers.extend(_collect_continuation_integers(cont_tokens))
        else:
            cont_integers.extend(_collect_integers(cont_tokens))

    # -----------------------------------------------------------------------
    # Parse scores — layout depends on format
    # -----------------------------------------------------------------------
    if rank_format and len(header_integers) >= 2:
        # Rank format: scores have "/" suffix and ranks follow.
        # 10+X and X are always the last two values.
        tens_plus_x = header_integers[-2]
        x_count     = header_integers[-1]

        # Score values can be either:
        # A) All on header line: [end_a, end_b, grand_total, 10+X, X]
        # B) Split across lines: header = [scoring_index, 10+X, X],
        #                        cont = [end_a, end_b, half_total, ...]
        end_scores: list[int] = []
        half_totals: list[int] = []

        if cont_integers:
            # Case B: Scores are on continuation lines.
            # Step 1 — collect end scores from each continuation line using
            # per-line parsing.  This correctly handles:
            #   • Lines with more than 2 ends (e.g. Visa-HIng PRE with 4 ends).
            #   • Spurious plain integers in POST lines (e.g. "0 0" in Visa-HIng
            #     "285/ 4 283/ 3 0 0 568") — only the last plain integer on each
            #     line is the line subtotal; it is used for verification only.
            for cont_line in lines[1:]:
                cont_tokens = [w.text for w in cont_line]
                line_ends, _ = _parse_rank_line_scores(cont_tokens)
                end_scores.extend(line_ends)
            # Step 2 — derive half-totals from consecutive pairs of end scores.
            # Only produced for rounds with 4+ ends (e.g. Visa-HIng PRE with 4
            # ends → 2 half-totals).  2-end rounds have no intermediate half-
            # subtotal regardless of how many continuation lines were present.
            if len(end_scores) >= 4:
                half_totals = [
                    end_scores[i] + end_scores[i + 1]
                    for i in range(0, len(end_scores) - 1, 2)
                ]
            else:
                half_totals = []
            grand_total = sum(half_totals) if half_totals else sum(end_scores)
        else:
            # Case A: All scores on header line [e1, e2, grand_total, 10+X, X]
            # Extract grand total (third from end) and end scores
            if len(header_integers) >= 3:
                grand_total = header_integers[-3]
                # End scores are everything before grand_total, 10+X, X.
                # Some single-distance rank-format PDFs include a zero filler
                # column for the non-existent second end, e.g.:
                #   "543/ 1  0  543  8  0"  → end_scores=[543, 0]
                # Strip trailing zeros because 0 is never a valid archery end.
                raw_ends = header_integers[:-3]
                while raw_ends and raw_ends[-1] == 0:
                    raw_ends.pop()
                end_scores = raw_ends
            else:
                # Degenerate case: too few values
                grand_total = 0
                end_scores = []
    else:
        # Original format: all ints combined, last 2 are 10+X and X
        score_integers = header_integers + cont_integers
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
                if current_group and _is_athlete_start([w.text for w in current_group[0]]):
                    # current_group already has an anchor (the previous athlete).
                    # In rank-format PDFs the line immediately before a new anchor
                    # is a pre-score line belonging to THIS new athlete — detect and
                    # carry it forward rather than finalising it with the old athlete.
                    pre_scores: list = []
                    if len(current_group) > 1:
                        last_toks = [w.text for w in current_group[-1]]
                        # Carry forward if the last line starts with a
                        # rank-format score token — either trailing-slash
                        # ("246/") or compact rank ("196/10").
                        if last_toks and (
                            last_toks[0].endswith("/")
                            or bool(_COMPACT_RANK_RE.match(last_toks[0]))
                        ):
                            pre_scores = [current_group.pop()]
                    _finalise(current_group)
                    current_group = [line] + pre_scores
                else:
                    # current_group contains only pre-score lines that arrived
                    # before the first anchor in this section.  They belong to
                    # THIS athlete — keep them as continuation lines.
                    pre_scores = list(current_group)
                    current_group = [line] + pre_scores
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

        # Validate: all athletes in the same section must have the same
        # number of end scores, matching the expected count from distances.
        _validate_section_result_counts(
            records[section_start_idx:], section.context,
        )

        # Validate: names and club fields must not contain digits.
        for rec in records[section_start_idx:]:
            _validate_no_digits_in_name_or_club(rec)

    return records


def _validate_section_result_counts(
    section_records: list[AthleteRecord],
    context: SectionContext,
) -> None:
    """
    Warn if athletes in a section have inconsistent result counts.

    All athletes in one section shot the same round, so they must all
    have the same number of end scores.  The expected count equals the
    number of distances defined in the section context.

    Also checks half-total counts against the expected value derived
    from end count (one half-total per pair of ends).
    """
    if not section_records:
        return

    expected_ends = len(context.distances)
    expected_halves = expected_ends // 2 if expected_ends > 2 else 0
    section_label = f"{context.bow_type}/{context.age_class}/{context.gender}"

    for rec in section_records:
        actual_ends = len(rec.end_scores)
        actual_halves = len(rec.half_totals)

        if actual_ends != expected_ends:
            logger.warning(
                "assembler  Result count mismatch in %s: "
                "%s %s has %d end scores, expected %d",
                section_label,
                rec.firstname, rec.lastname,
                actual_ends, expected_ends,
            )

        if actual_halves != expected_halves:
            logger.warning(
                "assembler  Result count mismatch in %s: "
                "%s %s has %d half-totals, expected %d",
                section_label,
                rec.firstname, rec.lastname,
                actual_halves, expected_halves,
            )


def _validate_no_digits_in_name_or_club(rec: AthleteRecord) -> None:
    """
    Warn if an athlete's name or club field contains a digit.

    Digits in these fields indicate a parsing error.  Two known causes:

    1. Compact rank-format scores (e.g. "200/11" with no space between
       score and rank) are not recognised as numeric tokens and fall
       through into the club-name parser.

    2. A middle name (extra token after the recognised firstname) causes
       that token to be absorbed into the club field, which then also
       sweeps in trailing score tokens.

    Legitimate athlete names and club names never contain digits.
    """
    _has_digit = re.compile(r'\d')

    athlete_label = f"{rec.firstname} {rec.lastname}"

    for field_name, value in (
        ("firstname", rec.firstname),
        ("lastname",  rec.lastname),
        ("club_code", rec.club_code or ""),
        ("club_name", rec.club_name or ""),
    ):
        if _has_digit.search(value):
            logger.warning(
                "assembler  Digit found in %s for athlete %s: %r — "
                "likely a parsing error (score absorbed into field, "
                "or unrecognised middle name)",
                field_name, athlete_label, value,
            )
