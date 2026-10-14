"""Drawing shared by the grid, the side panel's label buttons and the
Preferences previews: label chips, emblems, hatching, text, and the
theme-dependent neutral colours."""

from __future__ import annotations

import math
import warnings

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gtk, Pango, PangoCairo  # noqa: E402

from .. import style  # noqa: E402
from ..labels import CellLabel  # noqa: E402


class Palette:
    """Neutral colours from the current libadwaita theme (light or dark,
    high contrast, accent colour), as (r, g, b, a)."""

    def __init__(self, widget: Gtk.Widget):
        dark = Adw.StyleManager.get_default().get_dark()
        self.dark = dark
        fg = widget.get_color()
        self.fg = (fg.red, fg.green, fg.blue, 1.0)
        self.view_bg = self._lookup(widget, "view_bg_color", (0.118,) * 3 if dark else (1.0,) * 3)
        self.pane_bg = self._lookup(widget, "window_bg_color",
                                    (0.141,) * 3 if dark else (0.98,) * 3)
        self.accent = self._accent(widget)

    @staticmethod
    def _lookup(widget, name, fallback):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ok, c = widget.get_style_context().lookup_color(name)
            if ok:
                return (c.red, c.green, c.blue, 1.0)
        except Exception:  # noqa: BLE001 - lookup_color may disappear in GTK 5
            pass
        return (*fallback, 1.0)

    def _accent(self, widget):
        sm = Adw.StyleManager.get_default()
        if hasattr(sm, "get_accent_color_rgba"):        # libadwaita 1.6+
            c = sm.get_accent_color_rgba()
            return (c.red, c.green, c.blue, 1.0)
        return self._lookup(widget, "accent_bg_color", (0.208, 0.518, 0.894))

    def text(self, alpha=1.0):
        """The foreground, at ``alpha`` (0.55 secondary, 0.35 tertiary)."""
        return (*self.fg[:3], alpha)

    def line(self, strong=False):
        return (*self.fg[:3], 0.22 if strong else 0.09)

    def tint(self, alpha):
        return (*self.fg[:3], alpha)

    @property
    def weekend(self):
        return self.tint(0.05 if self.dark else 0.04)


def rgba(cr, c, alpha: float | None = None) -> None:
    if len(c) == 3:
        cr.set_source_rgba(c[0], c[1], c[2], 1.0 if alpha is None else alpha)
    else:
        cr.set_source_rgba(c[0], c[1], c[2], c[3] if alpha is None else c[3] * alpha)


def rect(cr, x, y, w, h, c) -> None:
    rgba(cr, c)
    cr.rectangle(x, y, w, h)
    cr.fill()


def rounded(cr, x, y, w, h, r) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


# --- text -----------------------------------------------------------------

