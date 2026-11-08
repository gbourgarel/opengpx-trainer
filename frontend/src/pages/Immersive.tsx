// Immersive mode of the ride screen (GPX rides): the 3D view of the route over the whole window,
// with the key metrics on top (layout validated with the user on a mock-up):
//
// * top left: 3 s power in the colour of its zone, a zone bar (target ± 25 %), W/kg; with a
//   workout, step left / next target / interval average and a thin band of the workout;
// * top right: speed (big), time, heart rate, cadence, average / NP;
// * bottom left: the road ahead (zoomed profile, grade, altitude, VAM);
// * bottom right: the whole route (small profile, done / left) above a 2D mini map (fixed);
// * controls at the top centre, hidden after 3 s without moving the mouse.
//
// V or Esc: back to the normal screen; F: browser full screen.
import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fmtTime, type RouteDetail, type Telemetry, type Workout } from '../api'
import { ElevationProfile, LocalProfile, WorkoutProfile } from '../components/charts'
import { WindBadge } from '../components/Wind'
import { ATTRIBUTION } from '../scenery/tiles'
import { targetZone, type TargetZone } from '../targetZone'
import './immersive.css'

// MapLibre is only downloaded when the immersive mode is opened
const Scenery3D = lazy(() => import('../components/Scenery3D'))

const ZONE_LABEL: Record<TargetZone, string> = { on: 'On target', high: 'Slightly high', 'too-high': 'Too high', low: 'Slightly low', 'too-low': 'Too low' }
const HIDE_CONTROLS_MS = 3000

export interface ImmersiveProps {
  tel: Telemetry
  route: RouteDetail
  workout?: Workout
  ftp: number
  routePos?: number
  remainingDist: number | null
  doneIdx: number
  /** pause / stop / step / effort controls (built by RidePage) */
  controls: ReactNode
  sound: boolean
  setSound: (on: boolean) => void
  error: string | null
  onExit: () => void
}

export function Immersive(p: ImmersiveProps) {
  const { tel, route, workout, onExit } = p
  const controlsShown = useAutoHide(HIDE_CONTROLS_MS)
  const fullscreen = useFullscreen()

  return (
    <div className={`immersive ${controlsShown ? '' : 'im-idle'}`}>
      <Suspense fallback={<div className="im-loading">Loading the 3D view…</div>}>
        <Scenery3D route={route} tel={tel} />
      </Suspense>

      <div className="im-top">
        <h2>{tel.name}</h2>
        <span className={`badge state-${tel.state}`}>{tel.state}</span>
        <span className="badge">{workout ? 'GPX + workout' : 'GPX · pseudo-ERG'}</span>
        <span className="im-sp" />
        {workout && (
          <button className={p.sound ? '' : 'muted'} onClick={() => p.setSound(!p.sound)}>
            {p.sound ? 'Sound on' : 'Sound off'}
          </button>
        )}
        <button onClick={fullscreen.toggle} title="Browser full screen (F)">
          {fullscreen.on ? 'Exit full screen' : '⛶ Full screen'} <kbd>F</kbd>
        </button>
        <button onClick={onExit} title="Back to the normal ride screen (V or Esc)">
          ⤢ Normal view <kbd>V</kbd>
        </button>
      </div>

      <div className={`im-controls im-glass ${controlsShown ? '' : 'hidden'}`}>{p.controls}</div>
      {p.error && <div className="im-error">{p.error}</div>}
      {tel.state === 'ready' && <div className="im-hint">Start pedalling to begin</div>}
      {tel.state === 'paused' && <div className="im-hint">Paused</div>}

      <PowerBlock {...p} />
      <Tiles tel={tel} />
      <div className="im-ahead im-glass">
        {p.routePos != null && (
          <LocalProfile
            distance={route.profile_distance_m}
            altitude={route.altitude_m}
            grade={route.grade}
            position={p.routePos}
            speedKmh={tel.avg_speed_kmh}
            loop={!!workout}
            height={70}
            current={tel.grade != null ? { grade: tel.grade, altitude: tel.altitude_m ?? 0, vamMh: tel.vam_mh ?? null } : undefined}
          />
        )}
      </div>
      <RouteBlock {...p} />
      <div className="im-attrib" dangerouslySetInnerHTML={{ __html: ATTRIBUTION }} />
    </div>
  )
}

// ---------------------------------------------------------------------------------------

