import { useEffect, useState } from 'react'
import { profileChanged, type ProfileGuard } from '../profileDiff'
import { api, type BikePreset, type DeviceStatus, type Profile } from '../api'
import { DevicesCard, type DeviceRole } from '../components/DevicesCard'

type NumKey = Exclude<{ [K in keyof Profile]-?: Profile[K] extends number | null ? K : never }[keyof Profile], undefined>

type Setter = <K extends keyof Profile>(k: K, v: Profile[K]) => void

function Num({ p, k, label, step = 1, help, scale = 1, set }: { p: Profile; k: NumKey; label: string; step?: number; help?: string; scale?: number; set: Setter }) {
  const v = p[k] as number | null
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        step={step}
        defaultValue={v == null ? '' : +(v * scale).toFixed(6)}
        onChange={(e) => set(k, (e.target.value === '' ? null : Number(e.target.value) / scale) as Profile[typeof k])}
      />
      {help && <small>{help}</small>}
    </label>
  )
}

/** Speed (km/h) at a given power/grade, steady state, same equation as the backend (for preview). */
function steadySpeed(p: Profile, watts: number, grade: number) {
  const m = p.rider_mass_kg + p.bike_mass_kg
  const rho = 1.2
  const s = grade / Math.hypot(1, grade)
  const c = 1 / Math.hypot(1, grade)
  const f = (v: number) => (m * 9.80665 * (p.crr * c + s) + 0.5 * rho * p.cda_m2 * v * v) * v - p.drivetrain_efficiency * watts * (1 + p.speed_power_scale_pct / 100)
  let lo = 0
  let hi = 40
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2
    if (f(mid) < 0) lo = mid
    else hi = mid
  }
  return Math.min(lo * 3.6, p.max_speed_kmh)
}

