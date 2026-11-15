import { useCallback, useEffect, useState } from 'react'
import { WindPicker } from '../components/Wind'
import { loadWind, saveWind, type WindSetting } from '../wind'
import { api, fmtTime, type PlannedWorkout, type Profile, type Ride, type RouteDetail, type RouteEstimate, type RouteSummary, type Workout } from '../api'
import { ElevationProfile, WorkoutProfile } from '../components/charts'
import { RouteMap } from '../components/RouteMap'

function FilePick({ accept, label, onFile }: { accept: string; label: string; onFile: (f: File) => void }) {
  return (
    <label className="button">
      {label}
      <input
        type="file"
        accept={accept}
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onFile(f)
          e.target.value = ''
        }}
      />
    </label>
  )
}

// ---------------------------------------------------------------------------------------
export function WorkoutsPage({ profile, canStart, onStart }: { profile: Profile | null; canStart: boolean; onStart: (w: Workout) => void }) {
  const [list, setList] = useState<Workout[]>([])
  const [planned, setPlanned] = useState<PlannedWorkout[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const reload = useCallback(() => api.workouts().then(setList).catch((e) => setError(e.message)), [])
  useEffect(() => {
    reload()
  }, [reload])
  const ftp = profile?.ftp_w ?? 250

  const run = async (f: () => Promise<unknown>) => {
    setError(null)
    setBusy(true)
    try {
      await f()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="toolbar">
        <FilePick accept=".zwo,.erg,.mrc" label="Import .zwo / .erg / .mrc" onFile={(f) => run(() => api.importWorkout(f).then(reload))} />
        <button disabled={busy} onClick={() => run(() => api.planned().then(setPlanned))}>
          Load planned from intervals.icu
        </button>
      </div>
      {error && <div className="error">{error}</div>}

      {planned && (
        <div className="card">
          <h3>intervals.icu — planned</h3>
          {planned.length === 0 && <p className="muted">No planned workouts in the next 7 days.</p>}
          <table>
            <tbody>
              {planned.map((p) => (
                <tr key={p.id}>
                  <td>{p.date?.slice(0, 10)}</td>
                  <td>{p.name}</td>
                  <td className="muted">{p.type}</td>
                  <td>{fmtTime(p.moving_time_s)}</td>
                  <td>{p.load != null ? `${p.load} TSS` : ''}</td>
                  <td>
                    <button disabled={busy} onClick={() => run(() => api.importPlanned(p.id).then(reload))}>
                      Import
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="cards">
        {list.map((w) => (
          <div className="card" key={w.id}>
            <div className="card-head">
              <h3>{w.name}</h3>
              <span className="muted">
                {fmtTime(w.duration_s)} · {w.source}
              </span>
            </div>
            <WorkoutProfile steps={w.steps} ftp={ftp} height={60} />
            {w.description && <p className="muted desc">{w.description}</p>}
            <div className="row-end">
              <button className="ghost" onClick={() => confirm(`Delete ${w.name}?`) && run(() => api.deleteWorkout(w.id).then(reload))}>
                Delete
              </button>
              <button className="primary" disabled={!canStart} title={canStart ? '' : 'Connect sensors first'} onClick={() => onStart(w)}>
                Ride (ERG)
              </button>
            </div>
          </div>
        ))}
        {list.length === 0 && <p className="muted">No workouts yet — import a file or fetch from intervals.icu.</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------
export function RoutesPage({ canStart, onStart }: { canStart: boolean; onStart: (r: RouteDetail, w: Workout | undefined, wind: WindSetting) => void }) {
  const [list, setList] = useState<RouteSummary[]>([])
  const [wind, setWind] = useState<WindSetting>(loadWind) // last wind used, per browser
  const [sel, setSel] = useState<RouteDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [workouts, setWorkouts] = useState<Workout[]>([])
  const [workoutId, setWorkoutId] = useState<number | null>(null) // optional: GPX + workout
  const reload = useCallback(() => api.routes().then(setList).catch((e) => setError(e.message)), [])
  useEffect(() => {
    reload()
    api.workouts().then(setWorkouts).catch(() => {})
  }, [reload])
  const chosenWorkout = workouts.find((w) => w.id === workoutId)
  // ride the route from its end (a climb becomes its descent): chosen at start, not stored
  const [reverse, setReverse] = useState(false)
  const open = (id: number, rev = reverse) => api.route(id, rev).then(setSel).catch((e) => setError(e.message))
  // estimated time (or, with a workout, distance) for the options chosen; the key says which
  // options an estimate is for, so a stale one is never shown
  const [est, setEst] = useState<{ key: string; value: RouteEstimate } | null>(null)
  const estKey = sel ? JSON.stringify([sel.id, !!sel.reversed, wind.kmh, wind.fromDeg, workoutId]) : ''
  useEffect(() => {
    if (!sel) return
    let cancelled = false
    api
      .routeEstimate(sel.id, { reverse: !!sel.reversed, windKmh: wind.kmh, windFromDeg: wind.fromDeg, workoutId })
      .then((value) => !cancelled && setEst({ key: estKey, value }))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sel, wind.kmh, wind.fromDeg, workoutId, estKey])
  const estimate = est && est.key === estKey ? est.value : null

  return (
    <div>
      <div className="toolbar">
        <FilePick
          accept=".gpx"
          label="Import GPX"
          onFile={(f) =>
            api
              .importRoute(f)
              .then((r) => {
                reload()
                open(r.id)
              })
              .catch((e) => setError(e.message))
          }
        />
      </div>
      {error && <div className="error">{error}</div>}
      <div className="grid-side">
        <div className="list">
          {list.map((r) => (
            <div key={r.id} className={`list-item ${sel?.id === r.id ? 'sel' : ''}`} onClick={() => open(r.id)}>
              <b>{r.name}</b>
              <span className="muted">
                {(r.distance_m / 1000).toFixed(1)} km · +{r.ascent_m.toFixed(0)} m · max {(r.max_grade * 100).toFixed(1)}%
                {r.estimate_s != null && ` · ≈ ${fmtTime(r.estimate_s)}`}
              </span>
            </div>
          ))}
          {list.length === 0 && <p className="muted">No routes yet.</p>}
        </div>
        {sel && (
          <div className="card">
            <div className="card-head">
              <h3>{sel.name}</h3>
              <span className="muted">
                {(sel.distance_m / 1000).toFixed(2)} km · +{sel.ascent_m.toFixed(0)} / −{sel.descent_m.toFixed(0)} m · {sel.min_altitude_m.toFixed(0)}–{sel.max_altitude_m.toFixed(0)} m
              </span>
              {estimate && (
                <span
                  className="estimate"
                  title="Speed model of the ride, the rider holding the targets (Slope ERG at 100 % effort; the workout's targets with a workout), with the wind and direction chosen"
                >
                  {chosenWorkout
                    ? `≈ ${(estimate.distance_m / 1000).toFixed(1)} km in ${fmtTime(estimate.duration_s)} (${estimate.laps.toFixed(1)} laps)`
                    : `≈ ${fmtTime(estimate.duration_s)} at 100 % effort`}
                </span>
              )}
            </div>
            <RouteMap latlon={sel.latlon} height={300} />
            <ElevationProfile distance={sel.profile_distance_m} altitude={sel.altitude_m} grade={sel.grade} height={120} />
            <div className="row-end">
              <button
                className="ghost"
                onClick={() =>
                  confirm(`Delete ${sel.name}?`) &&
                  api.deleteRoute(sel.id).then(() => {
                    setSel(null)
                    reload()
                  })
                }
              >
                Delete
              </button>
              <label className="workout-pick" title="Follow a workout on this route: the workout sets the target, the route gives speed and position">
                <span className="muted">Workout</span>
                <select value={workoutId ?? ''} onChange={(e) => setWorkoutId(e.target.value === '' ? null : Number(e.target.value))}>
                  <option value="">none (Slope ERG)</option>
                  {workouts.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} · {fmtTime(w.duration_s)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="chk" title="Ride the route from its end to its start: a climb becomes its descent">
                <input
                  type="checkbox"
                  checked={reverse}
                  onChange={(e) => {
                    setReverse(e.target.checked)
                    open(sel.id, e.target.checked) // map and profile in the direction ridden
                  }}
                />
                Reverse
              </label>
              <WindPicker value={wind} onChange={setWind} />
              <button
                className="primary"
                disabled={!canStart}
                title={canStart ? '' : 'Connect sensors first'}
                onClick={() => {
                  saveWind(wind)
                  onStart(sel, chosenWorkout, wind)
                }}
              >
                {chosenWorkout ? 'Ride with workout' : 'Ride this route'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------
export function HistoryPage() {
  const [rides, setRides] = useState<Ride[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const reload = useCallback(() => api.rides().then(setRides), [])
  useEffect(() => {
    reload()
  }, [reload])
  return (
    <div className="card">
      {msg && <div className="hint">{msg}</div>}
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Name</th>
            <th>Mode</th>
            <th>Time</th>
            <th>Distance</th>
            <th>Avg / NP</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rides.map((r) => (
            <tr key={r.id}>
              <td>{new Date(r.started_at).toLocaleString()}</td>
              <td>{r.name}</td>
              <td>{r.mode}</td>
              <td>{fmtTime(r.duration_s)}</td>
              <td>{((r.distance_m ?? 0) / 1000).toFixed(2)} km</td>
              <td>
                {r.avg_power_w?.toFixed(0)} / {r.summary.normalized_power_w?.toFixed(0) ?? '—'} W
              </td>
              <td className="row-end">
                <a className="button ghost" href={`/api/rides/${r.id}/fit`}>
                  .fit
                </a>
                {r.intervals_activity_id ? (
                  <span className="muted">uploaded</span>
                ) : (
                  <button
                    onClick={() =>
                      api
                        .uploadRide(r.id)
                        .then(() => {
                          setMsg('Uploaded to intervals.icu')
                          reload()
                        })
                        .catch((e) => setMsg(e.message))
                    }
                  >
                    Upload
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rides.length === 0 && <p className="muted">No rides yet.</p>}
    </div>
  )
}
