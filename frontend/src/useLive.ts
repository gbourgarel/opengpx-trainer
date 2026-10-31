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
  const lastElapsed = useRef(-1)

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
        if (m.elapsed_s != null && m.state === 'running') {
          if (m.elapsed_s < lastElapsed.current) history.current = [] // new session
          if (m.elapsed_s !== lastElapsed.current) {
            history.current.push({
              t: m.elapsed_s,
              power: m.power_w ?? null,
              target: m.target_w ?? null,
              hr: m.heart_rate_bpm ?? null,
              cadence: m.cadence_rpm ?? null,
              speed: m.speed_kmh ?? null,
            })
            if (history.current.length > MAX_HISTORY) history.current.shift()
          }
          lastElapsed.current = m.elapsed_s
        } else if (m.elapsed_s == null) {
          lastElapsed.current = -1
        }
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
