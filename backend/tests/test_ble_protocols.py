"""BLE GATT profile decoding/encoding (frames built by hand from the Bluetooth specs)."""

import struct

import pytest

from hometrainer.ble import protocols as bp


def test_heart_rate_8_and_16_bit():
    assert bp.parse_heart_rate(bytes([0x00, 142])) == 142
    assert bp.parse_heart_rate(bytes([0x01, 0x2C, 0x01])) == 300
    assert bp.parse_heart_rate(bytes([0x00, 0])) is None  # no contact / not ready
    assert bp.parse_heart_rate(b"\x00") is None


def test_cycling_power_with_crank_data_after_optional_fields():
    # flags: balance (bit0) + accumulated torque (bit2) + crank data (bit5)
    flags = 0x0001 | 0x0004 | 0x0020
    frame = struct.pack("<Hh", flags, 251) + bytes([50]) + struct.pack("<H", 1234)
    frame += struct.pack("<HH", 812, 40000)
    cp = bp.parse_cycling_power(frame)
    assert (cp.power_w, cp.crank_revs, cp.crank_event_time) == (251, 812, 40000)


def test_cycling_power_without_crank_data():
    cp = bp.parse_cycling_power(struct.pack("<Hh", 0, 180))
    assert cp.power_w == 180 and cp.crank_revs is None


def test_crank_cadence_rollover_and_stall():
    c = bp.CrankCadence(stall_s=3.0)
    c.update(65535, 65000, now=0.0)
    # 1 rev in 0.667 s (683/1024 s) across both rollovers -> ~90 rpm
    assert c.update(0, (65000 + 683) % 65536, now=0.7) == pytest.approx(89.96, abs=0.1)
    # sensor repeats the same values: cadence kept, then 0 after 3 s
    assert c.update(0, (65000 + 683) % 65536, now=2.0) == pytest.approx(89.96, abs=0.1)
    assert c.update(0, (65000 + 683) % 65536, now=4.0) == 0.0
    assert c.stalled(now=4.0)


def test_indoor_bike_data_typical_frame():
    # speed present (bit0 clear), cadence (bit2), power (bit6), heart rate (bit9)
    flags = 0x0004 | 0x0040 | 0x0200
    frame = struct.pack("<HHHhB", flags, 3215, 180, 245, 151)
    d = bp.parse_indoor_bike_data(frame)
    assert d.speed_kmh == pytest.approx(32.15)
    assert d.cadence_rpm == pytest.approx(90.0)
    assert (d.power_w, d.heart_rate) == (245, 151)


def test_indoor_bike_data_skips_optional_fields_before_power():
    # avg speed, avg cadence, distance (uint24), resistance before power
    flags = 0x0002 | 0x0004 | 0x0008 | 0x0010 | 0x0020 | 0x0040
    frame = struct.pack("<HHHHH", flags, 3000, 2900, 170, 168) + (12345).to_bytes(3, "little")
    frame += struct.pack("<hh", 20, 210)
    d = bp.parse_indoor_bike_data(frame)
    assert d.cadence_rpm == pytest.approx(85.0) and d.power_w == 210


def test_indoor_bike_data_more_data_and_truncated():
    d = bp.parse_indoor_bike_data(struct.pack("<H", 0x0001))  # more data: no speed field
    assert d.speed_kmh is None and d.power_w is None
    d = bp.parse_indoor_bike_data(struct.pack("<HH", 0x0040, 3000))  # power announced, missing
    assert d.speed_kmh == pytest.approx(30.0) and d.power_w is None


def test_ftms_control_point_commands():
    assert bp.ftms_request_control() == b"\x00"
    assert bp.ftms_start() == b"\x07"
    assert bp.ftms_set_target_power(250) == bytes([0x05, 0xFA, 0x00])
    sim = bp.ftms_set_simulation(grade=0.05, crr=0.004, cw_kg_m=0.51)
    assert sim == struct.pack("<BhhBB", 0x11, 0, 500, 40, 51)
    assert bp.parse_control_point_response(bytes([0x80, 0x05, 0x01])) == (0x05, "success")
    assert bp.parse_control_point_response(bytes([0x80, 0x00, 0x05]))[1] == "control not permitted"
    assert bp.parse_control_point_response(b"\x05\xfa\x00") is None
