"""Workload settings (``progress.yml``): how labels turn into numbers, and
how the totals are coloured. Saved in the workspace so it travels with the
data (docs/FILE_FORMAT.md §2)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .labels import CellLabel


@dataclass
class ExtraField:
    """A key the app does not know, kept as read (a composed YAML node) so
    that saving never loses what someone, or a newer version, put in a file."""

    key: str
    value: object  # a yaml.Node

    def __eq__(self, other):
        # yaml.Node has no value equality; compare what it would write.
        if not isinstance(other, ExtraField) or self.key != other.key:
            return False
        return self.value is other.value or repr(self.value) == repr(other.value)


@dataclass(frozen=True)
class SizePreset:
    """A named mapping from the five work sizes to numbers."""

    id: str
    name: str
    values: tuple[int, ...]
    detail: str


LINEAR = SizePreset(
    "linear", "Linear", (1, 2, 3, 4, 5),
    "Each size is one step more than the last. Simple to add up in your head.")
FIBONACCI = SizePreset(
    "fibonacci", "Fibonacci", (1, 2, 3, 5, 8),
    "The big days weigh more: an XL day counts as much as eight XS days. Felt "
    "effort grows faster than linearly, which is why agile teams estimate with "
    "this scale.")
DOUBLING = SizePreset(
    "doubling", "Doubling", (1, 2, 4, 8, 16),
    "Each size is twice the last. Makes one exhausting day stand out sharply "
    "in the totals.")
PRESETS = [LINEAR, FIBONACCI, DOUBLING]


def _normalised(values) -> list[int]:
    v = list(values)[:5]
    while len(v) < 5:
        v.append(LINEAR.values[len(v)])
    return v


@dataclass
class WorkloadSettings:
    #: The numbers for XS, S, M, L, XL, in that order.
    size_values: list[int] = field(default_factory=lambda: list(LINEAR.values))
    #: The size a meeting counts as.
    meeting_size: CellLabel = CellLabel.M
    due_value: int = 0
    planned_value: int = 0
    #: The daily total at which the totals colour is deepest. The working
    #: week (Monday–Friday) peaks at five times this, the weekend at twice it.
    day_peak: int = 15
    extras: list[ExtraField] = field(default_factory=list)

    def __post_init__(self):
        self.size_values = _normalised(self.size_values)
        if not self.meeting_size.is_size:
            self.meeting_size = CellLabel.M
        self.day_peak = max(1, self.day_peak)

    def value(self, label: CellLabel | None) -> int:
        """The number a label adds to the totals."""
        if label is None:
            return 0
        i = label.size_index
        if i is not None:
            return self.size_values[i]
        if label is CellLabel.MEETING:
            idx = self.meeting_size.size_index
            return self.size_values[2 if idx is None else idx]
        if label is CellLabel.DUE:
            return self.due_value
        if label is CellLabel.PLANNED:
            return self.planned_value
        return 0  # tick, cross, information

    @property
    def matching_preset(self) -> SizePreset | None:
        for p in PRESETS:
            if tuple(self.size_values) == p.values:
                return p
        return None

    @property
    def week_peak(self) -> int:
        return self.day_peak * 5

    @property
    def weekend_peak(self) -> int:
        return self.day_peak * 2

    def copy(self) -> "WorkloadSettings":
        return WorkloadSettings(list(self.size_values), self.meeting_size, self.due_value,
                                self.planned_value, self.day_peak, list(self.extras))
