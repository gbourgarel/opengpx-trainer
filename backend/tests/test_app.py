"""API-level regression tests (code review 2026-10-31)."""

import time

import pytest
from fastapi.testclient import TestClient

from hometrainer.app import create_app
from hometrainer.storage import Storage
from tests.test_gpx_workouts import ZWO


@pytest.fixture
def client(tmp_path):
    app = create_app(Storage(tmp_path))
    with TestClient(app) as c:
        c.st = app.state.st
        yield c


def start_erg(c) -> None:
    assert c.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = c.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)}).json()["id"]
    assert c.post("/api/session/start", json={"mode": "erg", "workout_id": wid}).status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("ftp_w", None),  # cleared field in the UI
        ("ftp_w", "250"),
        ("wheel_diameter_m", 0),
        ("rider_mass_kg", True),
        ("power_source", "both"),
        ("power_match", "yes"),
        ("grade_curve", [[0, 0.7]]),
        ("trainer_device_number", 70000),
        ("bike_preset", "bmx"),
    ],
)
def test_invalid_profile_is_rejected_and_not_saved(client, field, value):
    """Review #2: a cleared FTP was stored as null and crashed every ERG tick."""
    before = client.get("/api/profile").json()
    r = client.put("/api/profile", json={field: value})
    assert r.status_code == 422 and field in r.json()["detail"]
    assert client.get("/api/profile").json() == before


def test_valid_profile_update_and_optional_fields(client):
    r = client.put(
        "/api/profile", json={"ftp_w": 280, "max_hr_bpm": None, "power_meter_device_number": 63426}
    )
    assert r.status_code == 200
    assert (r.json()["ftp_w"], r.json()["power_meter_device_number"]) == (280, 63426)


def test_bad_stored_profile_falls_back_to_defaults(tmp_path):
    import json

    from hometrainer.profile import Profile

    s = Storage(tmp_path)
    s._exec(
        "INSERT INTO settings(key, value) VALUES('profile', ?)",
        (json.dumps({"ftp_w": None, "rider_mass_kg": 72}),),
    )
    p = s.load_profile()
    assert p.ftp_w == Profile().ftp_w and p.rider_mass_kg == 72


def test_default_profile_is_its_preset():
    from hometrainer.profile import BIKE_PRESETS, PRESET_FIELDS, Profile

    p = Profile()
    preset = BIKE_PRESETS[p.bike_preset]
    assert all(getattr(p, f) == getattr(preset, f) for f in PRESET_FIELDS)


def test_bike_preset_sets_its_values_and_custom_keeps_them(client):
    presets = {p["id"]: p for p in client.get("/api/bike-presets").json()}
    assert {"road_hoods", "road_drops", "tt", "gravel", "mtb", "city"} == set(presets)
    # a preset wins over values sent with it
    r = client.put("/api/profile", json={"bike_preset": "mtb", "cda_m2": 0.2, "crr": 0.002})
    assert r.status_code == 200
    got = r.json()
    assert got["bike_preset"] == "mtb"
    assert (got["cda_m2"], got["crr"], got["wheel_diameter_m"]) == (0.45, 0.009, 0.74)
    # custom: the values are the rider's
    r = client.put("/api/profile", json={"bike_preset": "custom", "cda_m2": 0.3})
    assert (r.json()["bike_preset"], r.json()["cda_m2"], r.json()["crr"]) == ("custom", 0.3, 0.009)
    assert client.st.profile.model_params().cda_m2 == 0.3


@pytest.mark.parametrize(
    "stored,preset,cda",
    [
        ({"cda_m2": 0.30, "crr": 0.004}, "custom", 0.30),  # rider's own values: kept
        ({"cda_m2": 0.29, "crr": 0.0045}, "road_drops", 0.29),  # same as a preset
        ({"rider_mass_kg": 70}, "road_hoods", 0.32),  # no speed-model field: default preset
    ],
)
def test_profile_stored_before_presets(tmp_path, stored, preset, cda):
    import json

    s = Storage(tmp_path)
    s._exec("INSERT INTO settings(key, value) VALUES('profile', ?)", (json.dumps(stored),))
    p = s.load_profile()
    assert (p.bike_preset, p.cda_m2) == (preset, cda)


