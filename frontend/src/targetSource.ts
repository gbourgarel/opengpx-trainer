// What sets the trainer target right now, and which value the ride controls and the ↑ / ↓ keys
// change for it. Pure functions (checked with a Node script, no test runner in the frontend).
//
// * ERG ride: the workout (× intensity).
// * GPX ride, manual mode: the rider's watts (also overrides a workout that is not over).
// * GPX + workout while it lasts: the workout (× intensity), except in its free-ride steps
//   (no target of their own), where the slope curve (× effort) sets it.
// * GPX ride without workout, or once the workout is over: the slope curve (× effort).
import type { Step } from './api'

export type TargetSource = 'workout' | 'free-ride' | 'slope' | 'manual'

export function targetSource(o: {
  mode?: 'erg' | 'gpx'
  targetMode?: 'slope' | 'manual'
  manualTargetW?: number | null
  /** the ride has a workout that is not over yet */
  workoutActive: boolean
  /** the workout step being ridden */
  step?: Step
}): TargetSource {
  if (o.mode === 'erg') return 'workout'
  if (o.targetMode === 'manual' && o.manualTargetW != null) return 'manual'
  if (o.workoutActive) return o.step && o.step.start == null ? 'free-ride' : 'workout'
  return 'slope'
}

/** Where the target comes from, in a few words (under the power dial). */
export const SOURCE_LABEL: Record<TargetSource, string> = {
  workout: 'from the workout',
  'free-ride': 'free-ride step: from the slope',
  slope: 'from the slope',
  manual: 'set by hand',
}

export type KeyField = 'intensity_pct' | 'effort_pct' | 'manual_target_w'

/** The value ↑ / ↓ change: the one of the current target source. */
export function keyField(source: TargetSource): { field: KeyField; step: number; lo: number; hi: number } {
  if (source === 'workout') return { field: 'intensity_pct', step: 1, lo: 10, hi: 200 }
  if (source === 'manual') return { field: 'manual_target_w', step: 5, lo: 0, hi: 2000 }
  return { field: 'effort_pct', step: 2, lo: 10, hi: 200 }
}

const KEY_HELP: Record<KeyField, string> = { intensity_pct: 'intensity', effort_pct: 'effort', manual_target_w: 'target ±5 W' }

export function shortcutsHelp(source: TargetSource, opts: { sound: boolean; immersive: boolean }): string {
  return [
    'Space pause/resume',
    `↑↓ ${KEY_HELP[keyField(source).field]}`,
    ...(opts.sound ? ['M sound'] : []),
    ...(opts.immersive ? ['V 3D view'] : []),
  ].join(' · ')
}
