"""Sensor hub abstraction: trainer (FE-C) + optional power meter + optional heart-rate strap."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

STALE_AFTER_S = 3.0


@dataclass
class SensorValue:
    value: float | None = None
    updated: float = 0.0  # time.monotonic()

    def set(self, v: float | None) -> None:
        self.value = v
        self.updated = time.monotonic()

    def fresh(self, now: float | None = None) -> float | None:
        now = time.monotonic() if now is None else now
        return self.value if now - self.updated <= STALE_AFTER_S else None


@dataclass
class DeviceInfo:
    kind: str  # "trainer" | "power_meter" | "heart_rate"
    connected: bool = False
    device_number: int | None = None
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


@dataclass
class _Store:
    trainer_power: SensorValue = field(default_factory=SensorValue)
    trainer_cadence: SensorValue = field(default_factory=SensorValue)
    trainer_speed: SensorValue = field(default_factory=SensorValue)
    pm_power: SensorValue = field(default_factory=SensorValue)
    pm_cadence: SensorValue = field(default_factory=SensorValue)
    heart_rate: SensorValue = field(default_factory=SensorValue)


class SensorHub(ABC):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._s = _Store()
        self.devices = {
            "trainer": DeviceInfo("trainer"),
            "power_meter": DeviceInfo("power_meter"),
            "heart_rate": DeviceInfo("heart_rate"),
        }

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
    def _seen(self, kind: str, device_number: int | None = None) -> None:
        dev = self.devices[kind]
        dev.last_seen = time.monotonic()
        dev.connected = True
        if device_number is not None:
            dev.device_number = device_number

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
            )

    def status(self) -> dict:
        self.readings()  # refresh connection flags
        return {
            k: {"connected": d.connected, "device_number": d.device_number}
            for k, d in self.devices.items()
        }
