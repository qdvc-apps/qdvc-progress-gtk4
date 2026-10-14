# QDVC Progress — Workspace File Format

This format is shared, byte for byte, with
[QDVC Progress for macOS](https://github.com/qdvc-apps/qdvc-progress-mac): both
editions can open the same workspace, and rewriting a file the other wrote
changes nothing (`tests/test_core.py`, `ParityTests`).

Format version 1. A workspace is a folder you can commit to Git. Everything
is UTF-8 text with `\n` line ends. YAML is used for structured settings and
lists; CSV for the log, which is a table.

## 1. Layout

```
my-workspace/
├── progress.yml          workload settings (§2)
├── projects.yml          programmes and projects (§3)
├── week-labels.csv       the header's week labels (§5; optional)
└── log/
    └── 2026/
        ├── 2026-09.csv   one file per month with entries (§4)
        └── 2026-10.csv
```

A folder is recognised as a workspace if it holds `progress.yml` or
`projects.yml`. Opening an empty folder creates both and `log/`.

Why this shape, for Git: settings and the project list change rarely and
diff as a few lines; the log grows a month at a time, so each commit
touches one or two small files; and every row of a log file is one
project-day, so a diff reads as "this day, this project, this changed".

The app writes each file atomically (to a temporary file, then renamed) as
soon as a change is made. Unknown YAML keys are kept and written back.

## 2. `progress.yml`

```yaml
format: 1
sizes:
  XS: 1
  S: 2
  M: 3
  L: 4
  XL: 5
meeting_size: M
due_value: 0
planned_value: 0
day_peak: 15
```

| Key | Meaning |
| --- | --- |
| `sizes` | The number each work size adds to the totals. Presets in the app: Linear 1–5 (default), Fibonacci 1, 2, 3, 5, 8, Doubling 1, 2, 4, 8, 16. Any whole numbers are allowed. |
| `meeting_size` | The size a meeting (`mtg`) counts as. |
| `due_value`, `planned_value` | What `(!)` and `(P)` add (normally 0). Tick, cross and information always add 0. |
| `day_peak` | The daily total at which the totals' colour is deepest. Monday–Friday totals peak at 5×, weekends at 2×. |

## 3. `projects.yml`

```yaml
programmes:
- name: Research
- name: Teaching
projects:
- key: arc-discovery-grant
  id: '26AR'
  title: ARC Discovery grant
  programme: Research
  target: DP27 round
  collaborators: M. Chen, R. Okafor
- key: soil-carbon-paper
  title: Soil carbon paper
  programme: Research
  inactive_periods:
  - from: 2026-09-21
    to: 2026-10-02
    label: With co-authors for comments
- key: open-day-2025
  title: Open Day 2025
  programme: Service
  active: false
```

`programmes` lists the programmes of work in display order. A programme
named by a project but missing from the list is added to it on reading.

`projects` lists the projects in their manual order (Move Up / Move Down).
Keys, in the order written:

| Key | Required | Meaning |
| --- | --- | --- |
| `key` | yes | Stable identifier used by the log. Made from the title when the project is created (lower-case ASCII letters, digits and hyphens, at most 40 characters, `-2`… if taken) and never changed by the app, so the title can be edited freely. |
| `id` | no | The project ID, conventionally NNXX (two digits, two letters, e.g. `26XY`). Quoted, as it starts with a digit. |
| `title` | yes | The project's name. |
| `programme` | no | The programme it belongs to; absent for No Programme. |
| `target`, `collaborators` | no | Free text labels. |
| `active` | no | `false` marks the whole project inactive. Absent means active. |
| `inactive_periods` | no | Runs of days the project was set aside: `from`, `to` (inclusive, `yyyy-mm-dd`) and an optional `label` shown across the run. Periods are kept sorted and never overlap or touch (adjoining ones are joined). |

Strings are written plain where YAML reads them back unchanged, and
single-quoted otherwise (`'26XY'`, `'Yes'`).

On reading, a project without a `key` gets one from its title, and a
repeated key gets `-2`…; both are reported, and the repaired keys are
written back on the next change.

## 4. Log files: `log/yyyy/yyyy-mm.csv`

```csv
date,project,label,note
2026-10-05,arc-discovery-grant,M,
2026-10-05,soil-carbon-paper,M,Comments back from Luisa; mostly on the discussion
2026-10-06,arc-discovery-grant,L,"Rewrote the budget justification, as the grants office asked"
2026-10-07,phd-supervision,mtg,"Jai: rehearsal went well.
Next meeting in two weeks"
2026-10-16,arc-discovery-grant,(!),Internal deadline for the full application
```

- One row per project per day that has a label, a note, or both. Empty
  cells are not written; a month with no entries has no file.
- `date` is `yyyy-mm-dd` and must fall in the file's month. `project` is a
  project `key` (§3).
- `label` is one of `XS`, `S`, `M`, `L`, `XL`, `mtg`, `(P)`, or one of the
  emblems `(!)` (due date), `(ok)` (tick), `(x)` (cross), `(i)`
  (information), or empty for a note on its own. On reading, case and
  brackets are forgiven (`xs`, `!`, `p`, `ok`, `x`, `i`), and `✓`, `✔`, `✗`,
  `✘` and `×` are read as tick and cross.
- `note` is free text and may span lines.
- Rows are sorted by date, then by project key. Fields are quoted (with `"`,
  doubled inside) only when they hold a comma, a quote, a line break or
  leading or trailing spaces — standard RFC 4180, so the files open in
  Numbers or Excel.
- Inactive days are not in the log; they are periods in `projects.yml`.

A log file with a row that cannot be read is reported in a banner and is
**not overwritten** until it is fixed and the workspace refreshed (main
menu › Refresh from Disk, Ctrl+R). Changes made meanwhile to that month stay in memory only.

## 5. `week-labels.csv`

```csv
week,label
2026-09-21,Mid-semester break
2026-10-05,Teaching wk 9
```

`week` is the Monday of the week (any other day is moved to its Monday on
reading). Weeks without a label show their ISO week number (W41), which can
be turned off. The file is created when the first label is set.
