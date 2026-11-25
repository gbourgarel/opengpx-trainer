/* Low sensor batteries, from the devices status in the telemetry. Shown only before and after
 * a ride (never while riding: a sensor that reports "low" mid-ride still has hours left, and
 * nothing can be done about it then). Pure functions. */
import type { DeviceStatus } from './api'

/** ANT+ / FIT battery status from which a battery is worth a warning (4 low, 5 critical). */
export const LOW_STATUS = 4
/** Bluetooth Battery Level (%) at or below which a battery is worth a warning. */
export const LOW_LEVEL_PCT = 20

const ROLE_LABEL: Record<string, string> = {
  trainer: 'Trainer',
  power_meter: 'Power meter',
  heart_rate: 'Heart-rate strap',
}

export interface LowBattery {
  role: string
  critical: boolean
  /** e.g. "Power meter: battery low (3.77 V)" */
  text: string
}

/** The sensors whose last battery report is low or critical, trainer first. */
export function lowBatteries(devices?: Partial<Record<string, DeviceStatus>>): LowBattery[] {
  const out: LowBattery[] = []
  for (const role of Object.keys(ROLE_LABEL)) {
    const b = devices?.[role]?.battery
    if (!b) continue
    const byStatus = b.status != null && b.status >= LOW_STATUS
    const byLevel = b.level != null && b.level <= LOW_LEVEL_PCT
    if (!byStatus && !byLevel) continue
    const critical = b.status === 5 || (b.level != null && b.level <= 5)
    const detail = [b.level != null ? `${b.level} %` : null, b.voltage != null ? `${b.voltage.toFixed(2)} V` : null].filter(Boolean).join(', ')
    out.push({ role, critical, text: `${ROLE_LABEL[role]}: battery ${critical ? 'critical' : 'low'}${detail ? ` (${detail})` : ''}` })
  }
  return out
}
