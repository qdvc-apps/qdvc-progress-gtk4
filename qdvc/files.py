"""Reading and writing the workspace's files (docs/FILE_FORMAT.md).

The output is byte-for-byte what the macOS edition writes, so the two can
share one workspace (tests/test_parity.py checks this against
``sample-workspace/``).
"""

from __future__ import annotations

from . import csvio
from . import yamlio as Y
from .dates import Date, DayRange, MonthKey, parse_iso
from .labels import SIZES, Cell, CellLabel
from .log import LogEntry
from .models import InactivePeriod, Programme, Project, ProjectList, merged
from .settings import ExtraField, WorkloadSettings

# --- projects.yml ---------------------------------------------------------

_PROJECT_KEYS = ["key", "id", "title", "programme", "target", "collaborators", "active",
                 "inactive_periods"]


def _one(node) -> str:
    s = Y.string(node)
    return Y.one_line(s) if s is not None else ""


def _add_programme(plist: ProjectList, p: Programme) -> None:
    if p.name and p.name not in plist.programme_names:
        plist.programmes.append(p)


def parse_projects(text: str) -> tuple[ProjectList, list[str]]:
    """The list, and a description of every entry that had to be repaired
    or skipped. Raises :class:`yamlio.FileError` for an unreadable file."""
    plist = ProjectList()
    problems: list[str] = []
    project_nodes = []
    for k, v in Y.mapping_pairs(text):
        if k == "programmes":
            for item in Y.sequence(v):
                name = Y.string(item)
                if name is not None:
                    _add_programme(plist, Programme(Y.one_line(name)))
                    continue
                try:
                    pp = Y.pairs(item)
                except Y.FileError:
                    continue
                name, extras = "", []
                for pk, pv in pp:
                    if pk == "name":
                        name = _one(pv)
                    else:
                        extras.append(ExtraField(pk, pv))
                if not name:
                    problems.append("A programme has no name and was skipped.")
                else:
                    _add_programme(plist, Programme(name, extras))
        elif k == "projects":
            project_nodes = Y.sequence(v)
        else:
            plist.extras.append(ExtraField(k, v))

    for i, node in enumerate(project_nodes):
        try:
            pp = Y.pairs(node)
        except Y.FileError:
            problems.append(f"Project {i + 1} is not a mapping and was skipped.")
            continue
        values: dict = {}
        extras: list[ExtraField] = []
        for k, v in pp:
            if k in _PROJECT_KEYS:
                values.setdefault(k, v)
            else:
                extras.append(ExtraField(k, v))
        title = _one(values.get("title"))
        key = _one(values.get("key"))
        if not title and not key:
            problems.append(f"Project {i + 1} has neither a key nor a title and was skipped.")
            continue
        if not title:
            title = key
        if not key:
            key = plist.new_key(title)
            problems.append(f"\u201c{title}\u201d had no key; it was given \u201c{key}\u201d.")
        elif plist.project(key) is not None:
            fresh = plist.new_key(key)
            problems.append(f"The key \u201c{key}\u201d is used twice; the second project was "
                            f"given \u201c{fresh}\u201d.")
            key = fresh

        periods: list[InactivePeriod] = []
        for j, pn in enumerate(Y.sequence(values.get("inactive_periods"))):
            try:
                ppairs = Y.pairs(pn)
            except Y.FileError:
                continue
            start = end = None
            label = ""
            pextras: list[ExtraField] = []
            for k, v in ppairs:
                if k == "from":
                    s = Y.string(v)
                    start = parse_iso(s) if s is not None else None
                elif k == "to":
                    s = Y.string(v)
                    end = parse_iso(s) if s is not None else None
                elif k == "label":
                    label = _one(v)
                else:
                    pextras.append(ExtraField(k, v))
            if start is None:
                problems.append(f"Inactive period {j + 1} of \u201c{title}\u201d has no valid "
                                "from date and was skipped.")
                continue
            periods.append(InactivePeriod(DayRange(start, end or start), label, pextras))

        programme = _one(values.get("programme"))
        if programme:
            _add_programme(plist, Programme(programme))
        active = Y.boolean(values.get("active"))
        plist.projects.append(Project(
            key=key, title=title, code=_one(values.get("id")), programme=programme,
            target=_one(values.get("target")), collaborators=_one(values.get("collaborators")),
            is_active=True if active is None else active,
            inactive_periods=merged(periods), extras=extras))
    return plist, problems


def _project_node(p: Project):
    items = [(Y.key("key"), Y.text(p.key))]

    def add(k: str, v: str):
        t = Y.one_line(v)
        if t:
            items.append((Y.key(k), Y.text(t)))

    add("id", p.code)
    add("title", p.title)
    add("programme", p.programme)
    add("target", p.target)
    add("collaborators", p.collaborators)
    if not p.is_active:
        items.append((Y.key("active"), Y.flag(False)))
    if p.inactive_periods:
        nodes = []
        for period in p.inactive_periods:
            pp = [(Y.key("from"), Y.date(period.range.start)),
                  (Y.key("to"), Y.date(period.range.end))]
            label = Y.one_line(period.label)
            if label:
                pp.append((Y.key("label"), Y.text(label)))
            pp.extend((Y.key(e.key), e.value) for e in period.extras)
            nodes.append(Y.mapping(pp))
        items.append((Y.key("inactive_periods"), Y.seq(nodes)))
    items.extend((Y.key(e.key), e.value) for e in p.extras)
    return Y.mapping(items)


