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

    # -- simulation -----------------------------------------------------------------------
    def step(self) -> None:
        """Advance the simulation by one sample (public for tests)."""
        s = self.settings
        self._t += self.dt
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
            self._seen("trainer", 12345)
            self._s.trainer_power.set(p)
            self._s.trainer_cadence.set(cad)
            self._s.trainer_speed.set(p / 30)
            if s.power_meter:
                self._seen("power_meter", 54321)
                self._s.pm_power.set(max(0.0, p * (1 + s.pm_bias) + pm_noise))
                self._s.pm_cadence.set(cad)
            if s.heart_rate:
                self._seen("heart_rate", 777)
                self._s.heart_rate.set(round(self._hr))

    def _loop(self) -> None:
        while self._running:
            self.step()
            time.sleep(self.dt)
