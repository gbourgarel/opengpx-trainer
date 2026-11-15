"""Current weather along a route (Open-Meteo: free, no key), for the ride's wind and air.

The route is sampled every ``SAMPLE_EVERY_M`` (at least ``MIN_POINTS``, at most
``MAX_POINTS``, ends included); one request returns the current conditions at every point,
which are averaged into one weather for the whole ride (the user's choice: constant along the
route, but less sensitive to one point than a single sample):

* temperature and relative humidity: arithmetic means;
* wind: the mean of the wind *vectors* (two opposite winds cancel out instead of adding up),
  i.e. speed = |mean vector|, direction = direction of the mean vector.

Forecast wind is the wind 10 m above the ground. At the rider's height it is weaker: with a
neutral logarithmic profile ``u(z) = u_10 ln(z / z0) / ln(10 / z0)``, for z = ``RIDER_HEIGHT_M``
and an open-country roughness length z0 = ``ROUGHNESS_M`` (WMO / Davenport "open": flat
terrain, grass, few obstacles), ``u = 0.60 u_10``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx
import numpy as np

from .gpx.route import Route

API_URL = "https://api.open-meteo.com/v1/forecast"
SAMPLE_EVERY_M = 10_000.0
MIN_POINTS, MAX_POINTS = 3, 10
RIDER_HEIGHT_M = 1.0
ROUGHNESS_M = 0.03
WIND_HEIGHT_FACTOR = math.log(RIDER_HEIGHT_M / ROUGHNESS_M) / math.log(10.0 / ROUGHNESS_M)


@dataclass(frozen=True)
class Weather:
    wind_kmh: float  # at the rider's height
    wind_from_deg: float  # direction it blows from (meteorological convention)
    wind_10m_kmh: float  # as forecast (10 m), averaged
    temperature_c: float
    relative_humidity: float  # 0-1
    points: int


def sample_points(route: Route) -> list[tuple[float, float]]:
    """(lat, lon) every ~10 km along the route, ends included."""
    total = route.total_distance_m
    n = int(min(MAX_POINTS, max(MIN_POINTS, round(total / SAMPLE_EVERY_M) + 1)))
    out = []
    for d in np.linspace(0.0, total, n):
        p = route.point_at(float(d))
        out.append((round(p.lat, 4), round(p.lon, 4)))
    return out


def average(samples: list[dict]) -> Weather:
    """One weather from Open-Meteo's ``current`` blocks (km/h, degrees, %, degC)."""
    if not samples:
        raise ValueError("no weather data")
    # wind vectors pointing where the wind goes to; FROM direction = opposite
    east = north = 0.0
    for s in samples:
        a = math.radians(s["wind_direction_10m"])
        east += -s["wind_speed_10m"] * math.sin(a)
        north += -s["wind_speed_10m"] * math.cos(a)
    east, north = east / len(samples), north / len(samples)
    speed_10m = math.hypot(east, north)
    from_deg = (math.degrees(math.atan2(-east, -north)) + 360.0) % 360.0 if speed_10m > 0 else 0.0
    return Weather(
        wind_kmh=round(speed_10m * WIND_HEIGHT_FACTOR, 1),
        wind_from_deg=round(from_deg),
        wind_10m_kmh=round(speed_10m, 1),
        temperature_c=round(sum(s["temperature_2m"] for s in samples) / len(samples), 1),
        relative_humidity=round(
            sum(s["relative_humidity_2m"] for s in samples) / len(samples) / 100.0, 2
        ),
        points=len(samples),
    )


def current_weather(route: Route, client: httpx.Client | None = None) -> Weather:
    """Current weather averaged along the route (one HTTP request)."""
    pts = sample_points(route)
    params = {
        "latitude": ",".join(str(lat) for lat, _ in pts),
        "longitude": ",".join(str(lon) for _, lon in pts),
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kmh",
    }
    own = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        r = client.get(API_URL, params=params)
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            client.close()
    rows = data if isinstance(data, list) else [data]  # one location: a single object
    return average([row["current"] for row in rows])
