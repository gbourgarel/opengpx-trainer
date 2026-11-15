import assert from 'node:assert/strict'
import { nudgeBase, nudgedValue, type Pending } from '../src/rideKeys'

/** Rapid presses (↑ / ↓ keys and the +/− buttons) with telemetry lagging behind. */
function presses(telValue: number, field: Pending['field'], ups: boolean[], gapMs: number): number[] {
  let pending: Pending | null = null
  const sent: number[] = []
  ups.forEach((up, i) => {
    const now = i * gapMs
    const value = nudgedValue(nudgeBase(pending, field, now, telValue), field, up)
    pending = { field, value, at: now }
    sent.push(value)
  })
  return sent
}

export const checks = {
  'rapid presses add up before the telemetry catches up': () => {
    assert.deepEqual(presses(100, 'intensity_pct', [true, true, true], 100), [101, 102, 103])
    assert.deepEqual(presses(100, 'effort_pct', [true, true, false], 100), [102, 104, 102])
  },
  'after 1.5 s the telemetry is the base again': () => {
    const pending: Pending = { field: 'effort_pct', value: 120, at: 0 }
    assert.equal(nudgeBase(pending, 'effort_pct', 1000, 100), 120)
    assert.equal(nudgeBase(pending, 'effort_pct', 2000, 100), 100)
    assert.equal(nudgeBase(pending, 'intensity_pct', 1000, 100), 100) // another field
  },
  'a typed value goes to the next multiple of the step': () => {
    assert.equal(nudgedValue(203, 'manual_target_w', true), 205)
    assert.equal(nudgedValue(203, 'manual_target_w', false), 200)
    assert.equal(nudgedValue(205, 'manual_target_w', true), 210)
  },
  'values stay within bounds': () => {
    assert.equal(nudgedValue(10, 'effort_pct', false), 10)
    assert.equal(nudgedValue(200, 'intensity_pct', true), 200)
    assert.equal(nudgedValue(0, 'manual_target_w', false), 0)
  },
}
