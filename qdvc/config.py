"""Application preferences: YAML at ``$XDG_CONFIG_HOME/qdvc-progress/config.yml``.

Preferences only. Business data (projects, the log, week labels and the
workload settings) lives in the workspace, so it travels with it.
"""

from __future__ import annotations

import copy
import os
import tempfile

import yaml

from . import PRGNAME

DEFAULTS: dict = {
    "last_workspace": None,
    "recent_workspaces": [],
    "reopen_last": True,
    "window": {"width": 1320, "height": 800, "maximized": False},
    # The project filter, search excepted (docs/DESIGN.md §3).
    "filter_programme": None,          # None = all programmes, "" = No Programme
    "filter_status": "active",
    "sort_key": "manual",
    "sort_ascending": True,
    "group_by_programme": True,
    "inactive_today_last": False,
    "collapsed_programmes": [],
    "hidden_columns": [],
    "column_widths": {},
    "cell_width": 32,
    "totals_scope": "visible",
    "paste_mode": "both",
    "programme_subtotals": True,       # in the programme headings
    "footer_subtotals": True,          # a row per programme above the totals
    "outline_working_week": True,
    "note_callouts": True,
    "iso_week_fallback": True,
    "side_panel_shown": True,
    "date_order": None,                # None = from the locale
}

MAX_RECENTS = 10


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, PRGNAME)


class Config:
    def __init__(self, path: str | None = None, data: dict | None = None):
        self.path = path
        self.data = data or {}

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or os.path.join(config_dir(), "config.yml")
        data = {}
        try:
            with open(path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, yaml.YAMLError):
            pass
        return cls(path, data)

    @classmethod
    def in_memory(cls) -> "Config":
        """A config that is never saved (for tests)."""
        return cls(None, {})

    def get(self, key: str, default=None):
        if key in self.data:
            return self.data[key]
        if default is not None:
            return default
        return copy.deepcopy(DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if self.data.get(key) == value and key in self.data:
            return
        self.data[key] = value
        self.save()

    def save(self) -> None:
        if not self.path:
            return
        folder = os.path.dirname(self.path)
        try:
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=folder)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # --- validated accessors ---------------------------------------------

    def bool(self, key: str) -> bool:
        v = self.get(key)
        return bool(DEFAULTS.get(key)) if not isinstance(v, bool) else v

    def choice(self, key: str, allowed: list[str]) -> str:
        v = self.get(key)
        return v if v in allowed else DEFAULTS[key]

    @property
    def recent_workspaces(self) -> list[str]:
        v = self.get("recent_workspaces")
        return [p for p in v if isinstance(p, str)][:MAX_RECENTS] if isinstance(v, list) else []

    @recent_workspaces.setter
    def recent_workspaces(self, paths: list[str]) -> None:
        self.set("recent_workspaces", list(paths)[:MAX_RECENTS])
