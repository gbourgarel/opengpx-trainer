"""API-level regression tests (code review 2026-10-31)."""

import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from opengpx_trainer.app import create_app
from opengpx_trainer.storage import Storage
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
        ("map_tile_url", "https://tiles.example.com/{z}/{x}.png"),  # no {y}
        ("map_tile_url", "javascript:alert(1)//{z}{x}{y}"),
        ("map_tile_attribution", "x" * 201),
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


def test_map_tile_url_is_stored_and_can_be_cleared(client):
    url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    r = client.put("/api/profile", json={"map_tile_url": f" {url} ", "map_tile_attribution": "E"})
    assert (r.json()["map_tile_url"], r.json()["map_tile_attribution"]) == (url, "E")
    assert client.put("/api/profile", json={"map_tile_url": ""}).json()["map_tile_url"] == ""


def test_bad_stored_profile_falls_back_to_defaults(tmp_path):
    import json

    from opengpx_trainer.profile import Profile

    s = Storage(tmp_path)
    s._exec(
        "INSERT INTO settings(key, value) VALUES('profile', ?)",
        (json.dumps({"ftp_w": None, "rider_mass_kg": 72}),),
    )
    p = s.load_profile()
    assert p.ftp_w == Profile().ftp_w and p.rider_mass_kg == 72


def test_default_profile_is_its_preset():
    from opengpx_trainer.profile import BIKE_PRESETS, PRESET_FIELDS, Profile

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


def test_hub_swap_holds_the_session_lock_but_not_the_slow_stop(client, monkeypatch):
    """Review #18: the engine ticks the session (reading its hub) under session_lock."""
    start_erg(client)
    lock = client.st.session_lock
    seen = {}
    old = client.st.hub
    stop = old.stop
    monkeypatch.setattr(old, "stop", lambda: (seen.update(stop=lock._is_owned()), stop()))
    attach = client.st.session.attach_hub
    monkeypatch.setattr(
        client.st.session, "attach_hub", lambda h: (seen.update(attach=lock._is_owned()), attach(h))
    )
    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    assert seen == {"stop": False, "attach": True}
    assert client.st.session.hub is client.st.hub is not old


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


def test_workout_and_route_of_the_ride_cannot_be_deleted(client):
    """Review #31: other devices rebuild the ride view from them."""
    from tests.test_gpx_workouts import make_gpx

    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = client.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)}).json()["id"]
    other = client.post("/api/workouts/import", files={"file": ("o.zwo", ZWO)}).json()["id"]
    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    r = client.post("/api/session/start", json={"mode": "gpx", "route_id": rid, "workout_id": wid})
    assert r.status_code == 200
    assert client.delete(f"/api/workouts/{wid}").status_code == 409
    assert client.delete(f"/api/routes/{rid}").status_code == 409
    assert client.delete(f"/api/workouts/{other}").status_code == 200
    client.post("/api/session/stop?save=false")
    assert client.delete(f"/api/workouts/{wid}").status_code == 200
    assert client.delete(f"/api/routes/{rid}").status_code == 200


def test_start_gpx_ride_in_reverse(client):
    from tests.test_gpx_workouts import make_gpx

    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    r = client.post("/api/session/start", json={"mode": "gpx", "route_id": rid, "reverse": True})
    assert r.status_code == 200 and r.json()["name"] == "Test climb (reverse)"
    tel = client.st.session.tick()
    assert (tel["route_id"], tel["route_reversed"]) == (rid, True)
    assert tel["grade"] < 0  # the climb, ridden down
    client.post("/api/session/stop?save=false")
    # the client rebuilds the ride view from route_id + route_reversed
    fwd = client.get(f"/api/routes/{rid}").json()
    rev = client.get(f"/api/routes/{rid}?reverse=true").json()
    assert (fwd["reversed"], rev["reversed"]) == (False, True)
    assert rev["altitude_m"] == fwd["altitude_m"][::-1]
    assert (rev["ascent_m"], rev["descent_m"]) == (fwd["descent_m"], fwd["ascent_m"])


def test_start_gpx_ride_part_way(client):
    from tests.test_gpx_workouts import make_gpx

    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    body = {"mode": "gpx", "route_id": rid, "reverse": True, "start_m": 800}
    assert client.post("/api/session/start", json=body).status_code == 200
    tel = client.st.session.tick()
    assert (tel["route_position_m"], tel["route_start_m"], tel["distance_m"]) == (800, 800, 0)
    client.post("/api/session/stop?save=false")
    bad = dict(body, start_m=-5)
    assert client.post("/api/session/start", json=bad).status_code == 422


