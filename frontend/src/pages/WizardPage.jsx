import { useState } from 'react'
import { api } from '../lib/api'
import { parseMileage, formatMileage } from '../lib/mileage'

export default function WizardPage({ onDone, onCancel }) {
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [startText, setStartText] = useState('K23+000')
  const [endText, setEndText] = useState('')
  const [tolerance, setTolerance] = useState(2)
  const [cameras, setCameras] = useState([
    { name: '頂拱左', folder: '' },
    { name: '頂拱右', folder: '' },
  ])
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const startM = parseMileage(startText)
  const endM = parseMileage(endText)

  const step1Valid =
    name.trim().length > 0 && startM !== null && endM !== null && endM !== startM

  const dirLabel =
    startM === null || endM === null ? '' : endM > startM ? '里程遞增 ⟶' : '⟵ 遞減里程'

  const nextFrom1 = () => {
    if (!step1Valid) return
    setError('')
    setStep(2)
  }

  async function runPreview() {
    setBusy(true)
    setError('')
    try {
      const p = await api.previewImport({
        name: name.trim(),
        start_m: startM,
        end_m: endM,
        tolerance_seconds: tolerance,
        cameras,
      })
      setPreview(p)
      setStep(3)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    setBusy(true)
    try {
      const r = await api.createTunnel({
        name: name.trim(),
        start_m: startM,
        end_m: endM,
        tolerance_seconds: tolerance,
        cameras,
      })
      onDone(r.tunnel_id, name.trim())
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="wizard">
      <div className="wiz-head">
        <span className="display wiz-title">建立新隧道</span>
        <div className="wiz-steps mono">
          {['基本設定', '相機資料夾', '對齊預覽'].map((s, i) => (
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
              <b className={dirLabel.includes('遞減') ? 'mono' : 'mono'} style={{ color: 'var(--amber)' }}>
                {' '}
                {dirLabel || '—'}
              </b>
            </p>

            <div className="wiz-actions">
              <button type="button" className="btn" onClick={onCancel}>取消</button>
              <button type="button" className="btn primary" disabled={!step1Valid} onClick={nextFrom1}>下一步</button>
            </div>
          </section>
        )}

        {step === 2 && (
          <section>
            <p className="hint" style={{ marginBottom: 14 }}>
              資料夾必須位於<b style={{ color: 'var(--text-hi)' }}>伺服器本機磁碟</b>，填入絕對路徑（照片原地引用，不會搬動）。
            </p>
            {cameras.map((cam, i) => (
              <div className="cam-row" key={i}>
                <input
                  className="field cam-name"
                  value={cam.name}
                  placeholder={`視角 ${i + 1}`}
                  onChange={(e) =>
                    setCameras((cs) => cs.map((c, j) => (j === i ? { ...c, name: e.target.value } : c)))
                  }
                />
                <input
                  className="field mono"
                  value={cam.folder}
                  placeholder="/data/Cam1 或 E:\Tunnel\Cam1"
                  onChange={(e) =>
                    setCameras((cs) => cs.map((c, j) => (j === i ? { ...c, folder: e.target.value } : c)))
                  }
                />
                <select
                  className="field mono cam-rot"
                  value={cam.rotation ?? 0}
                  title="機位旋轉（照片呈現方向）"
                  onChange={(e) =>
                    setCameras((cs) => cs.map((c, j) => (j === i ? { ...c, rotation: parseInt(e.target.value) } : c)))
                  }
                >
                  {[0, 90, 180, 270].map((r) => <option key={r} value={r}>{r}°</option>)}
                </select>
                <button
                  type="button"
                  className="btn danger small"
                  disabled={cameras.length <= 1}
                  onClick={() => setCameras((cs) => cs.filter((_, j) => j !== i))}
                >移除</button>
              </div>
            ))}
            <button
              type="button"
              className="btn small"
              disabled={cameras.length >= 8}
              onClick={() => setCameras((cs) => [...cs, { name: `視角 ${cs.length + 1}`, folder: '' }])}
            >＋ 新增相機</button>

            <div style={{ marginTop: 18, maxWidth: 220 }}>
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
              <thead>
                <tr><th>相機視角</th><th>照片數</th><th>時間偏移 Δt</th></tr>
              </thead>
              <tbody>
                {preview.cameras.map((c, i) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td className="mono">{c.photo_count}</td>
                    <td className="mono">
                      {i === 0 ? <span className="chip amber">基準 0.00s</span> : `${c.offset_seconds >= 0 ? '+' : ''}${c.offset_seconds.toFixed(2)}s`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div style={{ marginTop: 16 }}>
              <span className="label">缺照分佈（缺照台數 → 群組數）</span>
              <div className="dist-row">
                {Object.entries(preview.missing_distribution).map(([missing, groups]) => (
                  <span key={missing} className={`chip ${Number(missing) > 0 ? 'red' : 'blue'}`}>
                    缺 {missing} 台 × {groups} 群
                  </span>
                ))}
              </div>
            </div>

            <p className="hint" style={{ marginTop: 14 }}>
              初始推算里程將以等分建立：{formatMileage(startM)} ～ {formatMileage(endM)}。
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
