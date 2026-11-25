"""The sensors of a ride declared in the FIT file (device_info), like a Garmin head unit:
another app reading our FIT checks that HR comes from the strap and power from the pedals."""

import pytest
from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage

from opengpx_trainer.ant import profiles as pf
from opengpx_trainer.ant.profiles import SensorIdentity
from opengpx_trainer.recording import Recorder, Sample

# pages from the ride of 2026-11-22 (raw ANT+ log)
TACX_80 = [80, 255, 255, 1, 89, 0, 84, 11]
TACX_81 = [81, 255, 3, 40, 240, 158, 0, 0]
ASSIOMA_80 = [80, 255, 255, 4, 7, 1, 12, 0]
ASSIOMA_81 = [81, 255, 40, 62, 128, 44, 194, 247]
ASSIOMA_82 = [82, 255, 1, 32, 241, 0, 199, 179]
POLAR_2 = [2, 123, 198, 43, 0, 0, 0, 0]
POLAR_3 = [131, 1, 11, 4, 0, 0, 0, 0]  # page 3, toggle bit set
POLAR_7 = [7, 60, 255, 63, 0, 0, 0, 0]


def identity(*parts) -> SensorIdentity:
    i = SensorIdentity()
    for p in parts:
        i.merge(p)
    return i


def test_common_pages_of_the_trainer_and_the_pedals():
    tacx = identity(pf.decode_common(TACX_80), pf.decode_common(TACX_81))
    assert (tacx.manufacturer, tacx.product, tacx.hardware_version) == (89, 2900, 1)
    assert (tacx.serial_number, tacx.software_version) == (40688, pytest.approx(4.003))
    pedals = identity(*(pf.decode_common(p) for p in (ASSIOMA_80, ASSIOMA_81, ASSIOMA_82)))
    assert (pedals.manufacturer, pedals.product, pedals.serial_number) == (263, 12, 4156697728)
    assert pedals.software_version == pytest.approx(6.24)
    assert (pedals.battery_voltage, pedals.battery_status) == (3.78, 3)  # 3 + 199/256 V, ok
    assert pf.decode_common([16, 25, 0, 0, 0, 0, 255, 36]) is None  # not an identity page


def test_heart_rate_background_pages():
    polar = identity(*(pf.decode_hrm_info(p, 52100) for p in (POLAR_2, POLAR_3, POLAR_7)))
    assert (polar.manufacturer, polar.product, polar.hardware_version) == (123, 4, 1)
    assert polar.serial_number == (11206 << 16) | 52100
    assert polar.software_version == 11
    assert (polar.battery_voltage, polar.battery_status) == (None, 3)  # coarse voltage invalid
    assert pf.decode_hrm_info([4, 0, 0, 0, 0, 0, 0, 0], 52100) is None


def test_a_merge_keeps_what_a_page_does_not_carry():
    i = identity(pf.decode_common(TACX_80))
    i.merge(pf.decode_common(TACX_81))
    assert i.manufacturer == 89 and i.serial_number == 40688


def _ride(rec: Recorder, t0: float) -> None:
    for k in range(10):
        rec.add(Sample(t0 + k, k + 1.0, 200.0, 90.0, 140.0, 8.0, 8.0 * k))


def test_fit_declares_the_app_and_each_sensor(tmp_path):
    t0 = 1_795_000_000.0
    rec = Recorder()
    pedals = identity(*(pf.decode_common(p) for p in (ASSIOMA_80, ASSIOMA_81, ASSIOMA_82)))
    tacx = identity(pf.decode_common(TACX_80))
    for _ in range(3):  # seen at every tick: declared once
        rec.sensor_seen("trainer", "ant", 40688, None, tacx, t0)
        rec.sensor_seen("power_meter", "ant", 63426, None, pedals, t0)
    rec.sensor_seen("heart_rate", "ble", None, "Polar H10 1234", SensorIdentity(), t0 + 5)
    rec.sensor_seen("heart_rate", "sim", 777, None, SensorIdentity(), t0)  # simulator: left out
    tacx.merge(pf.decode_common(TACX_81))  # heard after the ride started: still written
    _ride(rec, t0)
    path = rec.write_fit(tmp_path / "r.fit")
    msgs = [r.message for r in FitFile.from_file(str(path)).records]
    fid = next(m for m in msgs if isinstance(m, FileIdMessage))
    assert fid.product_name == "OpenGPX Trainer"
    infos = [m for m in msgs if isinstance(m, DeviceInfoMessage)]
    assert [m.device_index for m in infos] == [0, 1, 2, 3]
    assert infos[0].product_name == "OpenGPX Trainer"
    trainer, pm, hr = infos[1:]
    assert (trainer.device_type, trainer.ant_device_number) == (17, 40688)
    assert (trainer.manufacturer, trainer.product, trainer.serial_number) == (89, 2900, 40688)
    assert (pm.device_type, pm.manufacturer, pm.serial_number) == (11, 263, 4156697728)
    assert pm.software_version == pytest.approx(6.24)
    assert pm.battery_voltage == pytest.approx(3.78, abs=0.01)
    assert pm.source_type == 1  # antplus
    assert (hr.source_type, hr.product_name) == (3, "Polar H10 1234")  # bluetooth low energy
    assert hr.timestamp == (t0 + 5) * 1000


