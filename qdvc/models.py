"""Projects, their inactive periods, and programmes of work (``projects.yml``)."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from .dates import Date, DayRange
from .naming import slug
from .settings import ExtraField

NO_PROGRAMME_TITLE = "No Programme"


@dataclass
class InactivePeriod:
    """A run of days on which a project was set aside (on hold, waiting, on
    leave), with an optional label shown across the run in the grid. This is
    separate from the project-level active flag."""

    range: DayRange
    label: str = ""
    extras: list[ExtraField] = field(default_factory=list)
    #: In memory only, so the UI can tell periods apart while editing.
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Project:
    """A project: one row of the grid."""

    #: The stable key that ties the project to its log rows. Made from the
    #: title when the project is created and never changed afterwards.
    key: str
    title: str
    #: The optional project ID, conventionally NNXX (e.g. 26XY). Called
    #: ``id`` in projects.yml; ``code`` here to keep it apart from ``key``.
    code: str = ""
    #: The programme of work; empty for none.
    programme: str = ""
    target: str = ""
    collaborators: str = ""
    #: The project-level flag; inactive projects can be hidden with the
    #: Status filter and keep all their history.
    is_active: bool = True
    inactive_periods: list[InactivePeriod] = field(default_factory=list)
    extras: list[ExtraField] = field(default_factory=list)

    @staticmethod
    def is_conventional_code(code: str) -> bool:
        """Whether ``code`` has the NNXX form: two digits, then two letters."""
        return (len(code) == 4 and code[:2].isascii() and code[:2].isdigit()
                and code[2:].isascii() and code[2:].isalpha())

    def inactive_period(self, d: Date) -> InactivePeriod | None:
        for p in self.inactive_periods:
            if p.range.contains(d):
                return p
        return None

    def is_inactive(self, d: Date) -> bool:
        return self.inactive_period(d) is not None

    def set_inactive(self, inactive: bool, days) -> None:
        """Marks ``days`` inactive (merging with neighbouring periods, whose
        label the merged period keeps) or active again (splitting periods
        around them)."""
        days = list(days)
        if not days:
            return
        if inactive:
            periods = list(self.inactive_periods)
            for d in sorted(set(days)):
                if not any(p.range.contains(d) for p in periods):
                    periods.append(InactivePeriod(DayRange(d, d)))
            self.inactive_periods = merged(periods)
            return
        removing = set(days)
        out: list[InactivePeriod] = []
        for p in self.inactive_periods:
            pdays = p.range.days
            if not any(d in removing for d in pdays):
                out.append(p)
                continue
            runs: list[DayRange] = []
            start = previous = None
            for d in pdays:
                if d in removing:
                    if start is not None and previous is not None:
                        runs.append(DayRange(start, previous))
                    start = None
                elif start is None:
                    start = d
                if d not in removing:
                    previous = d
            if start is not None and previous is not None:
                runs.append(DayRange(start, previous))
            for i, r in enumerate(runs):
                out.append(InactivePeriod(r, p.label, list(p.extras),
                                          p.id if i == 0 else uuid.uuid4().hex))
        self.inactive_periods = sorted(out, key=lambda p: p.range.start)

    @property
    def search_text(self) -> str:
        """Text the search field matches against."""
        return "\n".join([self.code, self.title, self.programme, self.target,
                          self.collaborators]).lower()


def merged(periods: list[InactivePeriod]) -> list[InactivePeriod]:
    """Sorted, with overlapping or adjoining periods joined. A joined period
    keeps the first non-empty label among those it was made from."""
    out: list[InactivePeriod] = []
    for p in sorted(periods, key=lambda p: p.range.start):
        if out and out[-1].range.overlaps_or_touches(p.range):
            last = out[-1]
            last.range = DayRange(last.range.start, max(last.range.end, p.range.end))
            if not last.label.strip():
                last.label = p.label
        else:
            out.append(copy.copy(p))
    return out


@dataclass
class Programme:
    """A programme of work: a named group of projects."""

    name: str
    extras: list[ExtraField] = field(default_factory=list)


@dataclass
class ProjectList:
    """The contents of ``projects.yml``: the programmes in order, and the
    projects in order. A project's ``programme`` names its group; projects
    with an empty or unknown programme are listed under No Programme."""

    programmes: list[Programme] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    extras: list[ExtraField] = field(default_factory=list)

    def copy(self) -> "ProjectList":
        return copy.deepcopy(self)

    def project(self, key: str) -> Project | None:
        for p in self.projects:
            if p.key == key:
                return p
        return None

    def index(self, key: str) -> int | None:
        for i, p in enumerate(self.projects):
            if p.key == key:
                return i
        return None

    @property
    def programme_names(self) -> list[str]:
        return [p.name for p in self.programmes]

    def project_with_code(self, code: str, excluding: str | None = None) -> Project | None:
        """The project whose ID is ``code`` (ignoring case and surrounding
        spaces), other than ``excluding``. None for an empty code."""
        c = code.strip().lower()
        if not c:
            return None
        for p in self.projects:
            if p.key != excluding and p.code.strip().lower() == c:
                return p
        return None

    def group(self, project: Project) -> str:
        """The programme a project is grouped under: its own if it exists,
        otherwise "" (No Programme)."""
        return project.programme if project.programme in self.programme_names else ""

    def new_key(self, title: str) -> str:
        """A new, unused key made from ``title``, with ``-2``, ``-3``… if taken."""
        base = slug(title)
        taken = {p.key for p in self.projects}
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"


def programme_title(name: str) -> str:
    return name if name else NO_PROGRAMME_TITLE
