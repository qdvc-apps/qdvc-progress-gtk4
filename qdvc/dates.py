"""Calendar days with no time zone, months and runs of days.

A day is a plain ``datetime.date`` (a ``yyyy-mm-dd`` in a diary, as stored in
the workspace files). Weeks run Monday to Sunday throughout the app.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

Date = _dt.date

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_iso(text: str) -> Date | None:
    """``yyyy-mm-dd`` (surrounding whitespace allowed), or None."""
    m = _ISO.match(text.strip())
    if not m:
        return None
    try:
        return Date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def today() -> Date:
    return Date.today()


def add_days(d: Date, n: int) -> Date:
    return d + _dt.timedelta(days=n)


def days_between(a: Date, b: Date) -> int:
    """Whole days from ``a`` to ``b`` (negative if ``b`` is earlier)."""
    return b.toordinal() - a.toordinal()


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (Date(year, month + 1, 1) - Date(year, month, 1)).days


def add_months(d: Date, months: int) -> Date:
    """The same day of the month ``months`` later, clamped to the month's
    length (31 January + 1 month is 28 or 29 February)."""
    y, m = divmod(d.year * 12 + (d.month - 1) + months, 12)
    return Date(y, m + 1, min(d.day, days_in_month(y, m + 1)))


def is_weekend(d: Date) -> bool:
    return d.isoweekday() >= 6


def monday(d: Date) -> Date:
    """The Monday of the week containing ``d``."""
    return add_days(d, 1 - d.isoweekday())


def iso_week(d: Date) -> int:
    """The ISO 8601 week number (1…53)."""
    return d.isocalendar()[1]


def from_unix_days(n: int) -> Date:
    """The day ``n`` days after 1970-01-01."""
    return add_days(Date(1970, 1, 1), n)


@dataclass(frozen=True, order=True)
class MonthKey:
    """A calendar month, as used to name log files (``log/2026/2026-10.csv``)."""

    year: int
    month: int

    @staticmethod
    def parse(text: str) -> "MonthKey | None":
        """``yyyy-mm`` exactly."""
        m = _MONTH.match(text)
        if not m:
            return None
        y, mo = int(m.group(1)), int(m.group(2))
        return MonthKey(y, mo) if 1 <= mo <= 12 else None

    @staticmethod
    def of(d: Date) -> "MonthKey":
        return MonthKey(d.year, d.month)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def first_day(self) -> Date:
        return Date(self.year, self.month, 1)

    @property
    def last_day(self) -> Date:
        return Date(self.year, self.month, days_in_month(self.year, self.month))


@dataclass(frozen=True)
class DayRange:
    """An inclusive run of days; ``start`` is never after ``end``."""

    start: Date
    end: Date

    def __post_init__(self):
        if self.start > self.end:
            start, end = self.end, self.start
            object.__setattr__(self, "start", start)
            object.__setattr__(self, "end", end)

    def contains(self, d: Date) -> bool:
        return self.start <= d <= self.end

    @property
    def day_count(self) -> int:
        return days_between(self.start, self.end) + 1

    @property
    def days(self) -> list[Date]:
        return [add_days(self.start, i) for i in range(self.day_count)]

    def overlaps_or_touches(self, other: "DayRange") -> bool:
        return (self.start.toordinal() <= other.end.toordinal() + 1
                and other.start.toordinal() <= self.end.toordinal() + 1)