def test_snapshot_keeps_the_sensors_apart_from_the_live_ride():
    rec = Recorder()
    ident = SensorIdentity(manufacturer=89)
    rec.sensor_seen("trainer", "ant", 1, None, ident, 0.0)
    snap = rec.snapshot()
    ident.manufacturer = 1
    assert snap.sensors[0].identity.manufacturer == 89


def test_ant_hub_learns_who_the_sensors_are():
    from opengpx_trainer.ant.ant_hub import AntHub

    def ext(num: int, dev_type: int) -> list[int]:
        return [0x80, num & 0xFF, num >> 8, dev_type, 5]

    h = AntHub()
    h._on_fec(TACX_80 + ext(40688, 17))
    h._on_fec(TACX_81 + ext(40688, 17))
    h._on_power(ASSIOMA_81 + ext(63426, 11))
    h._on_hrm(POLAR_2 + ext(52100, 120))
    assert h.devices["trainer"].identity.product == 2900
    assert h.devices["trainer"].identity.serial_number == 40688
    assert h.devices["power_meter"].identity.serial_number == 4156697728
    assert h.devices["heart_rate"].identity.manufacturer == 123
    h._on_hrm([0, 0, 0, 0, 0, 0, 0, 80] + ext(11111, 120))  # another strap took the role
    assert h.devices["heart_rate"].identity == SensorIdentity()


# the Assioma near the end of the ride of 2026-11-25: status 4 (low), 3 + 198/256 V
ASSIOMA_82_LOW = [82, 255, 1, 32, 241, 0, 198, 195]


def test_hub_status_shows_the_latest_battery_report():
    from opengpx_trainer.ant.ant_hub import AntHub

    ext = [0x80, 63426 & 0xFF, 63426 >> 8, 11, 5]
    h = AntHub()
    assert h.status()["power_meter"]["battery"] == {"status": None, "voltage": None, "level": None}
    h._on_power(ASSIOMA_82 + ext)
    assert h.status()["power_meter"]["battery"]["status"] == 3
    h._on_power(ASSIOMA_82_LOW + ext)
    bat = h.status()["power_meter"]["battery"]
    assert (bat["status"], bat["voltage"]) == (4, pytest.approx(3.77, abs=0.01))


def test_ble_battery_level_written_in_the_fit(tmp_path):
    from opengpx_trainer.ble import protocols as bp

    assert bp.parse_battery_level(b"\x0f") == 15
    assert bp.parse_battery_level(b"") is None
    assert bp.parse_battery_level(b"\xff") is None  # not a percentage
    t0 = 1_795_000_000.0
    rec = Recorder()
    rec.sensor_seen("power_meter", "ble", None, "ASSIOMA", SensorIdentity(battery_level=15), t0)
    _ride(rec, t0)
    msgs = [r.message for r in FitFile.from_file(str(rec.write_fit(tmp_path / "r.fit"))).records]
    pm = [m for m in msgs if isinstance(m, DeviceInfoMessage)][1]
    assert pm.battery_level == 15


def test_simulator_can_report_a_low_power_meter_battery():
    from opengpx_trainer.ant.simulator import SimulatedHub

    h = SimulatedHub()
    h.step()
    assert h.status()["power_meter"]["battery"]["status"] == 3
    h.update_settings(pm_battery_low=True)
    h.step()
    assert h.status()["power_meter"]["battery"]["status"] == 4
