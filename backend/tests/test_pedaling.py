"""Pedal metrics of dual-sided power meters (balance, TE/PS, Cycling Dynamics), R-R intervals,
and their FIT export. Byte layouts: ANT+ Bicycle Power profile rev 5.1 (tables 8-1, 12-1,
15-13 to 15-15, 17-1 to 17-3); sample pages taken from a real ride (Favero Assioma, PM 63426).
The aggregation rules were checked on that ride against a Garmin Edge 540 recording."""

import queue
import threading
import time

import pytest
from fit_tool.data_message import DataMessage
from fit_tool.fit_file import FitFile

from hometrainer.ant import ant_hub as ah
from hometrainer.ant import profiles as pf
from hometrainer.ant.hub import SensorHub
from hometrainer.checkpoint import RideCheckpoint, load_checkpoint
from hometrainer.pedaling import (
    attributed_positions,
    balance_100,
    circular_mean_deg,
    fit_angle,
    pedal_summary,
    position_changes,
)
from hometrainer.profile import Profile
from hometrainer.recording import Recorder, Sample, hrv_is_synthetic, write_ride_feedback
from hometrainer.session import RideSession
from hometrainer.workouts.model import Step, Workout

PM = 63426
EXT = [0x80, PM & 0xFF, PM >> 8, 11, 5]
ASSIOMA_CAPS = [0x02, 0xFE, 0xFF, 0xFF, 212, 0xFF, 213, 0xFF]  # as sent, Edge connected


# -- decoding --------------------------------------------------------------------------------
def test_power_only_keeps_the_right_pedal_flag():
    m = pf.decode_power([0x10, 0, 178, 85, 0, 0, 200, 0])
    assert m.pedal_balance == 178  # 0x80 | 50: right pedal 50 %


def test_torque_effectiveness_and_pedal_smoothness():
    m = pf.decode_power_extra([0x13, 7, 163, 164, 48, 46, 0xFF, 0xFF])
    assert (m.left_te, m.right_te, m.left_ps, m.right_ps) == (81.5, 82.0, 24.0, 23.0)
    assert m.combined_ps is None
    c = pf.decode_power_extra([0x13, 7, 0xFF, 0xFF, 50, 0xFE, 0xFF, 0xFF])
    assert c.left_te is None and c.combined_ps == 25.0 and c.left_ps is c.right_ps is None


def test_force_angle_pages():
    left = pf.decode_power_extra([0xE1, 3, 2, 142, 50, 89, 30, 3])
    assert left.side == "left" and left.event_count == 3
    assert left.phase_deg == pytest.approx((2.8125, 199.6875))  # 1 brad = 360/256 deg
    assert left.peak_phase_deg == pytest.approx((70.3125, 125.15625))
    assert left.torque_nm == pytest.approx((30 | 3 << 8) / 32)
    right = pf.decode_power_extra([0xE0, 0, 0xC0, 0xC0, 0xC0, 0xC0, 0, 0])
    assert right.side == "right" and right.phase_deg is None and right.peak_phase_deg is None


def test_pedal_position_page():
    m = pf.decode_power_extra([0xE2, 1, 0x20 | 3 << 6, 88, 5, 0xFB, 0xFF, 0xFF])
    assert m.rider_position == 3 and m.cadence_rpm == 88
    assert (m.right_pco_mm, m.left_pco_mm) == (5, -5)
    assert pf.decode_power_extra([0xE2, 1, 0x20, 0xFF, 0x80, 0, 0xFF, 0xFF]).right_pco_mm is None
    assert pf.ANT_TO_FIT_RIDER_POSITION == {0: 0, 1: 2, 2: 1, 3: 3}