function PowerBlock({ tel, workout, ftp }: ImmersiveProps) {
  const target = tel.target_w != null && (tel.state === 'running' || tel.state === 'paused') ? tel.target_w : null
  const p3 = tel.power_avg3_w ?? tel.power_w ?? 0
  const shown = tel.power_avg3_w != null ? Math.round(tel.power_avg3_w) : tel.power_w
  const zone = target ? targetZone(p3, target) : null
  const inWorkout = !!workout && (tel.elapsed_s ?? 0) < (tel.workout_duration_s ?? 0)
  return (
    <div className="im-power im-glass">
      <span className="im-label">Power · 3 s</span>
      <div className={`im-watts ${zone ? `zone-fg-${zone}` : ''}`}>
        {shown ?? '—'}
        <span className="im-unit">W</span>
      </div>
      <div className="im-sub">
        {target ? (
          <>
            target <b>{target} W</b> · {tel.power_wkg?.toFixed(2) ?? '—'} W/kg
          </>
        ) : (
          <>free ride · {tel.power_wkg?.toFixed(2) ?? '—'} W/kg</>
        )}
      </div>
      {target && zone && (
        <>
          <ZoneBar power={p3} target={target} />
          <div className={`im-zone zone-fg-${zone}`}>{ZONE_LABEL[zone]}</div>
        </>
      )}
      {inWorkout && workout && (
        <>
          <div className="im-step">
            <div>
              <span className="im-label">Step left</span>
              <b>{fmtTime(tel.step_remaining_s)}</b>
              {tel.next_target_w != null && (
                <small>
                  next <b>{tel.next_target_w} W</b>
                </small>
              )}
            </div>
            <div>
              <span className="im-label">Interval avg</span>
              <b>
                {tel.step_avg_power_w ?? '—'}
                <span className="im-unit">W</span>
              </b>
              {target && (
                <small>
                  target <b>{target} W</b>
                </small>
              )}
            </div>
          </div>
          <div className="im-band">
            <WorkoutProfile steps={workout.steps} ftp={ftp} scale={(tel.intensity_pct ?? 100) / 100} elapsed={tel.elapsed_s} height={30} />
          </div>
          <div className="im-foot">
            <span>{workout.name}</span>
            <span>
              {fmtTime(tel.elapsed_s)} / {fmtTime(workout.duration_s)}
            </span>
          </div>
        </>
      )}
    </div>
  )
}

/** Target ± 25 %, zone bands as on the dial (ok: ± max(5 %, 5 W), warn: ± max(10 %, 10 W)). */
function ZoneBar({ power, target }: { power: number; target: number }) {
  const lo = target * 0.75
  const hi = target * 1.25
  const pct = (w: number) => Math.min(100, Math.max(0, ((w - lo) / (hi - lo)) * 100))
  const ok = Math.max(0.05 * target, 5)
  const warn = Math.max(0.1 * target, 10)
  const stops: [number, number, TargetZone][] = [
    [lo, target - warn, 'too-low'],
    [target - warn, target - ok, 'low'],
    [target - ok, target + ok, 'on'],
    [target + ok, target + warn, 'high'],
    [target + warn, hi, 'too-high'],
  ]
  return (
    <div className="im-zonebar">
      <div className="im-zonebar-track">
        {stops.map(([a, b, z]) => (
          <i key={z} className={`zone-bg-${z}`} style={{ left: `${pct(a)}%`, width: `${pct(b) - pct(a)}%` }} />
        ))}
        <span className="im-zonebar-tick" />
      </div>
      <span className="im-zonebar-marker" style={{ left: `${pct(power)}%` }} />
    </div>
  )
}

function Tiles({ tel }: { tel: Telemetry }) {
  return (
    <div className="im-tiles">
      <div className="im-tile im-glass big">
        <span className="im-label">Speed</span>
        <b>
          {tel.speed_kmh?.toFixed(1) ?? '—'}
          <span className="im-unit">km/h</span>
        </b>
        {tel.avg_speed_kmh != null && <small>avg {tel.avg_speed_kmh.toFixed(1)}</small>}
      </div>
      <div className="im-tile im-glass">
        <span className="im-label">Time</span>
        <b>{fmtTime(tel.elapsed_s)}</b>
      </div>
      <div className="im-tile im-glass hr">
        <span className="im-label">HR</span>
        <b>
          {tel.heart_rate_bpm ?? '—'}
          <span className="im-unit">bpm</span>
        </b>
      </div>
      <div className="im-tile im-glass">
        <span className="im-label">Cadence</span>
        <b>
          {tel.cadence_rpm ?? '—'}
          <span className="im-unit">rpm</span>
        </b>
      </div>
      <div className="im-tile im-glass">
        <span className="im-label">Avg / NP (W)</span>
        <b className="small">{tel.avg_power_w != null ? `${tel.avg_power_w} / ${tel.np_w ?? '—'}` : '—'}</b>
      </div>
    </div>
  )
}

