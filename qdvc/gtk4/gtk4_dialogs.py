"""Dialogs and small pickers. Every flow is asynchronous with a callback
(no ``dialog.run()``), and dates are always picked with a ``Gtk.Calendar``."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..dates import Date, iso_week  # noqa: E402
from ..models import NO_PROGRAMME_TITLE, Project  # noqa: E402
from ..session import Session  # noqa: E402
from ..ui_prefs import long_day  # noqa: E402


def calendar_date(cal: Gtk.Calendar) -> Date:
    dt = cal.get_date()
    return Date(dt.get_year(), dt.get_month(), dt.get_day_of_month())


def select_calendar_day(cal: Gtk.Calendar, d: Date) -> None:
    cal.select_day(GLib.DateTime.new_local(d.year, d.month, d.day, 12, 0, 0))


class DateButton(Gtk.MenuButton):
    """A button showing a day; clicking it opens a calendar."""

    def __init__(self, day: Date, on_pick: Callable[[Date], None]):
        super().__init__(valign=Gtk.Align.CENTER)
        self.day = day
        self.on_pick = on_pick
        self.set_label(long_day(day))
        self.add_css_class("flat")
        self.calendar = Gtk.Calendar()
        select_calendar_day(self.calendar, day)
        self._picking = False
        self.calendar.connect("day-selected", self._on_day)
        pop = Gtk.Popover(child=self.calendar)
        self.set_popover(pop)

    def _on_day(self, cal):
        if self._picking:
            return
        d = calendar_date(cal)
        if d != self.day:
            self.day = d
            self.set_label(long_day(d))
            self.get_popover().popdown()
            self.on_pick(d)


def go_to_date_popover(session: Session) -> Gtk.Popover:
    """A calendar that scrolls the grid to the day picked (Ctrl+G)."""
    cal = Gtk.Calendar()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.append(cal)
    today = Gtk.Button(label="Today")
    today.add_css_class("flat")
    box.append(today)
    pop = Gtk.Popover(child=box)
    state = {"busy": False}

    def on_show(*_):
        state["busy"] = True
        f = session.focus_ref
        select_calendar_day(cal, f.date if f else session.today)
        state["busy"] = False

    def on_day(c):
        if state["busy"]:
            return
        pop.popdown()
        session.go_to(calendar_date(c))

    pop.connect("show", on_show)
    cal.connect("day-selected", on_day)
    today.connect("clicked", lambda *_: (pop.popdown(), session.go_to_today()))
    return pop


def alert(parent: Gtk.Widget, heading: str, body: str = "") -> None:
    d = Adw.AlertDialog(heading=heading, body=body)
    d.add_response("ok", "OK")
    d.present(parent)


def confirm(parent: Gtk.Widget, heading: str, body: str, action_label: str,
            on_confirm: Callable[[], None], destructive: bool = False) -> None:
    d = Adw.AlertDialog(heading=heading, body=body)
    d.add_response("cancel", "Cancel")
    d.add_response("ok", action_label)
    d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                              else Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("cancel" if destructive else "ok")
    d.set_close_response("cancel")
    d.connect("response", lambda _d, r: on_confirm() if r == "ok" else None)
    d.present(parent)


def text_prompt(parent: Gtk.Widget, heading: str, body: str, initial: str, placeholder: str,
                action_label: str, validate: Callable[[str], str | None],
                on_accept: Callable[[str], None], extra: tuple[str, str, Callable] | None = None):
    """An alert with a text entry (New/Rename Programme, a week's label).
    ``validate`` returns a problem to show, or None. ``extra`` adds a third
    response (id, label, callback)."""
    d = Adw.AlertDialog(heading=heading, body=body)
    entry = Gtk.Entry(text=initial, placeholder_text=placeholder, activates_default=True)
    problem = Gtk.Label(xalign=0, wrap=True)
    problem.add_css_class("caption")
    problem.add_css_class("error")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.append(entry)
    box.append(problem)
    d.set_extra_child(box)
    d.add_response("cancel", "Cancel")
    if extra:
        d.add_response(extra[0], extra[1])
    d.add_response("ok", action_label)
    d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("ok")
    d.set_close_response("cancel")

    def check(*_):
        text = entry.get_text()
        p = validate(text)
        d.set_response_enabled("ok", p is None)
        problem.set_text(p if (p and text.strip()) else "")
        problem.set_visible(bool(p and text.strip()))

    entry.connect("changed", check)
    check()

    def on_response(_d, r):
        if r == "ok":
            on_accept(entry.get_text())
        elif extra and r == extra[0]:
            extra[2]()

    d.connect("response", on_response)
    d.present(parent)
    GLib.idle_add(lambda: (entry.grab_focus(), entry.select_region(0, -1), False)[2])


def programme_name_dialog(parent: Gtk.Widget, session: Session, original: str | None = None,
                          assign_to: str | None = None) -> None:
    """New Programme (``original`` None) or Rename Programme."""
    def accept(text):
        if original is None:
            session.new_programme(text, assign_to)
        else:
            session.rename_programme(original, text)

    def validate(text):
        if original is not None and text.strip() == original:
            return ""
        return session.programme_name_problem(text, original)

    text_prompt(parent, "New Programme" if original is None else "Rename Programme",
                "A programme is a major stream of work that groups related projects.",
                original or "", "e.g. Research", "Create" if original is None else "Rename",
                validate, accept)


def week_label_dialog(parent: Gtk.Widget, session: Session, week: Date,
                      on_edit_all: Callable[[], None]) -> None:
    text_prompt(parent, f"Week of {long_day(week)}",
                f"Leave empty to show the week number (W{iso_week(week)}).",
                session.week_labels.get(week) or "", "e.g. Teaching week 7, Sprint 12, Leave",
                "Save", lambda _t: None, lambda t: session.set_week_label(t, week),
                extra=("all", "All Labels\u2026", on_edit_all))


class NewProjectDialog(Adw.Dialog):
    """New Project (Ctrl+N)."""

    def __init__(self, session: Session, programme: str = ""):
        super().__init__(title="New Project", content_width=460)
        self.s = session
        names = session.project_list.programme_names + [""]
        self._names = names

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        self.create = Gtk.Button(label="Create")
        self.create.add_css_class("suggested-action")
        self.create.connect("clicked", lambda *_: self._accept())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.create)

        group = Adw.PreferencesGroup()
        self.title_row = Adw.EntryRow(title="Title")
        self.code_row = Adw.EntryRow(title="ID (optional, e.g. 26XY)")
        self.code_row.add_css_class("monospace")
        self.programme_row = Adw.ComboRow(
            title="Programme", model=Gtk.StringList.new([n or NO_PROGRAMME_TITLE for n in names]))
        self.programme_row.set_selected(names.index(programme) if programme in names
                                        else len(names) - 1)
        self.target_row = Adw.EntryRow(title="Target (optional)")
        self.collab_row = Adw.EntryRow(title="Collaborators (optional)")
        for r in (self.title_row, self.code_row, self.programme_row, self.target_row,
                  self.collab_row):
            group.add(r)
        for r in (self.title_row, self.code_row, self.target_row, self.collab_row):
            r.connect("changed", lambda *_: self._validate())
            r.connect("entry-activated", lambda *_: self._accept())
        self.problem = Gtk.Label(xalign=0, wrap=True)
        self.problem.add_css_class("caption")
        self.problem.set_margin_top(8)
        group.add(self.problem)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_top(12)
        box.set_margin_bottom(24)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.append(group)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(box)
        self.set_child(view)
        self.set_default_widget(self.create)
        self.set_focus(self.title_row)
        self._validate()

    def _validate(self):
        title, code = self.title_row.get_text(), self.code_row.get_text()
        other = self.s.project_list.project_with_code(code)
        ok = bool(title.strip()) and other is None
        self.create.set_sensitive(ok)
        if other is not None:
            self.problem.set_text(f"\u201c{other.title}\u201d already has the ID {other.code}. "
                                  "Each ID can be used once.")
            self.problem.add_css_class("error")
            self.problem.set_visible(True)
        elif code.strip() and not Project.is_conventional_code(code.strip()):
            self.problem.set_text("IDs usually take the form NNXX: two digits, then two letters.")
            self.problem.remove_css_class("error")
            self.problem.set_visible(True)
        else:
            self.problem.set_visible(False)
        return ok

    def _accept(self):
        if not self._validate():
            return
        self.s.add_project(self.title_row.get_text(), self.code_row.get_text(),
                           self._names[self.programme_row.get_selected()],
                           self.target_row.get_text(), self.collab_row.get_text())
        self.close()
