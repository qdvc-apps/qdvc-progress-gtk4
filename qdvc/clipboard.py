"""A rectangle of copied cells (rows top to bottom, days left to right), as
it travels on the clipboard: the app's own format (JSON), plus
tab-separated labels for other apps."""

from __future__ import annotations

import json

from .labels import EMPTY_CELL, Cell, CellLabel

#: The MIME type of the app's own copies.
MIME_TYPE = "application/x-qdvc-progress-cells"


class CellClip:
    def __init__(self, rows: list[list[Cell]]):
        width = max((len(r) for r in rows), default=0)
        self.rows = [list(r) + [EMPTY_CELL] * (width - len(r)) for r in rows]

    def __eq__(self, other):
        return isinstance(other, CellClip) and self.rows == other.rows

    def __repr__(self):
        return f"CellClip({self.rows!r})"

    @property
    def height(self) -> int:
        return len(self.rows)

    @property
    def width(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    @property
    def is_single_cell(self) -> bool:
        return self.height == 1 and self.width == 1

    def cell(self, row: int, column: int) -> Cell:
        if 0 <= row < self.height and 0 <= column < self.width:
            return self.rows[row][column]
        return EMPTY_CELL

    def to_json(self) -> bytes:
        def enc(c: Cell):
            d = {"note": c.note}
            if c.label is not None:
                d["label"] = c.label.value
            return d
        return json.dumps({"rows": [[enc(c) for c in row] for row in self.rows]}).encode()

    @staticmethod
    def from_json(data: bytes) -> "CellClip | None":
        try:
            obj = json.loads(data.decode("utf-8"))
            rows = [[Cell(CellLabel(c["label"]) if c.get("label") else None, str(c.get("note", "")))
                     for c in row] for row in obj["rows"]]
        except (ValueError, KeyError, TypeError, AttributeError):
            return None
        return CellClip(rows) if rows else None

    @property
    def tsv(self) -> str:
        """The labels as tab-separated text, for pasting into a spreadsheet.
        A cell with only a note gives its note (on one line)."""
        def text(c: Cell) -> str:
            if c.label is not None:
                return c.label.text
            return " ".join(part for part in c.note.splitlines() if part)
        return "\n".join("\t".join(text(c) for c in row) for row in self.rows)

    @staticmethod
    def from_text(text: str) -> "CellClip | None":
        """Text from another app. Tab-separated labels (as a spreadsheet
        copies them) become a rectangle of labels; with tabs, other text in a
        field becomes that cell's note. Text without tabs that is not all
        labels becomes one cell whose note is the whole text."""
        normalised = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalised.split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        if not lines:
            return None
        grid = [line.split("\t") for line in lines]
        fields = [f.strip(" \t") for row in grid for f in row]
        all_labels = all(not f or CellLabel.lenient(f) is not None for f in fields)
        if all_labels or "\t" in normalised:
            def cell(f: str) -> Cell:
                t = f.strip(" \t")
                label = CellLabel.lenient(t)
                return Cell(label=label) if label is not None else Cell(note=t)
            return CellClip([[cell(f) for f in row] for row in grid])
        note = normalised.strip()
        return CellClip([[Cell(note=note)]]) if note else None
