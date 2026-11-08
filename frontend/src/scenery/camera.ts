// Automatic camera of the 3D view (pure functions: no MapLibre; the terrain is a callback).
//
// Two placements, tuned in the spike (spikes/flyover3d) on the Alpe d'Huez up and down:
//
// * "follow" (climbs, descents, turns): behind the rider along the direction of travel smoothed
//   over the distance ridden (same turn shape at any speed), 5 s behind and never closer than
//   70 m, at half that height; looks at a point of the road ahead (250 m on flat straight roads,
//   60 m on steep ones, 30 m in sharp turns) and moves to the outside of turns, so it looks
//   across a hairpin at the rider instead of into the slope on its inside.
// * "low" (flat, straight roads): 3 m above the ground, looking almost level (pitch 84°), and
//   it is the distance behind that adapts so the rider is in the frame (never a tilt down).
//
// The two are blended by how flat and straight the road ahead is. Then, whatever the blend:
// the camera stays above the terrain between it and the rider, the lines of sight to the rider
// and to the look-at point clear the terrain, and the rider stays inside the frame (pitch and
// yaw limited, with margins for the overlays). Distances in metres, angles in degrees.
import { directionAt, gradeAt, pointAt, toLngLat, type RouteGeo } from './route3d'

const RAD = Math.PI / 180
const EARTH_CIRCUMFERENCE = 40075016.686

/** Ground altitude (m) at a longitude / latitude, or null when the terrain is not loaded yet. */
export type Ground = (lng: number, lat: number) => number | null

/** The view: canvas size (px), vertical field of view, margins the rider must stay out of. */
export interface Frame {
  width: number
  height: number
  fovDeg: number
  bottomMarginPx: number
  sideMarginPx: number
}

export interface CameraPose {
  center: [number, number]
  zoom: number
  pitch: number
  bearing: number
}

export interface CameraDebug {
  lowWeight: number // 0 = follow, 1 = low camera
  riderBelowCentreDeg: number // angle of the rider under the view axis
  riderSideDeg: number // angle of the rider off the view axis, sideways
  maxBelowDeg: number // limits the two must stay within
  maxSideDeg: number
  cameraAboveRider: number // m
  distanceToRider: number // m, horizontal
}

const FOLLOW = { lagS: 5, minBack: 70, heightRatio: 0.5, smoothM: 40, tauS: 1.5, farM: 250, steepM: 60, turnM: 30, outside: 0.8, flatBack: 40, flatHeightRatio: 0.3 }
const LOW = { height: 3, minBack: 8, maxBack: 200, pitch: 84, lookM: 150 }

export interface CameraState {
  sPrev: number | null
  speed: number // smoothed m/s
  dir: [number, number] | null // smoothed direction of travel (unit vector)
  turn: number // 0..1 sharpness of the upcoming turn (smoothed)
  steep: number | null // 0..1 steepness of the road ahead (smoothed)
  look: number | null // look-ahead distance along the road (smoothed)
  lateral: number // offset to the outside of the turn (smoothed)
  followAlt: number | null
  lowBack: number | null
  lowAlt: number | null
  lowWeight: number | null
}

export const newCameraState = (): CameraState => ({
  sPrev: null,
  speed: 0,
  dir: null,
  turn: 0,
  steep: null,
  look: null,
  lateral: 0,
  followAlt: null,
  lowBack: null,
  lowAlt: null,
  lowWeight: null,
})

type P2 = [number, number]
type P3 = [number, number, number]
const clamp01 = (x: number) => Math.max(0, Math.min(1, x))
const ease = (dt: number, tau: number) => 1 - Math.exp(-dt / tau)

function meanAbsGrade(g: RouteGeo, s0: number, s1: number): number {
  let sum = 0
  let n = 0
  for (let x = s0; x <= s1; x += 25) {
    sum += Math.abs(gradeAt(g, x))
    n++
  }
  return n ? sum / n : 0
}

/** Signed heading change (deg, + = left) between here and 60 m ahead. */
function upcomingTurn(g: RouteGeo, s: number): number {
  const [p1, p2, q1, q2] = [pointAt(g, s - 10), pointAt(g, s + 10), pointAt(g, s + 50), pointAt(g, s + 70)]
  const [ax, ay, bx, by] = [p2[0] - p1[0], p2[1] - p1[1], q2[0] - q1[0], q2[1] - q1[1]]
  return Math.atan2(ax * by - ay * bx, ax * bx + ay * by) / RAD
}

/** Half-angles (deg) of the frame part where the rider may be: below the axis, and sideways. */
function frameLimits(f: Frame): { below: number; side: number } {
  const focal = f.height / 2 / Math.tan((f.fovDeg / 2) * RAD) // px
  return {
    below: Math.atan(Math.max(10, f.height / 2 - f.bottomMarginPx) / focal) / RAD,
    side: Math.atan(Math.max(10, f.width / 2 - f.sideMarginPx) / focal) / RAD,
  }
}

/**
 * Camera pose for a rider at distance s along the route, riding at `speed` m/s. Mutates `st`
 * (smoothing between frames). `cameraToCenterDistance` is MapLibre's (px); it turns the camera
 * distance into a zoom level (512 px tiles).
 */
