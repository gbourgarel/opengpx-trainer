// Ride screen ("cockpit" layout).
//
// Left: the workout session on top, then the power dial with the step countdown and the
// interval average in big type around it. Right: what is coming (zoomed profile with the
// current grade and climb rate), route progress (done / left on the full profile) and the map
// (empty on ERG rides for now). Bottom: controls.
import type { ReactNode } from 'react'
import { fmtTime, wkg, type RouteDetail, type Telemetry, type Workout } from '../api'
import { ElevationProfile, LocalProfile, WorkoutProfile } from '../components/charts'
import { RouteMap } from '../components/RouteMap'
import { WindBadge } from '../components/Wind'
import { indexAt } from '../routeStart'
import { targetZone, type TargetZone } from '../targetZone'
import { DIST_LEFT_TITLE, TIME_LEFT_TITLE } from '../liveEstimate'
import { hrZone, powerZone } from '../zones'
import { Metric } from './RidePage'
import './ride-cockpit.css'

export interface RideCtx {
  tel: Telemetry
  route?: RouteDetail
  workout?: Workout
  ftp: number
  /** threshold heart rate: the HR in the colour of its zone */
  lthr: number | null
  routePos?: number
  doneIdx: number
  /** started part-way, on the first lap: where the ride started (m), the part before greyed */
  skippedM: number
  follow: boolean
  setFollow: (v: boolean) => void
  showGauge: boolean
  remainingDist: number | null
  lap: number
  head: ReactNode
  controls: ReactNode
  /** where the target comes from, under the dial (GPX rides) */
  sourceLabel?: string
}

const ZONE_LABEL: Record<TargetZone, string> = { on: 'On target', high: 'Slightly high', 'too-high': 'Too high', low: 'Slightly low', 'too-low': 'Too low' }

// ---------------------------------------------------------------------------------------
// small stat tiles

type Stat = { key: string; label: string; value: string | number | null | undefined; unit?: string; sub?: string; color?: string; title?: string }

function stats(c: RideCtx): Stat[] {
  const t = c.tel
  const hz = hrZone(t.heart_rate_bpm, c.lthr)
  return [
    { key: 'time', label: 'Time', value: fmtTime(t.elapsed_s) },
    { key: 'speed', label: 'Speed', value: t.speed_kmh?.toFixed(1), unit: 'km/h', sub: t.avg_speed_kmh != null ? `avg ${t.avg_speed_kmh.toFixed(1)}` : undefined },
    { key: 'cad', label: 'Cadence', value: t.cadence_rpm, unit: 'rpm' },
    { key: 'hr', label: hz ? `HR · Z${hz.n}` : 'HR', value: t.heart_rate_bpm, unit: 'bpm', color: hz?.color, title: hz ? `Heart-rate zone ${hz.n}: ${hz.name} (% of threshold HR)` : undefined },
    // unit in the label: "437 / 437" plus a unit does not fit a narrow tile
    { key: 'avg', label: 'Avg / NP (W)', value: t.avg_power_w != null ? `${t.avg_power_w} / ${t.np_w ?? '—'}` : null },
    { key: 'dist', label: 'Distance', value: ((t.distance_m ?? 0) / 1000).toFixed(2), unit: 'km' },
  ]
}

const pick = (all: Stat[], keys: string[]) => keys.map((k) => all.find((s) => s.key === k)).filter((s): s is Stat => !!s)

function Tile({ s }: { s: Stat }) {
  return <Metric label={s.label} value={s.value} unit={s.unit} sub={s.sub} className="ck-tile" valueColor={s.color} title={s.title} />
}

function BigStat({ label, value, unit, sub }: { label: string; value: string | number | null | undefined; unit?: string; sub?: ReactNode }) {
  return (
    <div className="ck-big">
      <span className="label">{label}</span>
      <b>
        {value ?? '—'}
        {unit && <span className="unit">{unit}</span>}
      </b>
      {sub && <small>{sub}</small>}
    </div>
  )
}

// ---------------------------------------------------------------------------------------
// power dial

/** Arc over target × (1 ± 25 %), zone bands, a marker and the 3 s power in the centre: the
 *  number, the marker and the zone message all use the same 3 s value. */
