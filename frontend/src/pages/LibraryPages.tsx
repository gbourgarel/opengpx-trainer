import { useCallback, useEffect, useState } from 'react'
import { api, fmtTime, type PlannedWorkout, type Profile, type Ride, type RouteDetail, type RouteSummary, type Workout } from '../api'
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
export function RoutesPage({ canStart, onStart }: { canStart: boolean; onStart: (r: RouteDetail) => void }) {
  const [list, setList] = useState<RouteSummary[]>([])
  const [sel, setSel] = useState<RouteDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => api.routes().then(setList).catch((e) => setError(e.message)), [])
  useEffect(() => {
    reload()
  }, [reload])
  const open = (id: number) => api.route(id).then(setSel).catch((e) => setError(e.message))

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
              <button className="primary" disabled={!canStart} title={canStart ? '' : 'Connect sensors first'} onClick={() => onStart(sel)}>
                Ride this route
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