export function ProfilePage({
  onSaved,
  devices,
  onGuard,
}: {
  onSaved: (p: Profile) => void
  devices?: Record<DeviceRole, DeviceStatus>
  /** told the unsaved state while the page is shown, null when it goes away (App asks
   * Save / Discard / Stay before leaving the tab) */
  onGuard?: (g: ProfileGuard | null) => void
}) {
  const [p, setP] = useState<Profile | null>(null)
  const [saved, setSaved] = useState<Profile | null>(null) // last loaded / saved
  const [msg, setMsg] = useState<string | null>(null)
  const [presets, setPresets] = useState<BikePreset[]>([])
  const set: Setter = (k, v) => setP((prev) => (prev ? { ...prev, [k]: v } : prev))
  useEffect(() => {
    api.getProfile().then((np) => {
      setP(np)
      setSaved(np)
    })
    api.bikePresets().then(setPresets).catch(() => {})
  }, [])
  const dirty = !!p && !!saved && profileChanged(p, saved)

  const save = (): Promise<boolean> =>
    p
      ? api
          .putProfile(p)
          .then((np) => {
            setP(np)
            setSaved(np)
            onSaved(np)
            setMsg(np.devices_note ? `Saved. ${np.devices_note}` : 'Saved')
            setTimeout(() => setMsg(null), np.devices_note ? 6000 : 2000)
            return true
          })
          .catch((e: Error) => {
            setMsg(e.message)
            return false
          })
      : Promise.resolve(true)

  // the app reads this before switching tabs; cleared when the page goes away
  useEffect(() => {
    onGuard?.({ dirty, save })
  })
  useEffect(() => () => onGuard?.(null), [onGuard])
  // closing or reloading the page with unsaved edits: the browser asks (its own wording)
  useEffect(() => {
    if (!dirty) return
    const ask = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', ask)
    return () => window.removeEventListener('beforeunload', ask)
  }, [dirty])

  if (!p) return <p className="muted">Loading…</p>

  const curve = p.grade_curve
  const setCurve = (c: [number, number][]) => set('grade_curve', c)
  const preset = presets.find((x) => x.id === p.bike_preset)
  // a preset brings its values (for the speed preview); custom starts from the current ones
  const choosePreset = (id: string) =>
    setP((prev) => {
      if (!prev) return prev
      const x = presets.find((y) => y.id === id)
      if (!x) return { ...prev, bike_preset: id }
      const { cda_m2, crr, drivetrain_efficiency, wheel_inertia_kg_m2, wheel_diameter_m } = x
      return { ...prev, bike_preset: id, cda_m2, crr, drivetrain_efficiency, wheel_inertia_kg_m2, wheel_diameter_m }
    })

  return (
    <div className="profile">
      <div className="card">
        <h3>Rider & bike</h3>
        <div className="fields">
          <Num set={set} p={p} k="rider_mass_kg" label="Rider weight (kg)" step={0.1} />
          <Num set={set} p={p} k="bike_mass_kg" label="Bike weight (kg)" step={0.1} />
          <Num set={set} p={p} k="ftp_w" label="FTP (W)" />
          <Num set={set} p={p} k="max_hr_bpm" label="Max HR (bpm)" />
          <Num set={set} p={p} k="threshold_hr_bpm" label="Threshold HR (bpm)" help="lactate threshold (LTHR): colours the heart rate by zone" />
        </div>
      </div>

      <div className="card">
        <h3>Speed model</h3>
        <p className="muted">
          η·P = m·g·v·(Crr·cosθ + sinθ) + ½·ρ·CdA·(v+v<sub>w</sub>)²·v + m<sub>eff</sub>·a·v, integrated in time (momentum carried across grade
          changes); m<sub>eff</sub> = m + I/r²; ρ from route altitude and the ride's air (set with the wind when starting a route; 15 °C / 50 % in ERG); P = measured power × (1 + power scale).
        </p>
        <div className="fields">
          <label className="field wide">
            <span>Bike & position</span>
            <select value={p.bike_preset} onChange={(e) => choosePreset(e.target.value)}>
              {presets.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
              <option value="custom">Custom (set the values)</option>
            </select>
            {preset && (
              <small>
                CdA {preset.cda_m2} m² · Crr {preset.crr} · drivetrain {preset.drivetrain_efficiency} · wheels {preset.wheel_inertia_kg_m2} kg·m², Ø{' '}
                {preset.wheel_diameter_m} m
              </small>
            )}
          </label>
        </div>
        {p.bike_preset === 'custom' && (
          <div className="fields">
            <Num set={set} p={p} k="cda_m2" label="CdA (m²)" step={0.005} help={'hoods ≈ 0.30–⁠0.40 · drops ≈ 0.27–⁠0.35 · TT ≈ 0.22–⁠0.32'} />
            <Num set={set} p={p} k="crr" label="Crr" step={0.0005} help={'good road tyres on real roads ≈ 0.004–⁠0.005'} />
            <Num set={set} p={p} k="drivetrain_efficiency" label="Drivetrain efficiency" step={0.001} help="clean chain ≈ 0.97–0.98" />
            <Num set={set} p={p} k="wheel_inertia_kg_m2" label="Wheel inertia, both (kg·m²)" step={0.01} />
            <Num set={set} p={p} k="wheel_diameter_m" label="Wheel diameter (m)" step={0.001} />
          </div>
        )}
        <details className="advanced">
          <summary>Advanced</summary>
          <div className="fields">
            <Num set={set} p={p} k="max_speed_kmh" label="Descent braking cap (km/h)" />
            <Num
              set={set}
              p={p}
              k="speed_power_scale_pct"
              label="Speed-model power scale (%)"
              help="speed only: trainer target & recorded power unchanged · applies from the next ride"
            />
          </div>
        </details>
        <div className="preview">
          {[
            [200, 0],
            [250, 0],
            [300, 0.05],
            [300, 0.08],
            [0, -0.06],
          ].map(([w, g]) => (
            <span key={`${w}${g}`}>
              {w} W @ {(g * 100).toFixed(0)}% → <b>{steadySpeed(p, w, g).toFixed(1)} km/h</b>
            </span>
          ))}
          <small className="muted">(steady state, sea level ρ = 1.2)</small>
        </div>
      </div>

      <DevicesCard p={p} set={set} devices={devices} />

      <div className="card">
        <h3>Power source</h3>
        <div className="fields">
          <label className="field">
            <span>Power used for speed & recording</span>
            <select
              defaultValue={p.power_source}
              onChange={(e) => set('power_source', e.target.value as Profile['power_source'])}
            >
              <option value="auto">Auto: power meter if detected, else trainer</option>
              <option value="power_meter">Power meter only</option>
              <option value="trainer">Trainer only</option>
            </select>
          </label>
          <label className="field check">
            <input
              type="checkbox"
              defaultChecked={p.power_match}
              onChange={(e) => set('power_match', e.target.checked)}
            />
            <span>Power match: correct the ERG target so the power meter reads the requested power</span>
          </label>
        </div>
      </div>

      <div className="card">
        <h3>Slope ERG — grade → target power</h3>
        <p className="muted">Target = FTP × f(look-ahead grade) × effort, clamped and rate-limited (piecewise linear, flat beyond the end points).</p>
        <table className="curve">
          <thead>
            <tr>
              <th>Grade %</th>
              <th>% FTP</th>
              <th>W</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {curve.map(([g, f], i) => (
              <tr key={i}>
                <td>
                  <input type="number" step={0.5} value={g} onChange={(e) => setCurve(curve.map((c, j) => (j === i ? [Number(e.target.value), c[1]] : c)))} />
                </td>
                <td>
                  <input type="number" step={1} value={Math.round(f * 100)} onChange={(e) => setCurve(curve.map((c, j) => (j === i ? [c[0], Number(e.target.value) / 100] : c)))} />
                </td>
                <td className="muted">{Math.round(f * p.ftp_w)}</td>
                <td>
                  <button className="ghost" disabled={curve.length <= 2} onClick={() => setCurve(curve.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="ghost" onClick={() => setCurve([...curve, [(curve[curve.length - 1]?.[0] ?? 0) + 2, curve[curve.length - 1]?.[1] ?? 0.7]])}>
          + point
        </button>
        <div className="fields">
          <Num set={set} p={p} k="grade_curve_min_frac" label="Floor (% FTP)" scale={100} />
          <Num set={set} p={p} k="grade_curve_max_frac" label="Ceiling (% FTP)" scale={100} />
          <Num set={set} p={p} k="grade_lookahead_m" label="Grade look-ahead (m)" />
          <Num set={set} p={p} k="target_ramp_w_per_s" label="Max target change (W/s)" />
        </div>
      </div>

      <div className="card">
        <h3>intervals.icu</h3>
        <div className="fields">
          <label className="field">
            <span>Athlete ID</span>
            <input defaultValue={p.intervals_athlete_id} onChange={(e) => set('intervals_athlete_id', e.target.value)} />
            <small>e.g. i12345 — "0" = owner of the API key</small>
          </label>
          <label className="field">
            <span>API key {p.intervals_api_key_set && <em className="muted">(stored — leave blank to keep)</em>}</span>
            <input type="password" placeholder="Settings → Developer settings" onChange={(e) => set('intervals_api_key', e.target.value)} />
          </label>
        </div>
      </div>

      <div className="toolbar sticky">
        <button className={`primary ${dirty ? 'unsaved' : ''}`} onClick={() => void save()}>
          Save profile
        </button>
        {dirty && <span className="unsaved-note">Unsaved changes</span>}
        {msg && <span className="hint">{msg}</span>}
      </div>
    </div>
  )
}
