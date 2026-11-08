"""Real ANT+ implementation on a USB stick (Garmin/Dynastream ANT USB2 / USB-m) via openant.

One ANT node, three slave channels: FE-C trainer, bicycle power meter, heart-rate monitor.
Each channel pairs with an explicit device number when one is configured (Profile → Devices),
otherwise with the first device found (wildcard).

Most smart trainers also broadcast a standard ANT+ *power* profile (type 11) with the same device
number as their FE-C channel. A wildcard power-meter search would then pair with the trainer
itself instead of the rider's power meter. The power-meter channel is therefore opened only once
the trainer's device number is known, with that number on an ANT exclusion list. When a power-
meter device number is configured, the channel pairs with that device only.

Dual-sided power meters also send pedal metrics: L/R balance (page 16), torque effectiveness and
pedal smoothness (page 19) and, once enabled by the display, Cycling Dynamics (pages 0xE0-0xE2:
power phase, rider position, platform centre offset). Enabling Cycling Dynamics from the app
(``profiles.CyclingDynamicsEnabler``) is switched off for now (``ENABLE_CYCLING_DYNAMICS``):
the pages are recorded when a head unit enables them. The heart-rate channel also yields
beat-to-beat (R-R) intervals.

Set ``HOMETRAINER_ANT_LOG=/path/file.csv`` to log every raw ANT page (for debugging).

openant's ``easy`` API is used directly. Its high-level ``devices.FitnessEquipment`` is not used
(FE-state parsing bug, and its ack sender retries forever recursively).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time

from . import profiles as pf
from .hub import STALE_AFTER_S, SensorHub

log = logging.getLogger(__name__)

# a power meter counts as "sending crank-torque pages" if one arrived within this window
PM_TORQUE_FRESH_S = 5.0


class AntUnavailable(RuntimeError):
    pass


class AntHub(SensorHub):
    TARGET_RESEND_S = 2.0  # re-send ERG target periodically (survives trainer reconnects)
    # Send the Cycling Dynamics set-up to the power meter. Off: on a real ride (2026-11-08,
    # Assioma) the power-meter channel received nothing more once the first request (page 70)
    # was sent, 0.3 s after pairing, on the 4 Hz channel. The pages are still decoded when a
    # head unit enables them; balance, TE and PS need no set-up.
    ENABLE_CYCLING_DYNAMICS = False

    def __init__(
        self,
        use_power_meter: bool = True,
        use_heart_rate: bool = True,
        trainer_id: int | None = None,
        power_meter_id: int | None = None,
        heart_rate_id: int | None = None,
        use_trainer: bool = True,
        shared: SensorHub | None = None,
    ):
        super().__init__(shared)
        self.use_trainer = use_trainer
        self.use_power_meter = use_power_meter
        self.use_heart_rate = use_heart_rate
        self.wanted = {
            "trainer": trainer_id,
            "power_meter": power_meter_id,
            "heart_rate": heart_rate_id,
        }
        roles = {
            "trainer": use_trainer,
            "power_meter": use_power_meter,
            "heart_rate": use_heart_rate,
        }
        for kind, num in self.wanted.items():
            if roles[kind]:  # only the roles served over ANT+
                self.devices[kind].wanted = num
        self._node = None
        self._fec = None
        self._node_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._tx_queue: queue.Queue = queue.Queue()
        self._running = False
        self._command: list[int] | None = None
        self._user_cfg: list[int] | None = None
        self._fec_ch = None
        self._channel_cls = None
        # openant numbers channels len(node.channels) and dispatches by list index: channels
        # must be created one at a time and never removed (closed channels are reused)
        self._channel_lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._scan_ch = None
        self._scan_sink = None
        self._raw_log = None
        self._raw_lock = threading.Lock()
        self._t0 = time.monotonic()
        self._fec_power = pf.EventAveragedPower(65536)
        self._pm_power = pf.EventAveragedPower(65536)
        self._pm_torque = pf.CrankTorquePower()
        self._pm_torque_seen_at = float("-inf")
        self._pm_ch = None
        self._pm_seen_at = float("-inf")
        self._dynamics = pf.CyclingDynamicsEnabler()
        self._rr = pf.RRIntervals()
        self.last_command_status: pf.FecCommandStatus | None = None

    # -- lifecycle ----------------------------------------------------------------------
    START_ATTEMPTS = 3

    def start(self) -> None:
        """Open the stick and the channels. Retries: a stick left in a bad state (e.g. by a
        killed process) often times out on the first configuration message after a reset."""
        try:
            from openant.easy.exception import AntException
        except ImportError as e:  # pragma: no cover
            raise AntUnavailable(f"openant not installed: {e}") from e
        for attempt in range(1, self.START_ATTEMPTS + 1):
            try:
                self._start_once()
                return
            except AntException as e:
                log.warning("ANT+ start attempt %d/%d failed: %s", attempt, self.START_ATTEMPTS, e)
                self.stop()  # always release the USB device before retrying
                if attempt == self.START_ATTEMPTS:
                    raise AntUnavailable(
                        f"The ANT+ stick did not answer ({e}). Unplug it, plug it back in and "
                        "try again."
                    ) from e
                time.sleep(1.5)

    def _start_once(self) -> None:
        from openant.devices import ANTPLUS_NETWORK_KEY
        from openant.easy.channel import Channel
        from openant.easy.node import Node

        try:
            node = Node()
        except Exception as e:  # usb.core.NoBackendError, DriverNotFound, USBError ...
            raise AntUnavailable(
                f"No usable ANT+ USB stick ({e}). Is it plugged in, libusb installed "
                "(brew install libusb) and Garmin Express / Zwift closed?"
            ) from e
        # Register the node *before* any call that can fail, so stop() can always release the
        # USB device. (Otherwise openant's reader thread keeps the stick busy forever.)
        self._node = node
        self._running = True
        node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)

        self._channel_cls = Channel
        log_path = os.environ.get("HOMETRAINER_ANT_LOG")
        if log_path and self._raw_log is None:
            self._raw_log = open(log_path, "a", buffering=1)  # noqa: SIM115 (closed in stop)
            self._raw_log.write("t_s,channel,device_number,b0,b1,b2,b3,b4,b5,b6,b7\n")
            log.info("Logging raw ANT pages to %s", log_path)

        if self.use_trainer:
            self._fec = self._open_channel(
                pf.FEC_DEVICE_TYPE,
                pf.FEC_PERIOD,
                self._on_fec,
                device_number=self.wanted["trainer"],
            )
        if self.use_heart_rate:
            self._open_channel(
                pf.HRM_DEVICE_TYPE,
                pf.HRM_PERIOD,
                self._on_hrm,
                device_number=self.wanted["heart_rate"],
            )

        self._node_thread = threading.Thread(target=node.start, name="ant-node", daemon=True)
        self._node_thread.start()
        self._tx_queue = queue.Queue()
        self._tx_thread = threading.Thread(target=self._tx_loop, name="ant-tx", daemon=True)
        self._tx_thread.start()
        if self.use_power_meter:
            threading.Thread(target=self._open_power_meter, name="ant-pm", daemon=True).start()

    PM_WAIT_FOR_TRAINER_S = 15.0

    def _open_channel(
        self,
        device_type: int,
        period: int,
        on_data,
        exclude: list[int] = (),
        device_number: int | None = None,
    ):
        from openant.base.message import Message

        with self._channel_lock:
            ch = self._node.new_channel(self._channel_cls.Type.BIDIRECTIONAL_RECEIVE, 0x00, 0x01)
        ch.on_broadcast_data = on_data
        ch.on_burst_data = on_data
        ch.on_acknowledge = on_data
        ch.set_search_timeout(0xFF)
        # device number 0 = wildcard; transmission type 0 = wildcard
        ch.set_id(device_number or 0, device_type, 0)
        if exclude and not device_number:
            # ANT inclusion/exclusion list: never pair with these device numbers
            for i, num in enumerate(exclude[:4]):
                ch._ant.write_message(
                    Message(
                        Message.ID.ADD_CHANNEL_ID,
                        [ch.id, num & 0xFF, (num >> 8) & 0xFF, device_type, 0, i],
                    )
                )
                ch.wait_for_response(Message.ID.ADD_CHANNEL_ID)
            ch._ant.write_message(Message(Message.ID.CONFIG_LIST, [ch.id, min(len(exclude), 4), 1]))
            ch.wait_for_response(Message.ID.CONFIG_LIST)
        ch.enable_extended_messages(1)
        ch.set_period(period)
        ch.set_rf_freq(pf.RF_FREQ)
        ch.open()
        return ch

    def _open_power_meter(self) -> None:
        """Open the power-meter channel: the configured device, or a wildcard search excluding
        the trainer (opened once the trainer's device number is known)."""
        pm_id = self.wanted["power_meter"]
        if pm_id:
            try:
                self._pm_ch = self._open_channel(
                    pf.PWR_DEVICE_TYPE, pf.PWR_PERIOD, self._on_power, device_number=pm_id
                )
                log.info("Power-meter channel opened, paired to device %s", pm_id)
            except Exception:
                log.exception("Could not open power-meter channel")
            return
        # wait for the ANT+ trainer (if it is on ANT+) so its number can be excluded
        deadline = time.monotonic() + (self.PM_WAIT_FOR_TRAINER_S if self.use_trainer else 0)
        while self._running and time.monotonic() < deadline:
            if self.devices["trainer"].device_number is not None:
                break
            time.sleep(0.2)
        if not self._running:
            return
        trainer_num = self.devices["trainer"].device_number
        exclude = [trainer_num] if trainer_num is not None else []
        try:
            self._pm_ch = self._open_channel(
                pf.PWR_DEVICE_TYPE, pf.PWR_PERIOD, self._on_power, exclude
            )
            log.info("Power-meter search opened (excluding trainer %s)", trainer_num)
        except Exception:
            log.exception("Could not open power-meter channel")

    # -- scan (while connected) ----------------------------------------------------------
    def scan(self, duration_s: float = 6.0) -> list[dict]:
        """List the ANT+ devices in range without disconnecting: an extra background-scanning
        channel on this node, opened for the scan then closed (kept for the next scan)."""
        from .scan import ScanCollector, configure_scan_channel

        if self._node is None or not self._running:
            raise AntUnavailable("ANT+ is not connected")
        collector = ScanCollector()
        with self._scan_lock:
            self._scan_sink = collector.on_data
            if self._scan_ch is None:
                with self._channel_lock:
                    ch = self._node.new_channel(
                        self._channel_cls.Type.BIDIRECTIONAL_RECEIVE, 0x00, 0x01
                    )
                configure_scan_channel(ch, self._on_scan)
                self._scan_ch = ch
            self._scan_ch.open()
            try:
                time.sleep(duration_s)
            finally:
                self._scan_ch.close()
                self._scan_sink = None
        return collector.summary()

    def _on_scan(self, data) -> None:
        sink = self._scan_sink
        if sink is not None:
            sink(data)

    def stop(self) -> None:
        self._running = False
        self._tx_queue.put(None)
        if self._raw_log is not None:
            with self._raw_lock:
                self._raw_log.close()
                self._raw_log = None
        node, self._node = self._node, None
        if node is not None:
            try:
                node.stop()
            except Exception:  # pragma: no cover
                log.exception("Error stopping ANT node")
        self._fec = None

    # -- receive ------------------------------------------------------------------------
    @staticmethod
    def _device_number(data) -> int | None:
        # Extended message: byte 8 = flag 0x80, then device number LSB/MSB, type, trans type
        if len(data) >= 13 and data[8] & 0x80:
            return data[9] | (data[10] << 8)
        return None

    def _log_raw(self, channel: str, data) -> None:
        if self._raw_log is None:
            return
        num = self._device_number(data)
        row = ",".join(str(b) for b in list(data[:8]))
        with self._raw_lock:
            if self._raw_log is not None:
                t = time.monotonic() - self._t0
                self._raw_log.write(f"{t:.3f},{channel},{num if num is not None else ''},{row}\n")

    def _accept(self, kind: str, num: int | None) -> bool:
        """Defensive check: ignore data from any device other than the configured one."""
        wanted = self.wanted.get(kind)
        return not wanted or num is None or num == wanted

    def _on_fec(self, data) -> None:
        self._log_raw("fec", data)
        num = self._device_number(data)
        if not self._accept("trainer", num):
            return
        msg = pf.decode_fec(data)
        with self._lock:
            self._seen("trainer", num, transport="ant")
            if isinstance(msg, pf.FecTrainer):
                avg = self._fec_power.update(
                    msg.event_count, msg.accumulated_power_w, msg.instantaneous_power_w
                )
                self._s.trainer_power.set(avg if avg is not None else msg.instantaneous_power_w)
                self._s.trainer_cadence.set(self._fec_power.cadence(msg.cadence_rpm))
            elif isinstance(msg, pf.FecGeneral):
                self._s.trainer_speed.set(msg.speed_ms)
                if msg.heart_rate and not self.devices["heart_rate"].connected:
                    self._s.heart_rate.set(msg.heart_rate)  # HR relayed by the trainer
            elif isinstance(msg, pf.FecCommandStatus):
                self.last_command_status = msg

    def _on_power(self, data) -> None:
        self._log_raw("power", data)
        num = self._device_number(data)
        if num is not None and num == self.devices["trainer"].device_number:
            return  # the trainer's own power broadcast, not an independent power meter
        if not self._accept("power_meter", num):
            return
        msg = pf.decode_power(data) or pf.decode_power_extra(data)
        now = time.monotonic()
        # a meter lost for a while (asleep, battery) may have forgotten Cycling Dynamics
        if now - self._pm_seen_at > STALE_AFTER_S:
            self._dynamics.reset()
        self._pm_seen_at = now
        cmds = self._dynamics.on_page(msg, now)  # also learns PCO support from the capabilities
        if self.ENABLE_CYCLING_DYNAMICS:
            for cmd in cmds + self._dynamics.poll(now):
                self._tx_queue.put(("pm", tuple(cmd)))
        with self._lock:
            self._seen("power_meter", num, transport="ant")
            self._store_pedal(msg)
            if isinstance(msg, pf.CrankTorque):
                # crank-torque pages: a fresh value at every crank revolution
                self._pm_torque_seen_at = now
                power, cadence = self._pm_torque.update(msg, now)
                if power is not None:
                    self._s.pm_power.set(power)
                if cadence is not None:
                    self._s.pm_cadence.set(round(cadence))
            elif isinstance(msg, pf.PowerOnly):
                avg = self._pm_power.update(
                    msg.event_count, msg.accumulated_power_w, msg.instantaneous_power_w, now
                )
                # meters sending crank-torque pages use those only: no flip-flopping between
                # two estimators; power-only meters use page 16 as before
                if now - self._pm_torque_seen_at > PM_TORQUE_FRESH_S:
                    self._s.pm_power.set(avg)
                    self._s.pm_cadence.set(self._pm_power.cadence(msg.cadence_rpm))

    def _store_pedal(self, msg) -> None:
        """Pedal metrics of a dual-sided meter (``_lock`` held)."""
        s = self._s
        if isinstance(msg, pf.PowerOnly):
            if msg.pedal_balance is not None:
                s.pm_balance.set(msg.pedal_balance)
        elif isinstance(msg, pf.PedalEfficiency):
            s.pm_te.set((msg.left_te, msg.right_te))
            s.pm_ps.set((msg.left_ps, msg.right_ps, msg.combined_ps))
        elif isinstance(msg, pf.ForceAngle):
            side = s.pm_left_angles if msg.side == "left" else s.pm_right_angles
            side.set((msg.phase_deg, msg.peak_phase_deg))
        elif isinstance(msg, pf.PedalPosition):
            s.pm_position.set(
                (
                    pf.ANT_TO_FIT_RIDER_POSITION[msg.rider_position],
                    msg.left_pco_mm if self._dynamics.pco_supported else None,
                    msg.right_pco_mm if self._dynamics.pco_supported else None,
                )
            )

    def _on_hrm(self, data) -> None:
        self._log_raw("hrm", data)
        num = self._device_number(data)
        if not self._accept("heart_rate", num):
            return
        hr = pf.decode_hrm(data)
        rr = self._rr.update(data)
        with self._lock:
            self._seen("heart_rate", num, transport="ant")
            self._s.heart_rate.set(hr)
            if rr:
                self.add_rr(rr)

    # -- transmit -----------------------------------------------------------------------
    def _set_command(self, data: list[int]) -> None:
        if data != self._command:
            self._command = data
            self._tx_queue.put("command")

    def set_target_power(self, watts: float) -> None:
        self._set_command(pf.encode_target_power(watts))

    def set_basic_resistance(self, percent: float) -> None:
        self._set_command(pf.encode_basic_resistance(percent))

    def set_user_configuration(self, rider_kg: float, bike_kg: float, wheel_d_m: float) -> None:
        self._user_cfg = pf.encode_user_configuration(rider_kg, bike_kg, wheel_d_m)
        self._tx_queue.put("user")

    def _send_ack(self, data: list[int], ch=None, retries: int = 3) -> bool:
        from openant.base.message import Message
        from openant.easy.exception import AntException

        ch = self._fec if ch is None else ch
        if ch is None:
            return False
        for _ in range(retries):
            try:
                ch._ant.send_acknowledged_data(ch.id, list(data))
                ch.wait_for_event([Message.Code.EVENT_TRANSFER_TX_COMPLETED])
                return True
            except AntException:
                time.sleep(0.1)
        log.warning("ANT+ command %#04x not acknowledged", data[0])
        return False

    def _tx_loop(self) -> None:
        """Single sender thread. Only the latest trainer control command matters, so queued
        requests are coalesced; the command is also re-sent periodically. Commands to the power
        meter (``("pm", data)``, Cycling Dynamics set-up) are sent in order, once."""
        last_sent = 0.0
        user_sent = False
        while self._running:
            try:
                items = [self._tx_queue.get(timeout=0.5)]
            except queue.Empty:
                items = ["tick"]
            while True:
                try:
                    items.append(self._tx_queue.get_nowait())
                except queue.Empty:
                    break
            if None in items:
                return
            for item in items:
                if isinstance(item, tuple) and item[0] == "pm":
                    if self._pm_ch is None:  # never fall back on the trainer's channel
                        continue
                    sent = self._send_ack(item[1], ch=self._pm_ch)
                    log.info("Power meter command %s: %s", bytes(item[1]).hex(), sent)
            if self._fec is None:
                continue  # trainer not on ANT+
            if not self.devices["trainer"].connected:
                user_sent = False  # (re)send user config once the trainer shows up again
                continue
            if self._user_cfg and ("user" in items or not user_sent):
                user_sent = self._send_ack(self._user_cfg)
            now = time.monotonic()
            cmd = self._command
            if cmd is not None and ("command" in items or now - last_sent >= self.TARGET_RESEND_S):
                self._send_ack(cmd)
                last_sent = now
