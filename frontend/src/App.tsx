import { useEffect, useState } from 'react'
import { api, type Profile, type RouteDetail, type Workout } from './api'
import { HistoryPage, RoutesPage, WorkoutsPage } from './pages/LibraryPages'
import { ProfilePage } from './pages/ProfilePage'
import { SimulatorPanel } from './components/SimulatorPanel'
import { RidePage, type ActiveRide } from './pages/RidePage'
import { useLive } from './useLive'

type Tab = 'ride' | 'workouts' | 'routes' | 'history' | 'profile'
const TABS: [Tab, string][] = [
  ['ride', 'Ride'],
  ['workouts', 'Workouts (ERG)'],
  ['routes', 'Routes (GPX)'],
  ['history', 'History'],
  ['profile', 'Profile'],
]

function Dot({ on, label }: { on?: boolean; label: string }) {
  return (
    <span className={`dev ${on ? 'on' : ''}`}>
      <i />
      {label}
    </span>
  )
}

export default function App() {
  const { tel, connected, history } = useLive()
  const [tab, setTab] = useState<Tab>('ride')
  const [profile, setProfile] = useState<Profile | null>(null)
  const [active, setActive] = useState<ActiveRide | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getProfile().then(setProfile).catch(() => {})
  }, [])

  const hub = tel.hub
  const dev = tel.devices

  const connect = (kind: 'ant' | 'simulator') => {
    setError(null)
    api.connect(kind).catch((e) => setError(e.message))
  }

  const startWorkout = (w: Workout) =>
    api
      .start({ mode: 'erg', workout_id: w.id })
      .then(() => {
        setActive({ mode: 'erg', workout: w })
        setTab('ride')
      })
      .catch((e) => setError(e.message))

  const startRoute = (r: RouteDetail) =>
    api
      .start({ mode: 'gpx', route_id: r.id })
      .then(() => {
        setActive({ mode: 'gpx', route: r })
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
              <Dot on={dev?.trainer.connected} label="Trainer" />
              <Dot on={dev?.power_meter.connected} label="Power" />
              <Dot on={dev?.heart_rate.connected} label="HR" />
              <span className="muted">{hub === 'simulator' ? 'simulator' : 'ANT+'}</span>
              <button className="ghost" onClick={() => api.disconnect()}>
                Disconnect
              </button>
            </>
          ) : (
            <>
              <button className="primary" onClick={() => connect('ant')}>
                Connect ANT+
              </button>
              <button className="ghost" onClick={() => connect('simulator')}>
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
      <main>
        {tab === 'ride' && tel.sim && <SimulatorPanel key={tel.hub ?? ''} initial={tel.sim} />}
        {tab === 'ride' && <RidePage tel={tel} history={history} active={active} profile={profile} onEnd={() => setActive(null)} />}
        {tab === 'workouts' && <WorkoutsPage profile={profile} canStart={!!hub} onStart={startWorkout} />}
        {tab === 'routes' && <RoutesPage canStart={!!hub} onStart={startRoute} />}
        {tab === 'history' && <HistoryPage />}
        {tab === 'profile' && <ProfilePage onSaved={setProfile} />}
      </main>
    </div>
  )
}
