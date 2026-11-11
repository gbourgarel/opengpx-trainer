"""FastAPI application: REST API + live telemetry WebSocket + 4 Hz engine loop."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ant.hub import SensorHub
from .ant.scan import scan_ant
from .ant.simulator import SimulatedHub
from .ble.scan import scan_ble
from .checkpoint import RideCheckpoint, load_checkpoint
from .gpx.route import Route
from .profile import Profile, ProfileError
from .recording import Recorder
from .sensors import MultiHub
from .session import RideSession, choose_power, w_per_kg
from .storage import Storage
from .workouts.intervals_icu import IntervalsIcuClient
from .workouts.model import Workout
from .workouts.parsers import parse_workout

log = logging.getLogger(__name__)
TICK_S = 0.25
# a client that has not taken a message for this long (asleep tablet, dead Wi-Fi) is dropped;
# it reconnects by itself when it wakes up
WS_SEND_TIMEOUT_S = 10.0


def publish_latest(q: asyncio.Queue, msg: dict) -> None:
    """Put ``msg`` in a client's one-slot queue, replacing a message it has not taken yet:
    a slow client gets the latest telemetry, never a backlog, and never slows the engine."""
    with contextlib.suppress(asyncio.QueueEmpty):
        q.get_nowait()
    q.put_nowait(msg)


class HubBusy(RuntimeError):
    pass


class AppState:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.profile = storage.load_profile()
        self.hub: SensorHub | None = None
        self.hub_kind: str | None = None
        self.session: RideSession | None = None
        # live telemetry: one slot per WebSocket client holding the latest message not sent yet
        # (see live()); the engine never waits for a client
        self.clients: dict[WebSocket, asyncio.Queue] = {}
        self.last_ride_id: int | None = None
        self._hub_lock = threading.Lock()
        # Serialises everything that touches the current session: the engine tick (event
        # loop thread) and the sync endpoints (threadpool) used to race, e.g. a ride finishing
        # on its own while "Stop & save" was clicked got saved twice.
        self.session_lock = threading.RLock()
        self._save_lock = threading.Lock()  # one FIT write at a time (see save_session)

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
                # real sensors: each role on ANT+ or Bluetooth, as chosen in the profile
                kind = "devices"
                hub = MultiHub(self.profile)
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

    def scan_ant_devices(self, seconds: float) -> list[dict]:
        """ANT+ scan without interrupting anything: on the connected hub's own node when ANT+
        is in use, otherwise stand-alone on the free stick (holding the hub lock so a
        concurrent connect cannot grab the stick mid-scan)."""
        ant = getattr(self.hub, "ant", None)
        if ant is not None and getattr(ant, "_running", False):
            return ant.scan(seconds)
        if not self._hub_lock.acquire(blocking=False):
            raise HubBusy("A connection is in progress, try again")
        try:
            return scan_ant(seconds)
        finally:
            self._hub_lock.release()

    def _disconnect_locked(self) -> None:
        if self.hub is not None:
            self.hub.stop()
        self.hub, self.hub_kind = None, None

    def save_session(self, s: RideSession) -> dict | None:
        """Write a finished ride's FIT file and history row, at most once per session.

        Blocking (~5 s for a 2 h ride): call it from a worker thread, never the event loop.
        It holds its own save lock, not ``session_lock``, so engine ticks and the other
        endpoints keep running while the file is written. A finished ride records no more
        samples, so it is safe to read them outside the session lock.
        """
        with self._save_lock:
            if s.saved is not None:
                return s.saved
            with self.session_lock:
                s.finish()  # no-op when already finished; guarantees the samples are final
                rec = s.recorder.snapshot()
                # the last seconds too, in case we die during the (long) FIT write
                s.checkpoint_now(time.monotonic(), final=True)
            if not rec.samples:
                return None
            started = s.started_at or dt.datetime.now(dt.UTC)
            s.saved = self._store_ride(rec, started, s.mode, s.name, s.id)
            if s.checkpoint is not None:
                s.checkpoint.discard()
            return s.saved

    def _store_ride(
        self, rec: Recorder, started: dt.datetime, mode: str, name: str, ride_key: str
    ) -> dict:
        fname = f"{started:%Y%m%d-%H%M%S}-{mode}-{ride_key[:6]}.fit"
        path = rec.write_fit(self.storage.rides_dir / fname)
        summary = rec.summary()
        rid = self.storage.add_ride(
            started.isoformat(timespec="seconds"), mode, name, summary, str(path)
        )
        self.last_ride_id = rid
        return {"ride_id": rid, **summary}

    def recover_rides(self) -> list[dict]:
        """Save the rides left unfinished by a crash (checkpoint files) into the history."""
        out = []
        for path in sorted(self.storage.checkpoints_dir.glob("*.jsonl")):
            try:
                header, samples = load_checkpoint(path)
                if samples:
                    started = (
                        dt.datetime.fromisoformat(header["started_at"])
                        if header.get("started_at")
                        else dt.datetime.fromtimestamp(samples[0].timestamp_s, dt.UTC)
                    )
                    saved = self._store_ride(
                        Recorder.from_samples(samples),
                        started,
                        header.get("mode", "ride"),
                        f"{header.get('name', 'Ride')} (recovered)",
                        header.get("session_id") or path.stem,
                    )
                    log.info("Recovered unfinished ride %s as #%s", path.name, saved["ride_id"])
                    out.append(saved)
                path.unlink()
            except Exception:
                log.exception("Cannot recover %s, renamed to .bad", path.name)
                path.replace(path.with_suffix(".bad"))
        return out

    def idle_telemetry(self) -> dict:
        if self.hub is None:
            return {"state": "disconnected"}
        r = self.hub.readings()
        pc = choose_power(r, self.profile.power_source)
        return {
            "state": "idle",
            "power_w": pc.power_w and round(pc.power_w),
            "power_wkg": w_per_kg(pc.power_w, self.profile.rider_mass_kg),
            "rider_mass_kg": self.profile.rider_mass_kg,
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
    # "devices": the real sensors from the profile (ANT+ and/or BLE); "ant" kept as an alias
    kind: Literal["devices", "ant", "simulator"] = "devices"


class StartBody(BaseModel):
    mode: Literal["erg", "gpx"]
    workout_id: int | None = None
    route_id: int | None = None
    # GPX rides: wind speed and the direction it blows from (deg, 0 = north); ignored in ERG
    wind_kmh: float = Field(0.0, ge=0.0, le=150.0)
    wind_from_deg: float = Field(0.0, ge=0.0, le=360.0)


class AdjustBody(BaseModel):
    intensity_pct: float | None = None
    effort_pct: float | None = None
    target_mode: Literal["slope", "manual"] | None = None
    manual_target_w: float | None = None


class StepBody(BaseModel):
    action: Literal["skip", "extend"]
    seconds: float = 60.0  # extend only


def frontend_dir() -> Path | None:
    """The built UI to serve: ``HOMETRAINER_FRONTEND``, else the copy packaged in the wheel
    (``hometrainer/web``, see ``hatch_build.py``), else ``frontend/dist`` of the repository."""
    env = os.environ.get("HOMETRAINER_FRONTEND")
    here = Path(__file__).resolve().parent
    candidates = [Path(env)] if env else [here / "web", here.parents[2] / "frontend" / "dist"]
    return next((d for d in candidates if d.is_dir()), None)


def create_app(storage: Storage | None = None) -> FastAPI:
    st = AppState(storage or Storage())

    saving: set[asyncio.Task] = set()  # strong refs to the background FIT writes
    upload_lock = asyncio.Lock()  # one intervals.icu upload at a time: never the same ride twice

    def save_in_background(s: RideSession) -> None:
        # once per session; the write runs in a worker thread so ticks keep coming
        if s.save_started:
            return
        s.save_started = True
        task = asyncio.create_task(asyncio.to_thread(st.save_session, s))
        saving.add(task)

        def done(t: asyncio.Task) -> None:
            saving.discard(t)
            if not t.cancelled() and t.exception() is not None:
                log.error("saving the ride failed", exc_info=t.exception())

        task.add_done_callback(done)

    async def engine_loop():
        while True:
            try:
                with st.session_lock:
                    s = st.session  # read once: stop() may clear it from another thread
                    if s is not None and st.hub is not None:
                        tel = s.tick()
                        s.checkpoint_now(time.monotonic())
                        if tel["state"] == "finished":
                            tel["saved"] = s.saved  # None while the FIT is being written
                            save_in_background(s)
                    else:
                        tel = st.idle_telemetry()
                tel["devices"] = st.hub.status() if st.hub else {}
                tel["hub"] = st.hub_kind
                if isinstance(st.hub, SimulatedHub):
                    tel["sim"] = asdict(st.hub.settings)
                for q in list(st.clients.values()):
                    publish_latest(q, tel)
            except Exception:
                log.exception("engine tick failed")
            await asyncio.sleep(TICK_S)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await asyncio.to_thread(st.recover_rides)  # rides left by a crash -> history
        except Exception:
            log.exception("recovering unfinished rides failed")
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
        dev_keys = tuple(
            f"{role}_{what}"
            for role in ("trainer", "power_meter", "heart_rate")
            for what in ("transport", "device_number", "ble_id")
        )
        try:
            p = Profile.from_dict(current)  # validates types and bounds of every field
        except ProfileError as e:
            raise HTTPException(422, f"Invalid profile: {e}") from e
        devices_changed = any(getattr(p, k) != getattr(st.profile, k) for k in dev_keys)
        st.profile = p
        st.storage.save_profile(p)
        out = p.to_dict(redact_secrets=True)
        # apply the new device choice right away when connected and no ride is in progress
        riding = st.session is not None and st.session.state in ("running", "paused")
        if devices_changed and st.hub_kind == "devices":
            if riding:
                out["devices_note"] = "Devices saved; reconnect after the ride to apply."
            else:
                try:
                    st.connect("devices")
                    out["devices_note"] = "Sensors reconnected with the new devices."
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
        return {"hub": st.hub_kind, "warnings": getattr(st.hub, "warnings", [])}

    @app.post("/api/devices/scan")
    async def scan(seconds: float = 6.0):
        """List ANT+ and BLE sensors in range, without disconnecting the current sensors."""
        seconds = max(2.0, min(seconds, 20.0))
        with st.session_lock:
            if st.session is not None and st.session.state in ("running", "paused"):
                raise HTTPException(409, "Not during a ride")
        result: dict = {"ant": [], "ble": [], "errors": {}}

        async def ant_part():
            try:
                result["ant"] = await asyncio.to_thread(st.scan_ant_devices, seconds)
            except Exception as e:
                result["errors"]["ant"] = str(e)

        async def ble_part():
            try:
                result["ble"] = await scan_ble(seconds)
            except Exception as e:
                result["errors"]["ble"] = str(e)

        await asyncio.gather(ant_part(), ble_part())
        return result

    @app.post("/api/devices/disconnect")
    def disconnect():
        # Not during a ride: without a hub the engine no longer ticks the session, so the ride
        # vanished from the screen (no Stop button), stopped recording and the trainer was no
        # longer driven. Stop the ride first (it is saved), then disconnect.
        with st.session_lock:
            if st.session is not None and st.session.state in ("ready", "running", "paused"):
                raise HTTPException(409, "A ride is in progress: stop it first")
        st.disconnect()  # outside the lock: stopping the hub can take seconds (BLE)
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

    @app.get("/api/workouts/{wid}")
    def get_workout(wid: int):
        d = st.storage.get_workout(wid)
        if d is None:
            raise HTTPException(404, "Workout not found")
        return {"id": wid, **d}

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
    # Every endpoint below holds st.session_lock while it reads or changes the session, so it
    # never interleaves with an engine tick (which runs on the event loop thread).
    @app.post("/api/session/start")
    def start_session(body: StartBody):
        workout = route = None
        # ERG needs a workout; GPX needs a route and may also follow a workout (mixed mode)
        if body.mode == "erg" or body.workout_id is not None:
            d = st.storage.get_workout(body.workout_id or -1)
            if d is None:
                raise HTTPException(404, "Workout not found")
            workout = Workout.from_dict(d)
        if body.mode == "gpx":
            route = load_route(body.route_id or -1)  # parsing a GPX: done outside the lock
        with st.session_lock:
            if st.hub is None:
                raise HTTPException(409, "Connect sensors first")
            if st.session is not None and st.session.state in ("running", "paused"):
                raise HTTPException(409, "A session is already in progress")
            st.session = RideSession(
                st.hub,
                st.profile,
                body.mode,
                workout=workout,
                route=route,
                workout_id=body.workout_id if workout else None,
                route_id=body.route_id if route else None,
                wind_kmh=body.wind_kmh,
                wind_from_deg=body.wind_from_deg,
            )
            st.session.checkpoint = RideCheckpoint(
                st.storage.checkpoints_dir / f"{st.session.id}.jsonl"
            )
            return {"ok": True, "name": st.session.name, "session_id": st.session.id}

    def require_session() -> RideSession:
        if st.session is None:
            raise HTTPException(409, "No session")
        return st.session

    @app.post("/api/session/pause")
    def pause():
        with st.session_lock:
            require_session().pause()
        return {"ok": True}

    @app.post("/api/session/resume")
    def resume():
        with st.session_lock:
            require_session().resume()
        return {"ok": True}

    @app.post("/api/session/adjust")
    def adjust(body: AdjustBody):
        with st.session_lock:
            s = require_session()
            try:
                s.adjust(
                    body.intensity_pct,
                    body.effort_pct,
                    body.target_mode,
                    body.manual_target_w,
                )
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            return {
                "intensity_pct": s.intensity_pct,
                "effort_pct": s.effort_pct,
                "target_mode": s.target_mode,
                "manual_target_w": s.manual_target_w,
            }

    @app.post("/api/session/step")
    def workout_step(body: StepBody):
        """Skip the current workout step, or extend it by ``seconds``."""
        with st.session_lock:
            s = require_session()
            try:
                if body.action == "skip":
                    s.skip_step()
                else:
                    s.extend_step(body.seconds)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            return session_workout_locked(s)

    def session_workout_locked(s: RideSession) -> dict:
        if s.workout is None:
            raise HTTPException(404, "No workout in this ride")
        return {"id": s.workout_id, "workout_rev": s.workout_rev, **s.workout.to_dict()}

    @app.get("/api/session/workout")
    def session_workout():
        """The ride's workout as edited by the rider (skipped / extended steps)."""
        with st.session_lock:
            return session_workout_locked(require_session())

    @app.post("/api/session/stop")
    def stop(save: bool = True):
        with st.session_lock:
            s = require_session()
            s.finish()
            st.session = None
            if st.hub:
                st.hub.set_basic_resistance(0)
        # Written outside the session lock (this sync endpoint runs in the threadpool, not on
        # the event loop). save_session is idempotent: a ride that finished on its own and is
        # being / was saved by the engine waits for that save and is not written twice.
        if save:
            saved = st.save_session(s)
        else:
            saved = s.saved
            if s.checkpoint is not None and saved is None:
                s.checkpoint.discard()  # discarded on purpose: nothing to recover
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
        """Send the ride's FIT file to intervals.icu, once: a ride already uploaded (another
        click, another device) returns its activity id without sending it again."""
        async with upload_lock:
            r = st.storage.get_ride(ride_id)
            if not r or not r["fit_path"] or not Path(r["fit_path"]).exists():
                raise HTTPException(404, "Ride not found")
            if r["intervals_activity_id"]:
                return {"intervals_activity_id": r["intervals_activity_id"], "already": True}
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
            return {"intervals_activity_id": aid, "already": False}

    # -- live telemetry -----------------------------------------------------------------
    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        st.clients[ws] = q

        async def receive():
            while True:
                await ws.receive_text()  # keep-alive; client messages are ignored

        async def send():
            # A sleeping client stops reading: its send blocks once the TCP buffer is full.
            # Only this task waits (the engine just replaces the queued message), and the
            # client is dropped after WS_SEND_TIMEOUT_S.
            while True:
                msg = await q.get()
                await asyncio.wait_for(ws.send_json(msg), WS_SEND_TIMEOUT_S)

        receiver, sender = asyncio.create_task(receive()), asyncio.create_task(send())
        try:
            # the first task to end (disconnect, send error or timeout) ends the connection
            await asyncio.wait((receiver, sender), return_when=asyncio.FIRST_COMPLETED)
            if sender.done():
                # stalled or failed client: close our side; it reconnects when it wakes up
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ws.close(), 1.0)
        finally:
            st.clients.pop(ws, None)
            receiver.cancel()
            sender.cancel()

    # -- built frontend (production) ----------------------------------------------------
    dist = frontend_dir()
    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
