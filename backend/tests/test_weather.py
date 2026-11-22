"""Current weather along a route (Open-Meteo), averaged; never calls the real service."""

import math

import httpx
import pytest

from opengpx_trainer.gpx.route import Route
from opengpx_trainer.weather import (
    WIND_HEIGHT_FACTOR,
    average,
    current_weather,
    sample_points,
)
from tests.test_gpx_workouts import make_gpx


def cur(speed, from_deg, temp=20.0, rh=50):
    return {
        "wind_speed_10m": speed,
        "wind_direction_10m": from_deg,
        "temperature_2m": temp,
        "relative_humidity_2m": rh,
    }


def test_wind_reduced_to_rider_height_by_the_log_profile():
    # u(1 m) / u(10 m) = ln(1 / 0.03) / ln(10 / 0.03) for open country
    assert pytest.approx(math.log(1 / 0.03) / math.log(10 / 0.03)) == WIND_HEIGHT_FACTOR
    assert pytest.approx(0.60, abs=0.01) == WIND_HEIGHT_FACTOR
    w = average([cur(20, 270)])
    assert (w.wind_10m_kmh, w.wind_kmh, w.wind_from_deg) == (
        20,
        round(20 * WIND_HEIGHT_FACTOR, 1),
        270,
    )


def test_average_of_wind_vectors_and_of_the_air():
    # from the north at 10 and from the east at 10: 7.07 from the north-east
    w = average([cur(10, 0, 18, 60), cur(10, 90, 22, 80)])
    assert w.wind_10m_kmh == pytest.approx(7.1, abs=0.05)
    assert w.wind_from_deg == 45
    assert (w.temperature_c, w.relative_humidity, w.points) == (20.0, 0.7, 2)
    # opposite winds cancel out instead of adding up
    assert average([cur(10, 0), cur(10, 180)]).wind_10m_kmh == pytest.approx(0, abs=0.05)
    # around north: 350 and 10 average to 0, not 180
    assert average([cur(10, 350), cur(10, 10)]).wind_from_deg in (0, 360)


def test_points_every_10_km_ends_included():
    short = Route.from_gpx(make_gpx(n=200))  # 2.2 km: the minimum, 3 points
    assert len(sample_points(short)) == 3
    long = Route.from_gpx(make_gpx(n=4000, step_deg=0.0003))  # ~133 km: capped at 10
    pts = sample_points(long)
    assert len(pts) == 10
    assert pts[0][0] == pytest.approx(45.0, abs=1e-3)


def test_one_request_for_all_the_points():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        n = len(request.url.params["latitude"].split(","))
        return httpx.Response(200, json=[{"current": cur(12, 200, 15, 70)} for _ in range(n)])

    route = Route.from_gpx(make_gpx(n=200))
    w = current_weather(route, httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(seen) == 1 and seen[0].url.host == "api.open-meteo.com"
    assert "wind_speed_10m" in seen[0].url.params["current"]
    assert seen[0].url.params["wind_speed_unit"] == "kmh"
    assert (w.points, w.wind_from_deg, w.temperature_c, w.relative_humidity) == (3, 200, 15.0, 0.7)
