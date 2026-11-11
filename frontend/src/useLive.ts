import { useEffect, useRef, useState } from 'react'
import type { Telemetry } from './api'

/** Live telemetry over WebSocket with auto-reconnect. */
export function useLive() {
  const [tel, setTel] = useState<Telemetry>({ state: 'disconnected' })
  const [connected, setConnected] = useState(false)
  const recent = useRef<{ at: number; p: number }[]>([])

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: number | undefined
    let closed = false
    let lastMessage = 0

    const open = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/live`)
      lastMessage = performance.now()
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) timer = window.setTimeout(open, 1000)
      }
      ws.onmessage = (ev) => {
        lastMessage = performance.now()
        const m = JSON.parse(ev.data) as Telemetry
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
    // The server sends 4 messages a second. Silence means a dead connection that the browser
    // has not noticed (e.g. a tablet waking up: the server dropped it while it slept). Start
    // a new one now instead of waiting for TCP to give up.
    const watchdog = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN || performance.now() - lastMessage < 5000) return
      const old = ws
      old.onclose = old.onmessage = null
      old.close()
      setConnected(false)
      open()
    }, 1000)
    return () => {
      closed = true
      window.clearTimeout(timer)
      window.clearInterval(ping)
      window.clearInterval(watchdog)
      ws?.close()
    }
  }, [])

  return { tel, connected }
}
