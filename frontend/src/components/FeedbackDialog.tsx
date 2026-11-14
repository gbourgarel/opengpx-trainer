import { useState } from 'react'
import { api } from '../api'

/** Perceived effort (RPE, 1-10), with the words a Garmin Edge shows next to it. */
const RPE_WORDS: Record<number, string> = {
  1: 'Very light',
  2: 'Light',
  3: 'Light',
  4: 'Moderate',
  5: 'Moderate',
  6: 'Moderate',
  7: 'Hard',
  8: 'Hard',
  9: 'Very hard',
  10: 'Maximum',
}

/** How the rider felt (FIT `workout_feel`, 0-100 in five levels, as the Edge records it). */
const FEELS: [number, string][] = [
  [0, 'Very weak'],
  [25, 'Weak'],
  [50, 'Normal'],
  [75, 'Strong'],
  [100, 'Very strong'],
]

/** After a ride is saved: "How was it?" (RPE and feel, both optional), written into the FIT
 * file before it may be uploaded. Skip leaves the file as it is. */
export function FeedbackDialog({ rideId, name, onDone }: { rideId: number; name?: string; onDone: () => void }) {
  const [rpe, setRpe] = useState<number | null>(null)
  const [feel, setFeel] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = () => {
    if (rpe == null && feel == null) return onDone()
    setBusy(true)
    api
      .rideFeedback(rideId, { rpe, feel })
      .then(onDone)
      .catch((e: Error) => {
        setError(e.message)
        setBusy(false)
      })
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="dialog" aria-label="How was the ride?">
        <h3>How was it?</h3>
        <p className="muted">
          Ride saved{name ? ` — ${name}` : ''} (#{rideId}). Written into the FIT file, as a Garmin Edge does.
        </p>

        <div className="dialog-row">
          <span className="dialog-label">
            Effort (RPE) {rpe != null && <b>{RPE_WORDS[rpe]}</b>}
          </span>
          <div className="seg rpe">
            {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => (
              <button key={v} className={rpe === v ? 'on' : ''} title={RPE_WORDS[v]} onClick={() => setRpe(rpe === v ? null : v)}>
                {v}
              </button>
            ))}
          </div>
        </div>

        <div className="dialog-row">
          <span className="dialog-label">Feel</span>
          <div className="seg">
            {FEELS.map(([v, label]) => (
              <button key={v} className={feel === v ? 'on' : ''} onClick={() => setFeel(feel === v ? null : v)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="error-inline">Not saved: {error}</p>}
        <div className="dialog-actions">
          <button onClick={onDone} disabled={busy}>
            Skip
          </button>
          <button className="primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
