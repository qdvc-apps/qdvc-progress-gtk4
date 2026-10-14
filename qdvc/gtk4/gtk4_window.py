"""The main window (docs/DESIGN.md §2).

    Adw.ApplicationWindow
      Adw.ToastOverlay
        Adw.OverlaySplitView ── sidebar (end): SidePanel (Day / Project)
          Adw.ToolbarView
            top: Adw.HeaderBar · Gtk.SearchBar · Adw.Banner × 2
            content: Gtk.Stack ── "welcome": Adw.StatusPage
                                └ "grid": Gtk.Overlay(ScrolledWindow(ProgressGrid),
                                                      empty-state Adw.StatusPage)

The header bar follows GNOME Calendar: New Project and ‹ Today › with a
date picker at the start; search, view options, the side-panel toggle and
the main menu at the end. Below 860 sp the side panel overlays the grid.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_NAME  # noqa: E402
from ..models import programme_title  # noqa: E402
from ..query import SortKey, StatusFilter  # noqa: E402
from ..session import Scheduler, Session  # noqa: E402
from ..ui_prefs import OPTIONAL_COLUMNS, TotalsScope, plural  # noqa: E402
from .gtk4_actions import ALL, ActionsMixin  # noqa: E402
from .gtk4_dialogs import go_to_date_popover  # noqa: E402
from .gtk4_grid import ProgressGrid, _item, _section  # noqa: E402
from .gtk4_side_panel import SidePanel  # noqa: E402


class GLibScheduler(Scheduler):
    def call_later(self, delay_ms, fn):
        def fire():
            fn()
            return False
        return GLib.timeout_add(delay_ms, fire)

    def cancel(self, handle):
        if handle:
            GLib.source_remove(handle)


class ProgressWindow(ActionsMixin, Adw.ApplicationWindow):
    def __init__(self, app, config, icon_name: str):
        super().__init__(application=app, title=APP_NAME)
        self.icon_name = icon_name
        self.set_icon_name(icon_name)
        self.config = config
        self.s = Session(config, GLibScheduler())
        self._refresh_pending = False
        self._recents_shown = None
        self._programmes_shown = None

        win = config.get("window") or {}
        self.set_default_size(int(win.get("width", 1320)), int(win.get("height", 800)))
        self.set_size_request(360, 400)
        if win.get("maximized"):
            self.maximize()

        self._install_actions()
        self._build()
        self.s.connect(self._on_session)
        self.connect("close-request", self._on_close_request)
        self.connect("notify::is-active", self._on_active_changed)
        GLib.timeout_add_seconds(60, self._tick)
        self._refresh_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self):
        s = self.s
        # Header bar.
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title=APP_NAME)
        header.set_title_widget(self.title_widget)

        new = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New Project (Ctrl+N)",
                         action_name="win.new-project")
        nav = Gtk.Box()
        nav.add_css_class("linked")
        nav.append(Gtk.Button(icon_name="go-previous-symbolic", action_name="win.previous-week",
                              tooltip_text="Previous Week (Alt+Left)"))
        nav.append(Gtk.Button(label="Today", action_name="win.today",
                              tooltip_text="Go to Today (Ctrl+T)"))
        nav.append(Gtk.Button(icon_name="go-next-symbolic", action_name="win.next-week",
                              tooltip_text="Next Week (Alt+Right)"))
        self.calendar_button = Gtk.MenuButton(icon_name="x-office-calendar-symbolic",
                                              tooltip_text="Go to Date (Ctrl+G)",
                                              popover=go_to_date_popover(s))
        self.start_widgets = [new, nav, self.calendar_button]
        for w in self.start_widgets:
            header.pack_start(w)

        self.menu_button = menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                                        primary=True, tooltip_text="Main Menu")
        panel_toggle = Gtk.ToggleButton(icon_name="sidebar-show-right-symbolic",
                                        tooltip_text="Side Panel (F9)",
                                        action_name="win.side-panel")
        self.view_button = view_button = Gtk.MenuButton(icon_name="view-sort-descending-symbolic",
                                                        tooltip_text="Filter, Sort and View")
        search_toggle = Gtk.ToggleButton(icon_name="edit-find-symbolic",
                                         tooltip_text="Filter Projects (Ctrl+F)")
        header.pack_end(menu_button)
        header.pack_end(panel_toggle)
        header.pack_end(view_button)
        header.pack_end(search_toggle)
        self.end_widgets = [panel_toggle, view_button, search_toggle]

        # Search.
        self.search_entry = Gtk.SearchEntry(placeholder_text="Filter projects by title, ID, "
                                                             "target or collaborators",
                                            hexpand=True)
        self.search_entry.connect("search-changed",
                                  lambda e: s.set_search(e.get_text()))
        self.search_entry.connect("stop-search", lambda *_: self.search_bar.set_search_mode(False))
        clamp = Adw.Clamp(maximum_size=560, child=self.search_entry)
        self.search_bar = Gtk.SearchBar(child=clamp)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.bind_property("search-mode-enabled", search_toggle, "active",
                                      GObjectBinding.BIDIRECTIONAL)
        self.search_bar.connect("notify::search-mode-enabled", self._on_search_mode)

        # Banners.
        self.issue_banner = Adw.Banner(button_label="Show in Files")
        self.issue_banner.connect("button-clicked", self._on_issue_banner)
        self.error_banner = Adw.Banner(button_label="Dismiss")
        self.error_banner.connect("button-clicked", lambda *_: s.dismiss_save_error())

        # Grid.
        self.grid = ProgressGrid(s)
        scroller = Gtk.ScrolledWindow(child=self.grid)
        self.empty_page = Adw.StatusPage(vexpand=True, hexpand=True)
        self.empty_page.add_css_class("empty-grid")
        self.empty_buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self.empty_page.set_child(self.empty_buttons)
        overlay = Gtk.Overlay(child=scroller)
        overlay.add_overlay(self.empty_page)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self._welcome(), "welcome")
        self.stack.add_named(overlay, "grid")

        main = Adw.ToolbarView()
        main.add_top_bar(header)
        main.add_top_bar(self.search_bar)
        main.add_top_bar(self.issue_banner)
        main.add_top_bar(self.error_banner)
        main.set_content(self.stack)

        self.side_panel = SidePanel(s)
        self.split = Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END,
                                          sidebar=self.side_panel, content=main,
                                          min_sidebar_width=300, max_sidebar_width=400,
                                          sidebar_width_fraction=0.28)
        self.split.set_show_sidebar(s.side_panel_shown)
        self.split.connect("notify::show-sidebar", lambda *_: self._queue_refresh())
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 860sp"))
        bp.add_setter(self.split, "collapsed", True)
        bp.connect("apply", lambda *_: self.split.set_show_sidebar(False))
        bp.connect("unapply", lambda *_: self.split.set_show_sidebar(self.s.side_panel_shown))
        self.add_breakpoint(bp)
        self._build_main_menu()

    def _zoom_control(self):
        box = Gtk.Box(spacing=0, halign=Gtk.Align.CENTER, margin_start=12, margin_end=12)
        out = Gtk.Button(icon_name="zoom-out-symbolic", action_name="win.zoom-out",
                         tooltip_text="Narrower Days (Ctrl+\u2212)")
        reset = Gtk.Button(label="Day Width", action_name="win.zoom-reset", hexpand=True,
                           tooltip_text="Default Width (Ctrl+0)")
        inn = Gtk.Button(icon_name="zoom-in-symbolic", action_name="win.zoom-in",
                         tooltip_text="Wider Days (Ctrl+plus)")
        for b in (out, reset, inn):
            b.add_css_class("flat")
            box.append(b)
        return box

    def _welcome(self):
        page = Adw.StatusPage(icon_name=self.icon_name, title=APP_NAME, description=(
            "Open a progress workspace, or choose an empty folder to start one. Your projects "
            "and the work you log against them are kept there as plain YAML and CSV files, "
            "ready to commit to Git."))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        open_button = Gtk.Button(label="Open Workspace\u2026", halign=Gtk.Align.CENTER,
                                 action_name="win.open-workspace")
        open_button.add_css_class("pill")
        open_button.add_css_class("suggested-action")
        self.recent_group = Adw.PreferencesGroup(title="Recent")
        self.recent_rows = []
        box.append(open_button)
        box.append(self.recent_group)
        page.set_child(Adw.Clamp(maximum_size=520, child=box))
        return page

    def _build_main_menu(self):
        # A new model each time: GTK 4.14's popover menus do not cope well
        # with submenus being removed from a model they show.
        m = Gio.Menu()
        m.append_section(None, _section(_item("New Project\u2026", "win.new-project"),
                                        _item("New Programme\u2026", "win.new-programme")))
        ws = _section(_item("Open Workspace\u2026", "win.open-workspace"))
        recent = Gio.Menu()
        recents = Gio.Menu()
        for path in self.s.recent_workspaces:
            recents.append_item(_item(_home(path), "win.open-recent", path))
        recent.append_section(None, recents)
        recent.append_section(None, _section(_item("Clear List", "win.clear-recents")))
        ws.append_submenu("Open Recent", recent)
        ws.append_item(_item("Show in Files", "win.show-in-files"))
        ws.append_item(_item("Close Workspace", "win.close-workspace"))
        m.append_section(None, ws)
        m.append_section(None, _section(_item("Week Labels\u2026", "win.week-labels"),
                                        _item("Go to Date\u2026", "win.go-to-date"),
                                        _item("Refresh from Disk", "win.refresh")))
        m.append_section(None, _section(_item("Preferences", "win.preferences"),
                                        _item("Keyboard Shortcuts", "win.shortcuts"),
                                        _item(f"About {APP_NAME}", "win.about")))
        self.menu_button.set_menu_model(m)
        self._recents_shown = list(self.s.recent_workspaces)

    def _build_view_menu(self):
        s = self.s
        m = Gio.Menu()
        progs = [_item("All Programmes", "win.programme-filter", ALL)]
        progs += [_item(n, "win.programme-filter", n) for n in s.project_list.programme_names]
        progs.append(_item(programme_title(""), "win.programme-filter", ""))
        m.append_section("Programme", _section(*progs))
        m.append_section("Show", _section(*[_item(f.title, "win.status-filter", f.value)
                                            for f in StatusFilter]))
        sort = Gio.Menu()
        sort.append_section(None, _section(*[_item(k.title, "win.sort-key", k.value)
                                             for k in SortKey]))
        sort.append_section(None, _section(_item("Ascending", "win.sort-order", "ascending"),
                                           _item("Descending", "win.sort-order", "descending")))
        sort.append_section(None, _section(
            _item("Group by Programme", "win.group-by-programme"),
            _item("Inactive Today Last", "win.inactive-today-last")))
        columns = Gio.Menu()
        columns.append_section(None, _section(*[_item(c.title, f"win.column-{c.value}")
                                                for c in OPTIONAL_COLUMNS]))
        columns.append_section(None, _section(_item("Reset Column Widths",
                                                    "win.reset-column-widths")))
        totals = Gio.Menu()
        totals.append_section("Totals Add Up", _section(*[
            _item(t.title, "win.totals-scope", t.value) for t in TotalsScope]))
        totals.append_section(None, _section(
            _item("Programme Subtotals Above Totals", "win.footer-subtotals"),
            _item("Programme Subtotals in Headings", "win.heading-subtotals")))
        more = Gio.Menu()
        more.append_submenu("Sort", sort)
        more.append_submenu("Columns", columns)
        more.append_submenu("Totals", totals)
        m.append_section(None, more)
        m.append_section(None, _section(_item("Expand All Programmes", "win.expand-all"),
                                        _item("Collapse All Programmes", "win.collapse-all")))
        zoom = Gio.MenuItem()
        zoom.set_attribute_value("custom", GLib.Variant("s", "zoom"))
        m.append_section(None, _section(zoom))
        self.view_button.set_menu_model(m)
        self.view_button.get_popover().add_child(self._zoom_control(), "zoom")
        self._programmes_shown = list(s.project_list.programme_names)

    # ------------------------------------------------------------------
    # Refreshing
    # ------------------------------------------------------------------

    def _on_session(self, event, payload):
        if event == "changed":
            self._queue_refresh()

    def _queue_refresh(self):
        if not self._refresh_pending:
            self._refresh_pending = True
            GLib.idle_add(self._refresh_ui)

    def _refresh_ui(self):
        self._refresh_pending = False
        s = self.s
        ws = s.workspace is not None
        self.stack.set_visible_child_name("grid" if ws else "welcome")
        for w in self.start_widgets + self.end_widgets:
            w.set_visible(ws)
        if not ws:
            if self.split.get_show_sidebar():
                self.split.set_show_sidebar(False)
        elif not self.split.get_collapsed() and \
                self.split.get_show_sidebar() != s.side_panel_shown:
            self.split.set_show_sidebar(s.side_panel_shown)

        # Title.
        if ws:
            q = s.query
            parts = [programme_title(q.programme) if q.programme is not None else
                     "All programmes"]
            if q.status is not StatusFilter.ACTIVE:
                parts.append(q.status.title.lower().capitalize())
            shown, total = len(s.included_keys), len(s.project_list.projects)
            parts.append(plural(total, "project") if shown == total else f"{shown} of {total}")
            self.title_widget.set_title(s.window_title)
            self.title_widget.set_subtitle(" \u00b7 ".join(parts))
            self.set_title(f"{s.window_title} \u2014 {APP_NAME}")
        else:
            self.title_widget.set_title(APP_NAME)
            self.title_widget.set_subtitle("")
            self.set_title(APP_NAME)

        # Banners.
        if s.issues:
            first = s.issues[0]
            if len(s.issues) == 1:
                text = f"{first.relative_path}: {'; '.join(first.messages)}"
                if first.is_protected:
                    text += " It will not be changed until it is fixed."
            else:
                text = (f"{len(s.issues)} files had problems, starting with "
                        f"{first.relative_path}: {first.messages[0]}")
            self.issue_banner.set_title(GLib.markup_escape_text(text))
        self.issue_banner.set_revealed(bool(s.issues))
        if s.save_error:
            self.error_banner.set_title(GLib.markup_escape_text(
                f"Couldn\u2019t save: {s.save_error}"))
        self.error_banner.set_revealed(bool(s.save_error))

        self._refresh_empty_state()
        self._refresh_recents()
        if self._recents_shown != s.recent_workspaces:
            self._build_main_menu()
        if self._programmes_shown != s.project_list.programme_names:
            self._build_view_menu()
        self._update_actions()
        if ws:
            self.side_panel.refresh()
        return False

    def _refresh_empty_state(self):
        s = self.s
        while (child := self.empty_buttons.get_first_child()) is not None:
            self.empty_buttons.remove(child)
        if s.workspace is None or s.rows:
            self.empty_page.set_visible(False)
            return
        self.empty_page.set_visible(True)
        if not s.project_list.projects:
            self.empty_page.set_icon_name("view-grid-symbolic")
            self.empty_page.set_title("No Projects Yet")
            self.empty_page.set_description(
                "Add the projects you are working on, grouped into programmes of work if you "
                "like. Each gets a row, and each day a column.")
            b1 = Gtk.Button(label="New Project\u2026", action_name="win.new-project")
            b1.add_css_class("pill")
            b1.add_css_class("suggested-action")
            b2 = Gtk.Button(label="New Programme\u2026", action_name="win.new-programme")
            b2.add_css_class("pill")
            self.empty_buttons.append(b1)
            self.empty_buttons.append(b2)
        else:
            self.empty_page.set_icon_name("edit-find-symbolic")
            self.empty_page.set_title("No Matching Projects")
            self.empty_page.set_description("No project passes the current programme, status "
                                            "and search filters.")
            b = Gtk.Button(label="Show All Projects")
            b.add_css_class("pill")
            b.connect("clicked", self._show_all_projects)
            self.empty_buttons.append(b)

    def _show_all_projects(self, *_):
        self.search_bar.set_search_mode(False)
        self.s.query = self.s.query.but(programme=None, status=StatusFilter.ALL, search="")

    def _refresh_recents(self):
        paths = self.s.recent_workspaces[:5]
        if getattr(self, "_recent_rows_paths", None) == paths:
            return
        self._recent_rows_paths = paths
        for r in self.recent_rows:
            self.recent_group.remove(r)
        self.recent_rows = []
        for path in paths:
            row = Adw.ActionRow(title=GLib.markup_escape_text(os.path.basename(path) or path),
                                subtitle=GLib.markup_escape_text(_home(os.path.dirname(path))),
                                activatable=True)
            row.add_prefix(Gtk.Image(icon_name="folder-symbolic"))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, p=path: self.open_path(p))
            self.recent_group.add(row)
            self.recent_rows.append(row)
        self.recent_group.set_visible(bool(paths))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_search_mode(self, bar, _pspec):
        if not bar.get_search_mode():
            self.search_entry.set_text("")
            self.s.set_search("")
            self.grid.grab_focus()

    def _on_issue_banner(self, *_):
        if self.s.issues:
            self._show_in_files(self.s.issues[0].relative_path)

    def _on_active_changed(self, *_):
        if self.is_active():
            self.s.window_became_active()
        else:
            self.s.window_left()

    def _tick(self):
        self.s.day_changed()
        return True

    def _on_close_request(self, *_):
        self.s.flush_saves()
        self.config.set("window", {"width": self.get_width() or 1320,
                                   "height": self.get_height() or 800,
                                   "maximized": self.is_maximized()})
        return False

    def toast(self, title: str, undo: bool = False):
        t = Adw.Toast(title=GLib.markup_escape_text(title), timeout=4 if undo else 2)
        if undo:
            t.set_button_label("Undo")
            t.set_action_name("win.undo")
        self.toasts.add_toast(t)


def _home(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


from gi.repository import GObject  # noqa: E402

GObjectBinding = GObject.BindingFlags
