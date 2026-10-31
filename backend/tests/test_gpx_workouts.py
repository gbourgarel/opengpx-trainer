import math

import pytest

from hometrainer.gpx.route import Route
from hometrainer.workouts.parsers import parse_erg_mrc, parse_zwo


def make_gpx(n=200, step_deg=0.0001, grade=0.05, noise=0.0) -> str:
    """Straight line north; ~11.1 m per point; constant grade."""
    pts = []
    for i in range(n):
        lat = 45.0 + i * step_deg
        ele = 100 + grade * i * step_deg * math.pi / 180 * 6_371_008.8
        ele += noise * ((-1) ** i)
        pts.append(f'<trkpt lat="{lat}" lon="6.0"><ele>{ele:.2f}</ele></trkpt>')
    return (
        '<?xml version="1.0"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Test climb</name><trkseg>'
        + "".join(pts)
        + "</trkseg></trk></gpx>"
    )


def test_route_constant_grade():
    r = Route.from_gpx(make_gpx())
    assert r.name == "Test climb"
    assert r.total_distance_m == pytest.approx(199 * 11.119, rel=1e-3)
    mid = r.total_distance_m / 2
    assert r.grade_at(mid) == pytest.approx(0.05, abs=1e-3)
    assert r.mean_grade(100, 500) == pytest.approx(0.05, abs=1e-3)
    p = r.point_at(mid)
    assert p.heading_deg == pytest.approx(0, abs=0.5)


def test_route_smoothing_kills_elevation_noise():
    noisy = Route.from_gpx(make_gpx(noise=1.5))
    mid = noisy.total_distance_m / 2
    assert noisy.grade_at(mid) == pytest.approx(0.05, abs=0.01)
    raw = Route.from_gpx(make_gpx(noise=1.5), smoothing_sigma_m=0)
    assert abs(raw.grade - 0.05).max() > 0.1  # unsmoothed is garbage


ZWO = """<workout_file><name>Sweet spot</name><description>2x10</description><workout>
<Warmup Duration="600" PowerLow="0.5" PowerHigh="0.75"/>
<IntervalsT Repeat="2" OnDuration="600" OffDuration="300" OnPower="0.9" OffPower="0.55"/>
<FreeRide Duration="120"/>
<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.4"/>
</workout></workout_file>"""


def test_parse_zwo():
    w = parse_zwo(ZWO)
    assert w.name == "Sweet spot"
    assert len(w.steps) == 1 + 4 + 1 + 1
    assert w.duration_s == 600 + 2 * 900 + 120 + 300
    assert w.target_watts(0, 200) == pytest.approx(100)
    assert w.target_watts(300, 200) == pytest.approx(125)  # mid warmup ramp
    assert w.target_watts(700, 200) == pytest.approx(180)
    assert w.target_watts(600 + 1800 + 10, 200) is None  # free ride
    assert w.target_watts(1e6, 200) is None


MRC = """[COURSE HEADER]
VERSION = 2
UNITS = ENGLISH
DESCRIPTION = test
FILE NAME = Ramp test
MINUTES PERCENT
[END COURSE HEADER]
[COURSE DATA]
0.00\t50
5.00\t50
5.00\t100
10.00\t100
[END COURSE DATA]"""


def test_parse_mrc():
    w = parse_erg_mrc(MRC)
    assert w.name == "Ramp test"
    assert w.duration_s == 600
    assert w.target_watts(60, 300) == pytest.approx(150)
    assert w.target_watts(400, 300) == pytest.approx(300)


def test_parse_erg_watts():
    w = parse_erg_mrc(MRC.replace("MINUTES PERCENT", "MINUTES WATTS"))
    assert w.target_watts(60, 300) == pytest.approx(50)


def test_smoothing_preserves_grade_at_route_ends():
    r = Route.from_gpx(make_gpx(grade=0.06))
    assert r.grade_at(0) == pytest.approx(0.06, abs=2e-3)
    assert r.grade_at(r.total_distance_m) == pytest.approx(0.06, abs=2e-3)
