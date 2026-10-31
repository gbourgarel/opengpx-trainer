"""ANT+ device-profile encoding/decoding (pure functions, no hardware).

References: ANT+ Device Profiles "Fitness Equipment" (FE-C, device type 17),
"Heart Rate" (type 120) and "Bicycle Power" (type 11).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# --- channel parameters -------------------------------------------------------------------
RF_FREQ = 57  # 2457 MHz
FEC_DEVICE_TYPE, FEC_PERIOD = 17, 8192
HRM_DEVICE_TYPE, HRM_PERIOD = 120, 8070
PWR_DEVICE_TYPE, PWR_PERIOD = 11, 8182

FE_STATES = {1: "asleep", 2: "ready", 3: "in_use", 4: "finished"}


# --- FE-C decoding -------------------------------------------------------------------------
@dataclass
class FecGeneral:  # page 16 (0x10)
    equipment_type: int
    elapsed_time_s: float  # rolls over every 64 s
    distance_m: int  # rolls over every 256 m
    speed_ms: float
    heart_rate: int | None
    fe_state: str


@dataclass
class FecTrainer:  # page 25 (0x19)
    event_count: int
    cadence_rpm: int | None
    accumulated_power_w: int
    instantaneous_power_w: int | None
    trainer_status: int  # bit0 bike power calibration, bit1 resistance calib, bit2 user config
    target_power_limits: int  # 0 = operating at target, 1 = speed too low, 2 = too high, 3 = n/a
    fe_state: str


@dataclass
class FecCommandStatus:  # page 71 (0x47)
    last_command_page: int
    sequence: int
    status: int  # 0 pass, 1 fail, 2 not supported, 3 rejected, 4 pending, 255 uninitialised


def decode_fec(data: bytes | list[int]):
    d = list(data[:8])
    page = d[0]
    if page == 0x10:
        speed_raw = d[4] | (d[5] << 8)
        return FecGeneral(
            equipment_type=d[1] & 0x1F,
            elapsed_time_s=d[2] * 0.25,
            distance_m=d[3],
            speed_ms=0.0 if speed_raw == 0xFFFF else speed_raw / 1000.0,
            heart_rate=None if d[6] in (0x00, 0xFF) else d[6],
            fe_state=FE_STATES.get((d[7] >> 4) & 0x07, "reserved"),
        )
    if page == 0x19:
        power = d[5] | ((d[6] & 0x0F) << 8)
        return FecTrainer(
            event_count=d[1],
            cadence_rpm=None if d[2] == 0xFF else d[2],
            accumulated_power_w=d[3] | (d[4] << 8),
            instantaneous_power_w=None if power == 0xFFF else power,
            trainer_status=(d[6] >> 4) & 0x0F,
            target_power_limits=d[7] & 0x03,
            fe_state=FE_STATES.get((d[7] >> 4) & 0x07, "reserved"),
        )
    if page == 0x47:
        return FecCommandStatus(last_command_page=d[1], sequence=d[2], status=d[3])
    return None


# --- FE-C commands -------------------------------------------------------------------------
def encode_target_power(watts: float) -> list[int]:
    """Page 49 (0x31): target power in 0.25 W units."""
    raw = int(round(max(0.0, min(watts, 4000.0)) * 4))
    return [0x31, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, raw & 0xFF, (raw >> 8) & 0xFF]


def encode_basic_resistance(percent: float) -> list[int]:
    """Page 48 (0x30): total resistance in 0.5 % units."""
    raw = int(round(max(0.0, min(percent, 100.0)) * 2))
    return [0x30, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, raw]


def encode_track_resistance(grade: float, crr: float | None = None) -> list[int]:
    """Page 51 (0x33): grade (rise/run) in 0.01 % units offset by -200 %, Crr in 5e-5 units."""
    raw = int(round((max(-2.0, min(grade, 2.0)) * 100.0 + 200.0) * 100.0))
    c = 0xFF if crr is None else int(round(max(0.0, min(crr, 0.0127)) / 5e-5))
    return [0x33, 0xFF, 0xFF, 0xFF, 0xFF, raw & 0xFF, (raw >> 8) & 0xFF, c]


def encode_user_configuration(
    user_weight_kg: float,
    bike_weight_kg: float,
    wheel_diameter_m: float = 0.70,
    gear_ratio: float | None = None,
) -> list[int]:
    """Page 55 (0x37)."""
    uw = int(round(max(0.0, min(user_weight_kg, 655.34)) / 0.01))
    bw = int(round(max(0.0, min(bike_weight_kg, 50.0)) / 0.05))
    wd_mm = int(round(wheel_diameter_m * 1000))
    wd_cm, wd_off = divmod(wd_mm, 10)
    wd_cm = min(wd_cm, 254)
    gr = 0x00 if gear_ratio is None else int(round(gear_ratio / 0.03)) & 0xFF
    return [
        0x37,
        uw & 0xFF,
        (uw >> 8) & 0xFF,
        0xFF,
        (wd_off & 0x0F) | ((bw & 0x0F) << 4),
        (bw >> 4) & 0xFF,
        wd_cm,
        gr,
    ]


def encode_request_page(page: int) -> list[int]:
    """Common page 70 (0x46): request a data page (sent 2 times, as broadcast reply)."""
    return [0x46, 0xFF, 0xFF, 0xFF, 0xFF, 0x02, page & 0xFF, 0x01]


# --- Heart rate ----------------------------------------------------------------------------
def decode_hrm(data: bytes | list[int]) -> int | None:
    hr = data[7]
    return None if hr == 0 else int(hr)


# --- Bicycle power -------------------------------------------------------------------------
@dataclass
class PowerOnly:  # page 16 (0x10)
    event_count: int
    pedal_balance: int | None
    cadence_rpm: int | None
    accumulated_power_w: int
    instantaneous_power_w: int


def decode_power(data: bytes | list[int]) -> PowerOnly | None:
    d = list(data[:8])
    if d[0] != 0x10:
        return None  # TODO: crank-torque (0x12) only meters
    return PowerOnly(
        event_count=d[1],
        pedal_balance=None if d[2] == 0xFF else d[2] & 0x7F,
        cadence_rpm=None if d[3] == 0xFF else d[3],
        accumulated_power_w=d[4] | (d[5] << 8),
        instantaneous_power_w=d[6] | (d[7] << 8),
    )


class EventAveragedPower:
    """Average power between broadcast events: d(accumulated)/d(event count).

    Robust to missed messages, which instantaneous power is not.

    When the rider stops pedalling, many sensors stop incrementing the event count (event-
    synchronous power meters, and some FE-C trainers) and just repeat the last message. The
    last average must not be held forever:
    * no new event and instantaneous power == 0  -> 0 W immediately,
    * no new event for more than ``stall_s``      -> 0 W.
    """

    def __init__(self, acc_modulo: int, stall_s: float = 3.0):
        self.mod = acc_modulo
        self.stall_s = stall_s
        self.last: tuple[int, int] | None = None
        self.last_event_at: float = 0.0
        self.value: float | None = None
        self.stalled = False  # no new event for > stall_s: the sensor is repeating itself

    def update(
        self,
        event_count: int,
        accumulated: int,
        instantaneous: float | None,
        now: float | None = None,
    ):
        now = time.monotonic() if now is None else now
        if self.last is None:
            self.last = (event_count, accumulated)
            self.last_event_at = now
            self.value = instantaneous
            self.stalled = False
            return self.value
        dc = (event_count - self.last[0]) % 256
        if dc:
            da = (accumulated - self.last[1]) % self.mod
            self.value = da / dc
            self.last = (event_count, accumulated)
            self.last_event_at = now
            self.stalled = False
        else:
            self.stalled = now - self.last_event_at > self.stall_s
            if instantaneous == 0 or self.stalled:
                self.value = 0.0
        return self.value

    def cadence(self, reported: int | None) -> int | None:
        """Cadence to trust alongside this power: a stalled sensor keeps repeating its last
        cadence (e.g. 61 rpm while the rider is stopped), so report 0 instead."""
        if reported is None:
            return None
        return 0 if self.stalled else reported
