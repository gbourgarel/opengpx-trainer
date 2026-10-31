import time

import pytest

from hometrainer.ant import profiles as pf
from hometrainer.ant.hub import SensorHub
from hometrainer.profile import Profile
from hometrainer.recording import Recorder, Sample
from hometrainer.session import PowerMatch, RideSession, choose_power
from hometrainer.workouts.model import Step, Workout


def test_target_power_page():
    assert pf.encode_target_power(250) == [0x31, 255, 255, 255, 255, 255, 0xE8, 0x03]


def test_track_resistance_page():
    d = pf.encode_track_resistance(0.05, 0.004)
    raw = d[5] | (d[6] << 8)
    assert raw == 20500  # (5 % + 200 %) / 0.01 %
    assert d[7] == 80


def test_user_config_page():
    d = pf.encode_user_configuration(75.0, 8.5, 0.672)
    assert d[1] | (d[2] << 8) == 7500
    assert (d[4] >> 4) | (d[5] << 4) == 170  # 8.5 kg / 0.05
    assert d[6] == 67 and d[4] & 0x0F == 2


def test_decode_fec_trainer_page():
    # event 7, cadence 90, acc power 1000, inst power 0x123 = 291 W, state in_use (3)
    msg = pf.decode_fec([0x19, 7, 90, 0xE8, 0x03, 0x23, 0x01, 0x30])
    assert msg.cadence_rpm == 90 and msg.instantaneous_power_w == 291
    assert msg.fe_state == "in_use"


def test_event_averaged_power_with_rollover():
    e = pf.EventAveragedPower(65536)
    e.update(254, 65000, 200)
    assert e.update(2, (65000 + 4 * 250) % 65536, 0) == pytest.approx(250)


class FakeHub(SensorHub):
    def __init__(self):
        super().__init__()
        self.targets = []

    def start(self): ...
    def stop(self): ...

    def set_target_power(self, w):
        self.targets.append(w)

    def set_basic_resistance(self, p):
        self.targets.append(("res", p))

    def set_user_configuration(self, *a): ...

    def feed(self, trainer=None, pm=None, cad=90, hr=140):
        with self._lock:
            if trainer is not None:
                self._seen("trainer")
                self._s.trainer_power.set(trainer)
                self._s.trainer_cadence.set(cad)
            if pm is not None:
                self._seen("power_meter")
                self._s.pm_power.set(pm)
                self._s.pm_cadence.set(cad)
            self._seen("heart_rate")
            self._s.heart_rate.set(hr)


def test_choose_power_auto_prefers_power_meter():
    h = FakeHub()
    h.feed(trainer=210, pm=200)
    assert choose_power(h.readings(), "auto").source == "power_meter"
    assert choose_power(h.readings(), "trainer").power_w == 210
    h2 = FakeHub()
    h2.feed(trainer=210)
    assert choose_power(h2.readings(), "auto").source == "trainer"
    assert choose_power(h2.readings(), "power_meter").source == "none"


def test_power_match_converges():
    """Trainer holds whatever it is told; PM reads 5 % low. PM should converge to target."""
    pmatch, target, sent = PowerMatch(tau_s=5), 250.0, 250.0
    h = FakeHub()
    for _ in range(400):
        h.feed(trainer=sent, pm=sent * 0.95)
        pmatch.update(h.readings(), target, 0.25)
        sent = pmatch.apply(target)
    assert sent * 0.95 == pytest.approx(target, rel=0.005)


def test_erg_session_flow():
    h = FakeHub()
    prof = Profile(ftp_w=200, power_match=False)
    w = Workout("t", [Step(10, 0.5, 0.5), Step(10, 1.0, 1.0)])
    s = RideSession(h, prof, "erg", workout=w)
    t0 = 1000.0
    s.tick(t0)
    assert s.state == "ready"
    h.feed(trainer=100, pm=98)
    for i in range(1, 37):
        tel = s.tick(t0 + i * 0.25)
    assert s.state == "running"
    assert tel["target_w"] == 100
    assert tel["power_source"] == "power_meter"
    s.adjust(intensity_pct=110)
    for i in range(37, 49):
        tel = s.tick(t0 + i * 0.25)
    assert tel["target_w"] == 220  # second step at 110 %
    assert tel["speed_kmh"] > 0


