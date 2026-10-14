"""Minimal RFC 4180 CSV, byte-compatible with the macOS edition.

Comma-separated; a field is quoted with ``"`` when it holds a comma, a quote,
a line break or leading or trailing spaces, with quotes doubled. Files are
written with ``\\n`` line ends and read with any. (Python's ``csv`` module
quotes differently, so it is not used.)
"""

from __future__ import annotations


def parse(text: str, separator: str = ",") -> list[list[str]]:
    """The rows of ``text``. A trailing line break does not make an empty
    row; blank lines are skipped."""
    rows: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    in_quotes = False
    was_quoted = False
    if text.startswith("\ufeff"):   # a byte-order mark, which Excel likes to write
        text = text[1:]
    i, n = 0, len(text)

    def end_field():
        nonlocal field, was_quoted
        row.append("".join(field))
        field = []
        was_quoted = False

    def end_row():
        nonlocal row
        end_field()
        if not (len(row) == 1 and row[0] == ""):
            rows.append(row)
        row = []

    while i < n:
        c = text[i]
        if in_quotes:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                field.append(c)
        elif c == '"' and not field and not was_quoted:
            in_quotes = True
            was_quoted = True
        elif c == separator:
            end_field()
        elif c == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                i += 1
            end_row()
        elif c == "\n":
            end_row()
        else:
            field.append(c)
        i += 1
    if field or row or was_quoted:
        end_row()
    return rows


def escape(field: str) -> str:
    needs = ("," in field or '"' in field or "\n" in field or "\r" in field
             or field.startswith(" ") or field.endswith(" "))
    if not needs:
        return field
    return '"' + field.replace('"', '""') + '"'


def render(rows: list[list[str]]) -> str:
    return "".join(",".join(escape(f) for f in row) + "\n" for row in rows)
