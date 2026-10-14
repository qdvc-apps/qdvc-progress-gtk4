"""The side panel on the right of the window (F9): the selected day, or the
selected day's project. The counterpart of the macOS edition's inspector.

The panel is refreshed after every change. Widgets are updated in place
(never rebuilt while you type in them), and every handler that writes to the
session is guarded so programmatic updates are not mistaken for typing.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..labels import SIZES, SPECIALS, CellLabel, PasteMode  # noqa: E402
from ..models import NO_PROGRAMME_TITLE, Project  # noqa: E402
from ..session import Session  # noqa: E402
from ..ui_prefs import long_day, plural, range_text  # noqa: E402
from .gtk4_dialogs import DateButton  # noqa: E402
from .gtk4_paint import LabelChip  # noqa: E402


def _group(title: str = "", description: str = "") -> Adw.PreferencesGroup:
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(title)
    if description:
        g.set_description(description)
    return g


def _value_row(title: str) -> tuple[Adw.ActionRow, Gtk.Label]:
    row = Adw.ActionRow(title=title)
    label = Gtk.Label(xalign=1)
    label.add_css_class("dim-label")
    label.add_css_class("numeric")
    row.add_suffix(label)
    return row, label


def _page(*children) -> Gtk.ScrolledWindow:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    box.set_margin_top(12)
    box.set_margin_bottom(18)
    box.set_margin_start(12)
    box.set_margin_end(12)
    for c in children:
        box.append(c)
    clamp = Adw.Clamp(maximum_size=480, child=box)
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    sw.set_child(clamp)
    return sw


class LabelButton(Gtk.Button):
    """Sets the selected days' label; drawn as in the grid, with the number
    it adds to the totals."""

    def __init__(self, label: CellLabel | None, session: Session):
        super().__init__()
        self.label = label
        self.s = session
        self.add_css_class("label-button")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_halign(Gtk.Align.CENTER)
        if label is None:
            chip = Gtk.Label(label="None")
            chip.add_css_class("caption-heading")
            chip.set_size_request(-1, 22)
        else:
            chip = LabelChip(label, 36, 22)
        box.append(chip)
        self.value = Gtk.Label()
        self.value.add_css_class("caption")
        self.value.add_css_class("dim-label")
        self.value.add_css_class("numeric")
        box.append(self.value)
        self.set_child(box)
        self.set_hexpand(True)
        self.set_tooltip_text(f"{label.title} (key {label.key})" if label else
                              "Clear the label (key 0)")
        self.connect("clicked", lambda *_: self.s.set_label(self.label))

    def refresh(self, selected: bool):
        self.value.set_text(str(self.s.settings.value(self.label)) if self.label else "\u2013")
        if selected:
            self.add_css_class("selected-label")
        else:
            self.remove_css_class("selected-label")


class DayPage(Gtk.Stack):
    def __init__(self, session: Session):
        super().__init__()
        self.s = session
        self._updating = False
        self._note_ref = None

        empty = Adw.StatusPage(icon_name="view-grid-symbolic", title="No Day Selected",
                               description="Click a cell in the grid.")
        empty.add_css_class("compact")
        self.add_named(empty, "empty")

        # Heading.
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("title-4")
        self.subtitle = Gtk.Label(xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head.append(self.title)
        head.append(self.subtitle)
        self.workload_group = _group()
        self.workload_row, self.workload_value = _value_row("Workload of selection")
        self.workload_group.add(self.workload_row)

        # Labels.
        self.buttons: list[LabelButton] = []

        def grid_of(labels):
            g = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
            for i, lb in enumerate(labels):
                b = LabelButton(lb, session)
                self.buttons.append(b)
                g.attach(b, i % 3, i // 3, 1, 1)
            return g

        work = _group("Work Done", "Type 1\u20135 in the grid for XS\u2013XL, 0 or Delete to clear.")
        work.add(grid_of([None] + SIZES))
        special = _group("Special", "Type m for a meeting, p for planned work, ! for a due date, "
                                    "v for a tick, x for a cross, ? for information. Emblems "
                                    "add nothing to the totals.")
        special.add(grid_of(SPECIALS))

        # Note.
        note = _group("Note")
        self.note_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False,
                                      top_margin=8, bottom_margin=8, left_margin=10,
                                      right_margin=10)
        self.note_view.add_css_class("note-view")
        self.note_view.get_buffer().connect("changed", self._on_note_changed)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_note_key)
        self.note_view.add_controller(keys)
        note_sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     min_content_height=120, max_content_height=320,
                                     propagate_natural_height=True)
        note_sw.set_child(self.note_view)
        note_sw.add_css_class("card")
        self.note_placeholder = Gtk.Label(label="Select a single day to write its note.",
                                          xalign=0, wrap=True)
        self.note_placeholder.add_css_class("dim-label")
        self.note_stack = Gtk.Stack(vhomogeneous=False)
        self.note_stack.add_named(note_sw, "note")
        self.note_stack.add_named(self.note_placeholder, "placeholder")
        note.add(self.note_stack)
        self.note_hint = Gtk.Label(label="Esc returns to the grid.", xalign=0)
        self.note_hint.add_css_class("caption")
        self.note_hint.add_css_class("dim-label")
        self.note_hint.set_margin_top(6)
        note.add(self.note_hint)

        # Availability.
        avail = _group("Availability", "Type i in the grid to mark the selected days inactive. "
                                       "The label is shown across the period.")
        self.inactive_row = Adw.SwitchRow(title="Inactive on this day")
        self.inactive_row.connect("notify::active", self._on_inactive)
        self.period_label = Adw.EntryRow(title="Label")
        self.period_label.connect("changed", self._on_period_label)
        self.period_row = Adw.ActionRow(title="Period")
        self.period_row.add_css_class("property")
        avail.add(self.inactive_row)
        avail.add(self.period_label)
        avail.add(self.period_row)

        # Copy & Paste.
        paste = _group("Copy &amp; Paste", "What Paste (Ctrl+V) writes into the selected days. A "
                                       "single copied day fills the whole selection. Ctrl+Shift+V "
                                       "pastes once in another way.")
        self.paste_checks: dict[PasteMode, Gtk.CheckButton] = {}
        first = None
        for mode in PasteMode:
            check = Gtk.CheckButton()
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.connect("toggled", self._on_paste_mode, mode)
            row = Adw.ActionRow(title=mode.title, activatable_widget=check)
            row.add_prefix(check)
            paste.add(row)
            self.paste_checks[mode] = check

        self.add_named(_page(head, self.workload_group, work, special, note, avail, paste),
                       "content")

    # --- handlers -------------------------------------------------------

    def _on_note_changed(self, buf):
        if self._updating or self._note_ref is None:
            return
        self.s.set_note(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False),
                        self._note_ref)

    def _on_note_key(self, _ctrl, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Escape:
            self.s.end_editing_sessions()
            self.s.emit("focus-grid")
            return True
        return False

    def _on_inactive(self, row, _pspec):
        if not self._updating:
            self.s.set_selection_inactive(row.get_active())

    def _on_period_label(self, entry):
        if self._updating:
            return
        f = self.s.focus_ref
        p = self.s.focused_project
        period = p.inactive_period(f.date) if (p and f) else None
        if period is not None:
            self.s.set_period_label(p.key, period.id, entry.get_text())

    def _on_paste_mode(self, check, mode):
        if not self._updating and check.get_active():
            self.s.paste_mode = mode

    def focus_note(self):
        if self.note_stack.get_visible_child_name() == "note":
            self.note_view.grab_focus()
            buf = self.note_view.get_buffer()
            buf.place_cursor(buf.get_end_iter())

    # --- refresh --------------------------------------------------------

    def refresh(self):
        s = self.s
        f = s.focus_ref
        p = s.focused_project
        if f is None or p is None:
            self.set_visible_child_name("empty")
            self._note_ref = None
            return
        self.set_visible_child_name("content")
        self._updating = True
        try:
            refs = s.selected_refs
            single = len(refs) == 1
            self.title.set_text(p.title)
            if single:
                self.subtitle.set_text(long_day(f.date))
            else:
                n = len({r.project for r in refs})
                self.subtitle.set_text(f"{plural(len(refs), 'day')} selected across "
                                       f"{plural(n, 'project')}")
            self.workload_group.set_visible(not single)
            self.workload_value.set_text(str(s.selection_workload()))
            same, common = s.common_selected_label()
            for b in self.buttons:
                b.refresh(same and b.label == common)

            self.note_stack.set_visible_child_name("note" if single else "placeholder")
            self.note_hint.set_visible(single)
            if single:
                note = s.cell(f).note
                buf = self.note_view.get_buffer()
                current = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
                if f != self._note_ref or current != note:
                    buf.set_text(note)
                self._note_ref = f
            else:
                self._note_ref = None

            inactive = s.selection_is_inactive
            self.inactive_row.set_title("Inactive on this day" if single else
                                        "Inactive on these days")
            if self.inactive_row.get_active() != inactive:
                self.inactive_row.set_active(inactive)
            period = p.inactive_period(f.date) if single else None
            self.period_label.set_visible(period is not None)
            self.period_row.set_visible(period is not None)
            if period is not None:
                if self.period_label.get_text() != period.label and \
                        not self.period_label.has_focus():
                    self.period_label.set_text(period.label)
                self.period_row.set_subtitle(range_text(period.range))
            check = self.paste_checks[s.paste_mode]
            if not check.get_active():
                check.set_active(True)
        finally:
            self._updating = False


class PeriodRow(Adw.ExpanderRow):
    """One inactive period: its dates, label, and Remove."""

    def __init__(self, page: "ProjectPage", key: str, period):
        super().__init__()
        self.page, self.key, self.period_id = page, key, period.id
        s = page.s
        self.set_title(range_text(period.range))
        self.set_subtitle(period.label or "No label")

        self.start_button = DateButton(period.range.start, lambda d: s.set_period_range(
            key, self.period_id, d, self._range().end))
        self.end_button = DateButton(period.range.end, lambda d: s.set_period_range(
            key, self.period_id, self._range().start, d))
        start_row = Adw.ActionRow(title="From")
        start_row.add_suffix(self.start_button)
        end_row = Adw.ActionRow(title="To")
        end_row.add_suffix(self.end_button)
        self.label_row = Adw.EntryRow(title="Label shown in the grid")
        self.label_row.set_text(period.label)
        self.label_row.connect("changed", self._on_label)
        remove = Gtk.Button(label="Remove Period", valign=Gtk.Align.CENTER)
        remove.add_css_class("destructive-action")
        remove.set_tooltip_text("The days become active again")
        remove.connect("clicked", lambda *_: s.remove_period(key, self.period_id))
        remove_row = Adw.ActionRow()
        remove_row.add_suffix(remove)
        for r in (start_row, end_row, self.label_row, remove_row):
            self.add_row(r)
        self.connect("notify::expanded", self._on_expanded)

    def _range(self):
        p = self.page.s.project(self.key)
        for period in (p.inactive_periods if p else []):
            if period.id == self.period_id:
                return period.range
        return None

    def _on_label(self, entry):
        if not self.page.updating:
            self.page.s.set_period_label(self.key, self.period_id, entry.get_text())

    def _on_expanded(self, *_):
        if self.get_expanded():
            self.page.expanded.add(self.period_id)
        else:
            self.page.expanded.discard(self.period_id)

    def update(self, period):
        self.set_subtitle(period.label or "No label")
        if self.label_row.get_text() != period.label and not self.label_row.has_focus():
            self.label_row.set_text(period.label)


class ProjectPage(Gtk.Stack):
    _FIELDS = [("title", "Title"), ("code", "ID"), ("target", "Target"),
               ("collaborators", "Collaborators")]

    def __init__(self, session: Session):
        super().__init__()
        self.s = session
        self.updating = False
        self._key = None
        self._programmes: list[str] = []
        self._period_signature = None
        self._period_rows: list[PeriodRow] = []
        self.expanded: set[str] = set()

        empty = Adw.StatusPage(icon_name="folder-documents-symbolic", title="No Project Selected",
                               description="Click a project in the grid.")
        empty.add_css_class("compact")
        self.add_named(empty, "empty")

        details = _group("Details")
        new_prog = Gtk.Button(label="New Programme\u2026", valign=Gtk.Align.CENTER)
        new_prog.add_css_class("flat")
        new_prog.set_action_name("win.new-programme-for-project")
        details.set_header_suffix(new_prog)
        self.entries: dict[str, Adw.EntryRow] = {}
        for attr, title in self._FIELDS:
            e = Adw.EntryRow(title=title)
            e.connect("changed", self._on_field, attr)
            self.entries[attr] = e
        self.entries["code"].add_css_class("monospace")
        self.code_hint = Gtk.Label(xalign=0, wrap=True)
        self.code_hint.add_css_class("caption")
        self.code_hint.set_margin_top(6)
        self.programme_model = Gtk.StringList()
        self.programme_row = Adw.ComboRow(title="Programme", model=self.programme_model)
        self.programme_row.connect("notify::selected", self._on_programme)
        self.active_row = Adw.SwitchRow(title="Active project",
                                        subtitle="Inactive projects can be hidden with the "
                                                 "Status filter")
        self.active_row.connect("notify::active", self._on_active)
        details.add(self.entries["title"])
        details.add(self.entries["code"])
        details.add(self.programme_row)
        details.add(self.entries["target"])
        details.add(self.entries["collaborators"])
        details.add(self.active_row)
        details.add(self.code_hint)

        self.periods = _group("Inactive Periods",
                              "Days the project was set aside, e.g. on hold for a few weeks. "
                              "Separate from the Active project switch.")
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER,
                         tooltip_text="Add Inactive Period")
        add.add_css_class("flat")
        add.connect("clicked", self._on_add_period)
        self.periods.set_header_suffix(add)
        self.no_periods = Adw.ActionRow(title="None")
        self.no_periods.add_css_class("dim-label")
        self.periods.add(self.no_periods)

        workload = _group("Workload")
        self.w7_row, self.w7 = _value_row("Last 7 days")
        self.w30_row, self.w30 = _value_row("Last 30 days")
        self.last_row, self.last = _value_row("Last worked on")
        self.count_row, self.count = _value_row("Days logged")
        for r in (self.w7_row, self.w30_row, self.last_row, self.count_row):
            workload.add(r)

        order = _group("Order and File")
        self.key_row = Adw.ActionRow(title="File key", subtitle_selectable=True)
        self.key_row.add_css_class("property")
        up = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.CENTER,
                        tooltip_text="Move Up (Alt+Up)", action_name="win.move-project-up")
        down = Gtk.Button(icon_name="go-down-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Move Down (Alt+Down)", action_name="win.move-project-down")
        for b in (up, down):
            b.add_css_class("flat")
        move_row = Adw.ActionRow(title="Position", subtitle="Within its programme")
        move_row.add_suffix(up)
        move_row.add_suffix(down)
        order.add(self.key_row)
        order.add(move_row)
        delete = Gtk.Button(label="Delete Project\u2026", halign=Gtk.Align.CENTER,
                            action_name="win.delete-project")
        delete.add_css_class("destructive-action")
        delete.add_css_class("pill")

        self.add_named(_page(details, self.periods, workload, order, delete), "content")

    # --- handlers -------------------------------------------------------

    def _on_field(self, entry, attr):
        if self.updating or self._key is None:
            return
        text = entry.get_text()
        self.s.edit_project(self._key, attr, lambda p: setattr(p, attr, text))

    def _on_programme(self, row, _pspec):
        if self.updating or self._key is None:
            return
        i = row.get_selected()
        if 0 <= i < len(self._programmes):
            self.s.set_programme(self._programmes[i], self._key)

    def _on_active(self, row, _pspec):
        if not self.updating and self._key is not None:
            self.s.set_project_active(self._key, row.get_active())

    def _on_add_period(self, *_):
        if self._key is not None:
            f = self.s.focus_ref
            self.s.add_period(self._key, f.date if f else self.s.today)

    # --- refresh --------------------------------------------------------

    def refresh(self):
        s = self.s
        p = s.focused_project
        if p is None:
            self.set_visible_child_name("empty")
            self._key = None
            return
        self.set_visible_child_name("content")
        self.updating = True
        try:
            changed_project = p.key != self._key
            self._key = p.key
            for attr, _ in self._FIELDS:
                e = self.entries[attr]
                value = getattr(p, attr)
                if e.get_text() != value and (changed_project or not e.has_focus()):
                    e.set_text(value)
            other = s.project_list.project_with_code(p.code, excluding=p.key)
            if other is not None:
                self.code_hint.set_text(f"\u201c{other.title}\u201d already has this ID. "
                                        "Each ID should be used once.")
                self.code_hint.add_css_class("error")
                self.code_hint.set_visible(True)
            elif p.code and not Project.is_conventional_code(p.code):
                self.code_hint.set_text("IDs usually take the form NNXX: two digits, then two "
                                        "letters.")
                self.code_hint.remove_css_class("error")
                self.code_hint.set_visible(True)
            else:
                self.code_hint.set_visible(False)

            names = s.project_list.programme_names + [""]
            if names != self._programmes:
                self._programmes = names
                self.programme_model.splice(0, self.programme_model.get_n_items(),
                                            [n or NO_PROGRAMME_TITLE for n in names])
            index = names.index(s.project_list.group(p))
            if self.programme_row.get_selected() != index:
                self.programme_row.set_selected(index)
            if self.active_row.get_active() != p.is_active:
                self.active_row.set_active(p.is_active)
            self._refresh_periods(p)

            self.w7.set_text(str(s.project_workload(p.key, 7)))
            self.w30.set_text(str(s.project_workload(p.key, 30)))
            lw = s.last_worked.get(p.key)
            self.last.set_text(long_day(lw) if lw else "Never")
            self.count.set_text(str(s.entry_count(p.key)))
            self.key_row.set_subtitle(p.key)
        finally:
            self.updating = False

    def _refresh_periods(self, p: Project):
        signature = (p.key, tuple((x.id, x.range) for x in p.inactive_periods))
        if signature != self._period_signature:
            self._period_signature = signature
            for r in self._period_rows:
                self.periods.remove(r)
            self._period_rows = []
            for period in p.inactive_periods:
                row = PeriodRow(self, p.key, period)
                self.periods.add(row)
                if period.id in self.expanded:
                    row.set_expanded(True)
                self._period_rows.append(row)
        else:
            for row, period in zip(self._period_rows, p.inactive_periods):
                row.update(period)
        self.no_periods.set_visible(not p.inactive_periods)


class SidePanel(Adw.Bin):
    """Day and Project, switched in the panel's own header bar."""

    def __init__(self, session: Session):
        super().__init__()
        self.s = session
        self.day = DayPage(session)
        self.project = ProjectPage(session)
        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self.day, "day", "Day", "x-office-calendar-symbolic")
        self.stack.add_titled_with_icon(self.project, "project", "Project",
                                        "folder-documents-symbolic")
        self.stack.connect("notify::visible-child-name", self._on_tab)
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header = Adw.HeaderBar(title_widget=switcher)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.stack)
        self.set_child(view)
        self._updating = False

    def _on_tab(self, *_):
        if not self._updating:
            self.s.inspector_tab = self.stack.get_visible_child_name() or "day"

    def refresh(self):
        self._updating = True
        try:
            if self.stack.get_visible_child_name() != self.s.inspector_tab:
                self.stack.set_visible_child_name(self.s.inspector_tab)
        finally:
            self._updating = False
        self.day.refresh()
        self.project.refresh()

    def edit_note(self):
        self.s.inspector_tab = "day"
        self.refresh()
        GLib.idle_add(lambda: (self.day.focus_note(), False)[1])
