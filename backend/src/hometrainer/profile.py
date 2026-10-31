"""Rider profile and app settings (persisted as JSON in SQLite)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Literal

from .physics.grade_power import DEFAULT_CURVE, GradePowerCurve
from .physics.model import ModelParams

PowerSource = Literal["auto", "trainer", "power_meter"]


@dataclass
class Profile:
    # rider & bike
    rider_mass_kg: float = 75.0
    bike_mass_kg: float = 8.5
    ftp_w: float = 250.0
    max_hr_bpm: int | None = None
    # aero / rolling / drivetrain
    cda_m2: float = 0.32
    crr: float = 0.004
    drivetrain_efficiency: float = 0.976
    wheel_inertia_kg_m2: float = 0.14
    wheel_diameter_m: float = 0.67  # 700x25c ~ 0.67 m
    max_speed_kmh: float = 70.0
    # environment
    temperature_c: float = 20.0
    relative_humidity: float = 0.5
    headwind_ms: float = 0.0
    # power source for speed model / recording: auto = power meter if present, else trainer
    power_source: PowerSource = "auto"
    # in ERG modes, correct the trainer target so the power meter reads the requested power
    power_match: bool = True
    # ANT+ device numbers to pair with (None = first device found). The power-meter search
    # never pairs with the trainer's own power broadcast.
    trainer_device_number: int | None = None
    power_meter_device_number: int | None = None
    heart_rate_device_number: int | None = None
    # GPX pseudo-ERG grade -> power curve
    grade_curve: list[tuple[float, float]] = field(default_factory=lambda: list(DEFAULT_CURVE))
    grade_curve_min_frac: float = 0.30
    grade_curve_max_frac: float = 1.05
    grade_lookahead_m: float = 40.0
    target_ramp_w_per_s: float = 15.0
    # intervals.icu
    intervals_athlete_id: str = "0"
    intervals_api_key: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Profile:
        names = {f.name for f in fields(cls)}
        clean = {k: v for k, v in d.items() if k in names}
        if "grade_curve" in clean:
            clean["grade_curve"] = [tuple(p) for p in clean["grade_curve"]]
        return cls(**clean)

    def to_dict(self, redact_secrets: bool = False) -> dict:
        d = asdict(self)
        d["grade_curve"] = [list(p) for p in self.grade_curve]
        if redact_secrets:
            d["intervals_api_key_set"] = bool(self.intervals_api_key)
            d["intervals_api_key"] = ""
        return d

    def model_params(self) -> ModelParams:
        return ModelParams(
            rider_mass_kg=self.rider_mass_kg,
            bike_mass_kg=self.bike_mass_kg,
            cda_m2=self.cda_m2,
            crr=self.crr,
            drivetrain_efficiency=self.drivetrain_efficiency,
            wheel_inertia_kg_m2=self.wheel_inertia_kg_m2,
            wheel_radius_m=self.wheel_diameter_m / 2,
            max_speed_ms=self.max_speed_kmh / 3.6,
            temperature_c=self.temperature_c,
            relative_humidity=self.relative_humidity,
            headwind_ms=self.headwind_ms,
        )

    def grade_power_curve(self) -> GradePowerCurve:
        return GradePowerCurve(
            points=list(self.grade_curve),
            min_frac=self.grade_curve_min_frac,
            max_frac=self.grade_curve_max_frac,
            lookahead_m=self.grade_lookahead_m,
            max_ramp_w_per_s=self.target_ramp_w_per_s,
        )
