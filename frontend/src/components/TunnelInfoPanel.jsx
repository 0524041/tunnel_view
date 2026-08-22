import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { toast } from '../lib/toast'
import { formatMileage } from '../lib/mileage'
import LayoutEditor from './LayoutEditor'

const ROT_OPTIONS = [0, 90, 180, 270]

export default function TunnelInfoPanel({ tunnelId, info, onJump, onJumpSeq, onChanged, currentGroupCount = 0 }) {
  const [tab, setTab] = useState('report')
  const [tolerance, setTolerance] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

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

  const actFlag = async (index, result) => {
    setBusy(true)
    setError('')
    try {
      await api.reviewPhoto(tunnelId, info.flagged[index].photo_id, result)
      const next = info.flagged.find((f, j) => j !== index)
      onChanged?.()
      if (next?.group_seq != null) onJumpSeq?.(next.group_seq)
      else if (info.flagged[index]?.group_seq != null) onJumpSeq?.(info.flagged[index].group_seq)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
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
          ['flagged', `待檢查 ${info.flagged.length || ''}`],
          ['reviewed', `人工檢查 ${info.reviewed.length || ''}`],
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
                <span>待檢查</span><b>{report.flagged_count ?? 0}</b>
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
                    <span>新待檢查</span><b>{preview.flagged_count}</b>
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

        {tab === 'flagged' && (
          <>
            {info.flagged.length === 0 && <p className="hint drawer-empty">目前沒有待檢查照片。</p>}
            {info.flagged.map((f, i) => (
              <div key={f.photo_id} className="panel flag-card with-thumb">
                <img className="flag-thumb" src={api.photoUrl(tunnelId, f.photo_id, 160)} alt="" />
                <div className="flag-body">
                  <div className="mono list-main">{f.camera} · {f.rel_path}</div>
                  <span className="chip amber">{f.reason}{f.group_seq != null ? ` · 群組 #${String(f.group_seq + 1).padStart(4, '0')}` : ''}</span>
                <div className="row-actions">
                  <button type="button" className="btn small" onClick={() => f.group_seq != null && onJumpSeq?.(f.group_seq)}>
                    📍 跳轉預覽
                  </button>
                  <button type="button" className="btn small" disabled={busy} onClick={() => actFlag(i, 'ok')}>✅ 檢查OK</button>
                  <button type="button" className="btn danger small" disabled={busy} onClick={() => actFlag(i, 'anomaly')}>🚩 標注異常</button>
                </div>
                </div>
              </div>
            ))}
          </>
        )}

        {tab === 'reviewed' && (
          <>
            {info.reviewed.length === 0 && info.manual_missing.length === 0 && (
              <p className="hint drawer-empty">尚無人工檢查紀錄。</p>
            )}
            {info.reviewed.map((r) => (
              <div key={`rv-${r.photo_id}`} className="panel flag-card">
                <div className="mono list-main">{r.camera} · {r.rel_path}</div>
                <div className="row-actions">
                  <span className={`chip ${r.result === 'ok' ? 'green-chip' : 'red'}`}>
                    {r.result === 'ok' ? '✅ 檢查OK' : '🚩 已標注異常'}
                  </span>
                  {r.group_seq != null && (
                    <button type="button" className="btn small" onClick={() => onJumpSeq?.(r.group_seq)}>📍</button>
                  )}
                  <button
                    type="button"
                    className="btn small"
                    title="撤銷結論，回到待檢查"
                    onClick={() => api.resetReview(tunnelId, r.photo_id).then(onChanged)}
                  >↩</button>
                </div>
              </div>
            ))}
            {info.manual_missing.length > 0 && (
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
          </>
        )}

        {tab === 'cams' && (
          <>
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
