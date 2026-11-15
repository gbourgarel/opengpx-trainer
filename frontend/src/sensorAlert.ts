export type SensorRole = 'trainer' | 'power_meter' | 'heart_rate'

export const ROLE_LABEL: Record<SensorRole, string> = { trainer: 'Trainer', power_meter: 'Power meter', heart_rate: 'Heart rate' }

/** One line of the banner for a sensor gone silent during the ride (`lost_sensors` in the
 * telemetry, computed by the backend: `LostSensors` in session.py). `powerSource`: what the
 * power comes from now ("trainer" when the app fell back on it, "none" when nothing). */
export function lostSensorText(role: SensorRole, sinceUnixS: number, powerSource?: string): string {
  const at = new Date(sinceUnixS * 1000).toLocaleTimeString()
  let what = ''
  if (role === 'power_meter' && powerSource === 'trainer') what = ' — using the trainer’s power'
  if (role === 'power_meter' && powerSource === 'none') what = ' — no power recorded'
  return `${ROLE_LABEL[role]}: no data since ${at}${what}`
}
