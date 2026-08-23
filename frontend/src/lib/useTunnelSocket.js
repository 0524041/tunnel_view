// Copyright (C) 2026 willywu <pop2585158@gmail.com>
// SPDX-License-Identifier: GPL-3.0-only
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

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
