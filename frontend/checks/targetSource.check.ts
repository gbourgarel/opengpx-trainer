import assert from 'node:assert/strict'
import { FIELD_STEP, keyField, targetSource } from '../src/targetSource'

const free = { start: null } as never // a free-ride step (no target of its own)
const steady = { start: 0.8 } as never

export const checks = {
  'Sim on a GPX ride: no target, the arrows change the trainer effect': () => {
    const src = targetSource({ mode: 'gpx', targetMode: 'sim', workoutActive: false })
    assert.equal(src, 'sim')
    assert.equal(keyField(src), 'trainer_effect_pct')
    assert.deepEqual(FIELD_STEP.trainer_effect_pct, { step: 10, lo: 0, hi: 100 })
  },
  'Sim keeps the workout targets while the workout lasts': () => {
    assert.equal(targetSource({ mode: 'gpx', targetMode: 'sim', workoutActive: true, step: steady }), 'workout')
    assert.equal(targetSource({ mode: 'gpx', targetMode: 'sim', workoutActive: true, step: free }), 'free-ride')
  },
  'the other sources are unchanged': () => {
    assert.equal(targetSource({ mode: 'erg', targetMode: 'sim', workoutActive: true }), 'workout')
    assert.equal(targetSource({ mode: 'gpx', targetMode: 'slope', workoutActive: false }), 'slope')
    assert.equal(targetSource({ mode: 'gpx', targetMode: 'manual', manualTargetW: 200, workoutActive: true }), 'manual')
  },
}
