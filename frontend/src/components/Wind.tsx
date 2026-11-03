/** Wind: the picker used when starting a GPX ride, and the badge on the ride map. */
import { compassName, type WindSetting } from '../wind'

export function WindPicker({ value, onChange }: { value: WindSetting; onChange: (w: WindSetting) => void }) {
  return (
    <span className="wind-pick" title="Wind for this ride: speed and the direction it blows from. It is projected on the route heading at each point (head / tail / cross wind).">
      <span className="muted">Wind</span>
      <input
        type="number"
        min={0}
        max={150}
        step={1}
        value={value.kmh}
        onChange={(e) => onChange({ ...value, kmh: Math.max(0, Math.min(150, Number(e.target.value) || 0)) })}
      />
      <span className="muted">km/h from</span>
      <input
        type="number"
        min={0}
        max={359}
        step={5}
        value={value.fromDeg}
        disabled={value.kmh === 0}
        title="Direction the wind blows from, in degrees: 0 = north, 90 = east, 180 = south, 270 = west"
        onChange={(e) => {
          const d = Number(e.target.value)
          onChange({ ...value, fromDeg: Number.isFinite(d) ? Math.round(((d % 360) + 360) % 360) : 0 })
        }}
      />
      <span className="muted wind-compass">° {compassName(value.fromDeg)}</span>
    </span>
  )
}

/** Discreet map overlay: an arrow showing where the wind blows (the map is north-up) and its
 * speed; the effect on the current heading (head / tail / cross) is in the tooltip. */
export function WindBadge({ kmh, fromDeg, head, cross }: { kmh: number; fromDeg: number; head?: number; cross?: number }) {
  if (!kmh) return null
  const along = head == null ? null : head >= 0.5 ? `headwind ${head.toFixed(0)} km/h` : head <= -0.5 ? `tailwind ${(-head).toFixed(0)} km/h` : null
  const side = cross == null || Math.abs(cross) < 0.5 ? null : `crosswind ${Math.abs(cross).toFixed(0)} km/h from the ${cross > 0 ? 'right' : 'left'}`
  const now = [along, side].filter(Boolean).join(', ')
  return (
    <div className="wind-badge" title={`Wind ${kmh.toFixed(0)} km/h from ${fromDeg}° (${compassName(fromDeg)})${now ? `\nHere: ${now}` : ''}`}>
      <svg viewBox="-12 -12 24 24" width="14" height="14" aria-hidden>
        {/* drawn pointing down (blowing from north to south), rotated by the from-direction */}
        <g transform={`rotate(${fromDeg})`}>
          <path d="M0 -10 L0 8 M-6 2 L0 9 L6 2" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </svg>
      {kmh.toFixed(0)} km/h
    </div>
  )
}
