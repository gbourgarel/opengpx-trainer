import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapTilesContext } from './mapTilesContext'
import { setFallbackImagery } from './scenery/tiles'
import { api, type DeviceStatus, type Profile, type RideAir, type RouteDetail, type Workout } from './api'
import { HistoryPage, RoutesPage, WorkoutsPage } from './pages/LibraryPages'
import { ProfilePage } from './pages/ProfilePage'
import type { ProfileGuard } from './profileDiff'
import { loadAsked, rememberAsked } from './feedbackAsked'
import { lostSensorText } from './sensorAlert'
import { SimulatorPanel } from './components/SimulatorPanel'
import { FeedbackDialog } from './components/FeedbackDialog'
import { UploadPrompt } from './components/UploadPrompt'
import type { WindSetting } from './wind'
import { RidePage, type ActiveRide } from './pages/RidePage'
import { useLive } from './useLive'
import { useWakeLock } from './wakeLock'
import { useEscape } from './useEscape'

type Tab = 'ride' | 'workouts' | 'routes' | 'history' | 'profile'
const TABS: [Tab, string][] = [
  ['ride', 'Ride'],
  ['workouts', 'Workouts (ERG)'],
  ['routes', 'Routes (GPX)'],
  ['history', 'History'],
  ['profile', 'Profile'],
]

function Dot({ status, label }: { status?: DeviceStatus; label: string }) {
  const on = status?.connected
  const ble = status?.transport === 'ble'
  // what identifies the device: ANT+ number, or the Bluetooth name
  const ident = ble ? (status?.name ?? (typeof status?.wanted === 'string' ? status.wanted.slice(0, 8) : null)) : on ? status?.device_number : status?.wanted
  const proto = ble ? 'Bluetooth' : status?.transport === 'sim' ? 'simulator' : 'ANT+'
  const title = on
    ? `${label}: ${proto} ${ident ?? ''}${status?.wanted ? ' (configured)' : ' (first found)'}`
    : status?.wanted
      ? `${label}: searching for ${proto} ${ident ?? status.wanted}`
      : `${label}: searching (first found)`
  return (
    <span className={`dev ${on ? 'on' : ''}`} title={title}>
      <i />
      {label}
      {ident != null && (
        <small className="dev-num">
          {ble && 'ᛒ '}
          {ident}
        </small>
      )}
    </span>
  )
}

