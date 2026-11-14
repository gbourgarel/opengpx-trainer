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
  'free-ride': 'free-ride step: Slope ERG',
  slope: 'Slope ERG',
  manual: 'set by hand',
}

export type KeyField = 'intensity_pct' | 'effort_pct' | 'manual_target_w'

/** Step and bounds of each value changed by ↑ / ↓ and the +/− buttons. */
export const FIELD_STEP: Record<KeyField, { step: number; lo: number; hi: number }> = {
  intensity_pct: { step: 1, lo: 10, hi: 200 },
  effort_pct: { step: 2, lo: 10, hi: 200 },
  manual_target_w: { step: 5, lo: 0, hi: 2000 },
}

/** The value ↑ / ↓ change: the one of the current target source. */
export function keyField(source: TargetSource): KeyField {
  if (source === 'workout') return 'intensity_pct'
  if (source === 'manual') return 'manual_target_w'
  return 'effort_pct'
}

const KEY_HELP: Record<KeyField, string> = { intensity_pct: 'intensity', effort_pct: 'effort', manual_target_w: 'target ±5 W' }

export function shortcutsHelp(source: TargetSource, opts: { sound: boolean; immersive: boolean }): string {
  return [
    'Space pause/resume',
    `↑↓ ${KEY_HELP[keyField(source)]}`,
    ...(opts.sound ? ['M sound'] : []),
    ...(opts.immersive ? ['V 3D view'] : []),
  ].join(' · ')
}