export function autoCamera(
  g: RouteGeo,
  s: number,
  speed: number,
  st: CameraState,
  dt: number,
  groundAt: Ground,
  frame: Frame,
  cameraToCenterDistance: number,
): { pose: CameraPose; debug: CameraDebug } {
  const altAt = (p: P2, fallback: number) => {
    const [lng, lat] = toLngLat(g, p[0], p[1])
    return groundAt(lng, lat) ?? fallback
  }
  const lim = frameLimits(frame)
  const travelled = st.sPrev == null ? 0 : Math.abs(s - st.sPrev)
  st.sPrev = s
  st.speed += (speed - st.speed) * ease(dt, 3) // no camera pumping with every pedal stroke

  // road ahead: turn sharpness and steepness (|grade|: descents count as steep)
  const turn = upcomingTurn(g, s)
  st.turn += (clamp01(Math.abs(turn) / 120) - st.turn) * ease(dt, 1)
  const steep = clamp01((meanAbsGrade(g, s, s + 300) - 0.02) / 0.04)
  st.steep = st.steep == null ? steep : st.steep + (steep - st.steep) * ease(dt, 1)
  const flat = (1 - st.steep) * (1 - st.turn)

  // direction of travel, smoothed over the distance ridden
  const d = directionAt(g, s)
  const k = st.dir == null ? 1 : 1 - Math.exp(-travelled / FOLLOW.smoothM)
  st.dir = st.dir == null ? d : [st.dir[0] + (d[0] - st.dir[0]) * k, st.dir[1] + (d[1] - st.dir[1]) * k]
  const n = Math.hypot(st.dir[0], st.dir[1]) || 1
  const [ux, uy] = [st.dir[0] / n, st.dir[1] / n]
  const rider = pointAt(g, s)
  const rAlt = altAt(rider, 0)

  // ---- follow ----
  let back = Math.max(FOLLOW.minBack, FOLLOW.lagS * st.speed)
  back = Math.max(back - (back - FOLLOW.flatBack) * flat, FOLLOW.lagS * st.speed)
  const height = back * (FOLLOW.heightRatio - (FOLLOW.heightRatio - FOLLOW.flatHeightRatio) * flat)
  const wantLook = (FOLLOW.farM - (FOLLOW.farM - FOLLOW.steepM) * st.steep) * (1 - st.turn) + FOLLOW.turnM * st.turn
  st.look = st.look == null ? wantLook : st.look + (wantLook - st.look) * ease(dt, 1)
  const side = turn > 0 ? 1 : -1 // outside of a left turn = right of the heading
  st.lateral += (side * back * FOLLOW.outside * clamp01(Math.abs(turn) / 90) - st.lateral) * ease(dt, 1)
  const fCam: P2 = [rider[0] - ux * back + uy * st.lateral, rider[1] - uy * back - ux * st.lateral]
  const fLook2 = pointAt(g, s + st.look)
  const fLookAlt = altAt(fLook2, rAlt)
  let need = altAt(fCam, rAlt) + height
  for (let i = 1; i <= 6; i++) {
    // above the slope between the camera and the rider
    const f = i / 6
    const p: P2 = [fCam[0] + (rider[0] - fCam[0]) * f, fCam[1] + (rider[1] - fCam[1]) * f]
    need = Math.max(need, altAt(p, -1e9) + Math.max(height * (1 - f), 2) + 1.5)
  }
  need = Math.max(need, sightAlt(fCam, fLook2, fLookAlt, altAt), sightAlt(fCam, rider, rAlt, altAt))
  st.followAlt = st.followAlt == null || need > st.followAlt ? need : st.followAlt + (need - st.followAlt) * ease(dt, FOLLOW.tauS)
  const follow = { cam: [fCam[0], fCam[1], st.followAlt] as P3, look: [fLook2[0], fLook2[1], fLookAlt] as P3 }

  // ---- low, looking far ----
  // rider in frame at a fixed pitch: atan(h / back) <= (90 - pitch) + below-limit - margin
  const maxDrop = Math.max(2, 90 - LOW.pitch + lim.below - 3) * RAD
  let lBack = Math.max(LOW.minBack, st.lowBack ?? LOW.minBack)
  let lCam: P2 = rider
  let lAlt = rAlt
  for (let it = 0; it < 3; it++) {
    lCam = [rider[0] - ux * lBack, rider[1] - uy * lBack]
    lAlt = Math.max(altAt(lCam, rAlt) + LOW.height, sightAlt(lCam, rider, rAlt, altAt, 1))
    const want = Math.max(LOW.minBack, (lAlt - rAlt) / Math.tan(maxDrop)) // back away, never tilt
    if (want <= lBack + 0.5) break
    lBack = Math.min(LOW.maxBack, want)
  }
  st.lowBack = st.lowBack == null || lBack > st.lowBack ? lBack : st.lowBack + (lBack - st.lowBack) * ease(dt, 2 * FOLLOW.tauS)
  st.lowAlt = st.lowAlt == null || lAlt > st.lowAlt ? lAlt : st.lowAlt + (lAlt - st.lowAlt) * ease(dt, FOLLOW.tauS)
  lCam = [rider[0] - ux * st.lowBack, rider[1] - uy * st.lowBack]
  const ahead = pointAt(g, s + LOW.lookM)
  const lb = Math.atan2(ahead[0] - lCam[0], ahead[1] - lCam[1])
  const lUp = Math.max(0.5, st.lowAlt - rAlt)
  const lReach = lUp * Math.tan(LOW.pitch * RAD) // where the view axis meets the ground
  const lLook2: P2 = [lCam[0] + Math.sin(lb) * lReach, lCam[1] + Math.cos(lb) * lReach]
  const low = { cam: [lCam[0], lCam[1], st.lowAlt] as P3, look: [lLook2[0], lLook2[1], st.lowAlt - lUp] as P3 }

  // ---- blend: low camera only on flat, straight road, and only if it stays close ----
  const wantLow = clamp01((flat - 0.55) / 0.35) * clamp01((90 - st.lowBack) / 40)
  st.lowWeight = st.lowWeight == null ? wantLow : st.lowWeight + (wantLow - st.lowWeight) * ease(dt, FOLLOW.tauS)
  const w = st.lowWeight
  const mix = (a: P3, b: P3): P3 => [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w, a[2] + (b[2] - a[2]) * w]
  const cam = mix(follow.cam, low.cam)
  let look = mix(follow.look, low.look)
  cam[2] = Math.max(cam[2], altAt([cam[0], cam[1]], -1e9) + 2) // never under the ground

  // ---- keep the rider in the frame ----
  const camXY: P2 = [cam[0], cam[1]]
  const toRider = Math.hypot(rider[0] - cam[0], rider[1] - cam[1])
  let dx = look[0] - cam[0]
  let dy = look[1] - cam[1]
  const riderBearing = Math.atan2(rider[0] - cam[0], rider[1] - cam[1]) / RAD
  const sideLimit = lim.side - 2
  let bearing = Math.atan2(dx, dy) / RAD
  let sideOff = ((riderBearing - bearing + 540) % 360) - 180
  if (Math.abs(sideOff) > sideLimit) {
    bearing = riderBearing - Math.sign(sideOff) * sideLimit
    const dist = Math.hypot(dx, dy)
    ;[dx, dy] = [Math.sin(bearing * RAD) * dist, Math.cos(bearing * RAD) * dist]
    look = [cam[0] + dx, cam[1] + dy, altAt([cam[0] + dx, cam[1] + dy], look[2])]
    sideOff = ((riderBearing - bearing + 540) % 360) - 180
  }
  let horiz = Math.max(1, Math.hypot(dx, dy))
  let up = Math.max(0.5, cam[2] - look[2])
  let pitch = Math.min(85, Math.atan2(horiz, up) / RAD)
  const riderDrop = Math.atan2(cam[2] - rAlt, Math.max(1, toRider)) / RAD // below the horizontal
  const maxPitch = 90 - riderDrop + lim.below - 2
  if (pitch > maxPitch) {
    // looking too far up: bring the look-at point closer along the same bearing
    const h2 = Math.min(horiz, Math.max(1, up) * Math.tan(Math.max(1, maxPitch) * RAD))
    const p2: P2 = [cam[0] + (dx / horiz) * h2, cam[1] + (dy / horiz) * h2]
    look = [p2[0], p2[1], altAt(p2, look[2])]
    horiz = h2
    up = Math.max(0.5, cam[2] - look[2])
    pitch = Math.min(85, Math.atan2(horiz, up) / RAD)
  }
  const center = toLngLat(g, look[0], look[1])
  const slant = Math.hypot(horiz, up)
  const zoom = Math.log2((EARTH_CIRCUMFERENCE * Math.cos(center[1] * RAD) * cameraToCenterDistance) / (512 * slant))
  return {
    pose: { center, zoom, pitch, bearing },
    debug: {
      lowWeight: w,
      riderBelowCentreDeg: riderDrop - (90 - pitch),
      riderSideDeg: sideOff,
      maxBelowDeg: lim.below,
      maxSideDeg: lim.side,
      cameraAboveRider: cam[2] - rAlt,
      distanceToRider: Math.hypot(rider[0] - camXY[0], rider[1] - camXY[1]),
    },
  }
}

/**
 * Lowest camera altitude at `from` from which the straight line to `to` (at `toAlt`) clears the
 * terrain by `margin`: along the line alt(f) = A + (toAlt - A) f >= ground(f) + margin.
 */
function sightAlt(from: P2, to: P2, toAlt: number, altAt: (p: P2, fallback: number) => number, margin = 3): number {
  let need = -1e9
  for (let i = 1; i <= 8; i++) {
    const f = i / 10
    const p: P2 = [from[0] + (to[0] - from[0]) * f, from[1] + (to[1] - from[1]) * f]
    need = Math.max(need, (altAt(p, -1e9) + margin - toAlt * f) / (1 - f))
  }
  return need
}
