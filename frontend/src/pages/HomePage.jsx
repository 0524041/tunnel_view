import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { formatMileage } from '../lib/mileage'

export default function HomePage({ onOpenTunnel, onNewTunnel }) {
  const [tunnels, setTunnels] = useState(null)

  useEffect(() => {
    api.listTunnels().then(setTunnels).catch(() => setTunnels([]))
  }, [])

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
                開啟檢視 <span className="mono">#{String(t.tunnel_id).padStart(3, '0')}</span>
              </div>
            </button>
          ))}
        </div>
      </main>
    </div>
  )
}
