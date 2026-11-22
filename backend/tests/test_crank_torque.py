"""ANT+ power meter crank-torque pages (0x12). Validated separately on a real ride log
(PM 63426): same mean power as page 16 within 0.1 % (median of 68 one-minute windows)."""

import math

import pytest

from opengpx_trainer.ant import profiles as pf


def page18(ev, ticks, cad, period, torque):
    return [
        0x12,
        ev % 256,
        ticks % 256,
        cad,
        period & 0xFF,
        (period >> 8) & 0xFF,
        torque & 0xFF,
        (torque >> 8) & 0xFF,
    ]


def test_power_and_cadence_from_crank_torque_with_rollovers():
    # 250 W at 90 rpm: one revolution = 1365.33/2048 s, torque per rev = P*period/(128*pi)
    d_period = round(2048 * 60 / 90)
    d_torque = round(250 * d_period / (128 * math.pi))
    c = pf.CrankTorquePower()
    period, torque = 65000, 65000  # both counters roll over on the next event
    c.update(pf.decode_power(page18(255, 0, 90, period, torque)), now=0.0)
    p, cad = c.update(
        pf.decode_power(page18(256, 1, 90, period + d_period, torque + d_torque)), now=0.7
    )
    assert p == pytest.approx(250, abs=0.5) and cad == pytest.approx(90, abs=0.1)


def test_crank_torque_stall_drops_to_zero():
    c = pf.CrankTorquePower(stall_s=3.0)
    c.update(pf.decode_power(page18(1, 1, 80, 1000, 1000)), now=0.0)
    c.update(pf.decode_power(page18(2, 2, 80, 2536, 1700)), now=0.75)
    frame = pf.decode_power(page18(2, 2, 80, 2536, 1700))  # repeated: crank not turning
    assert c.update(frame, now=2.0)[0] > 0
    assert c.update(frame, now=4.0) == (0.0, 0.0)


def test_hub_prefers_crank_torque_pages_over_power_only(monkeypatch):
    from opengpx_trainer.ant import ant_hub as ah

    clock = [100.0]
    monkeypatch.setattr(ah.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(pf.time, "monotonic", lambda: clock[0])
    hub = ah.AntHub(power_meter_id=63426)
    ext = [0x80, 63426 & 0xFF, 63426 >> 8, 11, 5]

    def page16(ev, acc, inst):
        return [0x10, ev, 0xFF, 85, acc & 0xFF, acc >> 8, inst & 0xFF, inst >> 8] + ext

    # power-only meter: page 16 drives the reading
    hub._on_power(page16(1, 1000, 200))
    clock[0] += 0.25
    hub._on_power(page16(2, 1200, 200))
    assert hub._s.pm_power.value == pytest.approx(200)
    # the meter also sends crank-torque pages: they take over, page 16 no longer overrides
    d_period = round(2048 * 60 / 90)
    d_torque = round(300 * d_period / (128 * math.pi))
    clock[0] += 0.25
    hub._on_power(page18(10, 10, 90, 5000, 5000) + ext)
    clock[0] += 0.7
    hub._on_power(page18(11, 11, 90, 5000 + d_period, 5000 + d_torque) + ext)
    assert hub._s.pm_power.value == pytest.approx(300, abs=1)
    clock[0] += 0.25
    hub._on_power(page16(3, 1400, 200))  # page 16 says 200 W: ignored now
    assert hub._s.pm_power.value == pytest.approx(300, abs=1)
    assert hub._s.pm_cadence.value == 90
