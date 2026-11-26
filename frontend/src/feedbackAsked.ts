// Rides already asked "How was it?" in this browser. A ride that finished on its own stays
// in the telemetry ("saved") until it is closed: without this, a page reload asked again.
import { getSetting, setSetting } from './localSettings'

const KEY = 'feedbackAsked'
const KEEP = 20 // the latest rides are enough: only a ride just finished can be asked

/** ``ids`` with ``id`` added last, the oldest dropped beyond ``keep``. */
export function withAsked(ids: number[], id: number, keep = KEEP): number[] {
  return [...ids.filter((x) => x !== id), id].slice(-keep)
}

export function loadAsked(): number[] {
  try {
    const v: unknown = JSON.parse(getSetting(KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : []
  } catch {
    return []
  }
}

/** Remembers ``id`` (answered or skipped) and returns the rides asked, ``id`` included. */
export function rememberAsked(id: number): number[] {
  const ids = withAsked(loadAsked(), id)
  try {
    setSetting(KEY, JSON.stringify(ids))
  } catch {
    // storage disabled: remembered until the page is reloaded
  }
  return ids
}
