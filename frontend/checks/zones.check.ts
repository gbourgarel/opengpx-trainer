import assert from 'node:assert/strict'
import { hrZone, powerZone, powerZoneOfFraction } from '../src/zones'

export const checks = {
  'Coggan power zones at their bounds': () => {
    const n = (f: number) => powerZoneOfFraction(f).n
    assert.deepEqual([0.3, 0.549, 0.55, 0.749, 0.75, 0.899, 0.9, 1.049, 1.05, 1.199, 1.2, 1.499, 1.5, 3].map(n), [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7])
    assert.equal(powerZone(250, 250)?.name, 'Threshold')
    assert.equal(powerZone(250, 0), null)
    assert.equal(powerZone(null, 250), null)
  },
  'Friel heart-rate zones as % of the threshold': () => {
    const n = (bpm: number) => hrZone(bpm, 165)?.n
    // 81 % = 133.65, 90 % = 148.5, 94 % = 155.1, 100 % = 165
    assert.deepEqual([120, 133, 134, 148, 149, 155, 156, 164, 165, 180].map(n), [1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    assert.equal(hrZone(150, null), null) // no threshold set: no colour
    assert.equal(hrZone(0, 165), null)
  },
  'every zone has its colour variable': () => {
    for (let f = 0.1; f < 2; f += 0.05) assert.match(powerZoneOfFraction(f).color, /^var\(--z[1-7]\)$/)
  },
}
