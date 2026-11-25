import { useEffect, useMemo, useState } from 'react'
import { api, type Profile, type RouteDetail, type Telemetry, type Workout } from '../api'
import { BatteryWarning } from '../components/BatteryWarning'
import { CalibrationOffer } from '../components/Calibration'
import { ManualTarget } from '../components/ManualTarget'
import { StopDialog } from '../components/StopDialog'
import { useNudge, useRideShortcuts } from '../rideKeys'
import { loadTrainerEffect, saveTrainerEffect } from '../wind'
import { shortcutsHelp, SOURCE_LABEL, targetSource } from '../targetSource'
import { useStepCues } from '../stepCues'
import type { WakeLockStatus } from '../wakeLock'
import { Immersive } from './Immersive'
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
  valueColor,
}: {
  label: string
  value: string | number | null | undefined
  unit?: string
  big?: boolean
  sub?: string
  className?: string
  title?: string
  /** e.g. the heart rate in the colour of its zone */
  valueColor?: string
}) {
  return (
    <div className={`metric ${big ? 'big' : ''} ${className}`} title={title}>
      <div className="label">{label}</div>
      <div className="value" style={valueColor ? { color: valueColor } : undefined}>
        {value ?? '—'}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

/** − value + ; `onStep` is `useNudge`'s (rapid clicks add up, requests sent in order). */
function Stepper({ label, value, onStep, unit = '%', title }: { label: string; value: number; onStep: (up: boolean) => void; unit?: string; title?: string }) {
  return (
    <div className="stepper" title={title}>
      <span className="label">{label}</span>
      <button onClick={() => onStep(false)}>−</button>
      <span className="val">
        {Math.round(value)}
        {unit}
      </span>
      <button onClick={() => onStep(true)}>+</button>
    </div>
  )
}

export function RidePage({
  tel,
  active,
  profile,
  wake,
  onEnd,
}: {
  tel: Telemetry
  active: ActiveRide | null
  profile: Profile | null
  wake: WakeLockStatus
  /** the ride view is closed; ``rideId`` of the ride saved, if any */
  onEnd: (rideId?: number) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [stopAsk, setStopAsk] = useState(false)
  const [follow, setFollow] = useState(true)
  const [sound, setSound] = useStepCues(tel) // 3-2-1 beeps before each workout step change
  const inSession = ['ready', 'running', 'paused', 'finished'].includes(tel.state)
  const route = active?.route
  const workout = active?.workout
  // immersive 3D view, per ride (a new ride starts on the normal screen); left when the ride
  // ends, so the "finished" message and the upload prompt are not hidden behind it
  const [immersiveRide, setImmersiveRide] = useState<string | null>(null)
  const canImmersive = ['ready', 'running', 'paused'].includes(tel.state) && !!route
  const immersive = canImmersive && immersiveRide === active?.sessionId
  const setImmersive = (on: boolean) => setImmersiveRide(on && active ? active.sessionId : null)
  // the workout still sets the target; once it is over, a GPX + workout ride behaves like a
  // plain GPX ride (slope effort or manual target), so the workout intensity is not offered
  const workoutActive = !!workout && (tel.elapsed_s ?? 0) < (tel.workout_duration_s ?? 0)
  // what sets the trainer target now (workout, its free-ride steps, slope, manual): the
  // controls show the value of that source, and ↑ / ↓ change it
  const source = targetSource({
    mode: tel.mode,
    targetMode: tel.target_mode,
    manualTargetW: tel.manual_target_w,
    workoutActive,
    step: tel.step_index != null ? workout?.steps[tel.step_index] : undefined,
  })
  const { nudge, shown } = useNudge(tel, setError) // ↑ / ↓ keys and +/− buttons
  // Sim: the trainer effect is remembered per browser for the next Sim ride
  const effect = tel.trainer_effect_pct
  useEffect(() => {
    if (tel.target_mode === 'sim' && effect != null) saveTrainerEffect(effect)
  }, [tel.target_mode, effect])
  useRideShortcuts({ tel, enabled: inSession && !!active, source, nudge, sound, setSound, onError: setError, canImmersive, immersive, setImmersive })
  const ftp = profile?.ftp_w ?? 250
  const lthr = profile?.threshold_hr_bpm ?? null // heart-rate zones

  // position within the current lap (the route loops in GPX + workout rides)
  const routePos = tel.route_position_m ?? tel.distance_m
  // started part-way: the part before the start point is greyed, on the first lap only
  const skippedM = (tel.lap ?? 1) === 1 ? (tel.route_start_m ?? 0) : 0
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
        <p>Pick a workout (ERG mode) or a GPX route (Slope ERG) to start.</p>
        {tel.state !== 'disconnected' && (
          <div className="row">
            <Metric label="Power" value={tel.power_w} unit="W" sub={tel.power_source} />
            <Metric label="W/kg" value={tel.power_wkg?.toFixed(2)} unit="W/kg" />
            <Metric label="Cadence" value={tel.cadence_rpm} unit="rpm" sub={tel.cadence_source && tel.cadence_source !== 'none' ? tel.cadence_source.replace('_', ' ') : undefined} />
            <Metric label="Heart rate" value={tel.heart_rate_bpm} unit="bpm" />
          </div>
        )}
        <CalibrationOffer devices={tel.devices} />
        <BatteryWarning devices={tel.devices} />
      </div>
    )
  }

  const split = tel.power_split_w
  const showGauge = tel.target_w != null && (tel.state === 'running' || tel.state === 'paused')
  const totalSplit = split ? Math.max(1, split.gravity + split.rolling + split.aero) : 1
  const remainingDist = route && routePos != null ? route.distance_m - routePos : null
  const lap = tel.lap ?? 1
  // under the power dial: where the target comes from (GPX rides; in ERG it is the workout)
  const sourceLabel = tel.mode === 'gpx' ? SOURCE_LABEL[source] : undefined
  const modeLabel = tel.mode === 'erg' ? 'ERG workout' : workout ? 'GPX + workout' : tel.target_mode === 'sim' ? 'GPX · Sim' : 'GPX · Slope ERG'

  const pauseButton =
    tel.state === 'running' ? (
      <button onClick={() => act(api.pause)}>Pause</button>
    ) : tel.state === 'paused' || tel.state === 'ready' ? (
      <button onClick={() => act(api.resume)}>Resume</button>
    ) : null
  const stop = (save: boolean) => {
    setStopAsk(false)
    act(() => api.stop(save).then((r) => onEnd(r.saved?.ride_id)))
  }
  const stopButton = (
    <button className="danger" onClick={() => (tel.state === 'finished' ? stop(true) : setStopAsk(true))}>
      {tel.state === 'finished' ? 'Close' : 'Stop'}
    </button>
  )
  const stopDialog = stopAsk && tel.state !== 'finished' && (
    <StopDialog elapsedS={tel.elapsed_s} distanceM={tel.mode === 'gpx' ? tel.distance_m : undefined} onSave={() => stop(true)} onDiscard={() => stop(false)} onClose={() => setStopAsk(false)} />
  )

  // head (title, badges, pause/stop) and controls, laid out by RideCockpit
  const head = (
    <>
      <div className="ride-head">
        <div>
          <h2 title={tel.name}>{tel.name}</h2>
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
          {canImmersive && (
            <button className="im-open" onClick={() => setImmersive(true)} title="Immersive 3D view of the route (V)">
              ⤢ Immersive <kbd>V</kbd>
            </button>
          )}
          {workout && (
            <button className={sound ? '' : 'muted'} onClick={() => setSound(!sound)} title="Beeps 3-2-1 before each step change, a rising tone when the target goes up">
              {sound ? 'Sound on' : 'Sound off'}
            </button>
          )}
          {pauseButton}
          {stopButton}
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {tel.state === 'ready' && (
        <>
          <div className="hint">Start pedalling to begin — the clock starts automatically.</div>
          <CalibrationOffer devices={tel.devices} />
          <BatteryWarning devices={tel.devices} start />
        </>
      )}
      {/* after the warm-up: calibrate while paused, the next pedal stroke resumes the ride */}
      {tel.state === 'paused' && <CalibrationOffer devices={tel.devices} />}
      {tel.state === 'finished' && (
        <>
          <div className="hint ok">Finished! {tel.saved ? `Ride saved (#${tel.saved.ride_id}).` : 'Saving the ride…'}</div>
          <BatteryWarning devices={tel.devices} start />
        </>
      )}
    </>
  )

  // the current workout step can be skipped or extended
  const stepEditable = workoutActive && (tel.state === 'running' || tel.state === 'paused' || tel.state === 'ready')
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

  // the value of the current target source (see targetSource.ts); in a free-ride step the
  // workout intensity stays offered, for the steps that follow
  const intensity = (label: string, title?: string) => (
    <Stepper label={label} title={title} value={shown('intensity_pct')} onStep={(up) => nudge('intensity_pct', up)} />
  )
  const effort = (label: string) => (
    <Stepper label={label} value={shown('effort_pct')} onStep={(up) => nudge('effort_pct', up)} />
  )
  const nextStepsTitle = 'Scales the targets of the workout steps (this free-ride step is in Slope ERG)'
  const sourceControls = (compact: boolean) =>
    source === 'manual' && tel.manual_target_w != null ? (
      <ManualTarget key={tel.session_id} server={tel.manual_target_w} onError={setError} />
    ) : source === 'workout' ? (
      intensity('Intensity')
    ) : source === 'sim' ? (
      <Stepper
        label={compact ? 'Trainer effect' : `Trainer effect · grade sent ${tel.sim_grade_pct != null ? `${tel.sim_grade_pct.toFixed(1)} %` : '—'}`}
        title="Share of the route's grade the trainer simulates (shift gears as on the road)"
        value={shown('trainer_effect_pct')}
        onStep={(up) => nudge('trainer_effect_pct', up)}
      />
    ) : source === 'free-ride' ? (
      <>
        {effort(compact ? 'Free-ride step · effort' : 'Free-ride step → Slope ERG · effort')}
        {intensity(compact ? 'Intensity' : 'Intensity (next steps)', nextStepsTitle)}
      </>
    ) : (
      effort('Effort')
    )

  const controls = (
      <div className="card adjust">
        {stepControls}
        {tel.mode === 'gpx' && (
          // left button: the automatic source (the workout while it lasts, else the slope)
          <div className="seg target-mode" title="What sets the trainer target">
            <button
              className={tel.target_mode !== 'manual' && tel.target_mode !== 'sim' ? 'on' : ''}
              onClick={() => act(() => api.adjust({ target_mode: 'slope' }))}
              title={workoutActive ? 'The workout sets the target (Slope ERG in its free-ride steps)' : 'Slope ERG: the slope of the route sets the target, held by the trainer in ERG (no shifting)'}
            >
              {workoutActive ? 'Workout' : 'Slope ERG'}
            </button>
            <button
              className={tel.target_mode === 'sim' ? 'on' : ''}
              onClick={() => act(() => api.adjust({ target_mode: 'sim', trainer_effect_pct: loadTrainerEffect() }))}
              title="Sim: the trainer simulates the route's grade (× trainer effect); you shift and choose your power, like on the road"
            >
              Sim
            </button>
            <button className={source === 'manual' ? 'on' : ''} onClick={() => act(() => api.adjust({ target_mode: 'manual' }))} title="Set the target in watts">
              Manual
            </button>
          </div>
        )}
        {sourceControls(false)}
        {source === 'manual' && workoutActive && <small className="muted override-note">Workout target overridden; its steps keep running.</small>}
        {tel.target_mode === 'sim' && workoutActive && <small className="muted override-note">Sim once the workout is over; until then its targets apply.</small>}
        {split && (
          <div className="split" title="Instantaneous resistive power at current speed">
            <span>Resistive power</span>
            <div className="bar">
              <div style={{ width: `${(Math.max(0, split.gravity) / totalSplit) * 100}%` }} className="grav" />
              <div style={{ width: `${(split.rolling / totalSplit) * 100}%` }} className="roll" />
              <div style={{ width: `${(split.aero / totalSplit) * 100}%` }} className="aero" />
            </div>
            <small>
              <span className="nw">gravity {split.gravity.toFixed(0)} W</span> · <span className="nw">rolling {split.rolling.toFixed(0)} W</span> ·{' '}
              <span className="nw">aero {split.aero.toFixed(0)} W</span> · <span className="nw">ρ {tel.air_density?.toFixed(3)} kg/m³</span>
            </small>
          </div>
        )}
        <small className="shortcuts-help" title="Keyboard shortcuts">
          Keys: {shortcutsHelp(source, { sound: !!workout, immersive: canImmersive })}
        </small>
      </div>
  )

  // compact controls of the immersive view (GPX rides): pause / stop, workout step, the value
  // of the current target source
  const immersiveControls = (
    <>
      {pauseButton}
      {stopButton}
      {stepControls}
      {sourceControls(true)}
    </>
  )

  // Cockpit layout (RideCockpit): fits the window on desktop screens; the immersive view covers it
  return (
    <>
      <RideCockpit c={{ tel, route, workout, ftp, lthr, routePos, doneIdx, skippedM, follow, setFollow, showGauge, remainingDist, lap, head, controls, sourceLabel }} />
      {immersive && route && (
        <Immersive
          tel={tel}
          route={route}
          workout={workout}
          ftp={ftp}
          lthr={lthr}
          routePos={routePos}
          remainingDist={remainingDist}
          doneIdx={doneIdx}
          controls={immersiveControls}
          sourceLabel={sourceLabel}
          sound={sound}
          setSound={setSound}
          error={error}
          onExit={() => setImmersive(false)}
        />
      )}
      {stopDialog}
    </>
  )
}
