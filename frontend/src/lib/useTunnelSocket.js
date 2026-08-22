import { useEffect, useRef } from 'react'

export function useTunnelSocket(tunnelId, onMessage) {
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    if (!tunnelId) return
    let closed = false
    let socket = null
    let retry = 0
    let timer = null

    const connect = () => {
      if (closed) return
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${proto}://${location.host}/ws/tunnels/${tunnelId}`)
      socket.onmessage = (ev) => {
        try {
          handlerRef.current(JSON.parse(ev.data))
        } catch {}
      }
      socket.onopen = () => {
        retry = 0
      }
      socket.onclose = () => {
        if (!closed) {
          timer = setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000))
        }
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      if (socket) socket.close()
    }
  }, [tunnelId])
}
