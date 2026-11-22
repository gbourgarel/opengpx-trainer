"""ANT+ device-profile encoding/decoding (pure functions, no hardware).

References: ANT+ Device Profiles "Fitness Equipment" (FE-C, device type 17),
"Heart Rate" (type 120) and "Bicycle Power" (type 11).
"""

from __future__ import annotations

import math
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


@dataclass
class FecCalibrationResult:  # page 1 (0x01), trainer -> display
    zero_offset_ok: bool
    spin_down_ok: bool
    temperature_c: float | None
    zero_offset: int | None
    spin_down_ms: int | None


@dataclass
class FecCalibrationProgress:  # page 2 (0x02)
    zero_offset_pending: bool
    spin_down_pending: bool
    temperature_condition: int  # 0 n/a, 1 too low, 2 ok, 3 too high
    speed_condition: int  # 0 n/a, 1 too low, 2 ok
    temperature_c: float | None
    target_speed_ms: float | None
    target_spin_down_ms: int | None


def _fec_temperature(raw: int) -> float | None:
    return None if raw == 0xFF else raw * 0.5 - 25.0


def _u16(lo: int, hi: int) -> int | None:
    v = lo | (hi << 8)
    return None if v == 0xFFFF else v


def decode_fec(data: bytes | list[int]):
    d = list(data[:8])
    page = d[0]
    if page == 0x01:
        return FecCalibrationResult(
            zero_offset_ok=bool(d[1] & 0x40),
            spin_down_ok=bool(d[1] & 0x80),
            temperature_c=_fec_temperature(d[3]),
            zero_offset=_u16(d[4], d[5]),
            spin_down_ms=_u16(d[6], d[7]),
        )
    if page == 0x02:
        speed = _u16(d[4], d[5])
        return FecCalibrationProgress(
            zero_offset_pending=bool(d[1] & 0x40),
            spin_down_pending=bool(d[1] & 0x80),
            temperature_condition=(d[2] >> 4) & 0x03,
            speed_condition=(d[2] >> 6) & 0x03,
            temperature_c=_fec_temperature(d[3]),
            target_speed_ms=None if speed is None else speed / 1000.0,
            target_spin_down_ms=_u16(d[6], d[7]),
        )
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


def encode_fec_calibration_request(spin_down: bool = True, zero_offset: bool = False) -> list[int]:
    """Page 1 (0x01) from the display: start a spin-down and / or a zero-offset calibration."""
    mode = (0x80 if spin_down else 0) | (0x40 if zero_offset else 0)
    return [0x01, mode, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]


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


def encode_request_page(page: int, descriptor: int = 0xFF) -> list[int]:
    """Common page 70 (0x46): request a data page (sent 2 times, as broadcast reply).
    ``descriptor`` (byte 3) selects a subpage, e.g. 0xFE for the power meter's Advanced
    Capabilities 2 (Get/Set Parameters page 0x02)."""
    return [0x46, 0xFF, 0xFF, descriptor & 0xFF, 0xFF, 0x02, page & 0xFF, 0x01]


# --- identity of a sensor (common pages, HRM background pages) ----------------------------
@dataclass
class SensorIdentity:
    """Who a sensor is, as it broadcasts it (for the FIT ``device_info``); None = not heard
    yet. Each page carries a few fields; they come every ~30 s at most."""

    manufacturer: int | None = None  # FIT / ANT+ manufacturer id (89 Tacx, 263 Favero, ...)
    product: int | None = None  # model number
    serial_number: int | None = None
    hardware_version: int | None = None
    software_version: float | None = None
    battery_voltage: float | None = None
    battery_status: int | None = None  # FIT battery_status: 1 new ... 5 critical

    def merge(self, part: SensorIdentity) -> None:
        """Take the fields ``part`` (one decoded page) carries."""
        for k, v in vars(part).items():
            if v is not None:
                setattr(self, k, v)


