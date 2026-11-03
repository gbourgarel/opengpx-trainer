import { useEffect, useState } from 'react'

export type WakeLockStatus = 'on' | 'off' | 'unsupported'

/** Keeps the screen on while ``active`` (a ride in progress), with the Screen Wake Lock API.
 *
 * The browser releases the lock whenever the page is hidden (other tab, screen locked by
 * hand), so it is requested again when the page becomes visible. Only available in a secure
 * context: localhost or HTTPS — not on a tablet opening the app over plain http on the LAN. */
export function useWakeLock(active: boolean): WakeLockStatus {
  const supported = typeof navigator !== 'undefined' && 'wakeLock' in navigator && window.isSecureContext
  const [held, setHeld] = useState(false)

  useEffect(() => {
    if (!active || !supported) return
    let lock: WakeLockSentinel | null = null
    let stopped = false

    const acquire = async () => {
      if (stopped || document.visibilityState !== 'visible' || (lock && !lock.released)) return
      try {
        const l = await navigator.wakeLock.request('screen')
        if (stopped) {
          void l.release()
          return
        }
        lock = l
        setHeld(true)
        l.addEventListener('release', () => setHeld(false))
      } catch {
        setHeld(false) // e.g. battery saver: the screen may turn off
      }
    }
    const onVisibility = () => void acquire()

    void acquire()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stopped = true
      document.removeEventListener('visibilitychange', onVisibility)
      void lock?.release()
      setHeld(false)
    }
  }, [active, supported])

  if (!supported) return 'unsupported'
  return active && held ? 'on' : 'off'
}