def test_weather_endpoint_and_ride_air(client, monkeypatch):
    from opengpx_trainer import app as app_mod
    from opengpx_trainer.weather import Weather
    from tests.test_gpx_workouts import make_gpx

    fake = Weather(9.0, 250, 15.0, 12.5, 0.8, 3)
    monkeypatch.setattr(app_mod, "current_weather", lambda route: fake)  # no network in tests
    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    w = client.get(f"/api/routes/{rid}/weather").json()
    assert (w["wind_kmh"], w["wind_from_deg"], w["temperature_c"]) == (9.0, 250, 12.5)
    assert client.get("/api/routes/999/weather").status_code == 404

    def down(route):
        raise httpx.ConnectError("offline")

    import httpx

    monkeypatch.setattr(app_mod, "current_weather", down)
    assert client.get(f"/api/routes/{rid}/weather").status_code == 502
    # the ride uses the air given at start (the profile has none)
    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    body = {"mode": "gpx", "route_id": rid, "temperature_c": 12.5, "relative_humidity": 0.8}
    assert client.post("/api/session/start", json=body).status_code == 200
    s = client.st.session
    assert (s.temperature_c, s.relative_humidity) == (12.5, 0.8)
    assert s.bike.params.temperature_c == 12.5
    assert "temperature_c" not in client.get("/api/profile").json()
    client.post("/api/session/stop?save=false")
    # not given: standard air (and always in ERG)
    client.post("/api/session/start", json={"mode": "gpx", "route_id": rid})
    assert (client.st.session.temperature_c, client.st.session.relative_humidity) == (15.0, 0.5)
    client.post("/api/session/stop?save=false")
    # colder air is denser: a slower estimate
    warm = client.get(f"/api/routes/{rid}/estimate?temperature_c=30").json()["duration_s"]
    cold = client.get(f"/api/routes/{rid}/estimate?temperature_c=-5").json()["duration_s"]
    assert cold > warm


def test_route_estimates_in_the_list_and_by_options(client):
    from tests.test_gpx_workouts import make_gpx

    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    wid = client.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)}).json()["id"]
    listed = client.get("/api/routes").json()[0]
    est = client.get(f"/api/routes/{rid}/estimate").json()
    assert listed["estimate_s"] == est["duration_s"] > 0 and est["laps"] == 1
    # the climb ridden down is faster; a headwind (route heads north) slows it
    down = client.get(f"/api/routes/{rid}/estimate?reverse=true").json()
    windy = client.get(f"/api/routes/{rid}/estimate?wind_kmh=30&wind_from_deg=0").json()
    assert down["duration_s"] < est["duration_s"] < windy["duration_s"]
    # started part-way: the rest of the route only (the climb is regular: about half)
    half = client.get(f"/api/routes/{rid}/estimate?start_m=1100").json()["duration_s"]
    assert half == pytest.approx(est["duration_s"] / 2, rel=0.1)
    # with a workout: its duration, and the distance covered
    w = client.get(f"/api/routes/{rid}/estimate?workout_id={wid}").json()
    assert w["duration_s"] == client.get(f"/api/workouts/{wid}").json()["duration_s"]
    assert w["distance_m"] > 0
    # a new FTP changes the estimate (memoised per profile)
    client.put("/api/profile", json={"ftp_w": 350})
    assert client.get(f"/api/routes/{rid}/estimate").json()["duration_s"] < est["duration_s"]
    assert client.get(f"/api/routes/{rid}/estimate?workout_id=999").status_code == 404
    assert client.get("/api/routes/999/estimate").status_code == 404


def test_route_list_estimates_survive_unrelated_profile_changes(client, monkeypatch):
    """Review #33: any profile Save used to re-parse and re-estimate every route."""
    import opengpx_trainer.app as app_mod
    from tests.test_gpx_workouts import make_gpx

    rid = client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).json()["id"]
    calls = {"parse": 0, "estimate": 0}
    parse, estimate = app_mod.Route.from_gpx, app_mod.estimate_route

    def counting(name, f):
        def wrapper(*a, **k):
            calls[name] += 1
            return f(*a, **k)

        return wrapper

    monkeypatch.setattr(app_mod.Route, "from_gpx", counting("parse", parse))
    monkeypatch.setattr(app_mod, "estimate_route", counting("estimate", estimate))
    first = client.get("/api/routes").json()[0]["estimate_s"]
    assert calls == {"parse": 1, "estimate": 1}
    client.put("/api/profile", json={"max_hr_bpm": 190})  # not used by the estimate
    assert client.get("/api/routes").json()[0]["estimate_s"] == first
    assert calls == {"parse": 1, "estimate": 1}
    client.put("/api/profile", json={"ftp_w": 350})  # used: re-estimated, not re-parsed
    assert client.get("/api/routes").json()[0]["estimate_s"] < first
    assert calls == {"parse": 1, "estimate": 2}
    client.delete(f"/api/routes/{rid}")
    assert client.st.parsed_route(rid) is None  # forgotten, not served from the cache


