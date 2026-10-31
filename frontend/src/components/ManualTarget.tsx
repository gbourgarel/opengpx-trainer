import { useRef, useState } from 'react'
import { api } from '../api'

const STEPS = [5, 10, 25]

/**
 * Rider-set target power for GPX rides (bypasses the grade curve).
 * Owns its value so rapid clicks accumulate instead of reading slightly stale telemetry;
 * seeded from the server when the control appears.
 */
export function ManualTarget({ initial, onError }: { initial: number; onError: (msg: string) => void }) {
  const [value, setValue] = useState(Math.round(initial))
  const [draft, setDraft] = useState<string | null>(null)
  const cur = useRef(Math.round(initial))

  const send = (w: number) => {
    const v = Math.max(0, Math.min(2000, Math.round(w)))
    cur.current = v
    setValue(v)
    api.adjust({ manual_target_w: v }).catch((e: Error) => onError(e.message))
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
