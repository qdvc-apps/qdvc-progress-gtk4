"""Cell labels, cells and paste modes (docs/DESIGN.md §5)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class CellLabel(Enum):
    """What a day-cell says: a work size (XS…XL, a subjective measure of the
    effort a day's work took) or one of the special labels. A cell holds at
    most one label. The value is the text written in log files."""

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    MEETING = "mtg"
    DUE = "(!)"
    PLANNED = "(P)"
    TICK = "(ok)"
    CROSS = "(x)"
    INFO = "(i)"

    @property
    def text(self) -> str:
        """The text written in the log file and shown in the grid."""
        return self.value

    @property
    def size_index(self) -> int | None:
        """0 for XS … 4 for XL; None for the special labels."""
        return _SIZE_INDEX.get(self)

    @property
    def is_size(self) -> bool:
        return self in _SIZE_INDEX

    @property
    def is_emblem(self) -> bool:
        """Due date, tick, cross and information: drawn as a coloured circle
        with a symbol on a blank cell, adding nothing to the totals."""
        return self in _EMBLEMS

    @property
    def title(self) -> str:
        """A longer name, for menus and the side panel."""
        return _TITLES[self]

    @property
    def key(self) -> str:
        """The key that sets this label when the grid has keyboard focus."""
        return _KEYS[self]

    @staticmethod
    def lenient(text: str) -> "CellLabel | None":
        """Reads a label as written in a log file or pasted from a
        spreadsheet. Case and surrounding brackets or spaces are forgiven, so
        ``xs``, ``Mtg``, ``!``, ``due``, ``p``, ``(p)``, ``ok``, ``✓``, ``x``
        and ``i`` are all understood. None for anything else."""
        return _LENIENT.get(text.strip().lower())

    @staticmethod
    def for_key(ch: str) -> "CellLabel | None":
        return _BY_KEY.get(ch)


SIZES = [CellLabel.XS, CellLabel.S, CellLabel.M, CellLabel.L, CellLabel.XL]
SPECIALS = [CellLabel.MEETING, CellLabel.PLANNED, CellLabel.DUE,
            CellLabel.TICK, CellLabel.CROSS, CellLabel.INFO]

_SIZE_INDEX = {label: i for i, label in enumerate(SIZES)}
_EMBLEMS = {CellLabel.DUE, CellLabel.TICK, CellLabel.CROSS, CellLabel.INFO}
_TITLES = {
    CellLabel.XS: "Extra Small", CellLabel.S: "Small", CellLabel.M: "Medium",
    CellLabel.L: "Large", CellLabel.XL: "Extra Large", CellLabel.MEETING: "Meeting",
    CellLabel.DUE: "Due Date", CellLabel.PLANNED: "Planned", CellLabel.TICK: "Tick",
    CellLabel.CROSS: "Cross", CellLabel.INFO: "Information",
}
_KEYS = {
    CellLabel.XS: "1", CellLabel.S: "2", CellLabel.M: "3", CellLabel.L: "4",
    CellLabel.XL: "5", CellLabel.MEETING: "m", CellLabel.DUE: "!",
    CellLabel.PLANNED: "p", CellLabel.TICK: "v", CellLabel.CROSS: "x",
    CellLabel.INFO: "?",
}
_BY_KEY = {key: label for label, key in _KEYS.items()}
_LENIENT: dict[str, CellLabel] = {}
for _words, _label in [
    (["xs"], CellLabel.XS), (["s"], CellLabel.S), (["m"], CellLabel.M),
    (["l"], CellLabel.L), (["xl"], CellLabel.XL),
    (["mtg", "meeting"], CellLabel.MEETING),
    (["(!)", "!", "due"], CellLabel.DUE),
    (["(p)", "p", "planned", "plan"], CellLabel.PLANNED),
    (["(ok)", "ok", "tick", "done", "\u2713", "\u2714", "(\u2713)", "(\u2714)", "(v)"],
     CellLabel.TICK),
    (["(x)", "x", "cross", "\u2717", "\u2718", "\u00d7", "(\u2717)", "(\u2718)"],
     CellLabel.CROSS),
    (["(i)", "i", "info", "\u2139", "\u2139\ufe0f"], CellLabel.INFO),
]:
    for _w in _words:
        _LENIENT[_w] = _label


def label_token(label: CellLabel | None) -> str:
    """A label as an action target string (``"none"`` for no label)."""
    return "none" if label is None else label.value


def label_from_token(token: str) -> CellLabel | None:
    """The inverse of :func:`label_token`."""
    return None if token == "none" else CellLabel(token)


@dataclass(frozen=True)
class Cell:
    """One project's entry for one day: a label, a note, or both."""

    label: CellLabel | None = None
    note: str = ""

    @property
    def has_note(self) -> bool:
        return bool(self.note.strip())

    @property
    def is_empty(self) -> bool:
        return self.label is None and not self.has_note

    def with_label(self, label: CellLabel | None) -> "Cell":
        return replace(self, label=label)

    def with_note(self, note: str) -> "Cell":
        return replace(self, note=note)


EMPTY_CELL = Cell()


class PasteMode(Enum):
    """Which parts of a copied cell Paste writes."""

    BOTH = "both"
    LABEL = "label"
    NOTE = "note"

    @property
    def title(self) -> str:
        return {PasteMode.BOTH: "Label and Note", PasteMode.LABEL: "Label Only",
                PasteMode.NOTE: "Note Only"}[self]

    @property
    def includes_label(self) -> bool:
        return self is not PasteMode.NOTE

    @property
    def includes_note(self) -> bool:
        return self is not PasteMode.LABEL

    def apply(self, source: Cell, onto: Cell) -> Cell:
        """``source`` written over ``onto`` in this mode."""
        out = onto
        if self.includes_label:
            out = out.with_label(source.label)
        if self.includes_note:
            out = out.with_note(source.note)
        return out