def test_reconnect_rebinds_existing_session_to_new_hub(client):
    """Review #1: after Disconnect/Connect the session kept driving the stopped hub."""
    start_erg(client)
    old_hub = client.st.hub
    client.post("/api/devices/disconnect")
    client.post("/api/devices/connect", json={"kind": "simulator"})
    assert client.st.hub is not old_hub
    assert client.st.session.hub is client.st.hub


def test_session_identity_lets_a_client_rebuild_the_ride_view(client):
    """Review #3: after a reload the ride screen was lost (view state lived only in React)."""
    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = client.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)}).json()["id"]
    res = client.post("/api/session/start", json={"mode": "erg", "workout_id": wid}).json()
    tel = client.st.session.tick()
    assert tel["session_id"] == res["session_id"]
    assert (tel["mode"], tel["workout_id"], tel["route_id"]) == ("erg", wid, None)
    w = client.get(f"/api/workouts/{wid}").json()
    assert w["id"] == wid and w["steps"]
    assert client.get("/api/workouts/9999").status_code == 404


def test_start_gpx_ride_with_workout(client):
    from tests.test_gpx_workouts import make_gpx

    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = client.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)}).json()["id"]
    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    r = client.post("/api/session/start", json={"mode": "gpx", "route_id": rid, "workout_id": wid})
    assert r.status_code == 200
    tel = client.st.session.tick()
    assert (tel["mode"], tel["route_id"], tel["workout_id"]) == ("gpx", rid, wid)
    assert "step_remaining_s" in tel and "lap" in tel
    client.post("/api/session/stop?save=false")
    bad = {"mode": "gpx", "route_id": rid, "workout_id": 999}
    assert client.post("/api/session/start", json=bad).status_code == 404


SHORT_ZWO = """<workout_file><name>Short</name><workout>
<SteadyState Duration="2" Power="0.5"/>
</workout></workout_file>"""


def test_ride_finished_by_engine_then_stopped_is_saved_once(client):
    """Review #5: engine auto-save + 'Stop & save' produced two history rows / FIT files."""
    import time

    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = client.post("/api/workouts/import", files={"file": ("s.zwo", SHORT_ZWO)}).json()["id"]
    client.post("/api/session/start", json={"mode": "erg", "workout_id": wid})
    deadline = time.monotonic() + 10
    while client.st.session.state != "finished" and time.monotonic() < deadline:
        time.sleep(0.1)  # the real engine loop is ticking in the background
    assert client.st.session.state == "finished"
    time.sleep(0.6)  # a few more "finished" ticks
    saved = client.post("/api/session/stop").json()["saved"]
    rides = client.get("/api/rides").json()
    assert len(rides) == 1 and saved["ride_id"] == rides[0]["id"]


def test_concurrent_saves_write_a_single_ride(client):
    import threading

    start_erg(client)
    s = client.st.session
    with client.st.session_lock:  # keep the background engine out while we prepare
        s.finish()
    if not s.recorder.samples:  # make sure there is something to save
        from hometrainer.recording import Sample

        s.recorder.add(Sample(1e9, 1.0, 150, 90, 120, 8.0, 8.0))
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(client.st.save_session(s))) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(client.get("/api/rides").json()) == 1
    assert len({r["ride_id"] for r in results}) == 1


def test_ride_is_uploaded_to_intervals_only_once(client, monkeypatch):
    from hometrainer.recording import Sample
    from hometrainer.workouts.intervals_icu import IntervalsIcuClient

    calls = []

    async def fake_upload(self, fit_bytes, filename, name=None):
        calls.append((filename, name, len(fit_bytes)))
        return {"id": "i4242"}

    monkeypatch.setattr(IntervalsIcuClient, "upload_activity", fake_upload)
    client.put("/api/profile", json={"intervals_api_key": "k", "intervals_athlete_id": "i1"})
    start_erg(client)
    s = client.st.session
    with client.st.session_lock:
        for i in range(30):
            s.recorder.add(Sample(1.8e9 + i, i + 1.0, 200, 90, 140, 9.0, 9.0 * i))
    rid = client.post("/api/session/stop").json()["saved"]["ride_id"]

    first = client.post(f"/api/rides/{rid}/upload").json()
    again = client.post(f"/api/rides/{rid}/upload").json()
    assert first == {"intervals_activity_id": "i4242", "already": False}
    assert again == {"intervals_activity_id": "i4242", "already": True}
    assert len(calls) == 1 and calls[0][1] == s.name and calls[0][2] > 0
    assert client.get("/api/rides").json()[0]["intervals_activity_id"] == "i4242"
    assert client.post("/api/rides/999/upload").status_code == 404


