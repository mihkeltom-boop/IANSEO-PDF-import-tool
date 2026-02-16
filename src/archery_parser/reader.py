"""
Module 1 — Reader.

Responsible for opening a PDF file and extracting all text words with their
bounding-box coordinates, then grouping them into logical lines sorted
left-to-right and top-to-bottom.

Words are grouped into the same line when their y-midpoints ((y0+y1)/2)
differ by less than Y_TOLERANCE points (default 4pt).  Within a line words
are sorted left-to-right by x0; lines are sorted top-to-bottom by their
mean y0.

Public API:
    extract_lines(pdf_path) -> list[list[Word]]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

# Words whose y-midpoints fall within this many points are considered the
# same printed line.
Y_TOLERANCE: float = 4.0


@dataclass
class Word:
    """
    A single text token extracted from a PDF page, with its bounding box.

    Attributes:
        text:  The string content of the word.
        x0:    Left edge of the bounding box in PDF user-space points.
        y0:    Top edge of the bounding box in PDF user-space points.
        x1:    Right edge of the bounding box.
        y1:    Bottom edge of the bounding box.
    """

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def y_mid(self) -> float:
        """Vertical midpoint, used for line-grouping comparisons."""
        return (self.y0 + self.y1) / 2.0


def _group_into_lines(words: list[Word], y_tolerance: float = Y_TOLERANCE) -> list[list[Word]]:
    """
    Group a flat list of Word objects into logical lines.

    Words are sorted by y-midpoint first, then grouped greedily: a new line
    starts whenever the next word's y-midpoint is more than y_tolerance away
    from the first word in the current line.

    Within each line, words are sorted left-to-right by x0.
    Lines are returned sorted top-to-bottom by the mean y0 of their words.

    Args:
        words:        Flat list of Word objects.
        y_tolerance:  Maximum y-midpoint gap (points) for same-line grouping.

    Returns:
        List of lines, each line being a list of Word objects sorted by x0.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: w.y_mid)

    lines: list[list[Word]] = []
    current_line: list[Word] = [sorted_words[0]]
    current_ref_y: float = sorted_words[0].y_mid

    for word in sorted_words[1:]:
        if abs(word.y_mid - current_ref_y) < y_tolerance:
            current_line.append(word)
        else:
            lines.append(current_line)
            current_line = [word]
            current_ref_y = word.y_mid

    lines.append(current_line)

    # Sort each line left-to-right by x0.
    for line in lines:
        line.sort(key=lambda w: w.x0)

    # Sort lines top-to-bottom by mean y0.
    lines.sort(key=lambda line: sum(w.y0 for w in line) / len(line))

    return lines


def extract_lines(pdf_path: str | Path, y_tolerance: float = Y_TOLERANCE) -> list[list[Word]]:
    """
    Open a PDF file and return all its text as a list of logical lines.

    Each page is processed independently (words are grouped into lines
    per-page) to avoid false merges across page boundaries.  The resulting
    line lists are concatenated in page order.

    Args:
        pdf_path:     Path to the PDF file (str or pathlib.Path).
        y_tolerance:  Maximum y-midpoint gap for same-line grouping (default 4pt).

    Returns:
        List of logical lines, each line being a list of Word objects sorted
        left-to-right.  Lines are ordered top-to-bottom within each page and
        pages are in document order.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    all_lines: list[list[Word]] = []

    with pdfplumber.open(pdf_path) as pdf:
        logger.info("reader  Opened: %s (%d pages)", pdf_path.name, len(pdf.pages))

        for page_num, page in enumerate(pdf.pages, start=1):
            raw_words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
            )

            page_words: list[Word] = []
            for rw in raw_words:
                text = rw.get("text", "").strip()
                if not text:
                    continue
                # pdfplumber uses "top"/"bottom" for y coords (distance from
                # page top), which maps directly to y0/y1 in our Word model.
                page_words.append(
                    Word(
                        text=text,
                        x0=float(rw["x0"]),
                        y0=float(rw["top"]),
                        x1=float(rw["x1"]),
                        y1=float(rw["bottom"]),
                    )
                )

            page_lines = _group_into_lines(page_words, y_tolerance=y_tolerance)
            all_lines.extend(page_lines)

            logger.debug("reader  Page %d: %d words → %d lines",
                         page_num, len(page_words), len(page_lines))

    return all_lines
