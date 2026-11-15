import type { Profile } from './api'

/** Fields the server adds to its answers, not part of what the rider edits. */
const NOT_EDITED = new Set(['devices_note', 'intervals_api_key_set'])

/** The Profile form differs from the profile last loaded or saved (a typed key counts too). */
export function profileChanged(draft: Profile, saved: Profile): boolean {
  const keys = new Set([...Object.keys(draft), ...Object.keys(saved)])
  for (const k of keys) {
    if (NOT_EDITED.has(k)) continue
    const a = draft[k as keyof Profile] ?? null
    const b = saved[k as keyof Profile] ?? null
    if (JSON.stringify(a) !== JSON.stringify(b)) return true
  }
  return false
}

/** What the app needs to guard a tab change: unsaved edits, and how to save them. */
export interface ProfileGuard {
  dirty: boolean
  save: () => Promise<boolean>
}
