import assert from 'node:assert/strict'
import { clampStart, indexAt, nearestIndex, startFromProfile } from '../src/routeStart'

export const checks = {
  'a start always leaves at least 100 m to ride': () => {
    assert.equal(clampStart(5000, 8000), 5000)
    assert.equal(clampStart(7990, 8000), 7900)
    assert.equal(clampStart(-20, 8000), 0)
    assert.equal(clampStart(50, 80), 0) // shorter than 100 m: from the start
    assert.equal(clampStart(Number.NaN, 8000), 0)
  },
  'a click on the profile maps its width onto the route': () => {
    assert.equal(startFromProfile(0.5, 8000), 4000)
    assert.equal(startFromProfile(1.2, 8000), 7900)
    assert.equal(startFromProfile(-0.1, 8000), 0)
  },
  'a click on the map picks the nearest route point': () => {
    const pts: [number, number][] = [
      [45.0, 6.0],
      [45.001, 6.0],
      [45.002, 6.0],
      [45.002, 6.002],
    ]
    assert.equal(nearestIndex(pts, [45.0011, 6.0001]), 1)
    assert.equal(nearestIndex(pts, [45.0021, 6.0019]), 3)
  },
  'the map draws up to the first point at or beyond a distance': () => {
    assert.equal(indexAt([0, 10, 20, 30], 15), 2)
    assert.equal(indexAt([0, 10, 20, 30], 99), 3)
    assert.equal(indexAt([0, 10, 20, 30], 0), 0)
  },
}
