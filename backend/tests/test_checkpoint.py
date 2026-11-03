"""Crash-safe checkpoint of the ride in progress (roadmap: ride robustness)."""

import datetime as dt

from fastapi.testclient import TestClient

from hometrainer.app import create_app
from hometrainer.checkpoint import RideCheckpoint, load_checkpoint
from hometrainer.recording import Sample
from hometrainer.storage import Storage
from tests.test_app import start_erg

HEADER = {
    "session_id": "abcdef123456",
    "mode": "erg",
    "name": "Sweet spot",
    "started_at": "2026-11-03T08:00:00+00:00",
}


def samples(n, t0=1.8e9):
    return [
        Sample(t0 + i, float(i), 200.0, 90.0, 140.0, 9.0, 9.0 * i, target_w=210.0) for i in range(n)
    ]


def test_appends_every_interval_and_holds_back_the_open_second(tmp_path):
    cp = RideCheckpoint(tmp_path / "r.jsonl", every_s=30)
    s = samples(10)
    cp.update(HEADER, s[:5], now=0.0)
    header, got = load_checkpoint(cp.path)
    assert header["name"] == "Sweet spot"
    assert got == s[:4]  # the last sample may still be replaced by a later tick
    cp.update(HEADER, s, now=10.0)  # too early: nothing written
    assert len(load_checkpoint(cp.path)[1]) == 4
    cp.update(HEADER, s, now=31.0)
    assert load_checkpoint(cp.path)[1] == s[:9]
    cp.update(HEADER, s, now=32.0, final=True)
    assert load_checkpoint(cp.path)[1] == s  # header written once, no duplicates
    cp.discard()
    assert not cp.path.exists()


def test_line_cut_short_by_a_crash_is_ignored(tmp_path):
    cp = RideCheckpoint(tmp_path / "r.jsonl")
    cp.update(HEADER, samples(5), now=0.0, final=True)
    with open(cp.path, "a") as f:
        f.write('{"timestamp_s": 1800000005.0, "elaps')
    assert len(load_checkpoint(cp.path)[1]) == 5


def test_unfinished_ride_is_saved_to_history_at_startup(tmp_path):
    storage = Storage(tmp_path)
    cp = RideCheckpoint(storage.checkpoints_dir / "abcdef123456.jsonl")
    cp.update(HEADER, samples(120), now=0.0, final=True)
    (storage.checkpoints_dir / "junk.jsonl").write_text("not json\n")
    storage.close()

    with TestClient(create_app(Storage(tmp_path))) as c:
        rides = c.get("/api/rides").json()
    assert len(rides) == 1
    r = rides[0]
    assert r["name"] == "Sweet spot (recovered)" and r["mode"] == "erg"
    assert r["duration_s"] == 119 and r["avg_power_w"] == 200
    assert dt.datetime.fromisoformat(r["started_at"]).hour == 8
    left = sorted(p.name for p in (tmp_path / "checkpoints").iterdir())
    assert left == ["junk.bad"]  # the recovered file is gone, the unreadable one set aside


def _ride_with_samples(c):
    start_erg(c)
    s = c.st.session
    with c.st.session_lock:
        s.started_at = dt.datetime.now(dt.UTC)
        for smp in samples(60):
            s.recorder.add(smp)
        s.checkpoint_now(0.0, final=True)
    assert s.checkpoint.path.exists()
    return s


def test_checkpoint_removed_once_the_ride_is_saved(tmp_path):
    with TestClient(create_app(Storage(tmp_path))) as c:
        c.st = c.app.state.st
        s = _ride_with_samples(c)
        assert c.post("/api/session/stop").json()["saved"]["ride_id"]
        assert not s.checkpoint.path.exists()


def test_checkpoint_removed_when_the_ride_is_discarded(tmp_path):
    with TestClient(create_app(Storage(tmp_path))) as c:
        c.st = c.app.state.st
        s = _ride_with_samples(c)
        assert c.post("/api/session/stop?save=false").json()["saved"] is None
        assert not s.checkpoint.path.exists()
        assert c.get("/api/rides").json() == []
