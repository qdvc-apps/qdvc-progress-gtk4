#!/usr/bin/env python3
"""QDVC Progress — entry point.

    python3 qdvc_progress.py [WORKSPACE-FOLDER]

GTK 4 / libadwaita only (docs/MAINTENANCE.md §4): there is no GTK 3
front-end to dispatch to. ``--gtk4`` is accepted and ignored, for
compatibility with the other QDVC apps' launchers.
"""

import os
import sys

MIN_ADW = (1, 5)


def _fail(message: str) -> int:
    print(f"qdvc-progress: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if sys.version_info < (3, 10):
        return _fail("Python 3.10 or later is needed.")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    argv = [a for a in sys.argv if a not in ("--gtk4",)]
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw
    except (ImportError, ValueError) as e:
        return _fail(f"GTK 4 and libadwaita are needed ({e}). On Debian or Ubuntu: sudo apt "
                     "install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 "
                     "python3-yaml")
    if (Adw.get_major_version(), Adw.get_minor_version()) < MIN_ADW:
        return _fail("libadwaita %d.%d or later is needed (found %d.%d)."
                     % (*MIN_ADW, Adw.get_major_version(), Adw.get_minor_version()))
    from qdvc.gtk4.gtk4_app import main as run
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
