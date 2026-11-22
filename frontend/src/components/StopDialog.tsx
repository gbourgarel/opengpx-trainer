import { useState } from 'react'
import { fmtTime } from '../api'

/** "Stop the ride?": Save, Discard (asked twice: it cannot be undone) or Keep riding. */
export function StopDialog({ elapsedS, distanceM, onSave, onDiscard, onClose }: { elapsedS?: number; distanceM?: number; onSave: () => void; onDiscard: () => void; onClose: () => void }) {
  const [discarding, setDiscarding] = useState(false)
  const km = distanceM != null && distanceM > 0 ? ` · ${(distanceM / 1000).toFixed(1)} km` : ''
  const ridden = `${fmtTime(elapsedS ?? 0)}${km}`
  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="dialog" aria-label="Stop the ride">
        <h3>{discarding ? 'Discard this ride?' : 'Stop the ride?'}</h3>
        <p className="muted">
          {discarding ? `${ridden} of riding will be lost. It cannot be undone.` : `${ridden} ridden. Save it to the history, or discard it.`}
        </p>
        <div className="dialog-actions">
          {discarding ? (
            <>
              <button onClick={() => setDiscarding(false)}>Back</button>
              <button className="danger" onClick={onDiscard}>
                Discard
              </button>
            </>
          ) : (
            <>
              <button onClick={onClose}>Keep riding</button>
              <button className="danger" onClick={() => setDiscarding(true)}>
                Discard
              </button>
              <button className="primary" onClick={onSave}>
                Save
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
