"""Multi-transport sensors: per-role ANT+/BLE routing, BLE hub callbacks and FTMS control, scan
endpoint. No hardware: BLE clients and ANT hubs are faked."""

import asyncio
import struct

import pytest

from opengpx_trainer.ble import protocols as bp
from opengpx_trainer.ble.ble_hub import BleDevice, BleHub
from opengpx_trainer.profile import Profile, ProfileError
from opengpx_trainer.sensors import MultiHub


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

    import opengpx_trainer.app as appmod
    from opengpx_trainer.storage import Storage

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


# --- ANT+ scan without disconnecting --------------------------------------------------------
class FakeChannel:
    class Type:
        BIDIRECTIONAL_RECEIVE = 0

    def __init__(self, cid):
        self.id = cid
        self.events: list[str] = []

    def __getattr__(self, name):  # set_id, set_period, ... just recorded
        return lambda *a, **k: self.events.append(name)

    def open(self):
        self.events.append("open")

    def close(self):
        self.events.append("close")


class FakeNode:
    def __init__(self):
        self.channels: list[FakeChannel] = []

    def new_channel(self, *_a):
        ch = FakeChannel(len(self.channels))
        self.channels.append(ch)
        return ch


def _ext(num, dtype):
    return [0] * 8 + [0x80, num & 0xFF, num >> 8, dtype, 5]


def test_ant_hub_scan_uses_an_extra_channel_and_reuses_it(monkeypatch):
    """The scan used to disconnect ANT+ for ~15 s (and could fail on the stick's reset)."""
    from opengpx_trainer.ant import ant_hub as ah

    hub = ah.AntHub()
    hub._node, hub._running, hub._channel_cls = FakeNode(), True, FakeChannel
    hub._node.new_channel()  # existing hub channels (trainer, PM, HR)
    hub._node.new_channel()
    hub._node.new_channel()

    def fake_sleep(_s):  # devices broadcasting during the scan window
        hub._on_scan(_ext(40688, 17))
        hub._on_scan(_ext(40688, 11))
        hub._on_scan(_ext(63426, 11))

    monkeypatch.setattr(ah.time, "sleep", fake_sleep)
    found = hub.scan(1)
    pm = {d["device_number"]: d for d in found if d["device_type"] == 11}
    assert pm[40688]["roles"] == [] and "own power" in pm[40688]["note"]
    assert pm[63426]["roles"] == ["power_meter"]
    hub.scan(1)  # second scan
    assert len(hub._node.channels) == 4  # one scan channel, created once, never removed
    scan_ch = hub._node.channels[3]
    assert scan_ch.events.count("open") == 2 and scan_ch.events.count("close") == 2
    hub._on_scan(_ext(1, 120))  # data after the scan is ignored
    assert hub._scan_sink is None


def test_scan_endpoint_keeps_ant_connected(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import opengpx_trainer.app as appmod
    from opengpx_trainer.storage import Storage

    monkeypatch.setattr(appmod, "scan_ant", lambda s: pytest.fail("stick must not be reopened"))

    async def no_ble(s):
        return []

    monkeypatch.setattr(appmod, "scan_ble", no_ble)
    app = appmod.create_app(Storage(tmp_path))
    st = app.state.st

    class FakeAnt:
        _running = True

        def scan(self, s):
            return [{"transport": "ant", "device_number": 63426, "roles": ["power_meter"]}]

    class ConnectedHub:
        ant = FakeAnt()

        def stop(self):
            pytest.fail("the sensors must stay connected during a scan")

    with TestClient(app) as c:
        st.hub, st.hub_kind = ConnectedHub(), "devices"
        try:
            r = c.post("/api/devices/scan?seconds=2").json()
            assert r["ant"][0]["device_number"] == 63426 and r["errors"] == {}
            assert st.hub_kind == "devices"
        finally:
            st.hub, st.hub_kind = None, None


def test_standalone_ant_scan_retries_after_missed_first_command(monkeypatch):
    import openant.easy.node as node_mod
    from openant.easy.exception import AntException

    from opengpx_trainer.ant import scan as scan_mod

    attempts, stopped = [], []

    class FlakyNode(FakeNode):
        def __init__(self):
            super().__init__()
            attempts.append(self)

        def set_network_key(self, *_):
            if len(attempts) == 1:
                raise AntException("Timed out while waiting for message")

        def start(self):
            pass

        def stop(self):
            stopped.append(self)

    monkeypatch.setattr(node_mod, "Node", FlakyNode)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _s: None)
    assert scan_mod.scan_ant(1) == []
    assert len(attempts) == 2 and stopped == attempts  # retried, every node released
