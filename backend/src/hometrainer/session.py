"""Ride session engine (ticked at ~4 Hz by the app).

Modes
-----
* ``erg``: target power from a structured workout x intensity %. Virtual speed on flat road.
* ``gpx``: pseudo-ERG; target power from the grade->power curve on the look-ahead grade x effort %
  (``target_mode="slope"``), or set directly by the rider in watts (``target_mode="manual"``).
  Virtual speed comes from the dynamic model fed with ``measured power x (1 + difficulty %)``.

Power source
------------
The power used for the speed model, display and recording comes from the power meter when one is
selected / detected (``auto``), else from the trainer. With a power meter and ``power_match``,
the ERG target sent to the trainer is corrected so that the *power meter* reads the request.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .ant.hub import Readings, SensorHub
from .gpx.route import Route
from .physics.grade_power import RateLimiter
from .physics.model import VirtualBike, flat_road
from .profile import Profile
from .recording import Recorder, Sample
from .workouts.model import Workout

Mode = Literal["erg", "gpx"]
TargetMode = Literal["slope", "manual"]
MAX_MANUAL_TARGET_W = 2000.0
State = Literal["ready", "running", "paused", "finished"]

FREE_RIDE_RESISTANCE_PCT = 20.0
AUTO_PAUSE_AFTER_S = 3.0


@dataclass
class PowerChoice:
    power_w: float | None
    cadence_rpm: float | None
    source: str  # power source: "power_meter" | "trainer" | "none"
    cadence_source: str = "none"  # "power_meter" | "trainer" | "none"


def _first_cadence(*candidates: tuple[float | None, str]) -> tuple[float | None, str]:
    # "is not None", not truthiness: 0 rpm is a valid reading, not a missing one
    for value, name in candidates:
        if value is not None:
            return value, name
    return None, "none"


def w_per_kg(watts: float | None, rider_mass_kg: float) -> float | None:
    """Power-to-weight ratio, by convention relative to the rider's mass only (no bike)."""
    if watts is None or rider_mass_kg <= 0:
        return None
    return round(watts / rider_mass_kg, 2)


def choose_power(r: Readings, preference: str) -> PowerChoice:
    """Pick power and cadence from the same sensor (the power meter when it is the power
    source). Cadence falls back to the other sensor only when the preferred one provides none."""
    pm_ok = r.power_meter_connected and r.pm_power_w is not None
    tr_ok = r.trainer_connected and r.trainer_power_w is not None
    pm_cad = (r.pm_cadence_rpm if r.power_meter_connected else None, "power_meter")
    tr_cad = (r.trainer_cadence_rpm if r.trainer_connected else None, "trainer")
    use_pm = preference == "power_meter" or (preference == "auto" and pm_ok)
    if use_pm:
        cad, cad_src = _first_cadence(pm_cad, tr_cad)
        if not pm_ok:
            return PowerChoice(None, cad, "none", cad_src)
        return PowerChoice(r.pm_power_w, cad, "power_meter", cad_src)
    cad, cad_src = _first_cadence(tr_cad, pm_cad)
    if tr_ok:
        return PowerChoice(r.trainer_power_w, cad, "trainer", cad_src)
    return PowerChoice(None, cad, "none", cad_src)


class PowerMatch:
    """Estimates the trainer-vs-power-meter offset and adds it to the ERG target.

    offset ~ EMA(P_trainer - P_pm); sending ``target + offset`` makes the power meter converge to
    the requested target when the bias is roughly proportional (fixed point: pm == target).
    """

    def __init__(self, tau_s: float = 10.0, max_frac: float = 0.15):
        self.tau_s = tau_s
        self.max_frac = max_frac
        self.offset_w = 0.0

    def update(self, r: Readings, target_w: float | None, dt: float) -> None:
        if target_w is None or r.trainer_power_w is None or r.pm_power_w is None:
            return
        if r.pm_power_w < 40 or (r.pm_cadence_rpm or r.trainer_cadence_rpm or 0) < 40:
            return  # not steady pedalling: ERG not holding, don't learn
        err = r.trainer_power_w - r.pm_power_w
        self.offset_w += min(dt / self.tau_s, 1.0) * (err - self.offset_w)
        lim = self.max_frac * max(target_w, 100.0)
        self.offset_w = max(-lim, min(self.offset_w, lim))

    def apply(self, target_w: float) -> float:
        return max(0.0, target_w + self.offset_w)


