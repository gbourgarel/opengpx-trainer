"""Simulated sensors for development without hardware.

Two rider models:

* ``follow`` (default): the trainer behaves like a real ERG trainer. Power follows the target
  with a first-order lag (tau 1.5 s) plus noise.
* ``manual``: the rider produces exactly ``manual_power_w`` (plus optional noise), whatever the
  target. Use this to probe the speed model in GPX mode, or to see what ERG does when you fight it.

The simulated power meter reads ``trainer x (1 + pm_bias)``, which exercises power match. It can be
switched off live to test the "auto" power-source fallback to the trainer.
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import asdict, dataclass, fields
from typing import Literal

from . import profiles as pf
from .calibration import CalibrationError
from .hub import SensorHub


@dataclass
class SimSettings:
    mode: Literal["follow", "manual"] = "follow"
    manual_power_w: float = 200.0
    cadence_rpm: float = 90.0
    pedaling: bool = True
    noise: bool = True
    power_meter: bool = True  # simulated power meter present
    heart_rate: bool = True  # simulated HR strap present
    pm_bias: float = -0.03  # power meter reads 3 % below the trainer


class SimulatedHub(SensorHub):
    def __init__(self, settings: SimSettings | None = None, rate_hz: float = 4.0):
        super().__init__()
        self.settings = settings or SimSettings()
        self.dt = 1.0 / rate_hz
        self._target = 0.0
        self._power = 0.0
        self._hr = 90.0
        self._t = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._cal_speed = 0.0  # fake calibration state (see _calibration_step)
        self._cal_coast_t: float | None = None
        self._cal_pm_due: float | None = None

    # -- control --------------------------------------------------------------------------
    def update_settings(self, **changes) -> SimSettings:
        names = {f.name for f in fields(SimSettings)}
        unknown = set(changes) - names
        if unknown:
            raise ValueError(f"Unknown simulator settings: {sorted(unknown)}")
        merged = {**asdict(self.settings), **{k: v for k, v in changes.items() if v is not None}}
        if merged["mode"] not in ("follow", "manual"):
            raise ValueError("mode must be 'follow' or 'manual'")
        merged["manual_power_w"] = max(0.0, min(float(merged["manual_power_w"]), 2000.0))
        merged["cadence_rpm"] = max(0.0, min(float(merged["cadence_rpm"]), 200.0))
        merged["pm_bias"] = max(-0.5, min(float(merged["pm_bias"]), 0.5))
        self.settings = SimSettings(**merged)
        return self.settings

    # -- SensorHub ------------------------------------------------------------------------
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="sim-hub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def set_target_power(self, watts: float) -> None:
        self._target = watts

    def set_basic_resistance(self, percent: float) -> None:
        self._target = 120 + percent  # crude: rider "free rides" around 120-200 W

    def set_user_configuration(self, rider_kg: float, bike_kg: float, wheel_d_m: float) -> None:
        pass

    # -- calibration (fake, to try the dialogs) --------------------------------------------
    # Spin-down: the flywheel speeds up while pedalling (ERG off) and coasts down otherwise;
    # the speed must pass 32 km/h, then the rider stops and the result comes once it is below
    # 1 m/s. Zero offset: answered 1 s after the request, failed if the rider pedals.
    SIM_SPIN_DOWN_TARGET_MS = 8.888

    def _check_calibration(self, role: str) -> None:
        if role == "power_meter" and not self.settings.power_meter:
            raise CalibrationError("No simulated power meter")

    def _calibration_step(self) -> bool:
        """Advance a fake calibration by one sample; True while a spin-down drives the trainer."""
        polled = self._calibration_poll(time.monotonic())
        if polled is not None:
            role = polled[0]
            if role == "trainer":
                self._cal_speed = self._s.trainer_speed.fresh() or 0.0
                self._cal_coast_t = None
            else:
                self._cal_pm_due = self._t + 1.0
        if self._cal_pm_due is not None and self._t >= self._cal_pm_due:
            self._cal_pm_due = None
            ok = not self.settings.pedaling
            self._calibration_page("power_meter", pf.PmCalibrationResult(ok, None, 12 if ok else 0))
        if not self.calibrating("trainer"):
            return False
        target = self.SIM_SPIN_DOWN_TARGET_MS
        pedaling = self.settings.pedaling
        if self._cal_coast_t is None and not pedaling and self._cal_speed >= target:
            self._cal_coast_t = self._t  # stopped above the target speed: measuring
        if pedaling and self._cal_coast_t is None:
            self._cal_speed = min(self._cal_speed + 1.2 * self.dt, 12.0)
        else:  # coasting (or stopped too early: still too slow, keep asking for speed)
            self._cal_speed = max(self._cal_speed - 0.9 * self.dt, 0.0)
        page: object
        if self._cal_coast_t is not None and self._cal_speed < 1.0:
            ms = round((self._t - self._cal_coast_t) * 1000)
            page = pf.FecCalibrationResult(False, True, 21.0, None, ms)
        else:
            reached = self._cal_speed >= target or self._cal_coast_t is not None
            page = pf.FecCalibrationProgress(
                False, True, 2, 2 if reached else 1, 21.0, target, None
            )
        self._calibration_page("trainer", page)
        cadence = self.settings.cadence_rpm if self.settings.pedaling else 0.0
        with self._lock:
            self._seen("trainer", 12345, transport="sim")
            self._s.trainer_speed.set(self._cal_speed)
            self._s.trainer_power.set(0.0)
            self._s.trainer_cadence.set(cadence)
            if self.settings.power_meter:  # still broadcasting (no load: ERG is off)
                self._seen("power_meter", 54321, transport="sim")
                self._s.pm_power.set(0.0)
                self._s.pm_cadence.set(cadence)
            if self.settings.heart_rate:
                self._seen("heart_rate", 777, transport="sim")
                self._s.heart_rate.set(round(self._hr))
        return True

    # -- simulation -----------------------------------------------------------------------
    def step(self) -> None:
        """Advance the simulation by one sample (public for tests)."""
        s = self.settings
        self._t += self.dt
        if self._calibration_step():
            return
        if not s.pedaling:
            goal = 0.0
        elif s.mode == "manual":
            goal = s.manual_power_w
        else:
            goal = self._target
        if s.mode == "manual" or not s.pedaling:
            self._power = goal  # the rider sets power directly
        else:
            self._power += (goal - self._power) * (1 - math.exp(-self.dt / 1.5))
        noise = random.gauss(0, 4) if (s.noise and s.pedaling) else 0.0
        p = max(0.0, self._power + noise) if s.pedaling else 0.0
        cad = 0.0
        if s.pedaling:
            cad = s.cadence_rpm + (
                4 * math.sin(self._t / 20) + random.gauss(0, 1) if s.noise else 0
            )
        self._hr += (60 + 0.38 * p - self._hr) * (1 - math.exp(-self.dt / 30))
        pm_noise = random.gauss(0, 3) if (s.noise and s.pedaling) else 0.0
        with self._lock:
            self._seen("trainer", 12345, transport="sim")
            self._s.trainer_power.set(p)
            self._s.trainer_cadence.set(cad)
            self._s.trainer_speed.set(p / 30)
            if s.power_meter:
                self._seen("power_meter", 54321, transport="sim")
                self._s.pm_power.set(max(0.0, p * (1 + s.pm_bias) + pm_noise))
                self._s.pm_cadence.set(cad)
            if s.heart_rate:
                self._seen("heart_rate", 777, transport="sim")
                self._s.heart_rate.set(round(self._hr))

    def _loop(self) -> None:
        while self._running:
            self.step()
            time.sleep(self.dt)
