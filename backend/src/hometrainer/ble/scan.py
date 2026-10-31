"""Discover BLE sensors in range (FTMS trainers, power meters, heart-rate straps)."""

from __future__ import annotations

import asyncio

from .protocols import SERVICE_ROLES


class BluetoothUnavailable(RuntimeError):
    pass


async def scan_ble(timeout_s: float = 6.0) -> list[dict]:
    from bleak import BleakScanner

    try:
        # On macOS, CoreBluetooth never answers when the app lacks Bluetooth permission:
        # bound the wait instead of hanging.
        found = await asyncio.wait_for(
            BleakScanner.discover(timeout=timeout_s, return_adv=True), timeout_s + 10
        )
    except TimeoutError as e:
        raise BluetoothUnavailable(
            "Bluetooth did not answer. On macOS, allow Bluetooth for the app running the server "
            "(System Settings → Privacy & Security → Bluetooth), and check Bluetooth is on."
        ) from e
    except Exception as e:  # BleakError: adapter off / missing
        raise BluetoothUnavailable(f"Bluetooth unavailable: {e}") from e
    out = []
    for ble_id, (device, adv) in found.items():
        uuids = {u.lower() for u in adv.service_uuids}
        roles = sorted({role for svc, role in SERVICE_ROLES.items() if svc in uuids})
        if not roles:
            continue  # not a cycling / heart-rate sensor
        out.append(
            {
                "transport": "ble",
                "ble_id": ble_id,
                "name": adv.local_name or device.name or "(unnamed)",
                "rssi": adv.rssi,
                "roles": roles,
            }
        )
    return sorted(out, key=lambda d: -(d["rssi"] or -999))
