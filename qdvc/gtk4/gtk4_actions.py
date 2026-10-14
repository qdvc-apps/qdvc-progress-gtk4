"""Every command of the window, as a ``win.*`` ``Gio.SimpleAction``.

Menu items, header-bar buttons, context menus and keyboard shortcuts all
name these actions, so one action drives every surface and
:meth:`ActionsMixin._update_actions` greys or checks them all at once.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_NAME  # noqa: E402
from ..clipboard import MIME_TYPE, CellClip  # noqa: E402
from ..dates import parse_iso  # noqa: E402
from ..labels import PasteMode, label_from_token, label_token  # noqa: E402
from ..query import SortKey, StatusFilter  # noqa: E402
from ..session import OpenError  # noqa: E402
from ..ui_prefs import CELL_WIDTH_STEP, DEFAULT_CELL_WIDTH, LeftColumn, TotalsScope, plural  # noqa: E402
from ..workspace import looks_like_workspace  # noqa: E402
from . import gtk4_dialogs as dialogs  # noqa: E402

ALL = "__all__"     # the programme filter's "All Programmes"


class ActionsMixin:
    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def _install_actions(self):
        self._actions: dict[str, Gio.SimpleAction] = {}
        plain = {
            "new-project": lambda: self.new_project(),
            "new-programme": lambda: dialogs.programme_name_dialog(self, self.s),
            "new-programme-for-project": self._new_programme_for_project,
            "open-workspace": self.choose_workspace,
            "clear-recents": self.s.clear_recents,
            "show-in-files": self._show_in_files,
            "close-workspace": self.s.close_workspace,
            "refresh": self._refresh_workspace,
            "week-labels": self.show_week_labels,
            "preferences": lambda: self.show_preferences(),
            "workload-settings": lambda: self.show_preferences("Workload"),
            "shortcuts": self.show_shortcuts,
            "about": self.show_about,
            "today": self.s.go_to_today,
            "previous-week": lambda: self.s.shift_weeks(-1),
            "next-week": lambda: self.s.shift_weeks(1),
            "go-to-date": lambda: self.calendar_button.popup(),
            "find": self._find,
            "zoom-in": lambda: self.s.zoom(CELL_WIDTH_STEP),
            "zoom-out": lambda: self.s.zoom(-CELL_WIDTH_STEP),
            "zoom-reset": lambda: setattr(self.s, "cell_width", DEFAULT_CELL_WIDTH),
            "programme-all": lambda: self._set_programme_filter(None),
            "reset-column-widths": self.s.reset_column_widths,
            "expand-all": lambda: self.s.set_all_programmes(False),
            "collapse-all": lambda: self.s.set_all_programmes(True),
            "edit-note": self.edit_note,
            "clear-note": self.s.clear_notes,
            "clear-cells": self.s.clear_cells,
            "toggle-inactive-days": self.s.toggle_selection_inactive,
            "copy": self.copy_selection,
            "cut": self.cut_selection,
            "paste": lambda: self.paste(None),
            "paste-special-menu": lambda: self.grid.popup_paste_special(),
            "select-all": self.s.select_all,
            "undo": self._undo,
            "redo": self._redo,
            "show-project": self.show_project,
            "toggle-project-active": self._toggle_project_active,
            "move-project-up": lambda: self.s.move_project(None, -1),
            "move-project-down": lambda: self.s.move_project(None, 1),
            "delete-project": self.delete_project,
        }
        for name, fn in plain.items():
            self._add(name, lambda _a, _p, fn=fn: fn())

        with_string = {
            "open-recent": self.open_path,
            "new-project-in": lambda name: self.new_project(name),
            "edit-week-label": self._edit_week_label,
            "toggle-programme": self.s.toggle_programme,
            "rename-programme": lambda n: dialogs.programme_name_dialog(self, self.s, original=n),
            "delete-programme": self.delete_programme,
            "move-programme-up": lambda n: self.s.move_programme(n, -1),
            "move-programme-down": lambda n: self.s.move_programme(n, 1),
            "move-to-programme": self._move_to_programme,
            "paste-special": lambda m: self.paste(PasteMode(m)),
        }
        for name, fn in with_string.items():
            self._add(name, lambda _a, p, fn=fn: fn(p.get_string()), GLib.VariantType("s"))

        self._add("programme-index",
                  lambda _a, p: self._programme_by_index(p.get_int32()), GLib.VariantType("i"))

        # Radio choices (string state).
        self._stateful("set-label", "none", lambda v: self.s.set_label(label_from_token(v)))
        self._stateful("programme-filter", ALL,
                       lambda v: self._set_programme_filter(None if v == ALL else v))
        self._stateful("status-filter", "active",
                       lambda v: setattr(self.s, "query", self.s.query.but(status=StatusFilter(v))))
        self._stateful("sort-key", "manual", lambda v: self.s.set_sort(SortKey(v)))
        self._stateful("sort-order", "ascending", lambda v: setattr(
            self.s, "query", self.s.query.but(ascending=v == "ascending")))
        self._stateful("totals-scope", "visible",
                       lambda v: setattr(self.s, "totals_scope", TotalsScope(v)))

        # Switches (boolean state).
        self._toggle("side-panel", lambda v: self.set_side_panel(v))
        self._toggle("group-by-programme",
                     lambda v: setattr(self.s, "query", self.s.query.but(grouped=v)))
        self._toggle("inactive-today-last",
                     lambda v: setattr(self.s, "query", self.s.query.but(inactive_today_last=v)))
        for col in (LeftColumn.CODE, LeftColumn.TARGET, LeftColumn.COLLABORATORS):
            self._toggle(f"column-{col.value}",
                         lambda v, col=col: self.s.set_column_shown(col, v))
        self._toggle("footer-subtotals", lambda v: setattr(self.s, "show_footer_subtotals", v))
        self._toggle("heading-subtotals",
                     lambda v: setattr(self.s, "show_programme_subtotals", v))
        self._toggle("week-numbers", lambda v: setattr(self.s, "iso_week_fallback", v))
        self._toggle("outline-week", lambda v: setattr(self.s, "outline_working_week", v))
        self._toggle("note-callouts", lambda v: setattr(self.s, "note_callouts", v))

    def _add(self, name, handler, ptype=None):
        a = Gio.SimpleAction.new(name, ptype)
        a.connect("activate", handler)
        self.add_action(a)
        self._actions[name] = a

    def _stateful(self, name, initial, handler):
        a = Gio.SimpleAction.new_stateful(name, GLib.VariantType("s"), GLib.Variant("s", initial))
        a.connect("change-state", lambda act, v: handler(v.get_string()))
        self.add_action(a)
        self._actions[name] = a

    def _toggle(self, name, handler):
        a = Gio.SimpleAction.new_stateful(name, None, GLib.Variant("b", False))
        a.connect("change-state", lambda act, v: handler(v.get_boolean()))
        self.add_action(a)
        self._actions[name] = a

    # ------------------------------------------------------------------
    # Sensitivity and state
    # ------------------------------------------------------------------

    def _set_state(self, name, value):
        a = self._actions[name]
        v = GLib.Variant("b", value) if isinstance(value, bool) else GLib.Variant("s", value)
        if a.get_state() is None or a.get_state() != v:
            a.set_state(v)

    def _enable(self, names, enabled):
        for n in names:
            self._actions[n].set_enabled(enabled)

    def _update_actions(self):
        s = self.s
        ws = s.workspace is not None
        sel = s.has_selection
        fp = s.focused_project
        self._enable([
            "new-project", "new-programme", "show-in-files", "close-workspace", "refresh",
            "week-labels", "today", "previous-week", "next-week", "go-to-date", "find",
            "programme-all", "programme-index", "expand-all", "collapse-all", "edit-week-label",
            "toggle-programme", "rename-programme", "delete-programme", "move-programme-up",
            "move-programme-down", "new-project-in", "programme-filter", "status-filter",
            "sort-key", "sort-order", "group-by-programme", "inactive-today-last",
            "side-panel", "select-all", "workload-settings"], ws)
        self._enable(["set-label", "edit-note", "clear-note", "clear-cells",
                      "toggle-inactive-days", "copy", "cut", "paste", "paste-special",
                      "paste-special-menu"], ws and sel)
        self._enable(["show-project", "toggle-project-active", "move-to-programme",
                      "delete-project", "new-programme-for-project"], ws and fp is not None)
        self._actions["move-project-up"].set_enabled(ws and s.can_move_project(None, -1))
        self._actions["move-project-down"].set_enabled(ws and s.can_move_project(None, 1))
        self._actions["undo"].set_enabled(s.undo_manager.can_undo)
        self._actions["redo"].set_enabled(s.undo_manager.can_redo)
        self._actions["clear-recents"].set_enabled(bool(s.recent_workspaces))

        same, common = s.common_selected_label()
        self._set_state("set-label", label_token(common) if same else "mixed")
        q = s.query
        self._set_state("programme-filter", ALL if q.programme is None else q.programme)
        self._set_state("status-filter", q.status.value)
        self._set_state("sort-key", q.sort.value)
        self._set_state("sort-order", "ascending" if q.ascending else "descending")
        self._set_state("totals-scope", s.totals_scope.value)
        self._set_state("group-by-programme", q.grouped)
        self._set_state("inactive-today-last", q.inactive_today_last)
        for col in (LeftColumn.CODE, LeftColumn.TARGET, LeftColumn.COLLABORATORS):
            self._set_state(f"column-{col.value}", s.is_column_shown(col))
        self._set_state("footer-subtotals", s.show_footer_subtotals)
        self._set_state("heading-subtotals", s.show_programme_subtotals)
        self._set_state("week-numbers", s.iso_week_fallback)
        self._set_state("outline-week", s.outline_working_week)
        self._set_state("note-callouts", s.note_callouts)
        self._set_state("side-panel", self.split.get_show_sidebar())

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    def choose_workspace(self):
        dialog = Gtk.FileDialog(title="Open Workspace", accept_label="Open", modal=True)
        last = self.s.workspace.root if self.s.workspace else None
        if last:
            dialog.set_initial_folder(Gio.File.new_for_path(os.path.dirname(last)))

        def done(d, res):
            try:
                f = d.select_folder_finish(res)
            except GLib.Error:
                return      # cancelled
            if f is not None and f.get_path():
                self.open_path(f.get_path())
        dialog.select_folder(self, None, done)

    def open_path(self, path: str):
        """Opens the workspace at ``path``, offering to start one in a folder
        that is not one yet."""
        if os.path.isdir(path) and not looks_like_workspace(path):
            name = os.path.basename(os.path.abspath(path))
            dialogs.confirm(
                self, "Start a Progress Workspace Here?",
                f"\u201c{name}\u201d has no progress.yml or projects.yml yet. {APP_NAME} will "
                "create them, and keep your log in a log folder beside them, as plain text "
                "files you can commit to Git.", "Create", lambda: self._open(path))
            return
        self._open(path)

    def _open(self, path):
        try:
            self.s.open_workspace(path)
        except OpenError as e:
            dialogs.alert(self, e.title, e.message)
            return
        self.grid.grab_focus()

    def _show_in_files(self, relative: str | None = None):
        ws = self.s.workspace
        if ws is None:
            return
        target = ws.path(relative) if relative else ws.root
        f = Gio.File.new_for_path(target)
        launcher = Gtk.FileLauncher.new(f)
        if relative and os.path.exists(target):
            launcher.open_containing_folder(self, None, None)
        else:
            launcher.launch(self, None, None)

    def _refresh_workspace(self):
        self.s.refresh()
        self.toast("Reloaded from disk")

    # ------------------------------------------------------------------
    # Dialogs and panels
    # ------------------------------------------------------------------

    def new_project(self, programme: str | None = None):
        s = self.s
        if programme is None:
            fp = s.focused_project
            programme = s.project_list.group(fp) if fp else (s.query.programme or "")
        dialogs.NewProjectDialog(s, programme).present(self)

    def _new_programme_for_project(self):
        fp = self.s.focused_project
        dialogs.programme_name_dialog(self, self.s, assign_to=fp.key if fp else None)

    def show_week_labels(self):
        from .gtk4_week_labels import WeekLabelsDialog
        WeekLabelsDialog(self.s).present(self)

    def _edit_week_label(self, iso: str):
        week = parse_iso(iso)
        if week is not None:
            dialogs.week_label_dialog(self, self.s, week, self.show_week_labels)

    def show_preferences(self, page: str | None = None):
        from .gtk4_preferences import PreferencesDialog
        d = PreferencesDialog(self.s)
        if page:
            d.set_visible_page_name(page) if hasattr(d, "set_visible_page_name") else None
        d.present(self)

    def show_shortcuts(self):
        from .gtk4_shortcuts import shortcuts_window
        shortcuts_window(self).present()

    def show_about(self):
        d = Adw.AboutDialog(
            application_name=APP_NAME, application_icon=self.icon_name,
            developer_name="QDVC",
            comments="Keep track of your projects and the work you put into them, day by day.")
        d.present(self)

    def set_side_panel(self, shown: bool):
        self.split.set_show_sidebar(shown)
        if not self.split.get_collapsed():
            self.s.side_panel_shown = shown
        self._queue_refresh()

    def edit_note(self):
        s = self.s
        if not s.has_selection:
            return
        s.collapse_selection()
        s.inspector_tab = "day"
        self.set_side_panel(True)
        self.side_panel.edit_note()

    def show_project(self):
        self.s.inspector_tab = "project"
        self.set_side_panel(True)
        self.side_panel.refresh()

    def _find(self):
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _set_programme_filter(self, name):
        self.s.query = self.s.query.but(programme=name)

    def _programme_by_index(self, i: int):
        names = self.s.project_list.programme_names
        if 1 <= i <= len(names):
            self._set_programme_filter(names[i - 1])

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def _toggle_project_active(self):
        p = self.s.focused_project
        if p is not None:
            self.s.set_project_active(p.key, not p.is_active)

    def _move_to_programme(self, name: str):
        p = self.s.focused_project
        if p is not None:
            self.s.set_programme(name, p.key)

    def delete_project(self):
        p = self.s.focused_project
        if p is None:
            return
        n = self.s.entry_count(p.key)
        title = p.title

        def go():
            self.s.delete_project(p.key)
            self.toast(f"Deleted \u201c{title}\u201d", undo=True)
        dialogs.confirm(
            self, f"Delete \u201c{title}\u201d?",
            f"The project and its {plural(n, 'logged day')} are removed from the workspace. "
            "You can undo this, and Git keeps the history. To keep the project but hide it, "
            "mark it inactive instead.", "Delete", go, destructive=True)

    def delete_programme(self, name: str):
        if not name:
            return
        n = self.s.project_count(name)
        self.s.delete_programme(name)
        moved = f"; its {plural(n, 'project')} moved to No Programme" if n else ""
        self.toast(f"Deleted the programme \u201c{name}\u201d{moved}", undo=True)

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def _undo(self):
        name = self.s.undo()
        if name:
            self.toast(f"Undid {name}")

    def _redo(self):
        name = self.s.redo()
        if name:
            self.toast(f"Redid {name}")

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def copy_selection(self):
        clip = self.s.selection_clip()
        if clip is None:
            return
        provider = Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_bytes(MIME_TYPE, GLib.Bytes.new(clip.to_json())),
            Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8",
                                              GLib.Bytes.new(clip.tsv.encode("utf-8"))),
            Gdk.ContentProvider.new_for_bytes("text/plain", GLib.Bytes.new(clip.tsv.encode())),
        ])
        self.get_clipboard().set_content(provider)
        self._copied = (provider, clip)

    def cut_selection(self):
        self.copy_selection()
        self.s.cut_cells()

    def paste(self, mode: PasteMode | None):
        clipboard = self.get_clipboard()
        copied = getattr(self, "_copied", None)
        if copied and clipboard.get_content() is copied[0]:
            self.s.paste(copied[1], mode)
            return
        formats = clipboard.get_formats()
        if formats.contain_mime_type(MIME_TYPE):
            def done(cb, res):
                try:
                    stream, _mime = cb.read_finish(res)
                except GLib.Error:
                    return
                out = Gio.MemoryOutputStream.new_resizable()

                def spliced(o, r):
                    try:
                        o.splice_finish(r)
                    except GLib.Error:
                        return
                    clip = CellClip.from_json(o.steal_as_bytes().get_data())
                    if clip:
                        self.s.paste(clip, mode)
                out.splice_async(stream, Gio.OutputStreamSpliceFlags.CLOSE_SOURCE
                                 | Gio.OutputStreamSpliceFlags.CLOSE_TARGET,
                                 GLib.PRIORITY_DEFAULT, None, spliced)
            clipboard.read_async([MIME_TYPE], GLib.PRIORITY_DEFAULT, None, done)
            return

        def got_text(cb, res):
            try:
                text = cb.read_text_finish(res)
            except GLib.Error:
                return
            clip = CellClip.from_text(text or "")
            if clip:
                self.s.paste(clip, mode)
        clipboard.read_text_async(None, got_text)
