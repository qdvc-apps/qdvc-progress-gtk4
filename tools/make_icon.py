#!/usr/bin/env python3
"""Generate the app icons in the GNOME (Adwaita) style.

    python3 tools/make_icon.py            # writes data/icons/hicolor/...
    python3 tools/make_icon.py --preview  # also build/icon-preview.png (needs rsvg-convert)

The design follows the macOS edition's icon in GNOME's idiom: a flat white
spreadsheet card with a soft bottom edge (the HIG's "thickness" cue), a
header row with today's column in yellow, work cells in the app's blue heat
map with one green meeting, a row of salmon-to-red totals, and a navy badge
with a white rising arrow. 128 × 128 canvas, per the GNOME app icon grid.

Writes:
  data/icons/hicolor/scalable/apps/qdvc.Progress.svg
  data/icons/hicolor/symbolic/apps/qdvc.Progress-symbolic.svg
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ID = "qdvc.Progress"

SIZES = ["#CFE8FB", "#9CCBF2", "#5A9BDB", "#2B5EA8", "#10275C"]
MEETING = "#2EDB4F"
TODAY = "#FFD60A"
TOTALS = ["#FCD2C3", "#F29C85", "#E06A55", "#C62F2F"]
NAVY, NAVY_DARK = "#2B5EA8", "#10275C"

# The cells: rows top to bottom, five day columns; None is an empty cell.
CELLS = [
    [3, 2, None, 1, 0],
    [None, "mtg", 2, 3, None],
    [1, None, 4, 2, 1],
]
TOTAL_ROW = [2, 1, 3, 3, 1]


def app_icon() -> str:
    x0, y0, w, h, r = 10, 14, 108, 96, 12
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">',
        "<defs>",
        '<linearGradient id="side" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#c0bfbc"/><stop offset="1" stop-color="#9a9996"/>'
        "</linearGradient>",
        '<linearGradient id="badge" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#4a7fd0"/><stop offset="1" stop-color="{NAVY}"/>'
        "</linearGradient>",
        "</defs>",
        # The card's bottom edge, then the card.
        f'<rect x="{x0}" y="{y0 + 6}" width="{w}" height="{h}" rx="{r}" fill="url(#side)"/>',
        f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="{r}" fill="#ffffff"/>',
        # Header row.
        f'<path d="M{x0} {y0 + r} a{r} {r} 0 0 1 {r} -{r} h{w - 2 * r} a{r} {r} 0 0 1 {r} {r} '
        f'v8 h-{w} z" fill="#f0eff0"/>',
    ]
    cols = 5
    left = x0 + 24          # the project column
    cw = (w - 24 - 8) / cols
    today_col = 2
    tx = left + today_col * cw
    out.append(f'<rect x="{tx + 1:.1f}" y="{y0 + 3}" width="{cw - 2:.1f}" height="{h - 6}" '
               f'rx="3" fill="{TODAY}" fill-opacity="0.28"/>')
    out.append(f'<rect x="{tx + 1:.1f}" y="{y0 + 3}" width="{cw - 2:.1f}" height="14" rx="3" '
               f'fill="{TODAY}"/>')
    for c in range(cols):
        if c != today_col:
            out.append(f'<rect x="{left + c * cw + cw / 2 - 4:.1f}" y="{y0 + 8}" width="8" '
                       f'height="3" rx="1.5" fill="#c0bfbc"/>')
    # Project titles.
    row_h = 15
    top = y0 + 22
    for i in range(len(CELLS)):
        out.append(f'<rect x="{x0 + 6}" y="{top + i * row_h + 5}" width="14" height="4" rx="2" '
                   'fill="#c0bfbc"/>')
    # Work cells.
    for i, row in enumerate(CELLS):
        for c, v in enumerate(row):
            if v is None:
                continue
            fill = MEETING if v == "mtg" else SIZES[v]
            out.append(f'<rect x="{left + c * cw + 1.5:.1f}" y="{top + i * row_h + 1.5}" '
                       f'width="{cw - 3:.1f}" height="{row_h - 3}" rx="3" fill="{fill}"/>')
    # Totals.
    ty = top + len(CELLS) * row_h + 4
    out.append(f'<rect x="{x0 + 4}" y="{ty - 2.5}" width="{w - 8}" height="1" fill="#deddda"/>')
    for c, v in enumerate(TOTAL_ROW):
        out.append(f'<rect x="{left + c * cw + 1.5:.1f}" y="{ty + 1}" width="{cw - 3:.1f}" '
                   f'height="{row_h - 3}" rx="3" fill="{TOTALS[v]}"/>')
    # Badge with a rising arrow.
    bx, by, br = 98, 96, 19
    out += [
        f'<circle cx="{bx}" cy="{by + 3}" r="{br}" fill="{NAVY_DARK}"/>',
        f'<circle cx="{bx}" cy="{by}" r="{br}" fill="url(#badge)"/>',
        f'<path d="M{bx - 12} {by + 8} L{bx - 3} {by - 1} L{bx + 2} {by + 4} L{bx + 11} {by - 6}" '
        'fill="none" stroke="#ffffff" stroke-width="4.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
        f'<path d="M{bx + 3} {by - 8} L{bx + 12} {by - 8} L{bx + 12} {by + 1} z" fill="#ffffff" '
        'stroke="#ffffff" stroke-width="2" stroke-linejoin="round"/>',
        "</svg>",
    ]
    return "\n".join(out) + "\n"


def symbolic_icon() -> str:
    """16 × 16, one colour (GNOME recolours symbolic icons)."""
    return """<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
<path fill="#2e3436" d="M3 1C1.9 1 1 1.9 1 3v10c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-2-2-2zm0 2h10v2H3zm0 4h3v2H3zm4 0h2v2H7zm3 0h3v2h-3zM3 11h3v2H3zm4 0h2v2H7zm3 0h3v2h-3z"/>
</svg>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()
    base = os.path.join(ROOT, "data", "icons", "hicolor")
    paths = {
        os.path.join(base, "scalable", "apps", f"{APP_ID}.svg"): app_icon(),
        os.path.join(base, "symbolic", "apps", f"{APP_ID}-symbolic.svg"): symbolic_icon(),
    }
    for path, svg in paths.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", os.path.relpath(path, ROOT))
    if args.preview:
        os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
        out = os.path.join(ROOT, "build", "icon-preview.png")
        try:
            subprocess.run(["rsvg-convert", "-w", "256", "-h", "256", "-o", out,
                            list(paths)[0]], check=True)
            print("wrote", os.path.relpath(out, ROOT))
        except (OSError, subprocess.CalledProcessError) as e:
            print("preview needs rsvg-convert:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