def _software_version(main: int, supplemental: int) -> float | None:
    """ANT+ software revision: main / 10, or (main x 100 + supplemental) / 1000 when the
    supplemental byte is used (Tacx: 40 / 3 -> 4.003; Favero: 62 / 40 -> 6.24)."""
    if main == 0xFF:
        return None
    if supplemental == 0xFF:
        return main / 10
    return (main * 100 + supplemental) / 1000


def _battery(fraction: int, bits: int) -> SensorIdentity:
    coarse, status = bits & 0x0F, (bits >> 4) & 0x07
    return SensorIdentity(
        battery_voltage=None if coarse == 0x0F else round(coarse + fraction / 256, 2),
        battery_status=status if 1 <= status <= 5 else None,
    )


def decode_common(data: bytes | list[int]) -> SensorIdentity | None:
    """Common pages 80-82, broadcast by every ANT+ sensor (FE-C and power meter here)."""
    d = list(data[:8])
    if d[0] == 0x50:
        return SensorIdentity(
            hardware_version=None if d[3] == 0xFF else d[3],
            manufacturer=_u16(d[4], d[5]),
            product=_u16(d[6], d[7]),
        )
    if d[0] == 0x51:
        serial = d[4] | (d[5] << 8) | (d[6] << 16) | (d[7] << 24)
        return SensorIdentity(
            software_version=_software_version(d[3], d[2]),
            serial_number=None if serial == 0xFFFFFFFF else serial,
        )
    if d[0] == 0x52:
        return _battery(d[6], d[7])
    return None


def decode_hrm_info(data: bytes | list[int], device_number: int | None) -> SensorIdentity | None:
    """Heart-rate background pages (page number in bits 0-6, bit 7 is a toggle): 2 =
    manufacturer and the upper 16 bits of the serial (the lower ones are the device number),
    3 = hardware / software version and model, 7 = battery."""
    d = list(data[:8])
    page = d[0] & 0x7F
    if page == 2:
        upper = d[2] | (d[3] << 8)
        serial = None if device_number is None else (upper << 16) | device_number
        return SensorIdentity(manufacturer=d[1], serial_number=serial)
    if page == 3:
        return SensorIdentity(hardware_version=d[1], software_version=float(d[2]), product=d[3])
    if page == 7:
        return _battery(d[2], d[3])
    return None


# --- Heart rate ----------------------------------------------------------------------------
def decode_hrm(data: bytes | list[int]) -> int | None:
    hr = data[7]
    return None if hr == 0 else int(hr)


class RRIntervals:
    """Beat-to-beat (R-R) intervals from the heart-rate pages (ANT+ Heart Rate profile).

    Every page carries the time of the last beat (bytes 4-5, 1/1024 s, rolls over at 64 s)
    and a beat count (byte 6). Page 4 also carries the time of the previous beat (bytes 2-3).
    When the count goes up by exactly one, the interval is the difference of the two last-beat
    times; when beats were missed, only page 4 still gives the last interval. Implausible
    intervals (outside 0.2-3 s, i.e. 20-300 bpm) are dropped.
    """

    MIN_S, MAX_S = 0.2, 3.0

    def __init__(self) -> None:
        self.last: tuple[int, int] | None = None  # (beat count, last beat time)

    def update(self, data: bytes | list[int]) -> list[float]:
        d = list(data[:8])
        page = d[0] & 0x7F  # bit 7 is the page-change toggle
        t, n = d[4] | (d[5] << 8), d[6]
        prev, self.last = self.last, (n, t)
        if prev is None or (n - prev[0]) % 256 == 0:
            return []
        if (n - prev[0]) % 256 == 1:
            rr = ((t - prev[1]) % 65536) / 1024.0
        elif page == 4:
            rr = ((t - (d[2] | (d[3] << 8))) % 65536) / 1024.0
        else:
            return []  # beats missed: interval unknown
        return [rr] if self.MIN_S <= rr <= self.MAX_S else []


