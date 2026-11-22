"""Parsers for .zwo (Zwift XML), .erg (watts) and .mrc (% FTP) workout files.

intervals.icu can export planned workouts in all three formats.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .model import Step, Workout


def _f(el: ET.Element, *names: str, default: float | None = None) -> float | None:
    # Zwift attribute names are case-inconsistent in the wild ("Power", "power", "PowerLow"...)
    lower = {k.lower(): v for k, v in el.attrib.items()}
    for n in names:
        if n.lower() in lower:
            return float(lower[n.lower()])
    return default


def _cad(el: ET.Element) -> int | None:
    c = _f(el, "Cadence")
    return int(c) if c else None


def parse_zwo(text: str) -> Workout:
    root = ET.fromstring(text.strip())
    name = (root.findtext("name") or "Workout").strip()
    desc = (root.findtext("description") or "").strip()
    wk = root.find("workout")
    if wk is None:
        raise ValueError("ZWO file has no <workout> element")
    steps: list[Step] = []
    for el in wk:
        tag = el.tag.lower()
        dur = _f(el, "Duration", default=0.0) or 0.0
        cad = _cad(el)
        if tag in ("warmup", "cooldown", "ramp"):
            lo = _f(el, "PowerLow", "Power")
            hi = _f(el, "PowerHigh", "Power")
            steps.append(Step(dur, lo, hi, cadence_rpm=cad, label=el.tag))
        elif tag == "steadystate":
            p = _f(el, "Power", "PowerLow")
            steps.append(Step(dur, p, p, cadence_rpm=cad, label=el.tag))
        elif tag == "intervalst":
            reps = int(_f(el, "Repeat", default=1) or 1)
            on_d = _f(el, "OnDuration", default=0.0) or 0.0
            off_d = _f(el, "OffDuration", default=0.0) or 0.0
            on_p = _f(el, "OnPower", "PowerHigh")
            off_p = _f(el, "OffPower", "PowerLow")
            on_c = _f(el, "Cadence")
            off_c = _f(el, "CadenceResting")
            for r in range(reps):
                steps.append(
                    Step(
                        on_d,
                        on_p,
                        on_p,
                        cadence_rpm=int(on_c) if on_c else None,
                        label=f"Interval {r + 1}/{reps} on",
                    )
                )
                steps.append(
                    Step(
                        off_d,
                        off_p,
                        off_p,
                        cadence_rpm=int(off_c) if off_c else None,
                        label=f"Interval {r + 1}/{reps} off",
                    )
                )
        elif tag in ("freeride", "maxeffort"):
            steps.append(Step(dur, None, None, cadence_rpm=cad, label=el.tag))
        # textevent and other elements are ignored
    return Workout(
        name=name, steps=[s for s in steps if s.duration_s > 0], description=desc, source="zwo"
    )


_SECTION = re.compile(r"^\s*\[(.+?)\]\s*$")


def parse_erg_mrc(text: str) -> Workout:
    """ERG/MRC: [COURSE HEADER] with 'MINUTES WATTS' or 'MINUTES PERCENT', then
    [COURSE DATA] with (minute, value) points defining a piecewise-linear profile."""
    name = "Workout"
    desc = ""
    unit = None
    points: list[tuple[float, float]] = []
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        m = _SECTION.match(line)
        if m:
            section = m.group(1).upper()
            continue
        if section == "COURSE HEADER":
            up = line.upper()
            if up.startswith("FILE NAME") or up.startswith("DESCRIPTION"):
                key, _, val = line.partition("=")
                if key.strip().upper() == "FILE NAME":
                    name = val.strip() or name
                else:
                    desc = val.strip()
            elif "MINUTES" in up and "WATTS" in up:
                unit = "watts"
            elif "MINUTES" in up and "PERCENT" in up:
                unit = "ftp"
        elif section == "COURSE DATA":
            parts = line.split()
            if len(parts) >= 2:
                try:
                    points.append((float(parts[0]) * 60.0, float(parts[1])))
                except ValueError:
                    continue
    if unit is None:
        raise ValueError("ERG/MRC header must declare MINUTES WATTS or MINUTES PERCENT")
    steps: list[Step] = []
    for (t0, v0), (t1, v1) in zip(points, points[1:], strict=False):
        if t1 - t0 <= 0:
            continue  # vertical edge = instantaneous change
        if unit == "ftp":
            v0, v1 = v0 / 100.0, v1 / 100.0
        steps.append(Step(t1 - t0, v0, v1, unit=unit))  # type: ignore[arg-type]
    source = "erg" if unit == "watts" else "mrc"
    return Workout(name=name, steps=steps, description=desc, source=source)


def parse_workout(text: str, filename: str) -> Workout:
    ext = Path(filename).suffix.lower()
    if ext == ".zwo":
        return parse_zwo(text)
    if ext in (".erg", ".mrc"):
        return parse_erg_mrc(text)
    raise ValueError(f"Unsupported workout format: {ext}")