function Dial({ c }: { c: RideCtx }) {
  const t = c.tel
  const range = 0.25
  const target = c.showGauge ? t.target_w! : null
  const p3 = t.power_avg3_w ?? t.power_w ?? 0
  const shown = t.power_avg3_w != null ? Math.round(t.power_avg3_w) : t.power_w
  const pz = shown ? powerZone(shown, c.ftp) : null // training zone of the 3 s power (Coggan)
  const lo = target ? target * (1 - range) : 0
  const hi = target ? target * (1 + range) : Math.max(400, c.ftp * 1.5)
  const cx = 160
  const cy = 165
  const r = 128
  const frac = (w: number) => Math.min(1, Math.max(0, (w - lo) / (hi - lo)))
  const ang = (f: number) => ((210 - 240 * f) * Math.PI) / 180
  const pt = (f: number, rr = r) => [cx + rr * Math.cos(ang(f)), cy - rr * Math.sin(ang(f))]
  const arc = (f0: number, f1: number) => {
    const [x0, y0] = pt(f0)
    const [x1, y1] = pt(f1)
    return `M ${x0} ${y0} A ${r} ${r} 0 ${(f1 - f0) * 240 > 180 ? 1 : 0} 1 ${x1} ${y1}`
  }
  const bands: [number, number, string][] = []
  if (target) {
    const ok = Math.max(0.05 * target, 5)
    const warn = Math.max(0.1 * target, 10)
    bands.push(
      [lo, target - warn, 'var(--zone-too-low)'],
      [target - warn, target - ok, 'var(--zone-low)'],
      [target - ok, target + ok, 'var(--zone-on)'],
      [target + ok, target + warn, 'var(--zone-high)'],
      [target + warn, hi, 'var(--zone-too-high)'],
    )
  }
  const [mx, my] = pt(frac(p3), r)
  const zone = target ? targetZone(p3, target) : null
  const [tx0, ty0] = pt(0.5, r - 22)
  const [tx1, ty1] = pt(0.5, r + 22)
  return (
    // viewBox must contain the arc ends (y ≈ 165 + 128·sin 30° + stroke) and the min/max labels
    <svg viewBox="0 0 320 262" className="ck-dial">
      <path d={arc(0, 1)} className="ck-track" />
      {bands.map(([a, b, col], i) => (
        <path key={i} d={arc(frac(a), frac(b))} stroke={col} className="ck-band" />
      ))}
      {target && <line x1={tx0} y1={ty0} x2={tx1} y2={ty1} className="ck-target-tick" />}
      <circle cx={mx} cy={my} r={11} className="ck-marker" />
      <text x={cx} y={cy - 22} className={`ck-power zone-text-${zone ?? 'none'}`}>
        {shown ?? '—'}
      </text>
      <text x={cx} y={cy + 8} className="ck-unit">
        W (3 s) · {wkg(shown, t.rider_mass_kg)} W/kg
        {pz && (
          <tspan fill={pz.color} className="ck-pzone">
            <title>{`Power zone ${pz.n}: ${pz.name} (Coggan, % of FTP)`}</title> · Z{pz.n}
          </tspan>
        )}
      </text>
      <text x={cx} y={cy + 44} className="ck-target">
        {target ? `target ${target} W` : t.sim_grade_pct != null ? `Sim · ${t.sim_grade_pct.toFixed(1)} %` : 'free ride'}
      </text>
      {target && (
        <text x={cx} y={cy + 66} className={`ck-zone zone-text-${zone}`}>
          {ZONE_LABEL[zone!]}
        </text>
      )}
      {target && c.sourceLabel && (
        <text x={cx} y={cy + 88} className="ck-source">
          {c.sourceLabel}
        </text>
      )}
      <text x={pt(0)[0]} y={pt(0)[1] + 22} className="ck-scale">
        {Math.round(lo)}
      </text>
      <text x={pt(1)[0]} y={pt(1)[1] + 22} className="ck-scale">
        {Math.round(hi)}
      </text>
    </svg>
  )
}

// ---------------------------------------------------------------------------------------
// cards

function SessionCard({ c }: { c: RideCtx }) {
  const t = c.tel
  if (!c.workout) return null
  const done = t.workout_duration_s != null && (t.elapsed_s ?? 0) >= t.workout_duration_s
  return (
    <div className="card ck-session">
      <div className="ck-session-head">
        <span className="ck-label">Session</span>
        <b>{c.workout.name}</b>
        {/* the step countdown and next target are shown in big type next to the dial */}
        <span className="ck-step">{done ? (t.mode === 'gpx' ? 'done · Slope ERG until end of lap' : 'done') : null}</span>
      </div>
      <WorkoutProfile steps={c.workout.steps} ftp={c.ftp} scale={(t.intensity_pct ?? 100) / 100} elapsed={t.elapsed_s} height={64} />
      <small className="muted">
        {fmtTime(t.elapsed_s)} / {fmtTime(c.workout.duration_s)}
        {t.remaining_workout_distance_m != null && (
          <span title={DIST_LEFT_TITLE}> · ≈ {(t.remaining_workout_distance_m / 1000).toFixed(1)} km to go</span>
        )}
      </small>
    </div>
  )
}

