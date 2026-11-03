import { useEffect, useRef, useState } from 'react'
import { api, type SimSettings } from '../api'

/**
 * Fake power input for testing without hardware.
 * Keyboard (when no input is focused): ←/→ ±10 W, Shift+←/→ ±50 W (manual mode), P = pedal
 * on/off. (Space and ↑/↓ belong to the ride shortcuts: pause, intensity.)
 *
 * The panel owns the settings (seeded from telemetry when the simulator connects) and pushes
 * every change to the backend. Edits apply instantly and rapid key presses accumulate, instead
 * of reading slightly stale telemetry.
 */
export function SimulatorPanel({ initial }: { initial: SimSettings }) {
  const [sim, setSim] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const cur = useRef(initial) // latest value, read/written only in event handlers

  const set = (patch: Partial<SimSettings>) => {
    cur.current = { ...cur.current, ...patch }
    setSim(cur.current)
    api.setSim(patch).then(
      () => setError(null),
      (e: Error) => setError(e.message),
    )
  }
  const bump = (d: number) => set({ manual_power_w: Math.max(0, cur.current.manual_power_w + d) })

  const handlers = useRef({ set, bump })
  useEffect(() => {
    handlers.current = { set, bump }
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === 'p' || e.key === 'P') {
        handlers.current.set({ pedaling: !cur.current.pedaling })
      } else if (cur.current.mode === 'manual' && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
        e.preventDefault()
        handlers.current.bump((e.shiftKey ? 50 : 10) * (e.key === 'ArrowRight' ? 1 : -1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="card sim">
      <div className="sim-row">
        <b className="sim-title">Simulator</b>
        <div className="seg">
          <button className={sim.mode === 'follow' ? 'on' : ''} onClick={() => set({ mode: 'follow' })} title="Behaves like an ERG trainer: power follows the target">
            Follow target
          </button>
          <button className={sim.mode === 'manual' ? 'on' : ''} onClick={() => set({ mode: 'manual' })} title="You set the rider's power">
            Manual power
          </button>
        </div>
        <label className="chk">
          <input type="checkbox" checked={sim.pedaling} onChange={(e) => set({ pedaling: e.target.checked })} /> pedaling (P)
        </label>
        <label className="chk">
          <input type="checkbox" checked={sim.power_meter} onChange={(e) => set({ power_meter: e.target.checked })} /> power meter
        </label>
        <label className="chk">
          <input type="checkbox" checked={sim.heart_rate} onChange={(e) => set({ heart_rate: e.target.checked })} /> HR strap
        </label>
        <label className="chk">
          <input type="checkbox" checked={sim.noise} onChange={(e) => set({ noise: e.target.checked })} /> noise
        </label>
        <label className="chk" title="Power meter reading relative to trainer">
          PM bias
          <input
            type="number"
            step={1}
            className="small"
            defaultValue={Math.round(sim.pm_bias * 100)}
            onChange={(e) => e.target.value !== '' && set({ pm_bias: Number(e.target.value) / 100 })}
          />
          %
        </label>
      </div>
      {sim.mode === 'manual' && (
        <div className="sim-row">
          <span className="muted">Rider power</span>
          {[-50, -10].map((d) => (
            <button key={d} onClick={() => bump(d)}>
              {d}
            </button>
          ))}
          <input
            type="range"
            min={0}
            max={1000}
            step={5}
            value={sim.manual_power_w}
            className="slider"
            onChange={(e) => set({ manual_power_w: Number(e.target.value) })}
          />
          {[10, 50].map((d) => (
            <button key={d} onClick={() => bump(d)}>
              +{d}
            </button>
          ))}
          <b className="sim-power">{Math.round(sim.manual_power_w)} W</b>
          <small className="muted">←/→ ±10 W · Shift ±50 · P pedal on/off</small>
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  )
}
