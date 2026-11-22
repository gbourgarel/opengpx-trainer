"""Structured workout model: a flat list of steps with linear power ramps."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

PowerUnit = Literal["ftp", "watts"]


@dataclass
class Step:
    duration_s: float
    start: float | None  # None = free ride (no ERG target)
    end: float | None
    unit: PowerUnit = "ftp"  # "ftp" -> fraction of FTP, "watts" -> absolute
    cadence_rpm: int | None = None
    label: str = ""

    def target_at(self, t_in_step: float, ftp_w: float) -> float | None:
        if self.start is None:
            return None
        end = self.start if self.end is None else self.end
        x = min(max(t_in_step / self.duration_s, 0.0), 1.0) if self.duration_s > 0 else 0.0
        v = self.start + (end - self.start) * x
        return v * ftp_w if self.unit == "ftp" else v


@dataclass
class WorkoutPosition:
    step_index: int
    time_in_step_s: float
    step_remaining_s: float
    finished: bool


@dataclass
class Workout:
    name: str
    steps: list[Step] = field(default_factory=list)
    description: str = ""
    source: str = ""

    @property
    def duration_s(self) -> float:
        return sum(s.duration_s for s in self.steps)

    def position(self, t: float) -> WorkoutPosition:
        acc = 0.0
        for i, s in enumerate(self.steps):
            if t < acc + s.duration_s:
                return WorkoutPosition(i, t - acc, acc + s.duration_s - t, False)
            acc += s.duration_s
        last = len(self.steps) - 1
        return WorkoutPosition(last, self.steps[last].duration_s if self.steps else 0, 0, True)

    def target_watts(self, t: float, ftp_w: float) -> float | None:
        if not self.steps:
            return None
        pos = self.position(t)
        if pos.finished:
            return None
        return self.steps[pos.step_index].target_at(pos.time_in_step_s, ftp_w)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "duration_s": self.duration_s,
            "steps": [asdict(s) for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Workout:
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            source=d.get("source", ""),
            steps=[Step(**s) for s in d["steps"]],
        )
