import { useEffect, useRef } from 'react'
import { api, type Telemetry } from './api'

/** Keyboard shortcuts of the ride screen.
 *
 * * Space: pause / resume
 * * ↑ / ↓ (or + / −): workout intensity ±1 % (ERG, GPX + workout); effort ±2 % on a plain
 *   GPX ride following the slope; target ±5 W on a GPX ride in manual target mode
 * * M: sound on / off
 * * V: immersive 3D view on / off (GPX rides); Esc leaves it
 *
 * Ignored while typing in a field or with Ctrl / Cmd / Alt held. */
export const SHORTCUTS_HELP = 'Space pause/resume · ↑↓ intensity · M sound · V 3D view'

type Field = 'intensity_pct' | 'effort_pct' | 'manual_target_w'

// how long a sent value is preferred over the telemetry (which may not reflect it yet)
const PENDING_MS = 1500

export function useRideShortcuts(opts: {
  tel: Telemetry
  enabled: boolean
  hasWorkout: boolean
  sound: boolean
  setSound: (on: boolean) => void
  onError: (msg: string) => void
  /** immersive view: available (GPX ride with its route), shown, switch */
  canImmersive?: boolean
  immersive?: boolean
  setImmersive?: (on: boolean) => void
}) {
  const latest = useRef(opts)
  useEffect(() => {
    latest.current = opts // the key handler reads the latest telemetry / callbacks
  })
  // last value sent per field: rapid presses add up even before the telemetry catches up
  const pending = useRef<{ field: Field; value: number; at: number } | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const { tel, enabled, hasWorkout, sound, setSound, onError, canImmersive, immersive, setImmersive } = latest.current
      if (!enabled || e.ctrlKey || e.metaKey || e.altKey) return
      const el = e.target as HTMLElement | null
      if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return
      const fail = (err: Error) => onError(err.message)

      if ((e.key === 'v' || e.key === 'V') && canImmersive && setImmersive) {
        setImmersive(!immersive)
        return
      }
      if (e.key === 'Escape' && immersive && setImmersive) {
        setImmersive(false)
        return
      }

      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault() // no page scroll, no click on the focused button
        if (e.repeat) return
        if (tel.state === 'running') api.pause().catch(fail)
        else if (tel.state === 'paused' || tel.state === 'ready') api.resume().catch(fail)
        return
      }
      if (e.key === 'm' || e.key === 'M') {
        setSound(!sound)
        return
      }
      const up = e.key === 'ArrowUp' || e.key === '+' || e.key === '='
      const down = e.key === 'ArrowDown' || e.key === '-' || e.key === '_'
      if (!up && !down) return
      e.preventDefault()
      let field: Field, step: number, lo: number, hi: number, fallback: number
      if (tel.mode === 'erg' || hasWorkout) [field, step, lo, hi, fallback] = ['intensity_pct', 1, 10, 200, 100]
      else if (tel.target_mode === 'manual') [field, step, lo, hi, fallback] = ['manual_target_w', 5, 0, 2000, tel.target_w ?? 0]
      else [field, step, lo, hi, fallback] = ['effort_pct', 2, 10, 200, 100]
      const p = pending.current
      const now = performance.now()
      const base = p && p.field === field && now - p.at < PENDING_MS ? p.value : (tel[field] ?? fallback)
      // to the next multiple of the step (a typed 203 W goes to 205 / 200, not 208 / 198)
      const next = up ? Math.floor(base / step + 1e-9) * step + step : Math.ceil(base / step - 1e-9) * step - step
      const value = Math.max(lo, Math.min(hi, next))
      pending.current = { field, value, at: now }
      // one request at a time, in order: concurrent ones could land out of order
      queue.current = queue.current.then(() => api.adjust({ [field]: value }).then(() => undefined, fail))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
