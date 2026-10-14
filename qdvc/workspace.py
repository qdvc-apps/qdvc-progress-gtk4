"""A workspace folder (docs/FILE_FORMAT.md §1). Every write is atomic and
immediate; the files are meant to be committed to Git."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

from . import files
from .dates import MonthKey
from .log import LogEntry, ProgressLog
from .models import ProjectList
from .settings import WorkloadSettings
from .week_labels import WeekLabels
from .yamlio import FileError

SETTINGS_FILE = "progress.yml"
PROJECTS_FILE = "projects.yml"
WEEK_LABELS_FILE = "week-labels.csv"
LOG_FOLDER = "log"

_UMASK = os.umask(0)
os.umask(_UMASK)


@dataclass(frozen=True)
class LoadIssue:
    """A file that could not be read cleanly. A protected file is left alone:
    changes that belong in it are kept in memory but not written until the
    file is fixed and the workspace refreshed."""

    relative_path: str
    messages: tuple[str, ...]
    is_protected: bool


class ProtectedFileError(Exception):
    def __init__(self, path: str):
        super().__init__(f"{path} could not be read when the workspace was opened, so it is "
                         "not being overwritten. Fix the file and refresh the workspace.")
        self.path = path


@dataclass
class WorkspaceContents:
    settings: WorkloadSettings = field(default_factory=WorkloadSettings)
    projects: ProjectList = field(default_factory=ProjectList)
    week_labels: WeekLabels = field(default_factory=WeekLabels)
    log: ProgressLog = field(default_factory=ProgressLog)
    issues: list[LoadIssue] = field(default_factory=list)


def looks_like_workspace(path: str) -> bool:
    """Whether the folder holds a ``progress.yml`` or ``projects.yml``."""
    return (os.path.isfile(os.path.join(path, SETTINGS_FILE))
            or os.path.isfile(os.path.join(path, PROJECTS_FILE)))


class Workspace:
    def __init__(self, root: str):
        self.root = os.path.abspath(os.path.expanduser(root))
        self._stamps: dict[str, tuple[int, int] | None] = {}
        self.protected_files: set[str] = set()

    @property
    def name(self) -> str:
        return os.path.basename(self.root.rstrip(os.sep)) or self.root

    def path(self, relative: str) -> str:
        return os.path.join(self.root, *relative.split("/"))

    def ensure_layout(self) -> None:
        """Creates ``progress.yml``, ``projects.yml`` and ``log/`` where missing."""
        os.makedirs(self.path(LOG_FOLDER), exist_ok=True)
        if not os.path.exists(self.path(SETTINGS_FILE)):
            self._write(files.render_settings(WorkloadSettings()), SETTINGS_FILE)
        if not os.path.exists(self.path(PROJECTS_FILE)):
            self._write(files.render_projects(ProjectList()), PROJECTS_FILE)

    # --- reading ----------------------------------------------------------

    def log_files(self) -> list[tuple[MonthKey, str]]:
        """Every ``log/yyyy/yyyy-mm.csv``, by month."""
        base = self.path(LOG_FOLDER)
        try:
            years = sorted(os.listdir(base))
        except OSError:
            return []
        out = []
        for year in years:
            if len(year) != 4 or not year.isdigit():
                continue
            try:
                names = sorted(os.listdir(os.path.join(base, year)))
            except OSError:
                continue
            for name in names:
                if not name.lower().endswith(".csv"):
                    continue
                month = MonthKey.parse(name[:-4])
                if month is None or f"{month.year}" != year:
                    continue
                out.append((month, f"{LOG_FOLDER}/{year}/{name}"))
        return out

    def _stamp(self, relative: str) -> tuple[int, int] | None:
        try:
            st = os.stat(self.path(relative))
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _read(self, relative: str) -> str | None:
        p = self.path(relative)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            data = f.read()
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise FileError("The file is not UTF-8 text.") from None

    def load(self) -> WorkspaceContents:
        """Reads the whole workspace. A file that cannot be read at all is
        reported and protected from being overwritten; a file read with
        repairs (projects.yml) is reported but may be rewritten."""
        c = WorkspaceContents()
        self._stamps = {}
        self.protected_files = set()

        def note(path: str, messages: list[str], protect: bool):
            if messages:
                c.issues.append(LoadIssue(path, tuple(messages), protect))
                if protect:
                    self.protected_files.add(path)

        for path in (SETTINGS_FILE, PROJECTS_FILE, WEEK_LABELS_FILE):
            self._stamps[path] = self._stamp(path)

        try:
            text = self._read(SETTINGS_FILE)
            if text is not None:
                c.settings = files.parse_settings(text)
        except (FileError, OSError) as e:
            note(SETTINGS_FILE, [str(e)], True)

        try:
            text = self._read(PROJECTS_FILE)
            if text is not None:
                c.projects, problems = files.parse_projects(text)
                note(PROJECTS_FILE, problems, False)
        except (FileError, OSError) as e:
            note(PROJECTS_FILE, [str(e)], True)

        try:
            text = self._read(WEEK_LABELS_FILE)
            if text is not None:
                c.week_labels, problems = WeekLabels.parse_file(text)
                note(WEEK_LABELS_FILE, problems, True)
        except (FileError, OSError) as e:
            note(WEEK_LABELS_FILE, [str(e)], True)

        entries: list[LogEntry] = []
        for month, path in self.log_files():
            self._stamps[path] = self._stamp(path)
            try:
                text = self._read(path)
                if text is None:
                    continue
                parsed, problems = files.parse_log(text, month)
                entries.extend(parsed)
                note(path, problems, True)
            except (FileError, OSError) as e:
                note(path, [str(e)], True)
        c.log = ProgressLog(entries)
        return c

    def has_external_changes(self) -> bool:
        """Whether any file was changed, added or removed since the last load
        or write (by another app, ``git pull``, …)."""
        current = {p: self._stamp(p) for p in (SETTINGS_FILE, PROJECTS_FILE, WEEK_LABELS_FILE)}
        for _, path in self.log_files():
            current[path] = self._stamp(path)
        known = {k: v for k, v in self._stamps.items() if v is not None}
        now = {k: v for k, v in current.items() if v is not None}
        return known != now

    # --- writing ----------------------------------------------------------

    def _write(self, text: str, relative: str) -> None:
        if relative in self.protected_files:
            raise ProtectedFileError(relative)
        target = self.path(relative)
        folder = os.path.dirname(target)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(text.encode("utf-8"))
            # mkstemp makes the file private; give it the mode a normal
            # write would (or keep the mode of the file it replaces).
            try:
                mode = os.stat(target).st_mode & 0o7777
            except OSError:
                mode = 0o666 & ~_UMASK
            os.chmod(tmp, mode)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._stamps[relative] = self._stamp(relative)

    def save_settings(self, s: WorkloadSettings) -> None:
        self._write(files.render_settings(s), SETTINGS_FILE)

    def save_projects(self, plist: ProjectList) -> None:
        self._write(files.render_projects(plist), PROJECTS_FILE)

    def save_week_labels(self, labels: WeekLabels) -> None:
        if labels.is_empty and not os.path.exists(self.path(WEEK_LABELS_FILE)):
            return
        self._write(labels.render_file(), WEEK_LABELS_FILE)

    def save_month(self, month: MonthKey, entries: list[LogEntry]) -> None:
        """Writes one month's log file, or removes it (and an emptied year
        folder) when the month has no entries."""
        path = files.log_relative_path(month)
        if entries:
            self._write(files.render_log(entries), path)
            return
        if path in self.protected_files:
            raise ProtectedFileError(path)
        target = self.path(path)
        if os.path.exists(target):
            os.remove(target)
            folder = os.path.dirname(target)
            try:
                if all(n == ".DS_Store" for n in os.listdir(folder)):
                    for n in os.listdir(folder):
                        os.remove(os.path.join(folder, n))
                    os.rmdir(folder)
            except OSError:
                pass
        self._stamps.pop(path, None)

    def is_protected(self, month: MonthKey) -> bool:
        return files.log_relative_path(month) in self.protected_files