/** Zoomed profile of what is coming, with the current grade and climb rate under it. */
function AheadCard({ c }: { c: RideCtx }) {
  if (!c.route || c.routePos == null) return null
  const t = c.tel
  const current = t.grade != null ? { grade: t.grade, altitude: t.altitude_m ?? 0, vamMh: t.vam_mh ?? null } : undefined
  return (
    <div className="card side-card">
      <LocalProfile
        distance={c.route.profile_distance_m}
        altitude={c.route.altitude_m}
        grade={c.route.grade}
        position={c.routePos}
        speedKmh={t.avg_speed_kmh}
        loop={!!c.workout}
        height={90}
        current={current}
      />
    </div>
  )
}

/** Full-route profile with progress: done (distance, climbing) vs left, done part shaded. */
function RouteProgressCard({ c }: { c: RideCtx }) {
  const t = c.tel
  if (!c.route) return null
  const total = c.route.distance_m || 1
  const pos = Math.min(Math.max(c.routePos ?? 0, 0), total)
  return (
    <div className="card side-card ck-progress">
      <div className="ck-progress-head">
        <span>
          <i>Done</i> <b>{((t.distance_m ?? 0) / 1000).toFixed(2)}</b> km · <b>+{(t.elevation_gain_m ?? 0).toFixed(0)}</b> m
        </span>
        <span>
          <i>Left{c.workout ? ' (lap)' : ''}</i> <b>{c.remainingDist != null ? (c.remainingDist / 1000).toFixed(2) : '—'}</b> km ·{' '}
          <b>{t.elevation_left_m != null ? t.elevation_left_m.toFixed(0) : '—'}</b> m
          {t.remaining_time_s != null && (
            <>
              {' '}
              · <b title={TIME_LEFT_TITLE}>≈ {fmtTime(t.remaining_time_s)}</b>
            </>
          )}
        </span>
      </div>
      <div className="ck-profile-wrap">
        <ElevationProfile distance={c.route.profile_distance_m} altitude={c.route.altitude_m} grade={c.route.grade} position={c.routePos} height={64} start={c.skippedM} />
        <div className="ck-done-shade" style={{ width: `${(pos / total) * 100}%` }} />
      </div>
      <small className="muted">
        {(c.route.distance_m / 1000).toFixed(1)} km · +{c.route.ascent_m.toFixed(0)} m{c.lap > 1 ? ` · lap ${c.lap}` : ''}
      </small>
    </div>
  )
}

function MapCard({ c }: { c: RideCtx }) {
  if (!c.route) return null
  return (
    <div className="card map-card ck-fill">
      <label className="inline map-follow">
        <input type="checkbox" checked={c.follow} onChange={(e) => c.setFollow(e.target.checked)} /> follow rider
      </label>
      <RouteMap
        latlon={c.route.latlon}
        position={c.tel.lat != null ? [c.tel.lat, c.tel.lon!] : undefined}
        follow={c.follow}
        done={c.doneIdx}
        start={c.skippedM > 0 ? indexAt(c.route.profile_distance_m, c.skippedM) : undefined}
        height="100%"
      />
      <WindBadge kmh={c.tel.wind_kmh ?? 0} fromDeg={c.tel.wind_from_deg ?? 0} head={c.tel.headwind_kmh} cross={c.tel.crosswind_kmh} />
    </div>
  )
}

// ---------------------------------------------------------------------------------------
export function RideCockpit({ c }: { c: RideCtx }) {
  const t = c.tel
  const all = stats(c)
  const inWorkout = !!c.workout && !(t.workout_duration_s != null && (t.elapsed_s ?? 0) >= t.workout_duration_s)
  const left = pick(all, ['time', 'cad', 'hr'])
  // distance and climbing are on the route-progress card when there is a route
  const right = pick(all, ['speed', 'avg', ...(c.route ? [] : ['dist'])])
  return (
    <div className="ride ride-fit cockpit">
      {c.head}
      {/* ERG: no route cards, the session and the dial take the whole width */}
      <div className={`ck-main ${c.route ? '' : 'ck-solo'}`}>
        <div className="ck-left">
          <SessionCard c={c} />
          <div className="card ck-dial-card">
            <div className="ck-col">
              {inWorkout && (
                <BigStat label="Step left" value={fmtTime(t.step_remaining_s)} sub={t.next_target_w != null ? <>next <b>{t.next_target_w} W</b></> : undefined} />
              )}
              {left.map((s) => (
                <Tile key={s.key} s={s} />
              ))}
            </div>
            <Dial c={c} />
            <div className="ck-col">
              {inWorkout && (
                <BigStat label="Interval avg" value={t.step_avg_power_w} unit="W" sub={t.target_w != null ? <>target <b>{t.target_w} W</b></> : undefined} />
              )}
              {right.map((s) => (
                <Tile key={s.key} s={s} />
              ))}
            </div>
          </div>
        </div>
        {c.route && (
          <div className="ck-side">
            <AheadCard c={c} />
            <RouteProgressCard c={c} />
            <MapCard c={c} />
          </div>
        )}
      </div>
      <div className="ck-bottom">{c.controls}</div>
    </div>
  )
}
