"""
Data models for the archery_parser pipeline.

Defines the three primary internal objects (CompetitionMeta, SectionContext,
AthleteRecord) plus the flat CSVRow that is the final output unit.
"""

from dataclasses import dataclass
from datetime import date
from typing import ClassVar


@dataclass
class CompetitionMeta:
    """
    Metadata extracted from the competition header on page 1 of an
    Ianseo qualification protocol PDF.

    Attributes:
        name:        Competition title, e.g. "Puiatu CUP 2025".
        organiser:   Organising club(s), e.g. "Vana-Võidu Vibuklubi/Viljandi SK".
        event_code:  World Archery event identifier, e.g. "25VV03".
        venue:       Venue name, e.g. "Puiatu Vibukeskus".
        date_start:  First day of the competition.
        date_end:    Last day of the competition (used in CSV Date column).
    """

    name: str
    organiser: str
    event_code: str
    venue: str
    date_start: date
    date_end: date


@dataclass
class SectionContext:
    """
    Metadata for one category section within the competition PDF.

    A section corresponds to a single bow-type / age-class / gender combination,
    e.g. "Recurve / Adult / Men".

    Attributes:
        bow_type:     Canonical bow type string: "Recurve" | "Compound" |
                      "Barebow" | "Longbow".
        age_class:    Canonical age class: "Adult" | "U21" | "U18" | "U15" |
                      "U13" | "U10" | "+50".
        gender:       "Men" | "Women".
        arrow_count:  Total arrows in the round: 72 | 144 | 216 | 288.
        distances:    Ordered list of distance strings, one per end, e.g.
                      ["70m", "70m", "70m", "70m"] or ["40m", "40m", "30m", "30m"].
        half_labels:  Distance label for each half-subtotal row, e.g.
                      ["2x70m", "2x70m"] or ["2x40m", "2x30m"].
                      Empty list for 72-arrow (2-end) rounds.
        total_label:  Distance label for the grand-total row, e.g.
                      "4x70m" or "2x40m+2x30m".
    """

    bow_type: str
    age_class: str
    gender: str
    arrow_count: int
    distances: list[str]
    half_labels: list[str]
    total_label: str


@dataclass
class AthleteRecord:
    """
    All data extracted for a single athlete from one section.

    Attributes:
        position:     Finishing position (1-based integer).
        target_code:  Session/target assignment code, e.g. "2-001A".
                      Retained for debugging; never written to CSV.
        firstname:    Athlete's given name, e.g. "Martin".
        lastname:     Athlete's family name (originally ALL-CAPS in PDF),
                      e.g. "Rist".
        class_code:   Raw Ianseo class code, e.g. "M", "U18W", "50M", "HM".
        club_code:    Four-character club abbreviation if present, e.g. "VVVK".
                      None when only a full club name is available.
        club_name:    Full club name if present, e.g. "Tallinna Vibukool".
                      None when only a code is available.
        end_scores:   Individual end scores in order, e.g. [318, 293, 314, 313].
        half_totals:  Half-subtotal scores in order, e.g. [611, 627].
                      Empty list for 72-arrow rounds.
        grand_total:  Overall competition total, e.g. 1238.
        tens_plus_x:  Count of 10s and Xs (inner 10s), e.g. 26.
        x_count:      Count of Xs only, e.g. 10.
        section:      The SectionContext this athlete belongs to.
    """

    position: int
    target_code: str
    firstname: str
    lastname: str
    class_code: str
    club_code: str | None
    club_name: str | None
    end_scores: list[int]
    half_totals: list[int]
    grand_total: int
    tens_plus_x: int
    x_count: int
    section: SectionContext


@dataclass
class CSVRow:
    """
    A single row in the output CSV file.

    Each AthleteRecord expands into multiple CSVRows — one per individual
    end score, one per half-subtotal, and one grand total row.  All
    descriptor columns repeat unchanged across all rows for the same athlete.

    Attributes:
        date:        Competition end date formatted as DD.MM.YYYY.
        athlete:     Full name formatted as "Firstname Lastname" (title case).
        club:        Club identifier: "{code} {name}", "{code}", or "{name}".
        bow_type:    Canonical bow type, e.g. "Recurve".
        age_class:   Canonical age class, e.g. "Adult".
        gender:      "Men" | "Women".
        distance:    Distance label for this row, e.g. "70m", "2x70m", "4x70m".
        result:      Integer score for this distance label.
        competition: Competition name, identical for all rows in one file.
    """

    date: str
    athlete: str
    club: str
    bow_type: str
    age_class: str
    gender: str
    distance: str
    result: int
    competition: str

    # Column order used when writing CSV headers and rows.
    COLUMNS: ClassVar[list[str]] = [
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

    def as_row(self) -> list:
        """Return values in CSV column order."""
        return [
            self.date,
            self.athlete,
            self.club,
            self.bow_type,
            self.age_class,
            self.gender,
            self.distance,
            self.result,
            self.competition,
        ]