# --- Bicycle power -------------------------------------------------------------------------
@dataclass
class PowerOnly:  # page 16 (0x10)
    event_count: int
    # byte 2 as sent (None if 0xFF): bit 7 set = bits 0-6 are the *right* pedal's share (%),
    # else the share of an unknown pedal. Same encoding as the FIT left_right_balance field.
    pedal_balance: int | None
    cadence_rpm: int | None
    accumulated_power_w: int
    instantaneous_power_w: int


def _half_pct(b: int) -> float | None:
    return None if b == 0xFF else b / 2.0


@dataclass
class PedalEfficiency:  # page 19 (0x13): torque effectiveness and pedal smoothness, %
    event_count: int
    left_te: float | None
    right_te: float | None
    left_ps: float | None  # None when combined
    right_ps: float | None
    combined_ps: float | None  # sensors that cannot tell the legs apart (byte 5 = 0xFE)


def brads_to_deg(b: int) -> float:
    """Crank angle: 256 binary radians per turn, 0 at the top, clockwise (seen from the right)."""
    return b * 360.0 / 256.0


@dataclass
class ForceAngle:  # pages 0xE0 (right) / 0xE1 (left): power phase, Cycling Dynamics
    side: str  # "left" | "right"
    event_count: int
    phase_deg: tuple[float, float] | None  # (start, end) of positive torque
    peak_phase_deg: tuple[float, float] | None  # (start, end) of peak torque
    torque_nm: float  # mean torque over the event interval


@dataclass
class PedalPosition:  # page 0xE2: rider position and platform centre offset
    event_count: int
    rider_position: int  # ANT: 0 seated, 1 transition to seated, 2 standing, 3 to standing
    cadence_rpm: int | None
    right_pco_mm: int | None
    left_pco_mm: int | None


@dataclass
class AdvancedCapabilities2:  # page 0x02, subpage 0xFE (from the sensor)
    mask: int  # bit = 0: capability supported
    value: int  # bit = 0: capability enabled (4 Hz / 8 Hz bits: transmitting at that rate)


# Advanced Capabilities 2 bits (Bicycle Power profile rev 5.1, tables 15-14 and 15-15)
CAP_8HZ, CAP_POWER_PHASE, CAP_PCO, CAP_RIDER_POSITION = 1, 3, 4, 5
CYCLING_DYNAMICS = (CAP_POWER_PHASE, CAP_PCO, CAP_RIDER_POSITION)


def _angles(a: int, b: int) -> tuple[float, float] | None:
    return None if a == 0xC0 and b == 0xC0 else (brads_to_deg(a), brads_to_deg(b))


def _pco(b: int) -> int | None:
    v = b - 256 if b > 127 else b
    return None if v == -128 else v


def decode_power_extra(
    data: bytes | list[int],
) -> (
    PedalEfficiency
    | ForceAngle
    | PedalPosition
    | AdvancedCapabilities2
    | PmCalibrationResult
    | None
):
    """Pages of a dual-sided power meter beyond power and cadence (see decode_power)."""
    d = list(data[:8])
    page = d[0]
    if page == 0x13:
        combined = d[5] == 0xFE
        return PedalEfficiency(
            event_count=d[1],
            left_te=_half_pct(d[2]),
            right_te=_half_pct(d[3]),
            left_ps=None if combined else _half_pct(d[4]),
            right_ps=None if combined else _half_pct(d[5]),
            combined_ps=_half_pct(d[4]) if combined else None,
        )
    if page in (0xE0, 0xE1):
        return ForceAngle(
            side="right" if page == 0xE0 else "left",
            event_count=d[1],
            phase_deg=_angles(d[2], d[3]),
            peak_phase_deg=_angles(d[4], d[5]),
            torque_nm=(d[6] | (d[7] << 8)) / 32.0,
        )
    if page == 0xE2:
        return PedalPosition(
            event_count=d[1],
            rider_position=(d[2] >> 6) & 0x03,
            cadence_rpm=None if d[3] == 0xFF else d[3],
            right_pco_mm=_pco(d[4]),
            left_pco_mm=_pco(d[5]),
        )
    if page == 0x02 and d[1] == 0xFE:
        return AdvancedCapabilities2(mask=d[4], value=d[6])
    if page == 0x01 and d[1] in (PM_CALIBRATION_OK, PM_CALIBRATION_FAILED):
        raw = d[6] | (d[7] << 8)
        return PmCalibrationResult(
            ok=d[1] == PM_CALIBRATION_OK,
            auto_zero=None if d[2] == 0xFF else bool(d[2]),
            offset=raw - 0x10000 if raw >= 0x8000 else raw,
        )
    return None


