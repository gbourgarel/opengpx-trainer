/* Starting a GPX route part-way: where a click on the map or the elevation profile puts the
 * start point. Pure functions (checked by `npm run check`). */

/** The ride keeps at least this much of the route (the backend clamps the same way). */
export const MIN_LEFT_M = 100

/** A start distance within [0, total - MIN_LEFT_M], to the metre; 0 for a route shorter than
 * that. */
export function clampStart(m: number, total: number): number {
  if (!Number.isFinite(m)) return 0
  return Math.round(Math.max(0, Math.min(m, Math.max(0, total - MIN_LEFT_M))))
}

/** Distance under a click on the elevation profile (it spans the whole route, left to right). */
export function startFromProfile(fraction: number, total: number): number {
  return clampStart(Math.max(0, Math.min(1, fraction)) * total, total)
}

/** Index of the route point nearest to a clicked position (equirectangular distances, plenty
 * at route scale). */
export function nearestIndex(latlon: readonly (readonly [number, number])[], at: readonly [number, number]): number {
  const k = Math.cos((at[0] * Math.PI) / 180)
  let best = 0
  let bestD = Infinity
  latlon.forEach(([lat, lon], i) => {
    const d = (lat - at[0]) ** 2 + ((lon - at[1]) * k) ** 2
    if (d < bestD) {
      bestD = d
      best = i
    }
  })
  return best
}

/** Index of the first point at or beyond a distance (the map draws up to it). */
export function indexAt(distance: readonly number[], m: number): number {
  const k = distance.findIndex((d) => d >= m)
  return k < 0 ? distance.length - 1 : k
}