def test_gpx_session_difficulty_affects_speed_only():
    from hometrainer.gpx.route import Route
    from tests.test_gpx_workouts import make_gpx

    route = Route.from_gpx(make_gpx(grade=0.0))
    res = {}
    for diff in (0.0, 20.0):
        h = FakeHub()
        s = RideSession(h, Profile(ftp_w=250), "gpx", route=route)
        s.adjust(difficulty_pct=diff)
        for i in range(200):
            h.feed(trainer=200, pm=200)
            tel = s.tick(1000 + i * 0.25)
        res[diff] = tel
    assert res[20.0]["speed_kmh"] > res[0.0]["speed_kmh"]
    assert res[20.0]["target_w"] == res[0.0]["target_w"] == round(0.70 * 250)


def test_fit_export_roundtrip(tmp_path):
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.record_message import RecordMessage

    rec = Recorder()
    t = time.time()
    for i in range(120):
        rec.add(Sample(t + i, i, 200 + i % 10, 90, 140, 9.0, 9.0 * i, 100.0, 45.0, 6.0, 0.01))
    path = rec.write_fit(tmp_path / "r.fit")
    ff = FitFile.from_file(str(path))
    recs = [r.message for r in ff.records if isinstance(r.message, RecordMessage)]
    assert len(recs) == 120
    assert recs[10].power == 200
    assert rec.summary()["normalized_power_w"] > 200


def test_simulator_manual_power_and_pm_dropout():
    from hometrainer.ant.simulator import SimulatedHub

    h = SimulatedHub()
    h.update_settings(mode="manual", manual_power_w=320, noise=False, pm_bias=0.0)
    h.set_target_power(150)  # ignored in manual mode
    h.step()
    r = h.readings()
    assert r.trainer_power_w == 320 and r.pm_power_w == 320
    assert choose_power(r, "auto").source == "power_meter"

    h.update_settings(pedaling=False)
    h.step()
    assert h.readings().trainer_power_w == 0 and h.readings().trainer_cadence_rpm == 0

    with pytest.raises(ValueError):
        h.update_settings(bogus=1)


def test_simulator_follow_mode_tracks_target():
    from hometrainer.ant.simulator import SimulatedHub

    h = SimulatedHub()
    h.update_settings(noise=False)
    h.set_target_power(250)
    for _ in range(80):  # 20 s at 4 Hz, tau 1.5 s
        h.step()
    assert h.readings().trainer_power_w == pytest.approx(250, abs=1)


def test_simulator_api(tmp_path):
    from fastapi.testclient import TestClient

    from hometrainer.app import create_app
    from hometrainer.storage import Storage

    with TestClient(create_app(Storage(tmp_path))) as c:
        assert c.get("/api/simulator").status_code == 409
        c.post("/api/devices/connect", json={"kind": "simulator"})
        r = c.put("/api/simulator", json={"mode": "manual", "manual_power_w": 280})
        assert r.json()["manual_power_w"] == 280
        assert c.put("/api/simulator", json={"mode": "turbo"}).status_code == 422


def test_event_averaged_power_drops_to_zero_when_events_stop():
    """Regression: stopping pedalling used to freeze the last average (e.g. 230 W forever)."""
    e = pf.EventAveragedPower(65536, stall_s=3.0)
    e.update(10, 1000, 230, now=0.0)
    assert e.update(11, 1230, 230, now=0.25) == pytest.approx(230)
    # rider stops: sensor repeats the same event count, instantaneous still non-zero
    assert e.update(11, 1230, 180, now=1.0) == pytest.approx(230)  # within stall window
    assert e.update(11, 1230, 180, now=3.5) == 0.0  # stalled > 3 s
    # same, but the sensor reports instantaneous 0 -> zero immediately
    e2 = pf.EventAveragedPower(65536)
    e2.update(10, 1000, 230, now=0.0)
    e2.update(11, 1230, 230, now=0.25)
    assert e2.update(11, 1230, 0, now=0.5) == 0.0
    # pedalling again
    assert e2.update(12, 1430, 200, now=0.75) == pytest.approx(200)


def test_power_channel_ignores_trainer_own_broadcast():
    from hometrainer.ant.ant_hub import AntHub

    h = AntHub()
    trainer_page = [0x19, 1, 90, 0, 0, 200, 0x30, 0x30]
    ext = [0x80, 40688 & 0xFF, 40688 >> 8, 17, 5]
    h._on_fec(trainer_page + ext)
    assert h.devices["trainer"].device_number == 40688
    pm_page = [0x10, 1, 0xFF, 90, 0, 0, 200, 0]
    h._on_power(pm_page + [0x80, 40688 & 0xFF, 40688 >> 8, 11, 5])  # same number -> trainer
    assert h.devices["power_meter"].device_number is None
    assert not h.readings().power_meter_connected
    h._on_power(pm_page + [0x80, 0x39, 0x30, 11, 5])  # a real power meter
    assert h.devices["power_meter"].device_number == 0x3039
    assert h.readings().power_meter_connected