# Bicycle Power page 1 calibration IDs: general calibration request / response
PM_CALIBRATION_REQUEST = 0xAA
PM_CALIBRATION_OK = 0xAC
PM_CALIBRATION_FAILED = 0xAF


@dataclass
class PmCalibrationResult:  # page 1 (0x01), calibration ID 0xAC / 0xAF
    ok: bool
    auto_zero: bool | None  # auto zero on / off; None = not supported
    offset: int  # calibration data (signed), meaning set by the manufacturer


def encode_pm_calibration_request() -> list[int]:
    """Page 1, General Calibration Request (0xAA): zero offset of a power meter."""
    return [0x01, PM_CALIBRATION_REQUEST, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]


# ANT+ rider position -> FIT RiderPositionType (0 seated, 1 standing, 2 / 3 transitions)
ANT_TO_FIT_RIDER_POSITION = {0: 0, 1: 2, 2: 1, 3: 3}


def encode_enable_cycling_dynamics(caps: AdvancedCapabilities2) -> list[int] | None:
    """Set Advanced Capabilities 2 (from the display): 8 Hz transmission plus every Cycling
    Dynamics element the sensor supports. None when it supports none (or no 8 Hz).

    From the display, a mask bit at 0 means "apply this bit of the value"; a value bit at 0
    enables the capability (or transmits at that rate). Reserved bits 2 and 7 are set to 1."""
    supported = [b for b in CYCLING_DYNAMICS if not caps.mask >> b & 1]
    if caps.mask >> CAP_8HZ & 1 or not supported:
        return None
    mask = 0xFF
    for b in (CAP_8HZ, *supported):
        mask &= ~(1 << b)
    return [0x02, 0xFE, 0xFF, 0xFF, mask, 0xFF, mask, 0xFF]  # value: same bits cleared


def cycling_dynamics_enabled(caps: AdvancedCapabilities2) -> bool:
    """True when the sensor transmits at 8 Hz with every supported Cycling Dynamics element."""
    if caps.value >> CAP_8HZ & 1:
        return False
    return all(caps.value >> b & 1 == 0 for b in CYCLING_DYNAMICS if not caps.mask >> b & 1)


class CyclingDynamicsEnabler:
    """Turns Cycling Dynamics on in a power meter (Bicycle Power profile §4.5.2): request its
    Advanced Capabilities 2, then set 8 Hz + the supported elements, and check again.

    Pure state machine: feed it the pages received (``on_page``) and call ``poll``
    regularly; both return the commands to send (acknowledged) to the power meter. The
    receiving channel stays at 4 Hz: the sensor interleaves the dynamics pages so that a 4 Hz
    receiver gets them (§15.2.5.1.2). A meter that never answers is left alone after
    ``max_requests``; one already sending dynamics pages (e.g. enabled by a head unit) needs
    nothing.
    """

    RETRY_S = 3.0

    def __init__(self, max_requests: int = 5, max_sets: int = 3):
        self.max_requests = max_requests
        self.max_sets = max_sets
        self.state = "unknown"  # unknown | enabled | unsupported
        self.requests = 0
        self.sets = 0
        self._next_request = 0.0
        # Some meters send 0 mm in the PCO bytes without supporting PCO (Assioma: mask bit 4
        # set): trust PCO only when the capabilities say so.
        self.pco_supported = False

    def reset(self) -> None:
        """The meter was lost (asleep, battery): it may have forgotten its configuration."""
        self.state, self.requests, self.sets, self._next_request = "unknown", 0, 0, 0.0

    def on_page(self, msg, now: float) -> list[list[int]]:
        if isinstance(msg, AdvancedCapabilities2):
            self.pco_supported = not msg.mask >> CAP_PCO & 1
        if isinstance(msg, ForceAngle | PedalPosition):
            self.state = "enabled"
        elif isinstance(msg, AdvancedCapabilities2) and self.state == "unknown":
            if cycling_dynamics_enabled(msg):
                self.state = "enabled"
                return []
            cmd = encode_enable_cycling_dynamics(msg)
            if cmd is None or self.sets >= self.max_sets:
                self.state = "unsupported"
                return []
            self.sets += 1
            self._next_request = now + self.RETRY_S  # then check it was applied
            return [cmd]
        return []

    def poll(self, now: float) -> list[list[int]]:
        if self.state != "unknown" or now < self._next_request:
            return []
        if self.requests >= self.max_requests:
            self.state = "unsupported"
            return []
        self.requests += 1
        self._next_request = now + self.RETRY_S
        return [encode_request_page(0x02, descriptor=0xFE)]


