/* Calibration of the power source (trainer spin-down, power-meter zero offset): what the
 * dialogs and buttons show, from the devices status in the telemetry. Pure functions. */
import type { CalibrationInfo, CalibrationRole, DeviceStatus } from './api'

export const CALIBRATION_ROLES: CalibrationRole[] = ['trainer', 'power_meter']

export const CALIBRATION_LABEL: Record<CalibrationRole, string> = {
  trainer: 'Trainer spin-down',
  power_meter: 'Power meter zero',
}

/** Calibratable from the app: connected over ANT+ (or the simulator). */
export function canCalibrate(dev?: DeviceStatus | null): boolean {
  return !!dev?.connected && (dev.transport === 'ant' || dev.transport === 'sim')
}

/** Roles whose device asks for a calibration and can get one now (nothing running), unless
 * the last one succeeded: the Tacx raises its flag at every power-up and after a reboot, even
 * right after a successful spin-down (the backend keeps the last result while it runs). */
export function requestedCalibrations(devices?: Partial<Record<string, DeviceStatus>>): CalibrationRole[] {
  return CALIBRATION_ROLES.filter((r) => {
    const d = devices?.[r]
    return !!d?.calibration_requested && canCalibrate(d) && !d.calibration?.active && d.calibration?.phase !== 'done'
  })
}

/** The run a dialog follows: the one it started (same `started_at`); until the telemetry
 * shows it, the answer of the start request. Never the previous result of the sensor. */
export function followedRun(dev: DeviceStatus | undefined, started: CalibrationInfo | null): CalibrationInfo | null {
  if (!started) return null
  const live = dev?.calibration
  return live && live.started_at === started.started_at ? live : started
}

export interface CalibrationView {
  steps: string[]
  /** index in `steps` of the current one */
  step: number
  text: string
  tone: 'active' | 'ok' | 'error'
  /** live speed / target speed, 0-1 (spin-down, speeding up) */
  progress?: number
}

const seconds = (ms: number | null) => (ms == null ? '—' : `${(ms / 1000).toFixed(1)} s`)

export function calibrationView(c: CalibrationInfo): CalibrationView {
  const ended = (step: number): CalibrationView | null =>
    c.phase === 'failed'
      ? { steps: [], step, text: c.message || 'Calibration failed.', tone: 'error' }
      : c.phase === 'cancelled'
        ? { steps: [], step, text: 'Cancelled.', tone: 'error' }
        : null
  if (c.kind === 'spin_down') {
    const steps = ['Pedal up to the target speed', 'Stop pedalling, let the wheel coast', 'Result']
    const end = ended(2)
    if (end) return { ...end, steps }
    if (c.phase === 'done') {
      const temp = c.temperature_c != null ? ` (trainer at ${c.temperature_c} °C)` : ''
      // the Tacx gives no time (0xFFFF, 2026-11-22): a success all the same
      const text = c.spin_down_ms == null ? `Spin-down done${temp}.` : `Spin-down time ${seconds(c.spin_down_ms)}${temp}.`
      return { steps, step: 2, text, tone: 'ok' }
    }
    if (c.phase === 'coast') return { steps, step: 1, text: 'Stop pedalling now and let the wheel coast down: the trainer is measuring.', tone: 'active' }
    if (c.phase === 'speed_up') {
      const target = c.target_speed_kmh
      const progress = target && c.speed_kmh != null ? Math.max(0, Math.min(1, c.speed_kmh / target)) : undefined
      return { steps, step: 0, text: target ? `Pedal up to ${target} km/h.` : 'Pedal up to the target speed.', tone: 'active', progress }
    }
    return { steps, step: 0, text: 'Asking the trainer…', tone: 'active' }
  }
  const steps = ['No weight on the pedals, cranks still', 'Result']
  const end = ended(1)
  if (end) return { ...end, steps }
  if (c.phase === 'done') return { steps, step: 1, text: `Zero offset done (calibration value ${c.zero_offset ?? '—'}).`, tone: 'ok' }
  return { steps, step: 0, text: 'Calibrating… keep the cranks still.', tone: 'active' }
}

const two = (n: number) => String(n).padStart(2, '0')

/** "last: 18:30 · 9.8 s" for a finished run (local time), null otherwise. */
export function lastCalibrationText(c: CalibrationInfo | null | undefined): string | null {
  if (!c || c.active || c.finished_at == null) return null
  const d = new Date(c.finished_at * 1000)
  const at = `${two(d.getHours())}:${two(d.getMinutes())}`
  if (c.phase === 'cancelled') return null
  if (c.phase === 'failed') return `last: ${at} · failed`
  if (c.kind === 'spin_down') return `last: ${at} · ${c.spin_down_ms == null ? 'done' : seconds(c.spin_down_ms)}`
  return `last: ${at} · offset ${c.zero_offset ?? '—'}`
}
