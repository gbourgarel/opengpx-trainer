"""Estimated time (or distance) of a GPX ride, before riding it.

The ride's own equation of motion (``VirtualBike.accel``: drive force, gravity, rolling,
aerodynamic drag with the wind, wheel inertia, braking cap), integrated along the distance
instead of in time: the route is walked in steps of ``STEP_M`` (horizontal), and on each step
of road length ``L = dx / cos(theta)`` the kinetic energy changes by the net work,

    v_out^2 = v_in^2 + 2 a(v_mid) L        (midpoint: v_mid^2 = v_in^2 + a(v_in) L)

with ``a = (eta P / max(v, v_min) - F_resist(v)) / m_eff``; when ``a`` changes sign within
the step (the speed reaches its equilibrium there, e.g. when starting), the steady speed is
taken instead of overshooting it. The step takes
``L / ((v_in + v_out) / 2)``. Momentum is therefore carried across grade changes (a short
steep ramp is climbed partly on speed, as in the ride), at a fraction of the cost of the
time-domain integration (no 50 ms sub-steps). The power is the target the ride would set
(Slope ERG: grade -> power curve on the look-ahead grade x effort, through the same ramp
limiter; or the workout's target), held exactly by the rider, times the profile's
speed-model power scale. The ride starts from standstill.

Not modelled: a rider not holding the target, pauses.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from ..gpx.route import Route
from ..profile import Profile
from ..workouts.model import Workout
from .grade_power import RateLimiter
from .model import VirtualBike

STEP_M = 10.0
V_FLOOR = 0.5  # m/s: a stall on a wall is walked, not an infinite time
MAX_LAPS = 50  # a workout on a short route: stop looping after this many laps


@dataclass(frozen=True)
class Estimate:
    duration_s: float
    distance_m: float
    laps: float = 1.0  # routes ridden (GPX + workout: the route loops)


# target(t, position) -> (watts, through the ramp limiter?)
TargetFn = Callable[[float, float], tuple[float, bool]]


def _ride(
    route: Route,
    profile: Profile,
    target: TargetFn,
    wind_kmh: float,
    wind_from_deg: float,
    duration_s: float | None = None,
) -> Estimate:
    """Ride the route once (``duration_s`` None) or, looping, for ``duration_s``."""
    bike = VirtualBike(profile.model_params())  # only its acceleration is used
    vmax = bike.params.max_speed_ms
    scale = 1.0 + profile.speed_power_scale_pct / 100.0
    wind_ms = wind_kmh / 3.6
    limiter = RateLimiter(profile.target_ramp_w_per_s)
    total = route.total_distance_m
    t = pos = v = 0.0  # pos: position on the current lap
    laps = 0
    last_dt = 0.0
    limiter.value = target(0.0, 0.0)[0]
    while True:
        if duration_s is None and laps >= 1:
            break
        if duration_s is not None and (t >= duration_s or laps >= MAX_LAPS):
            break
        dx = min(STEP_M, total - pos)  # a step never crosses the end of a lap
        mid = pos + dx / 2
        grade, alt = route.grade_and_altitude(mid)
        rho = bike.model.rho(alt)
        wind = route.wind_components(mid, wind_ms, wind_from_deg)
        watts, ramped = target(t, pos)
        if ramped:
            watts = limiter(watts, last_dt)
        else:
            limiter.value = watts  # smooth hand-over to the slope curve, as in the ride
        p = watts * scale
        road = dx * math.hypot(1.0, grade)  # road length of the step
        a1 = bike.accel(v, p, grade, rho, wind)
        v_mid = math.sqrt(max(v * v + a1 * road, V_FLOOR**2))
        a2 = bike.accel(v_mid, p, grade, rho, wind)
        if a1 * a2 < 0:
            # the speed reaches its equilibrium within the step (e.g. starting, or at a grade
            # change at low speed): the midpoint would overshoot it, take it
            v_out = min(bike.model.steady_speed(p, grade, rho, wind), vmax)
        else:
            v_out = min(math.sqrt(max(v * v + 2 * a2 * road, V_FLOOR**2)), vmax)
        dt = road / (0.5 * (v + v_out))
        if duration_s is not None and t + dt > duration_s:  # ends inside this step
            pos += dx * (duration_s - t) / dt
            t = duration_s
            break
        t += dt
        pos += dx
        if pos >= total - 1e-6:  # end of a lap (the route loops in a workout)
            laps += 1
            pos = 0.0
        v = v_out
        last_dt = dt
    covered = laps * total + pos
    return Estimate(duration_s=t, distance_m=covered, laps=covered / total)


def estimate_route(
    route: Route,
    profile: Profile,
    effort_pct: float = 100.0,
    wind_kmh: float = 0.0,
    wind_from_deg: float = 0.0,
) -> Estimate:
    """Time to ride the whole route in Slope ERG at ``effort_pct``."""
    curve = profile.grade_power_curve()

    def slope(_t: float, pos: float) -> tuple[float, bool]:
        g = route.mean_grade(pos, curve.lookahead_m)
        return curve.target_watts(g, profile.ftp_w, effort_pct / 100.0), True

    return _ride(route, profile, slope, wind_kmh, wind_from_deg)


def estimate_workout_on_route(
    route: Route,
    profile: Profile,
    workout: Workout,
    effort_pct: float = 100.0,
    intensity_pct: float = 100.0,
    wind_kmh: float = 0.0,
    wind_from_deg: float = 0.0,
) -> Estimate:
    """Distance covered during a workout ridden on the route (it loops while the workout
    lasts): the workout's targets on its steps, the slope curve in its free-ride steps."""
    curve = profile.grade_power_curve()

    def target(t: float, pos: float) -> tuple[float, bool]:
        w = workout.target_watts(t, profile.ftp_w)
        if w is not None:
            return w * intensity_pct / 100.0, False
        g = route.mean_grade(pos, curve.lookahead_m)
        return curve.target_watts(g, profile.ftp_w, effort_pct / 100.0), True

    return _ride(route, profile, target, wind_kmh, wind_from_deg, workout.duration_s)