@dataclass
class CrankTorque:  # page 18 (0x12), standard crank torque
    event_count: int  # one event per crank revolution
    crank_ticks: int
    cadence_rpm: int | None  # instantaneous, from the sensor
    accumulated_period: int  # 1/2048 s, rolls over at 65536
    accumulated_torque: int  # 1/32 N·m, rolls over at 65536


def decode_power(data: bytes | list[int]) -> PowerOnly | CrankTorque | None:
    """Power and cadence pages (16 and 18); other pages: decode_power_extra."""
    d = list(data[:8])
    if d[0] == 0x12:
        return CrankTorque(
            event_count=d[1],
            crank_ticks=d[2],
            cadence_rpm=None if d[3] == 0xFF else d[3],
            accumulated_period=d[4] | (d[5] << 8),
            accumulated_torque=d[6] | (d[7] << 8),
        )
    if d[0] != 0x10:
        return None
    return PowerOnly(
        event_count=d[1],
        pedal_balance=None if d[2] == 0xFF else d[2],
        cadence_rpm=None if d[3] == 0xFF else d[3],
        accumulated_power_w=d[4] | (d[5] << 8),
        instantaneous_power_w=d[6] | (d[7] << 8),
    )


class CrankTorquePower:
    """Power and cadence from crank-torque pages (ANT+ Bicycle Power, page 0x12).

    Between two events (one per crank revolution):
        angular velocity  w = 2*pi * d_events / (d_period / 2048)      [rad/s]
        mean torque       T = d_torque / (32 * d_events)               [N*m]
        power             P = T * w = 128 * pi * d_torque / d_period   [W]
        cadence             = 60 * 2048 * d_events / d_period          [rpm]
    The sensor repeats its last page while the crank is not turning: after ``stall_s``
    without a new event, power and cadence are 0.
    """

    def __init__(self, stall_s: float = 3.0):
        self.stall_s = stall_s
        self.last: CrankTorque | None = None
        self.last_event_at = 0.0
        self.power_w: float | None = None
        self.cadence_rpm: float | None = None

    def update(self, m: CrankTorque, now: float | None = None) -> tuple[float | None, float | None]:
        now = time.monotonic() if now is None else now
        prev = self.last
        if prev is None:
            self.last, self.last_event_at = m, now
            return self.power_w, self.cadence_rpm
        d_ev = (m.event_count - prev.event_count) % 256
        if d_ev:
            d_period = (m.accumulated_period - prev.accumulated_period) % 65536
            d_torque = (m.accumulated_torque - prev.accumulated_torque) % 65536
            if d_period:
                self.power_w = 128 * math.pi * d_torque / d_period
                self.cadence_rpm = 60 * 2048 * d_ev / d_period
            self.last, self.last_event_at = m, now
        elif now - self.last_event_at > self.stall_s:
            self.power_w, self.cadence_rpm = 0.0, 0.0
        return self.power_w, self.cadence_rpm


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
