import { useMemo, useState } from 'react'
import { api, type Profile, type RouteDetail, type Telemetry, type Workout } from '../api'
import { ManualTarget } from '../components/ManualTarget'
import { SHORTCUTS_HELP, useRideShortcuts } from '../rideKeys'
import { useStepCues } from '../stepCues'
import type { WakeLockStatus } from '../wakeLock'
import type { HistoryPoint } from '../useLive'
import { RideCockpit } from './RideCockpit'

export interface ActiveRide {
  sessionId: string
  mode: 'erg' | 'gpx'
  workout?: Workout
  route?: RouteDetail
  /** revision of the workout above (the rider may skip / extend steps during the ride) */
  workoutRev?: number
}

export function Metric({
  label,
  value,
  unit,
  big,
  sub,
  className = '',
  title,
}: {
  label: string
  value: string | number | null | undefined
  unit?: string
  big?: boolean
  sub?: string
  className?: string
  title?: string
}) {
  return (
    <div className={`metric ${big ? 'big' : ''} ${className}`} title={title}>
      <div className="label">{label}</div>
      <div className="value">
        {value ?? '—'}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

function Stepper({ label, value, step, onChange, unit = '%', signed }: { label: string; value: number; step: number; onChange: (v: number) => void; unit?: string; signed?: boolean }) {
  return (
    <div className="stepper">
      <span className="label">{label}</span>
      <button onClick={() => onChange(value - step)}>−</button>
      <span className="val">
        {signed && value > 0 ? '+' : ''}
        {Math.round(value)}
        {unit}
      </span>
      <button onClick={() => onChange(value + step)}>+</button>
    </div>
  )
}

export function RidePage({
  tel,
  history,
  active,
  profile,
  wake,
  onEnd,
}: {
  tel: Telemetry
  history: { current: HistoryPoint[] }
  active: ActiveRide | null
  profile: Profile | null
  wake: WakeLockStatus
  /** the ride view is closed; ``rideId`` of the ride saved, if any */
  onEnd: (rideId?: number) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [follow, setFollow] = useState(true)
  const [sound, setSound] = useStepCues(tel) // 3-2-1 beeps before each workout step change
  const inSession = ['ready', 'running', 'paused', 'finished'].includes(tel.state)
  const route = active?.route
  const workout = active?.workout
  useRideShortcuts({ tel, enabled: inSession && !!active, hasWorkout: !!workout, sound, setSound, onError: setError })
  const ftp = profile?.ftp_w ?? 250

  // position within the current lap (the route loops in GPX + workout rides)
  const routePos = tel.route_position_m ?? tel.distance_m
  const doneIdx = useMemo(() => {
    if (!route || routePos == null) return 0
    const k = route.profile_distance_m.findIndex((d) => d >= routePos)
    return k < 0 ? route.latlon.length - 1 : k
  }, [route, routePos])

  const act = (f: () => Promise<unknown>) => f().catch((e: Error) => setError(e.message))

  if (!inSession || !active) {
    return (
      <div className="card empty">
        <h2>No ride in progress</h2>
        <p>Pick a workout (ERG mode) or a GPX route (slope mode) to start.</p>
        {tel.state !== 'disconnected' && (
          <div className="row">
            <Metric label="Power" value={tel.power_w} unit="W" sub={tel.power_source} />
            <Metric label="W/kg" value={tel.power_wkg?.toFixed(2)} unit="W/kg" />
            <Metric label="Cadence" value={tel.cadence_rpm} unit="rpm" sub={tel.cadence_source && tel.cadence_source !== 'none' ? tel.cadence_source.replace('_', ' ') : undefined} />
            <Metric label="Heart rate" value={tel.heart_rate_bpm} unit="bpm" />
          </div>
        )}
      </div>
    )
  }

  const split = tel.power_split_w
  const showGauge = tel.target_w != null && (tel.state === 'running' || tel.state === 'paused')
  const totalSplit = split ? Math.max(1, split.gravity + split.rolling + split.aero) : 1
  const remainingDist = route && routePos != null ? route.distance_m - routePos : null
  const lap = tel.lap ?? 1
  const modeLabel = tel.mode === 'erg' ? 'ERG workout' : workout ? 'GPX + workout' : 'GPX · pseudo-ERG'

  // head (title, badges, pause/stop) and controls, laid out by RideCockpit
  const head = (
    <>
      <div className="ride-head">
        <div>
          <h2>{tel.name}</h2>
          <span className={`badge state-${tel.state}`}>{tel.state}</span>
          <span className="badge">{modeLabel}</span>
          {lap > 1 && <span className="badge">lap {lap}</span>}
          <span className="badge">power: {tel.power_source}</span>
          {wake === 'on' && (
            <span className="badge" title="The screen will not go to sleep during the ride">
              screen on
            </span>
          )}
          {wake === 'unsupported' && tel.state !== 'finished' && (
            <span className="badge warn" title="This browser cannot keep the screen on here (needs localhost or HTTPS): turn off screen sleep in the system settings">
              screen may sleep
            </span>
          )}
        </div>
        <div className="controls">
          {workout && (
            <button className={sound ? '' : 'muted'} onClick={() => setSound(!sound)} title="Beeps 3-2-1 before each step change, a rising tone when the target goes up">
              {sound ? 'Sound on' : 'Sound off'}
            </button>
          )}
          {tel.state === 'running' && <button onClick={() => act(api.pause)}>Pause</button>}
          {(tel.state === 'paused' || tel.state === 'ready') && <button onClick={() => act(api.resume)}>Resume</button>}
          <button
            className="danger"
            onClick={() => {
              if (tel.state === 'finished' || confirm('Stop and save this ride?')) act(() => api.stop(true).then((r) => onEnd(r.saved?.ride_id)))
            }}
          >
            {tel.state === 'finished' ? 'Close' : 'Stop & save'}
          </button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {tel.state === 'ready' && <div className="hint">Start pedalling to begin — the clock starts automatically.</div>}
      {tel.state === 'finished' && <div className="hint ok">Finished! {tel.saved ? `Ride saved (#${tel.saved.ride_id}).` : 'Saving the ride…'}</div>}
    </>
  )

  // the current workout step can be skipped or extended
  const stepEditable =
    !!workout && (tel.state === 'running' || tel.state === 'paused' || tel.state === 'ready') && (tel.elapsed_s ?? 0) < (tel.workout_duration_s ?? 0)
  const stepControls = stepEditable && (
    <div className="seg step-edit" title="Current workout step">
      <button onClick={() => act(() => api.extendStep(60))} title="Make the current step 1 min longer">
        +1 min
      </button>
      <button onClick={() => act(api.skipStep)} title="End the current step now and start the next one">
        Skip step ⏭
      </button>
    </div>
  )

  const controls = (
      <div className="card adjust">
        {stepControls}
        {tel.mode === 'erg' ? (
          <Stepper label="Intensity" value={tel.intensity_pct ?? 100} step={1} onChange={(v) => act(() => api.adjust({ intensity_pct: v }))} />
        ) : (
          <>
            {workout && (
              <Stepper label="Workout intensity" value={tel.intensity_pct ?? 100} step={1} onChange={(v) => act(() => api.adjust({ intensity_pct: v }))} />
            )}
            <div className="seg target-mode" title="How the trainer target is set">
              <button className={tel.target_mode !== 'manual' ? 'on' : ''} onClick={() => act(() => api.adjust({ target_mode: 'slope' }))}>
                Slope
              </button>
              <button className={tel.target_mode === 'manual' ? 'on' : ''} onClick={() => act(() => api.adjust({ target_mode: 'manual' }))}>
                Manual
              </button>
            </div>
            {tel.target_mode === 'manual' && tel.manual_target_w != null ? (
              <ManualTarget key={tel.name} initial={tel.manual_target_w} onError={setError} />
            ) : (
              <Stepper label={workout ? 'Slope effort' : 'Effort (target power)'} value={tel.effort_pct ?? 100} step={2} onChange={(v) => act(() => api.adjust({ effort_pct: v }))} />
            )}
            <Stepper label="Difficulty (speed = P×)" value={tel.difficulty_pct ?? 0} step={1} signed onChange={(v) => act(() => api.adjust({ difficulty_pct: v }))} />
          </>
        )}
        {split && (
          <div className="split" title="Instantaneous resistive power at current speed">
            <span>Resistive power</span>
            <div className="bar">
              <div style={{ width: `${(Math.max(0, split.gravity) / totalSplit) * 100}%` }} className="grav" />
              <div style={{ width: `${(split.rolling / totalSplit) * 100}%` }} className="roll" />
              <div style={{ width: `${(split.aero / totalSplit) * 100}%` }} className="aero" />
            </div>
            <small>
              gravity {split.gravity.toFixed(0)} W · rolling {split.rolling.toFixed(0)} W · aero {split.aero.toFixed(0)} W · ρ {tel.air_density?.toFixed(3)} kg/m³
            </small>
          </div>
        )}
        <small className="shortcuts-help" title="Keyboard shortcuts">
          ⌨ {SHORTCUTS_HELP}
        </small>
      </div>
  )

  // Cockpit layout (RideCockpit): fits the window on desktop screens
  return <RideCockpit c={{ tel, history, route, workout, ftp, routePos, doneIdx, follow, setFollow, showGauge, remainingDist, lap, head, controls }} />
}
