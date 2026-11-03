"""Ride session engine (ticked at ~4 Hz by the app).

Modes
-----
* ``erg``: target power from a structured workout x intensity %. Virtual speed on flat road.
* ``gpx``: pseudo-ERG; target power from the grade->power curve on the look-ahead grade x effort %
  (``target_mode="slope"``), or set directly by the rider in watts (``target_mode="manual"``).
  Virtual speed comes from the dynamic model fed with ``measured power x (1 + difficulty %)``.
* ``gpx`` + workout (mixed): the workout sets the target (x intensity %) while the route gives
  speed, position, grade and VAM; free-ride steps use the slope curve. The route loops while the
  workout lasts; once the workout is over, the slope curve takes over until the end of the lap.

Power source
------------
The power used for the speed model, display and recording comes from the power meter when one is
selected / detected (``auto``), else from the trainer. With a power meter and ``power_match``,
the ERG target sent to the trainer is corrected so that the *power meter* reads the request.
"""

from __future__ import annotations

import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .ant.hub import Readings, SensorHub
from .checkpoint import RideCheckpoint
from .gpx.route import Route
from .physics.grade_power import RateLimiter
from .physics.model import VirtualBike, flat_road
from .profile import Profile
from .recording import Recorder, RideAverages, Sample
from .workouts.model import Step, Workout, WorkoutPosition

Mode = Literal["erg", "gpx"]
TargetMode = Literal["slope", "manual"]
MAX_MANUAL_TARGET_W = 2000.0
MAX_STEP_EXTENSION_S = 600.0
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


