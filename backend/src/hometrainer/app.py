"""FastAPI application: REST API + live telemetry WebSocket + 4 Hz engine loop."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ant.hub import SensorHub
from .ant.simulator import SimulatedHub
from .gpx.route import Route
from .profile import Profile
from .session import RideSession, choose_power
from .storage import Storage
from .workouts.intervals_icu import IntervalsIcuClient
from .workouts.model import Workout
from .workouts.parsers import parse_workout

log = logging.getLogger(__name__)
TICK_S = 0.25


class HubBusy(RuntimeError):
    pass


class AppState:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.profile = storage.load_profile()
        self.hub: SensorHub | None = None
        self.hub_kind: str | None = None
        self.session: RideSession | None = None
        self.clients: set[WebSocket] = set()
        self.last_ride_id: int | None = None
        self._hub_lock = threading.Lock()

    def connect(self, kind: str) -> None:
        # One connection attempt at a time: two concurrent requests (double click) used to
        # open two ANT nodes on the same USB stick and leak a reader thread spinning on errors.
        if not self._hub_lock.acquire(blocking=False):
            raise HubBusy("A connection is already in progress")
        try:
            self._disconnect_locked()
            if kind == "simulator":
                hub: SensorHub = SimulatedHub()
            else:
                from .ant.ant_hub import AntHub

                p = self.profile
                hub = AntHub(
                    trainer_id=p.trainer_device_number,
                    power_meter_id=p.power_meter_device_number,
                    heart_rate_id=p.heart_rate_device_number,
                )
            try:
                hub.start()
            except Exception:
                hub.stop()  # release the USB device if start failed half-way
                raise
            self.hub, self.hub_kind = hub, kind
            if self.session is not None:
                # keep an existing ride driving the trainer through the *new* hub; otherwise
                # it would keep reading/commanding the stopped one
                self.session.attach_hub(hub)
        finally:
            self._hub_lock.release()

    def disconnect(self) -> None:
        with self._hub_lock:
            self._disconnect_locked()

    def _disconnect_locked(self) -> None:
        if self.hub is not None:
            self.hub.stop()
        self.hub, self.hub_kind = None, None

    def save_session(self) -> dict | None:
        s = self.session
        if s is None or not s.recorder.samples:
            return None
        started = s.started_at or dt.datetime.now(dt.UTC)
        fname = f"{started:%Y%m%d-%H%M%S}-{s.mode}.fit"
        path = s.recorder.write_fit(self.storage.rides_dir / fname)
        summary = s.recorder.summary()
        rid = self.storage.add_ride(
            started.isoformat(timespec="seconds"), s.mode, s.name, summary, str(path)
        )
        self.last_ride_id = rid
        return {"ride_id": rid, **summary}

    def idle_telemetry(self) -> dict:
        if self.hub is None:
            return {"state": "disconnected"}
        r = self.hub.readings()
        pc = choose_power(r, self.profile.power_source)
        return {
            "state": "idle",
            "power_w": pc.power_w and round(pc.power_w),
            "power_source": pc.source,
            "cadence_source": pc.cadence_source,
            "trainer_power_w": r.trainer_power_w and round(r.trainer_power_w),
            "pm_power_w": r.pm_power_w and round(r.pm_power_w),
            "cadence_rpm": pc.cadence_rpm and round(pc.cadence_rpm),
            "heart_rate_bpm": r.heart_rate_bpm and round(r.heart_rate_bpm),
        }


# --------------------------------------------------------------------------------------
# request bodies
class ConnectBody(BaseModel):
    kind: Literal["ant", "simulator"] = "ant"


class StartBody(BaseModel):
    mode: Literal["erg", "gpx"]
    workout_id: int | None = None
    route_id: int | None = None


class AdjustBody(BaseModel):
    intensity_pct: float | None = None
    effort_pct: float | None = None
    difficulty_pct: float | None = None
    target_mode: Literal["slope", "manual"] | None = None
    manual_target_w: float | None = None


def create_app(storage: Storage | None = None) -> FastAPI:
    st = AppState(storage or Storage())

    async def engine_loop():
        while True:
            try:
                if st.session is not None and st.hub is not None:
                    was_finished = st.session.state == "finished"
                    tel = st.session.tick()
                    if tel["state"] == "finished" and not was_finished:
                        tel["saved"] = st.save_session()
                else:
                    tel = st.idle_telemetry()
                tel["devices"] = st.hub.status() if st.hub else {}
                tel["hub"] = st.hub_kind
                if isinstance(st.hub, SimulatedHub):
                    tel["sim"] = asdict(st.hub.settings)
                dead = []
                for ws in list(st.clients):
                    try:
                        await ws.send_json(tel)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    st.clients.discard(ws)
            except Exception:
                log.exception("engine tick failed")
            await asyncio.sleep(TICK_S)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(engine_loop())
        try:
            yield
        finally:
            task.cancel()
            st.disconnect()
            st.storage.close()

    app = FastAPI(title="Home Trainer", lifespan=lifespan)
    app.state.st = st

    # -- profile ------------------------------------------------------------------------
    @app.get("/api/profile")
    def get_profile():
        return st.profile.to_dict(redact_secrets=True)

    @app.put("/api/profile")
    def put_profile(body: dict):
        current = st.profile.to_dict()
        if not body.get("intervals_api_key"):
            body.pop("intervals_api_key", None)  # keep stored key unless a new one is sent
        current.update(body)
        dev_keys = (
            "trainer_device_number",
            "power_meter_device_number",
            "heart_rate_device_number",
        )
        for k in dev_keys:
            v = current.get(k)
            if v in (None, "", 0):
                current[k] = None
            elif not (isinstance(v, int | float) and float(v).is_integer() and 1 <= v <= 65535):
                raise HTTPException(422, f"{k} must be an ANT+ device number (1-65535) or empty")
            else:
                current[k] = int(v)
        try:
            p = Profile.from_dict(current)
            p.grade_power_curve()  # validate
        except (TypeError, ValueError) as e:
            raise HTTPException(422, str(e)) from e
        devices_changed = any(getattr(p, k) != getattr(st.profile, k) for k in dev_keys)
        st.profile = p
        st.storage.save_profile(p)
        out = p.to_dict(redact_secrets=True)
        # apply new pairing right away when connected over ANT+ and no ride is in progress
        riding = st.session is not None and st.session.state in ("running", "paused")
        if devices_changed and st.hub_kind == "ant":
            if riding:
                out["devices_note"] = "Device numbers saved; reconnect after the ride to apply."
            else:
                try:
                    st.connect("ant")
                    out["devices_note"] = "ANT+ reconnected with the new device numbers."
                except Exception as e:
                    out["devices_note"] = f"Saved, but reconnecting failed: {e}"
        return out

    # -- devices ------------------------------------------------------------------------
    @app.post("/api/devices/connect")
    def connect(body: ConnectBody):
        try:
            st.connect(body.kind)
        except HubBusy as e:
            raise HTTPException(409, str(e)) from e
        except Exception as e:
            log.exception("Connecting %s failed", body.kind)
            raise HTTPException(503, str(e)) from e
        return {"hub": st.hub_kind}

    @app.post("/api/devices/disconnect")
    def disconnect():
        st.disconnect()
        return {"hub": None}

    @app.get("/api/devices")
    def devices():
        return {"hub": st.hub_kind, "devices": st.hub.status() if st.hub else {}}

    # -- simulator (fake power input) -----------------------------------------------------
    def require_sim() -> SimulatedHub:
        if not isinstance(st.hub, SimulatedHub):
            raise HTTPException(409, "Simulator is not the connected hub")
        return st.hub

    @app.get("/api/simulator")
    def get_sim():
        return asdict(require_sim().settings)

    @app.put("/api/simulator")
    def put_sim(body: dict):
        try:
            return asdict(require_sim().update_settings(**body))
        except (TypeError, ValueError) as e:
            raise HTTPException(422, str(e)) from e

    # -- workouts -----------------------------------------------------------------------
    @app.get("/api/workouts")
    def list_workouts():
        return st.storage.list_workouts()

    @app.post("/api/workouts/import")
    async def import_workout(file: UploadFile = File(...)):
        text = (await file.read()).decode("utf-8", errors="replace")
        try:
            w = parse_workout(text, file.filename or "workout.zwo")
        except Exception as e:
            raise HTTPException(422, f"Cannot parse workout: {e}") from e
        wid = st.storage.add_workout(w.to_dict())
        return {"id": wid, **w.to_dict()}

    @app.delete("/api/workouts/{wid}")
    def delete_workout(wid: int):
        st.storage.delete_workout(wid)
        return {"ok": True}

    def intervals_client() -> IntervalsIcuClient:
        try:
            return IntervalsIcuClient(st.profile.intervals_api_key, st.profile.intervals_athlete_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/intervals/planned")
    async def intervals_planned(days_back: int = 1, days_ahead: int = 7):
        c = intervals_client()
        today = dt.date.today()
        try:
            return await c.planned_workouts(
                today - dt.timedelta(days=days_back), today + dt.timedelta(days=days_ahead)
            )
        except Exception as e:
            raise HTTPException(502, f"intervals.icu error: {e}") from e
        finally:
            await c.aclose()

    @app.post("/api/intervals/import/{event_id}")
    async def intervals_import(event_id: str):
        c = intervals_client()
        try:
            w = await c.download_workout(event_id)
        except Exception as e:
            raise HTTPException(502, f"intervals.icu error: {e}") from e
        finally:
            await c.aclose()
        wid = st.storage.add_workout(w.to_dict())
        return {"id": wid, **w.to_dict()}

    # -- routes -------------------------------------------------------------------------
    @app.get("/api/routes")
    def list_routes():
        return st.storage.list_routes()

    @app.post("/api/routes/import")
    async def import_route(file: UploadFile = File(...)):
        text = (await file.read()).decode("utf-8", errors="replace")
        try:
            route = Route.from_gpx(text)
        except Exception as e:
            raise HTTPException(422, f"Cannot parse GPX: {e}") from e
        if route.name == "Route" and file.filename:
            route.name = Path(file.filename).stem
        rid = st.storage.add_route(route.name, text, route.summary())
        return {"id": rid, **route.summary()}

    def load_route(rid: int) -> Route:
        gpx = st.storage.get_route_gpx(rid)
        if gpx is None:
            raise HTTPException(404, "Route not found")
        return Route.from_gpx(gpx)

    @app.get("/api/routes/{rid}")
    def get_route(rid: int):
        r = load_route(rid)
        return {"id": rid, **r.summary(), **r.geometry()}

    @app.delete("/api/routes/{rid}")
    def delete_route(rid: int):
        st.storage.delete_route(rid)
        return {"ok": True}

    # -- session ------------------------------------------------------------------------
    @app.post("/api/session/start")
    def start_session(body: StartBody):
        if st.hub is None:
            raise HTTPException(409, "Connect sensors first")
        if st.session is not None and st.session.state in ("running", "paused"):
            raise HTTPException(409, "A session is already in progress")
        workout = route = None
        if body.mode == "erg":
            d = st.storage.get_workout(body.workout_id or -1)
            if d is None:
                raise HTTPException(404, "Workout not found")
            workout = Workout.from_dict(d)
        else:
            route = load_route(body.route_id or -1)
        st.session = RideSession(st.hub, st.profile, body.mode, workout=workout, route=route)
        return {"ok": True, "name": st.session.name}

    def require_session() -> RideSession:
        if st.session is None:
            raise HTTPException(409, "No session")
        return st.session

    @app.post("/api/session/pause")
    def pause():
        require_session().pause()
        return {"ok": True}

    @app.post("/api/session/resume")
    def resume():
        require_session().resume()
        return {"ok": True}

    @app.post("/api/session/adjust")
    def adjust(body: AdjustBody):
        s = require_session()
        try:
            s.adjust(
                body.intensity_pct,
                body.effort_pct,
                body.difficulty_pct,
                body.target_mode,
                body.manual_target_w,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {
            "intensity_pct": s.intensity_pct,
            "effort_pct": s.effort_pct,
            "difficulty_pct": s.difficulty_pct,
            "target_mode": s.target_mode,
            "manual_target_w": s.manual_target_w,
        }

    @app.post("/api/session/stop")
    def stop(save: bool = True):
        s = require_session()
        already = s.state == "finished"
        s.finish()
        saved = None if (already or not save) else st.save_session()
        st.session = None
        if st.hub:
            st.hub.set_basic_resistance(0)
        return {"saved": saved}

    # -- rides --------------------------------------------------------------------------
    @app.get("/api/rides")
    def rides():
        return st.storage.list_rides()

    @app.get("/api/rides/{ride_id}/fit")
    def ride_fit(ride_id: int):
        r = st.storage.get_ride(ride_id)
        if not r or not r["fit_path"] or not Path(r["fit_path"]).exists():
            raise HTTPException(404, "FIT file not found")
        return FileResponse(
            r["fit_path"], media_type="application/octet-stream", filename=Path(r["fit_path"]).name
        )

    @app.post("/api/rides/{ride_id}/upload")
    async def ride_upload(ride_id: int):
        r = st.storage.get_ride(ride_id)
        if not r or not r["fit_path"]:
            raise HTTPException(404, "Ride not found")
        c = intervals_client()
        try:
            res = await c.upload_activity(
                Path(r["fit_path"]).read_bytes(), Path(r["fit_path"]).name, r["name"]
            )
        except Exception as e:
            raise HTTPException(502, f"intervals.icu error: {e}") from e
        finally:
            await c.aclose()
        aid = str(res.get("id", ""))
        st.storage.set_ride_intervals_id(ride_id, aid)
        return {"intervals_activity_id": aid}

    # -- live telemetry -----------------------------------------------------------------
    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        await ws.accept()
        st.clients.add(ws)
        try:
            while True:
                await ws.receive_text()  # keep-alive; client messages are ignored
        except WebSocketDisconnect:
            st.clients.discard(ws)

    # -- built frontend (production) ----------------------------------------------------
    dist = Path(
        os.environ.get(
            "HOMETRAINER_FRONTEND", Path(__file__).resolve().parents[3] / "frontend" / "dist"
        )
    )
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
