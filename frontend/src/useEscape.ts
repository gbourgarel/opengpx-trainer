import { useEffect, useRef } from 'react'

/** Esc closes a dialog the safe way (Keep riding, Back, Stay): ``onEscape`` while it is set. */
export function useEscape(onEscape: (() => void) | null) {
  const latest = useRef(onEscape)
  useEffect(() => {
    latest.current = onEscape
  })
  const active = onEscape != null
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !latest.current) return
      e.preventDefault()
      latest.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active])
}
