"""All window state and actions, independent of the toolkit.

This is the counterpart of the macOS edition's ``AppModel`` (and its
``+Cells`` and ``+Projects`` extensions). The GTK front-end draws what it
holds and calls its methods; it never changes the model directly. Every
change is written to the workspace straight away, except typing (notes,
project fields), which is written after a short pause, and whenever the
window is left or closed.

Listeners are told about changes through :meth:`Session.connect`:

* ``("changed", None)`` — anything shown may have changed; redraw.
* ``("scroll-to", date)`` — bring a day into view.
* ``("focus-grid", None)`` / ``("focus-note", None)`` — move the keyboard focus.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, NamedTuple

from . import workspace as ws_mod
from .clipboard import CellClip
from .config import Config
from .dates import Date, DayRange, MonthKey, add_days, days_between, monday, today as _today
from .labels import EMPTY_CELL, Cell, CellLabel, PasteMode
from .log import ProgressLog
from .models import NO_PROGRAMME_TITLE, InactivePeriod, Programme, Project, ProjectList, merged
from .query import LayoutRow, ProjectQuery, SortKey, StatusFilter, layout_rows
from .settings import WorkloadSettings
from .ui_prefs import (CELL_WIDTH_MAX, CELL_WIDTH_MIN, DEFAULT_CELL_WIDTH, LeftColumn,
                       TotalsScope)
from .undo import UndoManager
from .week_labels import WeekLabels
from .workspace import LoadIssue, Workspace

SAVE_DELAY_MS = 600


class CellRef(NamedTuple):
    """A project's cell on a day."""

    project: str
    date: Date


@dataclass(frozen=True)
class GridSelection:
    """The rectangle between the anchor (where the selection started) and
    the focus (where it ends: the cell the side panel shows and the arrow
    keys move)."""

    anchor: CellRef
    focus: CellRef


class OpenError(Exception):
    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title = title
        self.message = message


class Scheduler:
    """Runs a function after a delay. The GTK front-end uses GLib timeouts;
    the default never fires, so pending saves wait for :meth:`flush_saves`."""

    def call_later(self, delay_ms: int, fn: Callable[[], None]):
        return None

    def cancel(self, handle) -> None:
        pass


