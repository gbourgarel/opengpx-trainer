"""Ride recording and FIT activity export (Sport=cycling, SubSport=virtual_activity)."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
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
from fit_tool.profile.profile_type import (
    Event,
    EventType,
    FileType,
    LapTrigger,
    Manufacturer,
    RiderPositionType,
    Sport,
    SubSport,
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

    def write_fit(self, path: Path) -> Path:
        if not self.samples:
            raise ValueError("Nothing recorded")
        first, last = self.samples[0], self.samples[-1]
        b = FitFileBuilder(auto_define=True, min_string_size=50)

        fid = FileIdMessage()
        fid.type = FileType.ACTIVITY
        fid.manufacturer = Manufacturer.DEVELOPMENT.value
        fid.product = 0
        fid.serial_number = 0x48544E52
        fid.time_created = ms(first.timestamp_s)
        b.add(fid)

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
        ev.timestamp = ms(first.timestamp_s)
        b.add(ev)

        changes = dict(position_changes(self.samples))  # timestamp -> FIT rider position
        rr_pending: list[float] = []
        write_hrv = not hrv_is_synthetic(self.samples)
        if not write_hrv:
            log.warning("R-R intervals are 60/HR (strap does not send real beats): no HRV in FIT")
        for s in self.samples:
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

        laps = split_laps(self.samples)
        prev: Sample | None = None  # last sample of the previous lap: where this one starts
        for i, group in enumerate(laps):
            b.add(self._lap_message(i, group, prev, is_last=i == len(laps) - 1))
            prev = group[-1]

        summ = self.summary()
        elapsed = last.timestamp_s - first.timestamp_s

        ses = SessionMessage()
        ses.timestamp = ms(last.timestamp_s)
        ses.start_time = ms(first.timestamp_s)
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
        for k, v in pedal_summary(self.samples).items():
            setattr(ses, k, v)
        b.add(ses)

        act = ActivityMessage()
        act.timestamp = ms(last.timestamp_s)
        act.total_timer_time = last.elapsed_s
        act.num_sessions = 1
        b.add(act)

        path.parent.mkdir(parents=True, exist_ok=True)
        b.build().to_file(str(path))
        return path

    @staticmethod
    def _lap_message(index: int, group: list[Sample], prev: Sample | None, is_last: bool):
        """Lap for one workout step: averages over its 1 Hz samples (riding time only, like
        the session), the average target as the ``target_power`` developer field."""
        first, last = group[0], group[-1]
        start_ts = first.timestamp_s if prev is None else prev.timestamp_s
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
        lap.total_elapsed_time = last.timestamp_s - start_ts
        lap.total_timer_time = last.elapsed_s - (0.0 if prev is None else prev.elapsed_s)
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
        if first.step_index is not None:
            lap.workout_step_index = first.step_index
        lap.lap_trigger = LapTrigger.SESSION_END if is_last else LapTrigger.TIME
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
