import math

import pytest

from hometrainer.physics.grade_power import GradePowerCurve, RateLimiter
from hometrainer.physics.model import ModelParams, SpeedModel, VirtualBike, air_density

P = ModelParams()
M = SpeedModel(P)


def test_air_density_reference_values():
    # dry air, ISA sea level 15 C -> 1.225 kg/m3
    assert air_density(0, 15, 0.0) == pytest.approx(1.225, abs=0.002)
    # density drops ~10 % per 1000 m
    assert air_density(1000, 15, 0.0) / air_density(0, 15, 0.0) == pytest.approx(0.89, abs=0.01)
    # humid air is lighter
    assert air_density(0, 30, 1.0) < air_density(0, 30, 0.0)


def test_power_required_matches_closed_form():
    v, grade, rho = 10.0, 0.05, 1.2
    s, c = grade / math.hypot(1, grade), 1 / math.hypot(1, grade)
    m = P.mass_kg
    expected = (m * 9.80665 * (P.crr * c + s) + 0.5 * rho * P.cda_m2 * v * v) * v
    assert M.power_required(v, grade, rho) == pytest.approx(expected / P.drivetrain_efficiency)


@pytest.mark.parametrize("power,grade", [(250, 0.0), (300, 0.08), (150, -0.02), (0, -0.06)])
def test_steady_speed_inverts_power_required(power, grade):
    v = M.steady_speed(power, grade, 1.2)
    assert M.power_required(v, grade, 1.2) == pytest.approx(power, abs=0.1)


def test_flat_250w_is_plausible():
    v = M.steady_speed(250, 0.0, 1.2) * 3.6
    assert 34 < v < 38


def test_zero_power_on_flat_stays_still():
    assert M.steady_speed(0, 0.0, 1.2) == 0.0
    bike = VirtualBike(P)
    bike.step(0, 10)
    assert bike.state.speed_ms == 0.0


def test_dynamic_model_converges_to_steady_state():
    bike = VirtualBike(P)
    for _ in range(400):  # 100 s at 4 Hz
        bike.step(250, 0.25)
    assert bike.state.speed_ms == pytest.approx(M.steady_speed(250, 0.0, M.rho(0)), rel=1e-3)


def test_energy_balance_on_acceleration():
    """Integrated work = kinetic energy + dissipated energy (no grade)."""
    bike = VirtualBike(P)
    dt, power, e_diss = 0.05, 300.0, 0.0
    for _ in range(200):
        v0 = bike.state.speed_ms
        bike.step(power, dt)
        v1 = bike.state.speed_ms
        vm = 0.5 * (v0 + v1)
        e_diss += M.forces(vm, 0.0, M.rho(0)).total_n * vm * dt
    ke = 0.5 * P.inertial_mass_kg * bike.state.speed_ms**2
    work = P.drivetrain_efficiency * power * 200 * dt
    assert ke + e_diss == pytest.approx(work, rel=0.02)  # first second has drive-force cap


def test_momentum_carries_into_climb():
    """Speed decays progressively at the foot of a climb instead of jumping."""

    def road(d):
        return (0.0 if d < 500 else 0.08), 0.0

    bike = VirtualBike(P, road)
    while bike.state.distance_m < 500:
        bike.step(250, 0.25)
    v_flat = bike.state.speed_ms
    bike.step(250, 0.25)
    v_steady_climb = M.steady_speed(250, 0.08, M.rho(0))
    assert v_steady_climb < bike.state.speed_ms < v_flat


def test_descent_capped_by_braking():
    bike = VirtualBike(P, lambda d: (-0.15, 0.0))
    for _ in range(600):
        bike.step(0, 0.25)
    assert bike.state.speed_ms == pytest.approx(P.max_speed_ms)


def test_horizontal_vs_road_distance():
    bike = VirtualBike(P, lambda d: (0.10, 0.0))
    for _ in range(100):
        bike.step(300, 0.25)
    ratio = bike.state.distance_m / bike.state.distance_3d_m
    assert ratio == pytest.approx(1 / math.hypot(1, 0.10), rel=1e-6)


def test_power_multiplier_gives_more_speed():
    a, b = VirtualBike(P), VirtualBike(P)
    for _ in range(200):
        a.step(200, 0.25)
        b.step(200 * 1.10, 0.25)
    assert b.state.speed_ms > a.state.speed_ms


def test_grade_curve_and_limits():
    c = GradePowerCurve()
    assert c.fraction(0.0) == pytest.approx(0.70)
    assert c.fraction(0.30) == pytest.approx(1.00)  # flat beyond last point
    assert c.fraction(-0.2) == pytest.approx(0.40)
    assert c.target_watts(0.0, 250, 1.1) == pytest.approx(0.7 * 250 * 1.1)


def test_rate_limiter():
    rl = RateLimiter(10)
    assert rl(100, 1) == 100
    assert rl(200, 1) == 110
    assert rl(50, 2) == 90


def test_aero_drag_with_apparent_wind():
    v, rho, k = 30 / 3.6, 1.2, 0.5 * 1.2 * P.cda_m2
    still = M.forces(v, 0.0, rho).aero_n
    assert still == pytest.approx(k * v * v)
    # head / tail wind only: the usual (v + w)|v + w|
    w = 5.0
    assert M.forces(v, 0.0, rho, (w, 0.0)).aero_n == pytest.approx(k * (v + w) ** 2)
    assert M.forces(v, 0.0, rho, (-w, 0.0)).aero_n == pytest.approx(k * (v - w) ** 2)
    # tailwind faster than the rider pushes him
    assert M.forces(3.0, 0.0, rho, (-w, 0.0)).aero_n < 0
    # pure crosswind of 20 km/h at 30 km/h: drag x |Va|/v = hypot(30, 20)/30 = 1.20
    cross = M.forces(v, 0.0, rho, (0.0, 20 / 3.6)).aero_n
    assert cross / still == pytest.approx(math.hypot(30, 20) / 30)
    # the side it comes from does not matter
    assert M.forces(v, 0.0, rho, (0.0, -20 / 3.6)).aero_n == pytest.approx(cross)


def test_steady_speed_with_wind():
    rho = 1.2
    calm = M.steady_speed(250, 0.0, rho)
    head = M.steady_speed(250, 0.0, rho, (15 / 3.6, 0.0))
    tail = M.steady_speed(250, 0.0, rho, (-15 / 3.6, 0.0))
    cross = M.steady_speed(250, 0.0, rho, (0.0, 15 / 3.6))
    assert tail > calm > cross > head
    v = M.steady_speed(250, 0.02, rho, (3.0, 4.0))
    assert M.power_required(v, 0.02, rho, (3.0, 4.0)) == pytest.approx(250, abs=0.1)


def test_virtual_bike_follows_the_wind_along_the_route():
    # first 1 km headwind, then tailwind (e.g. an out-and-back)
    bike = VirtualBike(P, wind_fn=lambda d: (5.0, 0.0) if d < 1000 else (-5.0, 0.0))
    speeds = []
    for _ in range(4 * 600):
        bike.step(250, 0.25)
        speeds.append((bike.state.distance_m, bike.state.speed_ms))
    v_head = max(v for d, v in speeds if 500 < d < 1000)
    v_tail = speeds[-1][1]
    assert v_head == pytest.approx(M.steady_speed(250, 0.0, M.rho(0), (5.0, 0.0)), rel=0.01)
    assert v_tail == pytest.approx(M.steady_speed(250, 0.0, M.rho(0), (-5.0, 0.0)), rel=0.01)
    assert bike.state.wind == (-5.0, 0.0)
