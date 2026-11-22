"""Rider profile and app settings (persisted as JSON in SQLite)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Literal

from .physics.grade_power import DEFAULT_CURVE, GradePowerCurve
from .physics.model import ModelParams

PowerSource = Literal["auto", "trainer", "power_meter"]
POWER_SOURCES = ("auto", "trainer", "power_meter")
Transport = Literal["ant", "ble"]
TRANSPORTS = ("ant", "ble")
_ROLES = ("trainer", "power_meter", "heart_rate")
_TRANSPORT_FIELDS = {f"{r}_transport" for r in _ROLES}
_BLE_TEXT_FIELDS = {f"{r}_ble_id" for r in _ROLES} | {f"{r}_ble_name" for r in _ROLES}


# Air of a ride without chosen conditions (ERG rides, the routes list's estimates): ISA sea-level
# temperature, mid humidity. GPX rides take the conditions chosen at start.
STANDARD_TEMPERATURE_C = 15.0
STANDARD_HUMIDITY = 0.5


@dataclass(frozen=True)
class BikePreset:
    """Speed-model values of a typical bike and riding position (bike weight not included)."""

    label: str
    cda_m2: float
    crr: float  # on real asphalt, not on a test drum (~1.2-1.5x lower)
    drivetrain_efficiency: float
    wheel_inertia_kg_m2: float  # both wheels
    wheel_diameter_m: float


# Orders of magnitude, not measurements of a given rider: CdA from the usual ranges (hoods
# 0.30-0.40, drops 0.27-0.35, recreational TT 0.26-0.32), Crr of good tyres on real roads.
# Sources and resulting speeds: README, "Speed model".
BIKE_PRESETS: dict[str, BikePreset] = {
    "road_hoods": BikePreset("Road bike, hoods", 0.32, 0.0045, 0.976, 0.14, 0.670),
    "road_drops": BikePreset("Road bike, drops", 0.29, 0.0045, 0.976, 0.14, 0.670),
    "tt": BikePreset("Time trial / triathlon", 0.28, 0.0040, 0.977, 0.16, 0.670),
    "gravel": BikePreset("Gravel (40 mm tyres)", 0.35, 0.0060, 0.970, 0.18, 0.700),
    "mtb": BikePreset('Mountain bike 29"', 0.45, 0.0090, 0.960, 0.25, 0.740),
    "city": BikePreset("City bike", 0.55, 0.0080, 0.950, 0.20, 0.690),
}
CUSTOM_PRESET = "custom"
# the profile fields a preset sets
PRESET_FIELDS = (
    "cda_m2",
    "crr",
    "drivetrain_efficiency",
    "wheel_inertia_kg_m2",
    "wheel_diameter_m",
)


def matching_preset(values: dict) -> str:
    """The preset whose values all equal these, else "custom"."""
    for key, preset in BIKE_PRESETS.items():
        if all(values.get(f) == getattr(preset, f) for f in PRESET_FIELDS):
            return key
    return CUSTOM_PRESET


class ProfileError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# Physically sensible bounds (inclusive). Optional fields accept None.
_BOUNDS: dict[str, tuple[float, float]] = {
    "rider_mass_kg": (20, 250),
    "bike_mass_kg": (1, 50),
    "ftp_w": (30, 1000),
    "max_hr_bpm": (80, 250),
    "threshold_hr_bpm": (60, 240),
    "cda_m2": (0.1, 1.0),
    "crr": (0.0005, 0.03),
    "drivetrain_efficiency": (0.8, 1.0),
    "wheel_inertia_kg_m2": (0.0, 1.0),
    "wheel_diameter_m": (0.3, 1.0),
    "max_speed_kmh": (10, 150),
    "speed_power_scale_pct": (-90, 200),
    "grade_curve_min_frac": (0.0, 2.0),
    "grade_curve_max_frac": (0.1, 3.0),
    "grade_lookahead_m": (0, 1000),
    "target_ramp_w_per_s": (1, 500),
}
_OPTIONAL = {"max_hr_bpm", "threshold_hr_bpm"}
_DEVICE_NUMBERS = {"trainer_device_number", "power_meter_device_number", "heart_rate_device_number"}
_INTS = {"max_hr_bpm", "threshold_hr_bpm"} | _DEVICE_NUMBERS


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("must be a finite number")
    return value


def _validate_field(name: str, value):
    if name in _DEVICE_NUMBERS:
        if value in (None, "", 0):
            return None  # first device found
        v = _number(value)
        if not float(v).is_integer() or not 1 <= v <= 65535:
            raise ValueError("must be an ANT+ device number (1-65535) or empty")
        return int(v)
    if name in _BOUNDS:
        if value is None and name in _OPTIONAL:
            return None
        if value is None:
            raise ValueError("is required")
        v = _number(value)
        lo, hi = _BOUNDS[name]
        if not lo <= v <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return int(round(v)) if name in _INTS else float(v)
    if name in _TRANSPORT_FIELDS:
        if value not in TRANSPORTS:
            raise ValueError("must be 'ant' or 'ble'")
        return value
    if name in _BLE_TEXT_FIELDS:
        if value in (None, ""):
            return None
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError("must be text (max 100 characters) or empty")
        return value.strip()
    if name == "power_source":
        if value not in POWER_SOURCES:
            raise ValueError(f"must be one of {', '.join(POWER_SOURCES)}")
        return value
    if name == "bike_preset":
        if value != CUSTOM_PRESET and value not in BIKE_PRESETS:
            raise ValueError(f"must be one of {', '.join([*BIKE_PRESETS, CUSTOM_PRESET])}")
        return value
    if name == "power_match":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
        return value
    if name in ("intervals_athlete_id", "intervals_api_key"):
        if not isinstance(value, str):
            raise ValueError("must be text")
        return value.strip()
    if name == "grade_curve":
        try:
            pts = [(float(_number(g)), float(_number(f))) for g, f in value]
        except (TypeError, ValueError) as e:
            raise ValueError("must be a list of [grade %, fraction of FTP] pairs") from e
        if len(pts) < 2:
            raise ValueError("needs at least two points")
        if any(not -50 <= g <= 50 or not 0 <= f <= 3 for g, f in pts):
            raise ValueError("grades must be within ±50 % and fractions within 0-3")
        return pts
    return value


@dataclass
class Profile:
    # rider & bike
    rider_mass_kg: float = 75.0
    bike_mass_kg: float = 8.5
    ftp_w: float = 250.0
    max_hr_bpm: int | None = None
    # lactate threshold heart rate: heart-rate zones (Friel, % of it) on the ride screen
    threshold_hr_bpm: int | None = None
    # aero / rolling / drivetrain: set by the bike preset (BIKE_PRESETS), or by hand with
    # "custom"; the values are stored either way so a ride can be reproduced
    bike_preset: str = "road_hoods"
    cda_m2: float = 0.32
    crr: float = 0.0045
    drivetrain_efficiency: float = 0.976
    wheel_inertia_kg_m2: float = 0.14
    wheel_diameter_m: float = 0.67  # 700x25c ~ 0.67 m
    max_speed_kmh: float = 70.0
    # the speed model is fed with measured power x (1 + x / 100); the trainer target and the
    # recorded power are unchanged (e.g. to compensate a power meter reading low)
    speed_power_scale_pct: float = 0.0
    # (the ride's conditions, wind and air, are chosen per GPX ride: see RideSession; a
    # profile stored with temperature / humidity, as before 2026-11-15, has them ignored)
    # power source for speed model / recording: auto = power meter if present, else trainer
    power_source: PowerSource = "auto"
    # in ERG modes, correct the trainer target so the power meter reads the requested power
    power_match: bool = True
    # ANT+ device numbers to pair with (None = first device found). The power-meter search
    # never pairs with the trainer's own power broadcast.
    trainer_device_number: int | None = None
    power_meter_device_number: int | None = None
    heart_rate_device_number: int | None = None
    # transport per role, and the chosen Bluetooth device (id = address, a UUID on macOS)
    trainer_transport: Transport = "ant"
    power_meter_transport: Transport = "ant"
    heart_rate_transport: Transport = "ant"
    trainer_ble_id: str | None = None
    power_meter_ble_id: str | None = None
    heart_rate_ble_id: str | None = None
    trainer_ble_name: str | None = None
    power_meter_ble_name: str | None = None
    heart_rate_ble_name: str | None = None
    # Slope ERG (GPX) grade -> power curve
    grade_curve: list[tuple[float, float]] = field(default_factory=lambda: list(DEFAULT_CURVE))
    grade_curve_min_frac: float = 0.30
    grade_curve_max_frac: float = 1.05
    grade_lookahead_m: float = 40.0
    target_ramp_w_per_s: float = 15.0
    # intervals.icu
    intervals_athlete_id: str = "0"
    intervals_api_key: str = ""

    @classmethod
    def from_dict(cls, d: dict, strict: bool = True) -> Profile:
        """Build and validate a profile.

        strict=True raises ProfileError listing every invalid field (API input).
        strict=False replaces invalid fields with their defaults (loading stored data, so a bad
        value saved by an older version can never stop the app from starting).
        """
        names = {f.name for f in fields(cls)}
        clean = {k: v for k, v in d.items() if k in names}
        if "bike_preset" not in clean and any(f in clean for f in PRESET_FIELDS):
            # stored before presets existed: keep its values, under the preset they match
            clean["bike_preset"] = matching_preset({**asdict(cls()), **clean})
        errors: dict[str, str] = {}
        defaults = cls()
        out: dict = {}
        for name, value in clean.items():
            try:
                out[name] = _validate_field(name, value)
            except ValueError as e:
                errors[name] = str(e)
                out[name] = getattr(defaults, name)
        p = cls(**out)
        preset = BIKE_PRESETS.get(p.bike_preset)
        if preset is not None:  # a preset's values win over the ones sent with it
            for f in PRESET_FIELDS:
                setattr(p, f, getattr(preset, f))
        if p.grade_curve_min_frac > p.grade_curve_max_frac:
            errors["grade_curve_min_frac"] = "floor must not exceed ceiling"
            p.grade_curve_min_frac = defaults.grade_curve_min_frac
            p.grade_curve_max_frac = max(defaults.grade_curve_max_frac, p.grade_curve_min_frac)
        if errors and strict:
            raise ProfileError(errors)
        return p

    def to_dict(self, redact_secrets: bool = False) -> dict:
        d = asdict(self)
        d["grade_curve"] = [list(p) for p in self.grade_curve]
        if redact_secrets:
            d["intervals_api_key_set"] = bool(self.intervals_api_key)
            d["intervals_api_key"] = ""
        return d

    def model_params(
        self,
        temperature_c: float = STANDARD_TEMPERATURE_C,
        relative_humidity: float = STANDARD_HUMIDITY,
    ) -> ModelParams:
        """Speed-model parameters for a ride in this air (standard air by default: ERG rides,
        route list estimates)."""
        return ModelParams(
            rider_mass_kg=self.rider_mass_kg,
            bike_mass_kg=self.bike_mass_kg,
            cda_m2=self.cda_m2,
            crr=self.crr,
            drivetrain_efficiency=self.drivetrain_efficiency,
            wheel_inertia_kg_m2=self.wheel_inertia_kg_m2,
            wheel_radius_m=self.wheel_diameter_m / 2,
            max_speed_ms=self.max_speed_kmh / 3.6,
            temperature_c=temperature_c,
            relative_humidity=relative_humidity,
        )

    def grade_power_curve(self) -> GradePowerCurve:
        return GradePowerCurve(
            points=list(self.grade_curve),
            min_frac=self.grade_curve_min_frac,
            max_frac=self.grade_curve_max_frac,
            lookahead_m=self.grade_lookahead_m,
            max_ramp_w_per_s=self.target_ramp_w_per_s,
        )
