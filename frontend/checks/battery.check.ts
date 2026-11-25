import assert from 'node:assert/strict'
import type { BatteryInfo, DeviceStatus } from '../src/api'
import { lowBatteries } from '../src/battery'

const dev = (battery?: Partial<BatteryInfo>): DeviceStatus => ({
  connected: true,
  transport: 'ant',
  device_number: 1,
  ble_id: null,
  name: null,
  wanted: null,
  battery: battery && { status: null, voltage: null, level: null, ...battery },
})

export const checks = {
  'nothing reported, or ok: no warning': () => {
    assert.deepEqual(lowBatteries(undefined), [])
    assert.deepEqual(lowBatteries({ trainer: dev(), power_meter: dev({}) }), [])
    assert.deepEqual(lowBatteries({ power_meter: dev({ status: 3, voltage: 3.86 }), heart_rate: dev({ level: 21 }) }), [])
  },
  'ANT+ status low / critical (the Assioma of 2026-11-25: status 4, 3.77 V)': () => {
    const [b] = lowBatteries({ power_meter: dev({ status: 4, voltage: 3.7734 }) })
    assert.equal(b.role, 'power_meter')
    assert.equal(b.critical, false)
    assert.equal(b.text, 'Power meter: battery low (3.77 V)')
    assert.equal(lowBatteries({ heart_rate: dev({ status: 5 }) })[0].text, 'Heart-rate strap: battery critical')
  },
  'Bluetooth level: low at 20 % or less, critical at 5 % or less': () => {
    assert.equal(lowBatteries({ power_meter: dev({ level: 20 }) })[0].text, 'Power meter: battery low (20 %)')
    assert.equal(lowBatteries({ power_meter: dev({ level: 5 }) })[0].critical, true)
  },
  'several sensors: trainer, power meter, heart rate order': () => {
    const roles = lowBatteries({ heart_rate: dev({ status: 4 }), power_meter: dev({ status: 4 }), trainer: dev({ level: 3 }) }).map((b) => b.role)
    assert.deepEqual(roles, ['trainer', 'power_meter', 'heart_rate'])
  },
}
