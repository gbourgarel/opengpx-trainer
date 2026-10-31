"""Real ANT+ implementation on a USB stick (Garmin/Dynastream ANT USB2 / USB-m) via openant.

One ANT node, three slave channels: FE-C trainer, bicycle power meter, heart-rate monitor.
Each channel pairs with an explicit device number when one is configured (Profile → Devices),
otherwise with the first device found (wildcard).

Most smart trainers also broadcast a standard ANT+ *power* profile (type 11) with the same device
number as their FE-C channel. A wildcard power-meter search would then pair with the trainer
itself instead of the rider's power meter. The power-meter channel is therefore opened only once
the trainer's device number is known, with that number on an ANT exclusion list. When a power-
meter device number is configured, the channel pairs with that device only.

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
from .hub import SensorHub

log = logging.getLogger(__name__)


class AntUnavailable(RuntimeError):
    pass


class AntHub(SensorHub):
    TARGET_RESEND_S = 2.0  # re-send ERG target periodically (survives trainer reconnects)

    def __init__(
        self,
        use_power_meter: bool = True,
        use_heart_rate: bool = True,
        trainer_id: int | None = None,
        power_meter_id: int | None = None,
        heart_rate_id: int | None = None,
    ):
        super().__init__()
        self.use_power_meter = use_power_meter
        self.use_heart_rate = use_heart_rate
        self.wanted = {
            "trainer": trainer_id,
            "power_meter": power_meter_id,
            "heart_rate": heart_rate_id,
        }
        for kind, num in self.wanted.items():
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
        self._raw_log = None
        self._raw_lock = threading.Lock()
        self._t0 = time.monotonic()
        self._fec_power = pf.EventAveragedPower(65536)
        self._pm_power = pf.EventAveragedPower(65536)
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

        self._fec = self._open_channel(
            pf.FEC_DEVICE_TYPE, pf.FEC_PERIOD, self._on_fec, device_number=self.wanted["trainer"]
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
                self._open_channel(
                    pf.PWR_DEVICE_TYPE, pf.PWR_PERIOD, self._on_power, device_number=pm_id
                )
                log.info("Power-meter channel opened, paired to device %s", pm_id)
            except Exception:
                log.exception("Could not open power-meter channel")
            return
        deadline = time.monotonic() + self.PM_WAIT_FOR_TRAINER_S
        while self._running and time.monotonic() < deadline:
            if self.devices["trainer"].device_number is not None:
                break
            time.sleep(0.2)
        if not self._running:
            return
        trainer_num = self.devices["trainer"].device_number
        exclude = [trainer_num] if trainer_num is not None else []
        try:
            self._open_channel(pf.PWR_DEVICE_TYPE, pf.PWR_PERIOD, self._on_power, exclude)
            log.info("Power-meter search opened (excluding trainer %s)", trainer_num)
        except Exception:
            log.exception("Could not open power-meter channel")

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
            self._seen("trainer", num)
            if isinstance(msg, pf.FecTrainer):
                avg = self._fec_power.update(
                    msg.event_count, msg.accumulated_power_w, msg.instantaneous_power_w
                )
                self._s.trainer_power.set(avg if avg is not None else msg.instantaneous_power_w)
                self._s.trainer_cadence.set(msg.cadence_rpm)
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
        msg = pf.decode_power(data)
        with self._lock:
            self._seen("power_meter", num)
            if msg is not None:
                avg = self._pm_power.update(
                    msg.event_count, msg.accumulated_power_w, msg.instantaneous_power_w
                )
                self._s.pm_power.set(avg)
                self._s.pm_cadence.set(msg.cadence_rpm)

    def _on_hrm(self, data) -> None:
        self._log_raw("hrm", data)
        num = self._device_number(data)
        if not self._accept("heart_rate", num):
            return
        hr = pf.decode_hrm(data)
        with self._lock:
            self._seen("heart_rate", num)
            self._s.heart_rate.set(hr)

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

    def _send_ack(self, data: list[int], retries: int = 3) -> bool:
        from openant.base.message import Message
        from openant.easy.exception import AntException

        ch = self._fec
        for _ in range(retries):
            try:
                ch._ant.send_acknowledged_data(ch.id, data)
                ch.wait_for_event([Message.Code.EVENT_TRANSFER_TX_COMPLETED])
                return True
            except AntException:
                time.sleep(0.1)
        log.warning("FE-C command %#04x not acknowledged", data[0])
        return False

    def _tx_loop(self) -> None:
        """Single sender thread. Only the latest control command matters, so queued requests
        are coalesced; the command is also re-sent periodically."""
        last_sent = 0.0
        user_sent = False
        while self._running:
            try:
                items = {self._tx_queue.get(timeout=0.5)}
            except queue.Empty:
                items = {"tick"}
            while True:
                try:
                    items.add(self._tx_queue.get_nowait())
                except queue.Empty:
                    break
            if None in items or self._fec is None:
                return
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
