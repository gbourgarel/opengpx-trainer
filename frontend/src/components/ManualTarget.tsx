import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const STEPS = [5, 10, 25]
// after a send, the telemetry may still show the previous value for a moment: ignore it this long
const SETTLE_MS = 1500

/**
 * Rider-set target power for GPX rides (bypasses the grade curve).
 * Owns its value so rapid clicks accumulate instead of reading slightly stale telemetry; the
 * requests go one at a time, in order (concurrent ones could land out of order). Once nothing
 * is pending it follows the server's value, which another copy of this control (immersive
 * view, second device) may have changed.
 */
export function ManualTarget({ server, onError }: { server: number; onError: (msg: string) => void }) {
  const [value, setValue] = useState(Math.round(server))
  const [draft, setDraft] = useState<string | null>(null)
  const cur = useRef(Math.round(server))
  const queue = useRef<Promise<void>>(Promise.resolve())
  const pending = useRef(0) // requests not answered yet
  const lastSend = useRef(-Infinity)
  const serverRef = useRef(server)
  const timer = useRef<number | undefined>(undefined)

  // adopt the server's value when nothing of ours is in flight (also re-checked once the last
  // request has settled: a refused request leaves the telemetry unchanged)
  const resync = () => {
    const v = Math.round(serverRef.current)
    if (pending.current > 0 || performance.now() - lastSend.current < SETTLE_MS || v === cur.current) return
    cur.current = v
    setValue(v)
  }
  useEffect(() => {
    serverRef.current = server
    resync()
  })
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const send = (w: number) => {
    const v = Math.max(0, Math.min(2000, Math.round(w)))
    cur.current = v
    setValue(v)
    pending.current++
    lastSend.current = performance.now()
    queue.current = queue.current.then(() =>
      api
        .adjust({ manual_target_w: v })
        .then(
          () => undefined,
          (e: Error) => onError(e.message),
        )
        .finally(() => {
          pending.current--
          lastSend.current = performance.now()
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(resync, SETTLE_MS + 50)
        }),
    )
  }

  const commitDraft = () => {
    if (draft != null && draft.trim() !== '' && !Number.isNaN(Number(draft))) send(Number(draft))
    setDraft(null)
  }

  return (
    <div className="manual-target">
      <span className="label">Target</span>
      {[...STEPS].reverse().map((d) => (
        <button key={-d} onClick={() => send(cur.current - d)}>
          −{d}
        </button>
      ))}
      <input
        type="number"
        className="mt-input"
        value={draft ?? value}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commitDraft}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitDraft()
          if (e.key === 'Escape') setDraft(null)
        }}
      />
      <span className="unit">W</span>
      {STEPS.map((d) => (
        <button key={d} onClick={() => send(cur.current + d)}>
          +{d}
        </button>
      ))}
    </div>
  )
}
