// Immersive mode of the ride screen (GPX rides): the 3D view of the route over the whole window.
// The metrics overlays (power, tiles, profiles, mini map, controls) come with a later step.
import { lazy, Suspense } from 'react'
import type { RouteDetail, Telemetry } from '../api'
import './immersive.css'

// MapLibre is only downloaded when the immersive mode is opened
const Scenery3D = lazy(() => import('../components/Scenery3D'))

export function Immersive({ tel, route, onExit }: { tel: Telemetry; route: RouteDetail; onExit: () => void }) {
  return (
    <div className="immersive">
      <Suspense fallback={<div className="im-loading">Loading the 3D view…</div>}>
        <Scenery3D route={route} tel={tel} />
      </Suspense>
      <div className="im-top">
        <h2>{tel.name}</h2>
        <span className={`badge state-${tel.state}`}>{tel.state}</span>
        <span className="im-sp" />
        <button className="im-exit" onClick={onExit} title="Back to the normal ride screen (V or Esc)">
          ⤢ Normal view <kbd>V</kbd>
        </button>
      </div>
    </div>
  )
}
