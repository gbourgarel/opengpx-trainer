import assert from 'node:assert/strict'
import { cuesBetween, type Cue, type CueState } from '../src/stepCues'

/** Telemetry every 250 ms from `from` s before a step change, through the change. */
function ride(from: number, opts: { target: number; next: number; jitter?: boolean }): CueState[] {
  const out: CueState[] = []
  for (let t = from; t >= -1; t -= 0.25) {
    const step = t > 0 ? 1 : 2
    const remaining = t > 0 ? t : 60 + t
    const s: CueState = { session: 'a', state: 'running', step, remaining, target: step === 1 ? opts.target : opts.next, next: step === 1 ? opts.next : 100 }
    out.push(s)
    if (opts.jitter) out.push({ ...s }) // the same sample twice (two ticks, one telemetry)
  }
  return out
}

function cues(seq: CueState[]): Cue[] {
  const out: Cue[] = []
  for (let i = 1; i < seq.length; i++) out.push(...cuesBetween(seq[i - 1], seq[i]))
  return out
}

export const checks = {
  'one 3-2-1 and one cue per step change': () => {
    assert.deepEqual(cues(ride(5, { target: 200, next: 150 })), ['tick', 'tick', 'tick', 'change'])
  },
  'a rising target gets the rising cue': () => {
    assert.deepEqual(cues(ride(5, { target: 150, next: 250 })), ['tick', 'tick', 'tick', 'rise'])
  },
  'repeated samples never beep twice': () => {
    assert.deepEqual(cues(ride(5, { target: 200, next: 150, jitter: true })), ['tick', 'tick', 'tick', 'change'])
  },
  'nothing across a different session or when paused': () => {
    const a: CueState = { session: 'a', state: 'running', step: 1, remaining: 3.1, target: 200, next: 150 }
    assert.deepEqual(cuesBetween(a, { ...a, session: 'b', remaining: 2.9 }), [])
    assert.deepEqual(cuesBetween(a, { ...a, state: 'paused', remaining: 2.9 }), [])
  },
}
