/** Power vs target zone: on target within ±max(5 %, 5 W), slightly high/low within
 *  ±max(10 %, 10 W), beyond that too high/low. Used by the ride screen's power dial. */
export type TargetZone = 'on' | 'high' | 'too-high' | 'low' | 'too-low'

export function targetZone(power: number, target: number): TargetZone {
  const d = power - target
  const ok = Math.max(0.05 * target, 5)
  const warn = Math.max(0.1 * target, 10)
  if (Math.abs(d) <= ok) return 'on'
  if (d > 0) return d <= warn ? 'high' : 'too-high'
  return -d <= warn ? 'low' : 'too-low'
}
