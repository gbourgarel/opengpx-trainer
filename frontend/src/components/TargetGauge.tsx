import { targetZone, type TargetZone } from '../targetZone'

/**
 * Power vs target indicator.
 *
 * Deviation = (P_avg3s − target) / target. Zones (with an absolute floor so low targets are
 * not hypersensitive):
 *   |Δ| ≤ max(5 %, 5 W)  → on target (green)
 *   |Δ| ≤ max(10 %, 10 W) → slightly high (amber) / slightly low (light blue)
 *   beyond               → too high (red)   / too low (blue)
 */

const RANGE = 0.2 // gauge spans −20 % … +20 %

const LABEL: Record<TargetZone, string> = {
  on: 'On target',
  high: 'Slightly high',
  'too-high': 'Too high — ease off',
  low: 'Slightly low',
  'too-low': 'Too low — push',
}

export function TargetGauge({ power, target }: { power: number | null | undefined; target: number | null | undefined }) {
  if (target == null || target <= 0) return null
  const p = power ?? 0
  const zone = targetZone(p, target)
  const dev = (p - target) / target
  const pos = 50 + (Math.max(-RANGE, Math.min(RANGE, dev)) / RANGE) * 50 // % across the bar
  const okPct = (Math.max(0.05, 5 / target) / RANGE) * 50
  const warnPct = (Math.max(0.1, 10 / target) / RANGE) * 50
  const clamp = (x: number) => Math.max(0, Math.min(50, x))
  const dW = Math.round(p - target)

  return (
    <div className={`gauge card zone-${zone}`}>
      <div className="gauge-head">
        <span className="gauge-label">
          {zone === 'on' ? '●' : dev > 0 ? '▲' : '▼'} {LABEL[zone]}
        </span>
        <span className="gauge-delta">
          {dW > 0 ? '+' : ''}
          {dW} W ({dev > 0 ? '+' : ''}
          {(dev * 100).toFixed(0)} %)
        </span>
        <span className="muted">
          3 s avg {Math.round(p)} W · target {Math.round(target)} W
        </span>
      </div>
    <div className="gauge-track">
      <div className="gauge-bar">
        {/* zone bands, symmetric around the centre */}
        <div className="band too-low" style={{ left: 0, width: `${50 - clamp(warnPct)}%` }} />
        <div className="band low" style={{ left: `${50 - clamp(warnPct)}%`, width: `${clamp(warnPct) - clamp(okPct)}%` }} />
        <div className="band on" style={{ left: `${50 - clamp(okPct)}%`, width: `${2 * clamp(okPct)}%` }} />
        <div className="band high" style={{ left: `${50 + clamp(okPct)}%`, width: `${clamp(warnPct) - clamp(okPct)}%` }} />
        <div className="band too-high" style={{ left: `${50 + clamp(warnPct)}%`, width: `${50 - clamp(warnPct)}%` }} />
        <div className="gauge-centre" />
      </div>
      <div className="gauge-marker" style={{ left: `calc(9px + (100% - 18px) * ${pos / 100})` }} />
    </div>
      <div className="gauge-scale">
        <span>−20 %</span>
        <span>−10 %</span>
        <span>target</span>
        <span>+10 %</span>
        <span>+20 %</span>
      </div>
    </div>
  )
}
