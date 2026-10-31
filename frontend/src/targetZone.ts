/** Power vs target zone; see TargetGauge for the thresholds. */
export type TargetZone = 'on' | 'high' | 'too-high' | 'low' | 'too-low'

export function targetZone(power: number, target: number): TargetZone {
  const d = power - target
  const ok = Math.max(0.05 * target, 5)
  const warn = Math.max(0.1 * target, 10)
  if (Math.abs(d) <= ok) return 'on'
  if (d > 0) return d <= warn ? 'high' : 'too-high'
  return -d <= warn ? 'low' : 'too-low'
}
