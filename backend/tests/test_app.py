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


def test_reconnect_rebinds_existing_session_to_new_hub(client):
    """Review #1: after Disconnect/Connect the session kept driving the stopped hub."""
    start_erg(client)
    old_hub = client.st.hub
    client.post("/api/devices/disconnect")
    client.post("/api/devices/connect", json={"kind": "simulator"})
    assert client.st.hub is not old_hub
    assert client.st.session.hub is client.st.hub
