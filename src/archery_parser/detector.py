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
_GENDER_TOKEN: dict[str, str] = {
    # Estonian
    "Mehed":     "M",   # Men (adult)
    "Noormehed": "M",   # Young men (covers U18/U21 in some clubs)
    "Poisid":    "M",   # Boys (U15 and below)
    "Mees":      "M",   # Man (singular, rare)
    "Naised":    "W",   # Women
    "Neiud":     "W",   # Girls / young women
    "Tüdrukud":  "W",   # Girls (U15 and below)
    "Naine":     "W",   # Woman (singular, rare)
    # English (Ianseo English language setting)
    "Men":       "M",
    "Women":     "W",
    "Boys":      "M",
    "Girls":     "W",
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
        if not age_prefix and token in _AGE_PREFIX:
            age_prefix = _AGE_PREFIX[token]
        elif token in _GENDER_TOKEN:
            gender_char = _GENDER_TOKEN[token]

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

    # Parse all DD-MM-YYYY dates from the line
    date_matches = _DATE_RE.findall(line3_text)
    dates: list[date] = []
    for dd, mm, yyyy in date_matches:
        dates.append(date(int(yyyy), int(mm), int(dd)))

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

_DIST_TOKEN_RE = re.compile(r"^(\d+m)-\d+$")   # matches e.g. "70m-1", "30m-4"


def _is_column_header_line(tokens: list[str]) -> bool:
    """Return True if the line contains at least one 'NNm-N' distance token."""
    return any(_DIST_TOKEN_RE.match(t) for t in tokens)


def _extract_distances_from_line(tokens: list[str]) -> list[str]:
    """
    Return ordered list of distance strings from a column-header line.

    e.g. ["70m-1", "70m-2", "Tot."] → ["70m", "70m"]
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
    """Return True if the first token of the line is a positive integer."""
    if not tokens:
        return False
    try:
        return int(tokens[0]) > 0
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
        nonlocal current_distances, current_lines, current_class_code, current_bow_prefix
        if not current_class_code or not current_bow_prefix:
            return
        if current_class_code not in AGE_CLASS:
            logger.warning(
                "detector  Unknown class code '%s' for bow prefix '%s' — section skipped.",
                current_class_code, current_bow_prefix,
            )
            _reset_section()
            return

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
        if state is _State.BETWEEN:
            continue  # ignore everything until first "After N Arrows"

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
