#!/usr/bin/env python3
"""Render the app to PNG files without a desktop, for checking the UI.

    xvfb-run -a python3 tools/snapshot.py OUTDIR [--dark] [--width W --height H]

Copies sample-workspace/ to a temporary folder, opens it with a throwaway
config, runs a short script of interactions and saves a screenshot after
each step (OUTDIR/NN-name.png). Needs GTK 4 and libadwaita; with no display,
run it under ``xvfb-run``. GSK_RENDERER=cairo is set for software rendering.
"""

import argparse
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("GSK_RENDERER", "cairo")
os.environ.setdefault("GTK_A11Y", "none")

parser = argparse.ArgumentParser()
parser.add_argument("outdir")
parser.add_argument("--dark", action="store_true")
parser.add_argument("--width", type=int, default=1400)
parser.add_argument("--height", type=int, default=860)
parser.add_argument("--steps", default="all", help="comma-separated step names, or all")
args = parser.parse_args()

tmp = tempfile.mkdtemp(prefix="qdvc-progress-snap-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
workspace = os.path.join(tmp, "workspace")
shutil.copytree(os.path.join(ROOT, "sample-workspace"), workspace)
os.makedirs(args.outdir, exist_ok=True)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from qdvc.dates import Date  # noqa: E402
from qdvc.gtk4 import gtk4_app  # noqa: E402
from qdvc.session import CellRef  # noqa: E402

app = gtk4_app.Application()
app.config.set("window", {"width": args.width, "height": args.height, "maximized": False})
counter = [0]


def shoot(name, widget=None):
    win = widget or app.window
    w, h = win.get_width(), win.get_height()
    paintable = Gtk.WidgetPaintable.new(win)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        print("nothing to render for", name)
        return
    texture = win.get_native().get_renderer().render_texture(node, None)
    counter[0] += 1
    path = os.path.join(args.outdir, f"{counter[0]:02d}-{name}.png")
    texture.save_to_png(path)
    print("saved", path)


def dialog_shot(name):
    """Screenshots the topmost dialog (Adw dialogs are children of the window)."""
    shoot(name)


STEPS = []


def step(fn):
    STEPS.append(fn)
    return fn


@step
def welcome():
    shoot("welcome")


@step
def grid():
    app.window.open_path(workspace)
    s = app.window.s
    s.select(CellRef("arc-discovery-grant", Date(2026, 10, 6)))


@step
def grid_shot():
    shoot("grid")


@step
def project_panel():
    app.window.show_project()


@step
def project_shot():
    shoot("project-panel")


@step
def multi_select():
    s = app.window.s
    from qdvc.session import GridSelection
    s.selection = GridSelection(CellRef("soil-carbon-paper", Date(2026, 9, 28)),
                                CellRef("envs-201-lectures", Date(2026, 10, 2)))
    s.inspector_tab = "day"
    s.bump()


@step
def multi_shot():
    shoot("multi-select")


@step
def callout():
    s = app.window.s
    ref = CellRef("phd-supervision", Date(2026, 10, 7))
    s.select(ref)
    app.window.grid._pin_callout(ref)


@step
def callout_shot():
    shoot("callout")
    app.window.grid.callout.close()


@step
def new_project():
    app.window.new_project()


@step
def new_project_shot():
    shoot("new-project")
    _close_dialogs()


@step
def week_labels():
    app.window.show_week_labels()


@step
def week_labels_paste():
    d = _dialog()
    if d is not None:
        d.text.get_buffer().set_text("Week of\tLabel\n2/11/2026\tStudy week\n9/11/2026\tExams\n"
                                     "11/11/2026\tExams again\nnotes\tx\n")


@step
def week_labels_shot():
    shoot("week-labels")
    _close_dialogs()


@step
def preferences():
    app.window.show_preferences()


@step
def preferences_shot():
    shoot("preferences")
    _close_dialogs()


@step
def narrow():
    app.window.set_default_size(760, 720)


@step
def narrow_wait():
    pass


@step
def narrow_shot():
    shoot("narrow")


def _dialog():
    d = app.window.get_visible_dialog() if hasattr(app.window, "get_visible_dialog") else None
    return d


def _close_dialogs():
    d = _dialog()
    if d is not None:
        d.force_close() if hasattr(d, "force_close") else d.close()


def run_steps():
    wanted = None if args.steps == "all" else set(args.steps.split(","))
    queue = [f for f in STEPS if wanted is None or f.__name__.split("_shot")[0] in wanted
             or f.__name__ in wanted]

    def next_step():
        if not queue:
            app.quit()
            return False
        fn = queue.pop(0)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - keep going, report
            import traceback
            traceback.print_exc()
            print("step failed:", fn.__name__, e)
        GLib.timeout_add(450, next_step)
        return False
    GLib.timeout_add(700, next_step)


def on_activate(_app):
    if args.dark:
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    run_steps()


app.connect("activate", on_activate)
app.run([sys.argv[0]])
shutil.rmtree(tmp, ignore_errors=True)
