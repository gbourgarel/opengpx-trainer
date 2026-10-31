"""API-level regression tests (code review 2026-10-31)."""

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


def test_reconnect_rebinds_existing_session_to_new_hub(client):
    """Review #1: after Disconnect/Connect the session kept driving the stopped hub."""
    start_erg(client)
    old_hub = client.st.hub
    client.post("/api/devices/disconnect")
    client.post("/api/devices/connect", json={"kind": "simulator"})
    assert client.st.hub is not old_hub
    assert client.st.session.hub is client.st.hub
