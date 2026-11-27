"""Calibration of the power source: trainer spin-down and power-meter zero offset."""

import pytest

from opengpx_trainer.ant import profiles as pf
from opengpx_trainer.ant.calibration import CalibrationError, SpinDown, ZeroOffset
from opengpx_trainer.profile import Profile

ZWO = """<workout_file><name>W</name><workout>
<SteadyState Duration="300" Power="0.5"/>
</workout></workout_file>"""

# pages seen on the stick on 2026-11-19
TACX_PAGE_2 = [2, 128, 64, 255, 184, 34, 255, 255]  # spin-down pending, speed too low
ASSIOMA_ZERO_OK = [1, 172, 255, 255, 255, 255, 0, 0]


def progress(speed_condition: int) -> pf.FecCalibrationProgress:
    return pf.FecCalibrationProgress(False, True, 0, speed_condition, None, 8.888, None)


# -- pages ---------------------------------------------------------------------------------
def test_fec_calibration_pages():
    assert pf.encode_fec_calibration_request() == [1, 0x80, 0, 255, 255, 255, 255, 255]
    assert pf.encode_fec_calibration_request(spin_down=False, zero_offset=True)[1] == 0x40
    p = pf.decode_fec(TACX_PAGE_2)
    assert p == pf.FecCalibrationProgress(False, True, 0, 1, None, 8.888, None)
    # result: spin-down ok, 20 degC (90 * 0.5 - 25), zero offset n/a, 9800 ms
    r = pf.decode_fec([1, 0x80, 0, 90, 255, 255, 9800 & 0xFF, 9800 >> 8])
    assert r == pf.FecCalibrationResult(False, True, 20.0, None, 9800)


def test_power_meter_calibration_pages():
    assert pf.encode_pm_calibration_request() == [1, 0xAA, 255, 255, 255, 255, 255, 255]
    assert pf.decode_power_extra(ASSIOMA_ZERO_OK) == pf.PmCalibrationResult(True, None, 0)
    failed = pf.decode_power_extra([1, 0xAF, 1, 255, 255, 255, 0xF6, 0xFF])
    assert failed == pf.PmCalibrationResult(False, True, -10)
    assert pf.decode_power_extra([1, 0x12, 0, 0, 0, 0, 0, 0]) is None  # other calibration IDs


# -- state machines ------------------------------------------------------------------------
def test_spin_down_happy_path():
    c = SpinDown(now=0.0)
    assert c.poll(0.0) == pf.encode_fec_calibration_request()
    assert c.poll(1.0) is None  # re-sent every 2 s until the trainer answers
    assert c.poll(2.0) is not None
    c.on_page(progress(1), now=9.0)
    assert c.status.phase == "speed_up" and c.status.target_speed_kmh == 32.0
    assert c.poll(10.0) is None  # answered: no more requests
    c.on_page(progress(2), now=11.0)
    assert c.status.phase == "coast"
    c.on_page(progress(1), now=12.0)  # slowing down while coasting: still coasting
    assert c.status.phase == "coast"
    c.on_page(pf.FecCalibrationResult(False, True, 21.0, None, 9800))
    s = c.status
    assert (s.phase, s.spin_down_ms, s.temperature_c, s.active) == ("done", 9800, 21.0, False)
    assert s.finished_at is not None
    c.on_page(pf.FecCalibrationResult(False, False, None, None, None))  # after the end: ignored
    assert c.status.phase == "done"


def test_spin_down_failures():
    c = SpinDown(now=0.0)
    c.on_page(progress(1))
    c.on_page(pf.FecCalibrationResult(False, False, None, None, None))
    assert c.status.phase == "failed"

    silent = SpinDown(now=0.0)
    for t in range(12):
        silent.poll(float(t))
    assert silent.status.phase == "failed" and "does not answer" in silent.status.message

    slow = SpinDown(now=0.0)
    slow.on_page(progress(1), now=119.0)  # still answering, never finishing
    slow.poll(121.0)
    assert slow.status.phase == "failed" and "Timed out" in slow.status.message

    cancelled = SpinDown(now=0.0)
    cancelled.cancel()
    assert cancelled.status.phase == "cancelled" and cancelled.poll(1.0) is None


