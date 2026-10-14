"""The grid: one row per project, one column per day (docs/DESIGN.md §3).

One custom-drawn widget, placed in a ``Gtk.ScrolledWindow`` as a
``Gtk.Scrollable``, so it gets GNOME's overlay scrollbars and kinetic
touchpad scrolling. The date header, the project columns and the totals are
drawn frozen around the scrolling body, as in a spreadsheet:

    ┌ corner ─────────┬ header (scrolls horizontally) ─┐
    ├ left columns ───┼ body (scrolls both ways) ──────┤
    ├ footer corner ──┼ footer: totals ────────────────┤

Only the visible rows and days are drawn, so long histories stay fast. The
range of days grows when you scroll near either end.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .. import style  # noqa: E402
from ..dates import add_days, is_weekend, monday  # noqa: E402
from ..labels import SIZES, SPECIALS, CellLabel, PasteMode, label_token  # noqa: E402
from ..log import heat_level  # noqa: E402
from ..models import programme_title  # noqa: E402
from ..session import CellRef, GridSelection, Session  # noqa: E402
from ..ui_prefs import (OPTIONAL_COLUMNS, WEEKDAY_LETTERS, LeftColumn, TotalsScope,  # noqa: E402
                        long_day, month_title, plural, range_text, short_day)
from .gtk4_paint import Fonts, Palette, draw_label, hatch, note_marker, rect, rgba, rounded  # noqa: E402

HOVER_DELAY_MS = 500
HIDE_DELAY_MS = 300


class Metrics:
    """The grid's geometry. Day columns and rows are measured in the body's
    own coordinates: day 0 at x = 0, the first row at y = 0."""

    def __init__(self, s: Session, scale: float):
        def px(v):
            return int(round(v * scale))
        self.header_rows = [px(24), px(21), px(19), px(19)]   # month, week, day, weekday
        self.footer_rows = [px(25), px(25)]                    # daily totals, week & weekend
        self.subtotal_h = px(20)
        self.row_h = px(26)
        self.programme_h = px(30)
        self.cell_w = max(16, px(s.cell_width))
        self.day_count = s.day_count
        self.columns: list[tuple[LeftColumn, int, int]] = []
        x = 0
        for c in s.visible_columns:
            w = px(s.column_width(c))
            self.columns.append((c, x, w))
            x += w
        self.left_w = x
        tops = [0]
        for r in s.rows:
            tops.append(tops[-1] + (self.programme_h if r.is_programme else self.row_h))
        self.row_tops = tops
        self.footer_programmes = s.footer_programmes

    @property
    def header_h(self) -> int:
        return sum(self.header_rows)

    def header_top(self, i: int) -> int:
        return sum(self.header_rows[:i])

    @property
    def totals_top(self) -> int:
        return len(self.footer_programmes) * self.subtotal_h

    @property
    def footer_h(self) -> int:
        return self.totals_top + sum(self.footer_rows)

    @property
    def content_w(self) -> int:
        return self.day_count * self.cell_w

    @property
    def content_h(self) -> int:
        return self.row_tops[-1]

    @property
    def row_count(self) -> int:
        return len(self.row_tops) - 1

    def day_x(self, d: int) -> int:
        return d * self.cell_w

    def row_at(self, y: float) -> int | None:
        if self.row_count == 0 or y < 0 or y >= self.content_h:
            return None
        lo, hi = 0, self.row_count - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.row_tops[mid] <= y:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def day_at(self, x: float) -> int | None:
        if x < 0:
            return None
        d = int(x // self.cell_w)
        return d if d < self.day_count else None

    def days_in(self, x0: float, x1: float) -> range:
        lo = max(0, int(math.floor(x0 / self.cell_w)))
        hi = min(self.day_count, int(math.ceil(x1 / self.cell_w)))
        return range(lo, hi) if lo < hi else range(0)

    def rows_in(self, y0: float, y1: float) -> range:
        if self.row_count == 0:
            return range(0)
        lo = self.row_at(max(0, y0))
        if lo is None:
            lo = 0 if y0 < 0 else self.row_count
        hi = self.row_at(min(y1, self.content_h - 0.5))
        hi = (self.row_count - 1 if y1 > 0 else -1) if hi is None else hi
        return range(lo, hi + 1) if lo <= hi else range(0)

    def column_divider_near(self, x: float) -> LeftColumn | None:
        for c, cx, w in self.columns:
            if abs(cx + w - x) <= 4:
                return c
        return None

    def column_at(self, x: float) -> LeftColumn | None:
        for c, cx, w in self.columns:
            if cx <= x < cx + w:
                return c
        return None


def _item(label: str, action: str, target: str | None = None) -> Gio.MenuItem:
    it = Gio.MenuItem.new(label, None)
    if target is None:
        it.set_detailed_action(action)
    else:
        it.set_action_and_target_value(action, GLib.Variant("s", target))
    return it


def _section(*items) -> Gio.Menu:
    m = Gio.Menu()
    for it in items:
        if it is not None:
            m.append_item(it)
    return m


class NoteCallout:
    """The popover beside a cell with a note (docs/DESIGN.md §5).

    Clicking a cell with a note shows it at once and keeps it ("pinned")
    until another cell is clicked, a key is pressed, the grid scrolls or
    loses the focus. Hovering shows it after half a second; it goes 0.3 s
    after the pointer leaves the cell."""

    def __init__(self, grid: "ProgressGrid"):
        self.grid = grid
        self.ref: CellRef | None = None
        self.pinned = False
        self.content = None
        self._popover: Gtk.Popover | None = None
        self._show_id = 0
        self._hide_id = 0

    @property
    def shown(self) -> bool:
        return self._popover is not None and self._popover.get_visible()

    def _cancel(self):
        for attr in ("_show_id", "_hide_id"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, 0)

    def show(self, content, ref: CellRef, area: Gdk.Rectangle, pinned: bool):
        self._cancel()
        if self.shown and self.ref == ref and self.content == content:
            self.pinned = self.pinned or pinned
            return
        self.close()
        title, subtitle, note = content
        pop = Gtk.Popover()
        pop.set_autohide(False)
        pop.set_can_focus(False)
        pop.set_position(Gtk.PositionType.RIGHT)
        pop.add_css_class("note-callout")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        t = Gtk.Label(label=title, xalign=0, ellipsize=3, max_width_chars=36)
        t.add_css_class("heading")
        sub = Gtk.Label(label=subtitle, xalign=0)
        sub.add_css_class("caption")
        sub.add_css_class("dim-label")
        body = Gtk.Label(label=note, xalign=0, wrap=True, max_width_chars=40, width_chars=24,
                         selectable=False)
        body.set_wrap_mode(2)  # Pango.WrapMode.WORD_CHAR
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                propagate_natural_height=True, max_content_height=280)
        sw.set_child(body)
        box.append(t)
        box.append(sub)
        box.append(Gtk.Separator())
        box.append(sw)
        pop.set_child(box)
        pop.set_parent(self.grid)
        pop.set_pointing_to(area)
        pop.popup()
        self._popover = pop
        self.ref, self.content, self.pinned = ref, content, pinned
        self.grid.grab_focus()

    def hover(self, content, ref: CellRef, area: Gdk.Rectangle):
        if self._hide_id:
            GLib.source_remove(self._hide_id)
            self._hide_id = 0
        if self.shown and self.ref == ref:
            return
        if self._show_id:
            GLib.source_remove(self._show_id)

        def fire():
            self._show_id = 0
            if self.grid.get_mapped():
                self.show(content, ref, area, False)
            return False
        self._show_id = GLib.timeout_add(HOVER_DELAY_MS, fire)

    def hover_ended(self):
        if self._show_id:
            GLib.source_remove(self._show_id)
            self._show_id = 0
        if not self.shown or self.pinned or self._hide_id:
            return

        def fire():
            self._hide_id = 0
            if not self.pinned:
                self.close()
            return False
        self._hide_id = GLib.timeout_add(HIDE_DELAY_MS, fire)

    def close(self):
        self._cancel()
        pop = self._popover
        self._popover = None
        self.ref = self.content = None
        self.pinned = False
        if pop is not None:
            pop.popdown()
            pop.unparent()


class ProgressGrid(Gtk.DrawingArea, Gtk.Scrollable):
    __gtype_name__ = "QdvcProgressGrid"

    hadjustment = GObject.Property(type=Gtk.Adjustment)
    vadjustment = GObject.Property(type=Gtk.Adjustment)
    hscroll_policy = GObject.Property(type=Gtk.ScrollablePolicy,
                                      default=Gtk.ScrollablePolicy.MINIMUM)
    vscroll_policy = GObject.Property(type=Gtk.ScrollablePolicy,
                                      default=Gtk.ScrollablePolicy.MINIMUM)

    def __init__(self, session: Session):
        super().__init__()
        self.s = session
        self.set_focusable(True)
        self.set_can_focus(True)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_has_tooltip(True)
        self.set_draw_func(self._draw)
        self.fonts = Fonts(self)
        self.m = Metrics(session, self.fonts.scale)
        self._last_start = session.range_start
        self._last_cell_w = self.m.cell_w
        self._adjusting = False
        self._pending_scroll = None
        self._hover: CellRef | None = None
        self._drag = None          # ("select",) or ("resize", column, start_x, start_w)
        self._drag_origin = (0.0, 0.0)
        self._drag_point = None
        self._autoscroll_id = 0
        self._menu: Gtk.PopoverMenu | None = None
        self.callout = NoteCallout(self)
        self._hsig = self._vsig = None
        self._px = 1.0           # one device pixel, in widget units

        self.connect("notify::hadjustment", self._on_adjustment_set, "h")
        self.connect("notify::vadjustment", self._on_adjustment_set, "v")
        self.connect("query-tooltip", self._on_query_tooltip)
        self.connect("unmap", lambda *_: self.callout.close())

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)
        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: self.queue_draw())
        focus.connect("leave", self._on_focus_leave)
        self.add_controller(focus)

        session.connect(self._on_session)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.connect("notify::gtk-font-name", self._on_font_changed)

    # ------------------------------------------------------------------
    # Geometry and scrolling
    # ------------------------------------------------------------------

    def _on_font_changed(self, *_):
        self.fonts = Fonts(self)
        self.reload()

    def _viewport(self):
        """(left width, top, body width, body height) in widget pixels."""
        w, h = self.get_width(), self.get_height()
        lw = min(self.m.left_w, max(140, int(w * 0.5)))
        top, bottom = self.m.header_h, self.m.footer_h
        return lw, top, max(0, w - lw), max(0, h - top - bottom)

    @property
    def ox(self) -> float:
        a = self.props.hadjustment
        return a.get_value() if a else 0.0

    @property
    def oy(self) -> float:
        a = self.props.vadjustment
        return a.get_value() if a else 0.0

    def _on_adjustment_set(self, _obj, _pspec, which):
        adj = self.props.hadjustment if which == "h" else self.props.vadjustment
        if adj is None:
            return
        adj.connect("value-changed", self._on_scrolled, which)
        self._configure()

    def do_size_allocate(self, width, height, baseline):
        try:
            Gtk.DrawingArea.do_size_allocate(self, width, height, baseline)
        except (TypeError, AttributeError):
            pass
        self._configure()
        if self._pending_scroll is not None:
            self.scroll_to_day(self._pending_scroll)

    def _configure(self):
        _, _, bw, bh = self._viewport()
        self._adjusting = True
        ha, va = self.props.hadjustment, self.props.vadjustment
        if ha is not None:
            upper = max(self.m.content_w, bw)
            ha.configure(min(ha.get_value(), max(0, upper - bw)), 0, upper, self.m.cell_w,
                         max(1, bw * 0.9), bw)
        if va is not None:
            upper = max(self.m.content_h, bh)
            va.configure(min(va.get_value(), max(0, upper - bh)), 0, upper, self.m.row_h,
                         max(1, bh * 0.9), bh)
        self._adjusting = False

    def _on_scrolled(self, adj, which):
        if self.callout.shown:
            self.callout.close()
        self.queue_draw()
        if self._adjusting or which != "h":
            return
        _, _, bw, _ = self._viewport()
        margin = 14 * self.m.cell_w
        v = adj.get_value()
        if v < margin and self.s.range_start.year > 1900:
            GLib.idle_add(self._grow, -1)
        elif v + bw > self.m.content_w - margin:
            GLib.idle_add(self._grow, 1)

    def _grow(self, direction):
        _, _, bw, _ = self._viewport()
        margin = 14 * self.m.cell_w
        v = self.ox
        if direction < 0 and v < margin:
            self.s.extend_earlier()
        elif direction > 0 and v + bw > self.m.content_w - margin:
            self.s.extend_later()
        return False

    def reload(self):
        """Recomputes the geometry, keeping the same day at the left edge
        (the range may have grown at the start, or the zoom changed)."""
        old_w = self._last_cell_w
        anchor = None
        if old_w > 0:
            anchor = self._last_start.toordinal() + self.ox / old_w
        self.m = Metrics(self.s, self.fonts.scale)
        self._last_start = self.s.range_start
        self._last_cell_w = self.m.cell_w
        self._configure()
        if anchor is not None and self.props.hadjustment is not None:
            x = (anchor - self.s.range_start.toordinal()) * self.m.cell_w
            if abs(x - self.ox) > 0.5:
                self._adjusting = True
                self.props.hadjustment.set_value(max(0, x))
                self._adjusting = False
        self._refresh_callout()
        self.queue_draw()

    def _on_session(self, event, payload):
        if event == "changed":
            self.reload()
        elif event == "scroll-to":
            self.scroll_to_day(payload)
        elif event == "focus-grid":
            self.grab_focus()

    def scroll_to_day(self, d):
        """Shows ``d`` with the week before it to its left."""
        _, _, bw, _ = self._viewport()
        if bw <= 0 or self.props.hadjustment is None:
            self._pending_scroll = d
            return
        self._pending_scroll = None
        x = self.m.day_x(self.s.day_index(d) - 7)
        a = self.props.hadjustment
        self._adjusting = True
        a.set_value(max(0, min(x, a.get_upper() - a.get_page_size())))
        self._adjusting = False
        self.queue_draw()

    def reveal_focus(self):
        """Scrolls the selected cell into view (after a keyboard move)."""
        f = self.s.focus_ref
        if f is None:
            return
        row = self.s.row_of(f.project)
        if row is None:
            return
        _, _, bw, bh = self._viewport()
        x0 = self.m.day_x(self.s.day_index(f.date))
        x1 = x0 + self.m.cell_w
        y0, y1 = self.m.row_tops[row], self.m.row_tops[row + 1]
        ha, va = self.props.hadjustment, self.props.vadjustment
        if ha is not None:
            if x0 - self.m.cell_w < self.ox:
                ha.set_value(max(0, x0 - self.m.cell_w))
            elif x1 + self.m.cell_w > self.ox + bw:
                ha.set_value(x1 + self.m.cell_w - bw)
        if va is not None:
            if y0 - 4 < self.oy:
                va.set_value(max(0, y0 - 4))
            elif y1 + 4 > self.oy + bh:
                va.set_value(y1 + 4 - bh)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self, _area, cr, width, height):
        s, m = self.s, self.m
        pal = Palette(self)
        lw, top, bw, bh = self._viewport()
        # Whole device pixels: with a fractional scroll offset every line
        # would be blended over two pixels at half strength.
        sf = max(1, self.get_scale_factor())
        self._px = 1.0 / sf
        ox, oy = round(self.ox * sf) / sf, round(self.oy * sf) / sf
        days = m.days_in(ox, ox + bw)
        rows = m.rows_in(oy, oy + bh)

        # Body.
        cr.save()
        cr.rectangle(lw, top, bw, bh)
        cr.clip()
        cr.translate(lw - ox, top - oy)
        self._draw_body(cr, pal, days, rows, ox, oy, bw, bh)
        cr.restore()

        # Header.
        cr.save()
        cr.rectangle(lw, 0, bw, top)
        cr.clip()
        cr.translate(lw, 0)
        self._draw_header(cr, pal, days, ox, bw)
        cr.restore()

        # Left columns.
        cr.save()
        cr.rectangle(0, top, lw, bh)
        cr.clip()
        cr.translate(0, top)
        self._draw_left(cr, pal, rows, oy, lw, bh)
        cr.restore()

        # Corner.
        cr.save()
        cr.rectangle(0, 0, lw, top)
        cr.clip()
        self._draw_corner(cr, pal, lw)
        cr.restore()

        # Footer and its corner.
        fy = top + bh
        cr.save()
        cr.rectangle(lw, fy, bw, height - fy)
        cr.clip()
        cr.translate(lw, fy)
        self._draw_footer(cr, pal, days, ox, bw, height - fy)
        cr.restore()
        cr.save()
        cr.rectangle(0, fy, lw, height - fy)
        cr.clip()
        cr.translate(0, fy)
        self._draw_footer_corner(cr, pal, lw, height - fy)
        cr.restore()

    def _working_week_lines(self, cr, pal, days, x_of, y, h):
        if not self.s.outline_working_week or h <= 0:
            return
        # 1.5 px, as the macOS edition's 1.5 pt, rounded to whole device
        # pixels and centred on the column boundary.
        px = self._px
        w = max(1, round(1.5 / px)) * px
        rgba(cr, pal.text(0.85))
        for d in range(days.start - 1, days.stop + 1):
            wd = self.s.date_at(d).isoweekday()
            if wd in (1, 5):
                edge = x_of(d) if wd == 1 else x_of(d + 1)
                cr.rectangle(round((edge - w / 2) / px) * px, y, w, h)
        cr.fill()

    def _draw_body(self, cr, pal, days, rows, ox, oy, bw, bh):
        s, m, f = self.s, self.m, self.fonts
        rect(cr, ox, oy, bw, bh, pal.view_bg)
        if not days:
            return
        y0, y1 = oy, oy + bh
        # Weekend and today columns.
        for d in days:
            date = s.date_at(d)
            if date == s.today:
                rect(cr, m.day_x(d), y0, m.cell_w, bh, (*style.TODAY_YELLOW, 0.16))
            elif is_weekend(date):
                rect(cr, m.day_x(d), y0, m.cell_w, bh, pal.weekend)

        first_day, last_day = s.date_at(days.start), s.date_at(days.stop - 1)
        for r in rows:
            row = s.rows[r]
            top, h = m.row_tops[r], m.row_tops[r + 1] - m.row_tops[r]
            if row.is_programme:
                rect(cr, m.day_x(days.start), top, m.day_x(days.stop) - m.day_x(days.start), h,
                     (*pal.pane_bg[:3], 0.9))
                if s.show_programme_subtotals:
                    for d in days:
                        t = s.programme_total(row.name, s.date_at(d))
                        if t:
                            f.centred(cr, str(t), m.day_x(d), top, m.cell_w, h, f.small,
                                      pal.text(0.55))
                continue
            p = s.project(row.key)
            if p is None:
                continue
            for period in p.inactive_periods:
                if period.range.end < first_day or period.range.start > last_day:
                    continue
                start, end = max(period.range.start, first_day), min(period.range.end, last_day)
                x0, x1 = m.day_x(s.day_index(start)), m.day_x(s.day_index(end) + 1)
                rect(cr, x0, top, x1 - x0, h, pal.tint(0.07))
                hatch(cr, x0, top, x1 - x0, h, pal.text(0.30))
                label = period.label.strip()
                if not label:
                    continue
                # One label per fortnight of the period, centred in it, so a
                # long period shows its label wherever it is scrolled to.
                total = period.range.day_count
                chunks = max(1, int(round(total / 14)))
                pstart = s.day_index(period.range.start)
                for c in range(chunks):
                    cx0 = m.day_x(pstart + c * total // chunks)
                    cx1 = m.day_x(pstart + (c + 1) * total // chunks)
                    if cx1 <= x0 or cx0 >= x1:
                        continue
                    width = min(f.width(cr, label, f.italic) + 14, cx1 - cx0 - 4)
                    if width <= 16:
                        continue
                    px0 = (cx0 + cx1 - width) / 2
                    rounded(cr, px0, top + 3, width, h - 6, 5)
                    rgba(cr, pal.view_bg, 0.9)
                    cr.fill()
                    f.draw(cr, label, px0 + 7, top, width - 14, h, f.italic, pal.text(0.6),
                           "center")
            dim = not p.is_active
            for d in days:
                c = s.log.get(p.key, s.date_at(d))
                if c.is_empty:
                    continue
                x = m.day_x(d)
                if c.label is not None:
                    draw_label(cr, f, pal, c.label, x, top, m.cell_w, h, dimmed=dim)
                if c.has_note:
                    note_marker(cr, x, top, m.cell_w, 7 * f.scale)

        # Grid lines.
        bottom = min(y1, m.content_h)
        for d in days:
            weekstart = s.date_at(d).isoweekday() == 1
            rect(cr, m.day_x(d), y0, 1 if weekstart else self._px, max(0, bottom - y0),
                 pal.line(weekstart))
        for r in rows:
            y = m.row_tops[r + 1]
            w = 1 if s.rows[r].is_programme else self._px
            rect(cr, ox, y - w, bw, w, pal.line(s.rows[r].is_programme))
        self._working_week_lines(cr, pal, days, m.day_x, y0, bottom - y0)
        self._draw_selection(cr, pal)

    def _draw_selection(self, cr, pal):
        s, m = self.s, self.m
        b = s.selection_bounds
        if b is None:
            return
        rows, days = b
        accent = pal.accent if self.has_focus() else pal.text(0.45)
        x0, x1 = m.day_x(days.start), m.day_x(days.stop)
        y0, y1 = m.row_tops[rows.start], m.row_tops[rows.stop]
        single = len(days) == 1 and len(rows) == 1
        if not single:
            rect(cr, x0, y0, x1 - x0, y1 - y0, (*accent[:3], 0.14))
        rgba(cr, accent)
        cr.set_line_width(2)
        cr.rectangle(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2)
        cr.stroke()
        fr = s.focus_ref
        if not single and fr is not None:
            row = s.row_of(fr.project)
            if row is not None:
                fx = m.day_x(s.day_index(fr.date))
                cr.set_line_width(1)
                cr.rectangle(fx + 2.5, m.row_tops[row] + 2.5, m.cell_w - 5,
                             m.row_tops[row + 1] - m.row_tops[row] - 5)
                cr.stroke()

    def _draw_header(self, cr, pal, days, ox, bw):
        s, m, f = self.s, self.m, self.fonts
        h_total = m.header_h
        rect(cr, 0, 0, bw, h_total, pal.pane_bg)
        if not days:
            return
        ry = [m.header_top(i) for i in range(4)]
        rh = m.header_rows

        def x(d):
            return m.day_x(d) - ox

        for d in days:
            date = s.date_at(d)
            cx = x(d)
            is_today = date == s.today
            if is_today:
                rect(cr, cx, ry[2], m.cell_w, rh[2] + rh[3], style.TODAY_YELLOW)
            elif is_weekend(date):
                rect(cr, cx, ry[2], m.cell_w, rh[2] + rh[3], pal.weekend)
            colour = (*style.TODAY_TEXT, 1) if is_today else \
                pal.text(0.55 if is_weekend(date) else 0.9)
            font = f.header_bold if is_today else f.header
            f.centred(cr, str(date.day), cx, ry[2], m.cell_w, rh[2], font, colour)
            f.centred(cr, WEEKDAY_LETTERS[date.isoweekday() - 1], cx, ry[3], m.cell_w, rh[3],
                      font, colour if is_today else pal.text(0.55), numeric=False)

        # Months: the name sticks to the left edge while its month is shown.
        d = days.start
        while d < days.stop:
            date = s.date_at(d)
            first = date.replace(day=1)
            nxt = add_days(first, 32).replace(day=1)
            month_start = s.day_index(first)
            month_end = min(days.stop, s.day_index(nxt))
            x0, x1 = max(0, x(month_start)), x(month_end)
            f.draw(cr, month_title(date), x0 + 6, ry[0], x1 - x0 - 8, rh[0], f.month,
                   pal.text(0.9))
            if month_start >= days.start:
                rect(cr, x(month_start), ry[0], 1, rh[0], pal.line(True))
            d = month_end

        # Weeks: the custom label (or the ISO week number) across Mon–Sun.
        w = s.day_index(monday(s.date_at(days.start)))
        while w < days.stop:
            label, custom = s.week_label(s.date_at(w))
            wx = x(w)
            ww = 7 * m.cell_w
            if custom:
                rect(cr, wx + 1.5, ry[1] + 2, ww - 3, rh[1] - 4, (*pal.accent[:3], 0.13))
            vx = max(wx, 0)
            f.draw(cr, label, vx + 5, ry[1], wx + ww - vx - 10, rh[1],
                   f.header_bold if custom else f.header, pal.text(0.9 if custom else 0.4))
            rect(cr, wx, ry[1], 1, rh[1] + rh[2] + rh[3], pal.line(True))
            w += 7

        self._working_week_lines(cr, pal, days, x, ry[1], h_total - ry[1])
        for i in (1, 2, 3):
            rect(cr, 0, ry[i] - self._px, bw, self._px, pal.line())
        rect(cr, 0, h_total - 1, bw, 1, pal.line(True))

    def _draw_left(self, cr, pal, rows, oy, lw, bh):
        s, m, f = self.s, self.m, self.fonts
        rect(cr, 0, 0, lw, bh, pal.view_bg)
        b = s.selection_bounds
        selected_rows = b[0] if b else range(0)
        fr = s.focus_ref
        focus_row = s.row_of(fr.project) if fr else None
        indent = int(14 * f.scale) if s.query.grouped else 0
        for r in rows:
            row = s.rows[r]
            y = m.row_tops[r] - oy
            h = m.row_tops[r + 1] - m.row_tops[r]
            if row.is_programme:
                rect(cr, 0, y, lw, h, pal.pane_bg)
                self._draw_chevron(cr, pal, 10 * f.scale, y + h / 2, row.collapsed)
                title = programme_title(row.name)
                tw = min(f.width(cr, title, f.programme), lw - 70)
                f.draw(cr, title, 22 * f.scale, y, tw + 2, h, f.programme, pal.text(0.9))
                f.draw(cr, str(row.count), 22 * f.scale + tw + 8, y, 40, h, f.secondary,
                       pal.text(0.5), numeric=True)
                rect(cr, 0, y + h - 1, lw, 1, pal.line(True))
                continue
            p = s.project(row.key)
            if p is None:
                continue
            if r == focus_row:
                rect(cr, 0, y, lw, h, (*pal.accent[:3], 0.16))
            elif r in selected_rows:
                rect(cr, 0, y, lw, h, (*pal.accent[:3], 0.08))
            for col, cx, cw in m.columns:
                tx, tw = cx + 7, cw - 12
                if col is LeftColumn.CODE:
                    f.draw(cr, p.code, tx, y, tw, h, f.code, pal.text(0.55))
                elif col is LeftColumn.TITLE:
                    f.draw(cr, p.title, tx + indent, y, tw - indent, h,
                           f.row if p.is_active else f.row_italic,
                           pal.text(0.9 if p.is_active else 0.5))
                elif col is LeftColumn.TARGET:
                    f.draw(cr, p.target, tx, y, tw, h, f.secondary, pal.text(0.55))
                else:
                    f.draw(cr, p.collaborators, tx, y, tw, h, f.secondary, pal.text(0.55))
            rect(cr, 0, y + h - self._px, lw, self._px, pal.line())
        height = min(bh, m.content_h - oy)
        for _, cx, cw in m.columns[:-1]:
            rect(cr, cx + cw - self._px, 0, self._px, max(0, height), pal.line())
        rect(cr, lw - 1, 0, 1, bh, pal.line(True))

    def _draw_chevron(self, cr, pal, cx, cy, collapsed):
        k = 3.5 * self.fonts.scale
        rgba(cr, pal.text(0.55))
        cr.set_line_width(1.6)
        if collapsed:
            cr.move_to(cx - k * 0.5, cy - k)
            cr.line_to(cx + k * 0.5, cy)
            cr.line_to(cx - k * 0.5, cy + k)
        else:
            cr.move_to(cx - k, cy - k * 0.5)
            cr.line_to(cx, cy + k * 0.5)
            cr.line_to(cx + k, cy - k * 0.5)
        cr.stroke()

    def _draw_corner(self, cr, pal, lw):
        s, m, f = self.s, self.m, self.fonts
        rect(cr, 0, 0, lw, m.header_h, pal.pane_bg)
        shown, total = len(s.included_keys), len(s.project_list.projects)
        summary = plural(total, "project") if shown == total else f"{shown} of {total} projects"
        f.draw(cr, summary, 8, 1, lw - 16, m.header_rows[0], f.secondary, pal.text(0.55))
        f.draw(cr, f"Today: {long_day(s.today)}", 8, m.header_top(1), lw - 16, m.header_rows[1],
               f.secondary, pal.text(0.4))
        top = m.header_top(2)
        hh = m.header_h - top
        for col, cx, cw in m.columns:
            title = col.title
            if s.query.sort is col.sort_key:
                title += " \u25b2" if s.query.ascending else " \u25bc"
            f.draw(cr, title, cx + 7, top, cw - 12, hh, f.header_bold, pal.text(0.6))
            rect(cr, cx + cw - 1, top + 4, 1, hh - 8, pal.line(True))
        rect(cr, 0, top - self._px, lw, self._px, pal.line())
        rect(cr, 0, m.header_h - 1, lw, 1, pal.line(True))
        rect(cr, lw - 1, 0, 1, m.header_h, pal.line(True))

    def _draw_footer(self, cr, pal, days, ox, bw, fh):
        s, m, f = self.s, self.m, self.fonts
        rect(cr, 0, 0, bw, fh, pal.pane_bg)
        if not days:
            return

        def x(d):
            return m.day_x(d) - ox

        peak = s.settings.day_peak
        sub = m.subtotal_h
        for i, programme in enumerate(m.footer_programmes):
            y = i * sub
            for d in days:
                date = s.date_at(d)
                cx = x(d)
                if date == s.today:
                    rect(cr, cx, y, m.cell_w, sub, (*style.TODAY_YELLOW, 0.16))
                elif is_weekend(date):
                    rect(cr, cx, y, m.cell_w, sub, pal.weekend)
                t = s.programme_footer_total(programme, date)
                if not t:
                    continue
                level = heat_level(t, peak)
                fill = style.total_fill(level)
                if fill:
                    rounded(cr, cx + 1.5, y + 2, m.cell_w - 3, sub - 4, 3)
                    rgba(cr, fill, 0.55)
                    cr.fill()
                colour = (1, 1, 1, 1) if level > 0.75 else (*style.TOTAL_DARK_TEXT, 1)
                if pal.dark and level <= 0.3:
                    colour = pal.text(0.85)
                f.centred(cr, str(t), cx, y, m.cell_w, sub, f.small, colour)
            rect(cr, 0, y + sub - self._px, bw, self._px, pal.line())

        t0 = m.totals_top
        r0, r1 = m.footer_rows
        for d in days:
            date = s.date_at(d)
            t = s.day_total(date)
            cx = x(d)
            level = heat_level(t, peak)
            fill = style.total_fill(level)
            if fill:
                rounded(cr, cx + 1, t0 + 2, m.cell_w - 2, r0 - 4, 3)
                rgba(cr, fill)
                cr.fill()
                f.centred(cr, str(t), cx + 1, t0 + 2, m.cell_w - 2, r0 - 4, f.total,
                          (*style.total_text(level), 1))
            if date == s.today:
                rounded(cr, cx + 0.5, t0 + 1.5, m.cell_w - 1, r0 - 3, 3)
                rgba(cr, style.TODAY_YELLOW)
                cr.set_line_width(2)
                cr.stroke()

        # Week and weekend spans, summed over all their days (even those
        # scrolled out of view).
        w = s.day_index(monday(s.date_at(days.start)))
        while w < days.stop:
            mon = s.date_at(w)
            self._span(cr, pal, s.span_total(mon, 5), s.settings.week_peak,
                       x(w), t0 + r0, 5 * m.cell_w, r1)
            self._span(cr, pal, s.span_total(add_days(mon, 5), 2), s.settings.weekend_peak,
                       x(w + 5), t0 + r0, 2 * m.cell_w, r1)
            w += 7
        self._working_week_lines(cr, pal, days, x, 0, fh)
        rect(cr, 0, 0, bw, 1, pal.line(True))
        if t0 > 0:
            rect(cr, 0, t0 - 1, bw, 1, pal.line(True))

    def _span(self, cr, pal, total, peak, x, y, w, h):
        f = self.fonts
        rx, ry, rw, rh = x + 2.5, y + 2, w - 5, h - 4
        level = heat_level(total, peak)
        fill = style.total_fill(level)
        if fill:
            rounded(cr, rx, ry, rw, rh, 3)
            rgba(cr, fill)
            cr.fill()
            f.centred(cr, str(total), rx, ry, rw, rh, f.total, (*style.total_text(level), 1))
        else:
            rounded(cr, rx + 0.5, ry + 0.5, rw - 1, rh - 1, 3)
            rgba(cr, pal.line(True))
            cr.set_line_width(1)
            cr.stroke()
            f.centred(cr, "0", rx, ry, rw, rh, f.small, pal.text(0.35))

    def _draw_footer_corner(self, cr, pal, lw, fh):
        s, m, f = self.s, self.m, self.fonts
        rect(cr, 0, 0, lw, fh, pal.pane_bg)
        sub = m.subtotal_h
        for i, programme in enumerate(m.footer_programmes):
            y = i * sub
            f.draw(cr, programme_title(programme), 8, y, lw - 16, sub, f.secondary,
                   pal.text(0.55), "right")
            rect(cr, 0, y + sub - self._px, lw, self._px, pal.line())
        t0 = m.totals_top
        r0, r1 = m.footer_rows
        scope = "shown" if s.totals_scope is TotalsScope.VISIBLE else "all"
        f.draw(cr, f"Daily total ({scope}) \u25be", 8, t0, lw - 16, r0, f.header_bold,
               pal.text(0.6), "right")
        f.draw(cr, "Mon\u2013Fri \u00b7 weekend", 8, t0 + r0, lw - 16, r1, f.header,
               pal.text(0.55), "right")
        rect(cr, 0, 0, lw, 1, pal.line(True))
        if t0 > 0:
            rect(cr, 0, t0 - 1, lw, 1, pal.line(True))
        rect(cr, lw - 1, 0, 1, fh, pal.line(True))

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def _hit(self, x, y):
        """(region, detail) for a point in widget coordinates."""
        lw, top, bw, bh = self._viewport()
        if y < top:
            if x < lw:
                return "corner", (x, y)
            day = self.m.day_at(x - lw + self.ox)
            row = max(i for i in range(4) if self.m.header_top(i) <= y)
            return "header", (row, day)
        if y >= top + bh:
            return ("footer-corner" if x < lw else "footer"), None
        cy = y - top + self.oy
        r = self.m.row_at(cy)
        if x < lw:
            return "left", r
        day = self.m.day_at(x - lw + self.ox)
        return "body", (r, day)

    def _ref_at(self, r, day) -> CellRef | None:
        if r is None or day is None or r >= len(self.s.rows):
            return None
        row = self.s.rows[r]
        if row.kind != "project":
            return None
        return CellRef(row.key, self.s.date_at(day))

    def cell_area(self, ref: CellRef) -> Gdk.Rectangle | None:
        """The cell's rectangle in widget coordinates."""
        row = self.s.row_of(ref.project)
        if row is None:
            return None
        lw, top, _, _ = self._viewport()
        r = Gdk.Rectangle()
        r.x = int(lw + self.m.day_x(self.s.day_index(ref.date)) - self.ox)
        r.y = int(top + self.m.row_tops[row] - self.oy)
        r.width = self.m.cell_w
        r.height = self.m.row_tops[row + 1] - self.m.row_tops[row]
        return r

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def _on_pressed(self, gesture, n_press, x, y):
        s = self.s
        button = gesture.get_current_button()
        state = gesture.get_current_event_state()
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        self.grab_focus()
        region, detail = self._hit(x, y)
        if button == 3:
            self._context_menu(region, detail, x, y)
            return
        if button != 1:
            return
        if region == "body":
            r, day = detail
            ref = self._ref_at(r, day)
            if ref is None:
                self.callout.close()
                if r is not None and r < len(s.rows) and s.rows[r].is_programme:
                    s.toggle_programme(s.rows[r].name)
                return
            if n_press == 2:
                self.callout.close()
                s.select(ref)
                self.activate_action("win.edit-note", None)
                return
            s.select(ref, extend=shift)
            if shift:
                self.callout.close()
            else:
                self._pin_callout(ref)
        elif region == "header":
            row, day = detail
            if day is None:
                return
            date = s.date_at(day)
            if row == 1:
                if n_press == 2:
                    self.activate_action("win.edit-week-label",
                                         GLib.Variant("s", monday(date).isoformat()))
                else:
                    s.select_days(monday(date), add_days(monday(date), 6))
            elif row >= 2:
                s.select_days(date, date, extend=shift)
        elif region == "left":
            r = detail
            if r is None or r >= len(s.rows):
                return
            row = s.rows[r]
            if row.is_programme:
                s.toggle_programme(row.name)
            else:
                s.select_project_row(row.key, extend=shift)
                s.inspector_tab = "project"
                s.bump()
                if n_press == 2:
                    self.activate_action("win.show-project", None)
        elif region == "corner":
            cx, cy = detail
            if cy < self.m.header_top(2):
                s.go_to_today()
                return
            if self.m.column_divider_near(cx) is not None:
                return    # a resize; see the drag gesture
            col = self.m.column_at(cx)
            if col is not None:
                s.set_sort(col.sort_key)
        elif region == "footer-corner":
            self._popup(self._totals_menu(), x, y)

    def _on_drag_begin(self, gesture, x, y):
        region, detail = self._hit(x, y)
        self._drag_origin = (x, y)
        self._drag = None
        if region == "body" and self._ref_at(*detail) is not None:
            self._drag = ("select",)
        elif region == "corner" and detail[1] >= self.m.header_top(2):
            col = self.m.column_divider_near(detail[0])
            if col is not None:
                self._drag = ("resize", col, x, self.s.column_width(col))

    def _on_drag_update(self, gesture, dx, dy):
        if self._drag is None:
            return
        x, y = self._drag_origin[0] + dx, self._drag_origin[1] + dy
        if self._drag[0] == "resize":
            _, col, start_x, start_w = self._drag
            self.s.set_column_width(col, start_w + (x - start_x) / self.fonts.scale)
            return
        if abs(dx) + abs(dy) < 3:
            return
        self._drag_point = (x, y)
        self._extend_drag_to(x, y)
        lw, top, bw, bh = self._viewport()
        outside = x < lw or x > lw + bw or y < top or y > top + bh
        if outside and not self._autoscroll_id:
            self._autoscroll_id = GLib.timeout_add(40, self._autoscroll)

    def _extend_drag_to(self, x, y):
        lw, top, bw, bh = self._viewport()
        cx = min(max(x - lw + self.ox, 0), self.m.content_w - 1)
        cy = min(max(y - top + self.oy, 0), self.m.content_h - 1)
        ref = self._ref_at(self.m.row_at(cy), self.m.day_at(cx))
        if ref is not None and self.s.selection and ref != self.s.selection.focus:
            self.callout.close()
            self.s.select(ref, extend=True)

    def _autoscroll(self):
        if self._drag is None or self._drag_point is None:
            self._autoscroll_id = 0
            return False
        x, y = self._drag_point
        lw, top, bw, bh = self._viewport()
        ha, va = self.props.hadjustment, self.props.vadjustment
        moved = False
        if x > lw + bw:
            ha.set_value(self.ox + min(40, (x - lw - bw) / 2 + 4))
            moved = True
        elif x < lw:
            ha.set_value(self.ox - min(40, (lw - x) / 2 + 4))
            moved = True
        if y > top + bh:
            va.set_value(self.oy + min(30, (y - top - bh) / 2 + 3))
            moved = True
        elif y < top:
            va.set_value(self.oy - min(30, (top - y) / 2 + 3))
            moved = True
        if not moved:
            self._autoscroll_id = 0
            return False
        self._extend_drag_to(x, y)
        return True

    def _on_drag_end(self, gesture, dx, dy):
        self._drag = None
        self._drag_point = None
        if self._autoscroll_id:
            GLib.source_remove(self._autoscroll_id)
            self._autoscroll_id = 0

    def _on_motion(self, _ctrl, x, y):
        region, detail = self._hit(x, y)
        resize = region == "corner" and detail[1] >= self.m.header_top(2) \
            and self.m.column_divider_near(detail[0]) is not None
        self.set_cursor_from_name("col-resize" if resize or (self._drag and self._drag[0] == "resize")
                                  else None)
        ref = self._ref_at(*detail) if region == "body" else None
        if ref == self._hover:
            return
        self._hover = ref
        if ref is None:
            self.callout.hover_ended()
            return
        c = self.s.cell(ref)
        if self.s.note_callouts and c.has_note:
            area = self.cell_area(ref)
            if area is not None:
                self.callout.hover(self._callout_content(ref), ref, area)
        else:
            self.callout.hover_ended()

    def _on_leave(self, _ctrl):
        self._hover = None
        self.callout.hover_ended()

    def _on_focus_leave(self, *_):
        self.queue_draw()
        if self.callout.pinned:
            self.callout.close()

    # ------------------------------------------------------------------
    # Notes and tooltips
    # ------------------------------------------------------------------

    def _callout_content(self, ref: CellRef):
        c = self.s.cell(ref)
        p = self.s.project(ref.project)
        subtitle = long_day(ref.date) + (f" \u00b7 {c.label.title}" if c.label else "")
        return (p.title if p else ref.project, subtitle, c.note)

    def _pin_callout(self, ref: CellRef):
        c = self.s.cell(ref)
        area = self.cell_area(ref)
        if not self.s.note_callouts or not c.has_note or area is None:
            self.callout.close()
            return
        self.callout.show(self._callout_content(ref), ref, area, True)

    def _refresh_callout(self):
        """After a change: closes a callout whose cell is gone, has lost its
        note or had it changed, or when callouts are switched off."""
        cl = self.callout
        if not cl.shown or cl.ref is None:
            return
        if (not self.s.note_callouts or self.s.row_of(cl.ref.project) is None
                or not self.s.cell(cl.ref).has_note
                or self._callout_content(cl.ref) != cl.content
                or (cl.pinned and self.s.selection and self.s.selection.focus != cl.ref)):
            cl.close()

    def _on_query_tooltip(self, _w, x, y, keyboard, tooltip):
        if keyboard:
            return False
        region, detail = self._hit(x, y)
        if region != "body":
            return False
        ref = self._ref_at(*detail)
        if ref is None:
            return False
        c = self.s.cell(ref)
        p = self.s.project(ref.project)
        lines = []
        period = p.inactive_period(ref.date) if p else None
        if period is not None:
            label = f"Inactive: {period.label}" if period.label else "Inactive"
            lines.append(f"{label} ({range_text(period.range)})")
        if c.has_note and not self.s.note_callouts:
            lines.append(c.note)
        if not lines:
            return False
        title = f"{p.title if p else ref.project} \u00b7 {long_day(ref.date)}"
        if c.label:
            title += f" \u00b7 {c.label.title}"
        tooltip.set_text("\n".join([title] + lines))
        area = self.cell_area(ref)
        if area is not None:
            tooltip.set_tip_area(area)
        return True

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def _on_key(self, _ctrl, keyval, _keycode, state):
        s = self.s
        self.callout.close()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        K = Gdk
        if ctrl and not alt:
            name = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or ""
            mapping = {"c": "win.copy", "x": "win.cut", "a": "win.select-all"}
            if name == "v":
                self.activate_action("win.paste-special-menu" if shift else "win.paste", None)
                return True
            if name == "z":
                self.activate_action("win.redo" if shift else "win.undo", None)
                return True
            if name == "y":
                self.activate_action("win.redo", None)
                return True
            if name in mapping and not shift:
                self.activate_action(mapping[name], None)
                return True
            return False
        if alt:
            return False
        moves = {K.KEY_Left: (0, -1), K.KEY_Right: (0, 1), K.KEY_Up: (-1, 0), K.KEY_Down: (1, 0),
                 K.KEY_KP_Left: (0, -1), K.KEY_KP_Right: (0, 1), K.KEY_KP_Up: (-1, 0),
                 K.KEY_KP_Down: (1, 0)}
        if keyval in moves:
            dr, dd = moves[keyval]
            self._move(dr, dd, shift)
            return True
        if keyval == K.KEY_Tab:
            self._move(0, 1, False)
            return True
        if keyval == K.KEY_ISO_Left_Tab:
            self._move(0, -1, False)
            return True
        if keyval in (K.KEY_Page_Up, K.KEY_Page_Down):
            n = max(1, self._viewport()[3] // self.m.row_h - 1)
            self._move(-n if keyval == K.KEY_Page_Up else n, 0, shift)
            return True
        if keyval == K.KEY_Home:
            self._move(0, -(s.focus_ref.date.isoweekday() - 1) if s.focus_ref else 0, shift)
            return True
        if keyval == K.KEY_Escape:
            s.collapse_selection()
            return True
        if keyval in (K.KEY_Return, K.KEY_KP_Enter, K.KEY_ISO_Enter):
            self.activate_action("win.edit-note", None)
            return True
        if keyval in (K.KEY_Delete, K.KEY_BackSpace, K.KEY_KP_Delete):
            s.set_label(None)
            return True
        cp = Gdk.keyval_to_unicode(keyval)
        if not cp:
            return False
        ch = chr(cp).lower()
        label = CellLabel.for_key(ch)
        if label is not None:
            s.set_label(label)
        elif ch == "0":
            s.set_label(None)
        elif ch == "i":
            s.toggle_selection_inactive()
        elif ch == " ":
            self.activate_action("win.side-panel", None)
        else:
            return False
        return True

    def _move(self, rows, days, extend):
        self.s.move_selection(rows, days, extend)
        self.reveal_focus()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _popup(self, model: Gio.Menu, x, y):
        if self._menu is not None:
            self._menu.unparent()
        menu = Gtk.PopoverMenu.new_from_model(model)
        menu.set_parent(self)
        menu.set_has_arrow(False)
        menu.set_halign(Gtk.Align.START)
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = int(x), int(y), 1, 1
        menu.set_pointing_to(r)
        menu.set_position(Gtk.PositionType.BOTTOM)
        self._menu = menu
        menu.popup()

    def popup_paste_special(self):
        """Ctrl+Shift+V: the paste modes, beside the selected cell."""
        f = self.s.focus_ref
        area = self.cell_area(f) if f else None
        x, y = (area.x + area.width, area.y + area.height) if area else (40, 40)
        m = Gio.Menu()
        m.append_section("Paste Special", _section(*[
            _item(mode.title, "win.paste-special", mode.value) for mode in PasteMode]))
        self._popup(m, x, y)

    def _context_menu(self, region, detail, x, y):
        s = self.s
        if region == "body":
            ref = self._ref_at(*detail)
            if ref is None:
                r = detail[0]
                if r is not None and r < len(s.rows) and s.rows[r].is_programme:
                    self._popup(self._programme_menu(s.rows[r].name), x, y)
                return
            self.callout.close()
            if ref not in s.selected_refs:
                s.select(ref)
            self._popup(self._cell_menu(), x, y)
        elif region == "left":
            r = detail
            if r is None or r >= len(s.rows):
                return
            row = s.rows[r]
            if row.is_programme:
                self._popup(self._programme_menu(row.name), x, y)
            else:
                if not s.selection or s.selection.focus.project != row.key:
                    s.select_project_row(row.key)
                self._popup(self._project_menu(row.key), x, y)
        elif region == "header":
            row, day = detail
            if day is not None:
                self._popup(self._week_menu(monday(s.date_at(day))), x, y)
        elif region == "corner":
            self._popup(self._columns_menu(), x, y)
        else:
            self._popup(self._totals_menu(), x, y)

    def _cell_menu(self) -> Gio.Menu:
        s = self.s
        m = Gio.Menu()
        m.append_section(None, _section(*[
            _item(f"{lb.text} \u2014 {lb.title}", "win.set-label", label_token(lb)) for lb in SIZES]))
        m.append_section(None, _section(*[
            _item(lb.title if lb.is_emblem else f"{lb.text} \u2014 {lb.title}",
                  "win.set-label", label_token(lb)) for lb in SPECIALS],
            _item("No Label", "win.set-label", "none")))
        has_note = s.focus_cell is not None and s.focus_cell.has_note
        m.append_section(None, _section(
            _item("Edit Note\u2026" if has_note else "Add Note\u2026", "win.edit-note"),
            _item("Clear Note", "win.clear-note"),
            _item("Mark Days Active" if s.selection_is_inactive else "Mark Days Inactive",
                  "win.toggle-inactive-days")))
        special = Gio.Menu()
        for mode in PasteMode:
            special.append_item(_item(mode.title, "win.paste-special", mode.value))
        edit = _section(_item("Cut", "win.cut"), _item("Copy", "win.copy"),
                        _item(f"Paste ({s.paste_mode.title})", "win.paste"))
        edit.append_submenu("Paste Special", special)
        m.append_section(None, edit)
        f = s.focus_ref
        if f is not None:
            m.append_submenu("Project", self._project_menu(f.project))
        return m

    def _project_menu(self, key: str) -> Gio.Menu:
        s = self.s
        p = s.project(key)
        m = Gio.Menu()
        if p is None:
            return m
        programmes = Gio.Menu()
        progs = Gio.Menu()
        for name in s.project_list.programme_names + [""]:
            progs.append_item(_item(programme_title(name), "win.move-to-programme", name))
        programmes.append_section(None, progs)
        programmes.append_section(None, _section(_item("New Programme\u2026",
                                                       "win.new-programme-for-project")))
        top = _section(_item("Show Details", "win.show-project"),
                       _item("Mark Project Active" if not p.is_active else "Mark Project Inactive",
                             "win.toggle-project-active"))
        top.append_submenu("Move to Programme", programmes)
        m.append_section(None, top)
        m.append_section(None, _section(_item("Move Up", "win.move-project-up"),
                                        _item("Move Down", "win.move-project-down")))
        m.append_section(None, _section(_item("Delete Project\u2026", "win.delete-project")))
        return m

    def _programme_menu(self, name: str) -> Gio.Menu:
        s = self.s
        collapsed = name in s.collapsed_programmes
        m = Gio.Menu()
        m.append_section(None, _section(
            _item("Expand" if collapsed else "Collapse", "win.toggle-programme", name),
            _item("Expand All", "win.expand-all"), _item("Collapse All", "win.collapse-all")))
        m.append_section(None, _section(
            _item(f"New Project in \u201c{programme_title(name)}\u201d\u2026",
                  "win.new-project-in", name),
            _item("Show Only This Programme", "win.programme-filter", name)))
        if name:
            m.append_section(None, _section(
                _item("Rename Programme\u2026", "win.rename-programme", name),
                _item("Move Programme Up", "win.move-programme-up", name),
                _item("Move Programme Down", "win.move-programme-down", name)))
            m.append_section(None, _section(_item("Delete Programme", "win.delete-programme",
                                                  name)))
        return m

    def _week_menu(self, week) -> Gio.Menu:
        m = Gio.Menu()
        m.append_section(None, _section(
            _item(f"Label for Week of {short_day(week)}\u2026", "win.edit-week-label",
                  week.isoformat()),
            _item("All Week Labels\u2026", "win.week-labels")))
        m.append_section(None, _section(_item("Week Numbers for Unlabelled Weeks",
                                              "win.week-numbers")))
        return m

    def _columns_menu(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append_section(None, _section(*[_item(c.title, f"win.column-{c.value}")
                                          for c in OPTIONAL_COLUMNS]))
        m.append_section(None, _section(_item("Reset Column Widths", "win.reset-column-widths")))
        return m

    def _totals_menu(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append_section("Totals Add Up", _section(*[
            _item(sc.title, "win.totals-scope", sc.value) for sc in TotalsScope]))
        m.append_section(None, _section(
            _item("Programme Subtotals Above Totals", "win.footer-subtotals"),
            _item("Workload Settings\u2026", "win.workload-settings")))
        return m


def selection_summary(s: Session) -> str:
    refs = s.selected_refs
    projects = len({r.project for r in refs})
    return f"{plural(len(refs), 'day')} selected across {plural(projects, 'project')}"


__all__ = ["ProgressGrid", "Metrics", "selection_summary", "GridSelection"]
