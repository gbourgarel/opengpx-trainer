import { useEffect, useState } from 'react'
import { api, type DeviceStatus, type Profile, type RouteDetail, type Workout } from './api'
import { HistoryPage, RoutesPage, WorkoutsPage } from './pages/LibraryPages'
import { ProfilePage } from './pages/ProfilePage'
import { SimulatorPanel } from './components/SimulatorPanel'
import { RidePage, type ActiveRide } from './pages/RidePage'
import { useLive } from './useLive'
import { useWakeLock } from './wakeLock'

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
  const { tel, connected, history } = useLive()
  const [tab, setTab] = useState<Tab>('ride')
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
  const wake = useWakeLock(['ready', 'running', 'paused'].includes(tel.state))

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
  useEffect(() => {
    if (!sessionId || !mode || active?.sessionId === sessionId) return
    let cancelled = false
    // ERG: workout only; GPX: route, plus the workout in mixed mode
    const load =
      mode === 'erg' && workoutId != null
        ? api.workout(workoutId).then((workout) => ({ sessionId, mode, workout }) as ActiveRide)
        : mode === 'gpx' && routeId != null
          ? Promise.all([api.route(routeId), workoutId != null ? api.workout(workoutId) : Promise.resolve(undefined)]).then(
              ([route, workout]) => ({ sessionId, mode, route, workout }) as ActiveRide,
            )
          : null
    load
      ?.then((a) => {
        if (!cancelled) setActive(a)
      })
      .catch((e: Error) => !cancelled && setError(`Cannot restore the ride view: ${e.message}`))
    return () => {
      cancelled = true
    }
  }, [sessionId, mode, workoutId, routeId, active?.sessionId])

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

  const startRoute = (r: RouteDetail, w?: Workout) =>
    api
      .start({ mode: 'gpx', route_id: r.id, workout_id: w?.id })
      .then((res) => {
        setActive({ sessionId: res.session_id, mode: 'gpx', route: r, workout: w })
        setTab('ride')
      })
      .catch((e) => setError(e.message))

  return (
    <div className="app">
      <header>
        <h1>Home Trainer</h1>
        <nav>
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>
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
              <button className="ghost" onClick={() => api.disconnect()}>
                Disconnect
              </button>
            </>
          ) : (
            <>
              <button className="primary" disabled={connecting} onClick={() => connect('devices')} title="Connect the sensors chosen in Profile → Devices (ANT+ and/or Bluetooth)">
                {connecting ? 'Connecting…' : 'Connect sensors'}
              </button>
              <button className="ghost" disabled={connecting} onClick={() => connect('simulator')}>
                Simulator
              </button>
            </>
          )}
        </div>
      </header>
      {error && (
        <div className="error banner" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      <main className={tab === 'ride' ? 'ride-main' : ''}>
        {tab === 'ride' && tel.sim && <SimulatorPanel key={tel.hub ?? ''} initial={tel.sim} />}
        {tab === 'ride' && <RidePage tel={tel} history={history} active={active} profile={profile} wake={wake} onEnd={() => setActive(null)} />}
        {tab === 'workouts' && <WorkoutsPage profile={profile} canStart={!!hub} onStart={startWorkout} />}
        {tab === 'routes' && <RoutesPage canStart={!!hub} onStart={startRoute} />}
        {tab === 'history' && <HistoryPage />}
        {tab === 'profile' && <ProfilePage onSaved={setProfile} devices={dev} />}
      </main>
    </div>
  )
}
