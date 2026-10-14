"""The filter, search and sort that decide which rows the grid shows."""

from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum

from .dates import Date, today as _today
from .models import Project, ProjectList


class StatusFilter(Enum):
    """Which projects the Status filter shows (the project-level active flag)."""

    ACTIVE = "active"
    ALL = "all"
    INACTIVE = "inactive"

    @property
    def title(self) -> str:
        return {StatusFilter.ACTIVE: "Active Projects", StatusFilter.ALL: "All Projects",
                StatusFilter.INACTIVE: "Inactive Projects"}[self]

    def includes(self, p: Project) -> bool:
        if self is StatusFilter.ACTIVE:
            return p.is_active
        if self is StatusFilter.INACTIVE:
            return not p.is_active
        return True


class SortKey(Enum):
    MANUAL = "manual"          # the order of projects.yml (Move Up / Move Down)
    TITLE = "title"
    CODE = "code"
    TARGET = "target"
    COLLABORATORS = "collaborators"
    LAST_WORKED = "lastWorked"

    @property
    def title(self) -> str:
        return {SortKey.MANUAL: "Manual Order", SortKey.TITLE: "Title", SortKey.CODE: "ID",
                SortKey.TARGET: "Target", SortKey.COLLABORATORS: "Collaborators",
                SortKey.LAST_WORKED: "Last Worked On"}[self]

    @property
    def default_ascending(self) -> bool:
        """Most recent first for Last Worked On, A to Z otherwise."""
        return self is not SortKey.LAST_WORKED


@dataclass(frozen=True)
class ProjectQuery:
    #: None shows every programme; "" shows only projects with none.
    programme: str | None = None
    status: StatusFilter = StatusFilter.ACTIVE
    search: str = ""
    sort: SortKey = SortKey.MANUAL
    ascending: bool = True
    #: Show projects under programme headings (otherwise one flat list).
    grouped: bool = True
    #: Within each programme (or the flat list), put the projects that are
    #: inactive today (an inactive period covers today) after the others.
    inactive_today_last: bool = False

    def but(self, **changes) -> "ProjectQuery":
        return replace(self, **changes)

    def includes(self, p: Project, plist: ProjectList) -> bool:
        if self.programme is not None and plist.group(p) != self.programme:
            return False
        if not self.status.includes(p):
            return False
        terms = self.search.lower().split()
        if terms:
            haystack = p.search_text
            if any(t not in haystack for t in terms):
                return False
        return True


@dataclass(frozen=True)
class LayoutRow:
    """A row of the grid: a programme heading ("" for No Programme, with the
    number of projects under it that pass the filter) or a project."""

    kind: str                      # "programme" or "project"
    name: str = ""                 # programme name
    count: int = 0
    collapsed: bool = False
    key: str = ""                  # project key

    @staticmethod
    def programme_row(name: str, count: int, collapsed: bool) -> "LayoutRow":
        return LayoutRow("programme", name=name, count=count, collapsed=collapsed)

    @staticmethod
    def project_row(key: str) -> "LayoutRow":
        return LayoutRow("project", key=key)

    @property
    def project_key(self) -> str | None:
        return self.key if self.kind == "project" else None

    @property
    def is_programme(self) -> bool:
        return self.kind == "programme"


_DIGITS = re.compile(r"(\d+)")


def _natural_key(s: str):
    """A Finder/Files-like sort key: case and accents ignored, runs of
    digits compared as numbers."""
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", s)
                     if not unicodedata.combining(ch)).casefold()
    return [(0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in _DIGITS.split(folded) if part]


def _natural_compare(x: str, y: str) -> int:
    a, b = _natural_key(x), _natural_key(y)
    return (a > b) - (a < b)


def layout_rows(plist: ProjectList, query: ProjectQuery, collapsed: set[str],
                last_worked: dict[str, Date], today: Date | None = None):
    """The grid's rows for ``query``, and the keys of every project that
    passes the filter (including those in collapsed programmes), in row
    order. ``today`` decides which projects are inactive today."""
    today = today or _today()
    order = {p.key: i for i, p in enumerate(plist.projects)}
    matching = [p for p in plist.projects if query.includes(p, plist)]
    ordered = sort_projects(matching, query.sort, query.ascending, order, last_worked)
    if query.inactive_today_last:
        ordered = ([p for p in ordered if not p.is_inactive(today)]
                   + [p for p in ordered if p.is_inactive(today)])
    if not query.grouped:
        return [LayoutRow.project_row(p.key) for p in ordered], [p.key for p in ordered]
    rows: list[LayoutRow] = []
    included: list[str] = []
    for name in plist.programme_names + [""]:
        members = [p for p in ordered if plist.group(p) == name]
        if not members:
            continue
        is_collapsed = name in collapsed
        rows.append(LayoutRow.programme_row(name, len(members), is_collapsed))
        included.extend(p.key for p in members)
        if not is_collapsed:
            rows.extend(LayoutRow.project_row(p.key) for p in members)
    return rows, included


def sort_projects(projects: list[Project], key: SortKey, ascending: bool,
                  order: dict[str, int], last_worked: dict[str, Date]) -> list[Project]:
    def manual(a: Project, b: Project) -> int:
        x, y = order.get(a.key, 0), order.get(b.key, 0)
        return (x > y) - (x < y)

    if key is SortKey.MANUAL:
        out = sorted(projects, key=lambda p: order.get(p.key, 0))
        return out if ascending else list(reversed(out))

    if key is SortKey.LAST_WORKED:
        def cmp(a: Project, b: Project) -> int:
            x, y = last_worked.get(a.key), last_worked.get(b.key)
            if x is not None and y is not None and x != y:
                return (-1 if x < y else 1) if ascending else (-1 if x > y else 1)
            if x is None and y is not None:
                return 1
            if x is not None and y is None:
                return -1
            return manual(a, b)
        return sorted(projects, key=functools.cmp_to_key(cmp))

    attr = {SortKey.TITLE: "title", SortKey.CODE: "code", SortKey.TARGET: "target",
            SortKey.COLLABORATORS: "collaborators"}[key]

    def cmp_text(a: Project, b: Project) -> int:
        x, y = getattr(a, attr), getattr(b, attr)
        # Empty values go last whichever the direction.
        if (not x) != (not y):
            return -1 if x else 1
        r = _natural_compare(x, y)
        if r == 0:
            return manual(a, b)
        return r if ascending else -r

    return sorted(projects, key=functools.cmp_to_key(cmp_text))
