"""Simulated sensors for development without hardware.

The simulated trainer follows the ERG target with a first-order lag plus noise; the simulated
power meter reads with a configurable bias, which lets you exercise "power match".
"""

from __future__ import annotations

import math
import random
import threading
import time

from .hub import SensorHub


class SimulatedHub(SensorHub):
    def __init__(
        self,
        with_power_meter: bool = True,
        with_heart_rate: bool = True,
        pm_bias: float = -0.03,  # power meter reads 3 % below the trainer
        rate_hz: float = 4.0,
    ):
        super().__init__()
        self.with_pm = with_power_meter
        self.with_hr = with_heart_rate
        self.pm_bias = pm_bias
        self.dt = 1.0 / rate_hz
        self._target = 0.0
        self._power = 0.0
        self._hr = 90.0
        self._running = False
        self._thread: threading.Thread | None = None
        self.pedaling = True

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

    def _loop(self) -> None:
        t = 0.0
        while self._running:
            t += self.dt
            target = self._target if self.pedaling else 0.0
            self._power += (target - self._power) * (1 - math.exp(-self.dt / 1.5))
            p = max(0.0, self._power + random.gauss(0, 4)) if self.pedaling else 0.0
            cad = 88 + 4 * math.sin(t / 20) + random.gauss(0, 1) if self.pedaling else 0
            hr_eq = 60 + 0.38 * p
            self._hr += (hr_eq - self._hr) * (1 - math.exp(-self.dt / 30))
            with self._lock:
                self._seen("trainer", 12345)
                self._s.trainer_power.set(p)
                self._s.trainer_cadence.set(cad)
                self._s.trainer_speed.set(p / 30)
                if self.with_pm:
                    self._seen("power_meter", 54321)
                    self._s.pm_power.set(max(0.0, p * (1 + self.pm_bias) + random.gauss(0, 3)))
                    self._s.pm_cadence.set(cad)
                if self.with_hr:
                    self._seen("heart_rate", 777)
                    self._s.heart_rate.set(round(self._hr))
            time.sleep(self.dt)
