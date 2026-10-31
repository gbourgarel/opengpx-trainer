"""Minimal intervals.icu API client.

Auth: HTTP basic with username ``API_KEY`` and your personal API key as password
(intervals.icu > Settings > Developer). Athlete id ``0`` means "the key's owner".
"""

from __future__ import annotations

import datetime as dt

import httpx

from .model import Workout
from .parsers import parse_zwo

BASE_URL = "https://intervals.icu/api/v1"


class IntervalsIcuClient:
    def __init__(self, api_key: str, athlete_id: str = "0", base_url: str = BASE_URL):
        if not api_key:
            raise ValueError("intervals.icu API key is not configured")
        self.athlete_id = athlete_id or "0"
        self._client = httpx.AsyncClient(base_url=base_url, auth=("API_KEY", api_key), timeout=20.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def planned_workouts(self, oldest: dt.date, newest: dt.date) -> list[dict]:
        r = await self._client.get(
            f"/athlete/{self.athlete_id}/events",
            params={
                "oldest": oldest.isoformat(),
                "newest": newest.isoformat(),
                "category": "WORKOUT",
            },
        )
        r.raise_for_status()
        out = []
        for ev in r.json():
            if ev.get("category") != "WORKOUT":
                continue
            out.append(
                {
                    "id": ev["id"],
                    "name": ev.get("name") or "Workout",
                    "date": ev.get("start_date_local"),
                    "type": ev.get("type"),
                    "moving_time_s": ev.get("moving_time"),
                    "load": ev.get("icu_training_load"),
                    "description": ev.get("description") or "",
                }
            )
        return out

    async def download_workout(self, event_id: int | str) -> Workout:
        r = await self._client.get(f"/athlete/{self.athlete_id}/events/{event_id}/download.zwo")
        r.raise_for_status()
        w = parse_zwo(r.text)
        w.source = f"intervals.icu:{event_id}"
        return w

    async def upload_activity(
        self, fit_bytes: bytes, filename: str, name: str | None = None
    ) -> dict:
        params = {"name": name} if name else None
        r = await self._client.post(
            f"/athlete/{self.athlete_id}/activities",
            params=params,
            files={"file": (filename, fit_bytes, "application/octet-stream")},
        )
        r.raise_for_status()
        return r.json()
