"""The Keyboard Shortcuts window (Ctrl+?), built from ``ui_prefs.SHORTCUTS``."""

from __future__ import annotations

from xml.sax.saxutils import escape

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..ui_prefs import SHORTCUTS  # noqa: E402


def _xml() -> str:
    groups = []
    for title, items in SHORTCUTS:
        shortcuts = "".join(
            f'<child><object class="GtkShortcutsShortcut">'
            f'<property name="title">{escape(s.title)}</property>'
            f'<property name="accelerator">{escape(s.accels[0])}</property>'
            f"</object></child>"
            for s in items if s.shown)
        groups.append(f'<child><object class="GtkShortcutsGroup">'
                      f'<property name="title">{escape(title)}</property>{shortcuts}'
                      f"</object></child>")
    return ('<interface><object class="GtkShortcutsWindow" id="window">'
            '<property name="modal">1</property>'
            '<child><object class="GtkShortcutsSection">'
            '<property name="section-name">shortcuts</property>'
            '<property name="max-height">12</property>'
            f'{"".join(groups)}</object></child></object></interface>')


def shortcuts_window(parent: Gtk.Window) -> Gtk.Window:
    builder = Gtk.Builder.new_from_string(_xml(), -1)
    win = builder.get_object("window")
    win.set_transient_for(parent)
    return win
