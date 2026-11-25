import type { DeviceStatus } from '../api'
import { lowBatteries } from '../battery'

/** Before / after a ride only (Ride tab): the sensors whose battery is low. */
export function BatteryWarning({ devices, start }: { devices?: Partial<Record<string, DeviceStatus>>; start?: boolean }) {
  const low = lowBatteries(devices)
  if (!low.length) return null
  return (
    <div className={`battery-warning${start ? ' start' : ''}`}>
      {low.map((b) => (
        <span key={b.role} className={b.critical ? 'critical' : ''}>
          {b.text}
        </span>
      ))}
    </div>
  )
}
