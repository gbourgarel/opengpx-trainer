import { useEffect, useRef, useState } from 'react'
import type { Telemetry } from './api'

export interface HistoryPoint {
  t: number // elapsed s
  power: number | null
  target: number | null
  hr: number | null
  cadence: number | null
  speed: number | null
}

const MAX_HISTORY = 4 * 60 * 30 // 30 min at 4 Hz

/** Live telemetry over WebSocket with auto-reconnect, plus a rolling history buffer. */
export function useLive() {
  const [tel, setTel] = useState<Telemetry>({ state: 'disconnected' })
  const [connected, setConnected] = useState(false)
  const history = useRef<HistoryPoint[]>([])
  const historySession = useRef<string | null>(null)
  const lastElapsed = useRef(-1)
  const recent = useRef<{ at: number; p: number }[]>([])

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: number | undefined
    let closed = false

    const open = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/live`)
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) timer = window.setTimeout(open, 1000)
      }
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data) as Telemetry
        // The history belongs to one ride: start a fresh one whenever the session changes
        // (inferring "new ride" from elapsed time going backwards missed rides separated by
        // idle telemetry, and the chart then got an unsorted time axis).
        if (m.session_id && m.session_id !== historySession.current) {
          historySession.current = m.session_id
          history.current = []
          lastElapsed.current = -1
        }
        // only strictly increasing times, so the x axis is always sorted
        if (m.session_id && m.state === 'running' && m.elapsed_s != null && m.elapsed_s > lastElapsed.current) {
          history.current.push({
            t: m.elapsed_s,
            power: m.power_w ?? null,
            target: m.target_w ?? null,
            hr: m.heart_rate_bpm ?? null,
            cadence: m.cadence_rpm ?? null,
            speed: m.speed_kmh ?? null,
          })
          if (history.current.length > MAX_HISTORY) history.current.shift()
          lastElapsed.current = m.elapsed_s
        }
        // 3 s moving average (wall clock) so the target gauge doesn't flicker on every sample
        const now = performance.now()
        if (m.power_w != null) recent.current.push({ at: now, p: m.power_w })
        recent.current = recent.current.filter((x) => now - x.at <= 3000)
        m.power_avg3_w = recent.current.length
          ? recent.current.reduce((a, x) => a + x.p, 0) / recent.current.length
          : null
        setTel(m)
      }
    }
    open()
    const ping = window.setInterval(() => ws?.readyState === 1 && ws.send('ping'), 15000)
    return () => {
      closed = true
      window.clearTimeout(timer)
      window.clearInterval(ping)
      ws?.close()
    }
  }, [])

  return { tel, connected, history }
}