def test_spin_down_fails_when_the_trainer_goes_silent():
    """KNOWN_ISSUES #28: the Tacx rebooted mid speed-up and never sent page 2 again; the
    dialog kept saying "Pedal up" until the 120 s timeout."""
    c = SpinDown(now=0.0)
    c.poll(0.0)
    for t in (0.5, 1.0, 1.5, 2.5):  # page 2 at ~2 Hz, one 1 s gap (seen)
        c.on_page(progress(1), now=t)
        assert c.poll(t + 0.4) is None and c.status.active
    assert c.poll(6.4) is None and c.status.active  # 3.9 s of silence
    c.poll(6.6)
    assert c.status.phase == "failed" and "restarted" in c.status.message

    coasting = SpinDown(now=0.0)  # also while coasting: no page 2 until the result
    coasting.on_page(progress(2), now=1.0)
    coasting.poll(5.5)
    assert coasting.status.phase == "failed"


def test_spin_down_without_a_time_is_a_success():
    c = SpinDown(now=0.0)
    c.on_page(progress(2), now=1.0)
    c.on_page(pf.decode_fec([1, 0x80, 0, 255, 255, 255, 255, 255]), now=2.0)  # Tacx, 2026-11-22
    assert (c.status.phase, c.status.spin_down_ms) == ("done", None)


def test_user_configuration_is_resent_when_the_trainer_asks():
    """KNOWN_ISSUES #29: a reboot during a spin-down left the Tacx without rider weight and
    wheel size for the whole ride (status "user configuration required")."""
    from opengpx_trainer.ant.ant_hub import AntHub

    due = AntHub.user_config_due
    assert due(False, False, False, 0.0, 100.0)  # never sent to this connection
    assert due(True, True, False, 99.0, 100.0)  # profile changed
    assert not due(False, True, False, 0.0, 100.0)  # sent, not asked
    assert due(False, True, True, 94.0, 100.0)  # asked: again, every 5 s
    assert not due(False, True, True, 97.0, 100.0)
    h = AntHub()
    h._on_fec([0x19, 1, 90, 0, 0, 200, 0x60, 0x30])  # status 6: calibration + user config
    assert h._user_cfg_asked
    h._on_fec([0x19, 2, 90, 0, 0, 200, 0x20, 0x30])  # status 2: user config received
    assert not h._user_cfg_asked


def test_last_calibration_survives_a_reconnection(tmp_path):
    """KNOWN_ISSUES #30: keep the last result, so a flag raised again by a power-up or a
    reboot does not look like a failure (and the Ride tab stops nudging)."""
    from opengpx_trainer.ant.calibration import CalibrationStatus
    from opengpx_trainer.app import AppState
    from opengpx_trainer.storage import Storage

    st = AppState(Storage(tmp_path))
    st.connect("simulator")
    done = CalibrationStatus("trainer", "spin_down", "done", finished_at=1.0)
    st.hub.devices["trainer"].calibration = done
    st.disconnect()
    st.connect("simulator")
    assert st.hub.devices["trainer"].calibration is done
    assert st.hub.devices["power_meter"].calibration is None
    st.disconnect()


def test_zero_offset():
    c = ZeroOffset(now=0.0)
    assert c.status.phase == "zeroing"
    assert c.poll(0.0) == pf.encode_pm_calibration_request()
    assert c.poll(3.0) is None  # the pedals answer in ~4 s: no early second request
    assert c.poll(6.0) is not None
    assert c.poll(12.0) is None  # at most 2 requests
    c.on_page(pf.PmCalibrationResult(True, None, 0))
    assert (c.status.phase, c.status.zero_offset) == ("done", 0)

    bad = ZeroOffset(now=0.0)
    bad.on_page(pf.PmCalibrationResult(False, None, 0))
    assert bad.status.phase == "failed"

    silent = ZeroOffset(now=0.0)
    silent.poll(0.0)
    silent.poll(16.0)
    assert silent.status.phase == "failed"


# -- hubs ----------------------------------------------------------------------------------
def test_trainer_asks_for_a_spin_down():
    from opengpx_trainer.ant.ant_hub import AntHub

    h = AntHub()
    h._on_fec([0x19, 1, 90, 0, 0, 200, 0x60, 0x30])  # status bits 1 and 2 (0x60 >> 4)
    assert h.status()["trainer"]["calibration_requested"] is True
    h._on_fec([0x19, 2, 90, 0, 0, 200, 0x40, 0x30])  # user configuration only
    assert h.status()["trainer"]["calibration_requested"] is False


