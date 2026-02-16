"""
Lookup tables and helper functions for the archery_parser pipeline.

Contains all mappings between Ianseo's Estonian/coded values and the
canonical English strings used in CSV output.
"""


# ---------------------------------------------------------------------------
# 7.1  Bow Type
# ---------------------------------------------------------------------------

BOW_TYPE: dict[str, str] = {
    # Estonian section titles
    "Sportvibu": "Recurve",
    "Plokkvibu": "Compound",
    "Vaistuvibu": "Barebow",
    "Pikkvibu": "Longbow",
    "Harrastajad": "Recurve",
    # English section titles (used when Ianseo language is set to English)
    "Recurve": "Recurve",
    "Compound": "Compound",
    "Barebow": "Barebow",
    "Longbow": "Longbow",
}
"""Maps the first word of an Ianseo section title (Estonian) to the canonical
CSV bow-type string."""


# ---------------------------------------------------------------------------
# 7.2  Age Class
# ---------------------------------------------------------------------------

AGE_CLASS: dict[str, str] = {
    "M": "Adult",
    "W": "Adult",
    "U21M": "U21",
    "U21W": "U21",
    "U18M": "U18",
    "U18W": "U18",
    "U15M": "U15",
    "U15W": "U15",
    "U13M": "U13",
    "U13W": "U13",
    "U10M": "U10",
    "U10W": "U10",
    "50M": "+50",
    "50W": "+50",
    "30M": "30",
    "30W": "30",
    "HM": "Adult",
    "HW": "Adult",
}
"""Maps Ianseo class codes to the canonical CSV age-class string."""


# ---------------------------------------------------------------------------
# 7.3  Gender
# ---------------------------------------------------------------------------

GENDER: dict[str, str] = {
    "M": "Men",
    "W": "Women",
    "U21M": "Men",
    "U21W": "Women",
    "U18M": "Men",
    "U18W": "Women",
    "U15M": "Men",
    "U15W": "Women",
    "U13M": "Men",
    "U13W": "Women",
    "U10M": "Men",
    "U10W": "Women",
    "50M": "Men",
    "50W": "Women",
    "30M": "Men",
    "30W": "Women",
    "HM": "Men",
    "HW": "Women",
}
"""Maps Ianseo class codes to "Men" or "Women"."""


# ---------------------------------------------------------------------------
# 7.4  Distance label builder
# ---------------------------------------------------------------------------

def build_distance_context(distances: list[str]) -> dict:
    """
    Derive half_labels and total_label from an ordered list of per-end
    distance strings.

    The distances list contains one entry per end (i.e. two entries per
    printed score line).  This function groups them into consecutive pairs
    and builds the appropriate label strings.

    Args:
        distances: Ordered list of distance strings, one per end.
                   Length must be even (2, 4, 6, or 8), OR a single distance
                   (for single-distance 60-arrow rounds).
                   Example: ["70m", "70m", "70m", "70m"]
                   Example: ["40m", "40m", "30m", "30m"]
                   Example: ["70m"] → treated as ["70m", "70m"]

    Returns:
        A dict with keys:
            "half_labels" : list[str]  — one label per pair of ends.
                            Empty list when len(distances) == 2 (72-arrow
                            half-round; no intermediate subtotal row needed).
            "total_label" : str        — label for the grand-total row.

    Examples:
        >>> build_distance_context(["70m", "70m", "70m", "70m"])
        {'half_labels': ['2x70m', '2x70m'], 'total_label': '4x70m'}

        >>> build_distance_context(["40m", "40m", "30m", "30m"])
        {'half_labels': ['2x40m', '2x30m'], 'total_label': '2x40m+2x30m'}

        >>> build_distance_context(["60m", "60m"])
        {'half_labels': [], 'total_label': '2x60m'}

        >>> build_distance_context(["70m"])
        {'half_labels': [], 'total_label': '70m'}
    """
    # Handle single-distance format (e.g., 60 arrows at 70m)
    if len(distances) == 1:
        # Single distance: duplicate to make it a pair for processing
        distances = distances * 2

    if len(distances) % 2 != 0:
        raise ValueError(
            f"distances list must have an even length, got {len(distances)}: {distances}"
        )

    n = len(distances)

    # Build one label per consecutive pair of ends.
    pair_labels: list[str] = []
    for i in range(0, n, 2):
        d1, d2 = distances[i], distances[i + 1]
        if d1 == d2:
            pair_labels.append(f"2x{d1}")
        else:
            # Mixed-distance pair (shouldn't happen within a single half, but
            # handle gracefully).
            pair_labels.append(f"{d1}+{d2}")

    # Grand-total label: count occurrences of each distance in order of first
    # appearance, then join segments with "+".
    # e.g. ["70m"x4]        → "4x70m"
    # e.g. ["40m"x2,"30m"x2] → "2x40m+2x30m"
    seen: list[str] = []
    for d in distances:
        if d not in seen:
            seen.append(d)

    total_parts: list[str] = []
    for dist in seen:
        count = distances.count(dist)
        total_parts.append(f"{count}x{dist}")

    total_label = "+".join(total_parts)

    # For 72-arrow (2-end) rounds there is no intermediate half-subtotal row.
    half_labels = pair_labels if n > 2 else []

    return {
        "half_labels": half_labels,
        "total_label": total_label,
    }
