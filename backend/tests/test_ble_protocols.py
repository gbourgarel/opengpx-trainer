"""BLE GATT profile decoding/encoding (frames built by hand from the Bluetooth specs)."""

import struct

import pytest

from opengpx_trainer.ble import protocols as bp


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
    assert cp.power_w == 180 and cp.crank_revs is None and cp.balance is None


def test_cycling_power_balance_as_the_fit_byte():
    # 96 half-percent = 48 % for the left leg (reference bit set): right 52 % -> 0x80 | 52
    left = bp.parse_cycling_power(struct.pack("<Hh", 0x0003, 200) + bytes([96]))
    assert left.balance == 0x80 | 52
    # reference unknown: the share of an unknown side, bit 7 clear (FIT convention)
    unknown = bp.parse_cycling_power(struct.pack("<Hh", 0x0001, 200) + bytes([96]))
    assert unknown.balance == 48
    assert bp.parse_cycling_power(struct.pack("<Hh", 0x0001, 200) + bytes([0xFF])).balance is None


def test_heart_rate_rr_intervals():
    # flags: R-R present (bit 4) + energy expended (bit 3): HR, energy, then 2 intervals
    frame = bytes([0x18, 72]) + struct.pack("<H", 15) + struct.pack("<HH", 850, 870)
    assert bp.parse_rr_intervals(frame) == pytest.approx([850 / 1024, 870 / 1024])
    assert bp.parse_heart_rate(frame) == 72
    sixteen = bytes([0x11]) + struct.pack("<H", 72) + struct.pack("<H", 1024)
    assert bp.parse_rr_intervals(sixteen) == [1.0]
    assert bp.parse_rr_intervals(bytes([0x10, 72]) + struct.pack("<H", 100)) == []  # 0.1 s
    assert bp.parse_rr_intervals(bytes([0x00, 72])) == []


def test_ftms_supported_power_range_bounds_the_targets():
    rng = bp.parse_supported_power_range(struct.pack("<hhH", 0, 1500, 1))
    assert rng == bp.PowerRange(0, 1500, 1)
    assert rng.clamp(2000) == 1500 and rng.clamp(-5) == 0 and rng.clamp(250) == 250
    assert bp.parse_supported_power_range(b"\x00\x00") is None
    assert bp.parse_supported_power_range(struct.pack("<hhH", 500, 100, 1)) is None


def test_ble_hub_clamps_targets_to_the_power_range():
    from opengpx_trainer.ble.ble_hub import BleHub

    h = BleHub({"trainer": ("T", "Flux"), "power_meter": ("P", "Assioma")})
    h.set_target_power(2500)
    assert h._command == bp.ftms_set_target_power(2500)  # no range read: as it is
    h.power_range = bp.PowerRange(0, 1500, 1)
    h.set_target_power(2500)
    assert h._command == bp.ftms_set_target_power(1500)


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


def test_ble_hub_reads_then_follows_the_battery_level():
    import asyncio

    from opengpx_trainer.ble.ble_hub import BleDevice, BleHub

    class Client:
        notify = None

        async def read_gatt_char(self, uuid):
            assert uuid == bp.BATTERY_LEVEL
            return bytearray([42])

        async def start_notify(self, uuid, cb):
            self.notify = cb

    h = BleHub({"power_meter": ("P", "Assioma")})
    c = Client()
    asyncio.run(h._battery(c, BleDevice("P", "Assioma", {"power_meter"})))
    assert h.status()["power_meter"]["battery"]["level"] == 42
    c.notify(None, bytearray([18]))
    assert h.status()["power_meter"]["battery"]["level"] == 18

    class NoBattery(Client):
        async def read_gatt_char(self, uuid):
            raise RuntimeError("characteristic not found")

    h = BleHub({"heart_rate": ("H", "Polar")})
    asyncio.run(h._battery(NoBattery(), BleDevice("H", "Polar", {"heart_rate"})))
    assert h.status()["heart_rate"]["battery"]["level"] is None
