"""
Module 2 — Detector.

Scans the raw line stream produced by the Reader and identifies:
  * The competition header (name, organiser, event code, venue, dates).
  * Section boundaries keyed on "After N Arrows" sentinel lines.
  * Section titles (bow type + age/gender class in Estonian).
  * Column headers (distance labels per end).
  * Athlete data lines for each section.

State machine:
  HEADER          → reads first 3 lines as competition header
  BETWEEN         → waiting for "After N Arrows"
  EXPECT_TITLE    → next non-empty line is the section title
  EXPECT_COL_HDR  → reading distance column-header lines; transitions to
                    ATHLETE_DATA on first line starting with a positive integer
  ATHLETE_DATA    → collecting lines until the next "After N Arrows"
  SKIP_SECTION    → unknown section; discard lines until next "After N Arrows"

Public API:
    detect_sections(lines) -> tuple[CompetitionMeta, list[RawSection]]
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from archery_parser.lookups import AGE_CLASS, BOW_TYPE, GENDER, build_distance_context
from archery_parser.models import CompetitionMeta, SectionContext
from archery_parser.reader import Word

logger = logging.getLogger(__name__)


class _State(enum.Enum):
    """States for the section-detection state machine."""
    HEADER = "HEADER"
    BETWEEN = "BETWEEN"
    EXPECT_TITLE = "EXPECT_TITLE"
    EXPECT_COL_HDR = "EXPECT_COL_HDR"
    ATHLETE_DATA = "ATHLETE_DATA"
    SKIP_SECTION = "SKIP_SECTION"


# ---------------------------------------------------------------------------
# RawSection  (output of this module, input to Assembler)
# ---------------------------------------------------------------------------

@dataclass
class RawSection:
    """
    One parsed category section, ready for the Assembler.

    Attributes:
        context:  Fully populated SectionContext for this bow/age/gender combo.
        lines:    Athlete data lines only — header and column-label lines have
                  been stripped.  Each element is a list of Word objects
                  representing one printed line.
    """
    context: SectionContext
    lines: list[list[Word]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal Estonian → class-code lookup tables
# ---------------------------------------------------------------------------

# Age prefix tokens found in Estonian/English section titles.
# Maps to the prefix part of a class code (without gender suffix).
_AGE_PREFIX: dict[str, str] = {
    "U21": "U21",
    "U18": "U18",
    "U15": "U15",
    "U13": "U13",
    "U10": "U10",
    "Veteranid": "50",
    "50+": "50",
    "+50": "50",
    "30": "30",
}

# Multi-word English age phrases found in Ianseo English section titles.
# These map "Under NN" → "UNN" prefix (processed before single-token lookup).
_ENGLISH_AGE_PHRASES: dict[str, str] = {
    "Under 21": "U21",
    "Under 18": "U18",
    "Under 15": "U15",
    "Under 13": "U13",
    "Under 10": "U10",
}

# Gender tokens in Estonian section titles → M or W gender character.
# Keys are lowercase for case-insensitive matching.
_GENDER_TOKEN: dict[str, str] = {
    # Estonian
    "mehed":        "M",   # Men (adult)
    "noormehed":    "M",   # Young men (covers U18/U21 in some clubs)
    "poisid":       "M",   # Boys (U15 and below)
    "mees":         "M",   # Man (singular, rare)
    "naised":       "W",   # Women
    "neiud":        "W",   # Girls / young women
    "tüdrukud":     "W",   # Girls (U15 and below)
    "naine":        "W",   # Woman (singular, rare)
    "täiskasvanud": "M",   # Adults (gender-neutral, default to M)
    "algajad":      "M",   # Beginners (gender-neutral, default to M)
    # English (Ianseo English language setting)
    "men":          "M",
    "women":        "W",
    "boys":         "M",
    "girls":        "W",
}


def _parse_section_class_code(bow_prefix: str, remaining_tokens: list[str]) -> str | None:
    """
    Derive a class code (e.g. "M", "U18W", "50M", "HM") from the section
    title tokens that follow the bow-type prefix word.

    Handles both Estonian tokens (e.g. "Mehed", "U18", "Poisid") and English
    multi-word phrases (e.g. "- Under 18 Men", "- 50+ Women", "- 30 Men").

    Args:
        bow_prefix:       The first word of the section title (e.g. "Sportvibu").
        remaining_tokens: Remaining words after the bow-type prefix.

    Returns:
        A class code string, or None if the gender token is not found.
    """
    # Strip leading "-" separator (English titles: "Recurve - Men")
    tokens = [t for t in remaining_tokens if t != "-"]

    # Also strip "Continue" suffix (e.g. "Under 18 Men Continue" for overflow pages)
    if tokens and tokens[-1].lower() == "continue":
        tokens = tokens[:-1]

    age_prefix = ""
    gender_char = ""

    # Check for multi-word English age phrases first ("Under 18", etc.)
    joined = " ".join(tokens)
    for phrase, code in _ENGLISH_AGE_PHRASES.items():
        if phrase in joined:
            age_prefix = code
            # Remove the phrase tokens so they don't interfere with gender detection
            tokens = joined.replace(phrase, "").split()
            break

    for token in tokens:
        token_lower = token.lower()
        if not age_prefix and token in _AGE_PREFIX:
            age_prefix = _AGE_PREFIX[token]
        elif token_lower in _GENDER_TOKEN:
            gender_char = _GENDER_TOKEN[token_lower]
            # Warn if using gender-neutral token (needs manual review)
            if token_lower in ("täiskasvanud", "algajad"):
                logger.warning(
                    "detector  Gender-neutral token '%s' found; defaulting to M. "
                    "Manual review recommended for accurate gender assignment.",
                    token
                )

    if not gender_char:
        return None

    # Harrastajad (hobby archers) use class codes HM / HW.
    if bow_prefix == "Harrastajad":
        return "H" + gender_char

    # Veterans: age_prefix="50", so class code = "50M" / "50W"
    # Regular adult: age_prefix="", class code = "M" / "W"
    return age_prefix + gender_char


# ---------------------------------------------------------------------------
# Competition header parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
_EVENT_CODE_RE = re.compile(r"\(([^)]+)\)")


def _parse_date(first: str, second: str, year: str) -> date:
    """
    Parse a date from two ambiguous values and a year.

    The input format could be DD-MM-YYYY or MM-DD-YYYY.
    Use heuristics to determine which:
    - If first > 12: it must be day (format is DD-MM-YYYY)
    - If second > 12: it must be day (format is MM-DD-YYYY)
    - If both ≤ 12: ambiguous, default to DD-MM-YYYY (Estonian standard)

    Args:
        first: First two-digit value (could be day or month)
        second: Second two-digit value (could be month or day)
        year: Four-digit year

    Returns:
        Parsed date object

    Raises:
        ValueError: If date values are invalid
    """
    val1 = int(first)
    val2 = int(second)
    yyyy = int(year)

    # Determine format based on which value could be a month
    if val1 > 12:
        # first must be day, second must be month (DD-MM-YYYY)
        return date(yyyy, val2, val1)
    elif val2 > 12:
        # second must be day, first must be month (MM-DD-YYYY)
        return date(yyyy, val1, val2)
    else:
        # Both ≤ 12: ambiguous. Default to DD-MM-YYYY (Estonian standard).
        # Try DD-MM-YYYY first, fall back to MM-DD-YYYY if invalid.
        try:
            return date(yyyy, val2, val1)
        except ValueError:
            # Invalid day for that month, try MM-DD-YYYY instead
            return date(yyyy, val1, val2)


def _parse_competition_header(header_lines: list[list[Word]]) -> CompetitionMeta:
    """
    Extract CompetitionMeta from the first three lines of the document.

    Line 1: competition name
    Line 2: organiser text + "(EVENT_CODE)"
    Line 3: venue name + "From DD-MM-YYYY to DD-MM-YYYY"

    Args:
        header_lines: Exactly three lines from the Reader output.

    Returns:
        Populated CompetitionMeta dataclass.
    """
    # Line 1 — competition name
    name = " ".join(w.text for w in header_lines[0]).strip()

    # Line 2 — organiser and event code
    line2_text = " ".join(w.text for w in header_lines[1])
    code_match = _EVENT_CODE_RE.search(line2_text)
    event_code = code_match.group(1).strip() if code_match else ""
    # Organiser is everything before the opening parenthesis
    organiser = line2_text[:code_match.start()].strip().rstrip(",").rstrip() if code_match else line2_text.strip()

    # Line 3 — venue and dates
    line3_text = " ".join(w.text for w in header_lines[2])
    # Venue is everything before "From" (multi-day) or before the first date (single-day)
    from_idx = line3_text.find("From")
    if from_idx != -1:
        venue = line3_text[:from_idx].strip().rstrip(",").rstrip()
    else:
        # Single-day event: venue is text before the DD-MM-YYYY date
        date_m = _DATE_RE.search(line3_text)
        if date_m:
            venue = line3_text[:date_m.start()].strip().rstrip(",").rstrip()
        else:
            venue = line3_text.strip()

    # Parse all dates from the line (handles both DD-MM-YYYY and MM-DD-YYYY)
    date_matches = _DATE_RE.findall(line3_text)
    dates: list[date] = []
    for first, second, year in date_matches:
        try:
            dates.append(_parse_date(first, second, year))
        except ValueError as e:
            logger.warning(
                "detector  Failed to parse date '%s-%s-%s': %s",
                first, second, year, e
            )

    date_start = dates[0] if len(dates) >= 1 else date.today()
    date_end   = dates[1] if len(dates) >= 2 else date_start

    return CompetitionMeta(
        name=name,
        organiser=organiser,
        event_code=event_code,
        venue=venue,
        date_start=date_start,
        date_end=date_end,
    )


# ---------------------------------------------------------------------------
# Column-header line helpers
# ---------------------------------------------------------------------------

# Matches distance tokens in two formats:
#   - With suffix: "70m-1", "30m-4" (numbered columns)
#   - Without suffix: "70m", "30m" (1440 round format)
_DIST_TOKEN_RE = re.compile(r"^(\d+m)(?:-\d+)?$")


def _is_column_header_line(tokens: list[str]) -> bool:
    """
    Return True if the line contains at least one distance token.

    Matches both formats: "70m-1" (with suffix) and "70m" (plain).
    """
    return any(_DIST_TOKEN_RE.match(t) for t in tokens)


def _extract_distances_from_line(tokens: list[str]) -> list[str]:
    """
    Return ordered list of distance strings from a column-header line.

    Handles both formats:
      - With suffix: ["70m-1", "70m-2", "Tot."] → ["70m", "70m"]
      - Plain: ["90m", "70m", "Tot."] → ["90m", "70m"]
    """
    distances = []
    for token in tokens:
        m = _DIST_TOKEN_RE.match(token)
        if m:
            distances.append(m.group(1))   # e.g. "70m"
    return distances


# ---------------------------------------------------------------------------
# "After N Arrows" sentinel
# ---------------------------------------------------------------------------

_AFTER_ARROWS_RE = re.compile(r"^After\s+(\d+)\s+Arrows$", re.IGNORECASE)


def _match_after_arrows(tokens: list[str]) -> int | None:
    """
    If the line is the 'After N Arrows' sentinel, return N; else None.
    Matches both as a single joined string and as multi-token line.
    """
    joined = " ".join(tokens)
    m = _AFTER_ARROWS_RE.match(joined)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Positive-integer start detection (athlete-line anchor)
# ---------------------------------------------------------------------------

def _starts_with_positive_int(tokens: list[str]) -> bool:
    """Return True if the first token of the line is a positive integer.

    Strips a trailing "/" before parsing so that rank-format score tokens
    like "290/" are correctly recognised (int("290/") would raise ValueError).
    """
    if not tokens:
        return False
    try:
        return int(tokens[0].rstrip("/")) > 0
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_sections(
    lines: list[list[Word]],
) -> tuple[CompetitionMeta, list[RawSection]]:
    """
    Scan the full line stream and return competition metadata plus a list of
    raw sections, each containing its SectionContext and raw athlete lines.

    Args:
        lines: Output of reader.extract_lines() — list of logical lines,
               each line being a list of Word objects.

    Returns:
        (CompetitionMeta, list[RawSection])

    Raises:
        ValueError: If the competition header cannot be parsed from the first
                    three lines (FATAL condition per Section 8.1).
    """
    if len(lines) < 3:
        raise ValueError("Input too short to contain a competition header.")

    # Early validation: the third line should contain a DD-MM-YYYY date,
    # either as "From DD-MM-YYYY to DD-MM-YYYY" (multi-day) or as a bare
    # date like "Venue, DD-MM-YYYY" (single-day event).
    line3_text = " ".join(w.text for w in lines[2])
    if not _DATE_RE.search(line3_text):
        raise ValueError(
            "This does not appear to be an Ianseo qualification protocol: "
            "expected a DD-MM-YYYY date in the third line of the document."
        )

    sections: list[RawSection] = []
    meta: CompetitionMeta | None = None

    # State machine
    state = _State.HEADER
    header_buf: list[list[Word]] = []

    # Per-section working state
    current_arrow_count: int = 0
    current_bow_prefix: str = ""
    current_class_code: str = ""
    current_distances: list[str] = []
    current_lines: list[list[Word]] = []

    def _finalise_section() -> None:
        """Commit current_lines into a completed RawSection and reset buffers."""
        nonlocal current_distances, current_lines, current_class_code, current_bow_prefix, current_arrow_count
        if not current_class_code or not current_bow_prefix:
            return
        if current_class_code not in AGE_CLASS:
            logger.warning(
                "detector  Unknown class code '%s' for bow prefix '%s' — section skipped.",
                current_class_code, current_bow_prefix,
            )
            _reset_section()
            return

        # Infer arrow count from number of distance columns if not set by sentinel
        if current_arrow_count == 0 and current_distances:
            # Each distance column typically represents 18 arrows (2 ends of 6 arrows)
            current_arrow_count = len(current_distances) * 18
            logger.info(
                "detector  Arrow count inferred from %d distance columns: %d arrows",
                len(current_distances), current_arrow_count
            )

        dist_ctx = build_distance_context(current_distances)
        ctx = SectionContext(
            bow_type=BOW_TYPE[current_bow_prefix],
            age_class=AGE_CLASS[current_class_code],
            gender=GENDER[current_class_code],
            arrow_count=current_arrow_count,
            distances=list(current_distances),
            half_labels=dist_ctx["half_labels"],
            total_label=dist_ctx["total_label"],
        )
        sections.append(RawSection(context=ctx, lines=list(current_lines)))
        logger.info(
            "detector  Section: %s / %s / %s — %d athlete lines",
            ctx.bow_type, ctx.age_class, ctx.gender, len(current_lines),
        )
        _reset_section()

    def _reset_section() -> None:
        nonlocal current_distances, current_lines, current_class_code, current_bow_prefix
        current_distances = []
        current_lines = []
        current_class_code = ""
        current_bow_prefix = ""

    for line in lines:
        tokens = [w.text for w in line]
        if not tokens:
            continue

        # ----------------------------------------------------------------
        # HEADER  — collect first 3 non-empty lines
        # ----------------------------------------------------------------
        if state is _State.HEADER:
            header_buf.append(line)
            if len(header_buf) == 3:
                try:
                    meta = _parse_competition_header(header_buf)
                    logger.info("detector  Competition: %s", meta.name)
                except Exception as exc:
                    raise ValueError(f"Failed to parse competition header: {exc}") from exc
                state = _State.BETWEEN
            continue

        # ----------------------------------------------------------------
        # "After N Arrows" sentinel — always checked regardless of state
        # ----------------------------------------------------------------
        arrow_count = _match_after_arrows(tokens)
        if arrow_count is not None:
            # Finalise any open section
            if state is _State.ATHLETE_DATA:
                _finalise_section()
            elif state is _State.EXPECT_COL_HDR:
                # Section title was parsed but no athlete data yet — still finalise
                # (edge case: empty section)
                _finalise_section()
            else:
                _reset_section()
            current_arrow_count = arrow_count
            state = _State.EXPECT_TITLE
            continue

        # ----------------------------------------------------------------
        # BETWEEN  — waiting for "After N Arrows" OR a recognized bow-type prefix
        # ----------------------------------------------------------------
        if state is _State.BETWEEN:
            # Check if line starts with a known bow-type prefix (for PDFs without sentinels)
            bow_prefix = tokens[0] if tokens else ""
            if bow_prefix in BOW_TYPE:
                # Treat this as a section title and transition directly
                logger.info(
                    "detector  No 'After N Arrows' sentinel found; "
                    "inferring section start from bow type '%s'",
                    bow_prefix
                )
                remaining = tokens[1:]
                class_code = _parse_section_class_code(bow_prefix, remaining)
                if class_code is None:
                    logger.warning(
                        "detector  Cannot determine class code from section title '%s' — section skipped.",
                        " ".join(tokens),
                    )
                    state = _State.SKIP_SECTION
                    continue

                current_bow_prefix = bow_prefix
                current_class_code = class_code
                # Infer arrow count from first column header line (will be detected next)
                current_arrow_count = 0
                state = _State.EXPECT_COL_HDR
                continue
            # Otherwise, ignore line and stay in BETWEEN
            continue

        # ----------------------------------------------------------------
        # EXPECT_TITLE  — next non-empty line is the section title
        # ----------------------------------------------------------------
        if state is _State.EXPECT_TITLE:
            bow_prefix = tokens[0]
            if bow_prefix not in BOW_TYPE:
                logger.warning(
                    "detector  Unknown bow type '%s' in section title '%s' — section skipped.",
                    bow_prefix, " ".join(tokens),
                )
                state = _State.SKIP_SECTION
                continue

            remaining = tokens[1:]
            class_code = _parse_section_class_code(bow_prefix, remaining)
            if class_code is None:
                logger.warning(
                    "detector  Cannot determine class code from section title '%s' — section skipped.",
                    " ".join(tokens),
                )
                state = _State.SKIP_SECTION
                continue

            current_bow_prefix = bow_prefix
            current_class_code = class_code
            state = _State.EXPECT_COL_HDR
            continue

        # ----------------------------------------------------------------
        # SKIP_SECTION  — discard until "After N Arrows" (handled above)
        # ----------------------------------------------------------------
        if state is _State.SKIP_SECTION:
            continue

        # ----------------------------------------------------------------
        # EXPECT_COL_HDR  — collect distance labels; first athlete line
        #                    triggers transition to ATHLETE_DATA
        # ----------------------------------------------------------------
        if state is _State.EXPECT_COL_HDR:
            if _is_column_header_line(tokens):
                current_distances.extend(_extract_distances_from_line(tokens))
                # stay in EXPECT_COL_HDR to catch multi-line column headers
            elif _starts_with_positive_int(tokens):
                # First athlete line — finalise distances, switch state,
                # and fall through to ATHLETE_DATA handling below.
                state = _State.ATHLETE_DATA
                current_lines.append(line)
            # else: totals-header line like "Tot. 10+X X" — skip silently
            continue

        # ----------------------------------------------------------------
        # ATHLETE_DATA  — accumulate lines (continuation checked by assembler)
        # ----------------------------------------------------------------
        if state is _State.ATHLETE_DATA:
            current_lines.append(line)

    # End of document — finalise last open section
    if state is _State.ATHLETE_DATA:
        _finalise_section()

    if meta is None:
        raise ValueError("Competition header was never parsed.")

    return meta, sections