def test_concurrent_connect_is_rejected():
    import threading

    from hometrainer.app import AppState, HubBusy

    class SlowHub(FakeHub):
        started = 0

        def start(self):
            SlowHub.started += 1
            time.sleep(0.3)

    st = AppState.__new__(AppState)
    st.hub, st.hub_kind, st._hub_lock = None, None, threading.Lock()
    import hometrainer.app as appmod

    orig = appmod.SimulatedHub
    appmod.SimulatedHub = SlowHub
    try:
        errors = []

        def go():
            try:
                st.connect("simulator")
            except HubBusy as e:
                errors.append(e)

        ts = [threading.Thread(target=go) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        appmod.SimulatedHub = orig
    assert SlowHub.started == 1 and len(errors) == 1


def test_power_meter_pinned_to_configured_device():
    from hometrainer.ant.ant_hub import AntHub

    h = AntHub(power_meter_id=63426)
    pm_page = [0x10, 1, 0xFF, 90, 0, 0, 200, 0]
    h._on_power(pm_page + [0x80, 0x39, 0x30, 11, 5])  # some other power meter in range
    assert h.devices["power_meter"].device_number is None
    h._on_power(pm_page + [0x80, 63426 & 0xFF, 63426 >> 8, 11, 5])
    assert h.devices["power_meter"].device_number == 63426
    assert h.status()["power_meter"]["wanted"] == 63426


def test_profile_device_numbers_validation(tmp_path):
    from fastapi.testclient import TestClient

    from hometrainer.app import create_app
    from hometrainer.storage import Storage

    with TestClient(create_app(Storage(tmp_path))) as c:
        r = c.put("/api/profile", json={"power_meter_device_number": 63426})
        assert r.json()["power_meter_device_number"] == 63426
        assert c.put("/api/profile", json={"trainer_device_number": 70000}).status_code == 422
        r = c.put("/api/profile", json={"power_meter_device_number": None})
        assert r.json()["power_meter_device_number"] is None


def test_ant_start_releases_stick_and_retries_on_timeout(monkeypatch):
    """Regression: a timeout during setup left openant's reader thread holding the USB stick."""
    import openant.easy.node as node_mod
    from openant.easy.exception import AntException

    from hometrainer.ant import ant_hub
    from hometrainer.ant.ant_hub import AntHub, AntUnavailable

    created, stopped = [], []

    class FlakyNode:
        def __init__(self):
            created.append(self)

        def set_network_key(self, *_):
            raise AntException("Timed out while waiting for message")

        def stop(self):
            stopped.append(self)

    monkeypatch.setattr(node_mod, "Node", FlakyNode)
    monkeypatch.setattr(ant_hub.time, "sleep", lambda _s: None)
    h = AntHub()
    with pytest.raises(AntUnavailable, match="Unplug it"):
        h.start()
    assert len(created) == AntHub.START_ATTEMPTS
    assert stopped == created  # every node released, none leaked
    assert h._node is None


def test_cadence_comes_from_power_meter_even_at_zero():
    """Regression: `pm_cadence or trainer_cadence` switched to the trainer whenever PM said 0."""
    h = FakeHub()
    with h._lock:
        h._seen("trainer")
        h._s.trainer_power.set(150)
        h._s.trainer_cadence.set(64)
        h._seen("power_meter")
        h._s.pm_power.set(0)
        h._s.pm_cadence.set(0)
    pc = choose_power(h.readings(), "auto")
    assert (pc.source, pc.cadence_rpm, pc.cadence_source) == ("power_meter", 0, "power_meter")
    # PM without cadence field -> fall back to trainer cadence, and say so
    with h._lock:
        h._s.pm_cadence.set(None)
    pc = choose_power(h.readings(), "auto")
    assert (pc.cadence_rpm, pc.cadence_source) == (64, "trainer")


def test_stalled_power_meter_reports_zero_cadence():
    """Real log (PM 63426): stopped rider, PM repeats cadence 61 / event 62 / 99 W for 90 s."""
    from hometrainer.ant.ant_hub import AntHub

    h = AntHub(power_meter_id=63426)
    ext = [0x80, 63426 & 0xFF, 63426 >> 8, 11, 5]
    page = lambda ev, acc, cad, w: [0x10, ev, 0xFF, cad, acc & 0xFF, acc >> 8, w, 0] + ext  # noqa: E731
    t = [100.0]
    import hometrainer.ant.profiles as prof

    monkey_time = prof.time.monotonic
    prof.time.monotonic = lambda: t[0]
    try:
        h._on_power(page(61, 6000, 61, 99))
        t[0] += 0.25
        h._on_power(page(62, 6099, 61, 99))
        assert h._s.pm_cadence.value == 61
        for _ in range(20):  # 5 s of identical repeats
            t[0] += 0.25
            h._on_power(page(62, 6099, 61, 99))
        assert h._s.pm_cadence.value == 0 and h._s.pm_power.value == 0
    finally:
        prof.time.monotonic = monkey_time


def _gpx_session(grade=0.06):
    from hometrainer.gpx.route import Route
    from tests.test_gpx_workouts import make_gpx

    h = FakeHub()
    s = RideSession(
        h, Profile(ftp_w=250, power_match=False), "gpx", route=Route.from_gpx(make_gpx(grade=grade))
    )
    return h, s


def test_gpx_manual_target_overrides_slope_and_is_immediate():
    h, s = _gpx_session(grade=0.06)
    t = 1000.0
    for _ in range(80):  # 20 s on a 6 % climb: slope target ~ 92 % FTP
        h.feed(trainer=220, pm=220)
        tel = s.tick(t := t + 0.25)
    slope_target = tel["target_w"]
    assert slope_target == pytest.approx(0.92 * 250, abs=3)

    s.adjust(target_mode="manual")  # starts from the current target: no jump
    tel = s.tick(t := t + 0.25)
    assert tel["target_mode"] == "manual" and tel["target_w"] == round(slope_target)

    s.adjust(manual_target_w=150)  # immediate, no 15 W/s ramp
    tel = s.tick(t := t + 0.25)
    assert tel["target_w"] == 150 and h.targets[-1] == 150

    speed_before = tel["speed_kmh"]
    s.adjust(target_mode="slope")  # back to the curve: ramps from 150 W at 15 W/s
    tel = s.tick(t := t + 1.0)
    assert tel["target_mode"] == "slope"
    assert tel["target_w"] == pytest.approx(150 + 15, abs=1)
    assert speed_before > 0  # speed model unaffected by the target mode


def test_manual_target_rejected_in_erg_mode():
    h = FakeHub()
    s = RideSession(h, Profile(), "erg", workout=Workout("w", [Step(60, 0.5, 0.5)]))
    with pytest.raises(ValueError):
        s.adjust(manual_target_w=200)


def test_power_to_weight_uses_rider_mass_only():
    h = FakeHub()
    prof = Profile(rider_mass_kg=70, bike_mass_kg=8, ftp_w=280, power_match=False)
    s = RideSession(h, prof, "erg", workout=Workout("w", [Step(600, 1.0, 1.0)]))
    t = 1000.0
    for _ in range(8):
        h.feed(trainer=210, pm=210)
        tel = s.tick(t := t + 0.25)
    assert tel["power_wkg"] == pytest.approx(3.0)  # 210 W / 70 kg
    assert tel["target_wkg"] == pytest.approx(4.0)  # 280 W / 70 kg


def test_climb_tracker_vam_and_gain():
    from hometrainer.session import ClimbTracker

    c = ClimbTracker(window_s=30, min_span_s=5)
    c.update(0, 100.0)
    c.update(2, 101.0)
    assert c.vam_mh is None  # not enough data yet
    for t in range(3, 61):  # steady 0.5 m/s rise
        c.update(t, 100.0 + 0.5 * t)
    assert c.vam_mh == pytest.approx(1800)  # 0.5 m/s * 3600
    c.update(61, 50.0)  # a descent does not reduce the gain
    assert c.elevation_gain_m == pytest.approx(30.0)


def test_gpx_session_reports_vam_consistent_with_model():
    h, s = _gpx_session(grade=0.06)
    t = 1000.0
    for _ in range(4 * 90):  # 90 s at constant power on a constant 6 % climb
        h.feed(trainer=250, pm=250)
        tel = s.tick(t := t + 0.25)
    assert tel["vam_mh"] > 500
    # in steady state the 30 s VAM equals the model's instantaneous v·sinθ
    assert tel["vam_mh"] == pytest.approx(tel["vam_instant_mh"], rel=0.03)
    assert tel["elevation_gain_m"] > 0
    # ERG rides have no route, hence no VAM
    h2 = FakeHub()
    s2 = RideSession(h2, Profile(), "erg", workout=Workout("w", [Step(60, 0.5, 0.5)]))
    h2.feed(trainer=150, pm=150)
    assert "vam_mh" not in s2.tick(1.0)