class Session:
    def __init__(self, config: Config | None = None, scheduler: Scheduler | None = None,
                 clock: Callable[[], Date] = _today):
        self.config = config or Config.in_memory()
        self.scheduler = scheduler or Scheduler()
        self.clock = clock
        self.undo_manager = UndoManager()
        self._listeners: list[Callable[[str, object], None]] = []

        # Workspace contents.
        self.workspace: Workspace | None = None
        self.settings = WorkloadSettings()
        self.project_list = ProjectList()
        self.week_labels = WeekLabels()
        self.log = ProgressLog()
        self.issues: list[LoadIssue] = []
        #: The last error writing a file, shown in a banner until dismissed.
        self.save_error: str | None = None

        # View state, kept in the config.
        c = self.config
        status = c.choice("filter_status", [s.value for s in StatusFilter])
        sort = c.choice("sort_key", [s.value for s in SortKey])
        programme = c.get("filter_programme")
        self._query = ProjectQuery(
            programme=programme if isinstance(programme, str) else None,
            status=StatusFilter(status), sort=SortKey(sort),
            ascending=c.bool("sort_ascending"), grouped=c.bool("group_by_programme"),
            inactive_today_last=c.bool("inactive_today_last"))
        collapsed = c.get("collapsed_programmes")
        self._collapsed: set[str] = {x for x in collapsed if isinstance(x, str)} \
            if isinstance(collapsed, list) else set()
        hidden = c.get("hidden_columns")
        self._hidden_columns: set[LeftColumn] = {
            LeftColumn(x) for x in (hidden if isinstance(hidden, list) else [])
            if x in [col.value for col in LeftColumn] and x != LeftColumn.TITLE.value}
        widths = c.get("column_widths")
        self._column_widths: dict[LeftColumn, int] = {}
        if isinstance(widths, dict):
            for col in LeftColumn:
                v = widths.get(col.value)
                if isinstance(v, (int, float)):
                    self._column_widths[col] = max(col.min_width, int(v))
        cw = c.get("cell_width")
        self._cell_width = int(min(max(cw if isinstance(cw, (int, float)) else DEFAULT_CELL_WIDTH,
                                       CELL_WIDTH_MIN), CELL_WIDTH_MAX))
        self._totals_scope = TotalsScope(c.choice("totals_scope", [s.value for s in TotalsScope]))
        self._paste_mode = PasteMode(c.choice("paste_mode", [m.value for m in PasteMode]))
        self.inspector_tab = "day"

        # Layout (derived).
        self.revision = 0
        self.rows: list[LayoutRow] = []
        #: Projects that pass the filter, in row order (including those in
        #: collapsed programmes).
        self.included_keys: list[str] = []
        self.included_set: set[str] = set()
        self._row_of_project: dict[str, int] = {}
        self._project_rows: list[int] = []
        self.group_of_project: dict[str, str] = {}
        self.last_worked: dict[str, Date] = {}

        #: The first day of the grid (a Monday) and how many days it shows.
        self.today = self.clock()
        self.range_start = monday(add_days(self.today, -56))
        self.day_count = 7 * 26

        self._selection: GridSelection | None = None

        # Saving.
        self._pending_months: set[MonthKey] = set()
        self._pending_projects = False
        self._save_handle = None
        #: The cell whose note is being typed (one undo step per visit).
        self.note_session: CellRef | None = None
        #: The project field being typed in ("key/field"), likewise.
        self.project_session: str | None = None

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def connect(self, fn: Callable[[str, object], None]) -> None:
        self._listeners.append(fn)

    def disconnect(self, fn: Callable[[str, object], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def emit(self, event: str, payload=None) -> None:
        for fn in list(self._listeners):
            fn(event, payload)

    def bump(self) -> None:
        """Something the window shows has changed."""
        self.revision += 1
        self.emit("changed")

    # ------------------------------------------------------------------
    # Preferences (view state)
    # ------------------------------------------------------------------

    def _pref_bool(self, key: str) -> bool:
        return self.config.bool(key)

    def _set_pref_bool(self, key: str, value: bool) -> None:
        if self.config.bool(key) != value:
            self.config.set(key, bool(value))
            self.bump()

    @property
    def show_programme_subtotals(self) -> bool:
        return self._pref_bool("programme_subtotals")

    @show_programme_subtotals.setter
    def show_programme_subtotals(self, v: bool):
        self._set_pref_bool("programme_subtotals", v)

    @property
    def show_footer_subtotals(self) -> bool:
        """A row per programme above the totals."""
        return self._pref_bool("footer_subtotals")

    @show_footer_subtotals.setter
    def show_footer_subtotals(self, v: bool):
        self._set_pref_bool("footer_subtotals", v)

    @property
    def outline_working_week(self) -> bool:
        """Lines down the left of Mondays and the right of Fridays."""
        return self._pref_bool("outline_working_week")

    @outline_working_week.setter
    def outline_working_week(self, v: bool):
        self._set_pref_bool("outline_working_week", v)

    @property
    def note_callouts(self) -> bool:
        """Notes in a popover on click and hover (otherwise in a tooltip)."""
        return self._pref_bool("note_callouts")

    @note_callouts.setter
    def note_callouts(self, v: bool):
        self._set_pref_bool("note_callouts", v)

    @property
    def iso_week_fallback(self) -> bool:
        return self._pref_bool("iso_week_fallback")

    @iso_week_fallback.setter
    def iso_week_fallback(self, v: bool):
        self._set_pref_bool("iso_week_fallback", v)

    @property
    def side_panel_shown(self) -> bool:
        return self._pref_bool("side_panel_shown")

    @side_panel_shown.setter
    def side_panel_shown(self, v: bool):
        self._set_pref_bool("side_panel_shown", v)

    @property
    def reopen_last(self) -> bool:
        return self._pref_bool("reopen_last")

    @reopen_last.setter
    def reopen_last(self, v: bool):
        self._set_pref_bool("reopen_last", v)

    @property
    def query(self) -> ProjectQuery:
        return self._query

    @query.setter
    def query(self, q: ProjectQuery):
        if q == self._query:
            return
        self._query = q
        c = self.config
        c.set("filter_programme", q.programme)
        c.set("filter_status", q.status.value)
        c.set("sort_key", q.sort.value)
        c.set("sort_ascending", q.ascending)
        c.set("group_by_programme", q.grouped)
        c.set("inactive_today_last", q.inactive_today_last)
        self.relayout()

    def set_search(self, text: str) -> None:
        self.query = self._query.but(search=text)

    @property
    def collapsed_programmes(self) -> set[str]:
        return set(self._collapsed)

    @collapsed_programmes.setter
    def collapsed_programmes(self, names: set[str]):
        self._collapsed = set(names)
        self.config.set("collapsed_programmes", sorted(self._collapsed))
        self.relayout()

    @property
    def hidden_columns(self) -> set[LeftColumn]:
        return set(self._hidden_columns)

    @property
    def cell_width(self) -> int:
        return self._cell_width

    @cell_width.setter
    def cell_width(self, v: int):
        v = int(min(max(v, CELL_WIDTH_MIN), CELL_WIDTH_MAX))
        if v != self._cell_width:
            self._cell_width = v
            self.config.set("cell_width", v)
            self.bump()

    def zoom(self, step: int) -> None:
        self.cell_width = self._cell_width + step

    @property
    def totals_scope(self) -> TotalsScope:
        return self._totals_scope

    @totals_scope.setter
    def totals_scope(self, s: TotalsScope):
        if s != self._totals_scope:
            self._totals_scope = s
            self.config.set("totals_scope", s.value)
            self.bump()

    @property
    def paste_mode(self) -> PasteMode:
        return self._paste_mode

    @paste_mode.setter
    def paste_mode(self, m: PasteMode):
        if m != self._paste_mode:
            self._paste_mode = m
            self.config.set("paste_mode", m.value)
            self.bump()

    @property
    def recent_workspaces(self) -> list[str]:
        return self.config.recent_workspaces

    def clear_recents(self) -> None:
        self.config.recent_workspaces = []
        self.bump()

    def forget_recent(self, path: str) -> None:
        self.config.recent_workspaces = [p for p in self.recent_workspaces if p != path]
        self.bump()

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    @property
    def window_title(self) -> str:
        return self.workspace.name if self.workspace else "QDVC Progress"

    def start_up(self) -> None:
        """Reopens the last workspace, if wanted and still there."""
        if self.workspace is not None or not self.reopen_last:
            return
        last = self.config.get("last_workspace")
        if isinstance(last, str) and os.path.isdir(last):
            try:
                self.open_workspace(last)
            except OpenError:
                pass

    def open_workspace(self, path: str) -> None:
        """Opens (or, for a folder that is not a workspace yet, starts) the
        workspace at ``path``. The window asks before starting one."""
        root = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(root):
            self.forget_recent(root)
            raise OpenError("Folder Not Found", f"{root} no longer exists.")
        self.flush_saves()
        ws = Workspace(root)
        try:
            ws.ensure_layout()
        except OSError as e:
            raise OpenError("Couldn\u2019t Open Workspace", str(e)) from None
        self.workspace = ws
        self.undo_manager.clear()
        self._selection = None
        self._load()
        self._reset_range()
        self.select_initial_cell()
        self.emit("scroll-to", self.today)
        recents = [p for p in self.recent_workspaces if p != root]
        self.config.recent_workspaces = [root] + recents
        self.config.set("last_workspace", root)
        self.bump()

    def close_workspace(self) -> None:
        self.flush_saves()
        self.workspace = None
        self.settings = WorkloadSettings()
        self.project_list = ProjectList()
        self.week_labels = WeekLabels()
        self.log = ProgressLog()
        self.issues = []
        self.save_error = None
        self._selection = None
        self.undo_manager.clear()
        self.config.set("last_workspace", None)
        self.relayout()

    def refresh(self) -> None:
        """Re-reads every file (after editing them elsewhere, or ``git pull``)."""
        if self.workspace is None:
            return
        self.flush_saves()
        self._load()
        self.undo_manager.clear()
        self.bump()

    def window_became_active(self) -> None:
        """The window got the focus back: notices a new day, and files
        changed by another app."""
        self.day_changed()
        if self.workspace is not None and self.workspace.has_external_changes():
            self.refresh()

    def window_left(self) -> None:
        self.flush_saves()

    def day_changed(self) -> None:
        now = self.clock()
        if now == self.today:
            return
        self.today = now
        # Which projects are inactive today may have changed.
        if self._query.inactive_today_last:
            self.relayout()
        else:
            self.bump()

    def _load(self) -> None:
        if self.workspace is None:
            return
        c = self.workspace.load()
        self.settings = c.settings
        self.project_list = c.projects
        self.week_labels = c.week_labels
        self.log = c.log
        self.issues = c.issues
        self.save_error = None
        if self._selection and self.project_list.project(self._selection.focus.project) is None:
            self._selection = None
        self._extend_range_to_cover_log()
        self.relayout()

    def dismiss_save_error(self) -> None:
        self.save_error = None
        self.bump()

    # ------------------------------------------------------------------
    # Date range
    # ------------------------------------------------------------------

    def date_at(self, day_index: int) -> Date:
        return add_days(self.range_start, day_index)

    def day_index(self, d: Date) -> int:
        return days_between(self.range_start, d)

    @property
    def range_end(self) -> Date:
        return add_days(self.range_start, self.day_count - 1)

    def _reset_range(self) -> None:
        """Eight weeks back to six months ahead of today, widened to the log."""
        start = monday(add_days(self.today, -56))
        end = add_days(self.today, 182)
        bounds = self.log.date_bounds
        if bounds:
            start = min(start, monday(bounds.start))
            end = max(end, bounds.end)
        self.range_start = start
        self.day_count = days_between(start, monday(end)) + 7

    def _extend_range_to_cover_log(self) -> None:
        bounds = self.log.date_bounds
        if bounds is None:
            return
        if bounds.start < self.range_start:
            self.extend_earlier_to(bounds.start)
        if bounds.end > self.range_end:
            self.extend_later_to(bounds.end)

    def extend_earlier(self, weeks: int = 12) -> None:
        self.range_start = add_days(self.range_start, -7 * weeks)
        self.day_count += 7 * weeks
        self.bump()

    def extend_later(self, weeks: int = 12) -> None:
        self.day_count += 7 * weeks
        self.bump()

    def extend_earlier_to(self, d: Date) -> None:
        if d < self.range_start:
            self.extend_earlier(days_between(monday(d), self.range_start) // 7 + 4)

    def extend_later_to(self, d: Date) -> None:
        if d > self.range_end:
            self.extend_later(days_between(self.range_end, d) // 7 + 4)

    def go_to_today(self) -> None:
        self.day_changed()
        self.emit("scroll-to", self.today)
        if self._selection:
            self.select(CellRef(self._selection.focus.project, self.today))
        else:
            self.select_initial_cell()
        self.emit("focus-grid")

    def go_to(self, d: Date) -> None:
        self.extend_earlier_to(d)
        self.extend_later_to(d)
        self.emit("scroll-to", d)
        if self._selection:
            self.select(CellRef(self._selection.focus.project, d))
        self.emit("focus-grid")

    def shift_weeks(self, n: int) -> None:
        """Moves by whole weeks, taking the selection with it."""
        base = self._selection.focus.date if self._selection else self.today
        self.go_to(add_days(base, 7 * n))

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def relayout(self) -> None:
        """Recomputes the rows after a change to the projects or the query."""
        self.last_worked = self.log.last_worked()
        self.rows, self.included_keys = layout_rows(
            self.project_list, self._query, self._collapsed, self.last_worked, self.today)
        self.included_set = set(self.included_keys)
        self._row_of_project = {r.key: i for i, r in enumerate(self.rows) if r.kind == "project"}
        self._project_rows = [i for i, r in enumerate(self.rows) if r.kind == "project"]
        self.group_of_project = {p.key: self.project_list.group(p)
                                 for p in self.project_list.projects}
        self.bump()

    def row_of(self, project: str) -> int | None:
        return self._row_of_project.get(project)

    @property
    def shown_project_keys(self) -> list[str]:
        """The project rows' keys, top to bottom (not those in collapsed
        programmes)."""
        return [self.rows[i].key for i in self._project_rows]

    def project(self, key: str) -> Project | None:
        return self.project_list.project(key)

    @property
    def visible_columns(self) -> list[LeftColumn]:
        return [c for c in LeftColumn if c is LeftColumn.TITLE or c not in self._hidden_columns]

    def column_width(self, c: LeftColumn) -> int:
        return self._column_widths.get(c, c.default_width)

    def set_column_width(self, c: LeftColumn, width: int) -> None:
        w = max(c.min_width, min(600, int(width)))
        if self._column_widths.get(c) != w:
            self._column_widths[c] = w
            self.config.set("column_widths", {k.value: v for k, v in self._column_widths.items()})
            self.bump()

    def reset_column_widths(self) -> None:
        self._column_widths = {}
        self.config.set("column_widths", {})
        self.bump()

    def is_column_shown(self, c: LeftColumn) -> bool:
        return c not in self._hidden_columns

    def set_column_shown(self, c: LeftColumn, shown: bool) -> None:
        if c is LeftColumn.TITLE or self.is_column_shown(c) == shown:
            return
        if shown:
            self._hidden_columns.discard(c)
        else:
            self._hidden_columns.add(c)
        self.config.set("hidden_columns", sorted(x.value for x in self._hidden_columns))
        self.bump()

    def toggle_programme(self, name: str) -> None:
        names = set(self._collapsed)
        names.symmetric_difference_update({name})
        self.collapsed_programmes = names

    def set_all_programmes(self, collapsed: bool) -> None:
        self.collapsed_programmes = set(self.project_list.programme_names + [""]) if collapsed else set()

    def set_sort(self, key: SortKey) -> None:
        """Sorts by ``key``; again reverses."""
        if self._query.sort == key:
            self.query = self._query.but(ascending=not self._query.ascending)
        else:
            self.query = self._query.but(sort=key, ascending=key.default_ascending)

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------

    def counts_in_totals(self, key: str) -> bool:
        return self._totals_scope is TotalsScope.ALL or key in self.included_set

    def day_total(self, d: Date) -> int:
        return self.log.total(d, self.settings, self.counts_in_totals)

    def span_total(self, start: Date, days: int) -> int:
        return self.log.total_over(DayRange(start, add_days(start, days - 1)), self.settings,
                                   self.counts_in_totals)

    def programme_total(self, programme: str, d: Date) -> int:
        """A programme heading's subtotal: its projects that pass the filter."""
        inc, groups = self.included_set, self.group_of_project
        return self.log.total(d, self.settings,
                              lambda k: k in inc and groups.get(k) == programme)

    @property
    def footer_programmes(self) -> list[str]:
        """The programmes with a subtotal row above the totals: those with at
        least one project that counts in the totals, in programme order, then
        No Programme (""). Empty when the rows are switched off."""
        if not self.show_footer_subtotals:
            return []
        counted = {self.project_list.group(p) for p in self.project_list.projects
                   if self.counts_in_totals(p.key)}
        return [n for n in self.project_list.programme_names + [""] if n in counted]

    def programme_footer_total(self, programme: str, d: Date) -> int:
        groups = self.group_of_project
        return self.log.total(d, self.settings,
                              lambda k: self.counts_in_totals(k) and groups.get(k) == programme)

    def week_label(self, d: Date) -> tuple[str, bool]:
        return self.week_labels.display(d, self.iso_week_fallback)

    def project_workload(self, key: str, days: int) -> int:
        """A project's total over the last ``days`` days, today included."""
        return self.log.total_over(DayRange(add_days(self.today, 1 - days), self.today),
                                   self.settings, lambda k: k == key)

    def entry_count(self, key: str) -> int:
        return len(self.log.entries_for(key))

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def _report_save_error(self, e: Exception) -> None:
        self.save_error = str(e)

    def _save_months_now(self, months) -> None:
        if self.workspace is None:
            return
        for m in sorted(months):
            self._pending_months.discard(m)
            try:
                self.workspace.save_month(m, self.log.entries_in(m))
            except (OSError, ws_mod.ProtectedFileError) as e:
                self._report_save_error(e)

    def _save_projects_now(self) -> None:
        if self.workspace is None:
            return
        self._pending_projects = False
        try:
            self.workspace.save_projects(self.project_list)
        except (OSError, ws_mod.ProtectedFileError) as e:
            self._report_save_error(e)

    def _save_week_labels_now(self) -> None:
        if self.workspace is None:
            return
        try:
            self.workspace.save_week_labels(self.week_labels)
        except (OSError, ws_mod.ProtectedFileError) as e:
            self._report_save_error(e)

    def _schedule_save(self) -> None:
        if self._save_handle is not None:
            self.scheduler.cancel(self._save_handle)

        def fire():
            self._save_handle = None
            self.flush_saves()
        self._save_handle = self.scheduler.call_later(SAVE_DELAY_MS, fire)

    def flush_saves(self) -> None:
        """Writes whatever typing is still waiting to be written."""
        if self._save_handle is not None:
            self.scheduler.cancel(self._save_handle)
            self._save_handle = None
        if self._pending_months:
            self._save_months_now(set(self._pending_months))
        if self._pending_projects:
            self._save_projects_now()

    @property
    def has_pending_saves(self) -> bool:
        return bool(self._pending_months) or self._pending_projects

    def end_editing_sessions(self) -> None:
        self.note_session = None
        self.project_session = None
        self.flush_saves()

    # ------------------------------------------------------------------
    # Settings (progress.yml)
    # ------------------------------------------------------------------

    def update_settings(self, change: Callable[[WorkloadSettings], None]) -> None:
        s = self.settings.copy()
        change(s)
        s.__post_init__()
        if s == self.settings:
            return
        self.settings = s
        if self.workspace is not None:
            try:
                self.workspace.save_settings(s)
            except (OSError, ws_mod.ProtectedFileError) as e:
                self._report_save_error(e)
        self.bump()

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def undo(self) -> str | None:
        self.flush_saves()
        return self.undo_manager.undo()

    def redo(self) -> str | None:
        self.flush_saves()
        return self.undo_manager.redo()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    @property
    def selection(self) -> GridSelection | None:
        return self._selection

    @selection.setter
    def selection(self, s: GridSelection | None):
        if s == self._selection:
            return
        old = self._selection
        self._selection = s
        if (s.focus if s else None) != (old.focus if old else None):
            self.end_editing_sessions()
        self.bump()

    @property
    def selection_bounds(self) -> tuple[range, range] | None:
        """The rows the selection spans (top to bottom) and its day indexes."""
        s = self._selection
        if s is None:
            return None
        r1, r2 = self.row_of(s.anchor.project), self.row_of(s.focus.project)
        if r1 is None or r2 is None:
            return None
        d1, d2 = self.day_index(s.anchor.date), self.day_index(s.focus.date)
        return range(min(r1, r2), max(r1, r2) + 1), range(min(d1, d2), max(d1, d2) + 1)

    @property
    def selected_refs(self) -> list[CellRef]:
        """Every selected cell, row by row."""
        b = self.selection_bounds
        if b is None:
            return []
        rows, days = b
        return [CellRef(self.rows[r].key, self.date_at(d))
                for r in rows if self.rows[r].kind == "project" for d in days]

    @property
    def selected_project_keys(self) -> list[str]:
        b = self.selection_bounds
        if b is None:
            return []
        return [self.rows[r].key for r in b[0] if self.rows[r].kind == "project"]

    @property
    def focus_ref(self) -> CellRef | None:
        s = self._selection
        if s is None or self.row_of(s.focus.project) is None:
            return None
        return s.focus

    @property
    def focused_project(self) -> Project | None:
        f = self.focus_ref
        return self.project(f.project) if f else None

    @property
    def has_selection(self) -> bool:
        return self.focus_ref is not None

    @property
    def is_single_selection(self) -> bool:
        return len(self.selected_refs) == 1

    def select(self, ref: CellRef, extend: bool = False) -> None:
        s = self._selection
        if extend and s is not None and self.row_of(s.anchor.project) is not None:
            self.selection = GridSelection(s.anchor, ref)
        else:
            self.selection = GridSelection(ref, ref)

    def select_initial_cell(self) -> None:
        keys = self.shown_project_keys
        if keys:
            self.select(CellRef(keys[0], self.today))

    def select_days(self, first: Date, last: Date, extend: bool = False) -> None:
        """Every shown project on a run of days (a column or week heading)."""
        keys = self.shown_project_keys
        if not keys:
            return
        s = self._selection
        start = s.anchor.date if (extend and s) else first
        self.selection = GridSelection(CellRef(keys[0], start), CellRef(keys[-1], last))

    def select_all(self) -> None:
        keys = self.shown_project_keys
        if keys:
            self.selection = GridSelection(CellRef(keys[0], self.range_start),
                                           CellRef(keys[-1], self.range_end))

    def collapse_selection(self) -> None:
        s = self._selection
        if s is not None:
            self.selection = GridSelection(s.focus, s.focus)

    def move_selection(self, d_rows: int, d_days: int, extend: bool = False) -> None:
        """Moves the focus by rows (skipping programme headings) and days."""
        focus = self.focus_ref
        if focus is None:
            self.select_initial_cell()
            return
        keys = self.shown_project_keys
        if focus.project not in keys:
            return
        i = keys.index(focus.project)
        j = min(max(i + d_rows, 0), len(keys) - 1)
        day = add_days(focus.date, d_days)
        if day < self.range_start:
            self.extend_earlier_to(day)
        if day > self.range_end:
            self.extend_later_to(day)
        day = max(self.range_start, min(day, self.range_end))
        self.select(CellRef(keys[j], day), extend)

    def select_project_row(self, key: str, extend: bool = False) -> None:
        """A click on a project's title: its cell on the selected day."""
        s = self._selection
        d = s.focus.date if s else self.today
        if extend and s is not None:
            self.selection = GridSelection(s.anchor, CellRef(key, d))
        else:
            self.select(CellRef(key, d))

    # ------------------------------------------------------------------
    # Cells
    # ------------------------------------------------------------------

    def cell(self, ref: CellRef) -> Cell:
        return self.log.get(ref.project, ref.date)

    def apply_cells(self, changes: dict[CellRef, Cell], action_name: str | None,
                    save_now: bool = True) -> None:
        """Writes ``changes``, saves the months they touch, and registers one
        undo step named ``action_name`` (none if None)."""
        if not changes:
            return
        previous: dict[CellRef, Cell] = {}
        months: set[MonthKey] = set()
        for ref, c in changes.items():
            previous[ref] = self.log.get(ref.project, ref.date)
            self.log.set(ref.project, ref.date, c)
            months.add(MonthKey.of(ref.date))
        if save_now:
            self._save_months_now(months)
        else:
            self._pending_months |= months
            self._schedule_save()
        if action_name:
            def undo():
                self.note_session = None
                self.apply_cells(previous, action_name)
            self.undo_manager.register(action_name, undo)
        self.last_worked = self.log.last_worked()
        self.bump()

    @property
    def focus_cell(self) -> Cell | None:
        f = self.focus_ref
        return self.cell(f) if f else None

    def common_selected_label(self) -> tuple[bool, CellLabel | None]:
        """(True, label) when every selected cell has the same label (None
        for no label); (False, None) when they differ or nothing is selected."""
        refs = self.selected_refs
        if not refs:
            return False, None
        first = self.cell(refs[0]).label
        if all(self.cell(r).label == first for r in refs):
            return True, first
        return False, None

    def selection_workload(self) -> int:
        return sum(self.settings.value(self.cell(r).label) for r in self.selected_refs)

    def set_label(self, label: CellLabel | None) -> None:
        refs = self.selected_refs
        if not refs:
            return
        changes = {r: self.cell(r).with_label(label) for r in refs}
        self.apply_cells(changes, f"Set {label.title}" if label else "Clear Label")

    def clear_notes(self) -> None:
        changes = {r: self.cell(r).with_note("") for r in self.selected_refs if self.cell(r).has_note}
        self.apply_cells(changes, "Clear Note")

    def clear_cells(self) -> None:
        changes = {r: EMPTY_CELL for r in self.selected_refs if not self.cell(r).is_empty}
        self.apply_cells(changes, "Clear")

    def set_note(self, text: str, ref: CellRef) -> None:
        """Typing a note. One undo step per cell per visit; written after a pause."""
        c = self.cell(ref)
        if c.note == text:
            return
        c = c.with_note(text)
        if self.note_session == ref:
            self.apply_cells({ref: c}, None, save_now=False)
        else:
            self.note_session = ref
            self.apply_cells({ref: c}, "Edit Note", save_now=False)

    # --- inactive days ------------------------------------------------

    @property
    def selection_is_inactive(self) -> bool:
        """Whether every selected cell is on an inactive day."""
        refs = self.selected_refs
        if not refs:
            return False
        for r in refs:
            p = self.project(r.project)
            if p is None or not p.is_inactive(r.date):
                return False
        return True

    def set_selection_inactive(self, inactive: bool) -> None:
        by_project: dict[str, list[Date]] = {}
        for r in self.selected_refs:
            by_project.setdefault(r.project, []).append(r.date)
        if not by_project:
            return

        def change(plist: ProjectList):
            for key, days in by_project.items():
                i = plist.index(key)
                if i is not None:
                    plist.projects[i].set_inactive(inactive, days)
        self.update_projects("Mark Inactive" if inactive else "Mark Active", change)

    def toggle_selection_inactive(self) -> None:
        self.set_selection_inactive(not self.selection_is_inactive)

    # --- copy and paste -----------------------------------------------

    def selection_clip(self) -> CellClip | None:
        """The selection as a clip (the rectangle's rows of project cells)."""
        b = self.selection_bounds
        if b is None:
            return None
        rows, days = b
        out = [[self.cell(CellRef(self.rows[r].key, self.date_at(d))) for d in days]
               for r in rows if self.rows[r].kind == "project"]
        return CellClip(out) if out else None

    def cut_cells(self) -> None:
        """Clears what Cut takes (after the window has copied the clip): the
        parts of each cell the paste mode covers."""
        changes = {}
        for r in self.selected_refs:
            c = self._paste_mode.apply(EMPTY_CELL, self.cell(r))
            if c != self.cell(r):
                changes[r] = c
        self.apply_cells(changes, "Cut")

    def paste(self, clip: CellClip, mode: PasteMode | None = None) -> None:
        """Pastes ``clip`` at the selection. A single copied cell fills the
        whole selection; a block is pasted from the selection's top-left
        corner. ``mode`` (default: the paste mode) decides whether labels,
        notes or both are written."""
        mode = mode or self._paste_mode
        b = self.selection_bounds
        if b is None or clip.height == 0:
            return
        rows, days = b
        changes: dict[CellRef, Cell] = {}
        if clip.is_single_cell:
            source = clip.cell(0, 0)
            for r in self.selected_refs:
                changes[r] = mode.apply(source, self.cell(r))
        else:
            project_rows = [r for r in rows if self.rows[r].kind == "project"]
            all_keys = self.shown_project_keys
            if not project_rows:
                return
            first_key = self.rows[project_rows[0]].key
            start = all_keys.index(first_key)
            for r in range(clip.height):
                if start + r >= len(all_keys):
                    break
                key = all_keys[start + r]
                for c in range(clip.width):
                    day = self.date_at(days.start + c)
                    if day > self.range_end:
                        self.extend_later_to(day)
                    ref = CellRef(key, day)
                    changes[ref] = mode.apply(clip.cell(r, c), self.cell(ref))
            last_key = all_keys[min(start + clip.height, len(all_keys)) - 1]
            self.selection = GridSelection(
                CellRef(first_key, self.date_at(days.start)),
                CellRef(last_key, self.date_at(days.start + clip.width - 1)))
        changes = {k: v for k, v in changes.items() if v != self.cell(k)}
        self.apply_cells(changes, "Paste")

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def update_projects(self, action_name: str | None, change: Callable[[ProjectList], None],
                        debounce: bool = False) -> None:
        """Changes the project list, writes projects.yml (after a pause when
        ``debounce``), and registers one undo step named ``action_name``."""
        plist = self.project_list.copy()
        change(plist)
        if plist == self.project_list:
            return
        self.replace_projects(plist, action_name=action_name, debounce=debounce)

    def replace_projects(self, plist: ProjectList, cells: dict[CellRef, Cell] | None = None,
                         action_name: str | None = None, debounce: bool = False) -> None:
        """Replaces the list (and, for Delete Project and its undo, some cells
        with it), as one undo step."""
        cells = cells or {}
        previous = self.project_list
        previous_cells = {r: self.log.get(r.project, r.date) for r in cells}
        self.project_list = plist
        if cells:
            self.apply_cells(cells, None)
        if debounce:
            self._pending_projects = True
            self._schedule_save()
        else:
            self._save_projects_now()
        if action_name:
            def undo():
                self.project_session = None
                self.replace_projects(previous, previous_cells, action_name)
            self.undo_manager.register(action_name, undo)
        if self._selection and self.row_of(self._selection.focus.project) is None \
                and plist.project(self._selection.focus.project) is None:
            self._selection = None
        self.relayout()

    def edit_project(self, key: str, field: str, change: Callable[[Project], None]) -> None:
        """Typing in one of a project's fields. One undo step per field per
        visit; written after a pause."""
        i = self.project_list.index(key)
        if i is None:
            return
        session = f"{key}/{field}"
        name = None if self.project_session == session else "Edit Project"
        before = self.project_list.projects[i]
        plist = self.project_list.copy()
        change(plist.projects[i])
        if plist.projects[i] == before:
            return
        self.project_session = session
        self.replace_projects(plist, action_name=name, debounce=True)

    def set_project_active(self, key: str, active: bool) -> None:
        def change(plist):
            i = plist.index(key)
            if i is not None:
                plist.projects[i].is_active = active
        self.update_projects("Mark Project Active" if active else "Mark Project Inactive", change)

    def set_programme(self, programme: str, key: str) -> None:
        def change(plist):
            i = plist.index(key)
            if i is not None:
                plist.projects[i].programme = programme
        self.update_projects("Move to Programme", change)

    def new_project_problem(self, title: str, code: str) -> str | None:
        if not title.strip():
            return "Enter a title."
        other = self.project_list.project_with_code(code)
        if other is not None:
            return (f"\u201c{other.title}\u201d already has the ID {other.code}. "
                    "Each ID can be used once.")
        return None

    def add_project(self, title: str, code: str = "", programme: str = "", target: str = "",
                    collaborators: str = "") -> str | None:
        """Adds a project and selects it on the focused day (or today).
        Returns its key, or None if the title is empty or the ID taken."""
        t = title.strip()
        if not t or self.project_list.project_with_code(code) is not None:
            return None
        if programme and programme not in self.project_list.programme_names:
            programme = ""
        key = self.project_list.new_key(t)
        p = Project(key=key, title=t, code=code.strip(), programme=programme,
                    target=target.strip(), collaborators=collaborators.strip())

        def change(plist: ProjectList):
            # After the last project of the same programme, so the file keeps
            # programmes together.
            last = None
            for i, q in enumerate(plist.projects):
                if plist.group(q) == programme:
                    last = i
            if last is None:
                plist.projects.append(p)
            else:
                plist.projects.insert(last + 1, p)
        self.update_projects("New Project", change)
        q = self._query
        if not q.status.includes(p) or (q.programme is not None and q.programme != programme) \
                or q.search:
            self.query = q.but(status=StatusFilter.ACTIVE, programme=None, search="")
        if programme in self._collapsed:
            self.collapsed_programmes = self._collapsed - {programme}
        d = self._selection.focus.date if self._selection else self.today
        self.select(CellRef(key, d))
        self.inspector_tab = "project"
        self.bump()
        return key

    def delete_project(self, key: str) -> None:
        """Removes the project and its log rows, as one undo step."""
        plist = self.project_list.copy()
        plist.projects = [p for p in plist.projects if p.key != key]
        cells = {CellRef(key, e.date): EMPTY_CELL for e in self.log.entries_for(key)}
        s = self._selection
        if s and (s.focus.project == key or s.anchor.project == key):
            self._selection = None
        self.replace_projects(plist, cells, "Delete Project")

    def move_project(self, key: str | None, offset: int) -> None:
        """Moves the project up or down in the manual order, among the
        projects of its own programme when grouped."""
        key = key or (self.focus_ref.project if self.focus_ref else None)
        if key is None:
            return
        target = self._move_target(key, offset)
        if target is None:
            return

        def change(plist: ProjectList):
            i = plist.index(key)
            if i is not None:
                p = plist.projects.pop(i)
                plist.projects.insert(target, p)
        self.update_projects("Move Up" if offset < 0 else "Move Down", change)
        if self._query.sort is not SortKey.MANUAL:
            self.query = self._query.but(sort=SortKey.MANUAL, ascending=True)

    def can_move_project(self, key: str | None, offset: int) -> bool:
        key = key or (self.focus_ref.project if self.focus_ref else None)
        return key is not None and self._move_target(key, offset) is not None

    def _move_target(self, key: str, offset: int) -> int | None:
        """The index the project moves to: past the neighbouring project in
        the same programme (when grouped) that the filter shows."""
        plist = self.project_list
        i = plist.index(key)
        if i is None:
            return None
        p = plist.projects[i]
        group = plist.group(p)
        paused = p.is_inactive(self.today)
        q = self._query
        j = i + offset
        while 0 <= j < len(plist.projects):
            other = plist.projects[j]
            # With inactive-today projects clustered last, move within the cluster.
            same_cluster = not q.inactive_today_last or other.is_inactive(self.today) == paused
            if (not q.grouped or plist.group(other) == group) and same_cluster \
                    and q.includes(other, plist):
                return j
            j += offset
        return None

    # --- inactive periods -----------------------------------------------

    def set_period_label(self, key: str, period_id: str, label: str) -> None:
        def change(p: Project):
            for period in p.inactive_periods:
                if period.id == period_id:
                    period.label = label
        self.edit_project(key, f"period-{period_id}", change)

    def set_period_range(self, key: str, period_id: str, start: Date, end: Date) -> None:
        def change(plist: ProjectList):
            i = plist.index(key)
            if i is None:
                return
            p = plist.projects[i]
            for period in p.inactive_periods:
                if period.id == period_id:
                    period.range = DayRange(start, end)
            p.inactive_periods = merged(p.inactive_periods)
        self.update_projects("Change Inactive Period", change)

    def add_period(self, key: str, start: Date) -> None:
        def change(plist: ProjectList):
            i = plist.index(key)
            if i is None:
                return
            p = plist.projects[i]
            p.inactive_periods = merged(p.inactive_periods + [
                InactivePeriod(DayRange(start, add_days(start, 6)))])
        self.update_projects("Add Inactive Period", change)

    def remove_period(self, key: str, period_id: str) -> None:
        def change(plist: ProjectList):
            i = plist.index(key)
            if i is not None:
                p = plist.projects[i]
                p.inactive_periods = [x for x in p.inactive_periods if x.id != period_id]
        self.update_projects("Remove Inactive Period", change)

    # ------------------------------------------------------------------
    # Programmes
    # ------------------------------------------------------------------

    def programme_name_problem(self, name: str, renaming: str | None = None) -> str | None:
        """Why ``name`` cannot be used, or None if it can."""
        n = name.strip()
        if not n:
            return "Enter a name."
        if n == NO_PROGRAMME_TITLE:
            return f"\u201c{n}\u201d is reserved."
        if n != renaming and n in self.project_list.programme_names:
            return f"There is already a programme called \u201c{n}\u201d."
        return None

    def new_programme(self, name: str, assign_to: str | None = None) -> None:
        n = name.strip()
        if self.programme_name_problem(n) is not None:
            return

        def change(plist: ProjectList):
            plist.programmes.append(Programme(n))
            if assign_to is not None:
                i = plist.index(assign_to)
                if i is not None:
                    plist.projects[i].programme = n
        self.update_projects("New Programme", change)

    def rename_programme(self, original: str, name: str) -> None:
        n = name.strip()
        if self.programme_name_problem(n, original) is not None or n == original:
            return

        def change(plist: ProjectList):
            for prog in plist.programmes:
                if prog.name == original:
                    prog.name = n
            for p in plist.projects:
                if p.programme == original:
                    p.programme = n
        self.update_projects("Rename Programme", change)
        if original in self._collapsed:
            self.collapsed_programmes = (self._collapsed - {original}) | {n}
        if self._query.programme == original:
            self.query = self._query.but(programme=n)

    def delete_programme(self, name: str) -> None:
        """Removes the programme; its projects move to No Programme."""
        if not name:
            return

        def change(plist: ProjectList):
            plist.programmes = [p for p in plist.programmes if p.name != name]
            for p in plist.projects:
                if p.programme == name:
                    p.programme = ""
        self.update_projects("Delete Programme", change)
        if self._query.programme == name:
            self.query = self._query.but(programme=None)

    def move_programme(self, name: str, offset: int) -> None:
        names = self.project_list.programme_names
        if name not in names:
            return
        i = names.index(name)
        j = i + offset
        if not 0 <= j < len(names):
            return

        def change(plist: ProjectList):
            plist.programmes[i], plist.programmes[j] = plist.programmes[j], plist.programmes[i]
        self.update_projects("Move Programme Up" if offset < 0 else "Move Programme Down", change)

    def can_move_programme(self, name: str, offset: int) -> bool:
        names = self.project_list.programme_names
        return name in names and 0 <= names.index(name) + offset < len(names)

    def project_count(self, programme: str) -> int:
        return sum(1 for p in self.project_list.projects if self.project_list.group(p) == programme)

    # ------------------------------------------------------------------
    # Week labels
    # ------------------------------------------------------------------

    def replace_week_labels(self, labels: WeekLabels, action_name: str) -> None:
        if labels == self.week_labels:
            return
        previous = self.week_labels
        self.week_labels = labels
        self._save_week_labels_now()
        self.undo_manager.register(action_name,
                                   lambda: self.replace_week_labels(previous, action_name))
        self.bump()

    def set_week_label(self, text: str, week: Date) -> None:
        labels = self.week_labels.copy()
        labels.set(week, text)
        self.replace_week_labels(labels, "Edit Week Label")

    def import_week_labels(self, imported: dict[Date, str], replacing_all: bool) -> None:
        """Applies labels pasted from a spreadsheet, on top of the existing
        ones or instead of them."""
        labels = WeekLabels() if replacing_all else self.week_labels.copy()
        for week, text in imported.items():
            labels.set(week, text)
        self.replace_week_labels(labels, "Import Week Labels")
