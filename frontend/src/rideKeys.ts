import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Telemetry } from './api'
import { FIELD_STEP, keyField, type KeyField, type TargetSource } from './targetSource'

/** Keyboard shortcuts of the ride screen.
 *
 * * Space: pause / resume
 * * ↑ / ↓ (or + / −): the value of the current target source (`targetSource.ts`): workout
 *   intensity ±1 %, effort ±2 % when the slope sets the target (also in the free-ride steps of
 *   a workout), target ±5 W in manual target mode
 * * M: sound on / off
 * * V: immersive 3D view on / off (GPX rides); Esc leaves it
 *
 * Ignored while typing in a field or with Ctrl / Cmd / Alt held. The help line is
 * `shortcutsHelp` in `targetSource.ts`. */

// how long a sent value is preferred over the telemetry (which may not reflect it yet)
const PENDING_MS = 1500

/** A key press the ride shortcuts ignore: modifier held, or typing in a field. */
function ignoredKey(e: KeyboardEvent): boolean {
  if (e.ctrlKey || e.metaKey || e.altKey) return true
  const el = e.target as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}

const isUpKey = (key: string) => key === 'ArrowUp' || key === '+' || key === '='
const isDownKey = (key: string) => key === 'ArrowDown' || key === '-' || key === '_'
const isSpace = (e: { key: string; code: string }) => e.key === ' ' || e.code === 'Space'

/** Ride keys whose effect is shown in the controls panel (Space: pause / resume button;
 * ↑ / ↓: the target source's value). The immersive view shows its auto-hidden controls when
 * one is pressed, so the change is visible. Not V / Esc / F / M (top bar), nor the simulator's
 * keys. */
export function wakesRideControls(e: KeyboardEvent): boolean {
  return !ignoredKey(e) && (isSpace(e) || isUpKey(e.key) || isDownKey(e.key))
}

/** A value sent to the backend, preferred over the telemetry for `PENDING_MS`. */
export interface Pending {
  field: KeyField
  value: number
  at: number
}

/** The value a press starts from: the one just sent if recent (the telemetry, up to 250 ms
 * old, may not show it yet), else the telemetry's. */
export function nudgeBase(pending: Pending | null, field: KeyField, now: number, telValue: number): number {
  return pending && pending.field === field && now - pending.at < PENDING_MS ? pending.value : telValue
}

/** One step up or down, to the next multiple of the step (a typed 203 W goes to 205 / 200,
 * not 208 / 198), within the field's bounds. */
export function nudgedValue(base: number, field: KeyField, up: boolean): number {
  const { step, lo, hi } = FIELD_STEP[field]
  const next = up ? Math.floor(base / step + 1e-9) * step + step : Math.ceil(base / step - 1e-9) * step - step
  return Math.max(lo, Math.min(hi, next))
}

/** Step the value of a target source (↑ / ↓ keys and the +/− buttons share it): rapid
 * presses add up even before the telemetry catches up, and the requests are sent one at a
 * time, in order. `shown` is the value to display (the pending one while it is recent). */
export function useNudge(tel: Telemetry, onError: (msg: string) => void) {
  const latest = useRef({ tel, onError })
  useEffect(() => {
    latest.current = { tel, onError }
  })
  const [pending, setPending] = useState<Pending | null>(null)
  const pendingRef = useRef<Pending | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())

  const telValue = (t: Telemetry, field: KeyField) => t[field] ?? (field === 'manual_target_w' ? (t.target_w ?? 0) : 100)

  const nudge = useCallback((field: KeyField, up: boolean) => {
    const { tel: t, onError: fail } = latest.current
    const now = performance.now()
    const value = nudgedValue(nudgeBase(pendingRef.current, field, now, telValue(t, field)), field, up)
    pendingRef.current = { field, value, at: now }
    setPending(pendingRef.current)
    // one request at a time, in order: concurrent ones could land out of order
    queue.current = queue.current.then(() =>
      api.adjust({ [field]: value }).then(
        () => undefined,
        (err: Error) => fail(err.message),
      ),
    )
  }, [])

  const shown = (field: KeyField) => nudgeBase(pending, field, performance.now(), telValue(tel, field))
  return { nudge, shown }
}

export function useRideShortcuts(opts: {
  tel: Telemetry
  enabled: boolean
  /** what sets the target now: ↑ / ↓ change its value */
  source: TargetSource
  /** from `useNudge`, shared with the +/− buttons */
  nudge: (field: KeyField, up: boolean) => void
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const { tel, enabled, source, nudge, sound, setSound, onError, canImmersive, immersive, setImmersive } = latest.current
      if (!enabled || ignoredKey(e)) return
      const fail = (err: Error) => onError(err.message)

      if ((e.key === 'v' || e.key === 'V') && canImmersive && setImmersive) {
        setImmersive(!immersive)
        return
      }
      if (e.key === 'Escape' && immersive && setImmersive) {
        setImmersive(false)
        return
      }

      if (isSpace(e)) {
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
      const up = isUpKey(e.key)
      const down = isDownKey(e.key)
      if (!up && !down) return
      e.preventDefault()
      nudge(keyField(source), up)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
