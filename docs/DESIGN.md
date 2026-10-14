# QDVC Progress — Design (GNOME edition)

This is the GTK 4 / libadwaita port of
[QDVC Progress for macOS](https://github.com/qdvc-apps/qdvc-progress-mac).
The model, the grid and the file format are the same; the window around
them follows the GNOME Human Interface Guidelines instead of macOS's. The
macOS edition's `docs/DESIGN.md` explains the grid, the colours and the
workload numbers; this file records what changed in the port, and why.

## 1. Principles (unchanged)

- **The grid is the app.** Everything done daily happens in one
  spreadsheet-like view; everything else is a dialog, a menu or the side
  panel.
- **The workspace is a plain folder** of YAML and CSV, shaped for Git, and
  shared with the macOS edition byte for byte.
- **The keyboard is fast:** with a cell selected, one key sets a label.

## 2. From a Mac window to a GNOME window

| macOS edition | GNOME edition | Precedent |
| --- | --- | --- |
| Menu bar (File, Edit, View, Day, Project) | Header bar buttons, a **View Options** menu, the **main menu**, context menus, shortcuts | HIG: no menu bars; "primary menu" with Preferences, Keyboard Shortcuts, About last |
| Toolbar ‹ Today › (Calendar) | **+** then **‹ Today ›** and a date-picker button at the start of the header bar | GNOME Calendar |
| Programme and Status pop-ups, Sort menu in the toolbar | One **View Options** menu: programme, status, sort, columns, totals, and a day-width control | Files' view menu; Text Editor's zoom row |
| Toolbar search field | Search button (Ctrl+F) revealing a **search bar** | Files, Settings, Calendar |
| Inspector (⌥⌘I) with a Day/Project segmented control | **Side panel** (F9) with its own header bar and a Day/Project **view switcher**; slides over the grid below 860 sp | Files' sidebar toggle (F9); adaptive `AdwOverlaySplitView` |
| Settings window (⌘,) | **Preferences dialog**, applied live | `AdwPreferencesDialog` |
| Sheets | **Dialogs** with Cancel at the start and the action at the end of their header bar; short questions as alert dialogs with an entry | HIG dialogs |
| Confirmation for Delete Programme | Deleted at once, with **Undo** in a notification (toast); Delete Project still asks, as it removes logged days | HIG: prefer undo to confirmation |
| Banners for unreadable files and failed saves | **`AdwBanner`** below the header bar ("Show in Files", "Dismiss") | HIG banners |
| Welcome screen, "No Projects Yet" | **Status pages**, with recent workspaces as a boxed list | HIG placeholder pages |
| NSPopover note callouts | `GtkPopover` callouts, same timing | — |
| ⌥⌘1 … ⌥⌘8 label shortcuts | Not carried over: the plain keys (1–5, m, p, !, v, x, ?) work in the grid, and the context menu lists every label | — |

The window has no sidebar on the left, for the reason the macOS edition
gives: the useful view is many projects across many days, and a sidebar
would take width away from the days. Filtering by programme, which a
sidebar would otherwise do, is in the View Options menu and on Alt+0 …
Alt+9 (as GNOME apps use Alt+number to switch views).

## 3. The header bar

```
[+] [‹][Today][›] [📅]      workspace · All programmes · 8 of 9      [🔍] [⇅] [▯] [☰]
```

- **+** New Project. **‹ Today ›** move a week back or forward and return
  to today; the **calendar** button picks a day (Ctrl+G).
- The **title** is the workspace folder; the subtitle summarises the filter
  (programme, status, how many projects are shown).
- **Search** reveals the filter bar. **View Options** (⇅) holds the
  programme and status filters, the Sort, Columns and Totals submenus,
  Expand/Collapse All and the day-width control. **▯** shows or hides the
  side panel. The **main menu** (☰) holds New Project and New Programme;
  Open Workspace, Open Recent, Show in Files and Close Workspace; Week
  Labels, Go to Date and Refresh from Disk; then Preferences, Keyboard
  Shortcuts and About, as the HIG asks.

The calendar-style ‹ Today › group is deliberately the same as GNOME
Calendar's, so moving through time feels the same as in the calendar people
already use.

## 4. The grid

The grid is the macOS edition's, drawn with cairo in one custom widget
(`gtk4_grid.ProgressGrid`), with the header, the project columns and the
totals frozen around the scrolling body. The widget implements
`GtkScrollable` inside a `GtkScrolledWindow`, so it gets GNOME's overlay
scrollbars and kinetic touchpad scrolling. Only the visible rows and days
are drawn (a full redraw of a large window takes about 10 ms), and the range
of days grows when you scroll near either end.

Neutral colours (backgrounds, text, lines, the selection) come from the
libadwaita theme, so the grid follows light and dark styles and the accent
colour; the label and totals colours are the macOS edition's, so a workspace
looks the same on both. Fonts are sized from the desktop's interface font,
and the grid's geometry scales with it (Large Text works).

A spreadsheet is the one place where GNOME's own list widgets
(`GtkColumnView`) do not fit: frozen rows and columns, per-cell drawing,
rectangular selection and thousands of cells. Everything around the grid is
standard libadwaita.

## 5. Interaction

As in the macOS edition (its DESIGN.md §5): click, Shift-click or drag to
select; click a day heading for that day, a week label for the week; type
labels; Return or double-click edits the note in the side panel (Esc
returns to the grid); Space shows or hides the side panel. Differences:

- Moving a week is **Alt+← / Alt+→** (GNOME's back/forward), also
  Ctrl+[ / Ctrl+]. Moving a project is **Alt+↑ / Alt+↓**.
- **Paste Special** is Ctrl+Shift+V, as in LibreOffice: a small menu of the
  three paste modes beside the selected cell.
- **Undo and Redo** are Ctrl+Z / Ctrl+Shift+Z while the grid has the focus
  (in a text field, they undo the typing, as usual). Undo and Redo show what
  they did in a notification.
- Date fields (inactive periods, Go to Date) use calendar pickers, never
  typed dates.

## 6. Decisions taken in the port

| Question | Decision |
| --- | --- |
| Language | Python 3 with PyGObject, the QDVC GTK family's language: nothing to compile, so rebuilding and reinstalling takes seconds, and the pure core is unit-tested without a display. |
| GTK 3 front-end | None: GTK 4 and libadwaita only (docs/MAINTENANCE.md §4). |
| Minimum libadwaita | 1.5 (GNOME 46), for `AdwDialog`, `AdwAlertDialog`, `AdwPreferencesDialog`, `AdwBreakpoint`, `AdwSpinRow`. |
| App icon | A GNOME-style icon of its own (tools/make_icon.py), in the same motif as the macOS icon. |
| Application ID and launcher | `qdvc.Progress`; the launcher is `qdvc.Progress.desktop` so GNOME Shell matches the window on Wayland. |
| Workspace format | Unchanged; checked byte for byte against files the macOS edition wrote. |
