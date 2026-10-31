import { useMemo, useState } from 'react'
import { api, fmtTime, type Profile, type RouteDetail, type Telemetry, type Workout } from '../api'
import { ElevationProfile, LiveChart, WorkoutProfile } from '../components/charts'
import { ManualTarget } from '../components/ManualTarget'
import { RouteMap } from '../components/RouteMap'
import { TargetGauge } from '../components/TargetGauge'
import { targetZone } from '../targetZone'
import type { HistoryPoint } from '../useLive'

export interface ActiveRide {
  sessionId: string
  mode: 'erg' | 'gpx'
  workout?: Workout
  route?: RouteDetail
}

function Metric({ label, value, unit, big, sub, className = '' }: { label: string; value: string | number | null | undefined; unit?: string; big?: boolean; sub?: string; className?: string }) {
  return (
    <div className={`metric ${big ? 'big' : ''} ${className}`}>
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

export function RidePage({ tel, history, active, profile, onEnd }: { tel: Telemetry; history: { current: HistoryPoint[] }; active: ActiveRide | null; profile: Profile | null; onEnd: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const [follow, setFollow] = useState(true)
  const inSession = ['ready', 'running', 'paused', 'finished'].includes(tel.state)
  const route = active?.route
  const workout = active?.workout
  const ftp = profile?.ftp_w ?? 250

  const doneIdx = useMemo(() => {
    if (!route || tel.distance_m == null) return 0
    const k = route.profile_distance_m.findIndex((d) => d >= tel.distance_m!)
    return k < 0 ? route.latlon.length - 1 : k
  }, [route, tel.distance_m])

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
  const zone = showGauge ? targetZone(tel.power_avg3_w ?? 0, tel.target_w!) : null
  const totalSplit = split ? Math.max(1, split.gravity + split.rolling + split.aero) : 1
  const remainingDist = route && tel.distance_m != null ? route.distance_m - tel.distance_m : null

  return (
    <div className="ride">
      <div className="ride-head">
        <div>
          <h2>{tel.name}</h2>
          <span className={`badge state-${tel.state}`}>{tel.state}</span>
          <span className="badge">{tel.mode === 'erg' ? 'ERG workout' : 'GPX · pseudo-ERG'}</span>
          <span className="badge">power: {tel.power_source}</span>
        </div>
        <div className="controls">
          {tel.state === 'running' && <button onClick={() => act(api.pause)}>Pause</button>}
          {(tel.state === 'paused' || tel.state === 'ready') && <button onClick={() => act(api.resume)}>Resume</button>}
          <button
            className="danger"
            onClick={() => {
              if (tel.state === 'finished' || confirm('Stop and save this ride?')) act(() => api.stop(true).then(onEnd))
            }}
          >
            {tel.state === 'finished' ? 'Close' : 'Stop & save'}
          </button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {tel.state === 'ready' && <div className="hint">Start pedalling to begin — the clock starts automatically.</div>}
      {tel.state === 'finished' && <div className="hint ok">Finished! Ride saved{tel.saved ? ` (#${tel.saved.ride_id})` : ''}.</div>}

      <div className="metrics">
        <Metric big label="Power" className={zone ? `zone-${zone}` : ''} value={tel.power_w} unit="W" sub={tel.pm_power_w != null && tel.trainer_power_w != null ? `PM ${tel.pm_power_w} · trainer ${tel.trainer_power_w}` : undefined} />
        <Metric big label="Target" value={tel.target_w} unit="W" sub={tel.sent_target_w != null && tel.sent_target_w !== tel.target_w ? `sent ${tel.sent_target_w} W (match ${tel.power_match_offset_w! > 0 ? '+' : ''}${tel.power_match_offset_w} W)` : undefined} />
        <Metric big label="W/kg" value={tel.power_wkg?.toFixed(2)} unit="W/kg" sub={tel.target_wkg != null ? `target ${tel.target_wkg.toFixed(2)} W/kg` : undefined} />
        <Metric big label="Speed" value={tel.speed_kmh?.toFixed(1)} unit="km/h" />
        <Metric label="Time" value={fmtTime(tel.elapsed_s)} />
        <Metric label="Distance" value={((tel.distance_m ?? 0) / 1000).toFixed(2)} unit="km" sub={remainingDist != null ? `${(remainingDist / 1000).toFixed(2)} km to go` : undefined} />
        <Metric label="Cadence" value={tel.cadence_rpm} unit="rpm" sub={tel.cadence_source && tel.cadence_source !== 'none' ? tel.cadence_source.replace('_', ' ') : undefined} />
        <Metric label="Heart rate" value={tel.heart_rate_bpm} unit="bpm" />
        {tel.mode === 'gpx' && <Metric label="Grade" value={((tel.grade ?? 0) * 100).toFixed(1)} unit="%" sub={`${tel.altitude_m?.toFixed(0)} m`} />}
        {tel.mode === 'erg' && <Metric label="Step left" value={fmtTime(tel.step_remaining_s)} sub={tel.next_target_w != null ? `next ${tel.next_target_w} W` : undefined} />}
      </div>

      {showGauge && <TargetGauge power={tel.power_avg3_w} target={tel.target_w} />}

      <div className="card adjust">
        {tel.mode === 'erg' ? (
          <Stepper label="Intensity" value={tel.intensity_pct ?? 100} step={1} onChange={(v) => act(() => api.adjust({ intensity_pct: v }))} />
        ) : (
          <>
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
              <Stepper label="Effort (target power)" value={tel.effort_pct ?? 100} step={2} onChange={(v) => act(() => api.adjust({ effort_pct: v }))} />
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
      </div>

      {workout && (
        <div className="card">
          <WorkoutProfile steps={workout.steps} ftp={ftp} scale={(tel.intensity_pct ?? 100) / 100} elapsed={tel.elapsed_s} />
          <small className="muted">
            {fmtTime(tel.elapsed_s)} / {fmtTime(workout.duration_s)}
          </small>
        </div>
      )}

      {route && (
        <div className="grid2">
          <div className="card">
            <label className="inline">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow rider
            </label>
            <RouteMap latlon={route.latlon} position={tel.lat != null ? [tel.lat, tel.lon!] : undefined} follow={follow} done={doneIdx} height={340} />
          </div>
          <div className="card">
            <ElevationProfile distance={route.profile_distance_m} altitude={route.altitude_m} grade={route.grade} position={tel.distance_m} height={160} />
            <small className="muted">
              {(route.distance_m / 1000).toFixed(1)} km · +{route.ascent_m.toFixed(0)} m
            </small>
          </div>
        </div>
      )}

      <div className="card">
        <LiveChart history={history} tick={tel.elapsed_s} />
      </div>
    </div>
  )
}
