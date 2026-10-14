"""QDVC Progress — the GTK 4 / libadwaita application.

An ``Adw.Application`` owns the application id, the accelerators of the
``win.*`` actions (from ``ui_prefs.SHORTCUTS``) and the window lifecycle.
"""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, PRGNAME  # noqa: E402
from ..config import Config  # noqa: E402
from ..ui_prefs import accelerators  # noqa: E402
from .gtk4_window import ProgressWindow  # noqa: E402

#: The installed app icon (scripts/build-app.sh puts it in the icon theme),
#: and the stock themed icon used when running from a checkout.
ICON_NAME = APP_ID
FALLBACK_ICON_NAME = "x-office-spreadsheet"

# Matches StartupWMClass in the .desktop file (X11 window matching).
GLib.set_prgname(PRGNAME)
GLib.set_application_name("QDVC Progress")

CSS = """
.label-button { padding: 6px 2px; min-height: 40px; }
.label-button.selected-label { box-shadow: inset 0 0 0 2px @accent_bg_color; }
textview.note-view, textview.note-view text { background: transparent; }
statuspage.empty-grid { background: alpha(@view_bg_color, 0.94); }
popover.note-callout > contents { min-width: 220px; }
"""


def resolve_icon_name() -> str:
    display = Gdk.Display.get_default()
    if display is not None:
        theme = Gtk.IconTheme.get_for_display(display)
        here = os.path.join(os.path.dirname(__file__), "..", "..", "data", "icons")
        if os.path.isdir(here):
            theme.add_search_path(os.path.abspath(here))
        if theme.has_icon(ICON_NAME):
            return ICON_NAME
    return FALLBACK_ICON_NAME


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.config = Config.load()
        self.window: ProgressWindow | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self._quit())
        self.add_action(quit_action)
        for action, accels in accelerators().items():
            self.set_accels_for_action(action, accels)
        self.set_accels_for_action("window.close", ["<Control>w"])
        for i in range(1, 10):
            self.set_accels_for_action(f"win.programme-index({i})", [f"<Alt>{i}"])
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS) if hasattr(provider, "load_from_string") \
            else provider.load_from_data(CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Window.set_default_icon_name(resolve_icon_name())

    def _window(self) -> ProgressWindow:
        if self.window is None:
            self.window = ProgressWindow(self, self.config, resolve_icon_name())
            self.window.s.start_up()
        return self.window

    def do_activate(self):
        self._window().present()

    def do_open(self, files, n_files, hint):
        win = self._window()
        win.present()
        for f in files[:1]:
            path = f.get_path()
            if path and os.path.isdir(path):
                win.open_path(path)

    def _quit(self):
        if self.window is not None:
            self.window.close()
        self.quit()

    def do_shutdown(self):
        if self.window is not None:
            self.window.s.flush_saves()
        Adw.Application.do_shutdown(self)


def main(argv=None) -> int:
    return Application().run(argv if argv is not None else sys.argv)
