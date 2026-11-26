import { useCallback, useEffect, useState } from 'react'
import { WindPicker } from '../components/Wind'
import { NumberInput } from '../components/NumberInput'
import { feedbackText } from '../feedback'
import { loadAir, loadWind, saveAir, saveWind, type WindSetting } from '../wind'
import { api, fmtTime, type PlannedWorkout, type Profile, type Ride, type RideAir, type RouteDetail, type RouteEstimate, type RouteSummary, type Workout } from '../api'
import { ElevationProfile, WorkoutProfile } from '../components/charts'
import { RouteMap } from '../components/RouteMap'
import { DropOverlay } from '../components/DropOverlay'
import { useFileDrop } from '../useFileDrop'
import { clampStart, indexAt, nearestIndex, startFromProfile } from '../routeStart'

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

/** A distance in km, typed freely and applied on Enter or when leaving the field (remounted
 * with a new `key` when the value changes from elsewhere, e.g. a click on the map). */
function KmField({ m, onChange }: { m: number; onChange: (km: number) => void }) {
  const [text, setText] = useState((m / 1000).toFixed(1))
  const apply = () => {
    const km = Number(text.replace(',', '.'))
    if (Number.isFinite(km)) onChange(km)
    else setText((m / 1000).toFixed(1))
  }
  return (
    <input
      type="text"
      inputMode="decimal"
      className="km-field"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={apply}
      onKeyDown={(e) => e.key === 'Enter' && apply()}
    />
  )
}