class RideSession:
    def __init__(
        self,
        hub: SensorHub,
        profile: Profile,
        mode: Mode,
        workout: Workout | None = None,
        route: Route | None = None,
        name: str | None = None,
        workout_id: int | None = None,
        route_id: int | None = None,
    ):
        if mode == "erg" and workout is None:
            raise ValueError("ERG mode needs a workout")
        if mode == "gpx" and route is None:
            raise ValueError("GPX mode needs a route")
        self.hub = hub
        self.profile = profile
        self.mode: Mode = mode
        self.workout = workout
        self.route = route
        self.name = name or (workout.name if workout else route.name if route else "Ride")
        # identify the ride so any client (after a reload, another device) can rebuild its view
        self.id = uuid.uuid4().hex
        self.workout_id = workout_id
        self.route_id = route_id
        self.saved: dict | None = None  # set once the ride is written to history (save once)
        self.state: State = "ready"
        self.started_at: datetime | None = None
        self.elapsed_s = 0.0
        self.intensity_pct = 100.0  # ERG: scales workout targets
        self.effort_pct = 100.0  # GPX: scales the grade->power curve target
        self.difficulty_pct = 0.0  # GPX: speed model uses P * (1 + difficulty)
        self.target_mode: TargetMode = "slope"  # GPX: grade curve, or rider-set watts
        self.manual_target_w: float | None = None
        self.curve = profile.grade_power_curve()
        self.limiter = RateLimiter(self.curve.max_ramp_w_per_s)
        self.power_match = PowerMatch()
        grade_fn = route.grade_and_altitude if route else flat_road
        self.bike = VirtualBike(profile.model_params(), grade_fn)
        self.recorder = Recorder()
        self._idle_s = 0.0
        self._last_tick: float | None = None
        self.requested_target_w: float | None = None
        self.sent_target_w: float | None = None
        self.last: dict = {}
        self.attach_hub(hub)

    def attach_hub(self, hub: SensorHub) -> None:
        """(Re)bind the session to a sensor hub, e.g. after an ANT+ reconnection.

        The new hub starts with no trainer command, so the next tick re-sends the current
        target; the rider configuration is sent again as well.
        """
        self.hub = hub
        hub.set_user_configuration(
            self.profile.rider_mass_kg, self.profile.bike_mass_kg, self.profile.wheel_diameter_m
        )

    # -- controls -----------------------------------------------------------------------
    def pause(self) -> None:
        if self.state == "running":
            self.state = "paused"

    def resume(self) -> None:
        if self.state in ("paused", "ready"):
            self._start_if_needed()
            self.state = "running"

    def finish(self) -> None:
        self.state = "finished"

    def adjust(
        self,
        intensity_pct=None,
        effort_pct=None,
        difficulty_pct=None,
        target_mode=None,
        manual_target_w=None,
    ) -> None:
        if target_mode is not None:
            if target_mode not in ("slope", "manual"):
                raise ValueError("target_mode must be 'slope' or 'manual'")
            if self.mode != "gpx":
                raise ValueError("target_mode only applies to GPX rides")
            if target_mode == "manual" and self.manual_target_w is None:
                # start from the current target so switching mode causes no jump
                current = self.requested_target_w
                if current is None:
                    current = self.curve.target_watts(0.0, self.profile.ftp_w)
                self.manual_target_w = float(round(current))
            self.target_mode = target_mode
        if manual_target_w is not None:
            if self.mode != "gpx":
                raise ValueError("manual_target_w only applies to GPX rides")
            self.manual_target_w = max(0.0, min(float(manual_target_w), MAX_MANUAL_TARGET_W))
            self.target_mode = "manual"
        if intensity_pct is not None:
            self.intensity_pct = max(10.0, min(float(intensity_pct), 200.0))
        if effort_pct is not None:
            self.effort_pct = max(10.0, min(float(effort_pct), 200.0))
        if difficulty_pct is not None:
            self.difficulty_pct = max(-90.0, min(float(difficulty_pct), 200.0))

    def _start_if_needed(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now(UTC)

    # -- target computation -------------------------------------------------------------
    def _target(self, dt: float) -> float | None:
        ftp = self.profile.ftp_w
        if self.mode == "erg":
            t = self.workout.target_watts(self.elapsed_s, ftp)
            return None if t is None else t * self.intensity_pct / 100.0
        if self.target_mode == "manual" and self.manual_target_w is not None:
            # applied immediately (no ramp); keep the limiter in sync so going back to
            # "slope" ramps smoothly from the manual value
            self.limiter.value = self.manual_target_w
            return self.manual_target_w
        d = self.bike.state.distance_m
        g = self.route.mean_grade(d, self.curve.lookahead_m)
        raw = self.curve.target_watts(g, ftp, self.effort_pct / 100.0)
        return self.limiter(raw, dt)

    # -- main tick ----------------------------------------------------------------------
    def tick(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        dt = 0.0 if self._last_tick is None else min(max(now - self._last_tick, 0.0), 1.0)
        self._last_tick = now
        r = self.hub.readings()
        pc = choose_power(r, self.profile.power_source)
        pedaling = (pc.power_w or 0) > 5 or (pc.cadence_rpm or 0) > 5

        if self.state == "ready" and pedaling:
            self._start_if_needed()
            self.state = "running"
        elif self.state == "paused" and pedaling and self._idle_s >= AUTO_PAUSE_AFTER_S:
            self.state = "running"  # auto-resume after an auto-pause

        running = self.state == "running"
        if running:
            self.elapsed_s += dt

        # trainer command (also while ready/paused so ERG is set when pedalling starts)
        if self.state != "finished":
            self.requested_target_w = self._target(dt if running else 0.0)
            if self.requested_target_w is None:
                self.sent_target_w = None
                self.hub.set_basic_resistance(FREE_RIDE_RESISTANCE_PCT)
            else:
                use_match = self.profile.power_match and pc.source == "power_meter"
                if use_match and running:
                    self.power_match.update(r, self.sent_target_w, dt)
                self.sent_target_w = (
                    self.power_match.apply(self.requested_target_w)
                    if use_match
                    else self.requested_target_w
                )
                self.hub.set_target_power(self.sent_target_w)

        # virtual bike
        mult = 1.0 + (self.difficulty_pct / 100.0 if self.mode == "gpx" else 0.0)
        if running:
            self.bike.step((pc.power_w or 0.0) * mult, dt)
        st = self.bike.state

        # auto pause: no power, no cadence, (virtually) stopped
        if running and not pedaling and st.speed_ms < 0.5:
            self._idle_s += dt
            if self._idle_s >= AUTO_PAUSE_AFTER_S:
                self.state = "paused"
        elif pedaling:
            self._idle_s = 0.0 if self.state == "running" else self._idle_s

        point = self.route.point_at(st.distance_m) if self.route else None
        if self.mode == "gpx" and st.distance_m >= self.route.total_distance_m - 0.5:
            self.state = "finished"
        if self.mode == "erg" and self.elapsed_s >= self.workout.duration_s and running:
            self.state = "finished"

        if running:
            self.recorder.add(
                Sample(
                    timestamp_s=time.time(),
                    elapsed_s=self.elapsed_s,
                    power_w=pc.power_w,
                    cadence_rpm=pc.cadence_rpm,
                    heart_rate_bpm=r.heart_rate_bpm,
                    speed_ms=st.speed_ms,
                    distance_m=st.distance_m,
                    altitude_m=point.altitude_m if point else None,
                    lat=point.lat if point else None,
                    lon=point.lon if point else None,
                    grade=point.grade if point else None,
                    target_w=self.requested_target_w,
                )
            )

        self.last = self._telemetry(r, pc, point)
        return self.last

    def _telemetry(self, r: Readings, pc: PowerChoice, point) -> dict:
        st = self.bike.state
        rho = self.bike.model.rho(st.altitude_m)
        f = st.forces
        v = st.speed_ms
        out = {
            "session_id": self.id,
            "workout_id": self.workout_id,
            "route_id": self.route_id,
            "mode": self.mode,
            "state": self.state,
            "name": self.name,
            "elapsed_s": round(self.elapsed_s, 2),
            "power_w": None if pc.power_w is None else round(pc.power_w),
            "power_wkg": w_per_kg(pc.power_w, self.profile.rider_mass_kg),
            "target_wkg": w_per_kg(self.requested_target_w, self.profile.rider_mass_kg),
            "power_source": pc.source,
            "cadence_source": pc.cadence_source,
            "trainer_power_w": r.trainer_power_w and round(r.trainer_power_w),
            "pm_power_w": r.pm_power_w and round(r.pm_power_w),
            "cadence_rpm": pc.cadence_rpm and round(pc.cadence_rpm),
            "heart_rate_bpm": r.heart_rate_bpm and round(r.heart_rate_bpm),
            "target_w": None if self.requested_target_w is None else round(self.requested_target_w),
            "sent_target_w": None if self.sent_target_w is None else round(self.sent_target_w),
            "power_match_offset_w": round(self.power_match.offset_w, 1),
            "speed_kmh": round(v * 3.6, 2),
            "distance_m": round(st.distance_m, 1),
            "grade": round(st.grade, 4),
            "altitude_m": round(st.altitude_m, 1),
            "air_density": round(rho, 4),
            "power_split_w": {
                "gravity": round(f.gravity_n * v, 1) if f else 0,
                "rolling": round(f.rolling_n * v, 1) if f else 0,
                "aero": round(f.aero_n * v, 1) if f else 0,
            },
            "intensity_pct": self.intensity_pct,
            "effort_pct": self.effort_pct,
            "difficulty_pct": self.difficulty_pct,
            "target_mode": self.target_mode,
            "manual_target_w": self.manual_target_w,
        }
        if point is not None:
            out.update(
                lat=point.lat,
                lon=point.lon,
                heading_deg=round(point.heading_deg, 1),
                route_distance_m=round(self.route.total_distance_m, 1),
            )
        if self.workout is not None:
            pos = self.workout.position(self.elapsed_s)
            nxt = None
            if pos.step_index + 1 < len(self.workout.steps):
                ns = self.workout.steps[pos.step_index + 1]
                t = ns.target_at(0, self.profile.ftp_w)
                nxt = None if t is None else round(t * self.intensity_pct / 100)
            out.update(
                step_index=pos.step_index,
                step_remaining_s=round(pos.step_remaining_s, 1),
                workout_duration_s=self.workout.duration_s,
                next_target_w=nxt,
            )
        return out
