"""Pure, toolkit-independent UI helpers: the shortcuts table, the grid's
optional columns, the totals scope, and date formatting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .dates import Date, DayRange
from .query import SortKey


class LeftColumn(Enum):
    """The columns on the left of the grid (the title is always shown)."""

    CODE = "code"
    TITLE = "title"
    TARGET = "target"
    COLLABORATORS = "collaborators"

    @property
    def title(self) -> str:
        return {LeftColumn.CODE: "ID", LeftColumn.TITLE: "Project",
                LeftColumn.TARGET: "Target", LeftColumn.COLLABORATORS: "Collaborators"}[self]

    @property
    def default_width(self) -> int:
        return {LeftColumn.CODE: 58, LeftColumn.TITLE: 230, LeftColumn.TARGET: 120,
                LeftColumn.COLLABORATORS: 140}[self]

    @property
    def min_width(self) -> int:
        return 100 if self is LeftColumn.TITLE else 36

    @property
    def sort_key(self) -> SortKey:
        """The sort the column heading chooses when clicked."""
        return {LeftColumn.CODE: SortKey.CODE, LeftColumn.TITLE: SortKey.TITLE,
                LeftColumn.TARGET: SortKey.TARGET,
                LeftColumn.COLLABORATORS: SortKey.COLLABORATORS}[self]


OPTIONAL_COLUMNS = [LeftColumn.CODE, LeftColumn.TARGET, LeftColumn.COLLABORATORS]


class TotalsScope(Enum):
    """Which projects the totals at the bottom add up."""

    VISIBLE = "visible"
    ALL = "all"

    @property
    def title(self) -> str:
        return "Projects Shown" if self is TotalsScope.VISIBLE else "All Projects"


DEFAULT_CELL_WIDTH = 32
CELL_WIDTH_MIN = 24
CELL_WIDTH_MAX = 60
CELL_WIDTH_STEP = 4


# --- shortcuts ------------------------------------------------------------

@dataclass(frozen=True)
class Shortcut:
    title: str
    #: GTK accelerator strings; the first is the one shown.
    accels: tuple[str, ...]
    #: The ``win.``/``app.`` action it triggers, or None for keys the grid
    #: (or a text field) handles itself.
    action: str | None = None
    #: Shown in the shortcuts window (False for alternatives only).
    shown: bool = True


#: Every shortcut, by the section of the shortcuts window it is listed in.
#: The application registers the accelerators of the entries with an action;
#: the others document keys the grid handles while it has the focus.
SHORTCUTS: list[tuple[str, list[Shortcut]]] = [
    ("Workspace", [
        Shortcut("New project", ("<Control>n",), "win.new-project"),
        Shortcut("New programme", ("<Control><Shift>n",), "win.new-programme"),
        Shortcut("Open workspace", ("<Control>o",), "win.open-workspace"),
        Shortcut("Week labels", ("<Control>l",), "win.week-labels"),
        Shortcut("Refresh from disk", ("<Control>r", "F5"), "win.refresh"),
        Shortcut("Close workspace", ("<Control><Shift>w",), "win.close-workspace"),
    ]),
    ("Dates", [
        Shortcut("Today", ("<Control>t",), "win.today"),
        Shortcut("Previous week", ("<Alt>Left", "<Control>bracketleft"), "win.previous-week"),
        Shortcut("Next week", ("<Alt>Right", "<Control>bracketright"), "win.next-week"),
        Shortcut("Go to date", ("<Control>g",), "win.go-to-date"),
    ]),
    ("Typing in the Grid", [
        Shortcut("XS … XL", ("1...5",)),
        Shortcut("Meeting (mtg)", ("m",)),
        Shortcut("Planned (P)", ("p",)),
        Shortcut("Due date", ("exclam",)),
        Shortcut("Tick / cross / information", ("v x question",)),
        Shortcut("Clear the label", ("0 Delete",)),
        Shortcut("Mark days inactive or active", ("i",)),
        Shortcut("Edit the note", ("Return",)),
        Shortcut("Back to the grid from the note", ("Escape",)),
    ]),
    ("Selecting", [
        Shortcut("Move", ("Left Right Up Down",)),
        Shortcut("Extend the selection", ("<Shift>Left <Shift>Right",)),
        Shortcut("Next / previous day", ("Tab <Shift>Tab",)),
        Shortcut("Select all cells", ("<Control>a",)),
        Shortcut("Select one cell", ("Escape",)),
    ]),
    ("Editing", [
        Shortcut("Copy", ("<Control>c",)),
        Shortcut("Cut", ("<Control>x",)),
        Shortcut("Paste", ("<Control>v",)),
        Shortcut("Paste special", ("<Control><Shift>v",)),
        Shortcut("Undo", ("<Control>z",)),
        Shortcut("Redo", ("<Control><Shift>z",)),
    ]),
    ("Projects", [
        Shortcut("Show project details", ("<Control>i",), "win.show-project"),
        Shortcut("Move project up", ("<Alt>Up",), "win.move-project-up"),
        Shortcut("Move project down", ("<Alt>Down",), "win.move-project-down"),
    ]),
    ("View", [
        Shortcut("Filter projects", ("<Control>f",), "win.find"),
        Shortcut("Show or hide the side panel", ("F9",), "win.side-panel"),
        Shortcut("All programmes", ("<Alt>0",), "win.programme-all"),
        Shortcut("One programme", ("<Alt>1...<Alt>9",)),
        Shortcut("Wider day columns", ("<Control>plus", "<Control>equal", "<Control>KP_Add"),
                 "win.zoom-in"),
        Shortcut("Narrower day columns", ("<Control>minus", "<Control>KP_Subtract"),
                 "win.zoom-out"),
        Shortcut("Default day columns", ("<Control>0", "<Control>KP_0"), "win.zoom-reset"),
    ]),
    ("General", [
        Shortcut("Preferences", ("<Control>comma",), "win.preferences"),
        Shortcut("Keyboard shortcuts", ("<Control>question",), "win.shortcuts"),
        Shortcut("Close window", ("<Control>w",), "window.close"),
        Shortcut("Quit", ("<Control>q",), "app.quit"),
    ]),
]


def accelerators() -> dict[str, list[str]]:
    """Action name → accelerators, for ``set_accels_for_action``."""
    out: dict[str, list[str]] = {}
    for _, items in SHORTCUTS:
        for s in items:
            if s.action and s.action != "window.close":
                out.setdefault(s.action, []).extend(s.accels)
    return out


# --- formatting -----------------------------------------------------------

WEEKDAY_LETTERS = ["M", "Tu", "W", "Th", "Fr", "Sa", "Su"]


def long_day(d: Date) -> str:
    """``Fri 9 Oct 2026``."""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')} {d.year}"


def short_day(d: Date) -> str:
    """``9 Oct``."""
    return f"{d.day} {d.strftime('%b')}"


def month_title(d: Date) -> str:
    """``October 2026``."""
    return f"{d.strftime('%B')} {d.year}"


def range_text(r: DayRange) -> str:
    """``5 Oct – 16 Oct 2026``."""
    if r.start == r.end:
        return long_day(r.start)
    return f"{short_day(r.start)} \u2013 {short_day(r.end)} {r.end.year}"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"
