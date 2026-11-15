import { useMemo } from 'react'
import { stepWatts, type Step } from '../api'
import { powerZoneOfFraction } from '../zones'

// ---------------------------------------------------------------------------------------
// Workout profile (SVG): one polygon per step, coloured by its Coggan power zone, progress
// cursor.
const zoneColor = (frac: number | null) => (frac == null ? 'var(--muted)' : powerZoneOfFraction(frac).color)

export function WorkoutProfile({
  steps,
  ftp,
  scale = 1,
  elapsed,
  height = 90,
}: {
  steps: Step[]
  ftp: number
  scale?: number
  elapsed?: number
  height?: number
}) {
  const total = steps.reduce((a, s) => a + s.duration_s, 0) || 1
  const maxW = Math.max(
    ftp * 1.2,
    ...steps.flatMap((s) => [stepWatts(s, ftp, 0) ?? 0, stepWatts(s, ftp, s.duration_s) ?? 0]).map((w) => w * scale),
  )
  const W = 1000
  const y = (w: number) => height - (w / maxW) * (height - 4)
  const starts = steps.reduce<number[]>((acc, s, i) => [...acc, (acc[i] ?? 0) + s.duration_s], [0])
  const polys = steps.map((s, i) => {
    const x0 = (starts[i] / total) * W
    const x1 = (starts[i + 1] / total) * W
    const w0 = (stepWatts(s, ftp, 0) ?? ftp * 0.3) * scale
    const w1 = (stepWatts(s, ftp, s.duration_s) ?? ftp * 0.3) * scale
    const frac = s.start == null ? null : (w0 + w1) / 2 / ftp
    return (
      <polygon
        key={i}
        points={`${x0},${height} ${x0},${y(w0)} ${x1},${y(w1)} ${x1},${height}`}
        fill={zoneColor(frac)}
        opacity={s.start == null ? 0.35 : 0.9}
      >
        <title>{`${s.label || 'step'} · ${Math.round(s.duration_s)} s · ${Math.round(w0)}→${Math.round(w1)} W`}</title>
      </polygon>
    )
  })
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="profile-svg" style={{ height }}>
      <line x1={0} x2={W} y1={y(ftp * scale)} y2={y(ftp * scale)} className="ftp-line" />
      {polys}
      {elapsed != null && (
        <line x1={(elapsed / total) * W} x2={(elapsed / total) * W} y1={0} y2={height} className="cursor" />
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------------------
// Elevation profile (SVG) coloured by grade, with rider position.
const gradeColor = (g: number) => {
  const p = g * 100
  if (p < -2) return 'var(--g-down)'
  if (p < 2) return 'var(--g-flat)'
  if (p < 5) return 'var(--g-mod)'
  if (p < 8) return 'var(--g-hard)'
  return 'var(--g-steep)'
}

export function ElevationProfile({
  distance,
  altitude,
  grade,
  position,
  height = 120,
}: {
  distance: number[]
  altitude: number[]
  grade: number[]
  position?: number
  height?: number
}) {
  const W = 1000
  const total = distance[distance.length - 1] || 1
  const lo = Math.min(...altitude)
  const hi = Math.max(...altitude)
  const span = Math.max(hi - lo, 20)
  const x = (d: number) => (d / total) * W
  const y = (a: number) => height - 4 - ((a - lo) / span) * (height - 16)
  const segs = useMemo(() => {
    const out = []
    const stride = Math.max(1, Math.floor(distance.length / 400))
    for (let i = 0; i < distance.length - 1; i += stride) {
      const j = Math.min(i + stride, distance.length - 1)
      out.push(
        <polygon
          key={i}
          points={`${x(distance[i])},${height} ${x(distance[i])},${y(altitude[i])} ${x(distance[j])},${y(altitude[j])} ${x(distance[j])},${height}`}
          fill={gradeColor(grade[i])}
        />,
      )
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [distance, altitude, grade, height])
  let marker = null
  if (position != null) {
    let k = distance.findIndex((d) => d >= position)
    if (k < 0) k = distance.length - 1
    marker = (
      <g>
        <line x1={x(position)} x2={x(position)} y1={0} y2={height} className="cursor" />
        <circle cx={x(position)} cy={y(altitude[k])} r={5} className="rider-dot" />
      </g>
    )
  }
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="profile-svg" style={{ height }}>
      {segs}
      {marker}
    </svg>
  )
}

// ---------------------------------------------------------------------------------------
// Zoomed elevation profile: what is coming in the next few minutes.

/** Linear interpolation in sorted xs (binary search). */
function interp(xs: number[], ys: number[], x: number) {
  if (x <= xs[0]) return ys[0]
  const n = xs.length
  if (x >= xs[n - 1]) return ys[n - 1]
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (xs[mid] <= x) lo = mid
    else hi = mid
  }
  const f = (x - xs[lo]) / (xs[hi] - xs[lo] || 1)
  return ys[lo] + (ys[hi] - ys[lo]) * f
}

export function LocalProfile({
  distance,
  altitude,
  grade,
  position,
  speedKmh,
  loop,
  height = 96,
  current,
}: {
  distance: number[]
  altitude: number[]
  grade: number[]
  position: number
  speedKmh: number | null | undefined
  loop: boolean // the route repeats (GPX + workout): continue past the end with the start
  height?: number
  // optional: show the current grade (rise/run), altitude and climb rate under the profile
  current?: { grade: number; altitude: number; vamMh?: number | null }
}) {
  const total = distance[distance.length - 1] || 1
  // ~5 minutes ahead at the average speed, between 1.5 and 5 km; a little behind for context
  const v = speedKmh && speedKmh > 5 ? speedKmh / 3.6 : 25 / 3.6
  const ahead = Math.min(5000, Math.max(1500, v * 300))
  const behind = Math.max(150, ahead * 0.12)
  const start = position - behind
  const end = position + ahead
  const N = 240
  const pts: { rel: number; alt: number; g: number }[] = []
  for (let i = 0; i <= N; i++) {
    const rel = start + ((end - start) * i) / N // distance relative to the route start
    let d = rel
    if (rel < 0) continue // nothing before the start (looping: not the previous lap's end either)
    if (loop) d = rel % total // ahead, the route continues with its start
    else if (rel > total) continue // nothing after the end
    pts.push({ rel, alt: interp(distance, altitude, d), g: interp(distance, grade, d) })
  }
  if (pts.length < 2) return null
  let lo = Math.min(...pts.map((p) => p.alt))
  let hi = Math.max(...pts.map((p) => p.alt))
  if (hi - lo < 20) {
    const mid = (hi + lo) / 2 // keep a 20 m minimum span: false flats stay flat
    lo = mid - 10
    hi = mid + 10
  }
  const W = 1000
  const top = 14
  const x = (rel: number) => ((rel - start) / (end - start)) * W
  const y = (a: number) => height - 2 - ((a - lo) / (hi - lo)) * (height - top - 4)
  const polys = pts.slice(0, -1).map((p, i) => {
    const q = pts[i + 1]
    return <polygon key={i} points={`${x(p.rel)},${height} ${x(p.rel)},${y(p.alt)} ${x(q.rel)},${y(q.alt)} ${x(q.rel)},${height}`} fill={gradeColor(p.g)} />
  })
  const ticks = []
  for (let k = 1; k * 1000 <= ahead; k++) ticks.push(k)
  // next kilometre: elevation change and mean grade
  const at = (rel: number) => interp(distance, altitude, loop ? ((rel % total) + total) % total : Math.min(rel, total))
  const nextLen = loop ? 1000 : Math.min(1000, total - position)
  const rise = nextLen > 50 ? at(position + nextLen) - at(position) : 0
  return (
    <div className="local-profile">
      <div className="km-labels">
        {ticks.map((k) => (
          <i key={k} style={{ left: `${(x(position + k * 1000) / W) * 100}%` }}>
            +{k} km
          </i>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="profile-svg" style={{ height }}>
        {polys}
        {ticks.map((k) => (
          <line key={k} x1={x(position + k * 1000)} x2={x(position + k * 1000)} y1={top - 4} y2={height} className="km-tick" />
        ))}
        <line x1={x(position)} x2={x(position)} y1={0} y2={height} className="cursor" />
        <circle cx={x(position)} cy={y(at(position))} r={5} className="rider-dot" />
      </svg>
      <div className="local-profile-labels">
        {current ? (
          <span className="now-grade">
            now{' '}
            <b style={{ color: gradeColor(current.grade) }}>
              {(current.grade * 100).toFixed(1)} %
            </b>{' '}
            · {Math.round(current.altitude)} m
          </span>
        ) : (
          <span>
            {Math.round(lo)}–{Math.round(hi)} m
          </span>
        )}
        {current && current.vamMh !== undefined && (
          <span className="now-vam" title="climb rate over the last 30 s">
            VAM <b>{current.vamMh ?? '—'}</b> m/h
          </span>
        )}
        {!current && (
          // with the "current" line (grade, VAM) the next-km summary is left out
          <span className="next-km">
            next {nextLen >= 999 ? '1 km' : `${Math.round(nextLen)} m`}: {rise >= 0 ? '+' : ''}
            {Math.round(rise)} m · {nextLen > 50 ? ((rise / nextLen) * 100).toFixed(1) : '0.0'} %
          </span>
        )}
      </div>
    </div>
  )
}
