"""Smoke tests of the GTK 4 front-end.

* With a stub ``gi`` (tests/stubs), every ``qdvc.gtk4`` module must import:
  this runs anywhere, with or without GTK.
* With GTK 4, libadwaita and a display, the main window is built on a copy
  of sample-workspace/ (it is never shown).
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = sorted(f"qdvc.gtk4.{n[:-3]}" for n in os.listdir(os.path.join(ROOT, "qdvc", "gtk4"))
                 if n.startswith("gtk4_") and n.endswith(".py"))


class StubImportTests(unittest.TestCase):
    def test_every_gtk4_module_imports_with_a_stub_gi(self):
        code = "import importlib\n" + "".join(f"importlib.import_module({m!r})\n" for m in MODULES)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "tests", "stubs"),
                                                           ROOT]))
        r = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_entry_point_compiles(self):
        import py_compile
        py_compile.compile(os.path.join(ROOT, "qdvc_progress.py"), doraise=True)


def _have_gtk_display() -> bool:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


WINDOW_SCRIPT = r"""
import os, shutil, sys, tempfile
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
shutil.copytree(os.path.join(ROOT, "sample-workspace"), os.path.join(tmp, "ws"))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
Adw.init()
from qdvc.config import Config
from qdvc.gtk4.gtk4_window import ProgressWindow
app = Adw.Application(application_id="qdvc.ProgressSmokeTest")
app.register(None)
win = ProgressWindow(app, Config.in_memory(), "x-office-spreadsheet")
win.open_path(os.path.join(tmp, "ws"))
assert win.s.workspace is not None and win.s.rows, "workspace did not load"
win._refresh_ui()
win.destroy()
shutil.rmtree(tmp)
print("ok")
"""


@unittest.skipUnless(_have_gtk_display(), "needs GTK 4, libadwaita and a display")
class WindowTests(unittest.TestCase):
    def test_window_builds_on_the_sample_workspace(self):
        env = dict(os.environ, GTK_A11Y="none")
        r = subprocess.run([sys.executable, "-c", f"ROOT = {ROOT!r}\n" + WINDOW_SCRIPT],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
