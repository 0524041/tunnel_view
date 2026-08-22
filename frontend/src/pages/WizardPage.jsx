import { useState } from 'react'
import { api } from '../lib/api'
import { parseMileage, formatMileage } from '../lib/mileage'
import FsBrowser from '../components/FsBrowser'
import LayoutEditor from '../components/LayoutEditor'

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
  const [error, setError] = useState('')

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
        setThumbs((t) => ({ ...t, [seq]: api.fsPhotoUrl(`${d.path}/${d.sample}`) }))
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
    try {
      setPreview(
        await api.previewImport({
          name: name.trim(),
          start_m: startM,
          end_m: endM,
          tolerance_seconds: tolerance,
          layout_cols: layoutCols,
          cameras,
        }),
      )
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
      const r = await api.createTunnel({
        name: name.trim(),
        start_m: startM,
        end_m: endM,
        tolerance_seconds: tolerance,
        layout_cols: layoutCols,
        cameras,
      })
      onDone(r.tunnel_id, name.trim())
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="wizard wizard-wide">
      <div className="wiz-head">
        <span className="display wiz-title">建立新隧道</span>
        <div className="wiz-steps mono">
          {['基本設定', '相機與版型', '對齊預覽'].map((s, i) => (
            <span key={s} className={`wstep ${step >= i + 1 ? 'on' : ''}`}>
              <b>{i + 1}</b> {s}
            </span>
          ))}
        </div>
      </div>

      <div className="wiz-body panel">
        {step === 1 && (
          <section>
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
            <div className="wiz-actions">
              <button type="button" className="btn" onClick={() => setStep(1)}>上一步</button>
              <button
                type="button"
                className="btn primary"
                disabled={!cameras.every((c) => c.name.trim() && c.folder.trim()) || busy}
                onClick={runPreview}
              >
                {busy ? '分析中…' : '執行對齊分析'}
              </button>
            </div>
          </section>
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

            <p className="hint" style={{ marginTop: 14 }}>
              初始推算里程：{formatMileage(startM)} ～ {formatMileage(endM)}。
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
