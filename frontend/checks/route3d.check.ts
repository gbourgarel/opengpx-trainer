import assert from 'node:assert/strict'
import { followPosition } from '../src/scenery/route3d'

/** Rider shown on the 3D route between 4 Hz telemetry samples (60 fps frames). */
function follow(total: number, samples: { s: number; v: number }[]): number[] {
  const shown: number[] = []
  let pos: number | null = null
  for (const t of samples) {
    for (let f = 0; f < 15; f++) {
      pos = followPosition(pos, { s: t.s, v: t.v, ageS: f / 60 }, 1 / 60, total)
      shown.push(pos)
    }
  }
  return shown
}

export const checks = {
  'never off the route': () => {
    const shown = follow(1000, Array.from({ length: 40 }, (_, i) => ({ s: Math.min(980 + i * 3, 1000), v: 12 })))
    assert.ok(shown.every((p) => p >= 0 && p <= 1000), 'position outside [0, total]')
  },
  'tracks the telemetry without drifting': () => {
    const samples = Array.from({ length: 80 }, (_, i) => ({ s: 100 + i * 2.5, v: 10 }))
    const shown = follow(10_000, samples)
    const last = samples[samples.length - 1]
    assert.ok(Math.abs(shown[shown.length - 1] - (last.s + last.v * 14 / 60)) < 1, 'drifted from the telemetry')
  },
  'moves forward at constant speed (no jumps back)': () => {
    const shown = follow(10_000, Array.from({ length: 40 }, (_, i) => ({ s: 100 + i * 2.5, v: 10 })))
    for (let i = 1; i < shown.length; i++) assert.ok(shown[i] >= shown[i - 1] - 0.01, `backwards at frame ${i}`)
  },
  'a new lap restarts from the telemetry': () => {
    const shown = follow(1000, [{ s: 990, v: 10 }, { s: 5, v: 10 }])
    assert.ok(shown[15] < 50, 'did not restart at the new lap')
  },
}
