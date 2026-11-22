"""Real sensors: each role (trainer, power meter, heart rate) on ANT+ or Bluetooth LE.

MultiHub owns the shared readings; an AntHub and/or a BleHub write into them, each for the
roles configured on its transport. Trainer commands go to the transport that owns the trainer.
"""

from __future__ import annotations

import logging

from .ant.calibration import CalibrationError, CalibrationStatus
from .ant.hub import ROLES, SensorHub
from .profile import Profile

log = logging.getLogger(__name__)


class MultiHub(SensorHub):
    def __init__(self, profile: Profile):
        super().__init__()
        p = profile
        self.transport = {r: getattr(p, f"{r}_transport") for r in ROLES}
        ant_roles = {r for r in ROLES if self.transport[r] == "ant"}
        ble_roles: dict[str, tuple[str, str | None]] = {}
        self.warnings: list[str] = []
        for r in ROLES:
            if self.transport[r] != "ble":
                continue
            ble_id = getattr(p, f"{r}_ble_id")
            if ble_id:
                ble_roles[r] = (ble_id, getattr(p, f"{r}_ble_name"))
            else:
                self.warnings.append(f"{r.replace('_', ' ')}: no Bluetooth device chosen (scan)")
        self.ant = None
        if ant_roles:
            from .ant.ant_hub import AntHub

            self.ant = AntHub(
                use_trainer="trainer" in ant_roles,
                use_power_meter="power_meter" in ant_roles,
                use_heart_rate="heart_rate" in ant_roles,
                trainer_id=p.trainer_device_number,
                power_meter_id=p.power_meter_device_number,
                heart_rate_id=p.heart_rate_device_number,
                shared=self,
            )
        self.ble = None
        if ble_roles:
            from .ble.ble_hub import BleHub

            self.ble = BleHub(ble_roles, shared=self)
        for w in self.warnings:
            log.warning("Sensors: %s", w)

    @property
    def _trainer_hub(self) -> SensorHub | None:
        return self.ant if self.transport["trainer"] == "ant" else self.ble

    def start(self) -> None:
        if self.ant is not None:
            self.ant.start()  # raises if the stick is missing: nothing else started yet
        if self.ble is not None:
            self.ble.start()  # connects in the background, never raises here

    def stop(self) -> None:
        for hub in (self.ble, self.ant):
            if hub is not None:
                try:
                    hub.stop()
                except Exception:  # pragma: no cover
                    log.exception("Error stopping %s", type(hub).__name__)

    def set_target_power(self, watts: float) -> None:
        if (h := self._trainer_hub) is not None:
            h.set_target_power(watts)

    def set_basic_resistance(self, percent: float) -> None:
        if (h := self._trainer_hub) is not None:
            h.set_basic_resistance(percent)

    def set_user_configuration(self, rider_kg: float, bike_kg: float, wheel_d_m: float) -> None:
        if (h := self._trainer_hub) is not None:
            h.set_user_configuration(rider_kg, bike_kg, wheel_d_m)

    # -- calibration: done by the transport serving the role (ANT+ only for now) ----------
    def start_calibration(self, role: str) -> CalibrationStatus:
        if role not in ("trainer", "power_meter"):
            raise CalibrationError(f"No calibration for {role}")
        hub = self.ant if self.transport[role] == "ant" else None
        if hub is None:
            raise CalibrationError(
                f"Calibrating the {role.replace('_', ' ')} is only supported over ANT+"
            )
        return hub.start_calibration(role)

    def cancel_calibration(self) -> None:
        if self.ant is not None:
            self.ant.cancel_calibration()
