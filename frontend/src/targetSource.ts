// What sets the trainer target right now, and which value the ride controls and the ↑ / ↓ keys
// change for it. Pure functions (checked with a Node script, no test runner in the frontend).
//
// * ERG ride: the workout (× intensity).
// * GPX ride, manual mode: the rider's watts (also overrides a workout that is not over).
// * GPX + workout while it lasts: the workout (× intensity), except in its free-ride steps
//   (no target of their own), where the slope curve (× effort) sets it.
// * GPX ride without workout, or once the workout is over: the slope curve (× effort), or in
//   Sim mode no target: the trainer simulates the grade (× trainer effect) and the rider
//   shifts. A GPX + workout ride keeps the workout's targets until it is over, even in Sim.
import type { Step } from './api'

export type TargetSource = 'workout' | 'free-ride' | 'slope' | 'manual' | 'sim'

export function targetSource(o: {
  mode?: 'erg' | 'gpx'
  targetMode?: 'slope' | 'manual' | 'sim'
  manualTargetW?: number | null
  /** the ride has a workout that is not over yet */
  workoutActive: boolean
  /** the workout step being ridden */
  step?: Step
}): TargetSource {
  if (o.mode === 'erg') return 'workout'
  if (o.targetMode === 'manual' && o.manualTargetW != null) return 'manual'
  if (o.workoutActive) return o.step && o.step.start == null ? 'free-ride' : 'workout'
  return o.targetMode === 'sim' ? 'sim' : 'slope'
}

/** Where the target comes from, in a few words (under the power dial). */
export const SOURCE_LABEL: Record<TargetSource, string> = {
  workout: 'from the workout',
  'free-ride': 'free-ride step: Slope ERG',
  slope: 'Slope ERG',
  manual: 'set by hand',
  sim: 'Sim: the trainer follows the grade',
}

export type KeyField = 'intensity_pct' | 'effort_pct' | 'manual_target_w' | 'trainer_effect_pct'

/** Step and bounds of each value changed by ↑ / ↓ and the +/− buttons. */
export const FIELD_STEP: Record<KeyField, { step: number; lo: number; hi: number }> = {
  intensity_pct: { step: 1, lo: 10, hi: 200 },
  effort_pct: { step: 2, lo: 10, hi: 200 },
  manual_target_w: { step: 5, lo: 0, hi: 2000 },
  trainer_effect_pct: { step: 10, lo: 0, hi: 100 },
}

/** The value ↑ / ↓ change: the one of the current target source. */
export function keyField(source: TargetSource): KeyField {
  if (source === 'workout') return 'intensity_pct'
  if (source === 'manual') return 'manual_target_w'
  if (source === 'sim') return 'trainer_effect_pct'
  return 'effort_pct'
}

const KEY_HELP: Record<KeyField, string> = {
  intensity_pct: 'intensity',
  effort_pct: 'effort',
  manual_target_w: 'target ±5 W',
  trainer_effect_pct: 'trainer effect',
}

export function shortcutsHelp(source: TargetSource, opts: { sound: boolean; immersive: boolean }): string {
  return [
    'Space pause/resume',
    `↑↓ ${KEY_HELP[keyField(source)]}`,
    ...(opts.sound ? ['M sound'] : []),
    ...(opts.immersive ? ['V 3D view'] : []),
  ].join(' · ')
}
