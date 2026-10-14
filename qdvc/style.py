"""The grid's colours (docs/DESIGN.md §4), as (r, g, b) floats in 0…1.

Work sizes are a single-hue blue heat map, from baby blue (XS) to navy (XL);
totals are a salmon-to-red heat map; meetings are bright green. These are
the same colours as the macOS edition, so the two look alike. Neutral
colours (backgrounds, text, lines) come from the GTK theme instead.
"""

from __future__ import annotations

from .labels import CellLabel

RGB = tuple[float, float, float]


def hex_rgb(h: int) -> RGB:
    return (((h >> 16) & 0xFF) / 255, ((h >> 8) & 0xFF) / 255, (h & 0xFF) / 255)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Linear blend towards ``b`` (t = 0 is ``a``, 1 is ``b``)."""
    t = max(0.0, min(1.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))  # type: ignore[return-value]


SIZE_FILLS = [hex_rgb(0xCFE8FB), hex_rgb(0x9CCBF2), hex_rgb(0x5A9BDB),
              hex_rgb(0x2B5EA8), hex_rgb(0x10275C)]
MEETING_FILL = hex_rgb(0x2EDB4F)
PLANNED_STROKE = hex_rgb(0x5A9BDB)
NOTE_MARKER = hex_rgb(0xE5484D)
TODAY_YELLOW = hex_rgb(0xFFD60A)
TOTAL_LOW = hex_rgb(0xFFE3D8)
TOTAL_HIGH = hex_rgb(0xC62F2F)
DARK_TEXT = hex_rgb(0x111111)
TOTAL_DARK_TEXT = hex_rgb(0x3A1A14)
TODAY_TEXT = hex_rgb(0x1A1A1A)
WHITE: RGB = (1.0, 1.0, 1.0)

EMBLEM_COLOURS = {
    CellLabel.DUE: hex_rgb(0xFF9500),    # amber
    CellLabel.TICK: hex_rgb(0x28B44A),   # green
    CellLabel.CROSS: hex_rgb(0xE5372B),  # red
    CellLabel.INFO: hex_rgb(0x0A7AFF),   # blue
}


def fill(label: CellLabel) -> RGB | None:
    """The chip colour of a label, or None (planned work and emblems)."""
    i = label.size_index
    if i is not None:
        return SIZE_FILLS[i]
    return MEETING_FILL if label is CellLabel.MEETING else None


def text_on(label: CellLabel) -> RGB | None:
    """The text colour on a label's chip; None means "the theme's dimmed
    foreground" (planned work, which has no fill)."""
    if label in (CellLabel.L, CellLabel.XL):
        return WHITE
    if label is CellLabel.PLANNED:
        return None
    return DARK_TEXT


def total_fill(level: float) -> RGB | None:
    """The fill of a total at ``level`` (0…1), or None for zero. Even a
    small total is visibly tinted."""
    if level <= 0:
        return None
    return mix(TOTAL_LOW, TOTAL_HIGH, 0.12 + 0.88 * level)


def total_text(level: float) -> RGB:
    return WHITE if level > 0.55 else TOTAL_DARK_TEXT
