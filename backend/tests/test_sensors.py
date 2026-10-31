"""Multi-transport sensors: per-role ANT+/BLE routing, BLE hub callbacks and FTMS control, scan
endpoint. No hardware: BLE clients and ANT hubs are faked."""

import asyncio
import struct

import pytest

from hometrainer.ble import protocols as bp
from hometrainer.ble.ble_hub import BleDevice, BleHub
from hometrainer.profile import Profile, ProfileError
from hometrainer.sensors import MultiHub


class FakeClient:
    """Stands in for bleak.BleakClient: records subscriptions and writes."""

    def __init__(self):
        self.notify = {}
        self.writes: list[bytes] = []

    async def start_notify(self, uuid, cb):
        self.notify[uuid] = cb

    async def write_gatt_char(self, uuid, data, response=True):
        assert uuid == bp.FTMS_CONTROL_POINT
        self.writes.append(bytes(data))


def mixed_profile(**kw) -> Profile:
    base = dict(
        trainer_transport="ant",
        trainer_device_number=40688,
        power_meter_transport="ble",
        power_meter_ble_id="PM-UUID",
        power_meter_ble_name="Assioma",
        heart_rate_transport="ble",
        heart_rate_ble_id="HR-UUID",
    )
    return Profile.from_dict({**base, **kw})


def test_multihub_splits_roles_by_transport_and_shares_state():
    m = MultiHub(mixed_profile())
    assert (m.ant.use_trainer, m.ant.use_power_meter, m.ant.use_heart_rate) == (True, False, False)
    assert {d.ble_id: d.roles for d in m.ble.by_id.values()} == {
        "PM-UUID": {"power_meter"},
        "HR-UUID": {"heart_rate"},
    }
    # both transports write into the MultiHub's readings
    with m.ble._lock:
        m.ble._seen("power_meter", transport="ble", ble_id="PM-UUID")
        m.ble._s.pm_power.set(231)
    with m.ant._lock:
        m.ant._seen("trainer", 40688, transport="ant")
        m.ant._s.trainer_power.set(240)
    r = m.readings()
    assert (r.pm_power_w, r.trainer_power_w) == (231, 240)
    st = m.status()
    assert st["power_meter"]["transport"] == "ble" and st["power_meter"]["wanted"] == "PM-UUID"
    assert st["trainer"]["transport"] == "ant" and st["trainer"]["device_number"] == 40688


def test_multihub_routes_trainer_commands_to_its_transport():
    sent = []

    class Spy:
        def set_target_power(self, w):
            sent.append(("power", w))

        def set_basic_resistance(self, p):
            sent.append(("res", p))

        def set_user_configuration(self, *a):
            sent.append(("user", a))

    m = MultiHub(mixed_profile(trainer_transport="ble", trainer_ble_id="TR-UUID"))
    assert m.ant is None  # nothing left on ANT+: the stick is not even needed
    m.ble = Spy()
    m.set_target_power(250)
    m.set_basic_resistance(0)
    assert sent[:2] == [("power", 250), ("res", 0)]


def test_ble_role_without_device_is_a_warning_not_a_crash():
    m = MultiHub(mixed_profile(power_meter_ble_id=None))
    assert any("power meter" in w for w in m.warnings)
    assert "power_meter" not in {r for d in m.ble.by_id.values() for r in d.roles}


def test_profile_rejects_unknown_transport():
    with pytest.raises(ProfileError):
        Profile.from_dict({"trainer_transport": "wifi"})


async def test_ble_hub_decodes_notifications_into_readings():
    hub = BleHub({"power_meter": ("PM", "Assioma"), "heart_rate": ("HR", "Polar")})
    client = FakeClient()
    await hub._subscribe(client, BleDevice("PM", "Assioma", {"power_meter"}))
    await hub._subscribe(client, BleDevice("HR", "Polar", {"heart_rate"}))
    cp = client.notify[bp.CYCLING_POWER_MEASUREMENT]
    cp(None, bytearray(struct.pack("<HhHH", 0x0020, 212, 100, 1000)))
    cp(None, bytearray(struct.pack("<HhHH", 0x0020, 215, 101, 1000 + 683)))  # 1 rev / 0.667 s
    client.notify[bp.HEART_RATE_MEASUREMENT](None, bytearray([0x00, 147]))
    r = hub.readings()
    assert (r.pm_power_w, r.pm_cadence_rpm, r.heart_rate_bpm) == (215, 90, 147)
    st = hub.status()["power_meter"]
    assert (st["transport"], st["ble_id"], st["name"]) == ("ble", "PM", "Assioma")


async def test_ftms_control_loop_requests_control_then_sends_targets():
    hub = BleHub({"trainer": ("TR", "Kickr")})
    hub._running = True
    client = FakeClient()
    disconnected = asyncio.Event()
    hub.set_target_power(200)
    task = asyncio.create_task(hub._control_loop(client, disconnected))
    await asyncio.sleep(0.1)
    hub.set_target_power(260)
    await asyncio.sleep(0.4)
    disconnected.set()
    await task
    assert client.writes[:2] == [bp.ftms_request_control(), bp.ftms_start()]
    assert bp.ftms_set_target_power(200) in client.writes
    assert client.writes[-1] == bp.ftms_set_target_power(260)
    assert bp.FTMS_CONTROL_POINT in client.notify  # indications enabled before writing


def test_scan_endpoint_merges_results_and_reconnects(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import hometrainer.app as appmod
    from hometrainer.storage import Storage

    monkeypatch.setattr(
        appmod, "scan_ant", lambda s: [{"transport": "ant", "device_number": 40688, "roles": []}]
    )

    async def fake_ble(s):
        return [{"transport": "ble", "ble_id": "PM", "name": "Assioma", "roles": ["power_meter"]}]

    monkeypatch.setattr(appmod, "scan_ble", fake_ble)
    app = appmod.create_app(Storage(tmp_path))
    with TestClient(app) as c:
        c.post("/api/devices/connect", json={"kind": "simulator"})
        r = c.post("/api/devices/scan?seconds=2").json()
        assert r["ant"][0]["device_number"] == 40688 and r["ble"][0]["name"] == "Assioma"
        assert r["errors"] == {}
        assert app.state.st.hub_kind == "simulator"  # previous connection restored
