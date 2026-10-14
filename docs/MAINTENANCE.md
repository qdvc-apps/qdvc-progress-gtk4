# QDVC Progress — Maintenance Guide

The shared conventions of the QDVC GTK apps are in the
**QDVC Python desktop applications specification**,
<https://github.com/qdvc-apps/qdvc-python-gtk-app-specification/>. This guide
covers only what is specific to this app, and every place it departs from
the specification (§4).

The one rule that matters most: **the workspace is the contract.** The files
the app writes are documented in [FILE_FORMAT.md](FILE_FORMAT.md), shared
with [QDVC Progress for macOS](https://github.com/qdvc-apps/qdvc-progress-mac),
and checked by the tests. Any change to a file name or to the bytes of a
file is a format change: update FILE_FORMAT.md, the tests and the macOS
edition together.

## 1. Layout

```
qdvc_progress.py          entry point (checks Python, GTK 4, libadwaita ≥ 1.5)
qdvc/                     pure core: no GTK imports
qdvc/gtk4/                the GTK 4 / libadwaita front-end (every module gtk4_*)
tests/                    test_core.py (model, files, parity, session),
                          test_gtk4_smoke.py (stub-gi imports; window build with a display)
tests/stubs/gi/           the permissive fake gi used by the smoke test
data/                     qdvc.Progress.desktop.in, icons (generated)
tools/make_icon.py        regenerates data/icons/
tools/snapshot.py         renders the UI to PNGs without a desktop (xvfb-run)
scripts/build-app.sh      checks, tests, stages build/, installs to ~/.local
sample-workspace/         the macOS edition's sample (Aug–Oct 2026)
docs/                     DESIGN, FILE_FORMAT, this guide, screenshots
```

The app began as a port of the macOS edition and shares no code with it;
this repository builds, runs and tests on its own.

## 2. Modules

Pure core (`qdvc/`), with the macOS file each was ported from:

| Module | Responsibility | macOS origin |
| --- | --- | --- |
| `dates.py` | days (`datetime.date`), Mondays, ISO weeks, `MonthKey`, `DayRange` | `Dates.swift` |
| `labels.py` | `CellLabel` (sizes, specials, lenient parsing, keys), `Cell`, `PasteMode` | `Labels.swift` |
| `settings.py` | `WorkloadSettings`, presets, `ExtraField` (unknown YAML keys) | `Settings.swift` |
| `models.py`, `naming.py` | `Project` (inactive-day merge/split), `InactivePeriod`, `Programme`, `ProjectList`; key slugs | `Projects.swift` |
| `log.py` | `ProgressLog` (cells by day and project, totals, last worked), `heat_level` | `Log.swift` |
| `query.py` | filter, search, sort → `LayoutRow`s | `Query.swift` |
| `week_labels.py` | `WeekLabels`, spreadsheet date reader, import preview | `WeekLabels.swift` |
| `clipboard.py` | `CellClip`: the app's clipboard format, text from other apps | `Clipboard.swift` |
| `csvio.py`, `yamlio.py` | RFC 4180 CSV; YAML nodes with explicit styles | `CSV.swift`, `YAMLSupport.swift` |
| `files.py`, `workspace.py` | `projects.yml`, `progress.yml`, log files; loading, atomic writes, protected files, change detection | `WorkspaceFiles.swift`, `Workspace.swift` |
| `session.py` | all window state and actions: selection, labels, notes, paste, projects, programmes, periods, week labels, debounced saves, undo | `AppModel*.swift` |
| `undo.py` | undo manager with NSUndoManager's undo/redo semantics | (AppKit) |
| `config.py`, `ui_prefs.py`, `style.py` | preferences; shortcuts table, columns, formatting; colours | `Prefs.swift`, `GridStyle.swift` |

Front-end (`qdvc/gtk4/`):

| Module | Responsibility |
| --- | --- |
| `gtk4_app.py` | `Adw.Application`: accelerators from `ui_prefs.SHORTCUTS`, CSS, icon name, `app.quit` |
| `gtk4_window.py` | the window: header bar, search bar, banners, welcome and empty states, split view, menus, toasts |
| `gtk4_actions.py` | every `win.*` action, its enabled/checked state (`_update_actions`), clipboard I/O |
| `gtk4_grid.py` | `ProgressGrid` (drawing, mouse, keyboard, context menus, tooltips), `Metrics`, `NoteCallout` |
| `gtk4_paint.py` | cairo/Pango drawing shared by the grid, side panel and Preferences; theme palette; `LabelChip` |
| `gtk4_side_panel.py` | the side panel: Day and Project pages |
| `gtk4_dialogs.py` | New Project, programme name, week label, confirmations, `DateButton`, Go to Date |
| `gtk4_week_labels.py` | Week Labels dialog (paste preview, current labels) |
| `gtk4_preferences.py` | Preferences dialog (Workload, General) |
| `gtk4_shortcuts.py` | Keyboard Shortcuts window from `ui_prefs.SHORTCUTS` |

### 2.1 How the window stays in sync

The front-end never changes the model directly: it calls `Session` methods.
After every change the session calls `bump()`, which emits `"changed"` to its
listeners. The grid reloads its geometry at once (so a range that grew at
the start keeps the same day at the left edge) and queues a redraw; the
window coalesces the rest into one idle refresh (`_refresh_ui`): title,
banners, empty states, menus, action states and the side panel. The side
panel updates its widgets in place and never overwrites a field you are
typing in; every handler that writes to the session is guarded by an
`updating` flag.

`"scroll-to"` and `"focus-grid"` events ask the grid to scroll to a day or
take the keyboard focus.

### 2.2 How changes reach the disk

As in the macOS edition: `apply_cells` writes the months it touches at once
(a note: after 0.6 s, via `flush_saves`) and registers one undo step; project
changes go through `update_projects` / `replace_projects` (typing in a
field: after 0.6 s); week labels through `replace_week_labels`; settings
through `update_settings` (no undo). `flush_saves` runs when the focused
cell changes, when the window loses the focus or closes, before reloading,
and at quit. The debounce uses `Session.scheduler`, which the window backs
with GLib timeouts and the tests leave inert.

## 3. Behaviour to preserve

- Rendering the macOS edition's files gives the same bytes
  (`ParityTests`). `yamlio.text()` decides plain, single-quoted or literal
  style exactly as the macOS `YamlIO.str` does, and PyYAML's emitter, like
  Yams', descends from libyaml.
- Project keys never change once written; titles can.
- Unknown YAML keys survive a round trip (composed nodes are written back).
- A file that could not be read is never overwritten (`ProtectedFileError`).
- Inactive periods stay sorted, merged and non-overlapping.
- Weeks are Monday–Sunday everywhere.
- Atomic writes keep the file mode (mkstemp's private 0600 is not kept).
- The grid's adjustments must be configured whenever `Metrics` changes
  (`ProgressGrid._configure`), or the scrollbars disagree with the content.
- Grid lines are whole device pixels: `_draw` rounds the scroll offset to
  device pixels, and thin lines are `self._px` wide (one device pixel, more
  under fractional scaling) at whole-pixel positions. Never draw a 0.5-unit
  line or offset a line by 0.5: on a 1× screen cairo blends it over two
  pixels at half strength, and the grid looks washed out.
- The neutral strengths are the macOS edition's *effective* values, named in
  `gtk4_paint.Palette`: grid lines 35 % foreground, header rules 50 %,
  separators 10 %, panes #ECECEC-like (`PANE_TINT`), weekends 4.5 %. Note
  that AppKit's `withAlphaComponent(x)` replaces a colour's alpha rather than
  scaling it, so `separatorColor.withAlphaComponent(0.35)` is 35 % black, not
  35 % of the separator. The inactive hatching (`HATCH`) and dimmed text
  (`GREY_CONTRAST`) are deliberately a little stronger than on macOS, as
  GNOME's antialiasing renders them lighter.

## 4. Deviations from the specification

| Spec | This app | Why |
| --- | --- | --- |
| §1, §2, §3, §8: GTK 3 primary front-end, GTK 4 parallel, `--gtk3`/`--gtk4` dispatcher, `ui_backend` | **GTK 4 / libadwaita only.** No `qdvc/gtk3/`, no dispatcher, no backend selector in Preferences; `--gtk4` is accepted and ignored. | Requested for this app (a GNOME-native port). The layout keeps `qdvc/` pure and `qdvc/gtk4/` separate, so a GTK 3 front-end can be added later without touching the core. |
| §7.3: a stock themed icon by default, no bundled image | A bundled icon, `qdvc.Progress` (data/icons), installed into the user's hicolor theme; `x-office-spreadsheet` is used when it is not installed (running from a checkout). No custom-icon preference. | The app should be recognisable in the Dock and Activities. GTK 4 windows take only themed icon names, so a custom-file preference would not reach the window. |
| §7.4: launcher at `~/.local/share/applications/qdvc-<app>.desktop` | `qdvc.Progress.desktop`, installed by `scripts/build-app.sh`, with `StartupWMClass=qdvc-progress`. | GNOME Shell on Wayland matches a window to its launcher by the application ID, so the file must be named after it; StartupWMClass still covers X11. |
| §9: `Adw.PreferencesWindow`, `Adw.MessageDialog`, `Adw.AboutWindow` | `Adw.PreferencesDialog`, `Adw.AlertDialog`, `Adw.AboutDialog` (libadwaita 1.5). | The window forms are deprecated from libadwaita 1.6; the dialog forms adapt to narrow windows. |
| §9: lists and tables in `Gtk.ColumnView` | The grid is one custom-drawn `GtkScrollable` widget. | Frozen rows and columns, rectangular selection and per-cell drawing; see DESIGN.md §4. Every other list is a libadwaita boxed list. |
| §6: optional disposable index | None. | A workspace is a few small files; loading takes milliseconds. |
| §6: `validate()` report | Load problems are reported per file in a banner, and unreadable files are protected. | The same information, where it is needed; there are no cross-file references to check. |
| §10: Ctrl+W closes the workspace in some apps | Ctrl+W closes the window (GNOME's standard); Close Workspace is Ctrl+Shift+W. | Single-window app. |

## 5. Tasks

**Add a command.** Add the `win.*` action in `gtk4_actions._install_actions`,
its enabled state in `_update_actions`, the menu item where it belongs
(`gtk4_window._build_main_menu` / `_build_view_menu`, or a context menu in
`gtk4_grid`), and, with a shortcut, an entry in `ui_prefs.SHORTCUTS` (which
registers the accelerator and lists it in the Keyboard Shortcuts window).

**Change the model.** Put the logic in `session.py` (or a pure module) with
a test in `tests/test_core.py`; the front-end only calls it.

**Change the file format.** Don't, without the macOS edition: update
FILE_FORMAT.md, `files.py`, the parity test and the Swift `WorkspaceFiles`
together.

**Change the icon.** Edit the constants in `tools/make_icon.py` and run it;
`--preview` writes `build/icon-preview.png`.

**Check the UI without a desktop.**
`xvfb-run -a python3 tools/snapshot.py /tmp/shots` (add `--dark`) renders
the welcome page, grid, side panel, dialogs and the narrow layout to PNGs.

## 6. Tests

```sh
python3 -m unittest discover -s tests       # also run by scripts/build-app.sh
```

`test_core.py` ports the macOS `CoreTests` (dates, labels, CSV, log files,
totals, inactive days, slugs, `projects.yml` and `progress.yml` round trips,
queries, the spreadsheet date reader, week-label import, the clipboard, the
workspace), adds the parity test against `sample-workspace/`, and tests the
session on a copy of the sample: labels, undo/redo, debounced notes, block
paste, inactive days, new/move/delete project with undo, programmes, totals
under a filter, week labels, settings and external changes.
`test_gtk4_smoke.py` imports every `qdvc.gtk4` module against a stub `gi`
(no GTK needed) and, with a display, builds the window on the sample.

## 7. Roadmap

- Export a period as CSV or a printable report (per programme, per week).
- A year view: one small heat-map square per day.
- Drag rows to reorder projects.
- Keyboard focus for the side panel's label buttons from the grid (F6 to
  cycle panes, as in Files).
- A GTK 3 front-end, if ever wanted (spec §8), on the same core.
