// Typed client for the Python backend.

export type PowerSource = 'auto' | 'trainer' | 'power_meter'

export interface Profile {
  rider_mass_kg: number
  bike_mass_kg: number
  ftp_w: number
  max_hr_bpm: number | null
  cda_m2: number
  crr: number
  drivetrain_efficiency: number
  wheel_inertia_kg_m2: number
  wheel_diameter_m: number
  max_speed_kmh: number
  temperature_c: number
  relative_humidity: number
  power_source: PowerSource
  power_match: boolean
  trainer_device_number: number | null
  power_meter_device_number: number | null
  heart_rate_device_number: number | null
  trainer_transport: Transport
  power_meter_transport: Transport
  heart_rate_transport: Transport
  trainer_ble_id: string | null
  power_meter_ble_id: string | null
  heart_rate_ble_id: string | null
  trainer_ble_name: string | null
  power_meter_ble_name: string | null
  heart_rate_ble_name: string | null
  grade_curve: [number, number][]
  grade_curve_min_frac: number
  grade_curve_max_frac: number
  grade_lookahead_m: number
  target_ramp_w_per_s: number
  intervals_athlete_id: string
  intervals_api_key: string
  intervals_api_key_set?: boolean
  devices_note?: string
}

export interface Step {
  duration_s: number
  start: number | null
  end: number | null
  unit: 'ftp' | 'watts'
  cadence_rpm: number | null
  label: string
}

export interface Workout {
  id: number
  name: string
  description: string
  source: string
  duration_s: number
  steps: Step[]
}

export interface RouteSummary {
  id: number
  name: string
  distance_m: number
  ascent_m: number
  descent_m: number
  max_grade: number
  min_grade: number
  min_altitude_m: number
  max_altitude_m: number
}

export interface RouteDetail extends RouteSummary {
  latlon: [number, number][]
  profile_distance_m: number[]
  altitude_m: number[]
  grade: number[]
}

export interface PlannedWorkout {
  id: number
  name: string
  date: string
  type: string
  moving_time_s: number | null
  load: number | null
  description: string
}

export interface Ride {
  id: number
  started_at: string
  mode: string
  name: string
  duration_s: number
  distance_m: number
  avg_power_w: number | null
  intervals_activity_id: string | null
  summary: Record<string, number | null>
}

export type Transport = 'ant' | 'ble'

export interface DeviceStatus {
  connected: boolean
  transport: Transport | 'sim' | null
  device_number: number | null
  ble_id: string | null
  name: string | null
  wanted: number | string | null
}

export interface ScanDevice {
  transport: Transport
  roles: string[]
  // ANT+
  device_number?: number
  device_type?: number
  label?: string
  note?: string | null
  messages?: number
  // BLE
  ble_id?: string
  name?: string
  rssi?: number
}

export interface ScanResult {
  ant: ScanDevice[]
  ble: ScanDevice[]
  errors: Record<string, string>
}

export interface SimSettings {
  mode: 'follow' | 'manual'
  manual_power_w: number
  cadence_rpm: number
  pedaling: boolean
  noise: boolean
  power_meter: boolean
  heart_rate: boolean
  pm_bias: number
}

export interface Telemetry {
  session_id?: string
  workout_id?: number | null
  route_id?: number | null
  state: 'disconnected' | 'idle' | 'ready' | 'running' | 'paused' | 'finished'
  hub?: string | null
  devices?: Record<'trainer' | 'power_meter' | 'heart_rate', DeviceStatus>
  mode?: 'erg' | 'gpx'
  name?: string
  elapsed_s?: number
  power_w?: number | null
  power_source?: string
  /** instantaneous power_w / rider mass; next to a 3 s power, use wkg() on that value */
  power_wkg?: number | null
  rider_mass_kg?: number
  avg_speed_kmh?: number | null
  avg_power_w?: number | null
  np_w?: number | null
  target_wkg?: number | null
  route_position_m?: number
  lap?: number
  vam_mh?: number | null
  vam_instant_mh?: number
  elevation_gain_m?: number
  elevation_left_m?: number
  cadence_source?: string
  trainer_power_w?: number | null
  pm_power_w?: number | null
  cadence_rpm?: number | null
  heart_rate_bpm?: number | null
  target_w?: number | null
  sent_target_w?: number | null
  power_match_offset_w?: number
  speed_kmh?: number
  distance_m?: number
  grade?: number
  altitude_m?: number
  air_density?: number
  power_split_w?: { gravity: number; rolling: number; aero: number }
  intensity_pct?: number
  effort_pct?: number
  difficulty_pct?: number
  target_mode?: 'slope' | 'manual'
  manual_target_w?: number | null
  lat?: number
  lon?: number
  heading_deg?: number
  /** GPX: wind set for the ride (blowing FROM wind_from_deg) and its components on the heading */
  wind_kmh?: number
  wind_from_deg?: number
  headwind_kmh?: number // negative = tailwind
  crosswind_kmh?: number // positive = from the right
  route_distance_m?: number
  step_index?: number
  step_remaining_s?: number
  workout_duration_s?: number
  next_target_w?: number | null
  step_avg_power_w?: number | null
  /** bumped when the rider skips / extends a step: reload /api/session/workout */
  workout_rev?: number
  saved?: { ride_id: number } | null
  sim?: SimSettings
  /** client-side: 3 s moving average of power_w */
  power_avg3_w?: number | null
}