# -- enabling Cycling Dynamics -----------------------------------------------------------------
def test_enable_command_for_the_supported_elements():
    caps = pf.decode_power_extra(ASSIOMA_CAPS)
    # Assioma: 8 Hz, power phase and rider position supported; no PCO, no torque barycenter
    assert pf.encode_enable_cycling_dynamics(caps) == [0x02, 0xFE, 0xFF, 0xFF, 213, 0xFF, 213, 0xFF]
    assert pf.cycling_dynamics_enabled(caps)  # what the Edge had set
    off = pf.AdvancedCapabilities2(mask=212, value=0xFF)
    assert not pf.cycling_dynamics_enabled(off)
    assert pf.encode_enable_cycling_dynamics(pf.AdvancedCapabilities2(0xFF, 0xFF)) is None


def test_enabler_requests_sets_then_checks():
    e = pf.CyclingDynamicsEnabler()
    request = pf.encode_request_page(0x02, descriptor=0xFE)
    assert request == [0x46, 0xFF, 0xFF, 0xFE, 0xFF, 0x02, 0x02, 0x01]
    assert e.poll(0.0) == [request]
    assert e.poll(1.0) == []  # waits RETRY_S
    off = pf.AdvancedCapabilities2(mask=212, value=0xFF)
    assert e.on_page(off, 1.5) == [pf.encode_enable_cycling_dynamics(off)]
    assert e.poll(2.0) == [] and e.poll(4.6) == [request]  # check it was applied
    assert e.on_page(pf.AdvancedCapabilities2(mask=212, value=213), 5.0) == []
    assert e.state == "enabled" and e.poll(100.0) == []
    e.reset()
    assert e.state == "unknown" and e.poll(101.0) == [request]


def test_enabler_gives_up_and_notices_pages_enabled_elsewhere():
    e = pf.CyclingDynamicsEnabler(max_requests=2)
    assert len(e.poll(0)) == 1 and len(e.poll(3)) == 1 and e.poll(6) == []
    assert e.state == "unsupported"
    e2 = pf.CyclingDynamicsEnabler()
    e2.on_page(pf.decode_power_extra([0xE2, 1, 0x20, 80, 0, 0, 0xFF, 0xFF]), 0.0)
    assert e2.state == "enabled" and e2.poll(10.0) == []
    assert not e2.pco_supported
    e2.on_page(pf.AdvancedCapabilities2(mask=0b11000100, value=0xFF), 1.0)
    assert e2.pco_supported


# -- R-R intervals ----------------------------------------------------------------------------
def hrm(page, beat_time, count, hr=120, prev_time=0xFFFF):
    prev = [prev_time & 0xFF, prev_time >> 8]
    return [page, 0xFF, *prev, beat_time & 0xFF, beat_time >> 8, count, hr]


def test_rr_intervals_consecutive_missed_and_page_4():
    r = pf.RRIntervals()
    assert r.update(hrm(0, 65000, 10)) == []  # first page: no reference
    assert r.update(hrm(0x80, 65000, 10)) == []  # same beat repeated (toggle bit set)
    assert r.update(hrm(0, (65000 + 820) % 65536, 11)) == pytest.approx([820 / 1024])
    assert r.update(hrm(0, 2000, 14)) == []  # beats missed, no previous-beat time
    assert r.update(hrm(4, 2900, 16, prev_time=2100)) == pytest.approx([800 / 1024])
    assert r.update(hrm(0, 2900 + 100, 17)) == []  # 0.1 s: implausible, dropped