def test_imports_parse_off_the_event_loop(client, monkeypatch):
    """Review #17: a long GPX parsed on the event loop stalled the 4 Hz engine."""
    import asyncio

    import opengpx_trainer.app as app_mod
    from tests.test_gpx_workouts import make_gpx

    on_loop = []

    def watched(f):
        def wrapper(*a, **k):
            try:
                asyncio.get_running_loop()
                on_loop.append(f.__name__)
            except RuntimeError:  # a worker thread: no loop running here
                pass
            return f(*a, **k)

        return wrapper

    monkeypatch.setattr(app_mod.Route, "from_gpx", watched(app_mod.Route.from_gpx))
    monkeypatch.setattr(app_mod, "parse_workout", watched(app_mod.parse_workout))
    assert client.post("/api/routes/import", files={"file": ("r.gpx", make_gpx())}).is_success
    assert client.post("/api/workouts/import", files={"file": ("w.zwo", ZWO)}).is_success
    assert on_loop == []


@pytest.mark.parametrize(
    "name,text",
    [
        (
            "empty.erg",
            "[COURSE HEADER]\nMINUTES WATTS\n[END COURSE HEADER]\n[COURSE DATA]\n"
            "[END COURSE DATA]\n",
        ),
        (
            "zero.zwo",
            '<workout_file><name>Zero</name><workout><SteadyState Duration="0" '
            'Power="0.5"/></workout></workout_file>',
        ),
    ],
)
def test_empty_workouts_are_refused(client, name, text):
    """Review #10: stored with duration 0, the ride finished on the first pedal stroke."""
    r = client.post("/api/workouts/import", files={"file": (name, text)})
    assert r.status_code == 422 and "empty" in r.json()["detail"]
    assert client.get("/api/workouts").json() == []


def test_a_stored_empty_workout_cannot_be_ridden(client):
    assert client.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200
    wid = client.st.storage.add_workout({"name": "Old empty one", "steps": []})
    r = client.post("/api/session/start", json={"mode": "erg", "workout_id": wid})
    assert r.status_code == 422 and client.st.session is None


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
        from opengpx_trainer.recording import Sample

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
    from opengpx_trainer.recording import Sample
    from opengpx_trainer.workouts.intervals_icu import IntervalsIcuClient

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


def test_ride_feedback_is_written_to_fit_and_history(client):
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.session_message import SessionMessage

    from opengpx_trainer.recording import Sample

    start_erg(client)
    s = client.st.session
    with client.st.session_lock:
        for i in range(30):
            s.recorder.add(Sample(1.8e9 + i, i + 1.0, 200, 90, 140, 9.0, 9.0 * i))
    rid = client.post("/api/session/stop").json()["saved"]["ride_id"]

    body = {"rpe": 6, "feel": 25, "carbs_g": 50, "water_ml": 375}
    r = client.put(f"/api/rides/{rid}/feedback", json=body)
    assert r.status_code == 200 and r.json() == {"ok": True, "uploaded": False}
    summary = client.get("/api/rides").json()[0]["summary"]
    assert {k: summary[k] for k in body} == body
    path = client.st.storage.get_ride(rid)["fit_path"]
    ses = [
        rec.message
        for rec in FitFile.from_file(path).records
        if isinstance(rec.message, SessionMessage)
    ][0]
    assert (ses.workout_rpe, ses.workout_feel) == (60, 25)
    assert client.put(f"/api/rides/{rid}/feedback", json={"rpe": 0}).status_code == 422
    assert client.put(f"/api/rides/{rid}/feedback", json={"feel": 60}).status_code == 422
    assert client.put("/api/rides/999/feedback", json={"rpe": 5}).status_code == 404


def test_ride_is_saved_without_holding_the_session_lock(client, monkeypatch):
    """Review #9: the FIT write ran on the event loop and under the session lock."""
    import threading
    import time

    from opengpx_trainer.recording import Recorder

    real_write = Recorder.write_fit
    lock_free = []

    def slow_write(self, path, athlete=None, workout_name=None):
        def probe():
            got = client.st.session_lock.acquire(timeout=1)
            lock_free.append(got)
            if got:
                client.st.session_lock.release()

        th = threading.Thread(target=probe)
        th.start()
        th.join()
        time.sleep(0.5)  # meanwhile the engine must keep ticking
        return real_write(self, path, athlete, workout_name)

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

    from opengpx_trainer.app import publish_latest

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


