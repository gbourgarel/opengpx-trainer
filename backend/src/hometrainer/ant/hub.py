"""Sensor hub abstraction: trainer (FE-C) + optional power meter + optional heart-rate strap."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# A reading (and a device's "connected" flag) is dropped after this long without any message.
# 5 s rides through short reception gaps (a real ride had all ANT+ devices silent for 4.2 s at
# the stick level), while a real disconnection is still noticed quickly. Stopping pedalling is
# handled separately (power/cadence drop to 0 from the sensor's own event counter, ~3 s).
STALE_AFTER_S = 5.0


@dataclass
class SensorValue:
    value: Any = None  # a number, or a tuple for multi-field pages (pedal metrics)
    updated: float = 0.0  # time.monotonic()

    def set(self, v: Any) -> None:
        self.value = v
        self.updated = time.monotonic()

    def fresh(self, now: float | None = None) -> Any:
        now = time.monotonic() if now is None else now
        return self.value if now - self.updated <= STALE_AFTER_S else None


@dataclass(frozen=True)
class PedalData:
    """Pedalling metrics of a dual-sided power meter (None: not sent, or stale).

    Angles in degrees on the crank circle (0 at the top, clockwise seen from the right).
    """

    # FIT ``left_right_balance`` byte: bit 7 set = bits 0-6 are the right pedal's share (%)
    balance: int | None = None
    left_te: float | None = None  # torque effectiveness, %
    right_te: float | None = None
    left_ps: float | None = None  # pedal smoothness, %
    right_ps: float | None = None
    combined_ps: float | None = None
    left_phase: tuple[float, float] | None = None  # power phase (start, end)
    left_peak_phase: tuple[float, float] | None = None
    right_phase: tuple[float, float] | None = None
    right_peak_phase: tuple[float, float] | None = None
    left_pco_mm: int | None = None  # platform centre offset
    right_pco_mm: int | None = None
    # FIT RiderPositionType: 0 seated, 1 standing, 2 / 3 transition to seated / standing
    rider_position: int | None = None

    def any(self) -> bool:
        return any(v is not None for v in vars(self).values())


@dataclass
class DeviceInfo:
    kind: str  # "trainer" | "power_meter" | "heart_rate"
    connected: bool = False
    transport: str | None = None  # "ant" | "ble" | "sim"
    device_number: int | None = None  # ANT+ device number
    ble_id: str | None = None  # BLE address (a UUID on macOS)
    name: str | None = None  # BLE advertised name
    wanted: int | str | None = None  # configured ANT number / BLE id (None = first found)
    last_seen: float = 0.0


@dataclass
class Readings:
    """Snapshot of the freshest values (None = absent or stale)."""

    trainer_power_w: float | None
    trainer_cadence_rpm: float | None
    trainer_speed_ms: float | None
    pm_power_w: float | None
    pm_cadence_rpm: float | None
    heart_rate_bpm: float | None
    trainer_connected: bool
    power_meter_connected: bool
    heart_rate_connected: bool
    pedal: PedalData | None = None  # dual-sided power meter metrics, when any is fresh


MAX_PENDING_RR = 64  # R-R intervals kept when nobody drains them (no ride in progress)


@dataclass
class _Store:
    trainer_power: SensorValue = field(default_factory=SensorValue)
    trainer_cadence: SensorValue = field(default_factory=SensorValue)
    trainer_speed: SensorValue = field(default_factory=SensorValue)
    pm_power: SensorValue = field(default_factory=SensorValue)
    pm_cadence: SensorValue = field(default_factory=SensorValue)
    heart_rate: SensorValue = field(default_factory=SensorValue)
    # pedal metrics, one value per page: balance byte; (left TE, right TE); (left PS, right
    # PS, combined PS); (phase, peak phase) per side; (FIT rider position, left PCO, right PCO)
    pm_balance: SensorValue = field(default_factory=SensorValue)
    pm_te: SensorValue = field(default_factory=SensorValue)
    pm_ps: SensorValue = field(default_factory=SensorValue)
    pm_left_angles: SensorValue = field(default_factory=SensorValue)
    pm_right_angles: SensorValue = field(default_factory=SensorValue)
    pm_position: SensorValue = field(default_factory=SensorValue)
    # beat-to-beat intervals (s) not read yet (drain_rr)
    rr_intervals: list[float] = field(default_factory=list)


ROLES = ("trainer", "power_meter", "heart_rate")


class SensorHub(ABC):
    def __init__(self, shared: SensorHub | None = None) -> None:
        """``shared``: write into another hub's state (lock, values, device info). Used by
        MultiHub so that ANT+ and BLE transports feed one set of readings."""
        if shared is not None:
            self._lock = shared._lock
            self._s = shared._s
            self.devices = shared.devices
        else:
            self._lock = threading.Lock()
            self._s = _Store()
            self.devices = {k: DeviceInfo(k) for k in ROLES}

    # -- lifecycle ----------------------------------------------------------------------
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    # -- trainer control ----------------------------------------------------------------
    @abstractmethod
    def set_target_power(self, watts: float) -> None: ...

    @abstractmethod
    def set_basic_resistance(self, percent: float) -> None: ...

    @abstractmethod
    def set_user_configuration(self, rider_kg: float, bike_kg: float, wheel_d_m: float) -> None: ...

    # -- readings -----------------------------------------------------------------------
    def _seen(
        self,
        kind: str,
        device_number: int | None = None,
        transport: str | None = None,
        ble_id: str | None = None,
        name: str | None = None,
    ) -> None:
        dev = self.devices[kind]
        dev.last_seen = time.monotonic()
        dev.connected = True
        if device_number is not None:
            dev.device_number = device_number
        if transport is not None:
            dev.transport = transport
        if ble_id is not None:
            dev.ble_id = ble_id
        if name is not None:
            dev.name = name

    def readings(self) -> Readings:
        now = time.monotonic()
        with self._lock:
            s = self._s
            for dev in self.devices.values():
                dev.connected = now - dev.last_seen <= STALE_AFTER_S
            return Readings(
                trainer_power_w=s.trainer_power.fresh(now),
                trainer_cadence_rpm=s.trainer_cadence.fresh(now),
                trainer_speed_ms=s.trainer_speed.fresh(now),
                pm_power_w=s.pm_power.fresh(now),
                pm_cadence_rpm=s.pm_cadence.fresh(now),
                heart_rate_bpm=s.heart_rate.fresh(now),
                trainer_connected=self.devices["trainer"].connected,
                power_meter_connected=self.devices["power_meter"].connected,
                heart_rate_connected=self.devices["heart_rate"].connected,
                pedal=self._pedal(now),
            )

    def _pedal(self, now: float) -> PedalData | None:
        s = self._s
        te = s.pm_te.fresh(now) or (None, None)
        ps = s.pm_ps.fresh(now) or (None, None, None)
        la = s.pm_left_angles.fresh(now) or (None, None)
        ra = s.pm_right_angles.fresh(now) or (None, None)
        pos = s.pm_position.fresh(now) or (None, None, None)
        p = PedalData(
            balance=s.pm_balance.fresh(now),
            left_te=te[0],
            right_te=te[1],
            left_ps=ps[0],
            right_ps=ps[1],
            combined_ps=ps[2],
            left_phase=la[0],
            left_peak_phase=la[1],
            right_phase=ra[0],
            right_peak_phase=ra[1],
            rider_position=pos[0],
            left_pco_mm=pos[1],
            right_pco_mm=pos[2],
        )
        return p if p.any() else None

    def add_rr(self, intervals: list[float]) -> None:
        """Queue beat-to-beat intervals (call with ``_lock`` held)."""
        rr = self._s.rr_intervals
        rr.extend(intervals)
        del rr[:-MAX_PENDING_RR]

    def drain_rr(self) -> list[float]:
        """R-R intervals (s) received since the last call, oldest first."""
        with self._lock:
            out = list(self._s.rr_intervals)
            self._s.rr_intervals.clear()
            return out

    def status(self) -> dict:
        self.readings()  # refresh connection flags
        return {
            k: {
                "connected": d.connected,
                "transport": d.transport,
                "device_number": d.device_number,
                "ble_id": d.ble_id,
                "name": d.name,
                "wanted": d.wanted,
            }
            for k, d in self.devices.items()
        }
