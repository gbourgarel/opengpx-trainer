"""Discover ANT+ devices in range.

One background-scanning channel with a wildcard device type hears every ANT+ device
broadcasting on the ANT+ frequency; the extended data gives each one's number and type.

When the hub is connected, the scan runs as an extra channel on the hub's own node
(``AntHub.scan``), so the sensors stay connected. ``scan_ant`` here is the stand-alone version,
used when no hub holds the stick.
"""

from __future__ import annotations

import threading
import time

from . import profiles as pf
from .ant_hub import AntUnavailable

DEVICE_TYPES = {
    pf.FEC_DEVICE_TYPE: ("trainer", "FE-C trainer"),
    pf.PWR_DEVICE_TYPE: ("power_meter", "Power"),
    pf.HRM_DEVICE_TYPE: ("heart_rate", "Heart rate"),
    121: (None, "Speed & cadence"),
    122: (None, "Cadence"),
    123: (None, "Speed"),
}
SCAN_PERIOD = 8070
START_ATTEMPTS = 3


class ScanCollector:
    """Collects (device number, device type) from extended broadcast data."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.found: dict[tuple[int, int], int] = {}  # -> message count

    def on_data(self, data) -> None:
        if len(data) < 13 or not data[8] & 0x80:
            return
        key = (data[9] | (data[10] << 8), data[11])
        with self._lock:
            self.found[key] = self.found.get(key, 0) + 1

    def summary(self) -> list[dict]:
        with self._lock:
            found = dict(self.found)
        trainers = {n for (n, t) in found if t == pf.FEC_DEVICE_TYPE}
        out = []
        for (num, dtype), count in found.items():
            role, label = DEVICE_TYPES.get(dtype, (None, f"type {dtype}"))
            note = None
            if dtype == pf.PWR_DEVICE_TYPE and num in trainers:
                note = "trainer's own power broadcast"
                role = None  # never offer it as the power meter
            out.append(
                {
                    "transport": "ant",
                    "device_number": num,
                    "device_type": dtype,
                    "label": label,
                    "roles": [role] if role else [],
                    "note": note,
                    "messages": count,
                }
            )
        return sorted(out, key=lambda d: (d["device_type"], d["device_number"]))


def configure_scan_channel(ch, on_data) -> None:
    ch.on_broadcast_data = on_data
    ch.on_burst_data = on_data
    ch.set_id(0, 0, 0)  # any device number, any device type
    ch.enable_extended_messages(1)
    ch.set_search_timeout(0xFF)
    ch.set_period(SCAN_PERIOD)
    ch.set_rf_freq(pf.RF_FREQ)


def scan_ant(duration_s: float = 6.0) -> list[dict]:
    """Stand-alone scan: opens the stick, scans, releases it. Retries the start, since a stick
    that was just released often misses the first command after its reset."""
    try:
        from openant.devices import ANTPLUS_NETWORK_KEY
        from openant.easy.channel import Channel
        from openant.easy.exception import AntException
        from openant.easy.node import Node
    except ImportError as e:  # pragma: no cover
        raise AntUnavailable(f"openant not installed: {e}") from e
    collector = ScanCollector()
    for attempt in range(1, START_ATTEMPTS + 1):
        try:
            node = Node()
        except Exception as e:
            raise AntUnavailable(f"No usable ANT+ USB stick ({e})") from e
        try:
            node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)
            ch = node.new_channel(Channel.Type.BIDIRECTIONAL_RECEIVE, 0x00, 0x01)  # background
            configure_scan_channel(ch, collector.on_data)
            ch.open()
            threading.Thread(target=node.start, name="ant-scan", daemon=True).start()
            time.sleep(duration_s)
            break
        except AntException as e:
            if attempt == START_ATTEMPTS:
                raise AntUnavailable(f"The ANT+ stick did not answer ({e})") from e
        finally:
            node.stop()  # always release the stick
        time.sleep(1.5)
    return collector.summary()
