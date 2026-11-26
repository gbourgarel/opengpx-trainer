import { useState } from 'react'
import { api } from '../api'
import { FEELS } from '../feedback'

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

/** After a ride is saved: "How was it?" (RPE, feel, carbohydrates and water, all optional),
 * written into the FIT file before it may be uploaded. Skip leaves the file as it is. */
export function FeedbackDialog({ rideId, name, onDone }: { rideId: number; name?: string; onDone: () => void }) {
  const [rpe, setRpe] = useState<number | null>(null)
  const [feel, setFeel] = useState<number | null>(null)
  const [carbs, setCarbs] = useState('') // g, as typed
  const [water, setWater] = useState('') // ml, as typed
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const amount = (s: string) => (s.trim() === '' ? null : Math.round(Number(s)))

  const save = () => {
    const carbs_g = amount(carbs)
    const water_ml = amount(water)
    if (rpe == null && feel == null && carbs_g == null && water_ml == null) return onDone()
    if ([carbs_g, water_ml].some((v) => v != null && !(v >= 0))) return setError('amounts must be numbers ≥ 0')
    setBusy(true)
    api
      .rideFeedback(rideId, { rpe, feel, carbs_g, water_ml })
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

        <div className="dialog-row fuel">
          <label>
            <span className="dialog-label">Carbohydrates eaten (g)</span>
            <input type="number" min={0} step={5} inputMode="numeric" value={carbs} onChange={(e) => setCarbs(e.target.value)} />
          </label>
          <label>
            <span className="dialog-label">Water drunk (ml)</span>
            <input type="number" min={0} step={50} inputMode="numeric" value={water} onChange={(e) => setWater(e.target.value)} />
          </label>
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
