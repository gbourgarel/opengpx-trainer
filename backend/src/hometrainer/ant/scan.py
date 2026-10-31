"""Discover ANT+ devices in range.

One background-scanning channel with a wildcard device type hears every ANT+ device
broadcasting on the ANT+ frequency; the extended data gives each one's number and type.
The stick must not be in use by the hub while scanning.
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


def scan_ant(duration_s: float = 6.0) -> list[dict]:
    try:
        from openant.devices import ANTPLUS_NETWORK_KEY
        from openant.easy.channel import Channel
        from openant.easy.node import Node
    except ImportError as e:  # pragma: no cover
        raise AntUnavailable(f"openant not installed: {e}") from e
    try:
        node = Node()
    except Exception as e:
        raise AntUnavailable(f"No usable ANT+ USB stick ({e})") from e
    found: dict[tuple[int, int], dict] = {}
    lock = threading.Lock()

    def on_data(data) -> None:
        if len(data) < 13 or not data[8] & 0x80:
            return
        num, dtype = data[9] | (data[10] << 8), data[11]
        with lock:
            entry = found.setdefault(
                (num, dtype), {"device_number": num, "device_type": dtype, "messages": 0}
            )
            entry["messages"] += 1

    try:
        node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)
        ch = node.new_channel(Channel.Type.BIDIRECTIONAL_RECEIVE, 0x00, 0x01)  # background scan
        ch.on_broadcast_data = on_data
        ch.on_burst_data = on_data
        ch.set_id(0, 0, 0)  # any device number, any device type
        ch.enable_extended_messages(1)
        ch.set_search_timeout(0xFF)
        ch.set_period(8070)
        ch.set_rf_freq(pf.RF_FREQ)
        ch.open()
        threading.Thread(target=node.start, name="ant-scan", daemon=True).start()
        time.sleep(duration_s)
    finally:
        node.stop()  # always release the stick

    trainers = {n for (n, t) in found if t == pf.FEC_DEVICE_TYPE}
    out = []
    for (num, dtype), e in found.items():
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
                "messages": e["messages"],
            }
        )
    return sorted(out, key=lambda d: (d["device_type"], d["device_number"]))