@pytest.mark.parametrize(
    "origin,host,ok",
    [
        (None, "127.0.0.1:8000", True),  # curl, scripts
        ("http://127.0.0.1:8000", "127.0.0.1:8000", True),
        ("http://192.168.1.20:8000", "192.168.1.20:8000", True),  # tablet on the LAN
        ("http://LocalHost:5173", "localhost:5173", True),  # Vite dev proxy keeps the Host
        ("https://evil.example", "127.0.0.1:8000", False),
        ("http://127.0.0.1:9999", "127.0.0.1:8000", False),  # another local app
        ("null", "127.0.0.1:8000", False),  # sandboxed frame, file://
        ("http://127.0.0.1:8000", None, False),
    ],
)
def test_same_origin(origin, host, ok):
    from opengpx_trainer.app import same_origin

    assert same_origin(origin, host) is ok


def test_cross_site_requests_are_refused(client):
    """Review #32: any page could stop the ride or read the telemetry."""
    start_erg(client)
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/session/pause", headers=evil).status_code == 403
    assert client.post("/api/session/stop?save=false", headers=evil).status_code == 403
    assert client.st.session is not None
    assert client.get("/api/profile", headers=evil).status_code == 200  # reads: CORS hides them
    own = {"Origin": "http://testserver"}  # TestClient's Host
    assert client.post("/api/session/pause", headers=own).status_code == 200
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/live", headers=evil):
        pass
    with client.websocket_connect("/ws/live", headers=own) as ws:
        assert "state" in ws.receive_json()


@pytest.mark.parametrize("value,offered", [(None, False), ("1", True), ("0", False)])
def test_simulator_offered_only_when_asked(tmp_path, monkeypatch, value, offered):
    """The Simulator button is for development and demos: hidden unless the app is started
    with --simulator (OPENGPX_TRAINER_SIMULATOR=1); the API stays usable for the tests."""
    monkeypatch.delenv("HOMETRAINER_SIMULATOR", raising=False)
    if value is None:
        monkeypatch.delenv("OPENGPX_TRAINER_SIMULATOR", raising=False)
    else:
        monkeypatch.setenv("OPENGPX_TRAINER_SIMULATOR", value)
    with TestClient(create_app(Storage(tmp_path))) as c:
        with c.websocket_connect("/ws/live") as ws:
            assert ws.receive_json()["simulator_offered"] is offered
        assert c.post("/api/devices/connect", json={"kind": "simulator"}).status_code == 200


def test_a_client_that_stops_reading_does_not_stall_the_engine(client, monkeypatch):
    """Review #11: a sleeping tablet blocked ``await send_json`` in the engine loop, so the
    ride stopped ticking (riding time lost, no samples) until the socket timed out."""
    import asyncio

    from starlette.websockets import WebSocket

    import opengpx_trainer.app as app_mod

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


def test_delete_ride_removes_history_row_and_fit(client):
    from pathlib import Path

    from opengpx_trainer.recording import Sample

    start_erg(client)
    with client.st.session_lock:
        for i in range(30):
            client.st.session.recorder.add(Sample(1.8e9 + i, i + 1.0, 200, 90, 140, 9.0, 9.0 * i))
    rid = client.post("/api/session/stop").json()["saved"]["ride_id"]
    fit = Path(client.st.storage.get_ride(rid)["fit_path"])
    assert fit.exists()
    assert client.delete(f"/api/rides/{rid}").json() == {"ok": True}
    assert not fit.exists() and client.get("/api/rides").json() == []
    assert client.delete(f"/api/rides/{rid}").status_code == 404


def test_delete_ride_leaves_a_fit_outside_the_rides_directory(client, tmp_path):
    outside = tmp_path / "elsewhere.fit"
    outside.write_bytes(b"fit")
    rid = client.st.storage.add_ride("2026-11-22T10:00:00", "erg", "x", {}, str(outside))
    assert client.delete(f"/api/rides/{rid}").status_code == 200
    assert outside.exists()


def test_stop_without_saving_records_nothing(client):
    start_erg(client)
    with client.st.session_lock:
        s = client.st.session
        for _ in range(8):
            s.tick()
    assert client.post("/api/session/stop?save=false").json() == {"saved": None}
    assert client.get("/api/rides").json() == []
    assert not list(client.st.storage.rides_dir.glob("*.fit"))
