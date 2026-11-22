// Settings remembered per browser (localStorage), under "opengpx-trainer.<name>".
// The app was called "Home Trainer" before 2026-11: a value stored under the former key
// "hometrainer.<name>" is still read while none is stored under the new one.
// Both throw like localStorage itself (private mode, storage disabled): callers catch.

const PREFIX = 'opengpx-trainer.'
const FORMER_PREFIX = 'hometrainer.'

export function getSetting(name: string): string | null {
  return localStorage.getItem(PREFIX + name) ?? localStorage.getItem(FORMER_PREFIX + name)
}

export function setSetting(name: string, value: string) {
  localStorage.setItem(PREFIX + name, value)
}
