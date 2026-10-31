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
