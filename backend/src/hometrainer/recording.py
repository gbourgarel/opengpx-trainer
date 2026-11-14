"""Ride recording and FIT activity export (Sport=cycling, SubSport=virtual_activity)."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fit_tool.base_type import BaseType
from fit_tool.data_message import DataMessage
from fit_tool.developer_field import DeveloperField
from fit_tool.fit_file import FitFile
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.developer_data_id_message import DeveloperDataIdMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.field_description_message import FieldDescriptionMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.hrv_message import HrvMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.timestamp_correlation_message import TimestampCorrelationMessage
from fit_tool.profile.messages.user_profile_message import UserProfileMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.messages.zones_target_message import ZonesTargetMessage
from fit_tool.profile.profile_type import (
    Event,
    EventType,
    FileType,
    Intensity,
    LapTrigger,
    Manufacturer,
    RiderPositionType,
    Sport,
    SubSport,
    WorkoutStepDuration,
    WorkoutStepTarget,
)

from .pedaling import pedal_summary, position_changes

log = logging.getLogger(__name__)

# developer data: identifies this app's fields in the FIT file (16-byte application id)
TARGET_POWER_APP_ID = b"hometrainer\x00\x00\x00\x00\x01"
TARGET_POWER_FIELD = 0


@dataclass
class Sample:
    timestamp_s: float  # unix time
    elapsed_s: float
    power_w: float | None
    cadence_rpm: float | None
    heart_rate_bpm: float | None
    speed_ms: float
    distance_m: float
    altitude_m: float | None = None
    lat: float | None = None
    lon: float | None = None
    grade: float | None = None
    target_w: float | None = None
    step_index: int | None = None  # workout step being ridden (None: no workout / over)
    # dual-sided power meter (see hub.PedalData): FIT balance byte, %, [start, end] degrees
    lr_balance: int | None = None
    left_te: float | None = None
    right_te: float | None = None
    left_ps: float | None = None
    right_ps: float | None = None
    combined_ps: float | None = None
    left_power_phase: list[float] | None = None
    left_power_phase_peak: list[float] | None = None
    right_power_phase: list[float] | None = None
    right_power_phase_peak: list[float] | None = None
    left_pco: int | None = None
    right_pco: int | None = None
    rider_position: int | None = None  # FIT RiderPositionType
    rr_s: list[float] | None = None  # beat-to-beat intervals received during this second


def pedal_fields(p) -> dict:
    """Sample fields from a ``hub.PedalData`` (None: no dual-sided power meter)."""
    if p is None:
        return {}

    def pair(v):
        return None if v is None else [float(v[0]), float(v[1])]

    return {
        "lr_balance": p.balance,
        "left_te": p.left_te,
        "right_te": p.right_te,
        "left_ps": p.left_ps,
        "right_ps": p.right_ps,
        "combined_ps": p.combined_ps,
        "left_power_phase": pair(p.left_phase),
        "left_power_phase_peak": pair(p.left_peak_phase),
        "right_power_phase": pair(p.right_phase),
        "right_power_phase_peak": pair(p.right_peak_phase),
        "left_pco": p.left_pco_mm,
        "right_pco": p.right_pco_mm,
        "rider_position": p.rider_position,
    }


def ms(t: float) -> int:
    return int(round(t * 1000))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _target_field(watts: float) -> DeveloperField:
    """The ``target_power`` developer field (W), on records and on laps."""
    f = DeveloperField(
        developer_data_index=0,
        field_id=TARGET_POWER_FIELD,
        base_type=BaseType.UINT16,  # must match the field description
        size=2,
    )
    f.set_value(0, int(round(max(0.0, min(watts, 65534.0)))))
    return f


# Sample attribute -> FIT record field (pedal metrics of a dual-sided power meter)
_RECORD_PEDAL_FIELDS = (
    ("lr_balance", "left_right_balance"),
    ("left_te", "left_torque_effectiveness"),
    ("right_te", "right_torque_effectiveness"),
    ("left_ps", "left_pedal_smoothness"),
    ("right_ps", "right_pedal_smoothness"),
    ("combined_ps", "combined_pedal_smoothness"),
    ("left_power_phase", "left_power_phase"),
    ("left_power_phase_peak", "left_power_phase_peak"),
    ("right_power_phase", "right_power_phase"),
    ("right_power_phase_peak", "right_power_phase_peak"),
    ("left_pco", "left_pco"),
    ("right_pco", "right_pco"),
)


def hrv_is_synthetic(samples: list[Sample], tol_s: float = 0.010, share: float = 0.95) -> bool:
    """True when the "beat-to-beat" intervals are just 60 / heart rate.

    Some straps (a Polar over ANT+, seen on a real ride: 99.6 % of intervals within 10 ms of
    60/HR) fill the beat-time field from their averaged heart rate instead of the real beats.
    Real R-R intervals scatter around 60/HR (beat-to-beat variability, and the displayed HR is
    an average over several beats), so over a ride they are never almost all that close.
    Writing such intervals as HRV would mislead HRV analyses (e.g. DFA alpha 1)."""
    pairs = [
        (rr, s.heart_rate_bpm) for s in samples if s.heart_rate_bpm and s.rr_s for rr in s.rr_s
    ]
    if len(pairs) < 30:
        return False
    close = sum(1 for rr, hr in pairs if abs(rr - 60.0 / hr) <= tol_s)
    return close >= share * len(pairs)


def _hrv_message(rr_s: list[float]) -> HrvMessage:
    m = HrvMessage()
    m.time = list(rr_s) + [None] * (5 - len(rr_s))  # padding: FIT invalid (0xFFFF)
    return m


def split_laps(samples: list[Sample]) -> list[list[Sample]]:
    """One lap per workout step: consecutive samples sharing a step index.

    A ride without a workout is a single lap; after the end of a workout (mixed GPX ride),
    the rest of the route is one more lap.
    """
    laps: list[list[Sample]] = []
    for s in samples:
        if laps and laps[-1][-1].step_index == s.step_index:
            laps[-1].append(s)
        else:
            laps.append([s])
    return laps


class Recorder:
    """Keeps 1 Hz samples (the engine ticks at 4 Hz, the last sample of each second is kept)."""

    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self._last_second: int | None = None

    def add(self, s: Sample) -> None:
        sec = int(s.timestamp_s)
        if sec == self._last_second and self.samples:
            prev_rr = self.samples[-1].rr_s
            if prev_rr:  # beats are events, not a state: keep those of the replaced tick
                s.rr_s = prev_rr + (s.rr_s or [])
            self.samples[-1] = s
        else:
            self.samples.append(s)
            self._last_second = sec

    @classmethod
    def from_samples(cls, samples: list[Sample]) -> Recorder:
        r = cls()
        r.samples = list(samples)
        r._last_second = int(samples[-1].timestamp_s) if samples else None
        return r

    def snapshot(self) -> Recorder:
        """Copy of the samples recorded so far, to export without holding the session."""
        return Recorder.from_samples(self.samples)

    def summary(self) -> dict:
        if not self.samples:
            return {"duration_s": 0, "distance_m": 0, "avg_power_w": None}
        powers = [s.power_w or 0.0 for s in self.samples]
        hrs = [s.heart_rate_bpm for s in self.samples if s.heart_rate_bpm]
        np_w = normalized_power(powers)
        last = self.samples[-1]
        return {
            "duration_s": round(last.elapsed_s, 1),
            "distance_m": round(last.distance_m, 1),
            "avg_power_w": round(sum(powers) / len(powers), 1),
            "max_power_w": round(max(powers), 1),
            "normalized_power_w": round(np_w, 1) if np_w else None,
            "avg_hr_bpm": round(sum(hrs) / len(hrs), 1) if hrs else None,
            "avg_speed_kmh": round(3.6 * last.distance_m / last.elapsed_s, 2)
            if last.elapsed_s > 0
            else 0,
        }

    def write_fit(
        self, path: Path, athlete: Athlete | None = None, workout_name: str | None = None
    ) -> Path:
        if not self.samples:
            raise ValueError("Nothing recorded")
        athlete = athlete or Athlete()
        laps = split_laps(self.samples)
        first, last = self.samples[0], self.samples[-1]
        b = FitFileBuilder(auto_define=True, min_string_size=50)

        fid = FileIdMessage()
        fid.type = FileType.ACTIVITY
        fid.manufacturer = Manufacturer.DEVELOPMENT.value
        fid.product = 0
        fid.serial_number = 0x48544E52
        fid.time_created = ms(first.timestamp_s)
        b.add(fid)

        # the rider's weight, max HR and FTP, as a head unit writes them (analysis tools read
        # the FTP of the ride from here)
        if athlete.weight_kg or athlete.max_hr_bpm:
            up = UserProfileMessage()
            if athlete.weight_kg:
                up.weight = athlete.weight_kg
            if athlete.max_hr_bpm:
                up.default_max_heart_rate = athlete.max_hr_bpm
                up.default_max_biking_heart_rate = athlete.max_hr_bpm
            b.add(up)
        if athlete.ftp_w or athlete.max_hr_bpm:
            zt = ZonesTargetMessage()
            if athlete.ftp_w:
                zt.functional_threshold_power = int(round(athlete.ftp_w))
            if athlete.max_hr_bpm:
                zt.max_heart_rate = athlete.max_hr_bpm
            b.add(zt)
        for m in _workout_messages(laps, workout_name):
            b.add(m)

        # Developer field "target_power" (W) on each record: FIT has no standard per-second
        # target, so it is declared as developer data (readable by FIT analysis tools).
        dev = DeveloperDataIdMessage()
        dev.application_id = TARGET_POWER_APP_ID
        dev.developer_data_index = 0
        b.add(dev)
        desc = FieldDescriptionMessage()
        desc.developer_data_index = 0
        desc.field_definition_number = TARGET_POWER_FIELD
        desc.fit_base_type_id = BaseType.UINT16
        desc.field_name = "target_power"
        desc.units = "watts"
        b.add(desc)

        ev = EventMessage()
        ev.event = Event.TIMER
        ev.event_type = EventType.START
        ev.timestamp = ms(ride_start_s(first))
        b.add(ev)

        changes = dict(position_changes(self.samples))  # timestamp -> FIT rider position
        rr_pending: list[float] = []
        write_hrv = not hrv_is_synthetic(self.samples)
        if not write_hrv:
            log.warning("R-R intervals are 60/HR (strap does not send real beats): no HRV in FIT")
        accumulated = 0  # FIT accumulated_power: running sum of the 1 Hz powers (W)
        prev_s: Sample | None = None
        for s in self.samples:
            if prev_s is not None:
                # a pause: wall time went on, riding time did not -> timer stop / start events
                riding = s.elapsed_s - prev_s.elapsed_s
                if (s.timestamp_s - prev_s.timestamp_s) - riding > PAUSE_GAP_S:
                    for ts, kind in (
                        (prev_s.timestamp_s, EventType.STOP_ALL),
                        (s.timestamp_s - riding, EventType.START),
                    ):
                        tev = EventMessage()
                        tev.timestamp = ms(ts)
                        tev.event = Event.TIMER
                        tev.event_type = kind
                        b.add(tev)
            prev_s = s
            if s.timestamp_s in changes:
                pev = EventMessage()
                pev.timestamp = ms(s.timestamp_s)
                pev.event = Event.RIDER_POSITION_CHANGE
                pev.event_type = EventType.MARKER
                pev.rider_position = RiderPositionType(changes[s.timestamp_s])
                b.add(pev)
            # no target during free-ride steps
            fields = [] if s.target_w is None else [_target_field(s.target_w)]
            r = RecordMessage(developer_fields=fields)
            r.timestamp = ms(s.timestamp_s)
            r.distance = s.distance_m
            r.speed = s.speed_ms
            if s.power_w is not None:
                r.power = int(round(s.power_w))
                accumulated += r.power
                r.accumulated_power = accumulated
            if s.cadence_rpm is not None:
                r.cadence = int(round(s.cadence_rpm))
            if s.heart_rate_bpm is not None:
                r.heart_rate = int(round(s.heart_rate_bpm))
            if s.altitude_m is not None:
                r.altitude = s.altitude_m
            if s.lat is not None and s.lon is not None:
                r.position_lat = s.lat
                r.position_long = s.lon
            if s.grade is not None:
                r.grade = s.grade * 100
            for attr, field in _RECORD_PEDAL_FIELDS:
                if (v := getattr(s, attr)) is not None:
                    setattr(r, field, v)
            b.add(r)
            # HRV: beat-to-beat intervals, 5 per message (fixed size: one definition only)
            rr_pending += (s.rr_s or []) if write_hrv else []
            while len(rr_pending) >= 5:
                b.add(_hrv_message(rr_pending[:5]))
                del rr_pending[:5]
        if rr_pending:
            b.add(_hrv_message(rr_pending))

        ev = EventMessage()
        ev.event = Event.TIMER
        ev.event_type = EventType.STOP_ALL
        ev.timestamp = ms(last.timestamp_s)
        b.add(ev)

        # workout_step_index of a lap: its step in the workout embedded above (as ridden)
        step_of_lap = {lap: n for n, lap in enumerate(workout_laps(laps))}
        prev: Sample | None = None  # last sample of the previous lap: where this one starts
        for i, group in enumerate(laps):
            lap = self._lap_message(i, group, prev, is_last=i == len(laps) - 1)
            if i in step_of_lap:
                lap.workout_step_index = step_of_lap[i]
            b.add(lap)
            prev = group[-1]

        summ = self.summary()
        start = ride_start_s(first)
        # never below the timer time (FIT: timer <= elapsed), whatever the clocks' rounding
        elapsed = max(last.timestamp_s - start, last.elapsed_s)

        ses = SessionMessage()
        ses.timestamp = ms(last.timestamp_s)
        ses.start_time = ms(start)
        ses.total_elapsed_time = elapsed
        ses.total_timer_time = last.elapsed_s
        ses.total_distance = last.distance_m
        ses.sport = Sport.CYCLING
        ses.sub_sport = SubSport.VIRTUAL_ACTIVITY
        ses.first_lap_index = 0
        ses.num_laps = len(laps)
        if summ["avg_power_w"] is not None:
            ses.avg_power = int(summ["avg_power_w"])
            ses.max_power = int(summ["max_power_w"])
        if summ.get("normalized_power_w"):
            ses.normalized_power = int(summ["normalized_power_w"])
        if summ.get("avg_hr_bpm"):
            ses.avg_heart_rate = int(summ["avg_hr_bpm"])
        cads = [s.cadence_rpm for s in self.samples if s.cadence_rpm]  # zeros excluded
        if cads:
            ses.avg_cadence = int(round(_mean(cads)))
        for k, v in _totals(self.samples, None).items():
            setattr(ses, k, v)
        np_w = summ.get("normalized_power_w")
        if athlete.ftp_w:
            # Coggan: IF = NP / FTP, TSS = t x NP x IF / (FTP x 3600) x 100 (t: riding time);
            # checked against an Edge 540 file (NP 192, FTP 266, 5408 s -> IF 0.722, TSS 78)
            ses.threshold_power = int(round(athlete.ftp_w))
            if np_w:
                intensity = np_w / athlete.ftp_w
                ses.intensity_factor = intensity
                ses.training_stress_score = (
                    last.elapsed_s * np_w * intensity / (athlete.ftp_w * 3600) * 100
                )
        for k, v in pedal_summary(self.samples).items():
            setattr(ses, k, v)
        b.add(ses)

        # local time of the ride (analysis tools show the time of day from it)
        local = _fit_local_timestamp(last.timestamp_s)
        tc = TimestampCorrelationMessage()
        tc.timestamp = ms(last.timestamp_s)
        tc.system_timestamp = ms(last.timestamp_s)
        tc.local_timestamp = local
        b.add(tc)

        act = ActivityMessage()
        act.timestamp = ms(last.timestamp_s)
        act.total_timer_time = last.elapsed_s
        act.num_sessions = 1
        act.local_timestamp = local
        b.add(act)

        path.parent.mkdir(parents=True, exist_ok=True)
        b.build().to_file(str(path))
        return path

    @staticmethod
    def _lap_message(index: int, group: list[Sample], prev: Sample | None, is_last: bool):
        """Lap for one workout step: averages over its 1 Hz samples (riding time only, like
        the session), the average target as the ``target_power`` developer field."""
        first, last = group[0], group[-1]
        start_ts = ride_start_s(first) if prev is None else prev.timestamp_s
        timer = last.elapsed_s - (0.0 if prev is None else prev.elapsed_s)
        powers = [s.power_w or 0.0 for s in group]
        hrs = [s.heart_rate_bpm for s in group if s.heart_rate_bpm]
        cads = [s.cadence_rpm for s in group if s.cadence_rpm]  # zeros excluded (coasting)
        targets = [s.target_w for s in group if s.target_w is not None]
        avg_target = _mean(targets)
        lap = LapMessage(developer_fields=[] if avg_target is None else [_target_field(avg_target)])
        lap.message_index = index
        lap.event = Event.LAP
        lap.event_type = EventType.STOP
        lap.timestamp = ms(last.timestamp_s)
        lap.start_time = ms(start_ts)
        lap.total_elapsed_time = max(last.timestamp_s - start_ts, timer)
        lap.total_timer_time = timer
        lap.total_distance = last.distance_m - (0.0 if prev is None else prev.distance_m)
        lap.avg_power = int(round(_mean(powers)))
        lap.max_power = int(round(max(powers)))
        np_w = normalized_power(powers)  # None under 30 s
        if np_w:
            lap.normalized_power = int(round(np_w))
        if hrs:
            lap.avg_heart_rate = int(round(_mean(hrs)))
            lap.max_heart_rate = int(round(max(hrs)))
        if cads:
            lap.avg_cadence = int(round(_mean(cads)))
        lap.lap_trigger = LapTrigger.SESSION_END if is_last else LapTrigger.TIME
        for k, v in _totals(group, prev).items():
            setattr(lap, k, v)
        for k, v in pedal_summary(group).items():
            setattr(lap, k, v)
        return lap


class RideAverages:
    """Live averages since the start of the ride, updated incrementally at each tick.

    * average power: time-weighted over the riding time (pauses excluded);
    * normalized power: same definition as ``normalized_power`` (30 s rolling mean of 1 s
      power, 4th-power mean, 4th root), fed with 1 s buckets built from the ticks.
    """

    WINDOW = 30

    def __init__(self) -> None:
        self.time_s = 0.0
        self.energy_j = 0.0
        self._bucket_t = 0.0
        self._bucket_e = 0.0
        self._window: deque[float] = deque()
        self._window_sum = 0.0
        self._sum4 = 0.0
        self._n4 = 0

    def add(self, power_w: float, dt: float) -> None:
        if dt <= 0:
            return
        self.time_s += dt
        self.energy_j += power_w * dt
        self._bucket_t += dt
        self._bucket_e += power_w * dt
        while self._bucket_t >= 1.0:
            # close a 1 s bucket (a tick spanning a boundary is split proportionally)
            over = self._bucket_t - 1.0
            p1 = (self._bucket_e - power_w * over) / 1.0
            self._push_second(p1)
            self._bucket_t = over
            self._bucket_e = power_w * over

    def _push_second(self, p: float) -> None:
        self._window.append(p)
        self._window_sum += p
        if len(self._window) > self.WINDOW:
            self._window_sum -= self._window.popleft()
        if len(self._window) == self.WINDOW:
            self._sum4 += (self._window_sum / self.WINDOW) ** 4
            self._n4 += 1

    @property
    def avg_power_w(self) -> float | None:
        return self.energy_j / self.time_s if self.time_s > 0 else None

    @property
    def np_w(self) -> float | None:
        return (self._sum4 / self._n4) ** 0.25 if self._n4 else None


@dataclass(frozen=True)
class Athlete:
    """Rider data written into the FIT file (from the profile at save time)."""

    ftp_w: float | None = None
    weight_kg: float | None = None
    max_hr_bpm: int | None = None


# Gross efficiency of the rider (mechanical work / metabolic energy), to turn the work into
# calories like a Garmin Edge does. Fitted on the user's Edge 540 files (1146 kcal for
# 1016 kJ, 1128 kcal for 1012 kJ: 21.2 % and 21.4 %); typical values are 20-25 %.
GROSS_EFFICIENCY = 0.213
J_PER_KCAL = 4184.0
FIT_EPOCH_S = 631065600  # 1989-12-31T00:00:00Z, origin of FIT local timestamps
PAUSE_GAP_S = 1.5  # wall time beyond riding time between two samples: the ride was paused


def _totals(group: list[Sample], prev: Sample | None) -> dict:
    """Lap / session totals computable from the 1 Hz samples (riding seconds only):
    work, calories, crank revolutions, maxima, speeds, climbing. ``prev``: the sample just
    before the group (its altitude is where the group's climbing starts)."""
    powers = [s.power_w or 0.0 for s in group]
    work_j = sum(powers)  # one sample per riding second
    out: dict = {
        "total_work": int(round(work_j)),
        "total_calories": int(round(work_j / GROSS_EFFICIENCY / J_PER_KCAL)),
        "enhanced_max_speed": max(s.speed_ms for s in group),
    }
    timer = group[-1].elapsed_s - (0.0 if prev is None else prev.elapsed_s)
    dist = group[-1].distance_m - (0.0 if prev is None else prev.distance_m)
    if timer > 0:
        out["enhanced_avg_speed"] = dist / timer
    cads = [s.cadence_rpm for s in group if s.cadence_rpm]
    if cads:
        out["max_cadence"] = int(round(max(cads)))
        out["total_cycles"] = int(round(sum(cads) / 60.0))  # rpm x 1 s
    hrs = [s.heart_rate_bpm for s in group if s.heart_rate_bpm]
    if hrs:
        out["max_heart_rate"] = int(round(max(hrs)))
    alts = [s.altitude_m for s in ([prev] if prev else []) + group if s.altitude_m is not None]
    if len(alts) >= 2:
        diffs = [b - a for a, b in zip(alts, alts[1:], strict=False)]
        out["total_ascent"] = int(round(sum(d for d in diffs if d > 0)))
        out["total_descent"] = int(round(-sum(d for d in diffs if d < 0)))
    return out


def workout_laps(laps: list[list[Sample]]) -> list[int]:
    """Indexes (in ``laps``) of the laps ridden on a workout step, in order: the workout as
    ridden (a skipped step is absent, an extended one longer)."""
    return [i for i, group in enumerate(laps) if group[0].step_index is not None]


def _workout_messages(laps: list[list[Sample]], name: str | None) -> list:
    """The workout embedded in the activity, as a Garmin head unit does: intervals.icu
    extracts it and shows the targets on the activity chart (it ignores the ``target_power``
    developer field). One step per workout lap with its ridden duration; target = the range
    of the targets held on it, in watts (FIT custom power targets: watts + 1000)."""
    idx = workout_laps(laps)
    if not idx:
        return []
    wkt = WorkoutMessage()
    wkt.sport = Sport.CYCLING
    wkt.sub_sport = SubSport.VIRTUAL_ACTIVITY
    wkt.workout_name = (name or "Workout")[:40]
    wkt.num_valid_steps = len(idx)
    out: list = [wkt]
    for n, i in enumerate(idx):
        group, prev = laps[i], (laps[i - 1][-1] if i > 0 else None)
        step = WorkoutStepMessage()
        step.message_index = n
        step.duration_type = WorkoutStepDuration.TIME
        step.duration_time = group[-1].elapsed_s - (0.0 if prev is None else prev.elapsed_s)
        step.intensity = Intensity.ACTIVE
        targets = [s.target_w for s in group if s.target_w is not None]
        if targets:
            step.target_type = WorkoutStepTarget.POWER
            step.target_value = 0  # 0: the custom range below, not a power zone
            step.custom_target_power_low = int(round(min(targets))) + 1000
            step.custom_target_power_high = int(round(max(targets))) + 1000
        else:
            step.target_type = WorkoutStepTarget.OPEN  # free-ride step
        out.append(step)
    return out


def _fit_local_timestamp(unix_s: float) -> int:
    """FIT local timestamp: seconds since the FIT epoch, in this machine's local time."""
    offset = datetime.fromtimestamp(unix_s).astimezone().utcoffset() or timedelta(0)
    return int(unix_s + offset.total_seconds()) - FIT_EPOCH_S


def ride_start_s(first: Sample) -> float:
    """When the riding time started. The recorder keeps the last tick of each second, so the
    first sample comes up to ~1 s after the ride started: its `elapsed_s` already counts
    that time. Session and first lap start here, so their elapsed time is never below their
    timer time (KNOWN_ISSUES #13)."""
    return first.timestamp_s - first.elapsed_s


# How the rider felt the ride, as a Garmin Edge records it (session fields 192 / 193, FIT SDK
# 21.141; checked on an Edge 540 file): feel on 0-100 in five levels, RPE 1-10 stored x 10.
FEEL_LEVELS = (0, 25, 50, 75, 100)  # very weak, weak, normal, strong, very strong
_FEEL_FIELD, _RPE_FIELD = 192, 193


def write_ride_feedback(path: Path, rpe: int | None, feel: int | None) -> None:
    """Set (or clear, with None) the RPE and feel of a FIT activity written by `write_fit`.

    The file is read and rebuilt message by message (developer fields kept); only the
    session message changes. Written to a temporary file then renamed, so a reader (upload,
    download) never sees a half-written file.
    """
    if rpe is not None and not 1 <= rpe <= 10:
        raise ValueError("RPE must be 1-10")
    if feel is not None and feel not in FEEL_LEVELS:
        raise ValueError(f"feel must be one of {FEEL_LEVELS}")
    ff = FitFile.from_file(str(path))
    b = FitFileBuilder(auto_define=True, min_string_size=50)
    for rec in ff.records:
        m = rec.message
        if not isinstance(m, DataMessage):
            continue  # definitions are rebuilt by the builder
        if isinstance(m, SessionMessage):
            # a message read from a file only holds the fields it was written with: copy them
            # into a fresh one, which can take the new fields
            ses = SessionMessage()
            for f in m.fields:
                if f.is_valid() and f.field_id not in (_FEEL_FIELD, _RPE_FIELD):
                    ses.get_field(f.field_id).set_values(f.get_values())
            if rpe is not None:
                ses.workout_rpe = rpe * 10
            if feel is not None:
                ses.workout_feel = feel
            m = ses
        b.add(m)
    tmp = path.with_suffix(".fit.tmp")
    b.build().to_file(str(tmp))
    tmp.replace(path)


def normalized_power(powers_1hz: list[float]) -> float | None:
    if len(powers_1hz) < 30:
        return None
    window = 30
    acc = sum(powers_1hz[:window])
    rolling = [acc / window]
    for i in range(window, len(powers_1hz)):
        acc += powers_1hz[i] - powers_1hz[i - window]
        rolling.append(acc / window)
    return (sum(p**4 for p in rolling) / len(rolling)) ** 0.25