class Fonts:
    """The grid's fonts, sized from the desktop's interface font, and a
    cache of text widths."""

    def __init__(self, widget: Gtk.Widget):
        settings = Gtk.Settings.get_default()
        name = settings.props.gtk_font_name if settings else "Sans 11"
        base = Pango.FontDescription.from_string(name or "Sans 11")
        pt = base.get_size() / Pango.SCALE if base.get_size() else 11.0
        if base.get_size_is_absolute():
            pt = pt * 72 / 96
        self.scale = max(0.75, pt / 11.0)

        def make(rel, weight=Pango.Weight.NORMAL, italic=False, family=None):
            f = base.copy()
            if family:
                f.set_family(family)
            f.set_size(int(round(pt * rel * Pango.SCALE)))
            f.set_weight(weight)
            f.set_style(Pango.Style.ITALIC if italic else Pango.Style.NORMAL)
            return f

        self.row = make(0.91)
        self.row_italic = make(0.91, italic=True)
        self.secondary = make(0.82)
        self.small = make(0.75)
        self.small_bold = make(0.75, Pango.Weight.BOLD)
        self.label = make(0.80, Pango.Weight.BOLD)
        self.label_tight = make(0.68, Pango.Weight.BOLD)
        self.header = make(0.80)
        self.header_bold = make(0.80, Pango.Weight.BOLD)
        self.month = make(0.86, Pango.Weight.BOLD)
        self.programme = make(0.91, Pango.Weight.BOLD)
        self.total = make(0.80, Pango.Weight.BOLD)
        self.italic = make(0.78, italic=True)
        self.code = make(0.80, Pango.Weight.MEDIUM, family="Monospace")
        self._tnum = Pango.AttrList()
        try:
            self._tnum.insert(Pango.attr_font_features_new("tnum=1"))
        except (AttributeError, TypeError):
            pass
        self._widths: dict = {}
        self._layout = None

    def layout(self, cr):
        lay = PangoCairo.create_layout(cr)
        return lay

    def width(self, cr, text: str, font) -> float:
        key = (text, font.to_string())
        w = self._widths.get(key)
        if w is None:
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(font)
            lay.set_text(text, -1)
            w = lay.get_pixel_size()[0]
            if len(self._widths) > 4000:
                self._widths.clear()
            self._widths[key] = w
        return w

    def draw(self, cr, text: str, x, y, w, h, font, colour, align="left", numeric=False):
        """One line of ``text`` in the box, vertically centred, ellipsised
        if it does not fit."""
        if not text or w <= 2:
            return
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font)
        if numeric:
            lay.set_attributes(self._tnum)
        lay.set_text(text, -1)
        lay.set_width(int(w * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        lay.set_single_paragraph_mode(True)
        lay.set_alignment({"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
                           "right": Pango.Alignment.RIGHT}[align])
        th = lay.get_pixel_size()[1]
        rgba(cr, colour)
        cr.move_to(x, y + (h - th) / 2)
        PangoCairo.show_layout(cr, lay)

    def centred(self, cr, text, x, y, w, h, font, colour, numeric=True):
        self.draw(cr, text, x - 20, y, w + 40, h, font, colour, "center", numeric)


# --- labels, emblems, hatching --------------------------------------------

def draw_emblem(cr, label: CellLabel, cx: float, cy: float, radius: float, alpha=1.0) -> None:
    """A white symbol on a coloured circle: ! (due), tick, cross, i."""
    colour = style.EMBLEM_COLOURS.get(label)
    if colour is None:
        return
    rgba(cr, colour, alpha)
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, alpha)
    r = radius
    lw = max(1.4, r * 0.24)
    cr.set_line_width(lw)
    cr.set_line_cap(1)  # round
    cr.set_line_join(1)
    if label is CellLabel.DUE:
        cr.move_to(cx, cy - r * 0.52)
        cr.line_to(cx, cy + r * 0.12)
        cr.stroke()
        cr.arc(cx, cy + r * 0.48, lw * 0.62, 0, 2 * math.pi)
        cr.fill()
    elif label is CellLabel.INFO:
        cr.arc(cx, cy - r * 0.48, lw * 0.62, 0, 2 * math.pi)
        cr.fill()
        cr.move_to(cx, cy - r * 0.12)
        cr.line_to(cx, cy + r * 0.52)
        cr.stroke()
    elif label is CellLabel.TICK:
        cr.move_to(cx - r * 0.45, cy + r * 0.02)
        cr.line_to(cx - r * 0.12, cy + r * 0.36)
        cr.line_to(cx + r * 0.48, cy - r * 0.34)
        cr.stroke()
    elif label is CellLabel.CROSS:
        k = r * 0.36
        cr.move_to(cx - k, cy - k)
        cr.line_to(cx + k, cy + k)
        cr.move_to(cx + k, cy - k)
        cr.line_to(cx - k, cy + k)
        cr.stroke()
    cr.set_line_cap(0)


def draw_label(cr, fonts: Fonts, palette: Palette, label: CellLabel, x, y, w, h,
               dimmed=False, radius=3.0, inset=(1.5, 2.0)) -> None:
    """A label as drawn in a cell: a coloured chip with its text, a dashed
    outline for planned work, or an emblem."""
    if label.is_emblem:
        side = max(8.0, min(w, h) - 5)
        draw_emblem(cr, label, x + w / 2, y + h / 2, side * 0.42, 0.45 if dimmed else 1.0)
        return
    cx, cy, cw, ch = x + inset[0], y + inset[1], w - 2 * inset[0], h - 2 * inset[1]
    fill = style.fill(label)
    if fill is not None:
        rounded(cr, cx, cy, cw, ch, radius)
        rgba(cr, fill, 0.45 if dimmed else 1.0)
        cr.fill()
    elif label is CellLabel.PLANNED:
        rounded(cr, cx + 0.5, cy + 0.5, cw - 1, ch - 1, radius)
        cr.set_line_width(1)
        cr.set_dash([3, 2])
        rgba(cr, style.PLANNED_STROKE)
        cr.stroke()
        cr.set_dash([])
    tc = style.text_on(label)
    colour = palette.text(0.6) if tc is None else (*tc, 1.0)
    if dimmed:
        colour = (*colour[:3], colour[3] * 0.6)
    font = fonts.label_tight if (cw < 26 and len(label.text) > 2) else fonts.label
    fonts.centred(cr, label.text, cx, cy, cw, ch, font, colour, numeric=False)


def hatch(cr, x, y, w, h, colour, step=6.0) -> None:
    """Diagonal hatching anchored to the step, so neighbouring spans line up."""
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    rgba(cr, colour)
    cr.set_line_width(1)
    start = math.floor((x - h) / step) * step - step
    xx = start
    while xx < x + w:
        cr.move_to(xx, y + h)
        cr.line_to(xx + h, y)
        xx += step
    cr.stroke()
    cr.restore()


def note_marker(cr, x, y, w, size=7.0) -> None:
    """The red corner of a cell with a note, as in a spreadsheet."""
    rgba(cr, style.NOTE_MARKER)
    cr.move_to(x + w - size, y)
    cr.line_to(x + w, y)
    cr.line_to(x + w, y + size)
    cr.close_path()
    cr.fill()


class LabelChip(Gtk.DrawingArea):
    """A label drawn exactly as in the grid, for buttons and previews."""

    def __init__(self, label: CellLabel | None, width=34, height=22):
        super().__init__()
        self.label = label
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, w, h):
        if self.label is None:
            return
        draw_label(cr, Fonts(self), Palette(self), self.label, 0, 0, w, h, inset=(0, 0))
