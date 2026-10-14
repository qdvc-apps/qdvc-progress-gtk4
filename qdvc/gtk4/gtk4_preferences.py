"""Preferences (Ctrl+,), applied as you change them.

Workload is saved in the workspace (``progress.yml``), so it travels with the
data; General is saved in this computer's config.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import style  # noqa: E402
from ..labels import SIZES, CellLabel  # noqa: E402
from ..log import heat_level  # noqa: E402
from ..session import Session  # noqa: E402
from ..settings import PRESETS  # noqa: E402
from ..ui_prefs import CELL_WIDTH_MAX, CELL_WIDTH_MIN, CELL_WIDTH_STEP, TotalsScope  # noqa: E402
from .gtk4_paint import Fonts, LabelChip, rgba, rounded  # noqa: E402


class HeatPreview(Gtk.DrawingArea):
    """The totals colour scale, from 0 to the peak."""

    def __init__(self, session: Session):
        super().__init__(content_height=26, hexpand=True)
        self.s = session
        self.set_draw_func(self._draw)

    def _draw(self, _a, cr, w, h):
        f = Fonts(self)
        peak = self.s.settings.day_peak
        n = 6
        gap = 4
        cw = (w - gap * (n - 1)) / n
        for i in range(n):
            value = int(round(peak * i / (n - 1)))
            level = heat_level(value, peak)
            fill = style.total_fill(level)
            x = i * (cw + gap)
            rounded(cr, x, 0, cw, h, 4)
            if fill:
                rgba(cr, fill)
            else:
                fg = self.get_color()
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
            cr.fill()
            colour = (*style.total_text(level), 1) if fill else (*self._fg(), 0.6)
            f.centred(cr, str(value), x, 0, cw, h, f.total, colour)

    def _fg(self):
        c = self.get_color()
        return (c.red, c.green, c.blue)


def _chip(label):
    chip = LabelChip(label, 34, 20)
    chip.set_valign(Gtk.Align.CENTER)
    return chip


def _spin(title: str, low: int, high: int, step: int = 1) -> Adw.SpinRow:
    row = Adw.SpinRow.new_with_range(low, high, step)
    row.set_title(title)
    row.set_numeric(True)
    return row


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, session: Session):
        super().__init__(title="Preferences", search_enabled=False)
        self.s = session
        self._updating = False
        self.add(self._workload_page())
        self.add(self._general_page())
        self.refresh()
        self._listener = lambda e, _p: self.refresh() if e == "changed" else None
        session.connect(self._listener)
        self.connect("closed", lambda *_: session.disconnect(self._listener))

    # --- workload -----------------------------------------------------------

    def _workload_page(self):
        page = Adw.PreferencesPage(title="Workload", icon_name="view-grid-symbolic")
        self.no_workspace = Adw.PreferencesGroup(
            description="The workload settings are saved in the workspace. Open one to change "
                        "them.")
        page.add(self.no_workspace)

        sizes = Adw.PreferencesGroup(
            title="Work Sizes",
            description="How much each size adds to the totals. The sizes are your own sense of "
                        "the effort a day\u2019s work took, not the hours.")
        self.preset_names = [p.name for p in PRESETS] + ["Custom"]
        self.preset_row = Adw.ComboRow(title="Preset",
                                       model=Gtk.StringList.new(self.preset_names))
        self.preset_row.connect("notify::selected", self._on_preset)
        sizes.add(self.preset_row)
        self.size_rows = []
        for i, label in enumerate(SIZES):
            row = _spin(label.title, 0, 100)
            row.add_prefix(_chip(label))
            row.connect("notify::value", self._on_size, i)
            sizes.add(row)
            self.size_rows.append(row)
        self.workload_groups = [sizes]

        special = Adw.PreferencesGroup(title="Special Labels")
        self.meeting_row = Adw.ComboRow(title="A meeting counts as", model=Gtk.StringList())
        self.meeting_row.add_prefix(_chip(CellLabel.MEETING))
        self.meeting_row.connect("notify::selected", self._on_meeting)
        self.due_row = _spin("A due date adds", 0, 100)
        self.due_row.add_prefix(_chip(CellLabel.DUE))
        self.due_row.connect("notify::value", self._on_value, "due_value")
        self.planned_row = _spin("Planned work adds", 0, 100)
        self.planned_row.add_prefix(_chip(CellLabel.PLANNED))
        self.planned_row.connect("notify::value", self._on_value, "planned_value")
        emblems = Adw.ActionRow(title="Tick, cross and information add")
        chips = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
        for lb in (CellLabel.TICK, CellLabel.CROSS, CellLabel.INFO):
            chips.append(LabelChip(lb, 20, 20))
        emblems.add_prefix(chips)
        zero = Gtk.Label(label="0")
        zero.add_css_class("dim-label")
        emblems.add_suffix(zero)
        for r in (self.meeting_row, self.due_row, self.planned_row, emblems):
            special.add(r)
        self.workload_groups.append(special)

        totals = Adw.PreferencesGroup(
            title="Totals",
            description="Week totals (Monday\u2013Friday) are deepest at five times this, "
                        "weekends at twice it.")
        self.peak_row = _spin("Deepest colour at a daily total of", 1, 200)
        self.peak_row.connect("notify::value", self._on_value, "day_peak")
        totals.add(self.peak_row)
        self.heat = HeatPreview(self.s)
        self.heat.set_margin_top(12)
        totals.add(self.heat)
        self.workload_groups.append(totals)
        for g in self.workload_groups:
            page.add(g)
        return page

    def _on_preset(self, row, _p):
        i = row.get_selected()
        if self._updating or i >= len(PRESETS):
            return
        values = list(PRESETS[i].values)
        self.s.update_settings(lambda st: setattr(st, "size_values", values))

    def _on_size(self, row, _p, i):
        if self._updating:
            return
        v = int(row.get_value())

        def change(st):
            st.size_values[i] = v
        self.s.update_settings(change)

    def _on_meeting(self, row, _p):
        if self._updating:
            return
        label = SIZES[row.get_selected()]
        self.s.update_settings(lambda st: setattr(st, "meeting_size", label))

    def _on_value(self, row, _p, attr):
        if self._updating:
            return
        v = int(row.get_value())
        self.s.update_settings(lambda st: setattr(st, attr, v))

    # --- general ------------------------------------------------------------

    def _switch(self, title, attr, subtitle=""):
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.connect("notify::active", lambda r, _p: None if self._updating
                    else setattr(self.s, attr, r.get_active()))
        self.switches.append((row, attr))
        return row

    def _general_page(self):
        self.switches = []
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        start = Adw.PreferencesGroup()
        start.add(self._switch("Reopen the last workspace at launch", "reopen_last"))
        page.add(start)

        grid = Adw.PreferencesGroup(title="Grid")
        grid.add(self._switch("Outline the working week", "outline_working_week",
                              "A line down the left of each Monday and the right of each Friday"))
        grid.add(self._switch("Week numbers for weeks without a label", "iso_week_fallback"))
        grid.add(self._switch("Show notes in a popover", "note_callouts",
                              "On click and hover; otherwise in a tooltip"))
        self.width_row = _spin("Day column width", CELL_WIDTH_MIN, CELL_WIDTH_MAX, CELL_WIDTH_STEP)
        self.width_row.set_subtitle("Also Ctrl+plus, Ctrl+minus and Ctrl+0")
        self.width_row.connect("notify::value", lambda r, _p: None if self._updating
                               else setattr(self.s, "cell_width", int(r.get_value())))
        grid.add(self.width_row)
        page.add(grid)

        totals = Adw.PreferencesGroup(title="Totals")
        self.scope_row = Adw.ComboRow(title="Totals add up",
                                      model=Gtk.StringList.new([t.title for t in TotalsScope]))
        self.scope_row.connect("notify::selected", lambda r, _p: None if self._updating else
                               setattr(self.s, "totals_scope", list(TotalsScope)[r.get_selected()]))
        totals.add(self.scope_row)
        totals.add(self._switch("Programme subtotals above the totals", "show_footer_subtotals"))
        totals.add(self._switch("Programme subtotals in programme headings",
                                "show_programme_subtotals"))
        page.add(totals)
        return page

    # --- refresh ------------------------------------------------------------

    def refresh(self):
        s = self.s
        self._updating = True
        try:
            has_ws = s.workspace is not None
            self.no_workspace.set_visible(not has_ws)
            for g in self.workload_groups:
                g.set_sensitive(has_ws)
            st = s.settings
            preset = st.matching_preset
            idx = PRESETS.index(preset) if preset else len(PRESETS)
            if self.preset_row.get_selected() != idx:
                self.preset_row.set_selected(idx)
            if preset:
                self.preset_row.set_subtitle(f"{', '.join(map(str, preset.values))}. "
                                             f"{preset.detail}")
            else:
                self.preset_row.set_subtitle("Your own numbers")
            for row, v in zip(self.size_rows, st.size_values):
                if int(row.get_value()) != v:
                    row.set_value(v)
            model = self.meeting_row.get_model()
            names = [f"{lb.text} ({st.value(lb)})" for lb in SIZES]
            if [model.get_string(i) for i in range(model.get_n_items())] != names:
                model.splice(0, model.get_n_items(), names)
            mi = SIZES.index(st.meeting_size)
            if self.meeting_row.get_selected() != mi:
                self.meeting_row.set_selected(mi)
            for row, v in ((self.due_row, st.due_value), (self.planned_row, st.planned_value),
                           (self.peak_row, st.day_peak)):
                if int(row.get_value()) != v:
                    row.set_value(v)
            self.heat.queue_draw()
            for row, attr in self.switches:
                v = bool(getattr(s, attr))
                if row.get_active() != v:
                    row.set_active(v)
            if int(self.width_row.get_value()) != s.cell_width:
                self.width_row.set_value(s.cell_width)
            ti = list(TotalsScope).index(s.totals_scope)
            if self.scope_row.get_selected() != ti:
                self.scope_row.set_selected(ti)
        finally:
            self._updating = False
