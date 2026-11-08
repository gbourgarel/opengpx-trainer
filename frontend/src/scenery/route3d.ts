// Route geometry for the 3D view, in local metres (pure functions, no MapLibre).
//
// The route comes from /api/routes/{id} (decimated polyline + distance along the route). Positions
// are interpolated by distance; x = east, y = north, in metres from the first point
// (equirectangular projection, exact enough over a ride's extent).
import type { RouteDetail } from '../api'

const R = 6371008.8
const RAD = Math.PI / 180

export interface RouteGeo {
  lat0: number
  lon0: number
  xs: number[]
  ys: number[]
  ds: number[] // distance along the route (m), increasing
  grade: number[]
  total: number
}

export function routeGeo(r: Pick<RouteDetail, 'latlon' | 'profile_distance_m' | 'grade'>): RouteGeo {
  const [lat0, lon0] = r.latlon[0]
  const k = R * Math.cos(lat0 * RAD) * RAD
  return {
    lat0,
    lon0,
    xs: r.latlon.map(([, lon]) => (lon - lon0) * k),
    ys: r.latlon.map(([lat]) => (lat - lat0) * R * RAD),
    ds: r.profile_distance_m,
    grade: r.grade,
    total: r.profile_distance_m[r.profile_distance_m.length - 1] ?? 0,
  }
}

/** Index i such that ds[i] <= s < ds[i + 1] (clamped). */
function seg(g: RouteGeo, s: number): number {
  let lo = 0
  let hi = g.ds.length - 1
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1
    if (g.ds[m] <= s) lo = m
    else hi = m
  }
  return lo
}

export function pointAt(g: RouteGeo, s: number): [number, number] {
  s = Math.max(0, Math.min(s, g.total))
  const i = seg(g, s)
  const j = Math.min(i + 1, g.ds.length - 1)
  const f = g.ds[j] > g.ds[i] ? (s - g.ds[i]) / (g.ds[j] - g.ds[i]) : 0
  return [g.xs[i] + f * (g.xs[j] - g.xs[i]), g.ys[i] + f * (g.ys[j] - g.ys[i])]
}

export function gradeAt(g: RouteGeo, s: number): number {
  return g.grade[seg(g, Math.max(0, Math.min(s, g.total)))] ?? 0
}

/** Unit direction of travel around s (chord from s - back to s + ahead). */
export function directionAt(g: RouteGeo, s: number, back = 10, ahead = 25): [number, number] {
  const a = pointAt(g, s - back)
  const b = pointAt(g, s + ahead)
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const n = Math.hypot(dx, dy) || 1
  return [dx / n, dy / n]
}

export function toLngLat(g: RouteGeo, x: number, y: number): [number, number] {
  return [g.lon0 + x / (R * Math.cos(g.lat0 * RAD) * RAD), g.lat0 + y / (R * RAD)]
}

/**
 * Displayed position along the route between two 4 Hz telemetry samples: extrapolated with the
 * speed, pulled back towards the telemetry so it never drifts. A jump backwards of more than
 * half the route is a new lap (looping routes): restart from the telemetry.
 */
export function followPosition(
  shown: number | null,
  tel: { s: number; v: number; ageS: number },
  dt: number,
  total: number,
): number {
  const predicted = Math.min(tel.s + tel.v * tel.ageS, total)
  if (shown == null || shown < predicted - total / 2 || shown > predicted + total / 2) return predicted
  const next = shown + tel.v * dt + (predicted - shown) * Math.min(1, dt * 3)
  return Math.max(0, Math.min(next, total))
}