/** W/kg of a displayed power (rider mass only, as on the server), formatted, or '—'. */
export function wkg(watts: number | null | undefined, massKg: number | undefined): string {
  if (watts == null || !massKg || massKg <= 0) return '—'
  return (watts / massKg).toFixed(2)
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const r = await fetch(url, init)
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* not JSON */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

const upload = <T,>(url: string, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return req<T>('POST', url, fd)
}

export const api = {
  getProfile: () => req<Profile>('GET', '/api/profile'),
  putProfile: (p: Partial<Profile>) => req<Profile>('PUT', '/api/profile', p),

  connect: (kind: 'devices' | 'simulator') => req<{ hub: string; warnings?: string[] }>('POST', '/api/devices/connect', { kind }),
  scan: (seconds = 6) => req<ScanResult>('POST', `/api/devices/scan?seconds=${seconds}`),
  disconnect: () => req('POST', '/api/devices/disconnect'),

  workouts: () => req<Workout[]>('GET', '/api/workouts'),
  importWorkout: (f: File) => upload<Workout>('/api/workouts/import', f),
  deleteWorkout: (id: number) => req('DELETE', `/api/workouts/${id}`),
  planned: () => req<PlannedWorkout[]>('GET', '/api/intervals/planned'),
  importPlanned: (id: number) => req<Workout>('POST', `/api/intervals/import/${id}`),

  routes: () => req<RouteSummary[]>('GET', '/api/routes'),
  route: (id: number) => req<RouteDetail>('GET', `/api/routes/${id}`),
  importRoute: (f: File) => upload<RouteSummary>('/api/routes/import', f),
  deleteRoute: (id: number) => req('DELETE', `/api/routes/${id}`),

  start: (body: { mode: 'erg' | 'gpx'; workout_id?: number; route_id?: number; wind_kmh?: number; wind_from_deg?: number }) =>
    req<{ ok: boolean; name: string; session_id: string }>('POST', '/api/session/start', body),
  workout: (id: number) => req<Workout>('GET', `/api/workouts/${id}`),
  pause: () => req('POST', '/api/session/pause'),
  resume: () => req('POST', '/api/session/resume'),
  stop: (save = true) => req<{ saved: { ride_id: number } | null }>('POST', `/api/session/stop?save=${save}`),
  adjust: (a: {
    intensity_pct?: number
    effort_pct?: number
    difficulty_pct?: number
    target_mode?: 'slope' | 'manual'
    manual_target_w?: number
  }) =>
    req('POST', '/api/session/adjust', a),
  /** the ride's workout as edited by the rider (skipped / extended steps) */
  sessionWorkout: () => req<Workout & { workout_rev: number }>('GET', '/api/session/workout'),
  skipStep: () => req<Workout & { workout_rev: number }>('POST', '/api/session/step', { action: 'skip' }),
  extendStep: (seconds: number) => req<Workout & { workout_rev: number }>('POST', '/api/session/step', { action: 'extend', seconds }),

  setSim: (s: Partial<SimSettings>) => req<SimSettings>('PUT', '/api/simulator', s),

  rides: () => req<Ride[]>('GET', '/api/rides'),
  /** idempotent: a ride already on intervals.icu is not sent again (already = true) */
  uploadRide: (id: number) => req<{ intervals_activity_id: string; already?: boolean }>('POST', `/api/rides/${id}/upload`),
}

export const fmtTime = (s: number | undefined | null) => {
  if (s == null || !isFinite(s)) return '--:--'
  s = Math.max(0, Math.round(s))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(h ? 2 : 1, '0')
  return (h ? `${h}:` : '') + `${mm}:${String(sec).padStart(2, '0')}`
}

export const stepWatts = (s: Step, ftp: number, t: number) => {
  if (s.start == null) return null
  const end = s.end ?? s.start
  const v = s.start + (end - s.start) * Math.min(Math.max(t / s.duration_s, 0), 1)
  return s.unit === 'ftp' ? v * ftp : v
}
