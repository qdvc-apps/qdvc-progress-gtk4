#!/usr/bin/env bash
# Build and install QDVC Progress for the current user (no root needed).
#
#   scripts/build-app.sh               # check dependencies, run the tests, stage build/
#   scripts/build-app.sh --install     # ...and install to ~/.local (restarts a running copy)
#   scripts/build-app.sh --uninstall   # remove the installed copy
#   scripts/build-app.sh --no-tests    # skip the unit tests
#   scripts/build-app.sh --run         # after building/installing, start the app
#
# Installs:
#   ~/.local/share/qdvc-progress/app/                  the program (qdvc_progress.py + qdvc/)
#   ~/.local/bin/qdvc-progress                         launcher script
#   ~/.local/share/applications/qdvc.Progress.desktop  menu entry (Activities, Dock)
#   ~/.local/share/icons/hicolor/.../qdvc.Progress*.svg app icons
# Set PREFIX to install elsewhere (default: ~/.local).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP_ID="qdvc.Progress"
PREFIX="${PREFIX:-$HOME/.local}"
SHARE="$PREFIX/share"
APP_DIR="$SHARE/qdvc-progress/app"
BIN_DIR="$PREFIX/bin"
DESKTOP="$SHARE/applications/$APP_ID.desktop"
ICONS="$SHARE/icons/hicolor"
STAGE="$ROOT/build/qdvc-progress"

install=0 uninstall=0 tests=1 run=0
for arg in "$@"; do
    case "$arg" in
        --install) install=1 ;;
        --uninstall) uninstall=1 ;;
        --no-tests) tests=0 ;;
        --run) run=1 ;;
        -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

say() { printf '==> %s\n' "$*"; }

# Is a copy running? Ask it to quit through its D-Bus actions (it saves first).
running() {
    command -v gdbus >/dev/null 2>&1 || return 1
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$APP_ID" 2>/dev/null | grep -q true
}
quit_running() {
    gdbus call --session --dest "$APP_ID" --object-path "/${APP_ID//./\/}" \
        --method org.gtk.Actions.Activate quit [] {} >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do running || return 0; sleep 0.1; done
}

refresh_caches() {
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database -q "$SHARE/applications" 2>/dev/null || true
    touch "$ICONS" 2>/dev/null || true
    command -v gtk4-update-icon-cache >/dev/null 2>&1 \
        && gtk4-update-icon-cache -q -t -f "$ICONS" 2>/dev/null \
        || { command -v gtk-update-icon-cache >/dev/null 2>&1 \
             && gtk-update-icon-cache -q -t -f "$ICONS" 2>/dev/null; } || true
}

if [[ $uninstall -eq 1 ]]; then
    running && { say "Quitting the running copy"; quit_running; }
    rm -rf "$SHARE/qdvc-progress" "$BIN_DIR/qdvc-progress" "$DESKTOP" \
        "$ICONS/scalable/apps/$APP_ID.svg" "$ICONS/symbolic/apps/$APP_ID-symbolic.svg"
    refresh_caches
    say "Uninstalled (your workspaces and ~/.config/qdvc-progress are untouched)"
    exit 0
fi

# --- dependencies ---------------------------------------------------------
say "Checking dependencies"
if ! python3 - <<'PY'
import sys
problems = []
if sys.version_info < (3, 10):
    problems.append("Python 3.10 or later")
try:
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw
    if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 5):
        problems.append("libadwaita 1.5 or later (found %d.%d)"
                        % (Adw.get_major_version(), Adw.get_minor_version()))
    print("    GTK %d.%d.%d, libadwaita %d.%d.%d, Python %s" % (
        Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version(),
        Adw.get_major_version(), Adw.get_minor_version(), Adw.get_micro_version(),
        sys.version.split()[0]))
except (ImportError, ValueError) as e:
    problems.append(f"GTK 4 and libadwaita for Python ({e})")
try:
    import cairo  # noqa: F401
    gi.require_foreign("cairo")
except Exception:
    problems.append("PyGObject's cairo support")
try:
    import yaml  # noqa: F401
except ImportError:
    problems.append("PyYAML")
if problems:
    print("Missing: " + "; ".join(problems), file=sys.stderr)
    sys.exit(1)
PY
then
    cat >&2 <<'HELP'
Install the dependencies, then run this script again:
  Debian/Ubuntu: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 python3-yaml
  Fedora:        sudo dnf install python3-gobject python3-cairo gtk4 libadwaita python3-pyyaml
  Arch:          sudo pacman -S python-gobject python-cairo gtk4 libadwaita python-yaml
HELP
    exit 1
fi

# --- tests and build ------------------------------------------------------
if [[ $tests -eq 1 ]]; then
    say "Running the tests"
    python3 -m unittest discover -s tests -q
fi

say "Staging $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp qdvc_progress.py "$STAGE/"
cp -r qdvc "$STAGE/"
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +
python3 -m compileall -q "$STAGE" >/dev/null

if [[ $install -eq 1 ]]; then
    was_running=0
    if running; then
        say "Quitting the running copy (it saves first)"
        quit_running
        was_running=1
    fi
    say "Installing to $PREFIX"
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR" "$BIN_DIR" "$SHARE/applications" \
        "$ICONS/scalable/apps" "$ICONS/symbolic/apps"
    cp -r "$STAGE/." "$APP_DIR/"
    cat > "$BIN_DIR/qdvc-progress" <<LAUNCHER
#!/bin/sh
exec python3 "$APP_DIR/qdvc_progress.py" "\$@"
LAUNCHER
    chmod +x "$BIN_DIR/qdvc-progress"
    sed "s|@BINDIR@|$BIN_DIR|g" data/qdvc.Progress.desktop.in > "$DESKTOP"
    cp "data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICONS/scalable/apps/"
    cp "data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" "$ICONS/symbolic/apps/"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$DESKTOP" || echo "warning: desktop-file-validate complained" >&2
    fi
    refresh_caches
    say "Installed: open QDVC Progress from Activities, or run qdvc-progress"
    case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "note: $BIN_DIR is not on your PATH" >&2 ;; esac
    if [[ $was_running -eq 1 ]]; then run=1; fi
fi

if [[ $run -eq 1 ]]; then
    if [[ $install -eq 1 ]]; then cmd=("$BIN_DIR/qdvc-progress"); else cmd=(python3 "$STAGE/qdvc_progress.py"); fi
    say "Starting QDVC Progress"
    nohup "${cmd[@]}" >/dev/null 2>&1 &
fi
say "Done"