function RouteBlock({ tel, route, workout, routePos, remainingDist, doneIdx }: ImmersiveProps) {
  const total = route.distance_m || 1
  const pos = Math.min(Math.max(routePos ?? 0, 0), total)
  return (
    <div className="im-route">
      <div className="im-route-profile im-glass">
        <div className="im-route-row">
          <span>
            <b>{((tel.distance_m ?? 0) / 1000).toFixed(1)}</b> km · <b>+{Math.round(tel.elevation_gain_m ?? 0)}</b> m
          </span>
          <span title={workout ? 'left in this lap (the route loops while the workout lasts)' : 'left to the end of the route'}>
            left <b>{remainingDist != null ? (remainingDist / 1000).toFixed(1) : '—'}</b> km · <b>+{Math.round(tel.elevation_left_m ?? 0)}</b> m
          </span>
        </div>
        <div className="im-route-svg">
          <ElevationProfile distance={route.profile_distance_m} altitude={route.altitude_m} grade={route.grade} position={routePos} height={40} />
          <div className="im-done-shade" style={{ width: `${(pos / total) * 100}%` }} />
        </div>
      </div>
      <div className="im-mini im-glass">
        <MiniMap latlon={route.latlon} doneIdx={doneIdx} at={tel.lat != null && tel.lon != null ? [tel.lat, tel.lon] : null} />
        <WindBadge kmh={tel.wind_kmh ?? 0} fromDeg={tel.wind_from_deg ?? 0} head={tel.headwind_kmh} cross={tel.crosswind_kmh} />
      </div>
    </div>
  )
}

/** The route drawn in a fixed box (north up, no tiles, no interaction): done part, position. */
function MiniMap({ latlon, doneIdx, at }: { latlon: [number, number][]; doneIdx: number; at: [number, number] | null }) {
  const W = 250
  const H = 160
  const proj = useMemo(() => {
    const lat0 = latlon.reduce((a, [la]) => a + la, 0) / Math.max(1, latlon.length)
    const kx = Math.cos((lat0 * Math.PI) / 180)
    const xs = latlon.map(([, lo]) => lo * kx)
    const ys = latlon.map(([la]) => -la)
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const pad = 12
    const k = Math.min((W - 2 * pad) / (x1 - x0 || 1e-9), (H - 2 * pad) / (y1 - y0 || 1e-9))
    const ox = (W - (x1 - x0) * k) / 2
    const oy = (H - (y1 - y0) * k) / 2
    const f = (la: number, lo: number): [number, number] => [(lo * kx - x0) * k + ox, (-la - y0) * k + oy]
    const stride = Math.max(1, Math.floor(latlon.length / 600))
    const pts = latlon.map(([la, lo]) => f(la, lo))
    const path = (q: [number, number][]) => 'M' + q.filter((_, i) => i % stride === 0 || i === q.length - 1).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')
    return { f, pts, path }
  }, [latlon])
  const done = proj.pts.slice(0, Math.max(1, doneIdx + 1))
  const me = at ? proj.f(at[0], at[1]) : null
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="im-mini-svg">
      <path d={proj.path(proj.pts)} className="im-mini-all" />
      {done.length > 1 && <path d={proj.path(done)} className="im-mini-done" />}
      {me && <circle cx={me[0]} cy={me[1]} r={6} className="im-mini-me" />}
    </svg>
  )
}

// ---------------------------------------------------------------------------------------

/** True while the mouse moved (or the screen was touched) in the last `ms` milliseconds. */
function useAutoHide(ms: number): boolean {
  const [shown, setShown] = useState(true)
  useEffect(() => {
    let timer = window.setTimeout(() => setShown(false), ms)
    const wake = () => {
      setShown(true)
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setShown(false), ms)
    }
    window.addEventListener('mousemove', wake)
    window.addEventListener('pointerdown', wake)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('mousemove', wake)
      window.removeEventListener('pointerdown', wake)
    }
  }, [ms])
  return shown
}

/** Browser full screen: state, toggle, F key; left when the immersive view closes. */
function useFullscreen() {
  const [on, setOn] = useState(() => !!document.fullscreenElement)
  const toggle = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
    else void document.documentElement.requestFullscreen?.().catch(() => {})
  }
  useEffect(() => {
    const sync = () => setOn(!!document.fullscreenElement)
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const el = e.target as HTMLElement | null
      if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return
      if (e.key === 'f' || e.key === 'F') {
        if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
        else void document.documentElement.requestFullscreen?.().catch(() => {})
      }
    }
    document.addEventListener('fullscreenchange', sync)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('fullscreenchange', sync)
      window.removeEventListener('keydown', onKey)
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
    }
  }, [])
  return { on, toggle }
}
