"""A small undo manager.

It works like NSUndoManager in the macOS edition: an action registers a
closure that undoes it; while that closure runs (an undo), whatever it
registers in turn goes on the redo stack, and vice versa. A new action
clears the redo stack.
"""

from __future__ import annotations

from typing import Callable

MAX_STEPS = 200


class UndoManager:
    def __init__(self):
        self._undo: list[tuple[str, Callable[[], None]]] = []
        self._redo: list[tuple[str, Callable[[], None]]] = []
        self._state = "normal"   # "normal", "undoing" or "redoing"

    def register(self, name: str, undo: Callable[[], None]) -> None:
        if self._state == "undoing":
            self._redo.append((name, undo))
            return
        self._undo.append((name, undo))
        del self._undo[:-MAX_STEPS]
        if self._state == "normal":
            self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_name(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    @property
    def redo_name(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def undo(self) -> str | None:
        """Undoes the last action; returns its name."""
        if not self._undo:
            return None
        name, fn = self._undo.pop()
        self._state = "undoing"
        try:
            fn()
        finally:
            self._state = "normal"
        return name

    def redo(self) -> str | None:
        if not self._redo:
            return None
        name, fn = self._redo.pop()
        self._state = "redoing"
        try:
            fn()
        finally:
            self._state = "normal"
        return name

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
