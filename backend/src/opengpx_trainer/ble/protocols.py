"""Bluetooth LE GATT profiles used by the app (pure functions, no hardware).

* Heart Rate Service (0x180D): Heart Rate Measurement (0x2A37), with R-R intervals.
* Cycling Power Service (0x1818): Cycling Power Measurement (0x2A63), with L/R balance.
* Fitness Machine Service, FTMS (0x1826): Indoor Bike Data (0x2AD2), the Fitness Machine
  Control Point (0x2AD9), used for ERG (target power) and simulation control, and the
  Supported Power Range (0x2AD8), which bounds the targets sent.
* Battery Service (0x180F): Battery Level (0x2A19), in %, on any of the devices.

All multi-byte fields are little-endian.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass


def uuid16(short: int) -> str:
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


# services
HEART_RATE_SERVICE = uuid16(0x180D)
CYCLING_POWER_SERVICE = uuid16(0x1818)
FTMS_SERVICE = uuid16(0x1826)
# characteristics
HEART_RATE_MEASUREMENT = uuid16(0x2A37)
CYCLING_POWER_MEASUREMENT = uuid16(0x2A63)
INDOOR_BIKE_DATA = uuid16(0x2AD2)
FTMS_CONTROL_POINT = uuid16(0x2AD9)
SUPPORTED_POWER_RANGE = uuid16(0x2AD8)
BATTERY_LEVEL = uuid16(0x2A19)

# which role(s) a device can fill, from the services it advertises
SERVICE_ROLES = {
    FTMS_SERVICE: "trainer",
    CYCLING_POWER_SERVICE: "power_meter",
    HEART_RATE_SERVICE: "heart_rate",
}


# --- Heart rate ----------------------------------------------------------------------------
def parse_heart_rate(data: bytes) -> int | None:
    if len(data) < 2:
        return None
    flags = data[0]
    if flags & 0x01:  # 16-bit value
        if len(data) < 3:
            return None
        hr = data[1] | (data[2] << 8)
    else:
        hr = data[1]
    return hr or None


def parse_rr_intervals(data: bytes) -> list[float]:
    """Beat-to-beat (R-R) intervals of a Heart Rate Measurement, in s (flag bit 4: present,
    after the HR value and, flag bit 3, the energy expended); implausible ones (outside
    0.2-3 s) dropped, as over ANT+."""
    if len(data) < 2 or not data[0] & 0x10:
        return []
    off = 3 if data[0] & 0x01 else 2
    if data[0] & 0x08:
        off += 2
    out = []
    while off + 2 <= len(data):
        rr = struct.unpack_from("<H", data, off)[0] / 1024.0
        if 0.2 <= rr <= 3.0:
            out.append(rr)
        off += 2
    return out


# --- Cycling power -------------------------------------------------------------------------
@dataclass
class CyclingPower:
    power_w: int
    crank_revs: int | None = None  # cumulative, rolls over at 65536
    crank_event_time: int | None = None  # 1/1024 s, rolls over at 65536
    # FIT left_right_balance byte, as over ANT+: bit 7 set = bits 0-6 are the right's share
    balance: int | None = None


def _balance(raw: int, left_reference: bool) -> int | None:
    """Pedal Power Balance (1/2 %): the left leg's share when the reference bit says so, else
    of an unknown side (FIT: bit 7 clear)."""
    if raw == 0xFF:
        return None
    pct = round(raw / 2)
    if not 0 <= pct <= 100:
        return None
    return 0x80 | (100 - pct) if left_reference else pct


def parse_cycling_power(data: bytes) -> CyclingPower | None:
    if len(data) < 4:
        return None
    flags, power = struct.unpack_from("<Hh", data, 0)
    off = 4
    balance = None
    if flags & 0x0001 and len(data) >= off + 1:  # pedal power balance
        balance = _balance(data[off], bool(flags & 0x0002))
        off += 1
    if flags & 0x0004:  # accumulated torque
        off += 2
    if flags & 0x0010:  # wheel revolution data
        off += 6
    revs = evt = None
    if flags & 0x0020 and len(data) >= off + 4:  # crank revolution data
        revs, evt = struct.unpack_from("<HH", data, off)
    return CyclingPower(max(0, power), revs, evt, balance)


class CrankCadence:
    """Cadence from cumulative crank revolutions and the last crank event time.

    The sensor repeats the same values while the crank is not turning; after ``stall_s``
    without a new crank event the cadence (and the power, see ``stalled``) is 0.
    """

    def __init__(self, stall_s: float = 3.0):
        self.stall_s = stall_s
        self.last: tuple[int, int] | None = None
        self.last_change_at = 0.0
        self.cadence: float | None = None

    def update(self, revs: int, event_time: int, now: float | None = None) -> float | None:
        now = time.monotonic() if now is None else now
        if self.last is None:
            self.last = (revs, event_time)
            self.last_change_at = now
            return self.cadence
        d_revs = (revs - self.last[0]) % 65536
        d_t = (event_time - self.last[1]) % 65536
        if d_revs and d_t:
            self.cadence = d_revs / (d_t / 1024.0) * 60.0
            self.last = (revs, event_time)
            self.last_change_at = now
        elif now - self.last_change_at > self.stall_s:
            self.cadence = 0.0
        return self.cadence

    def stalled(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.last is not None and now - self.last_change_at > self.stall_s


# --- Battery -------------------------------------------------------------------------------
def parse_battery_level(data: bytes) -> int | None:
    """Battery Level: one uint8, 0-100 %; anything else is not a level."""
    return data[0] if len(data) >= 1 and data[0] <= 100 else None


# --- FTMS: indoor bike data ----------------------------------------------------------------
@dataclass
class IndoorBikeData:
    speed_kmh: float | None = None
    cadence_rpm: float | None = None
    power_w: int | None = None
    heart_rate: int | None = None


def parse_indoor_bike_data(data: bytes) -> IndoorBikeData | None:
    if len(data) < 2:
        return None
    flags = struct.unpack_from("<H", data, 0)[0]
    off = 2
    out = IndoorBikeData()

    def take(fmt: str):
        nonlocal off
        size = struct.calcsize(fmt)
        if len(data) < off + size:
            raise ValueError("truncated")
        v = struct.unpack_from(fmt, data, off)[0]
        off += size
        return v

    try:
        if not flags & 0x0001:  # "More Data" clear => instantaneous speed present
            out.speed_kmh = take("<H") * 0.01
        if flags & 0x0002:  # average speed
            take("<H")
        if flags & 0x0004:  # instantaneous cadence, 0.5 rpm
            out.cadence_rpm = take("<H") * 0.5
        if flags & 0x0008:  # average cadence
            take("<H")
        if flags & 0x0010:  # total distance, uint24
            off += 3
        if flags & 0x0020:  # resistance level
            take("<h")
        if flags & 0x0040:  # instantaneous power
            out.power_w = max(0, take("<h"))
        if flags & 0x0080:  # average power
            take("<h")
        if flags & 0x0100:  # expended energy: total, per hour, per minute
            off += 5
        if flags & 0x0200:  # heart rate
            out.heart_rate = take("<B") or None
    except ValueError:
        pass  # keep the fields decoded so far
    return out


# --- FTMS: control point -------------------------------------------------------------------
REQUEST_CONTROL = 0x00
RESET = 0x01
SET_TARGET_POWER = 0x05
START_OR_RESUME = 0x07
SET_SIMULATION = 0x11
RESPONSE_CODE = 0x80
RESULTS = {
    0x01: "success",
    0x02: "not supported",
    0x03: "invalid parameter",
    0x04: "operation failed",
    0x05: "control not permitted",
}


def ftms_request_control() -> bytes:
    return bytes([REQUEST_CONTROL])


def ftms_start() -> bytes:
    return bytes([START_OR_RESUME])


@dataclass(frozen=True)
class PowerRange:
    """FTMS Supported Power Range: the targets the trainer accepts."""

    min_w: int
    max_w: int
    increment_w: int

    def clamp(self, watts: float) -> float:
        return max(float(self.min_w), min(watts, float(self.max_w)))


def parse_supported_power_range(data: bytes) -> PowerRange | None:
    if len(data) < 6:
        return None
    lo, hi, inc = struct.unpack_from("<hhH", data, 0)
    return PowerRange(lo, hi, inc) if 0 <= lo < hi else None


def ftms_set_target_power(watts: float) -> bytes:
    w = int(round(max(0.0, min(watts, 4000.0))))
    return struct.pack("<Bh", SET_TARGET_POWER, w)


def ftms_set_simulation(
    grade: float, crr: float = 0.004, cw_kg_m: float = 0.51, wind_ms: float = 0.0
) -> bytes:
    """Indoor bike simulation: grade (rise/run), Crr, wind resistance coefficient (0.5·ρ·CdA)."""
    return struct.pack(
        "<BhhBB",
        SET_SIMULATION,
        int(round(max(-32.767, min(wind_ms, 32.767)) * 1000)),
        int(round(max(-0.4, min(grade, 0.4)) * 10000)),  # 0.01 % units
        int(round(max(0.0, min(crr, 0.0255)) * 10000)),
        int(round(max(0.0, min(cw_kg_m, 2.55)) * 100)),
    )


def parse_control_point_response(data: bytes) -> tuple[int, str] | None:
    """(request opcode, result) for a control point indication, else None."""
    if len(data) < 3 or data[0] != RESPONSE_CODE:
        return None
    return data[1], RESULTS.get(data[2], f"code {data[2]}")
