import { useState } from 'react'
import { api, type CalibrationInfo, type CalibrationRole, type DeviceStatus } from '../api'
import { CALIBRATION_LABEL, CALIBRATION_ROLES, calibrationView, canCalibrate, followedRun, requestedCalibrations } from '../calibration'

const INTRO: Record<CalibrationRole, string[]> = {
  trainer: [
    'The trainer measures how its flywheel slows down, so that its power reading (and ERG) stays accurate. Best done warmed up, after ~10 min of riding: pause the ride, it resumes on your next pedal stroke afterwards.',
    'You will pedal up to the speed the trainer asks for (about 30 km/h), then stop pedalling and let the wheel coast until it stops. ERG is off meanwhile.',
  ],
  power_meter: ['The power meter measures what zero torque reads.', 'Unclip and keep the cranks still, with no weight on the pedals.'],
}

/** Guided calibration of one sensor: instructions, then the steps live from the telemetry. */
export function CalibrationDialog({ role, dev, onClose }: { role: CalibrationRole; dev?: DeviceStatus; onClose: () => void }) {
  const [started, setStarted] = useState<CalibrationInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = followedRun(dev, started)
  const view = run ? calibrationView(run) : null

  const start = () => {
    setBusy(true)
    setError(null)
    api
      .calibrate(role)
      .then(setStarted)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  const close = () => {
    if (run?.active) api.cancelCalibration().catch(() => undefined)
    onClose()
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog calibration" role="dialog" aria-label={CALIBRATION_LABEL[role]}>
        <h3>{CALIBRATION_LABEL[role]}</h3>
        {!view ? (
          INTRO[role].map((t) => (
            <p key={t} className="muted">
              {t}
            </p>
          ))
        ) : (
          <>
            <ol className="cal-steps">
              {view.steps.map((s, i) => (
                <li key={s} className={i === view.step ? 'current' : i < view.step ? 'past' : ''}>
                  {s}
                </li>
              ))}
            </ol>
            <p className={`cal-text ${view.tone}`}>{view.text}</p>
            {run?.phase === 'speed_up' && (
              <div className="cal-speed">
                <div className="bar">
                  <div style={{ width: `${(view.progress ?? 0) * 100}%` }} />
                </div>
                <span>
                  now <b>{run.speed_kmh != null ? run.speed_kmh.toFixed(1) : '—'}</b> km/h
                </span>
              </div>
            )}
          </>
        )}
        {error && <p className="error-inline">{error}</p>}
        <div className="dialog-actions">
          {run?.active ? (
            <button onClick={close}>Cancel</button>
          ) : (
            <>
              <button onClick={close}>{run ? 'Close' : 'Cancel'}</button>
              {run?.phase !== 'done' && (
                <button className="primary" onClick={start} disabled={busy || !canCalibrate(dev)}>
                  {run ? 'Try again' : 'Start'}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** A button opening the calibration dialog of a sensor (disabled when it cannot be done). */
export function CalibrateButton({ role, dev, label = 'Calibrate', className, disabled }: { role: CalibrationRole; dev?: DeviceStatus; label?: string; className?: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const why = !canCalibrate(dev) ? (dev?.connected ? 'Only over ANT+' : 'Not connected') : undefined
  return (
    <>
      <button type="button" className={className} disabled={disabled || !!why} title={why ?? CALIBRATION_LABEL[role]} onClick={() => setOpen(true)}>
        {label}
      </button>
      {open && <CalibrationDialog role={role} dev={dev} onClose={() => setOpen(false)} />}
    </>
  )
}

/** Before a ride (Ride tab): calibration buttons, and a nudge when a sensor asks for one. */
export function CalibrationOffer({ devices }: { devices?: Partial<Record<string, DeviceStatus>> }) {
  const roles = CALIBRATION_ROLES.filter((r) => canCalibrate(devices?.[r]))
  if (!roles.length) return null
  const asked = requestedCalibrations(devices)
  return (
    <div className={`cal-offer ${asked.length ? 'asked' : ''}`}>
      {asked.includes('trainer') && <span>The trainer asks for a spin-down calibration.</span>}
      {asked.includes('power_meter') && <span>The power meter asks for a calibration.</span>}
      {!asked.length && <span className="muted">Calibrate:</span>}
      {roles.map((r) => (
        <CalibrateButton key={r} role={r} dev={devices?.[r]} label={CALIBRATION_LABEL[r]} className={asked.includes(r) ? 'primary' : ''} />
      ))}
    </div>
  )
}