export default function App() {
  const { tel, connected } = useLive()
  const [tab, setTab] = useState<Tab>('ride')
  // leaving the Profile tab with unsaved edits: ask Save / Discard / Stay first
  const profileGuard = useRef<ProfileGuard | null>(null)
  const setProfileGuard = useCallback((g: ProfileGuard | null) => {
    profileGuard.current = g
  }, [])
  const [leaveTo, setLeaveTo] = useState<Tab | null>(null)
  const [leaveBusy, setLeaveBusy] = useState(false)
  useEscape(leaveTo && !leaveBusy ? () => setLeaveTo(null) : null) // Stay
  const goTab = (k: Tab) => {
    if (tab === 'profile' && k !== 'profile' && profileGuard.current?.dirty) setLeaveTo(k)
    else setTab(k)
  }
  const leave = (k: Tab) => {
    setLeaveTo(null)
    setTab(k)
  }
  const saveAndLeave = (k: Tab) => {
    const g = profileGuard.current
    if (!g) return leave(k)
    setLeaveBusy(true)
    g.save()
      .then((ok) => (ok ? leave(k) : setLeaveTo(null))) // failed: stay, the error is shown
      .finally(() => setLeaveBusy(false))
  }
  const [profile, setProfile] = useState<Profile | null>(null)
  const [active, setActive] = useState<ActiveRide | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

  useEffect(() => {
    api.getProfile().then(setProfile).catch(() => {})
  }, [])

  const hub = tel.hub
  const dev = tel.devices
  // keep the screen on during a ride, whatever the tab shown
  const riding = ['ready', 'running', 'paused'].includes(tel.state)
  const wake = useWakeLock(riding)
  // a sensor that sent data during the ride went silent (> 5 s): banner until it comes back
  const lostSensors = riding ? (tel.lost_sensors ?? []) : []

  // Once a ride is saved (it finished on its own, telemetry, or "Stop & save"): ask "How was
  // it?" (RPE / feel, written into the FIT file), then offer (never force) the upload to
  // intervals.icu when a key is set. Asked once per ride in this browser, even across a page
  // reload while the finished ride is still open.
  type Ask = { rideId: number; name?: string }
  const [asked, setAsked] = useState(loadAsked) // answered or skipped, in this browser
  const [endedAsk, setEndedAsk] = useState<Ask | null>(null) // ride just stopped here
  const [uploadAsk, setUploadAsk] = useState<Ask | null>(null)
  const canUpload = !!profile?.intervals_api_key_set
  const tileUrl = profile?.map_tile_url ?? ''
  const tileCredit = profile?.map_tile_attribution ?? ''
  const tiles = useMemo(() => ({ url: tileUrl, attribution: tileCredit }), [tileUrl, tileCredit])
  const imageryUrl = profile?.imagery_tile_url ?? ''
  const imageryCredit = profile?.imagery_tile_attribution ?? ''
  useEffect(() => setFallbackImagery(imageryUrl, imageryCredit), [imageryUrl, imageryCredit])
  const offerUpload = (rideId: number, name?: string) => {
    if (!asked.includes(rideId)) setEndedAsk({ rideId, name })
  }
  // a ride that finished on its own (telemetry), else one stopped here
  const savedRideId = tel.saved?.ride_id
  const feedbackAsk: Ask | null =
    savedRideId != null && !asked.includes(savedRideId) ? { rideId: savedRideId, name: tel.name } : endedAsk && !asked.includes(endedAsk.rideId) ? endedAsk : null
  const feedbackDone = () => {
    if (!feedbackAsk) return
    if (canUpload) setUploadAsk(feedbackAsk)
    setAsked(rememberAsked(feedbackAsk.rideId))
    setEndedAsk(null)
  }

  const connect = (kind: 'devices' | 'simulator') => {
    if (connecting) return
    setError(null)
    setConnecting(true)
    api
      .connect(kind)
      .then((res) => res.warnings?.length && setError(res.warnings.join(' · ')))
      .catch((e) => setError(e.message))
      .finally(() => setConnecting(false))
  }

  // Rebuild the ride view from the server's session when this client doesn't know it
  // (page reload, second browser/tablet, or a ride started elsewhere).
  const sessionId = tel.session_id
  const { mode, workout_id: workoutId, route_id: routeId } = tel
  const routeReversed = !!tel.route_reversed
  // Until it is rebuilt, the Ride tab shows the ride's head from the telemetry alone (Pause /
  // Stop always reachable), with this error and a Retry if the rebuild failed.
  const [restoreError, setRestoreError] = useState<{ sessionId: string; message: string } | null>(null)
  const [restoreTry, setRestoreTry] = useState(0)
  useEffect(() => {
    if (!sessionId || !mode || active?.sessionId === sessionId) return
    let cancelled = false
    // the session's own copy of the workout (as edited during the ride, and still there if
    // the library's copy is gone); GPX: the route, plus the workout in mixed mode
    const workout = () =>
      api.sessionWorkout().then(({ workout_rev, ...w }) => ({ workout: w as Workout, workoutRev: workout_rev }))
    const load =
      mode === 'erg' && workoutId != null
        ? workout().then((w) => ({ sessionId, mode, ...w }) as ActiveRide)
        : mode === 'gpx' && routeId != null
          ? Promise.all([api.route(routeId, routeReversed), workoutId != null ? workout() : Promise.resolve(undefined)]).then(
              ([route, w]) => ({ sessionId, mode, route, ...w }) as ActiveRide,
            )
          : null
    load
      ?.then((a) => {
        if (!cancelled) setActive(a)
      })
      .catch((e: Error) => !cancelled && setRestoreError({ sessionId, message: `Cannot restore the ride view: ${e.message}` }))
    return () => {
      cancelled = true
    }
  }, [sessionId, mode, workoutId, routeId, routeReversed, active?.sessionId, restoreTry])

  // The rider skipped / extended a step (here or on another device): reload the session's
  // copy of the workout so the profile, the total time and the step list follow.
  const workoutRev = tel.workout_rev ?? 0
  const activeId = active?.sessionId
  const activeRev = active?.workoutRev ?? 0
  useEffect(() => {
    if (!activeId || activeId !== sessionId || workoutRev === activeRev) return
    let cancelled = false
    api
      .sessionWorkout()
      .then(({ workout_rev, ...workout }) => {
        if (cancelled) return
        setActive((a) => (a && a.sessionId === activeId ? { ...a, workout, workoutRev: workout_rev } : a))
      })
      .catch((e: Error) => !cancelled && setError(`Cannot reload the edited workout: ${e.message}`))
    return () => {
      cancelled = true
    }
  }, [activeId, sessionId, workoutRev, activeRev])

  const startWorkout =(w: Workout) =>
    api
      .start({ mode: 'erg', workout_id: w.id })
      .then((res) => {
        setActive({ sessionId: res.session_id, mode: 'erg', workout: w })
        setTab('ride')
      })
      .catch((e) => setError(e.message))

  const startRoute = (r: RouteDetail, w: Workout | undefined, wind: WindSetting, air: RideAir, startM: number) =>
    api
      .start({
        mode: 'gpx',
        route_id: r.id,
        reverse: !!r.reversed,
        workout_id: w?.id,
        wind_kmh: wind.kmh,
        wind_from_deg: wind.fromDeg,
        ...air, // the ride's air (conditions chosen with the wind)
        start_m: startM,
      })
      .then((res) => {
        setActive({ sessionId: res.session_id, mode: 'gpx', route: r, workout: w })
        setTab('ride')
      })
      .catch((e) => setError(e.message))

  return (
    <div className="app">
      <header>
        <h1>OpenGPX Trainer</h1>
        <nav>
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? 'active' : ''} onClick={() => goTab(k)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="devices">
          {!connected && <span className="error-inline">backend offline</span>}
          {hub ? (
            <>
              <Dot status={dev?.trainer} label="Trainer" />
              <Dot status={dev?.power_meter} label="Power" />
              <Dot status={dev?.heart_rate} label="HR" />
              <span className="muted">{hub === 'simulator' ? 'simulator' : 'sensors'}</span>
              <button
                className="ghost"
                disabled={riding}
                title={riding ? 'Stop the ride first (the sensors drive and record it)' : undefined}
                onClick={() => api.disconnect().catch((e: Error) => setError(e.message))}
              >
                Disconnect
              </button>
            </>
          ) : (
            <>
              <button className="primary" disabled={connecting} onClick={() => connect('devices')} title="Connect the sensors chosen in Profile → Devices (ANT+ and/or Bluetooth)">
                {connecting ? 'Connecting…' : 'Connect sensors'}
              </button>
              {tel.simulator_offered && (
                <button className="ghost" disabled={connecting} onClick={() => connect('simulator')}>
                  Simulator
                </button>
              )}
            </>
          )}
        </div>
      </header>
      {error && (
        <div className="error banner" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      {lostSensors.length > 0 && (
        <div className="sensor-alert" role="alert">
          {lostSensors.map((s) => (
            <div key={s.role}>⚠ {lostSensorText(s.role, s.since, tel.power_source)}</div>
          ))}
        </div>
      )}
      <MapTilesContext value={tiles}>
      <main className={tab === 'ride' ? 'ride-main' : ''}>
        {tab === 'ride' && tel.sim && <SimulatorPanel key={tel.hub ?? ''} initial={tel.sim} />}
        {feedbackAsk && <FeedbackDialog key={feedbackAsk.rideId} rideId={feedbackAsk.rideId} name={feedbackAsk.name} onDone={feedbackDone} />}
        {uploadAsk && <UploadPrompt key={uploadAsk.rideId} rideId={uploadAsk.rideId} name={uploadAsk.name} onClose={() => setUploadAsk(null)} />}
        {tab === 'ride' && (
          <RidePage
            tel={tel}
            active={active}
            profile={profile}
            wake={wake}
            restoreError={restoreError && restoreError.sessionId === sessionId ? restoreError.message : null}
            onRetryRestore={() => {
              setRestoreError(null)
              setRestoreTry((n) => n + 1)
            }}
            onEnd={(rideId) => {
              setActive(null)
              if (rideId != null) offerUpload(rideId, tel.name)
            }}
          />
        )}
        {tab === 'workouts' && <WorkoutsPage profile={profile} canStart={!!hub} onStart={startWorkout} />}
        {tab === 'routes' && <RoutesPage canStart={!!hub} onStart={startRoute} />}
        {tab === 'history' && <HistoryPage canUpload={canUpload} />}
        {tab === 'profile' && <ProfilePage onSaved={setProfile} devices={dev} onGuard={setProfileGuard} />}
        {leaveTo && (
          <div className="dialog-backdrop">
            <div className="dialog" role="dialog" aria-label="Unsaved profile changes">
              <h3>Unsaved profile changes</h3>
              <p className="muted">They are not used until they are saved (FTP, weight, bike, devices…).</p>
              <div className="dialog-actions">
                <button disabled={leaveBusy} onClick={() => setLeaveTo(null)}>
                  Stay
                </button>
                <button disabled={leaveBusy} onClick={() => leave(leaveTo)}>
                  Discard
                </button>
                <button className="primary" disabled={leaveBusy} onClick={() => saveAndLeave(leaveTo)}>
                  {leaveBusy ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
      </MapTilesContext>
    </div>
  )
}
