// Camera of the 3D view (pure functions: no MapLibre, the terrain is a callback).
//
// Step 1: a plain "high chase" camera — 70 m behind the rider along the smoothed direction of
// travel, 35 m up, looking at a point 50 m ahead, lifted above any terrain between it and the
// rider. The full automatic camera (follow / low on the flat, line of sight, rider kept in the
// frame) replaces it in the next step.
import { directionAt, pointAt, toLngLat, type RouteGeo } from './route3d'

const RAD = Math.PI / 180
const EARTH_CIRCUMFERENCE = 40075016.686

/** Ground altitude (m) at a longitude / latitude, or null when the terrain is not loaded yet. */
export type Ground = (lng: number, lat: number) => number | null

export interface CameraState {
  dir: [number, number] | null // smoothed direction of travel
  alt: number | null // smoothed camera altitude (m)
}

export interface CameraPose {
  center: [number, number]
  zoom: number
  pitch: number
  bearing: number
}

export const newCameraState = (): CameraState => ({ dir: null, alt: null })

const BACK = 70
const HEIGHT = 35
const AHEAD = 50
const TAU_S = 1.5

/**
 * Camera pose for a rider at distance s along the route. `cameraToCenterDistance` is MapLibre's
 * (pixels, depends on the canvas height and the field of view); it turns the camera distance
 * into a zoom level (512 px tiles).
 */
export function chaseCamera(
  g: RouteGeo,
  s: number,
  st: CameraState,
  dt: number,
  ground: Ground,
  cameraToCenterDistance: number,
): CameraPose {
  const k = 1 - Math.exp(-dt / TAU_S)
  const d = directionAt(g, s)
  st.dir = st.dir == null ? d : [st.dir[0] + (d[0] - st.dir[0]) * k, st.dir[1] + (d[1] - st.dir[1]) * k]
  const n = Math.hypot(st.dir[0], st.dir[1]) || 1
  const [ux, uy] = [st.dir[0] / n, st.dir[1] / n]
  const rider = pointAt(g, s)
  const cam: [number, number] = [rider[0] - ux * BACK, rider[1] - uy * BACK]
  const target: [number, number] = [rider[0] + ux * AHEAD, rider[1] + uy * AHEAD]
  const at = (p: [number, number], fallback: number) => {
    const [lng, lat] = toLngLat(g, p[0], p[1])
    return ground(lng, lat) ?? fallback
  }
  const tAlt = at(target, 0)
  // stay HEIGHT above the camera's ground and above the slope between the camera and the rider
  let need = at(cam, tAlt) + HEIGHT
  for (let i = 1; i <= 6; i++) {
    const f = i / 6
    const p: [number, number] = [cam[0] + (rider[0] - cam[0]) * f, cam[1] + (rider[1] - cam[1]) * f]
    need = Math.max(need, at(p, -1e9) + Math.max(HEIGHT * (1 - f), 2) + 1.5)
  }
  st.alt = st.alt == null || need > st.alt ? need : st.alt + (need - st.alt) * k // up fast, down smooth
  const dx = target[0] - cam[0]
  const dy = target[1] - cam[1]
  const horiz = Math.max(1, Math.hypot(dx, dy))
  const up = Math.max(0.5, st.alt - tAlt)
  const center = toLngLat(g, target[0], target[1])
  const slant = Math.hypot(horiz, up)
  return {
    center,
    pitch: Math.min(85, Math.atan2(horiz, up) / RAD),
    bearing: Math.atan2(dx, dy) / RAD,
    zoom: Math.log2((EARTH_CIRCUMFERENCE * Math.cos(center[1] * RAD) * cameraToCenterDistance) / (512 * slant)),
  }
}
