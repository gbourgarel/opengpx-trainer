/** Training zones (pure).
 *
 * * Power: Coggan's 7 zones, as % of FTP (upper bounds): Z1 Recovery < 55, Z2 Endurance
 *   < 75, Z3 Tempo < 90, Z4 Threshold < 105, Z5 VO2max < 120, Z6 Anaerobic < 150, Z7
 *   Neuromuscular. Same bounds as intervals.icu's default power zones.
 * * Heart rate: Friel's cycling zones, as % of the threshold heart rate (LTHR): Z1 < 81,
 *   Z2 < 90, Z3 < 94, Z4 < 100, Z5 >= 100 (Friel's 5a/5b/5c merged).
 *
 * Colours: CSS variables --z1 ... --z7. */

export interface Zone {
  n: number
  name: string
  color: string
}

const POWER: [number, string][] = [
  [0.55, 'Recovery'],
  [0.75, 'Endurance'],
  [0.9, 'Tempo'],
  [1.05, 'Threshold'],
  [1.2, 'VO2max'],
  [1.5, 'Anaerobic'],
  [Infinity, 'Neuromuscular'],
]

const HR: [number, string][] = [
  [0.81, 'Recovery'],
  [0.9, 'Aerobic'],
  [0.94, 'Tempo'],
  [1.0, 'Threshold'],
  [Infinity, 'Above threshold'],
]

function find(table: [number, string][], frac: number): Zone {
  const i = table.findIndex(([upper]) => frac < upper)
  return { n: i + 1, name: table[i][1], color: `var(--z${i + 1})` }
}

/** Power zone of a fraction of FTP (e.g. a workout step's target). */
export function powerZoneOfFraction(frac: number): Zone {
  return find(POWER, frac)
}

/** Power zone of a power, or null without power / FTP. */
export function powerZone(watts: number | null | undefined, ftpW: number | null | undefined): Zone | null {
  if (watts == null || !ftpW || ftpW <= 0) return null
  return powerZoneOfFraction(watts / ftpW)
}

/** Heart-rate zone, or null without HR / threshold HR. */
export function hrZone(bpm: number | null | undefined, lthrBpm: number | null | undefined): Zone | null {
  if (bpm == null || bpm <= 0 || !lthrBpm || lthrBpm <= 0) return null
  return find(HR, bpm / lthrBpm)
}
