"""Ride recording and FIT activity export (Sport=cycling, SubSport=virtual_activity)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from fit_tool.base_type import BaseType
from fit_tool.developer_field import DeveloperField
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.developer_data_id_message import DeveloperDataIdMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.field_description_message import FieldDescriptionMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Event,
    EventType,
    FileType,
    Manufacturer,
    Sport,
    SubSport,
)

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


def ms(t: float) -> int:
    return int(round(t * 1000))


class Recorder:
    """Keeps 1 Hz samples (the engine ticks at 4 Hz, the last sample of each second is kept)."""

    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self._last_second: int | None = None

    def add(self, s: Sample) -> None:
        sec = int(s.timestamp_s)
        if sec == self._last_second and self.samples:
            self.samples[-1] = s
        else:
            self.samples.append(s)
            self._last_second = sec

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

        for s in self.samples:
            fields = []
            if s.target_w is not None:  # none during free-ride steps
                f = DeveloperField(
                    developer_data_index=0,
                    field_id=TARGET_POWER_FIELD,
                    base_type=BaseType.UINT16,  # must match the field description
                    size=2,
                )
                f.set_value(0, int(round(max(0.0, min(s.target_w, 65534.0)))))
                fields.append(f)
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
            b.add(r)

        ev = EventMessage()
        ev.event = Event.TIMER
        ev.event_type = EventType.STOP_ALL
        ev.timestamp = ms(last.timestamp_s)
        b.add(ev)

        summ = self.summary()
        elapsed = last.timestamp_s - first.timestamp_s
        lap = LapMessage()
        lap.timestamp = ms(last.timestamp_s)
        lap.start_time = ms(first.timestamp_s)
        lap.total_elapsed_time = elapsed
        lap.total_timer_time = last.elapsed_s
        lap.total_distance = last.distance_m
        if summ["avg_power_w"] is not None:
            lap.avg_power = int(summ["avg_power_w"])
        b.add(lap)

        ses = SessionMessage()
        ses.timestamp = ms(last.timestamp_s)
        ses.start_time = ms(first.timestamp_s)
        ses.total_elapsed_time = elapsed
        ses.total_timer_time = last.elapsed_s
        ses.total_distance = last.distance_m
        ses.sport = Sport.CYCLING
        ses.sub_sport = SubSport.VIRTUAL_ACTIVITY
        ses.first_lap_index = 0
        ses.num_laps = 1
        if summ["avg_power_w"] is not None:
            ses.avg_power = int(summ["avg_power_w"])
            ses.max_power = int(summ["max_power_w"])
        if summ.get("normalized_power_w"):
            ses.normalized_power = int(summ["normalized_power_w"])
        if summ.get("avg_hr_bpm"):
            ses.avg_heart_rate = int(summ["avg_hr_bpm"])
        b.add(ses)

        act = ActivityMessage()
        act.timestamp = ms(last.timestamp_s)
        act.total_timer_time = last.elapsed_s
        act.num_sessions = 1
        b.add(act)

        path.parent.mkdir(parents=True, exist_ok=True)
        b.build().to_file(str(path))
        return path


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
