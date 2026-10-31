"""Grade -> target power curve used by GPX mode (pseudo-ERG).

The trainer is driven in ERG mode; the target power is a piecewise-linear function of the
(look-ahead averaged) grade, expressed as a fraction of FTP, then scaled by a live "effort"
factor, clamped and rate-limited so ERG transitions are not brutal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# (grade %, fraction of FTP)
DEFAULT_CURVE: list[tuple[float, float]] = [
    (-8.0, 0.40),
    (-3.0, 0.55),
    (0.0, 0.70),
    (3.0, 0.82),
    (6.0, 0.92),
    (10.0, 1.00),
]


@dataclass
class GradePowerCurve:
    points: list[tuple[float, float]] = field(default_factory=lambda: list(DEFAULT_CURVE))
    min_frac: float = 0.30
    max_frac: float = 1.05
    lookahead_m: float = 40.0
    max_ramp_w_per_s: float = 15.0

    def __post_init__(self) -> None:
        self.points = sorted((float(g), float(f)) for g, f in self.points)
        if len(self.points) < 2:
            raise ValueError("Grade/power curve needs at least two points")

    def fraction(self, grade: float) -> float:
        """Fraction of FTP for a grade given as rise/run (0.05 = 5 %); flat beyond the ends."""
        g, f = zip(*self.points, strict=True)
        frac = float(np.interp(grade * 100.0, g, f))
        return min(max(frac, self.min_frac), self.max_frac)

    def target_watts(self, grade: float, ftp_w: float, effort: float = 1.0) -> float:
        return self.fraction(grade) * ftp_w * effort


class RateLimiter:
    """Limits how fast a target power may change (W/s)."""

    def __init__(self, max_rate: float):
        self.max_rate = max_rate
        self.value: float | None = None

    def __call__(self, target: float, dt: float) -> float:
        if self.value is None:
            self.value = target
        else:
            step = self.max_rate * dt
            self.value += min(max(target - self.value, -step), step)
        return self.value

    def reset(self) -> None:
        self.value = None
