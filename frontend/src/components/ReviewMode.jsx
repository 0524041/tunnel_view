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

function parseTs(s) {
  return new Date(s.replace(' ', 'T')).getTime()
}

export default function ReviewMode({ tunnelId, current, cameras, onClose, onChanged }) {
  const [groups, setGroups] = useState([])
  const [conflict, setConflict] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    api.groups(tunnelId, Math.max(current, 1), 1, 1).then((rows) => {
      if (alive) setGroups(rows)
    })
    return () => {
      alive = false
    }
  }, [tunnelId, current])

  const mid = groups.find((g) => g.seq === current)
  const prevG = groups.find((g) => g.seq === current - 1)
  const nextG = groups.find((g) => g.seq === current + 1)
  const midT = mid ? parseTs(mid.corrected_time) : null

  if (!mid) {
    return (
      <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
        <div className="dialog"><div className="spin" /></div>
      </div>
    )
  }

  const doMerge = async (direction, keep) => {
    setBusy(true)
    try {
      await api.mergeGroup(tunnelId, current, direction, keep)
      setConflict(null)
      onChanged?.()
      onClose()
    } catch (e) {
      if (e.conflictCameras) setConflict({ cameras: e.conflictCameras, direction })
      else setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const cols = [
    { g: prevG, label: '前一群組', dir: 'prev' },
    { g: mid, label: '當前群組', dir: null },
    { g: nextG, label: '後一群組', dir: 'next' },
  ]

  return (
    <div className="review-overlay">
      <div className="review-head">
        <span className="display review-title">合併邊界 · 群組 #{String(current + 1).padStart(4, '0')}</span>
        {error && <span className="err-text">{error}</span>}
        <div className="row-actions">
          <button type="button" className="btn small" disabled={!prevG || busy} onClick={() => doMerge('prev')}>
            ⇤ 與前合併
          </button>
          <button type="button" className="btn small" disabled={!nextG || busy} onClick={() => doMerge('next')}>
            與後合併 ⇥
          </button>
          <button type="button" className="btn small" onClick={onClose}>關閉（Esc）</button>
        </div>
      </div>

      <div className="review-grid" style={{ gridTemplateColumns: `repeat(${cols.length}, 1fr)` }}>
        {cols.map(({ g, label, dir }) => (
          <div key={label} className={`review-col ${dir === null ? 'cur' : ''}`}>
            <div className="review-colhead mono">
              <b>{label}</b>
              <span>{g ? `#${String(g.seq + 1).padStart(4, '0')}` : '—'}</span>
              <span className="hint">
                {g && midT ? `${g.seq === current ? '±' : (parseTs(g.corrected_time) - midT >= 0 ? '+' : '')}${(parseTs(g.corrected_time) - midT) / 1000}s` : ''}
              </span>
            </div>
            {cameras.map((name, ci) => {
              const p = g?.photos.find((x) => x.camera_seq === ci)
              return (
                <div key={ci} className="review-cell">
                  {p ? (
                    <img src={api.photoUrl(tunnelId, p.photo_id, 480)} alt={name} draggable={false} />
                  ) : (
                    <div className="tile-missing review-miss">無影像</div>
                  )}
                  <span className="chip cam-chip">{name}</span>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {conflict && (
        <div className="overlay" style={{ zIndex: 200 }}>
          <div className="dialog">
            <span className="label">合併衝突裁決</span>
            <p className="hint">
              相機 <b className="mono">{conflict.cameras.map((c) => cameras[c] ?? c).join('、')}</b> 在兩側群組皆有照片，
              同一群組每台相機只能保留一張。
            </p>
            <div className="wiz-actions">
              <button type="button" className="btn" disabled={busy} onClick={() => setConflict(null)}>取消合併</button>
              <button type="button" className="btn primary" disabled={busy} onClick={() => doMerge(conflict.direction, 'neighbor')}>
                保留鄰側（當前側改判缺照）
              </button>
              <button type="button" className="btn primary" disabled={busy} onClick={() => doMerge(conflict.direction, 'current')}>
                保留當前側（鄰側改判缺照）
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
