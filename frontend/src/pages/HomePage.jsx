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

import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { formatMileage } from '../lib/mileage'

export default function HomePage({ onOpenTunnel, onNewTunnel }) {
  const [tunnels, setTunnels] = useState(null)

  const refresh = () => api.listTunnels().then(setTunnels).catch(() => {})
  useEffect(() => {
    refresh()
  }, [])

  const removeTunnel = (t) => {
    if (!window.confirm(`確定刪除「${t.name}」？\n此操作會移除對齊資料與所有錨點，且無法復原（照片原檔不受影響）。`)) return
    api.deleteTunnel(t.tunnel_id).then(refresh).catch((e) => alert(e.message))
  }

  return (
    <div className="home">
      <header className="home-hero display">
        <h1>隧道多視角檢視平台</h1>
        <p className="hint">多相機同步影像 · 即時里程錨定 · 公尺級定位</p>
      </header>

      <main className="home-body">
        <div className="home-head">
          <span className="label" style={{ marginBottom: 0 }}>隧道專案</span>
          <button type="button" className="btn primary" onClick={onNewTunnel}>＋ 建立新隧道</button>
        </div>

        {tunnels === null && (
          <div className="home-loading"><div className="spin" /></div>
        )}

        {tunnels?.length === 0 && (
          <div className="empty panel">
            <svg width="72" height="40" viewBox="0 0 96 52" fill="none" aria-hidden>
              <path d="M4 50V30C4 15.5 15.5 4 30 4s26 11.5 26 26v20" stroke="#2a2f37" strokeWidth="3" />
              <path d="M18 50V32a12 12 0 0 1 24 0v18" stroke="#2a2f37" strokeWidth="2" />
              <line x1="60" y1="50" x2="92" y2="50" stroke="#2a2f37" strokeWidth="2" />
              <circle cx="76" cy="38" r="5" stroke="#ffb300" strokeWidth="2" opacity="0.6" />
            </svg>
            <p>尚無隧道專案</p>
            <p className="hint">建立第一條隧道，匯入各相機資料夾即可開始檢視</p>
          </div>
        )}

        <div className="cards">
          {tunnels?.map((t) => (
            <button type="button" key={t.tunnel_id} className="tunnel-card panel" onClick={() => onOpenTunnel(t.tunnel_id, t.name)}>
              <div className="tc-top">
                <span className="display tc-name">{t.name}</span>
                <span className="chip">{t.camera_count} 台相機</span>
              </div>
              <div className="mono tc-range">
                {formatMileage(t.start_m)} <span className="arrow">⟶</span> {formatMileage(t.end_m)}
              </div>
              <div className="tc-foot hint">
                <span>開啟檢視 <span className="mono">#{String(t.tunnel_id).padStart(3, '0')}</span></span>
                <button
                  type="button"
                  className="btn danger small tc-del"
                  title="刪除此隧道專案"
                  onClick={(e) => { e.stopPropagation(); removeTunnel(t) }}
                >🗑 刪除</button>
              </div>
            </button>
          ))}
        </div>
      </main>
    </div>
  )
}
