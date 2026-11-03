"""Cycling speed model.

Longitudinal power balance at the wheel (ground speed ``v``; wind components relative to the
direction of travel: ``v_w`` headwind, positive from ahead, and ``v_c`` crosswind):

    eta * P_rider = [ m g (Crr cos(theta) + sin(theta))
                      + 1/2 rho CdA |V_a| (v + v_w)
                      + m_eff dv/dt ] * v,        |V_a| = sqrt((v + v_w)^2 + v_c^2)

The drag acts along the apparent wind ``V_a`` (magnitude ``|V_a|``); only its component along
the direction of travel, ``|V_a| (v + v_w)``, resists the motion. A crosswind therefore adds
drag; CdA is taken independent of the yaw angle. Without crosswind this is the usual
``(v + v_w) |v + v_w|``.

with
    * ``m``      total mass (rider + bike) acting on gravity and rolling resistance,
    * ``m_eff``  inertial mass = m + I_wheels / r_wheel^2 (rotating wheels store kinetic energy),
    * ``theta``  road angle, ``tan(theta) = grade``,
    * ``rho``    air density computed from altitude, temperature and humidity,
    * ``eta``    drivetrain efficiency (chain, bearings).

Instead of solving the steady-state cubic at each instant (speed would jump at every grade change),
:class:`VirtualBike` integrates the equation of motion in time, so momentum is carried through
climbs and descents. The steady-state solver is still provided for display / inverse problems.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

G = 9.80665  # m/s^2
R_DRY = 287.058  # J/(kg K), specific gas constant for dry air
R_VAPOR = 461.495  # J/(kg K), specific gas constant for water vapour
P0 = 101_325.0  # Pa, ISA sea-level pressure
T0 = 288.15  # K, ISA sea-level temperature
LAPSE = 0.0065  # K/m, ISA tropospheric lapse rate
BARO_EXP = G / (R_DRY * LAPSE)  # ~5.2559


def air_density(
    altitude_m: float,
    temperature_c: float = 20.0,
    relative_humidity: float = 0.5,
    sea_level_pressure_pa: float = P0,
) -> float:
    """Moist-air density in kg/m^3.

    Pressure comes from the ISA barometric formula (standard lapse rate) for the altitude; the
    local air temperature is then used in the ideal gas law. Water vapour partial pressure uses
    the Tetens saturation formula.
    """
    altitude_m = max(-500.0, min(altitude_m, 9000.0))
    pressure = sea_level_pressure_pa * (1.0 - LAPSE * altitude_m / T0) ** BARO_EXP
    t_k = temperature_c + 273.15
    p_sat = 610.78 * 10.0 ** (7.5 * temperature_c / (temperature_c + 237.3))
    p_vapor = max(0.0, min(relative_humidity, 1.0)) * p_sat
    p_dry = pressure - p_vapor
    return p_dry / (R_DRY * t_k) + p_vapor / (R_VAPOR * t_k)


def grade_to_angle(grade: float) -> tuple[float, float]:
    """Return (sin(theta), cos(theta)) for a grade expressed as rise/run (0.05 = 5 %)."""
    h = math.sqrt(1.0 + grade * grade)
    return grade / h, 1.0 / h


@dataclass(frozen=True)
class ModelParams:
    rider_mass_kg: float = 75.0
    bike_mass_kg: float = 8.5
    cda_m2: float = 0.32
    crr: float = 0.004
    drivetrain_efficiency: float = 0.976
    wheel_inertia_kg_m2: float = 0.14  # both wheels combined
    wheel_radius_m: float = 0.335
    max_speed_ms: float = 70 / 3.6  # virtual braking cap on descents
    temperature_c: float = 20.0
    relative_humidity: float = 0.5

    @property
    def mass_kg(self) -> float:
        return self.rider_mass_kg + self.bike_mass_kg

    @property
    def inertial_mass_kg(self) -> float:
        return self.mass_kg + self.wheel_inertia_kg_m2 / self.wheel_radius_m**2


@dataclass(frozen=True)
class ForceBreakdown:
    gravity_n: float
    rolling_n: float
    aero_n: float

    @property
    def total_n(self) -> float:
        return self.gravity_n + self.rolling_n + self.aero_n


class SpeedModel:
    """Stateless physics helpers built on :class:`ModelParams`."""

    def __init__(self, params: ModelParams):
        self.p = params

    def rho(self, altitude_m: float) -> float:
        return air_density(altitude_m, self.p.temperature_c, self.p.relative_humidity)

    def forces(
        self, v: float, grade: float, rho: float, wind: tuple[float, float] = (0.0, 0.0)
    ) -> ForceBreakdown:
        """Resistive forces (N) at ground speed ``v``. Positive = opposing motion.

        ``wind`` = (headwind, crosswind) components in m/s relative to the direction of travel.
        """
        sin_t, cos_t = grade_to_angle(grade)
        m = self.p.mass_kg
        head, cross = wind
        va = v + head  # apparent wind along the direction of travel
        return ForceBreakdown(
            gravity_n=m * G * sin_t,
            rolling_n=m * G * self.p.crr * cos_t,
            aero_n=0.5 * rho * self.p.cda_m2 * math.hypot(va, cross) * va,
        )

    def power_required(
        self, v: float, grade: float, rho: float, wind: tuple[float, float] = (0.0, 0.0)
    ) -> float:
        """Steady-state rider power (W) needed to hold speed ``v`` (may be negative)."""
        return self.forces(v, grade, rho, wind).total_n * v / self.p.drivetrain_efficiency

    def steady_speed(
        self, power_w: float, grade: float, rho: float, wind: tuple[float, float] = (0.0, 0.0)
    ) -> float:
        """Equilibrium ground speed (m/s) for a constant rider power.

        ``power_required`` is monotonic increasing in ``v`` for ``v >= 0`` wherever it is
        positive, so bisection is robust (also handles coasting terminal speed on descents).
        """
        power_w = max(0.0, power_w)
        if self.forces(0.0, grade, rho, wind).total_n > 0 and power_w == 0:
            return 0.0  # rolling resistance + gravity cannot be overcome with zero power

        def f(v: float) -> float:
            return self.power_required(v, grade, rho, wind) - power_w

        lo, hi = 0.0, 1.0
        while f(hi) < 0 and hi < 200:
            hi *= 2
        # On a descent f(v) is negative for small v then crosses zero once: find the crossing
        # that is the stable equilibrium (largest root).
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if f(mid) < 0:
                lo = mid
            else:
                hi = mid
        return min(0.5 * (lo + hi), self.p.max_speed_ms)


# grade_fn(horizontal_distance_m) -> (grade, altitude_m)
GradeFn = Callable[[float], tuple[float, float]]
# wind_fn(horizontal_distance_m) -> (headwind, crosswind) in m/s, relative to the direction of
# travel at that point of the route
WindFn = Callable[[float], tuple[float, float]]


def flat_road(_d: float) -> tuple[float, float]:
    return 0.0, 0.0


def no_wind(_d: float) -> tuple[float, float]:
    return 0.0, 0.0


@dataclass
class BikeState:
    speed_ms: float = 0.0
    distance_m: float = 0.0  # horizontal distance along the route (map distance)
    distance_3d_m: float = 0.0  # distance travelled along the road surface
    grade: float = 0.0
    altitude_m: float = 0.0
    wind: tuple[float, float] = (0.0, 0.0)  # (headwind, crosswind) m/s at the current position
    forces: ForceBreakdown | None = field(default=None)


class VirtualBike:
    """Time integration of the longitudinal equation of motion.

    The drive force ``eta P / v`` is singular at standstill; it is limited to
    ``eta P / max(v, v_min)`` which acts like a finite starting torque. A stopped bike stays stopped
    when the net static force is resistive (no rolling backwards). Integration uses the explicit
    midpoint method with fixed sub-steps; grade and air density are re-evaluated at each sub-step
    so that grade changes inside a tick are honoured.
    """

    V_MIN = 1.0  # m/s, drive-force regularisation at very low speed
    SUBSTEP_S = 0.05

    def __init__(
        self, params: ModelParams, grade_fn: GradeFn = flat_road, wind_fn: WindFn = no_wind
    ):
        self.model = SpeedModel(params)
        self.grade_fn = grade_fn
        self.wind_fn = wind_fn
        self.state = BikeState()
        g, alt = grade_fn(0.0)
        self.state.grade, self.state.altitude_m = g, alt
        self.state.wind = wind_fn(0.0)

    @property
    def params(self) -> ModelParams:
        return self.model.p

    def set_params(self, params: ModelParams) -> None:
        self.model = SpeedModel(params)

    def _accel(
        self, v: float, power_w: float, grade: float, rho: float, wind: tuple[float, float]
    ) -> float:
        p = self.model.p
        drive = p.drivetrain_efficiency * max(power_w, 0.0) / max(v, self.V_MIN)
        resist = self.model.forces(v, grade, rho, wind).total_n
        return (drive - resist) / p.inertial_mass_kg

    def step(self, power_w: float, dt: float) -> BikeState:
        """Advance by ``dt`` seconds with constant rider power ``power_w`` (W)."""
        s = self.state
        p = self.model.p
        n = max(1, math.ceil(dt / self.SUBSTEP_S))
        h = dt / n
        v = s.speed_ms
        for _ in range(n):
            grade, alt = self.grade_fn(s.distance_m)
            wind = self.wind_fn(s.distance_m)  # follows the route heading, like the grade
            rho = self.model.rho(alt)
            a1 = self._accel(v, power_w, grade, rho, wind)
            if v <= 0.0 and a1 <= 0.0:
                v = 0.0
                continue
            v_mid = max(0.0, v + 0.5 * h * a1)
            a2 = self._accel(v_mid, power_w, grade, rho, wind)
            v_new = max(0.0, v + h * a2)
            v_new = min(v_new, p.max_speed_ms)  # virtual braking
            v_avg = 0.5 * (v + v_new)
            _, cos_t = grade_to_angle(grade)
            s.distance_3d_m += v_avg * h
            s.distance_m += v_avg * cos_t * h
            v = v_new
        s.speed_ms = v
        s.grade, s.altitude_m = self.grade_fn(s.distance_m)
        s.wind = self.wind_fn(s.distance_m)
        s.forces = self.model.forces(v, s.grade, self.model.rho(s.altitude_m), s.wind)
        return s
