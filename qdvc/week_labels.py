"""Week labels (``week-labels.csv``), and reading them from rows pasted from
a spreadsheet: a date in the week (any day, in most formats people type)
and the label."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from . import csvio
from .dates import Date, days_between, from_unix_days, iso_week, monday, parse_iso

HEADER = ["week", "label"]


def one_line(s: str) -> str:
    return " ".join(part for part in s.splitlines() if part)


class WeekLabels:
    """The custom label of each week, keyed by the week's Monday. Weeks
    without a label show their ISO week number."""

    def __init__(self, labels: dict[Date, str] | None = None):
        self.labels: dict[Date, str] = {}
        for week, label in (labels or {}).items():
            self.set(week, label)

    def __eq__(self, other):
        return isinstance(other, WeekLabels) and self.labels == other.labels

    def copy(self) -> "WeekLabels":
        w = WeekLabels()
        w.labels = dict(self.labels)
        return w

    def get(self, day: Date) -> str | None:
        """The label of the week containing ``day``."""
        return self.labels.get(monday(day))

    def set(self, day: Date, text: str | None) -> None:
        """Sets the label of the week containing ``day``; empty removes it."""
        t = (text or "").strip()
        if t:
            self.labels[monday(day)] = one_line(t)
        else:
            self.labels.pop(monday(day), None)

    def __len__(self) -> int:
        return len(self.labels)

    @property
    def is_empty(self) -> bool:
        return not self.labels

    def sorted(self) -> list[tuple[Date, str]]:
        """Every labelled week, earliest first."""
        return sorted(self.labels.items())

    def display(self, day: Date, iso_fallback: bool) -> tuple[str, bool]:
        """What the header shows for the week containing ``day``: its label
        (True), or ``W41`` when it has none and ``iso_fallback`` is on."""
        label = self.get(day)
        if label is not None:
            return label, True
        return (f"W{iso_week(day)}" if iso_fallback else ""), False

    @staticmethod
    def parse_file(text: str) -> tuple["WeekLabels", list[str]]:
        """Reads ``week-labels.csv``. Rows whose week is not a date are
        reported in the problems (by line) and skipped."""
        out = WeekLabels()
        problems: list[str] = []
        for i, row in enumerate(csvio.parse(text)):
            if not row:
                continue
            first = row[0]
            if i == 0 and first.strip().lower() == "week":
                continue
            week = parse_iso(first)
            if week is None:
                problems.append(f"line {i + 1}: \u201c{first}\u201d is not a yyyy-mm-dd date")
                continue
            out.set(week, row[1] if len(row) > 1 else "")
        return out, problems

    def render_file(self) -> str:
        return csvio.render([HEADER] + [[w.isoformat(), label] for w, label in self.sorted()])


class DateOrder(Enum):
    """Whether a date like 5/10/2026 means 5 October (day first) or 10 May."""

    DAY_MONTH = "dayMonth"
    MONTH_DAY = "monthDay"

    @property
    def title(self) -> str:
        return {DateOrder.DAY_MONTH: "Day/Month (5/10 = 5 Oct)",
                DateOrder.MONTH_DAY: "Month/Day (10/5 = 5 Oct)"}[self]


_MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_FULL = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]
_WEEKDAYS = {"mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
             "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_IGNORABLE = {"week", "wk", "of", "w", "c", "wc", "beginning", "commencing", "starting",
              "from", "the"}
_SERIAL = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _is_month_word(token: str, index: int) -> bool:
    """"oct", "october" and "sept" are months; "octopus" is not."""
    return _MONTH_FULL[index].startswith(token) or token == "sept"


def _year(s: str) -> int | None:
    if not s.isdigit():
        return None
    if len(s) == 4:
        return int(s)
    if len(s) == 2:
        return 2000 + int(s)
    return None


def parse_flexible_date(text: str, order: DateOrder, default_year: int) -> tuple[Date, bool] | None:
    """Parses a date as people type them in spreadsheets: ``2026-10-05``
    (also with ``/`` or ``.``, or followed by a time), ``5/10/2026``,
    ``5/10/26`` and ``5/10`` in ``order``, ``5 Oct 2026``, ``Monday, 5th
    October``, ``Oct 5, 2026``, and spreadsheet serial numbers (45935). A
    missing year is ``default_year``. Returns the date and whether the text
    had a year."""
    t = text.strip()
    if not t:
        return None

    # A spreadsheet serial number (days since 1899-12-30).
    if _SERIAL.match(t) and "/" not in t:
        serial = float(t)
        if 20000 <= serial < 80000:
            return from_unix_days(int(serial) - 25569), True

    # An ISO date followed by a time.
    if len(t) > 10:
        first = next((i for i, ch in enumerate(t) if ch in " T"), None)
        if first == 10:
            t = t[:10]

    # Tokens: runs of digits, runs of letters; everything else separates.
    tokens: list[str] = []
    current = ""
    current_is_digit = False
    for ch in t.lower():
        is_digit = ch.isascii() and ch.isdigit()
        if is_digit or ch.isalpha():
            if current and is_digit != current_is_digit:
                tokens.append(current)
                current = ""
            current += ch
            current_is_digit = is_digit
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)

    numbers: list[str] = []
    month: int | None = None
    last_was_number = False
    for token in tokens:
        if token[0].isascii() and token[0].isdigit():
            numbers.append(token)
            last_was_number = True
            continue
        if last_was_number and token in ("st", "nd", "rd", "th"):   # the "th" of "5th"
            last_was_number = False
            continue
        last_was_number = False
        m = next((i for i, name in enumerate(_MONTH_NAMES) if token.startswith(name)), None) \
            if len(token) >= 3 else None
        if m is not None and _is_month_word(token, m):
            if month is not None:
                return None
            month = m + 1
        elif token in _WEEKDAYS or token in _IGNORABLE:
            continue
        else:
            return None

    def make(y: int, mo: int, d: int) -> Date | None:
        try:
            return Date(y, mo, d)
        except ValueError:
            return None

    if month is not None:
        # 5 Oct 2026, Oct 5 2026, 5 Oct.
        if not 1 <= len(numbers) <= 2:
            return None
        day = y = None
        for n in numbers:
            if len(n) == 4 or (day is not None and y is None):
                v = _year(n)
                if v is None:
                    return None
                y = v
            else:
                if day is not None:
                    return None
                day = int(n)
        if day is None:
            return None
        d = make(y if y is not None else default_year, month, day)
        return (d, y is not None) if d else None

    if not 2 <= len(numbers) <= 3:
        return None
    if len(numbers[0]) == 4:
        if len(numbers) != 3:
            return None
        d = make(int(numbers[0]), int(numbers[1]), int(numbers[2]))
        return (d, True) if d else None
    if len(numbers[0]) > 2 or len(numbers[1]) > 2:
        return None
    a, b = int(numbers[0]), int(numbers[1])
    dd, mm = (a, b) if order is DateOrder.DAY_MONTH else (b, a)
    y = None
    if len(numbers) == 3:
        y = _year(numbers[2])
        if y is None:
            return None
    d = make(y if y is not None else default_year, mm, dd)
    return (d, y is not None) if d else None


@dataclass(frozen=True)
class ImportRow:
    """One pasted line and how it was read: a label for a week, or the
    reason it was skipped."""

    line: int
    source: str
    week: Date | None = None
    label: str = ""
    skipped: str = ""

    @property
    def is_label(self) -> bool:
        return self.week is not None


def parse_import(text: str, order: DateOrder, reference_year: int) -> list[ImportRow]:
    """One row per non-blank line. Columns are split on tabs (what
    spreadsheets put on the clipboard), or as CSV when there are no tabs."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    uses_tabs = "\t" in text
    rows: list[ImportRow] = []
    seen: dict[Date, int] = {}
    previous: Date | None = None
    year = reference_year

    for i, line in enumerate(lines):
        line_number = i + 1
        if not line.strip():
            continue
        if uses_tabs:
            cells = line.split("\t")
        else:
            parsed = csvio.parse(line)
            cells = parsed[0] if parsed else [line]
        trimmed = [c.strip() for c in cells]

        match: tuple[int, Date] | None = None
        for j, cell in enumerate(trimmed):
            if not cell:
                continue
            parsed_date = parse_flexible_date(cell, order, year)
            if parsed_date is None:
                continue
            d, has_year = parsed_date
            if not has_year and previous is not None and days_between(d, previous) > 183:
                try:   # 3 Jan after 20 Dec: the next year.
                    d = Date(d.year + 1, d.month, d.day)
                except ValueError:
                    pass
            if has_year or d.year != year:
                year = d.year
            match = (j, d)
            break
        if match is None:
            rows.append(ImportRow(line_number, line, skipped=(
                "No date (a heading row?)" if not rows else "No date found")))
            continue
        index, found = match
        previous = found
        others = [(j, c) for j, c in enumerate(trimmed) if j != index and c]
        after = next(((j, c) for j, c in others if j > index), None)
        label_cell = after or (others[0] if others else None)
        if label_cell is None:
            rows.append(ImportRow(line_number, line, skipped="No label"))
            continue
        week = monday(found)
        if week in seen:
            rows.append(ImportRow(line_number, line, skipped=f"Same week as line {seen[week]}"))
            continue
        seen[week] = line_number
        rows.append(ImportRow(line_number, line, week=week, label=one_line(label_cell[1])))
    return rows


def import_labels(rows: list[ImportRow]) -> dict[Date, str]:
    """The labels the rows set."""
    return {r.week: r.label for r in rows if r.week is not None}