def test_simulated_spin_down_and_zero_offset():
    from opengpx_trainer.ant.simulator import SimulatedHub

    h = SimulatedHub()
    h.update_settings(noise=False)
    h.step()
    with pytest.raises(CalibrationError):
        h.start_calibration("heart_rate")
    h.start_calibration("trainer")
    assert h.calibrating() and h.calibrating("trainer")
    with pytest.raises(CalibrationError):
        h.start_calibration("power_meter")  # one at a time
    for _ in range(20):
        h.step()
    cal = h.status()["trainer"]["calibration"]
    assert cal["phase"] == "speed_up" and cal["speed_kmh"] > 0
    for _ in range(40):  # 10 s at +1.2 m/s^2: past 32 km/h
        h.step()
    h.update_settings(pedaling=False)
    for _ in range(80):  # coasting down
        h.step()
    cal = h.status()["trainer"]["calibration"]
    assert cal["phase"] == "done" and cal["spin_down_ms"] > 5000
    assert not h.calibrating()

    h.start_calibration("power_meter")  # not pedalling: succeeds
    for _ in range(8):
        h.step()
    assert h.status()["power_meter"]["calibration"]["phase"] == "done"
    h.update_settings(pedaling=True)
    h.start_calibration("power_meter")  # pedalling: fails
    for _ in range(8):
        h.step()
    assert h.status()["power_meter"]["calibration"]["phase"] == "failed"
    assert h.status()["trainer"]["calibration"]["phase"] == "done"  # last result kept


def test_multihub_calibrates_over_ant_only(monkeypatch):
    from opengpx_trainer.sensors import MultiHub

    p = Profile()
    p.trainer_transport = "ble"
    p.trainer_ble_id = "AA"
    m = MultiHub(p)
    with pytest.raises(CalibrationError, match="only supported over ANT"):
        m.start_calibration("trainer")


def test_calibration_api_and_no_auto_start(tmp_path):
    from fastapi.testclient import TestClient

    from opengpx_trainer.app import create_app
    from opengpx_trainer.storage import Storage

    with TestClient(create_app(Storage(tmp_path))) as c:
        assert c.post("/api/devices/calibrate", json={"role": "trainer"}).status_code == 409
        c.post("/api/devices/connect", json={"kind": "simulator"})
        st = c.app.state.st
        st.hub.update_settings(noise=False)
        st.hub.step()
        bad = c.post("/api/devices/calibrate", json={"role": "heart_rate"})
        assert bad.status_code == 422
        r = c.post("/api/devices/calibrate", json={"role": "trainer"})
        assert r.status_code == 200 and r.json()["phase"] == "requesting"
        assert c.post("/api/devices/calibrate", json={"role": "trainer"}).status_code == 409
        # a ride waiting for the first pedal stroke does not start during the spin-down
        w = c.post(
            "/api/workouts/import",
            files={"file": ("w.zwo", ZWO)},
        )
        assert c.post("/api/session/start", json={"mode": "erg", "workout_id": w.json()["id"]})
        for _ in range(8):
            st.hub.step()
            with st.session_lock:
                st.session.tick()
        assert st.session.state == "ready"
        assert c.post("/api/devices/calibrate/cancel").json() == {"ok": True}
        dev = c.get("/api/devices").json()["devices"]["trainer"]
        assert dev["calibration"]["phase"] == "cancelled"
        for _ in range(4):
            st.hub.step()
            with st.session_lock:
                st.session.tick()
        assert st.session.state == "running"
        assert c.post("/api/devices/calibrate", json={"role": "trainer"}).status_code == 409


def test_calibration_during_a_paused_ride(tmp_path):
    """ROADMAP 4a: calibrate after the warm-up; the ride stays paused meanwhile and resumes on
    a pedal stroke once the calibration is over and the pedals have stopped."""
    from fastapi.testclient import TestClient

    from opengpx_trainer.app import create_app
    from opengpx_trainer.storage import Storage

    with TestClient(create_app(Storage(tmp_path))) as c:
        c.post("/api/devices/connect", json={"kind": "simulator"})
        st = c.app.state.st
        st.hub.update_settings(noise=False)
        w = c.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)})
        c.post("/api/session/start", json={"mode": "erg", "workout_id": w.json()["id"]})

        def ticks(n):
            for _ in range(n):
                st.hub.step()
                with st.session_lock:
                    st.session.tick()

        ticks(4)
        assert st.session.state == "running"
        refused = c.post("/api/devices/calibrate", json={"role": "trainer"})
        assert refused.status_code == 409 and "Pause" in refused.json()["detail"]
        c.post("/api/session/pause")
        assert c.post("/api/devices/calibrate", json={"role": "trainer"}).status_code == 200
        ticks(20)  # pedalling up to the target speed: the ride does not resume
        assert st.session.state == "paused"
        c.post("/api/devices/calibrate/cancel")  # e.g. failed while pedalling
        ticks(8)
        assert st.session.state == "paused"  # Try again stays possible
        st.hub.update_settings(pedaling=False)
        ticks(4)
        assert st.session.state == "paused"
        st.hub.update_settings(pedaling=True)
        ticks(4)
        assert st.session.state == "running"  # resumed by the next pedal stroke
