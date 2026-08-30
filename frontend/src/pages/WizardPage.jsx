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

import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { parseMileage, formatMileage } from '../lib/mileage'
import FsBrowser from '../components/FsBrowser'
import LayoutEditor from '../components/LayoutEditor'
import UnifyDialog from '../components/UnifyDialog'

export default function WizardPage({ onDone, onCancel }) {
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [startText, setStartText] = useState('K23+000')
  const [endText, setEndText] = useState('')
  const [tolerance, setTolerance] = useState(2)
  const [layoutCols, setLayoutCols] = useState('auto')
  const [cameras, setCameras] = useState([
    { seq: 0, name: '頂拱左', folder: '', rotation: 0, grid_pos: -1 },
    { seq: 1, name: '頂拱右', folder: '', rotation: 0, grid_pos: -1 },
  ])
  const [thumbs, setThumbs] = useState({})
  const [pickerFor, setPickerFor] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null) // {done,total}
  const jobIdRef = useRef(null)
  // 方向統一對話框：{tid, items:[{seq,camera,landscape,portrait}]}
  const [unify, setUnify] = useState(null)
  const [error, setError] = useState('')
  const [displayOrder, setDisplayOrder] = useState(() => localStorage.getItem('tv_display_order') || 'asc')
  // R9 專案歸檔：''＝未分類；'new' 觸發就地新增
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [])

  const ensureProject = async () => {
    const name = window.prompt('新專案名稱：')
    if (!name || !name.trim()) return ''
    try {
      const p = await api.createProject(name.trim())
      setProjects((ps) => [...ps, p])
      return p.id
    } catch (e) {
      setError(e.message)
      return ''
    }
  }

  const startM = parseMileage(startText)
  const endM = parseMileage(endText)

  const step1Valid =
    name.trim().length > 0 && startM !== null && endM !== null && endM !== startM

  const dirLabel =
    startM === null || endM === null ? '' : endM > startM ? '里程遞增 ⟶' : '⟵ 遞減里程'

  const loadThumb = (seq, folder) => {
    if (!folder) return
    api.fsList(folder).then((d) => {
      if (d.sample) {
        setThumbs((t) => ({ ...t, [seq]: api.fsPhotoUrl(`${d.path}/${d.sample}`, 320) }))
      }
    }).catch(() => {})
  }

  const handleEditorChange = ({ cameras: cams, cols }) => {
    setCameras(cams)
    setLayoutCols(cols)
  }

  const pickFolder = (i, pick) => {
    setCameras((cs) =>
      cs.map((c, j) =>
        j === i ? { ...c, folder: pick.folder, rotation: pick.rotation } : c,
      ),
    )
    loadThumb(cameras[i]?.seq ?? i, pick.folder)
    setPickerFor(null)
  }

  const runPreview = async () => {
    setBusy(true)
    setError('')
    setProgress(null)
    try {
      const body = {
        name: name.trim(),
        start_m: startM,
        end_m: endM,
        tolerance_seconds: tolerance,
        layout_cols: layoutCols,
        cameras,
      }
      const job = await api.createImportJob(body)
      jobIdRef.current = job.job_id
      // 輪詢進度（掃描 x/total 張），完成後取預覽結果
      await new Promise((resolve, reject) => {
        const poll = async () => {
          try {
            const j = await api.getImportJob(job.job_id)
            if (j.status === 'running') {
              setProgress({ done: j.done ?? 0, total: j.total ?? 0 })
              setTimeout(poll, 1200)
            } else if (j.status === 'done') {
              setProgress(null)
              setPreview(j.preview)
              resolve()
            } else if (j.status === 'interrupted') {
              reject(new Error('伺服器曾重啟，掃描中斷。請重新執行「執行對齊分析」。'))
            } else {
              reject(new Error(j.error || '分析失敗'))
            }
          } catch (e) {
            reject(e)
          }
        }
        poll()
      })
      setStep(3)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    setBusy(true)
    try {
      const r = await api.createTunnel(
        {
          name: name.trim(),
          start_m: startM,
          end_m: endM,
          tolerance_seconds: tolerance,
          layout_cols: layoutCols,
          cameras,
          project_id: projectId === '' ? null : Number(projectId),
        },
        jobIdRef.current,
      )
      const tid = r.tunnel_id
      // 方向統一：偵測混合直橫式的機位，先詢問轉正方向再進入檢視
      let mixed = []
      try {
        const info = await api.info(tid)
        const stats = info?.report?.orientation_stats || []
        mixed = stats.filter((s) => s.minority)
      } catch {
        /* 無統計資訊就跳過 */
      }
      if (mixed.length) {
        setUnify({ tid, items: mixed })
        setBusy(false)
        return
      }
      onDone(tid, name.trim())
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="wizard wizard-wide">
      <div className="wiz-head">
        <span className="display wiz-title">建立新隧道</span>
        <div className="wiz-steps mono" data-tour="wizard-steps">
          {['基本設定', '相機與版型', '對齊預覽'].map((s, i) => (
            <span key={s} className={`wstep ${step >= i + 1 ? 'on' : ''}`}>
              <b>{i + 1}</b> {s}
            </span>
          ))}
        </div>
      </div>

      <div className="wiz-body panel">
        {step === 1 && (
          <section data-tour="wizard-basics">
            <label className="label">隧道名稱</label>
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="例：八卦山隧道 西行" autoFocus />

            <div className="row2">
              <div>
                <label className="label">起點樁號（拍攝起點）</label>
                <input
                  className={`field mono ${startM === null && startText ? 'error' : ''}`}
                  value={startText}
                  onChange={(e) => setStartText(e.target.value)}
                  placeholder="K23+000"
                />
              </div>
              <div>
                <label className="label">迄點樁號（拍攝終點）</label>
                <input
                  className={`field mono ${endM === null && endText ? 'error' : ''}`}
                  value={endText}
                  onChange={(e) => setEndText(e.target.value)}
                  placeholder="K24+200"
                />
              </div>
            </div>
            <p className="hint" style={{ marginTop: 8 }}>
              支援格式：<span className="mono">K23+150</span> /{' '}
              <span className="mono">23K+150</span> / <span className="mono">23+150</span> /{' '}
              <span className="mono">23150</span>。行進方向由起迄決定：
              <b className="mono" style={{ color: 'var(--amber)' }}> {dirLabel || '—'}</b>
            </p>

            <label className="label" style={{ marginTop: 12 }}>所屬專案（可之後再歸檔）</label>
            <select
              className="field"
              value={projectId}
              onChange={async (e) => {
                const v = e.target.value
                if (v === 'new') {
                  const id = await ensureProject()
                  setProjectId(id)
                } else {
                  setProjectId(v)
                }
              }}
            >
              <option value="">未分類</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
              <option value="new">＋ 新增專案…</option>
            </select>
            <p className="hint" style={{ marginTop: 4 }}>
              建議隧道名稱含方向與年份，例「鳥踏坑西行-2026」；同一案子（專案）下的多次拍攝就會歸在一起。
            </p>

            <div className="wiz-actions">
              <button type="button" className="btn" onClick={onCancel}>取消</button>
              <button type="button" className="btn primary" disabled={!step1Valid} onClick={() => { setError(''); setStep(2) }}>下一步</button>
            </div>
          </section>
        )}

        {step === 2 && (
          <section>
            {pickerFor != null && (
              <FsBrowser
                initialPath={cameras[pickerFor]?.folder || ''}
                initialRotation={cameras[pickerFor]?.rotation ?? 0}
                onPick={(pick) => pickFolder(pickerFor, pick)}
                onClose={() => setPickerFor(null)}
              />
            )}

            <LayoutEditor
              tunnelId={null}
              cameras={cameras}
              thumbs={thumbs}
              cols={layoutCols}
              onChange={handleEditorChange}
              onPickFolder={(i) => setPickerFor(i)}
              onRemoveCamera={(seq) => {
                setCameras((cs) => {
                  const filtered = cs.filter((c) => c.seq !== seq)
                  return filtered.map((c, j) => ({ ...c, seq: j, grid_pos: -1 }))
                })
              }}
            />
            <button
              type="button"
              className="btn small"
              style={{ marginTop: 10 }}
              disabled={cameras.length >= 8}
              onClick={() =>
                setCameras((cs) => [
                  ...cs,
                  { seq: cs.length, name: `視角 ${cs.length + 1}`, folder: '', rotation: 0, grid_pos: -1 },
                ])
              }
            >＋ 新增相機</button>

            {cameras.some((c) => c.folder) ? (
              <p className="hint" style={{ marginTop: 10 }}>
                已選資料夾的相機會顯示首張縮圖；拖曳或點選兩格可交換版型位置。
                尚未選擇的相機以虛位顯示。
              </p>
            ) : (
              <p className="hint" style={{ marginTop: 10 }}>
                點擊下方「📁 資料夾」為每台相機選擇照片資料夾，縮圖會自動載入。
              </p>
            )}

            <div style={{ marginTop: 14, maxWidth: 220 }}>
              <label className="label">時間容差（秒）</label>
              <input
                type="number"
                className="field mono"
                min="0.5"
                max="10"
                step="0.5"
                value={tolerance}
                onChange={(e) => setTolerance(parseFloat(e.target.value) || 2)}
              />
              <p className="hint">預設 2.0 秒；EXIF 為秒級解析度，一般不需調整。</p>
            </div>

            {error && <p className="err-text">{error}</p>}
            {busy && progress && (
              <div style={{ marginTop: 12 }}>
                <div className="hint" style={{ marginBottom: 4 }}>
                  正在讀取照片 EXIF：{progress.done} / {progress.total} 張（可離開頁面，背景會繼續）
                </div>
                <div style={{ height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${progress.total ? Math.round((progress.done / progress.total) * 100) : 0}%`,
                      background: 'var(--amber, #ffb300)',
                      transition: 'width 0.6s ease',
                    }}
                  />
                </div>
              </div>
            )}
            <div className="wiz-actions">
              <button type="button" className="btn" onClick={() => setStep(1)}>上一步</button>
              <button
                type="button"
                className="btn primary"
                disabled={!cameras.every((c) => c.name.trim() && c.folder.trim()) || busy}
                onClick={runPreview}
              >
                {busy ? (progress ? `掃描中 ${progress.done}/${progress.total}…` : '準備中…') : '執行對齊分析'}
              </button>
            </div>
          </section>
        )}

        {unify && (
          <UnifyDialog
            tunnelId={unify.tid}
            items={unify.items}
            onClose={() => onDone(unify.tid, name.trim())}
            onApplied={() => onDone(unify.tid, name.trim())}
          />
        )}

        {step === 3 && preview && (
          <section>
            <div className="pv-stats">
              <Stat label="群組數" value={preview.group_count} />
              <Stat label="照片總數" value={preview.cameras.reduce((a, c) => a + c.photo_count, 0)} />
              <Stat label="待檢查" value={preview.flagged_count} warn={preview.flagged_count > 0} />
            </div>

            <table className="pv-table">
              <thead><tr><th>視角</th><th>張數</th><th>Δt</th></tr></thead>
              <tbody>
                {preview.cameras.map((c, i) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td className="mono">{c.photo_count}</td>
                    <td className="mono">{i === 0 ? '基準' : `${c.offset_seconds >= 0 ? '+' : ''}${Number(c.offset_seconds).toFixed(2)}s`}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div style={{ marginTop: 16 }}>
              <span className="label">缺照分佈（缺照台數 → 群組數）</span>
              <div className="dist-row">
                {Object.entries(preview.missing_distribution).map(([m, n]) => (
                  <span key={m} className={`chip ${Number(m) > 0 ? 'red' : 'blue'}`}>缺 {m} 台 × {n} 群</span>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10 }}>
              <button
                type="button"
                className="btn small"
                onClick={() => {
                  const next = displayOrder === 'asc' ? 'desc' : 'asc'
                  setDisplayOrder(next)
                  localStorage.setItem('tv_display_order', next)
                }}
              >⇅ {displayOrder === 'asc' ? '小→大' : '大→小'}</button>
              <span className="hint" style={{ margin: 0 }}>僅顯示切換，不影響儲存與錨點</span>
            </div>
            <p className="hint" style={{ marginTop: 8 }}>
              初始推算里程：{displayOrder === 'asc'
                ? `${formatMileage(Math.min(startM, endM))} ～ ${formatMileage(Math.max(startM, endM))}`
                : `${formatMileage(Math.max(startM, endM))} ～ ${formatMileage(Math.min(startM, endM))}`}。
              建立後可隨時輸入實體里程牌錨點即時修正。
            </p>
            {error && <p className="err-text">{error}</p>}
            <div className="wiz-actions">
              <button type="button" className="btn" onClick={() => { setStep(2); setPreview(null) }}>上一步</button>
              <button type="button" className="btn primary" disabled={busy} onClick={commit}>
                {busy ? '建立中…' : '確認建立隧道'}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, warn }) {
  return (
    <div className="stat panel">
      <span className="label">{label}</span>
      <b className={`mono stat-v ${warn ? 'warn' : ''}`}>{value}</b>
    </div>
  )
}
