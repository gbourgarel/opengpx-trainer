import assert from 'node:assert/strict'
import type { CalibrationInfo, DeviceStatus } from '../src/api'
import { calibrationView, canCalibrate, followedRun, lastCalibrationText, requestedCalibrations } from '../src/calibration'

const cal = (over: Partial<CalibrationInfo>): CalibrationInfo => ({
  role: 'trainer',
  kind: 'spin_down',
  phase: 'requesting',
  active: true,
  message: '',
  target_speed_kmh: null,
  temperature_c: null,
  spin_down_ms: null,
  zero_offset: null,
  started_at: 1000,
  finished_at: null,
  ...over,
})
const dev = (over: Partial<DeviceStatus>): DeviceStatus => ({
  connected: true,
  transport: 'ant',
  device_number: 1,
  ble_id: null,
  name: null,
  wanted: null,
  ...over,
})

export const checks = {
  'only connected ANT+ (or simulated) sensors can be calibrated': () => {
    assert.equal(canCalibrate(dev({})), true)
    assert.equal(canCalibrate(dev({ transport: 'sim' })), true)
    assert.equal(canCalibrate(dev({ transport: 'ble' })), false)
    assert.equal(canCalibrate(dev({ connected: false })), false)
    assert.equal(canCalibrate(undefined), false)
  },
  'a calibration is suggested when the device asks and none is running': () => {
    const devices = {
      trainer: dev({ calibration_requested: true }),
      power_meter: dev({ calibration_requested: false }),
      heart_rate: dev({ calibration_requested: true }), // never a calibration role
    }
    assert.deepEqual(requestedCalibrations(devices), ['trainer'])
    assert.deepEqual(requestedCalibrations({ trainer: dev({ calibration_requested: true, calibration: cal({}) }) }), [])
    assert.deepEqual(requestedCalibrations({ trainer: dev({ calibration_requested: true, transport: 'ble' }) }), [])
    assert.deepEqual(requestedCalibrations(undefined), [])
  },
  'no nudge once the last calibration succeeded, again after a failure': () => {
    const after = (phase: CalibrationInfo['phase']) => ({ trainer: dev({ calibration_requested: true, calibration: cal({ phase, active: false, finished_at: 1100 }) }) })
    assert.deepEqual(requestedCalibrations(after('done')), [])
    assert.deepEqual(requestedCalibrations(after('failed')), ['trainer'])
    assert.deepEqual(requestedCalibrations(after('cancelled')), ['trainer'])
  },
  'the dialog follows its own run, never the previous result': () => {
    const previous = cal({ phase: 'done', active: false, started_at: 900, finished_at: 950, spin_down_ms: 9000 })
    const started = cal({ started_at: 1000 })
    assert.equal(followedRun(dev({ calibration: previous }), started), started)
    const live = cal({ started_at: 1000, phase: 'speed_up' })
    assert.equal(followedRun(dev({ calibration: live }), started), live)
    assert.equal(followedRun(dev({ calibration: live }), null), null)
  },
  'spin-down steps follow the phases': () => {
    const v = (over: Partial<CalibrationInfo>) => calibrationView(cal(over))
    assert.equal(v({}).step, 0)
    const up = v({ phase: 'speed_up', target_speed_kmh: 32, speed_kmh: 16 })
    assert.equal(up.progress, 0.5)
    assert.match(up.text, /32 km\/h/)
    assert.equal(v({ phase: 'speed_up', target_speed_kmh: 32, speed_kmh: 40 }).progress, 1)
    assert.equal(v({ phase: 'coast' }).step, 1)
    const done = v({ phase: 'done', active: false, spin_down_ms: 9840 })
    assert.equal(done.tone, 'ok')
    assert.match(done.text, /9\.8 s/)
    const noTime = v({ phase: 'done', active: false, spin_down_ms: null })
    assert.equal(noTime.tone, 'ok')
    assert.equal(noTime.text, 'Spin-down done.')
    const failed = v({ phase: 'failed', active: false, message: 'The trainer does not answer.' })
    assert.equal(failed.tone, 'error')
    assert.equal(failed.text, 'The trainer does not answer.')
    assert.equal(failed.steps.length, 3)
  },
  'zero offset steps': () => {
    const z = (over: Partial<CalibrationInfo>) => calibrationView(cal({ role: 'power_meter', kind: 'zero_offset', phase: 'zeroing', ...over }))
    assert.equal(z({}).step, 0)
    const done = z({ phase: 'done', active: false, zero_offset: -3 })
    assert.equal(done.step, 1)
    assert.match(done.text, /-3/)
  },
  'last result line only for finished runs': () => {
    assert.equal(lastCalibrationText(cal({})), null)
    assert.equal(lastCalibrationText(null), null)
    const t = new Date(2026, 10, 19, 18, 5).getTime() / 1000
    assert.equal(lastCalibrationText(cal({ phase: 'done', active: false, finished_at: t, spin_down_ms: 9840 })), 'last: 18:05 · 9.8 s')
    assert.equal(lastCalibrationText(cal({ phase: 'done', active: false, finished_at: t })), 'last: 18:05 · done')
    assert.equal(lastCalibrationText(cal({ kind: 'zero_offset', phase: 'done', active: false, finished_at: t, zero_offset: 0 })), 'last: 18:05 · offset 0')
    assert.equal(lastCalibrationText(cal({ phase: 'failed', active: false, finished_at: t })), 'last: 18:05 · failed')
    assert.equal(lastCalibrationText(cal({ phase: 'cancelled', active: false, finished_at: t })), null)
  },
}
