"""Short reception gaps must not zero the power (real ride, 2026-11-01: all ANT+ devices silent
for 4.2 s at the stick level, power recorded as 0 W for 2 s)."""

from opengpx_trainer.ant import hub as hub_mod
from tests.test_ant_session import FakeHub


def test_reading_survives_a_4_2_s_gap_but_not_a_real_disconnection(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(hub_mod.time, "monotonic", lambda: clock[0])
    h = FakeHub()
    h.feed(trainer=235, pm=230)
    clock[0] += 4.2  # nothing received
    r = h.readings()
    assert (r.pm_power_w, r.trainer_power_w) == (230, 235)
    assert r.power_meter_connected and r.trainer_connected
    clock[0] += 1.5  # 5.7 s of silence: really gone
    r = h.readings()
    assert r.pm_power_w is None and not r.power_meter_connected
