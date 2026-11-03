import { useState } from 'react'
import { api } from '../api'

/** After a ride is saved: ask before sending it to intervals.icu (never automatic). */
export function UploadPrompt({ rideId, name, onClose }: { rideId: number; name?: string; onClose: () => void }) {
  const [status, setStatus] = useState<{ kind: 'ask' | 'sending' | 'error'; msg?: string } | { kind: 'done'; id: string; already: boolean }>({ kind: 'ask' })

  const upload = () => {
    setStatus({ kind: 'sending' })
    api
      .uploadRide(rideId)
      .then((r) => setStatus({ kind: 'done', id: r.intervals_activity_id, already: !!r.already }))
      .catch((e: Error) => setStatus({ kind: 'error', msg: e.message }))
  }

  return (
    <div className="upload-prompt" role="dialog" aria-label="Upload to intervals.icu">
      <span>
        Ride saved{name ? ` — ${name}` : ''} (#{rideId}).{' '}
        {status.kind === 'done' ? (
          <>
            {status.already ? 'Already on intervals.icu' : 'Uploaded to intervals.icu'} ✓{' '}
            {status.id && (
              <a href={`https://intervals.icu/activities/${status.id}`} target="_blank" rel="noreferrer">
                open
              </a>
            )}
          </>
        ) : status.kind === 'error' ? (
          <span className="error-inline">Upload failed: {status.msg}</span>
        ) : (
          'Upload it to intervals.icu?'
        )}
      </span>
      <span className="actions">
        {status.kind === 'done' ? (
          <button onClick={onClose}>Close</button>
        ) : (
          <>
            <button className="primary" disabled={status.kind === 'sending'} onClick={upload}>
              {status.kind === 'sending' ? 'Uploading…' : status.kind === 'error' ? 'Retry' : 'Upload'}
            </button>
            <button disabled={status.kind === 'sending'} onClick={onClose} title="You can still upload it later from History">
              Not now
            </button>
          </>
        )}
      </span>
    </div>
  )
}
