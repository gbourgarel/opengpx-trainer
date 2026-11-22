"""Calibration of the power source: trainer spin-down (ANT+ FE-C) and power-meter zero offset
(ANT+ Bicycle Power).

Pure state machines fed with decoded pages and the clock; the hub sends the requests they ask
for (``poll``) and feeds them the pages it receives (``on_page``).

Spin-down (FE-C pages 1 and 2): the display sends a calibration request (page 1, spin-down
bit). The trainer answers with "calibration in progress" pages (page 2) carrying the target
speed and whether the current speed is still too low; the rider speeds up past the target,
then stops pedalling and lets the flywheel coast. The trainer measures the spin-down and sends
the result (page 1: success bit, spin-down time, temperature). Seen on the Tacx (2026-11-19):
target 8.888 m/s (32 km/h), page 2 at ~2 Hz from 0.5 s after the request.

Zero offset (Bicycle Power page 1): General Calibration Request (0xAA), answered by 0xAC
(success) or 0xAF (failure) with the calibration data. No load on the pedals meanwhile.
Seen on the Assioma pedals (2026-11-19): answered 4 s after the request, data 0, auto zero not
supported.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from . import profiles as pf

Phase = Literal["requesting", "speed_up", "coast", "zeroing", "done", "failed", "cancelled"]
ACTIVE_PHASES = ("requesting", "speed_up", "coast", "zeroing")


class CalibrationError(Exception):
    """A calibration cannot be started (no such sensor, not supported, one already running)."""


@dataclass
class CalibrationStatus:
    role: str  # "trainer" | "power_meter"
    kind: str  # "spin_down" | "zero_offset"
    phase: Phase
    message: str = ""
    target_speed_kmh: float | None = None
    temperature_c: float | None = None
    spin_down_ms: int | None = None
    zero_offset: int | None = None
    finished_at: float | None = None  # wall clock (s since the epoch)
    # wall clock; tells a client this run from the previous result of the same sensor
    started_at: float = field(default_factory=time.time)

    @property
    def active(self) -> bool:
        return self.phase in ACTIVE_PHASES

    def to_dict(self) -> dict:
        return {**asdict(self), "active": self.active}


class _Calibration:
    REQUEST_EVERY_S = 2.0
    MAX_REQUESTS = 5
    ANSWER_TIMEOUT_S = 10.0  # after the first request, without any answer
    TIMEOUT_S = 120.0  # whole calibration

    def __init__(self, status: CalibrationStatus, now: float):
        self.status = status
        self.started = now
        self.requests = 0
        self.last_request: float | None = None
        self.answered = False

    def _request(self) -> list[int]:
        raise NotImplementedError

    def poll(self, now: float) -> list[int] | None:
        """The request to send now, if any; also ends the calibration on a timeout."""
        if not self.status.active:
            return None
        if now - self.started > self.TIMEOUT_S:
            self._finish("failed", "Timed out: the calibration did not complete.")
            return None
        if self.answered:
            return None
        if now - self.started > self.ANSWER_TIMEOUT_S:
            self._finish("failed", self.NO_ANSWER)
            return None
        due = self.last_request is None or now - self.last_request >= self.REQUEST_EVERY_S
        if due and self.requests < self.MAX_REQUESTS:
            self.requests += 1
            self.last_request = now
            return self._request()
        return None

    def cancel(self) -> None:
        if self.status.active:
            self._finish("cancelled", "Cancelled.")

    def _finish(self, phase: Phase, message: str) -> None:
        self.status.phase = phase
        self.status.message = message
        self.status.finished_at = time.time()


class SpinDown(_Calibration):
    NO_ANSWER = "The trainer does not answer the spin-down request."
    # Once answering, the trainer sends page 2 at ~2 Hz until the result (largest gap seen:
    # 1 s). The Tacx rebooted twice during / right after a spin-down (2026-11-22): silent for
    # 8-32 s, then back with its counters reset, never sending page 2 again.
    SILENT_AFTER_S = 4.0
    LOST = (
        "The trainer stopped sending calibration data (it may have restarted). "
        "Wait a few seconds, then try again."
    )

    def __init__(self, now: float):
        super().__init__(CalibrationStatus("trainer", "spin_down", "requesting"), now)
        self.last_page: float | None = None

    def _request(self) -> list[int]:
        return pf.encode_fec_calibration_request(spin_down=True)

    def poll(self, now: float) -> list[int] | None:
        silent = self.last_page is not None and now - self.last_page > self.SILENT_AFTER_S
        if self.status.active and silent:
            self._finish("failed", self.LOST)
            return None
        return super().poll(now)

    def on_page(self, msg, now: float | None = None) -> None:
        s = self.status
        if not s.active:
            return
        if isinstance(msg, pf.FecCalibrationProgress) and msg.spin_down_pending:
            self.answered = True
            self.last_page = time.monotonic() if now is None else now
            if msg.target_speed_ms is not None:
                s.target_speed_kmh = round(msg.target_speed_ms * 3.6, 1)
            if msg.temperature_c is not None:
                s.temperature_c = msg.temperature_c
            # once the speed was reached the rider coasts: the speed falls below the target
            # again, which is not a reason to ask for more pedalling
            if s.phase != "coast":
                s.phase = "coast" if msg.speed_condition == 2 else "speed_up"
        elif isinstance(msg, pf.FecCalibrationResult):
            self.answered = True
            if msg.temperature_c is not None:
                s.temperature_c = msg.temperature_c
            if msg.spin_down_ok:
                s.spin_down_ms = msg.spin_down_ms
                self._finish("done", "Spin-down done.")
            else:
                self._finish("failed", "The trainer reported a failed spin-down.")


class ZeroOffset(_Calibration):
    NO_ANSWER = "The power meter does not answer the calibration request."
    # answered ~4 s after the request: a second request only if the first one went unanswered
    MAX_REQUESTS = 2
    REQUEST_EVERY_S = 6.0
    ANSWER_TIMEOUT_S = 15.0

    def __init__(self, now: float):
        super().__init__(CalibrationStatus("power_meter", "zero_offset", "zeroing"), now)

    def _request(self) -> list[int]:
        return pf.encode_pm_calibration_request()

    def on_page(self, msg) -> None:
        if not self.status.active or not isinstance(msg, pf.PmCalibrationResult):
            return
        self.answered = True
        self.status.zero_offset = msg.offset
        if msg.ok:
            self._finish("done", "Zero offset done.")
        else:
            self._finish("failed", "The power meter reported a failed calibration.")


def new_calibration(role: str, now: float) -> SpinDown | ZeroOffset:
    if role == "trainer":
        return SpinDown(now)
    if role == "power_meter":
        return ZeroOffset(now)
    raise CalibrationError(f"No calibration for {role}")
