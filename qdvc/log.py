"""The log: every non-empty cell, by day and project key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .dates import Date, DayRange, MonthKey
from .labels import EMPTY_CELL, Cell
from .settings import WorkloadSettings


@dataclass(frozen=True)
class LogEntry:
    """One entry of the log: a project's cell on a day."""

    date: Date
    project: str
    cell: Cell


def _all(_key: str) -> bool:
    return True


class ProgressLog:
    """Every non-empty cell, by day and project key. Empty cells are never
    stored."""

    def __init__(self, entries=()):
        self.by_date: dict[Date, dict[str, Cell]] = {}
        for e in entries:
            self.set(e.project, e.date, e.cell)

    def __eq__(self, other):
        return isinstance(other, ProgressLog) and self.by_date == other.by_date

    def get(self, project: str, d: Date) -> Cell:
        day = self.by_date.get(d)
        return day.get(project, EMPTY_CELL) if day else EMPTY_CELL

    def set(self, project: str, d: Date, cell: Cell) -> None:
        if cell.is_empty:
            day = self.by_date.get(d)
            if day is not None:
                day.pop(project, None)
                if not day:
                    del self.by_date[d]
        else:
            self.by_date.setdefault(d, {})[project] = cell

    def cells_on(self, d: Date) -> dict[str, Cell]:
        return self.by_date.get(d, {})

    @property
    def is_empty(self) -> bool:
        return not self.by_date

    @property
    def entry_count(self) -> int:
        return sum(len(v) for v in self.by_date.values())

    @property
    def date_bounds(self) -> DayRange | None:
        """The first and last days with an entry."""
        if not self.by_date:
            return None
        return DayRange(min(self.by_date), max(self.by_date))

    @property
    def months(self) -> set[MonthKey]:
        return {MonthKey.of(d) for d in self.by_date}

    def entries_in(self, month: MonthKey) -> list[LogEntry]:
        """The month's entries, by date, then project key (the order of the
        month's log file)."""
        out = [LogEntry(d, k, c) for d, cells in self.by_date.items()
               if d.year == month.year and d.month == month.month
               for k, c in cells.items()]
        out.sort(key=lambda e: (e.date, e.project))
        return out

    def entries_for(self, project: str) -> list[LogEntry]:
        """All entries of one project, by date."""
        out = [LogEntry(d, project, cells[project])
               for d, cells in self.by_date.items() if project in cells]
        out.sort(key=lambda e: e.date)
        return out

    def total(self, d: Date, settings: WorkloadSettings,
              includes: Callable[[str], bool] = _all) -> int:
        """The workload on ``d``: the sum of the label values of the projects
        ``includes`` accepts."""
        cells = self.by_date.get(d)
        if not cells:
            return 0
        return sum(settings.value(c.label) for k, c in cells.items() if includes(k))

    def total_over(self, r: DayRange, settings: WorkloadSettings,
                   includes: Callable[[str], bool] = _all) -> int:
        return sum(self.total(d, settings, includes) for d in r.days)

    def last_worked(self) -> dict[str, Date]:
        """The last day each project had work or a meeting logged (not
        counting due dates, plans or emblems), by project key."""
        from .labels import CellLabel
        out: dict[str, Date] = {}
        for d, cells in self.by_date.items():
            for k, c in cells.items():
                if c.label is None or not (c.label.is_size or c.label is CellLabel.MEETING):
                    continue
                if k in out and out[k] >= d:
                    continue
                out[k] = d
        return out


def heat_level(total: int, peak: int) -> float:
    """The colour depth (0…1) of a total, given the total at which it peaks."""
    if total <= 0 or peak <= 0:
        return 0.0
    return min(1.0, total / peak)
