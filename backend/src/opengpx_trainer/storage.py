"""SQLite persistence: settings/profile, imported workouts, routes and ride history."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .envvars import env
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


DATA_DIR_NAME = ".opengpx-trainer"
DB_NAME = "opengpx-trainer.db"
# names used before the app was renamed from "Home Trainer" (2026-11)
FORMER_DATA_DIR_NAME = ".hometrainer"
FORMER_DB_NAME = "hometrainer.db"


def default_data_dir(home: Path | None = None) -> Path:
    """``OPENGPX_TRAINER_DATA`` (or the former ``HOMETRAINER_DATA``), else
    ``~/.opengpx-trainer``. A ``~/.hometrainer`` left by the app's former name is moved there
    the first time."""
    custom = env("DATA")
    if custom:
        return Path(custom)
    home = home or Path.home()
    data_dir, former = home / DATA_DIR_NAME, home / FORMER_DATA_DIR_NAME
    if not data_dir.exists() and former.is_dir():
        former.rename(data_dir)
        log.info("Data moved from %s to %s (the app was renamed)", former, data_dir)
    return data_dir


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.rides_dir = self.data_dir / "rides"
        self.rides_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir = self.data_dir / "checkpoints"  # rides in progress (crash-safe)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        db_path, former_db = self.data_dir / DB_NAME, self.data_dir / FORMER_DB_NAME
        if not db_path.exists() and former_db.is_file():
            former_db.rename(db_path)
            log.info("Database renamed from %s to %s", former_db.name, db_path.name)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._migrate()
        self._relocate_fit_files()
        self._db.commit()

    def _migrate(self) -> None:
        """Columns added after the first release (CREATE TABLE IF NOT EXISTS does not add
        them to an existing database)."""
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(rides)")}
        if "session_id" not in cols:
            # the ride session a row comes from: a checkpoint of a ride already saved (crash
            # between the save and the checkpoint removal) is then not saved twice
            self._db.execute("ALTER TABLE rides ADD COLUMN session_id TEXT")

    def _relocate_fit_files(self) -> None:
        """Rides store the absolute path of their FIT file: after the data directory was moved
        (renamed app, or moved by hand), point the rows whose file is gone to the file of the
        same name in ``rides/``, when there is one."""
        rows = self._db.execute("SELECT id, fit_path FROM rides WHERE fit_path IS NOT NULL")
        for r in rows.fetchall():
            old = Path(r["fit_path"])
            moved = self.rides_dir / old.name
            if not old.exists() and moved.is_file():
                self._db.execute("UPDATE rides SET fit_path=? WHERE id=?", (str(moved), r["id"]))

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
    def add_ride(
        self,
        started_at: str,
        mode: str,
        name: str,
        summary: dict,
        fit_path: str,
        session_id: str | None = None,
    ) -> int:
        cur = self._exec(
            "INSERT INTO rides(started_at, mode, name, duration_s, distance_m, avg_power_w, "
            "fit_path, summary, session_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                started_at,
                mode,
                name,
                summary.get("duration_s"),
                summary.get("distance_m"),
                summary.get("avg_power_w"),
                fit_path,
                json.dumps(summary),
                session_id,
            ),
        )
        return int(cur.lastrowid)

    def ride_for_session(self, session_id: str) -> dict | None:
        r = self._exec("SELECT * FROM rides WHERE session_id=?", (session_id,)).fetchone()
        return dict(r) if r else None

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

    def set_ride_feedback(
        self,
        ride_id: int,
        rpe: int | None,
        feel: int | None,
        carbs_g: int | None = None,
        water_ml: int | None = None,
    ) -> None:
        """What the rider told after a ride (RPE, feel, carbohydrates, water), kept in its
        summary (shown with the history)."""
        r = self.get_ride(ride_id)
        if r is None:
            return
        summary = json.loads(r["summary"] or "{}")
        summary.update(rpe=rpe, feel=feel, carbs_g=carbs_g, water_ml=water_ml)
        self._exec("UPDATE rides SET summary=? WHERE id=?", (json.dumps(summary), ride_id))

    def set_ride_intervals_id(self, ride_id: int, activity_id: str) -> None:
        self._exec("UPDATE rides SET intervals_activity_id=? WHERE id=?", (activity_id, ride_id))
