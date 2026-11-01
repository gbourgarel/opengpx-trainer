"""Live ride averages (average power, NP, average speed)."""

import random

import pytest

from hometrainer.profile import Profile
from hometrainer.recording import RideAverages, normalized_power
from hometrainer.session import RideSession
from hometrainer.workouts.model import Step, Workout
from tests.test_ant_session import FakeHub


def test_incremental_np_matches_batch_definition():
    rng = random.Random(1)
    seconds = [max(0.0, 200 + 120 * ((i // 60) % 2) + rng.gauss(0, 25)) for i in range(900)]
    avg = RideAverages()
    for p in seconds:  # 4 ticks of 0.25 s per second, constant power within the second
        for _ in range(4):
            avg.add(p, 0.25)
    assert avg.np_w == pytest.approx(normalized_power(seconds), rel=1e-9)
    assert avg.avg_power_w == pytest.approx(sum(seconds) / len(seconds), rel=1e-9)


def test_irregular_ticks_are_split_on_second_boundaries():
    avg = RideAverages()
    for _ in range(101):  # 0.3 s ticks: every 1 s bucket straddles a tick (30.3 s in total)
        avg.add(250.0, 0.3)
    assert avg.time_s == pytest.approx(30.3)
    assert avg.np_w == pytest.approx(250.0)  # constant power: NP == power


def test_np_needs_30_seconds():
    avg = RideAverages()
    for _ in range(29 * 4):
        avg.add(200.0, 0.25)
    assert avg.np_w is None and avg.avg_power_w == pytest.approx(200.0)


def test_session_reports_averages_excluding_pauses():
    h = FakeHub()
    s = RideSession(
        h, Profile(power_match=False), "erg", workout=Workout("w", [Step(600, 0.8, 0.8)])
    )
    t = 1000.0
    for _ in range(4 * 40):  # 40 s at 200 W
        h.feed(trainer=200, pm=200)
        tel = s.tick(t := t + 0.25)
    s.pause()
    for _ in range(4 * 20):  # paused: not counted
        h.feed(trainer=0, pm=0, cad=0)
        tel = s.tick(t := t + 0.25)
    assert tel["avg_power_w"] == 200 and tel["np_w"] == 200
    assert tel["avg_speed_kmh"] == pytest.approx(tel["distance_m"] / s.elapsed_s * 3.6, abs=0.01)


def test_interval_average_resets_at_each_step():
    h = FakeHub()
    w = Workout("w", [Step(20, 0.5, 0.5), Step(20, 1.0, 1.0)])
    s = RideSession(h, Profile(power_match=False), "erg", workout=w)
    t = 1000.0

    def ride(seconds, watts):
        nonlocal t
        tel = None
        for _ in range(int(seconds * 4)):
            h.feed(trainer=watts, pm=watts)
            tel = s.tick(t := t + 0.25)
        return tel

    ride(10, 150)
    tel = ride(8, 170)  # first step: 10 s at 150 W then 8 s at 170 W
    assert tel["step_index"] == 0
    assert tel["step_avg_power_w"] == pytest.approx((10 * 150 + 8 * 170) / 18, abs=1.5)
    tel = ride(6, 300)  # crosses into the second step: its average starts from scratch
    assert tel["step_index"] == 1
    assert tel["step_avg_power_w"] == 300