# -- hub --------------------------------------------------------------------------------------
@pytest.fixture
def clocked_hub(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(ah.time, "monotonic", lambda: clock[0])
    return ah.AntHub(power_meter_id=PM, heart_rate_id=52100), clock


def test_hub_exposes_pedal_metrics_and_queues_dynamics_requests(clocked_hub):
    hub, clock = clocked_hub
    hub._on_power([0x10, 1, 178, 85, 0, 0, 200, 0] + EXT)
    hub._on_power([0x13, 1, 163, 163, 48, 46, 0xFF, 0xFF] + EXT)
    hub._on_power([0xE1, 1, 2, 142, 50, 89, 30, 3] + EXT)
    hub._on_power([0xE2, 1, 0x20 | 2 << 6, 85, 4, 4, 0xFF, 0xFF] + EXT)
    p = hub.readings().pedal
    assert p.balance == 178 and (p.left_te, p.right_ps) == (81.5, 23.0)
    assert p.left_phase == pytest.approx((2.8125, 199.6875)) and p.right_phase is None
    assert p.rider_position == 1  # ANT "standing" -> FIT STANDING
    assert p.left_pco_mm is None  # PCO not trusted until the meter says it supports it
    assert hub._tx_queue.empty()  # Cycling Dynamics set-up off: nothing sent to the meter
    clock[0] += 6.0  # stale
    assert hub.readings().pedal is None


def queued(hub):
    items = []
    while not hub._tx_queue.empty():
        items.append(hub._tx_queue.get())
    return items


def test_hub_sends_nothing_to_the_meter_by_default(clocked_hub):
    hub, _ = clocked_hub
    hub._on_power([0x02, 0xFE, 0xFF, 0xFF, 212, 0xFF, 0xFF, 0xFF] + EXT)
    hub._on_power([0x10, 1, 178, 85, 0, 0, 200, 0] + EXT)
    assert queued(hub) == []
    assert not hub._dynamics.pco_supported  # capabilities still read


def test_hub_cycling_dynamics_set_up_when_switched_on(clocked_hub, monkeypatch):
    hub, _ = clocked_hub
    monkeypatch.setattr(hub, "ENABLE_CYCLING_DYNAMICS", True)
    hub._on_power([0x10, 1, 178, 85, 0, 0, 200, 0] + EXT)
    assert ("pm", tuple(pf.encode_request_page(0x02, descriptor=0xFE))) in queued(hub)
    hub._on_power([0x02, 0xFE, 0xFF, 0xFF, 212, 0xFF, 0xFF, 0xFF] + EXT)
    assert ("pm", (0x02, 0xFE, 0xFF, 0xFF, 213, 0xFF, 213, 0xFF)) in queued(hub)


def test_hub_rr_intervals_are_drained_once(clocked_hub):
    hub, _ = clocked_hub
    hub._on_hrm(hrm(0, 1000, 1) + [0x80, 0x84, 0xCB, 120, 1])
    hub._on_hrm(hrm(0, 1800, 2) + [0x80, 0x84, 0xCB, 120, 1])
    assert hub.drain_rr() == pytest.approx([800 / 1024])
    assert hub.drain_rr() == []


class FakeChannel:
    id = 2

    def __init__(self):
        self.sent = []
        self._ant = self

    def send_acknowledged_data(self, ch_id, data):
        self.sent.append((ch_id, list(data)))

    def wait_for_event(self, codes): ...


def test_tx_thread_sends_power_meter_commands_without_an_ant_trainer():
    hub = ah.AntHub(use_trainer=False)  # e.g. trainer on Bluetooth: no FE-C channel
    hub._pm_ch = FakeChannel()
    hub._running = True
    hub._tx_queue = queue.Queue()
    t = threading.Thread(target=hub._tx_loop, daemon=True)
    t.start()
    hub._tx_queue.put(("pm", (0x46, 1, 2)))
    hub._tx_queue.put("tick")
    hub._tx_queue.put(("pm", (0x02, 3)))
    deadline = time.monotonic() + 5
    while len(hub._pm_ch.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    hub._tx_queue.put(None)
    t.join(timeout=5)
    assert not t.is_alive()
    assert hub._pm_ch.sent == [(2, [0x46, 1, 2]), (2, [0x02, 3])]


def test_power_meter_commands_never_go_to_the_trainer_channel():
    hub = ah.AntHub()
    hub._fec = FakeChannel()  # trainer channel open, power-meter channel not yet
    hub.devices["trainer"].last_seen = time.monotonic()
    hub._running = True
    hub._tx_queue = queue.Queue()
    t = threading.Thread(target=hub._tx_loop, daemon=True)
    t.start()
    hub._tx_queue.put(("pm", (0x46, 1, 2)))
    hub._tx_queue.put("command")  # no trainer command set: nothing to send either
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        time.sleep(0.05)
    hub._tx_queue.put(None)
    t.join(timeout=5)
    assert hub._fec.sent == []


# -- aggregation ------------------------------------------------------------------------------
def sample(t, power=200.0, **kw):
    return Sample(
        timestamp_s=1_793_806_952.0 + t,
        elapsed_s=float(t),
        power_w=power,
        cadence_rpm=kw.pop("cadence_rpm", 85.0),
        heart_rate_bpm=kw.pop("heart_rate_bpm", 140.0),
        speed_ms=8.0,
        distance_m=8.0 * t,
        **kw,
    )


def test_circular_mean_wraps_around_top_dead_centre():
    m = circular_mean_deg([355.0, 5.0])
    assert 0.0 <= m < 360.0 and min(m, 360.0 - m) == pytest.approx(0.0, abs=1e-9)
    assert circular_mean_deg([350.0, 20.0]) == pytest.approx(5.0)
    assert circular_mean_deg([0.0, 180.0]) is None
    assert circular_mean_deg([]) is None


def test_balance_is_power_weighted_right_share():
    s = [sample(0, 100.0, lr_balance=0x80 | 40), sample(1, 300.0, lr_balance=0x80 | 60)]
    assert balance_100(s) == 0x8000 | 5500  # (40*100 + 60*300) / 400 = 55 %
    unknown = [sample(0, 100.0, lr_balance=52)]
    assert balance_100(unknown) == 5200  # side unknown: no right-leg bit


def test_rider_position_attribution_table_17_4():
    seated, standing, to_seated, to_standing = 0, 1, 2, 3
    seq = [seated, to_standing, standing, standing, to_seated, standing, to_standing, seated]
    s = [sample(i, rider_position=p) for i, p in enumerate(seq)]
    assert attributed_positions(s) == [0, 1, 1, 1, 1, 1, 0, 0]
    assert attributed_positions([sample(0, rider_position=to_standing)]) == [1]
    assert position_changes(s[:3]) == [
        (s[0].timestamp_s, 0),
        (s[1].timestamp_s, 3),
        (s[2].timestamp_s, 1),
    ]


def test_pedal_summary_over_pedalling_samples():
    s = [
        sample(
            0,
            200.0,
            left_te=80.0,
            right_te=82.0,
            left_ps=24.0,
            right_ps=22.0,
            left_power_phase=[355.0, 210.0],
            rider_position=0,
            cadence_rpm=80.0,
        ),
        sample(
            1,
            300.0,
            left_te=84.0,
            right_te=82.0,
            left_ps=26.0,
            right_ps=24.0,
            left_power_phase=[5.0, 220.0],
            rider_position=1,
            cadence_rpm=70.0,
        ),
        sample(
            2,
            0.0,
            left_te=0.0,
            right_te=0.0,
            left_ps=0.0,
            right_ps=0.0,
            left_power_phase=[90.0, 90.0],
            rider_position=0,
            cadence_rpm=0.0,
        ),  # coasting
    ]
    out = pedal_summary(s)
    assert out["avg_left_torque_effectiveness"] == pytest.approx(82.0)
    assert out["avg_right_pedal_smoothness"] == pytest.approx(23.0)
    start, end = out["avg_left_power_phase"]
    # rounded to the FIT resolution (360/256°)
    assert start == 0.0 and end == pytest.approx(215.0, abs=360 / 512)
    assert out["avg_power_position"] == [200, 300] and out["max_cadence_position"] == [80, 70]
    assert out["time_standing"] == 1.0 and out["stand_count"] == 1
    assert "left_right_balance" not in out and "avg_left_pco" not in out
    assert pedal_summary([sample(0)]) == {}  # no dual-sided meter: nothing


# -- recording, checkpoint and FIT -------------------------------------------------------------
def test_recorder_keeps_the_beats_of_a_replaced_tick():
    rec = Recorder()
    rec.add(sample(0.0, rr_s=[0.8]))
    rec.add(sample(0.25, rr_s=[0.81]))  # same second: replaces the sample
    rec.add(sample(0.5))
    assert len(rec.samples) == 1 and rec.samples[0].rr_s == pytest.approx([0.8, 0.81])


def test_checkpoint_round_trip_with_pedal_fields(tmp_path):
    s = [sample(0, lr_balance=178, left_power_phase=[2.8, 199.7], rr_s=[0.8, 0.79])]
    cp = RideCheckpoint(tmp_path / "x.jsonl")
    cp.update({"session_id": "x"}, s, now=0.0, final=True)
    _, back = load_checkpoint(tmp_path / "x.jsonl")
    assert back == s


def real_rr(i):
    return [0.40 + 0.02 * ((i * 7 + k) % 5) for k in range(3)]  # scattered around 60/HR


def fit_messages(path):
    out = {}
    for r in FitFile.from_file(str(path)).records:
        out.setdefault(type(r.message).__name__, []).append(r.message)
    return out


def rich_recorder() -> Recorder:
    """One minute with every metric the FIT file can hold (pedals, HRV, positions, 2 steps)."""
    rec = Recorder()
    for i in range(60):
        rec.add(
            sample(
                i,
                200.0 + i,
                heart_rate_bpm=140.0,
                lr_balance=0x80 | 51,
                left_te=81.5,
                right_te=80.0,
                left_ps=24.0,
                right_ps=23.0,
                left_power_phase=[2.8125, 216.5625],
                left_power_phase_peak=[67.5, 125.15625],
                right_power_phase=[1.40625, 208.125],
                right_power_phase_peak=[64.6875, 119.53125],
                rider_position=3 if i == 30 else (1 if 30 < i < 40 else 0),
                rr_s=real_rr(i),
                step_index=0 if i < 30 else 1,
                target_w=200.0 if i < 30 else 250.0,
            )
        )
    return rec


def fit_content(path) -> list:
    """Every data message of a FIT file: (global id, field values, developer field values)."""
    out = []
    for r in FitFile.from_file(str(path)).records:
        m = r.message
        if isinstance(m, DataMessage):
            vals = {f.field_id: f.get_values() for f in m.fields if f.is_valid()}
            devs = {f.field_id: f.get_values() for f in m.developer_fields or [] if f.is_valid()}
            out.append((m.global_id, vals, devs))
    return out


def test_fit_timer_time_never_exceeds_elapsed_time(tmp_path):
    """KNOWN_ISSUES #13: the first sample comes ~1 s after the ride started (last tick of
    its second) but already counts that riding time; a real file had a session timer of
    4935.087 s for 4934.925 s elapsed (invalid FIT)."""
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.session_message import SessionMessage

    t0 = 1_793_806_952.0
    rec = Recorder()
    for i in range(120):
        # riding time 0.75 s ahead of the wall clock offset; a 20 s pause after 60 s
        wall = t0 + i + (20 if i >= 60 else 0)
        rec.add(Sample(wall, i + 0.75, 200.0, 85.0, 140.0, 8.0, 8.0 * i, step_index=i // 60))
    path = rec.write_fit(tmp_path / "ride.fit")
    msgs = [r.message for r in FitFile.from_file(str(path)).records]
    ses = next(m for m in msgs if isinstance(m, SessionMessage))
    laps = [m for m in msgs if isinstance(m, LapMessage)]
    assert ses.total_timer_time == pytest.approx(119.75)
    assert ses.total_elapsed_time == pytest.approx(139.75)  # from the real start, pause included
    assert ses.start_time == (t0 - 1) * 1000  # FIT times are whole seconds: 0.75 s earlier
    assert len(laps) == 2
    for lap in [*laps, ses]:
        assert lap.total_timer_time <= lap.total_elapsed_time


def test_fit_has_the_totals_a_head_unit_writes(tmp_path):
    """Roadmap "Complete FIT file", computable metrics: work, calories, crank revolutions,
    maxima, speeds, climbing, IF / TSS, pauses, accumulated power, rider profile."""
    from fit_tool.profile.messages.activity_message import ActivityMessage
    from fit_tool.profile.messages.event_message import EventMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.messages.user_profile_message import UserProfileMessage
    from fit_tool.profile.messages.zones_target_message import ZonesTargetMessage

    from hometrainer.recording import GROSS_EFFICIENCY, Athlete

    t0 = 1_793_806_952.0
    rec = Recorder()
    for i in range(120):
        alt = 100.0 + (i if i < 60 else 60 - 0.5 * (i - 60))  # +60 m then -30 m
        wall = t0 + i + (20 if i >= 60 else 0)  # a 20 s pause after the first minute
        rec.add(
            Sample(
                wall,
                i + 1.0,
                200.0,
                90.0,
                120.0 + i / 4,
                8.0 + (i % 10) / 10,
                8.0 * (i + 1),
                altitude_m=alt,
                step_index=i // 60,
            )
        )
    athlete = Athlete(ftp_w=250, weight_kg=73, max_hr_bpm=189)
    path = rec.write_fit(tmp_path / "r.fit", athlete)
    msgs = [r.message for r in FitFile.from_file(str(path)).records]
    of = lambda cls: [m for m in msgs if isinstance(m, cls)]  # noqa: E731
    ses, laps = of(SessionMessage)[0], of(LapMessage)

    assert ses.total_work == 24000  # J: 200 W x 120 s
    assert ses.total_calories == round(24000 / GROSS_EFFICIENCY / 4184)
    assert (ses.total_cycles, ses.max_cadence, ses.avg_cadence) == (180, 90, 90)
    assert ses.max_heart_rate == round(120 + 119 / 4)
    assert ses.enhanced_max_speed == pytest.approx(8.9)
    assert ses.enhanced_avg_speed == pytest.approx(8.0, abs=0.01)
    assert (ses.total_ascent, ses.total_descent) == (60, 30)  # 100 -> 160 -> 130.5 m
    assert [(lap.total_ascent, lap.total_descent) for lap in laps] == [(59, 0), (1, 30)]
    assert [lap.total_work for lap in laps] == [12000, 12000]
    # IF = NP / FTP, TSS = t x NP x IF / (FTP x 3600) x 100
    assert ses.threshold_power == 250 and ses.intensity_factor == pytest.approx(0.8)
    assert ses.training_stress_score == pytest.approx(120 * 200 * 0.8 / (250 * 3600) * 100, abs=0.1)
    timers = [(e.event_type, e.timestamp) for e in of(EventMessage) if e.event == 0]
    assert [k for k, _ in timers] == [0, 4, 0, 4]  # start, stop (pause), start, stop
    # stopped at the last sample before the pause, restarted one riding second before the next
    assert timers[1][1] == (t0 + 59) * 1000 and timers[2][1] == (t0 + 79) * 1000
    assert of(RecordMessage)[-1].accumulated_power == 24000
    user = of(UserProfileMessage)[0]
    assert (user.weight, user.default_max_heart_rate) == (73, 189)
    assert of(ZonesTargetMessage)[0].functional_threshold_power == 250
    assert of(ActivityMessage)[0].local_timestamp is not None


def test_ride_feedback_changes_only_rpe_and_feel(tmp_path):
    path = rich_recorder().write_fit(tmp_path / "ride.fit")
    before = fit_content(path)
    write_ride_feedback(path, rpe=7, feel=75)
    after = fit_content(path)
    assert len(after) == len(before)
    assert any(devs for _, _, devs in after)  # target_power developer field still there
    for (gid, vals, devs), (gid2, vals2, devs2) in zip(before, after, strict=True):
        assert (gid, devs) == (gid2, devs2)
        if gid == 18:  # session: RPE stored x 10, feel 0-100 (as a Garmin Edge does)
            assert vals2 == {**vals, 193: [70], 192: [75]}
        else:
            assert vals == vals2
    write_ride_feedback(path, rpe=None, feel=None)  # cleared again
    assert fit_content(path) == before
    with pytest.raises(ValueError):
        write_ride_feedback(path, rpe=11, feel=None)
    with pytest.raises(ValueError):
        write_ride_feedback(path, rpe=None, feel=60)


def test_fit_has_pedal_records_laps_session_events_and_hrv(tmp_path):
    path = rich_recorder().write_fit(tmp_path / "ride.fit")
    m = fit_messages(path)
    r0 = m["RecordMessage"][0]
    assert r0.left_right_balance == 0x80 | 51 and r0.left_torque_effectiveness == 81.5
    assert r0.left_power_phase == pytest.approx([2.8125, 216.5625], abs=0.01)
    assert r0.right_pedal_smoothness == 23.0
    ses = m["SessionMessage"][0]
    assert ses.left_right_balance == 0x8000 | 5100
    assert ses.avg_left_torque_effectiveness == 81.5
    assert ses.avg_right_power_phase_peak == pytest.approx([64.6875, 119.53125], abs=0.01)
    assert ses.time_standing == 10.0 and ses.stand_count == 1
    laps = m["LapMessage"]
    assert len(laps) == 2 and laps[1].time_standing == 10.0 and laps[0].time_standing == 0.0
    ev = [e for e in m["EventMessage"] if e.event == 44]
    assert [e.rider_position for e in ev] == [0, 3, 1, 0]
    hrv = [t for h in m["HrvMessage"] for t in h.time if t is not None and t < 60]
    assert hrv == pytest.approx([x for i in range(60) for x in real_rr(i)], abs=0.001)
    assert all(len(h.time) == 5 for h in m["HrvMessage"])


def test_fit_power_phase_average_just_below_360_wraps_to_zero(tmp_path):
    # ANT+ angles are multiples of 360/256°; 0° and 358.59375° (255 units) average to
    # 359.3°, which rounds to 256 units and overflowed the FIT byte
    rec = Recorder()
    for i in range(10):
        a = 358.59375 if i % 2 else 0.0
        rec.add(sample(i, 200.0, right_power_phase=[a, 199.6875]))
    assert fit_angle(359.6) == 0.0 and fit_angle(359.2) == pytest.approx(358.59375)
    m = fit_messages(rec.write_fit(tmp_path / "ride.fit"))
    assert m["SessionMessage"][0].avg_right_power_phase == pytest.approx([0.0, 199.69], abs=0.01)
    assert m["LapMessage"][0].avg_right_power_phase == pytest.approx([0.0, 199.69], abs=0.01)


def test_fit_without_hrv_when_intervals_are_just_60_over_hr(tmp_path):
    rec = Recorder()
    for i in range(60):
        rec.add(sample(i, heart_rate_bpm=144.0, rr_s=[60 / 144 + 0.001 * (i % 3)]))
    assert hrv_is_synthetic(rec.samples)
    assert "HrvMessage" not in fit_messages(rec.write_fit(tmp_path / "ride.fit"))
    real = [sample(i, heart_rate_bpm=144.0, rr_s=real_rr(i)) for i in range(60)]
    assert not hrv_is_synthetic(real)


class PedalHub(SensorHub):
    def start(self): ...
    def stop(self): ...
    def set_target_power(self, w): ...
    def set_basic_resistance(self, p): ...
    def set_user_configuration(self, *a): ...


def test_session_records_pedal_metrics_and_beats():
    h = PedalHub()
    s = RideSession(
        h, Profile(power_match=False), "erg", workout=Workout("w", [Step(60, 0.5, 0.5)])
    )
    with h._lock:
        h._seen("power_meter")
        h._s.pm_power.set(150)
        h._s.pm_cadence.set(85)
        h._s.pm_balance.set(0x80 | 52)
        h._s.pm_te.set((80.0, 81.0))
        h.add_rr([0.43, 0.44])
    s.tick(1000.0)
    s.tick(1000.25)  # running: this tick is recorded
    rec = s.recorder.samples[-1]
    assert rec.lr_balance == 0x80 | 52 and (rec.left_te, rec.right_te) == (80.0, 81.0)
    assert rec.rr_s == pytest.approx([0.43, 0.44])  # drained by the first tick, kept
    assert h.drain_rr() == []