class ClimbTracker:
    """Climb rate (VAM, m/h) and cumulative elevation gain along the virtual route.

    VAM over a sliding window from the altitude actually travelled; it needs a few seconds of
    data before it is reported, so it does not jump around at the start of a ride.
    """

    def __init__(self, window_s: float = 30.0, min_span_s: float = 5.0):
        self.window_s = window_s
        self.min_span_s = min_span_s
        self._hist: deque[tuple[float, float]] = deque()  # (elapsed s, altitude m)
        self.elevation_gain_m = 0.0

    def update(self, elapsed_s: float, altitude_m: float) -> None:
        if self._hist:
            rise = altitude_m - self._hist[-1][1]
            if rise > 0:
                self.elevation_gain_m += rise
        self._hist.append((elapsed_s, altitude_m))
        while self._hist and elapsed_s - self._hist[0][0] > self.window_s:
            self._hist.popleft()

    def break_continuity(self) -> None:
        """Forget the window (e.g. the route wrapped back to its start): the next altitude is
        a new baseline, neither gain nor VAM."""
        self._hist.clear()

    @property
    def vam_mh(self) -> float | None:
        if len(self._hist) < 2:
            return None
        (t0, a0), (t1, a1) = self._hist[0], self._hist[-1]
        if t1 - t0 < self.min_span_s:
            return None
        return (a1 - a0) / (t1 - t0) * 3600.0


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
        if name is None:
            parts = [x.name for x in (route, workout) if x is not None]
            name = " · ".join(parts) or "Ride"
        self.name = name
        # identify the ride so any client (after a reload, another device) can rebuild its view
        self.id = uuid.uuid4().hex
        self.workout_id = workout_id
        self.route_id = route_id
        self.saved: dict | None = None  # set once the ride is written to history (save once)
        self.save_started = False  # the engine launched its background save
        self.checkpoint: RideCheckpoint | None = None  # crash-safe copy, set by the app
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
        if route is not None:
            lap_m = route.total_distance_m

            def grade_fn(d: float) -> tuple[float, float]:
                # the route repeats (laps) when a workout outlasts it
                return route.grade_and_altitude(d % lap_m)
        else:
            grade_fn = flat_road
        self.bike = VirtualBike(profile.model_params(), grade_fn)
        self._lap = 0  # completed laps of the route
        self._workout_end_lap: int | None = None  # lap index when the workout ended
        self.recorder = Recorder()
        self._idle_s = 0.0
        self._last_tick: float | None = None
        self.climb = ClimbTracker()
        self.averages = RideAverages()
        # average power of the current workout step (interval), reset at each new step
        self._step_index: int | None = None
        self._step_energy_j = 0.0
        self._step_time_s = 0.0
        # rider changes to the workout: steps skipped / extended (this session's copy of the
        # workout is edited; the revision tells clients to reload it)
        self.workout_rev = 0
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

    # -- workout edits (rider) ------------------------------------------------------------
    def _current_step(self) -> tuple[Step, WorkoutPosition]:
        if self.workout is None:
            raise ValueError("No workout in this ride")
        if self.workout_done or self.state == "finished":
            raise ValueError("The workout is over")
        pos = self.workout.position(self.elapsed_s)
        return self.workout.steps[pos.step_index], pos

    def skip_step(self) -> None:
        """End the current step now: the next one starts at the next tick."""
        step, pos = self._current_step()
        step.duration_s = pos.time_in_step_s  # time already ridden in it (may be 0)
        self.workout_rev += 1

    def extend_step(self, seconds: float) -> None:
        """Make the current step longer (a ramp is stretched: same start and end power)."""
        if not 0 < seconds <= MAX_STEP_EXTENSION_S:
            raise ValueError(f"seconds must be in (0, {MAX_STEP_EXTENSION_S:.0f}]")
        step, _ = self._current_step()
        step.duration_s += float(seconds)
        self.workout_rev += 1

    def checkpoint_now(self, now: float, final: bool = False) -> None:
        """Append the new samples to the checkpoint file (at most every 30 s unless final)."""
        if self.checkpoint is None or self.started_at is None:
            return
        header = {
            "session_id": self.id,
            "mode": self.mode,
            "name": self.name,
            "started_at": self.started_at.isoformat(),
        }
        self.checkpoint.update(header, self.recorder.samples, now, final)

    def _start_if_needed(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now(UTC)

    # -- route / workout progress ---------------------------------------------------------
    @property
    def route_position_m(self) -> float:
        """Position on the route within the current lap."""
        if self.route is None:
            return 0.0
        return self.bike.state.distance_m % self.route.total_distance_m

    @property
    def workout_done(self) -> bool:
        return self.workout is not None and self.elapsed_s >= self.workout.duration_s

    # -- target computation -------------------------------------------------------------
    def _workout_target(self) -> float | None:
        t = self.workout.target_watts(self.elapsed_s, self.profile.ftp_w)
        return None if t is None else t * self.intensity_pct / 100.0

    def _target(self, dt: float) -> float | None:
        ftp = self.profile.ftp_w
        if self.mode == "erg":
            return self._workout_target()
        if self.target_mode == "manual" and self.manual_target_w is not None:
            # applied immediately (no ramp); keep the limiter in sync so going back to
            # "slope" ramps smoothly from the manual value
            self.limiter.value = self.manual_target_w
            return self.manual_target_w
        if self.workout is not None and not self.workout_done:
            # GPX + workout: the workout sets the target; free-ride steps use the slope
            t = self._workout_target()
            if t is not None:
                self.limiter.value = t  # smooth hand-over to the slope curve later
                return t
        g = self.route.mean_grade(self.route_position_m, self.curve.lookahead_m)
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
            self.averages.add(pc.power_w or 0.0, dt)  # measured power (no difficulty factor)
            if self.workout is not None and not self.workout_done:
                # the tick's power belongs to the step being ridden at the end of the tick
                idx = self.workout.position(self.elapsed_s).step_index
                if idx != self._step_index:
                    self._step_index, self._step_energy_j, self._step_time_s = idx, 0.0, 0.0
                self._step_energy_j += (pc.power_w or 0.0) * dt
                self._step_time_s += dt
        st = self.bike.state
        if self.route is not None:
            lap = int(st.distance_m // self.route.total_distance_m)
            if lap != self._lap:
                # back at the start of the route: the altitude jump is not climbing
                self.climb.break_continuity()
                self._lap = lap
        if running and self.mode == "gpx":
            self.climb.update(self.elapsed_s, st.altitude_m)

        # auto pause: no power, no cadence and, on a route, (virtually) stopped. In ERG the
        # flat virtual road coasts down for ~2 min from 34 km/h, which kept the workout clock
        # running and recorded zeros: pause on pedalling alone there.
        stopped = self.mode == "erg" or st.speed_ms < 0.5
        if running and not pedaling and stopped:
            self._idle_s += dt
            if self._idle_s >= AUTO_PAUSE_AFTER_S:
                self.state = "paused"
        elif pedaling:
            self._idle_s = 0.0 if self.state == "running" else self._idle_s

        point = self.route.point_at(self.route_position_m) if self.route else None
        if self.mode == "erg" and self.workout_done and running:
            self.state = "finished"
        if self.mode == "gpx":
            lap_m = self.route.total_distance_m
            if self.workout is None:
                end_m = lap_m  # plain GPX ride: one pass over the route
            elif self.workout_done:
                # workout over: carry on with the slope until the end of the current lap
                if self._workout_end_lap is None:
                    self._workout_end_lap = self._lap
                end_m = (self._workout_end_lap + 1) * lap_m
            else:
                end_m = None  # workout still running: the route loops
            if end_m is not None and st.distance_m >= end_m - 0.5:
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
                    # one FIT lap per workout step; in ERG the finishing tick belongs to the
                    # last step, in a mixed ride the rest of the route is a lap of its own
                    step_index=self.workout.position(self.elapsed_s).step_index
                    if self.workout is not None and (self.mode == "erg" or not self.workout_done)
                    else None,
                )
            )

        if running and self.state == "finished":
            # finished on its own: no more trainer commands are sent after this tick, and the
            # ANT sender would keep re-sending the last target (e.g. the summit's climbing
            # power) until the ride is closed. Hand the trainer back to free ride.
            self.requested_target_w = self.sent_target_w = None
            self.hub.set_basic_resistance(FREE_RIDE_RESISTANCE_PCT)

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
            # averages since the start (riding time only)
            "avg_speed_kmh": round(st.distance_m / self.elapsed_s * 3.6, 2)
            if self.elapsed_s > 0
            else None,
            "avg_power_w": None if (a := self.averages.avg_power_w) is None else round(a),
            "np_w": None if (n := self.averages.np_w) is None else round(n),
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
                route_position_m=round(self.route_position_m, 1),
                lap=self._lap + 1,
            )
            vam = self.climb.vam_mh
            # instantaneous vertical speed from the model: v·sin(θ), tan(θ) = grade
            vam_instant = st.speed_ms * math.sin(math.atan(st.grade)) * 3600.0
            out.update(
                vam_mh=None if vam is None else round(vam),
                vam_instant_mh=round(vam_instant),
                elevation_gain_m=round(self.climb.elevation_gain_m, 1),  # actually climbed
                # still to climb until the end of the route (of the current lap if it loops)
                elevation_left_m=round(
                    self.route.gain_between(self.route_position_m, self.route.total_distance_m), 1
                ),
            )
        if self.workout is not None:
            pos = self.workout.position(self.elapsed_s)
            nxt = None
            if pos.step_index + 1 < len(self.workout.steps):
                ns = self.workout.steps[pos.step_index + 1]
                t = ns.target_at(0, self.profile.ftp_w)
                nxt = None if t is None else round(t * self.intensity_pct / 100)
            out.update(
                workout_rev=self.workout_rev,
                step_index=pos.step_index,
                step_remaining_s=round(pos.step_remaining_s, 1),
                workout_duration_s=self.workout.duration_s,
                next_target_w=nxt,
                # average power since the start of the current step (riding time only)
                step_avg_power_w=round(self._step_energy_j / self._step_time_s)
                if self._step_index == pos.step_index and self._step_time_s > 0
                else None,
            )
        return out