def test_skip_and_extend_step_api(client):
    start_erg(client)
    w0 = client.get("/api/session/workout").json()
    assert w0["workout_rev"] == 0
    r = client.post("/api/session/step", json={"action": "extend", "seconds": 60})
    assert r.status_code == 200
    w1 = r.json()
    assert w1["workout_rev"] == 1 and w1["duration_s"] == w0["duration_s"] + 60
    assert w1["steps"][0]["duration_s"] == w0["steps"][0]["duration_s"] + 60
    assert client.get("/api/session/workout").json() == w1
    assert client.post("/api/session/step", json={"action": "skip"}).json()["workout_rev"] == 2
    bad = client.post("/api/session/step", json={"action": "extend", "seconds": -5})
    assert bad.status_code == 422


def test_ride_is_saved_without_holding_the_session_lock(client, monkeypatch):
    """Review #9: the FIT write ran on the event loop and under the session lock."""
    import threading
    import time

    from hometrainer.recording import Recorder

    real_write = Recorder.write_fit
    lock_free = []

    def slow_write(self, path):
        def probe():
            got = client.st.session_lock.acquire(timeout=1)
            lock_free.append(got)
            if got:
                client.st.session_lock.release()

        th = threading.Thread(target=probe)
        th.start()
        th.join()
        time.sleep(0.5)  # meanwhile the engine must keep ticking
        return real_write(self, path)

    monkeypatch.setattr(Recorder, "write_fit", slow_write)
    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = client.post("/api/workouts/import", files={"file": ("s.zwo", SHORT_ZWO)}).json()["id"]
    client.post("/api/session/start", json={"mode": "erg", "workout_id": wid})
    s = client.st.session
    deadline = time.monotonic() + 10
    while s.saved is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert s.saved is not None and lock_free == [True]
    assert len(client.get("/api/rides").json()) == 1


def test_disconnect_is_refused_during_a_ride(client):
    """Review #12: disconnecting mid-ride hid the ride and stopped ticking / recording it."""
    start_erg(client)  # "ready": waiting for the first pedal stroke
    assert client.post("/api/devices/disconnect").status_code == 409
    assert client.st.hub is not None
    client.post("/api/session/stop", params={"save": "false"})
    assert client.post("/api/devices/disconnect").status_code == 200
    assert client.st.hub is None


def test_publish_latest_keeps_only_the_newest_message():
    import asyncio

    from hometrainer.app import publish_latest

    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    for i in range(3):
        publish_latest(q, {"i": i})
    assert q.qsize() == 1 and q.get_nowait() == {"i": 2}


def test_live_websocket_sends_telemetry(client):
    with client.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["state"] == "disconnected"
        assert len(client.st.clients) == 1
    deadline = time.monotonic() + 2
    while client.st.clients and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not client.st.clients  # forgotten once closed


def test_a_client_that_stops_reading_does_not_stall_the_engine(client, monkeypatch):
    """Review #11: a sleeping tablet blocked ``await send_json`` in the engine loop, so the
    ride stopped ticking (riding time lost, no samples) until the socket timed out."""
    import asyncio

    from starlette.websockets import WebSocket

    import hometrainer.app as app_mod

    async def never_sent(self, data, mode="text"):
        await asyncio.sleep(3600)  # the client's TCP buffer is full

    monkeypatch.setattr(WebSocket, "send_json", never_sent)
    monkeypatch.setattr(app_mod, "WS_SEND_TIMEOUT_S", 0.5)
    start_erg(client)
    s = client.st.session
    with client.websocket_connect("/ws/live"):
        time.sleep(0.3)
        first = s._last_tick
        time.sleep(0.6)
        assert s._last_tick is not None and s._last_tick > first  # the engine keeps ticking
        deadline = time.monotonic() + 2
        while client.st.clients and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not client.st.clients  # the stalled client was dropped