def render_projects(plist: ProjectList) -> str:
    """``programmes`` (in order), then ``projects`` (in order), then unknown
    keys. Within a project: key, id, title, programme, target,
    collaborators, active (only when false), inactive_periods, then unknown
    keys. Empty fields are left out."""
    programmes = []
    for p in plist.programmes:
        pp = [(Y.key("name"), Y.text(Y.one_line(p.name)))]
        pp.extend((Y.key(e.key), e.value) for e in p.extras)
        programmes.append(Y.mapping(pp))
    items = [(Y.key("programmes"), Y.seq(programmes)),
             (Y.key("projects"), Y.seq([_project_node(p) for p in plist.projects]))]
    items.extend((Y.key(e.key), e.value) for e in plist.extras)
    return Y.emit(Y.mapping(items))


# --- progress.yml ---------------------------------------------------------

FORMAT_VERSION = 1


def parse_settings(text: str) -> WorkloadSettings:
    s = WorkloadSettings()
    extras: list[ExtraField] = []
    for k, v in Y.mapping_pairs(text):
        if k == "format":
            continue
        if k == "sizes":
            values = list(s.size_values)
            try:
                size_pairs = Y.pairs(v)
            except Y.FileError:
                size_pairs = []
            for sk, sv in size_pairs:
                label = CellLabel.lenient(sk)
                n = Y.integer(sv)
                if label is not None and label.is_size and n is not None:
                    values[label.size_index] = n
            s.size_values = values
        elif k == "meeting_size":
            t = Y.string(v)
            label = CellLabel.lenient(t) if t is not None else None
            if label is not None and label.is_size:
                s.meeting_size = label
        elif k == "due_value":
            n = Y.integer(v)
            if n is not None:
                s.due_value = n
        elif k == "planned_value":
            n = Y.integer(v)
            if n is not None:
                s.planned_value = n
        elif k == "day_peak":
            n = Y.integer(v)
            if n is not None and n > 0:
                s.day_peak = n
        else:
            extras.append(ExtraField(k, v))
    s.extras = extras
    return s


def render_settings(s: WorkloadSettings) -> str:
    sizes = [(Y.key(label.text), Y.number(s.size_values[i])) for i, label in enumerate(SIZES)]
    items = [
        (Y.key("format"), Y.number(FORMAT_VERSION)),
        (Y.key("sizes"), Y.mapping(sizes)),
        (Y.key("meeting_size"), Y.text(s.meeting_size.text)),
        (Y.key("due_value"), Y.number(s.due_value)),
        (Y.key("planned_value"), Y.number(s.planned_value)),
        (Y.key("day_peak"), Y.number(s.day_peak)),
    ]
    items.extend((Y.key(e.key), e.value) for e in s.extras)
    return Y.emit(Y.mapping(items))


# --- log/yyyy/yyyy-mm.csv -------------------------------------------------

LOG_HEADER = ["date", "project", "label", "note"]


def parse_log(text: str, month: MonthKey | None = None) -> tuple[list[LogEntry], list[str]]:
    """The entries of one month's file, and a description of each row that
    could not be read (a file with problems is never rewritten)."""
    rows = csvio.parse(text)
    cols = {"date": 0, "project": 1, "label": 2, "note": 3}
    if rows and rows[0] and rows[0][0].strip().lower() == "date":
        names = [n.strip().lower() for n in rows[0]]
        cols = {name: (names.index(name) if name in names else default)
                for name, default in cols.items()}
        rows = rows[1:]
    entries: list[LogEntry] = []
    problems: list[str] = []
    for i, row in enumerate(rows):
        line = i + 2

        def cell(name: str) -> str:
            c = cols[name]
            return row[c] if c < len(row) else ""

        date_text = cell("date").strip(" \t")
        d = parse_iso(date_text)
        if d is None:
            problems.append(f"line {line}: \u201c{date_text}\u201d is not a yyyy-mm-dd date")
            continue
        if month is not None and MonthKey.of(d) != month:
            problems.append(f"line {line}: {d.isoformat()} is not in {month}")
            continue
        project = cell("project").strip(" \t")
        if not project:
            problems.append(f"line {line}: no project")
            continue
        label_text = cell("label").strip(" \t")
        label = None
        if label_text:
            label = CellLabel.lenient(label_text)
            if label is None:
                problems.append(f"line {line}: \u201c{label_text}\u201d is not a label "
                                "(XS, S, M, L, XL, mtg, (!), (P))")
                continue
        entry = LogEntry(d, project, Cell(label, cell("note")))
        if not entry.cell.is_empty:
            entries.append(entry)
    return entries, problems


def _trim_trailing(s: str) -> str:
    return s.rstrip(" \t\n\r\u2028\u2029\x0b\x0c\x85")


def render_log(entries: list[LogEntry]) -> str:
    rows = sorted((e for e in entries if not e.cell.is_empty), key=lambda e: (e.date, e.project))
    return csvio.render([LOG_HEADER] + [
        [e.date.isoformat(), e.project, e.cell.label.text if e.cell.label else "",
         _trim_trailing(e.cell.note)] for e in rows])


def log_relative_path(month: MonthKey) -> str:
    """``log/2026/2026-10.csv``."""
    return f"log/{month.year:04d}/{month}.csv"
