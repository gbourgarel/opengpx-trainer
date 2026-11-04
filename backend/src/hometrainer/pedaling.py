"""Lap / session summaries of the pedal metrics of a dual-sided power meter (FIT fields).

Same conventions as a Garmin head unit (checked against an Edge 540 recording of the same ride
with the same Favero Assioma pedals: TE, PS, balance and power-phase averages agree within the
FIT resolution):

* averages over the samples where the rider is pedalling (power > 0);
* L/R balance weighted by power (the share of the *work* done by the right leg);
* power-phase angles averaged on the circle (a phase starting at 355° and one starting at 5°
  average to 0°, not 180°), returned in [0, 360);
* rider position: transition states are attributed to the stable state that follows them
  (ANT+ Bicycle Power profile, table 17-4), e.g. seated → "transition to standing" → seated
  counts as seated (a false start).

Pure functions on ``recording.Sample`` lists.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .recording import Sample

# FIT RiderPositionType
SEATED, STANDING, TO_SEATED, TO_STANDING = 0, 1, 2, 3
_TARGET = {SEATED: SEATED, STANDING: STANDING, TO_SEATED: SEATED, TO_STANDING: STANDING}


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def circular_mean_deg(angles: Sequence[float]) -> float | None:
    if not angles:
        return None
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    if math.hypot(s, c) < 1e-9 * len(angles):
        return None  # evenly spread: no meaningful mean
    a = math.degrees(math.atan2(s, c)) % 360.0
    return 0.0 if a >= 360.0 else a  # -1e-15 % 360 == 360.0 (would overflow the FIT byte)


def balance_100(samples: Sequence[Sample]) -> int | None:
    """Power-weighted L/R balance as the FIT ``left_right_balance_100`` value: % x 100 in bits
    0-13, bit 15 set when it is the right leg's share (else the side is unknown)."""
    vals = [(s.lr_balance, s.power_w or 0.0) for s in samples if s.lr_balance is not None]
    right = [(b, p) for b, p in vals if b & 0x80]
    vals = right or vals  # meters that tell the legs apart: right-leg shares only
    total = sum(p for _, p in vals)
    if not vals or total <= 0:
        return None
    pct = sum((b & 0x7F) * p for b, p in vals) / total
    return (round(pct * 100) & 0x3FFF) | (0x8000 if right else 0)


def attributed_positions(samples: Sequence[Sample]) -> list[int | None]:
    """Seated / standing for each sample (None: unknown), transitions resolved as in the
    ANT+ profile: a transition counts as the stable state that follows it (as its own target
    when the ride ends during it)."""
    out: list[int | None] = [None] * len(samples)
    following: int | None = None
    for i in range(len(samples) - 1, -1, -1):
        p = samples[i].rider_position
        if p is None:
            continue
        if p in (SEATED, STANDING):
            following = p
            out[i] = p
        else:
            out[i] = following if following is not None else _TARGET.get(p)
    return out


def position_changes(samples: Sequence[Sample]) -> list[tuple[float, int]]:
    """(timestamp, FIT rider position) at the first known position and at each change, as a
    head unit records ``rider_position_change`` events (transition states included)."""
    out: list[tuple[float, int]] = []
    last = None
    for s in samples:
        if s.rider_position is not None and s.rider_position != last:
            out.append((s.timestamp_s, s.rider_position))
            last = s.rider_position
    return out


def pedal_summary(samples: Sequence[Sample]) -> dict:
    """FIT lap / session fields (``avg_left_torque_effectiveness``, ``left_right_balance``,
    ``avg_left_power_phase``, ``avg_power_position``...) for these samples; only the fields
    with data."""
    pedalling = [s for s in samples if (s.power_w or 0) > 0]
    out: dict = {}

    for attr, field in (
        ("left_te", "avg_left_torque_effectiveness"),
        ("right_te", "avg_right_torque_effectiveness"),
        ("left_ps", "avg_left_pedal_smoothness"),
        ("right_ps", "avg_right_pedal_smoothness"),
        ("combined_ps", "avg_combined_pedal_smoothness"),
    ):
        v = _mean([x for s in pedalling if (x := getattr(s, attr)) is not None])
        if v is not None:
            out[field] = v
    for attr, field in (("left_pco", "avg_left_pco"), ("right_pco", "avg_right_pco")):
        v = _mean([x for s in pedalling if (x := getattr(s, attr)) is not None])
        if v is not None:
            out[field] = round(v)

    b = balance_100(pedalling)
    if b is not None:
        out["left_right_balance"] = b

    for attr in (
        "left_power_phase",
        "left_power_phase_peak",
        "right_power_phase",
        "right_power_phase_peak",
    ):
        pairs = [x for s in pedalling if (x := getattr(s, attr)) is not None]
        start = circular_mean_deg([p[0] for p in pairs])
        end = circular_mean_deg([p[1] for p in pairs])
        if start is not None and end is not None:
            out[f"avg_{attr}"] = [start, end]

    positions = attributed_positions(samples)
    if any(p is not None for p in positions):
        by_pos: dict[int, list[Sample]] = {SEATED: [], STANDING: []}
        for s, p in zip(samples, positions, strict=True):
            if p is not None and (s.power_w or 0) > 0:
                by_pos[p].append(s)

        def stat(pos: int, key: str, agg) -> int | None:
            vals = [v for s in by_pos[pos] if (v := getattr(s, key)) is not None]
            return round(agg(vals)) if vals else None  # None: FIT invalid value

        out["avg_power_position"] = [stat(p, "power_w", _mean) for p in (SEATED, STANDING)]
        out["max_power_position"] = [stat(p, "power_w", max) for p in (SEATED, STANDING)]
        out["avg_cadence_position"] = [stat(p, "cadence_rpm", _mean) for p in (SEATED, STANDING)]
        out["max_cadence_position"] = [stat(p, "cadence_rpm", max) for p in (SEATED, STANDING)]
        known = [p for p in positions if p is not None]
        out["time_standing"] = float(sum(1 for p in known if p == STANDING))  # 1 Hz samples
        out["stand_count"] = sum(
            1 for a, b in zip(known, known[1:], strict=False) if a != STANDING and b == STANDING
        ) + (1 if known and known[0] == STANDING else 0)
    return out
