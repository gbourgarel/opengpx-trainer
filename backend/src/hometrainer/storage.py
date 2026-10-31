"""SQLite persistence: settings/profile, imported workouts, routes and ride history."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .profile import Profile, ProfileError

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gpx TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    name TEXT NOT NULL,
    duration_s REAL,
    distance_m REAL,
    avg_power_w REAL,
    fit_path TEXT,
    summary TEXT,
    intervals_activity_id TEXT
);
"""


def default_data_dir() -> Path:
    return Path(os.environ.get("HOMETRAINER_DATA", Path.home() / ".hometrainer"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.rides_dir = self.data_dir / "rides"
        self.rides_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.data_dir / "hometrainer.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    # -- profile ------------------------------------------------------------------------
    def load_profile(self) -> Profile:
        row = self._exec("SELECT value FROM settings WHERE key='profile'").fetchone()
        if not row:
            return Profile()
        data = json.loads(row["value"])
        try:
            return Profile.from_dict(data)
        except ProfileError as e:
            # never refuse to start because of a bad stored value: fall back to defaults
            log.warning("Stored profile has invalid fields, using defaults for: %s", e)
            return Profile.from_dict(data, strict=False)

    def save_profile(self, p: Profile) -> None:
        self._exec(
            "INSERT INTO settings(key, value) VALUES('profile', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(p.to_dict()),),
        )

    # -- workouts -----------------------------------------------------------------------
    def add_workout(self, data: dict) -> int:
        cur = self._exec(
            "INSERT INTO workouts(name, source, data, created_at) VALUES(?,?,?,?)",
            (data["name"], data.get("source", ""), json.dumps(data), _now()),
        )
        return int(cur.lastrowid)

    def list_workouts(self) -> list[dict]:
        rows = self._exec("SELECT id, data, created_at FROM workouts ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            out.append({"id": r["id"], "created_at": r["created_at"], **d})
        return out

    def get_workout(self, wid: int) -> dict | None:
        r = self._exec("SELECT data FROM workouts WHERE id=?", (wid,)).fetchone()
        return json.loads(r["data"]) if r else None

    def delete_workout(self, wid: int) -> None:
        self._exec("DELETE FROM workouts WHERE id=?", (wid,))

    # -- routes -------------------------------------------------------------------------
    def add_route(self, name: str, gpx: str, summary: dict) -> int:
        cur = self._exec(
            "INSERT INTO routes(name, gpx, summary, created_at) VALUES(?,?,?,?)",
            (name, gpx, json.dumps(summary), _now()),
        )
        return int(cur.lastrowid)

    def list_routes(self) -> list[dict]:
        rows = self._exec("SELECT id, name, summary, created_at FROM routes ORDER BY id DESC")
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "created_at": r["created_at"],
                **json.loads(r["summary"]),
            }
            for r in rows.fetchall()
        ]

    def get_route_gpx(self, rid: int) -> str | None:
        r = self._exec("SELECT gpx FROM routes WHERE id=?", (rid,)).fetchone()
        return r["gpx"] if r else None

    def delete_route(self, rid: int) -> None:
        self._exec("DELETE FROM routes WHERE id=?", (rid,))

    # -- rides --------------------------------------------------------------------------
    def add_ride(self, started_at: str, mode: str, name: str, summary: dict, fit_path: str) -> int:
        cur = self._exec(
            "INSERT INTO rides(started_at, mode, name, duration_s, distance_m, avg_power_w, "
            "fit_path, summary) VALUES(?,?,?,?,?,?,?,?)",
            (
                started_at,
                mode,
                name,
                summary.get("duration_s"),
                summary.get("distance_m"),
                summary.get("avg_power_w"),
                fit_path,
                json.dumps(summary),
            ),
        )
        return int(cur.lastrowid)

    def list_rides(self) -> list[dict]:
        rows = self._exec("SELECT * FROM rides ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d["summary"] or "{}")
            out.append(d)
        return out

    def get_ride(self, ride_id: int) -> dict | None:
        r = self._exec("SELECT * FROM rides WHERE id=?", (ride_id,)).fetchone()
        return dict(r) if r else None

    def set_ride_intervals_id(self, ride_id: int, activity_id: str) -> None:
        self._exec("UPDATE rides SET intervals_activity_id=? WHERE id=?", (activity_id, ride_id))
