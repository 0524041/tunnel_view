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
import { toast } from '../lib/toast'
import { formatMileage } from '../lib/mileage'
import LayoutEditor from './LayoutEditor'

const ROT_OPTIONS = [0, 90, 180, 270]

export default function TunnelInfoPanel({ tunnelId, info, onChanged, currentGroupCount = 0 }) {
  const [tab, setTab] = useState('report')
  const [tolerance, setTolerance] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [renaming, setRenaming] = useState(null)

  const [camThumbs, setCamThumbs] = useState({})
  useEffect(() => {
    if (!tunnelId) return
    api.cameraThumbs(tunnelId).then((rows) => {
      const t = {}
      for (const r of rows) t[r.camera_seq] = api.photoUrl(tunnelId, r.photo_id, 480)
      setCamThumbs(t)
    }).catch(() => {})
  }, [tunnelId])

  if (!info) return <aside className="drawer"><p className="hint" style={{ padding: 14 }}>載入中…</p></aside>

  const report = info.report || {}
  const currentTol = tolerance ?? report.tolerance_seconds ?? 2.0

  const saveLayout = async ({ cameras: cams, cols }) => {
    try {
      const cur = new Map((info.cameras || []).map((c) => [c.seq, c]))
      for (const c of cams) {
        const prev = cur.get(c.seq)
        if (!prev) continue
        if (prev.name !== c.name && c.name?.trim()) await api.setCameraName(tunnelId, c.seq, c.name)
        if (prev.rotation !== c.rotation) await api.setCameraRotation(tunnelId, c.seq, c.rotation)
        if ((prev.grid_pos ?? -1) !== c.grid_pos) await api.setCameraGridPos(tunnelId, c.seq, c.grid_pos)
      }
      if (cols !== info.layout_cols) await api.setLayoutCols(tunnelId, cols)
      toast('版型已更新')
      onChanged?.()
    } catch (e) {
      toast(e.message, 'err')
      onChanged?.()
    }
  }

  const commitRename = async (seq, name) => {
    setRenaming(null)
    const trimmed = name?.trim()
    if (!trimmed || trimmed === info.cameras.find((c) => c.seq === seq)?.name) return
    try {
      await api.setCameraName(tunnelId, seq, trimmed)
      toast('已改名')
      onChanged?.()
    } catch (e) {
      toast(e.message, 'err')
    }
  }

  const runPreview = async () => {
    setBusy(true)
    setError('')
    try {
      setPreview(await api.realignPreview(tunnelId, Number(currentTol)))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const applyRealign = async () => {
    setBusy(true)
    setError('')
    try {
      await api.realignApply(tunnelId, Number(currentTol))
      setPreview(null)
      onChanged?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="drawer info-drawer">
      <div className="info-tabs">
        {[
          ['report', '報告'],
          ['cams', '相機'],
        ].map(([k, label]) => (
          <button type="button" key={k} className={`info-tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      <div className="drawer-list info-body">
        {tab === 'report' && (
          <>
            <Section title="匯入報告">
              <div className="kv mono">
                <span>容差</span><b>{report.tolerance_seconds ?? '—'}s</b>
                <span>群組數</span><b>{report.group_count ?? '—'}</b>
                {report.imported_at && <span>建立於</span>}
                {report.imported_at && <b>{report.imported_at}</b>}
              </div>
              {(report.cameras || []).length > 0 && (
                <table className="pv-table">
                  <thead><tr><th>視角</th><th>張數</th><th>Δt</th></tr></thead>
                  <tbody>
                    {report.cameras.map((c, i) => (
                      <tr key={c.name}>
                        <td>{c.name}</td>
                        <td className="mono">{c.photo_count}</td>
                        <td className="mono">{i === 0 ? '基準' : `${c.offset_seconds >= 0 ? '+' : ''}${Number(c.offset_seconds).toFixed(2)}s`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="dist-row">
                {Object.entries(report.missing_distribution || {}).map(([m, n]) => (
                  <span key={m} className={`chip ${Number(m) > 0 ? 'red' : 'blue'}`}>缺 {m} × {n}</span>
                ))}
              </div>
            </Section>

            <Section title="重新對齊（時間容差）">
              <div className="realign-row">
                <input
                  type="number"
                  className="field mono"
                  min="0.5"
                  step="0.5"
                  value={currentTol}
                  onChange={(e) => setTolerance(parseFloat(e.target.value))}
                />
                <button type="button" className="btn small" disabled={busy} onClick={runPreview}>乾跑預覽</button>
              </div>
              {preview && (
                <div className="panel realign-preview">
                  <div className="kv mono">
                    <span>群組數</span><b>{currentGroupCount} → {preview.group_count}
                      {preview.group_count !== currentGroupCount && (
                        <span className={`mono ${preview.group_count > currentGroupCount ? 'diff-up' : 'diff-down'}`}>
                          {' '}({preview.group_count > currentGroupCount ? '+' : ''}{preview.group_count - currentGroupCount})
                        </span>
                      )}</b>
                  </div>
                  <div className="dist-row">
                    {Object.entries(preview.missing_distribution).map(([m, n]) => (
                      <span key={m} className={`chip ${Number(m) > 0 ? 'red' : 'blue'}`}>缺 {m} × {n}</span>
                    ))}
                  </div>
                  <p className="hint">錨點將自動跟隨照片，不會遺失。</p>
                  <div className="wiz-actions" style={{ marginTop: 10 }}>
                    <button type="button" className="btn small" onClick={() => setPreview(null)}>取消</button>
                    <button type="button" className="btn primary small" disabled={busy} onClick={applyRealign}>
                      {busy ? '重建中…' : '套用'}
                    </button>
                  </div>
                </div>
              )}
            </Section>

            {(report.aspect_anomalies || []).length > 0 && (
              <Section title={`比例異常 · ${report.aspect_anomalies.length}`}>
                {report.aspect_anomalies.map((a, i) => (
                  <div key={i} className="list-item">
                    <span className="mono">{a.camera} · {a.rel_path}</span>
                    <span className="hint">{a.width}×{a.height}</span>
                  </div>
                ))}
                <p className="hint">瀏覽時該格會出現 ⟳ 按鈕可就地旋轉。</p>
              </Section>
            )}

            {(info.manual_missing || []).length > 0 && (
              <Section title="合併時改判缺照">
                {info.manual_missing.map((f) => (
                  <div key={`mm-${f.photo_id}`} className="panel flag-card">
                    <div className="mono list-main">{f.camera} · {f.rel_path}</div>
                    <button
                      type="button"
                      className="btn small"
                      onClick={() => api.restorePhoto(tunnelId, f.photo_id).then(onChanged)}
                    >↩ 復原</button>
                  </div>
                ))}
              </Section>
            )}

            {info.dangling_anchors.length > 0 && (
              <Section title={`⚠ 失準錨點 · ${info.dangling_anchors.length}`}>
                {info.dangling_anchors.map((a, i) => (
                  <div key={i} className="list-item warn-text">
                    <span className="mono">{formatMileage(a.mileage_m)}</span>
                    <span className="hint">退回最近群組 #{(a.group_seq ?? -1) + 1} · 載體 {a.carrier_camera ?? '?'}</span>
                  </div>
                ))}
              </Section>
            )}
          </>
        )}

        {tab === 'cams' && (
          <>
            {(info.cameras || []).map((c) => (
              <div key={c.seq} className="panel cam-rename-row">
                <span className="label">#{String(c.seq).padStart(2, '0')}</span>
                {renaming === c.seq ? (
                  <input
                    className="field"
                    autoFocus
                    defaultValue={c.name}
                    onBlur={(e) => commitRename(c.seq, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitRename(c.seq, e.target.value)
                      if (e.key === 'Escape') setRenaming(null)
                    }}
                  />
                ) : (
                  <>
                    <span className="list-main">{c.name}</span>
                    <button type="button" className="btn small ghost" title="重新命名" onClick={() => setRenaming(c.seq)}>✎</button>
                  </>
                )}
              </div>
            ))}
            <LayoutEditor
              compact
              tunnelId={tunnelId}
              cameras={(info.cameras || []).map((c) => ({
                seq: c.seq,
                name: c.name,
                rotation: c.rotation,
                grid_pos: c.grid_pos,
                folder: null,
              }))}
              thumbs={camThumbs}
              cols={info.layout_cols ?? 'auto'}
              onChange={saveLayout}
            />
            <p className="hint" style={{ marginTop: 8 }}>
              變更即時套用；拖曳或點選兩格交換版型位置。
            </p>
          </>
        )}

        {error && <p className="err-text">{error}</p>}
      </div>
    </aside>
  )
}

function Section({ title, children }) {
  return (
    <section className="info-section">
      <span className="label">{title}</span>
      {children}
    </section>
  )
}