const WORKOUT_EXTS = ['.zwo', '.erg', '.mrc']

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

  // workout files dropped anywhere on the tab: imported one after the other, like the button
  const [dropNote, setDropNote] = useState<string | null>(null)
  const dragging = useFileDrop(WORKOUT_EXTS, async (files, refused) => {
    setError(null)
    const problems = refused.map((n) => `${n}: not a .zwo / .erg / .mrc file`)
    let imported = 0
    for (const [i, f] of files.entries()) {
      setDropNote(`Importing ${f.name}${files.length > 1 ? ` (${i + 1}/${files.length})` : ''}…`)
      try {
        await api.importWorkout(f)
        imported += 1
      } catch (e) {
        problems.push(`${f.name}: ${(e as Error).message}`)
      }
    }
    setDropNote(null)
    if (imported) reload()
    if (problems.length) setError(problems.join(' · '))
  })

  return (
    <div>
      {dragging && <DropOverlay text="Drop .zwo / .erg / .mrc files to import them" />}
      {dropNote && <div className="hint">{dropNote}</div>}
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
export function RoutesPage({
  canStart,
  onStart,
}: {
  canStart: boolean
  onStart: (r: RouteDetail, w: Workout | undefined, wind: WindSetting, air: RideAir, startM: number) => void
}) {
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
  // conditions of the ride: wind and air (temperature, humidity), remembered per browser;
  // "Weather now" fills them in
  const [air, setAir] = useState<RideAir>(loadAir)
  const [weather, setWeather] = useState<{ busy: boolean; note?: string }>({ busy: false })
  const fetchWeather = (id: number) => {
    setWeather({ busy: true })
    api
      .routeWeather(id)
      .then((w) => {
        setWind({ kmh: Math.round(w.wind_kmh), fromDeg: w.wind_from_deg })
        setAir({ temperature_c: w.temperature_c, relative_humidity: w.relative_humidity })
        setWeather({
          busy: false,
          note: `Now, average of ${w.points} points: ${Math.round(w.wind_10m_kmh)} km/h at 10 m → ${Math.round(w.wind_kmh)} km/h at rider height`,
        })
      })
      .catch((e: Error) => setWeather({ busy: false, note: `Weather unavailable: ${e.message}` }))
  }
  // start part-way (m along the route, in the direction ridden): a click on the map or the
  // profile, or the km field; back to 0 for another route or direction
  const [startM, setStartM] = useState(0)
  const open = (id: number, rev = reverse) =>
    api
      .route(id, rev)
      .then((r) => {
        setSel(r)
        setStartM(0)
      })
      .catch((e) => setError(e.message))
  // estimated time (or, with a workout, distance) for the options chosen; the key says which
  // options an estimate is for, so a stale one is never shown
  const [est, setEst] = useState<{ key: string; value: RouteEstimate } | null>(null)
  const estKey = sel ? JSON.stringify([sel.id, !!sel.reversed, wind.kmh, wind.fromDeg, workoutId, air, startM]) : ''
  useEffect(() => {
    if (!sel) return
    let cancelled = false
    api
      .routeEstimate(sel.id, { reverse: !!sel.reversed, windKmh: wind.kmh, windFromDeg: wind.fromDeg, workoutId, air, startM })
      .then((value) => !cancelled && setEst({ key: estKey, value }))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sel, wind.kmh, wind.fromDeg, workoutId, air, startM, estKey])
  const estimate = est && est.key === estKey ? est.value : null

  // .gpx files dropped anywhere on the tab: imported one after the other like "Import GPX",
  // the last one opened
  const [dropNote, setDropNote] = useState<string | null>(null)
  const dragging = useFileDrop(['.gpx'], async (files, refused) => {
    setError(null)
    const problems = refused.map((n) => `${n}: not a .gpx file`)
    let last: RouteSummary | null = null
    for (const [i, f] of files.entries()) {
      setDropNote(`Importing ${f.name}${files.length > 1 ? ` (${i + 1}/${files.length})` : ''}…`)
      try {
        last = await api.importRoute(f)
      } catch (e) {
        problems.push(`${f.name}: ${(e as Error).message}`)
      }
    }
    setDropNote(null)
    if (last) {
      reload()
      open(last.id)
    }
    if (problems.length) setError(problems.join(' · '))
  })

  return (
    <div>
      {dragging && <DropOverlay text="Drop .gpx files to import them" />}
      {dropNote && <div className="hint">{dropNote}</div>}
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
                <span className="nw">{(sel.distance_m / 1000).toFixed(2)} km</span> ·{' '}
                <span className="nw">
                  +{sel.ascent_m.toFixed(0)} / −{sel.descent_m.toFixed(0)} m
                </span>{' '}
                ·{' '}
                <span className="nw">
                  {sel.min_altitude_m.toFixed(0)}–{sel.max_altitude_m.toFixed(0)} m
                </span>
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
            <RouteMap
              latlon={sel.latlon}
              height={300}
              start={startM > 0 ? indexAt(sel.profile_distance_m, startM) : undefined}
              onPick={(at) => setStartM(clampStart(sel.profile_distance_m[nearestIndex(sel.latlon, at)], sel.distance_m))}
            />
            <ElevationProfile
              distance={sel.profile_distance_m}
              altitude={sel.altitude_m}
              grade={sel.grade}
              height={120}
              start={startM}
              onPick={(f) => setStartM(startFromProfile(f, sel.distance_m))}
            />
            <div className="start-pick">
              <span className="muted" title="Click the map or the profile to start part-way; the ride ends at the route's end">
                Start at km
              </span>
              <KmField key={startM} m={startM} onChange={(km) => setStartM(clampStart(km * 1000, sel.distance_m))} />
              {startM > 0 ? (
                <button className="ghost" onClick={() => setStartM(0)}>
                  From the start
                </button>
              ) : (
                <span className="muted">click the map or the profile to start part-way</span>
              )}
            </div>
            <div className="row-end route-actions">
              <button
                className="ghost"
                onClick={() =>
                  confirm(`Delete ${sel.name}?`) &&
                  api
                    .deleteRoute(sel.id)
                    .then(() => {
                      setSel(null)
                      reload()
                    })
                    .catch((e: Error) => setError(e.message))
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
              <span className="air-pick" title="Air of the ride: temperature and humidity set its density (aerodynamic drag). Remembered for the next ride.">
                <span className="muted">Air</span>
                <NumberInput
                  step={0.5}
                  min={-30}
                  max={50}
                  value={air.temperature_c}
                  onChange={(t) => setAir({ ...air, temperature_c: Math.max(-30, Math.min(50, t)) })}
                />
                <span className="muted">°C</span>
                <input
                  type="number"
                  step={5}
                  min={0}
                  max={100}
                  value={Math.round(air.relative_humidity * 100)}
                  onChange={(e) => setAir({ ...air, relative_humidity: Math.max(0, Math.min(100, Number(e.target.value) || 0)) / 100 })}
                />
                <span className="muted">%</span>
              </span>
              <button
                className="ghost"
                disabled={weather.busy}
                title="Current wind, temperature and humidity along the route (Open-Meteo, averaged over points every ~10 km), the wind brought down to rider height. Editable before starting."
                onClick={() => fetchWeather(sel.id)}
              >
                {weather.busy ? 'Weather…' : 'Weather now'}
              </button>
              <button
                className="primary"
                disabled={!canStart}
                title={canStart ? '' : 'Connect sensors first'}
                onClick={() => {
                  saveWind(wind)
                  saveAir(air)
                  onStart(sel, chosenWorkout, wind, air, startM)
                }}
              >
                {chosenWorkout ? 'Ride with workout' : 'Ride this route'}
              </button>
            </div>
            {weather.note && <p className="muted weather-note">{weather.note}</p>}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------
export function HistoryPage({ canUpload }: { canUpload: boolean }) {
  const [rides, setRides] = useState<Ride[]>([])
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null)
  const fail = (e: Error) => setMsg({ text: e.message, error: true })
  const reload = useCallback(
    () =>
      api
        .rides()
        .then(setRides)
        .catch((e: Error) => setMsg({ text: `Cannot load the rides: ${e.message}`, error: true })),
    [],
  )
  useEffect(() => {
    reload()
  }, [reload])
  return (
    <div className="card">
      {msg && <div className={msg.error ? 'error' : 'hint ok'}>{msg.text}</div>}
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Name</th>
            <th>Mode</th>
            <th>Time</th>
            <th>Distance</th>
            <th>Avg / NP</th>
            <th title="Answers to &quot;How was it?&quot;: perceived effort (RPE), feel, carbohydrates, water">Feel</th>
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
              <td className={feedbackText(r.summary) ? '' : 'muted'}>{feedbackText(r.summary) ?? '—'}</td>
              <td>
                {/* flex inside the cell, not on it: a flex td leaves the table layout and
                    loses the row border */}
                <div className="row-end">
                  <a className="button ghost" href={`/api/rides/${r.id}/fit`}>
                    .fit
                  </a>
                  {r.intervals_activity_id ? (
                    <span className="muted">uploaded</span>
                  ) : (
                    <button
                      disabled={!canUpload}
                      title={canUpload ? 'Send the FIT file to intervals.icu' : 'Set the intervals.icu API key in Profile first'}
                      onClick={() =>
                        api
                          .uploadRide(r.id)
                          .then(() => {
                            setMsg({ text: 'Uploaded to intervals.icu' })
                            reload()
                          })
                          .catch(fail)
                      }
                    >
                      Upload
                    </button>
                  )}
                  <button
                    className="ghost"
                    onClick={() => {
                      const kept = r.intervals_activity_id ? '\n\nIts copy on intervals.icu is not deleted (delete it there if needed).' : ''
                      if (confirm(`Delete the ride "${r.name}" (history and FIT file)?${kept}`))
                        api
                          .deleteRide(r.id)
                          .then(reload)
                          .catch(fail)
                    }}
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rides.length === 0 && <p className="muted">No rides yet.</p>}
    </div>
  )
}
