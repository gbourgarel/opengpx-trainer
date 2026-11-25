"""Bluetooth LE sensor hub (bleak), feeding the same readings as the ANT+ hub.

Each configured device gets one connection task (a device may fill several roles, e.g. a smart
trainer that also relays heart rate). Tasks reconnect automatically. bleak is asyncio-based, so
it runs in a dedicated thread with its own event loop; the SensorHub interface stays sync.

Trainer control uses FTMS: request control, start, then "set target power" (ERG), bounded by the
trainer's Supported Power Range when it has one. Free ride uses the FTMS indoor-bike simulation
at 0 % grade, Sim mode the same with the route's grade. FTMS has no rider-weight command (the
User Data Service would need a consent procedure few trainers implement), so the user
configuration is not sent over BLE. Heart-rate straps give R-R intervals, power meters the
L/R balance, into the same readings as over ANT+. The Battery Level, when a device has one,
goes into the sensor's identity (shown before / after a ride, written in the FIT).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass

from ..ant.hub import SensorHub
from . import protocols as bp

log = logging.getLogger(__name__)

RECONNECT_DELAY_S = 3.0
COMMAND_RESEND_S = 5.0


@dataclass
class BleDevice:
    ble_id: str
    name: str | None
    roles: set[str]


class BleHub(SensorHub):
    def __init__(self, roles: dict[str, tuple[str, str | None]], shared: SensorHub | None = None):
        """roles: role -> (ble_id, display name), e.g. {"power_meter": ("UUID", "Assioma")}."""
        super().__init__(shared)
        self.by_id: dict[str, BleDevice] = {}
        for role, (ble_id, name) in roles.items():
            dev = self.by_id.setdefault(ble_id, BleDevice(ble_id, name, set()))
            dev.roles.add(role)
            self.devices[role].wanted = ble_id
            self.devices[role].transport = "ble"
            self.devices[role].ble_id = ble_id
            self.devices[role].name = name
        self.trainer_id = roles["trainer"][0] if "trainer" in roles else None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._command: bytes | None = None
        self._command_seq = 0
        self._pm_cadence = bp.CrankCadence()
        self.last_control_result: tuple[int, str] | None = None
        self.power_range: bp.PowerRange | None = None  # FTMS Supported Power Range, if read

    # -- lifecycle ----------------------------------------------------------------------
    def start(self) -> None:
        if not self.by_id:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble-hub", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        tasks = [self._loop.create_task(self._device_task(d)) for d in self.by_id.values()]
        try:
            self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        finally:
            self._loop.close()

    def stop(self) -> None:
        self._running = False
        loop, thread = self._loop, self._thread
        if loop is not None and loop.is_running():
            for task in asyncio.all_tasks(loop):
                loop.call_soon_threadsafe(task.cancel)
        if thread is not None:
            thread.join(timeout=10)
        self._loop = self._thread = None

    # -- trainer control (FTMS) ---------------------------------------------------------
    def _set_command(self, data: bytes) -> None:
        if data != self._command:
            self._command = data
            self._command_seq += 1

    def set_target_power(self, watts: float) -> None:
        if self.power_range is not None:  # a target outside it may be refused or ignored
            watts = self.power_range.clamp(watts)
        self._set_command(bp.ftms_set_target_power(watts))

    def set_basic_resistance(self, percent: float) -> None:
        self._set_command(bp.ftms_set_simulation(grade=0.0))  # free ride: flat road feel

    def set_slope(self, grade: float) -> None:
        # FTMS needs every field: the same defaults as free ride (no wind), only the grade
        self._set_command(bp.ftms_set_simulation(grade=grade))

    def set_user_configuration(self, rider_kg: float, bike_kg: float, wheel_d_m: float) -> None:
        pass  # not part of FTMS

    # -- connection per device ----------------------------------------------------------
    async def _device_task(self, dev: BleDevice) -> None:
        from bleak import BleakClient

        while self._running:
            disconnected = asyncio.Event()
            try:
                log.info("BLE: connecting to %s (%s) for %s", dev.name, dev.ble_id, dev.roles)
                # bind this attempt's event: a late callback from a previous connection must
                # not end the next one
                async with BleakClient(
                    dev.ble_id,
                    disconnected_callback=lambda _c, ev=disconnected: ev.set(),
                    timeout=15.0,
                ) as client:
                    await self._subscribe(client, dev)
                    log.info("BLE: connected to %s", dev.name or dev.ble_id)
                    if "trainer" in dev.roles:
                        await self._control_loop(client, disconnected)
                    else:
                        await disconnected.wait()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # device off, out of range, refused...
                log.warning("BLE: %s: %s", dev.name or dev.ble_id, e)
            if self._running:
                await asyncio.sleep(RECONNECT_DELAY_S)

    async def _subscribe(self, client, dev: BleDevice) -> None:
        bid, name = dev.ble_id, dev.name

        def seen(role: str) -> None:
            self._seen(role, transport="ble", ble_id=bid, name=name)

        if "heart_rate" in dev.roles:

            def on_hr(_s, data: bytearray) -> None:
                hr = bp.parse_heart_rate(bytes(data))
                rr = bp.parse_rr_intervals(bytes(data))
                with self._lock:
                    seen("heart_rate")
                    self._s.heart_rate.set(hr)
                    if rr:
                        self.add_rr(rr)  # beats for the FIT HRV, as over ANT+

            await client.start_notify(bp.HEART_RATE_MEASUREMENT, on_hr)

        if "power_meter" in dev.roles:

            def on_power(_s, data: bytearray) -> None:
                cp = bp.parse_cycling_power(bytes(data))
                if cp is None:
                    return
                with self._lock:
                    seen("power_meter")
                    cadence = None
                    power: float = cp.power_w
                    if cp.crank_revs is not None:
                        cadence = self._pm_cadence.update(cp.crank_revs, cp.crank_event_time)
                        if self._pm_cadence.stalled():
                            power = 0.0  # repeated last frame while not pedalling
                    self._s.pm_power.set(power)
                    self._s.pm_cadence.set(None if cadence is None else round(cadence))
                    if cp.balance is not None and power > 0:
                        self._s.pm_balance.set(cp.balance)

            await client.start_notify(bp.CYCLING_POWER_MEASUREMENT, on_power)

        if "trainer" in dev.roles:

            def on_bike(_s, data: bytearray) -> None:
                d = bp.parse_indoor_bike_data(bytes(data))
                if d is None:
                    return
                with self._lock:
                    seen("trainer")
                    if d.power_w is not None:
                        self._s.trainer_power.set(d.power_w)
                    if d.cadence_rpm is not None:
                        self._s.trainer_cadence.set(round(d.cadence_rpm))
                    if d.speed_kmh is not None:
                        self._s.trainer_speed.set(d.speed_kmh / 3.6)
                    if d.heart_rate and not self.devices["heart_rate"].connected:
                        self._s.heart_rate.set(d.heart_rate)  # relayed by the trainer

            await client.start_notify(bp.INDOOR_BIKE_DATA, on_bike)

        await self._battery(client, dev)

    async def _battery(self, client, dev: BleDevice) -> None:
        """Battery Level (optional service): read now, then follow its notifications if the
        device sends them (most only update it every few minutes, or on a new connection)."""

        def store(data: bytes) -> None:
            level = bp.parse_battery_level(data)
            if level is None:
                return
            with self._lock:
                for role in dev.roles:
                    self.devices[role].identity.battery_level = level

        try:
            store(bytes(await client.read_gatt_char(bp.BATTERY_LEVEL)))
        except Exception as e:
            log.info("BLE: %s: no battery level (%s)", dev.name or dev.ble_id, e)
            return
        with contextlib.suppress(Exception):  # notify is optional for this characteristic
            await client.start_notify(bp.BATTERY_LEVEL, lambda _s, data: store(bytes(data)))

    async def _control_loop(self, client, disconnected: asyncio.Event) -> None:
        def on_cp(_s, data: bytearray) -> None:
            res = bp.parse_control_point_response(bytes(data))
            if res:
                self.last_control_result = res
                if res[1] != "success":
                    log.warning("FTMS command %#04x: %s", res[0], res[1])

        await client.start_notify(bp.FTMS_CONTROL_POINT, on_cp)
        try:  # optional in FTMS: a trainer without it gets the targets as they are
            rng = bp.parse_supported_power_range(
                bytes(await client.read_gatt_char(bp.SUPPORTED_POWER_RANGE))
            )
            if rng is not None:
                self.power_range = rng
                log.info(
                    "FTMS power range: %d-%d W (step %d)", rng.min_w, rng.max_w, rng.increment_w
                )
        except Exception as e:
            log.info("FTMS power range not read: %s", e)
        await client.write_gatt_char(bp.FTMS_CONTROL_POINT, bp.ftms_request_control(), True)
        await client.write_gatt_char(bp.FTMS_CONTROL_POINT, bp.ftms_start(), True)
        sent_seq, sent_at = -1, 0.0  # (re)connected: always send the current command
        while self._running and not disconnected.is_set():
            cmd, seq = self._command, self._command_seq
            now = time.monotonic()
            if cmd is not None and (seq != sent_seq or now - sent_at > COMMAND_RESEND_S):
                await client.write_gatt_char(bp.FTMS_CONTROL_POINT, cmd, True)
                sent_seq, sent_at = seq, now
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(disconnected.wait(), timeout=0.25)
