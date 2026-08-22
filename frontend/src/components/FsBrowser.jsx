import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export default function FsBrowser({ initialPath, initialRotation = 0, onPick, onClose }) {
  const [cwd, setCwd] = useState(initialPath || '')
  const [data, setData] = useState(null)
  const [rotation, setRotation] = useState(initialRotation)
  const [error, setError] = useState('')

  const load = (p) => {
    setError('')
    api.fsList(p).then(setData).catch((e) => setError(e.message))
  }

  useEffect(() => {
    load(cwd)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cwd])

  const sampleUrl = data?.sample ? api.fsPhotoUrl(`${data.path}/${data.sample}`) : null

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog fs-dialog" onKeyDown={(e) => e.stopPropagation()}>
        <span className="label">選擇相機照片資料夾（伺服器本機路徑，支援 NAS／UNC）</span>

        {(data?.roots?.length ?? 0) > 0 && (
          <div className="fs-roots">
            {data.roots.map((r) => (
              <button type="button" key={r} className="btn small mono" onClick={() => setCwd(r)}>{r}</button>
            ))}
          </div>
        )}

        {(data?.recent?.length ?? 0) > 0 && (
          <div className="fs-recent">
            <span className="label" style={{ marginBottom: 4 }}>最近使用</span>
            <div className="fs-recent-list">
              {data.recent.map((p) => (
                <button type="button" key={p} className="chip mono" title={p} onClick={() => setCwd(p)}>
                  …{p.split(/[\\/]/).filter(Boolean).slice(-1)[0] || p}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="fs-pathrow">
          <input
            className="field mono"
            value={cwd}
            onChange={(e) => setCwd(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load(cwd)}
            placeholder="/Volumes/SD 或 E:\Tunnel\Cam1 或 \\NAS\share\Cam1"
          />
          <button type="button" className="btn small" disabled={!data?.parent} onClick={() => setCwd(data.parent)}>
            ⬆ 上層
          </button>
        </div>
        {error && <p className="err-text">{error}</p>}

        <div className="fs-main">
          <div className="fs-dirs">
            {data?.dirs?.length === 0 && data?.path && <p className="hint" style={{ padding: '8px 4px' }}>沒有子資料夾</p>}
            {data?.dirs?.map((d) => (
              <button type="button" key={d} className="fs-dir mono" onClick={() => setCwd(joinPath(data.path, d))}>
                📁 {d}
              </button>
            ))}
          </div>
          <div className="fs-preview">
            <span className="label">第一張照片預覽</span>
            {sampleUrl ? (
              <div className="fs-prevbox">
                <img
                  src={sampleUrl}
                  alt=""
                  style={{ transform: `rotate(${rotation}deg)` }}
                  className={rotation % 180 !== 0 ? 'rot90' : ''}
                />
                <div className="mono hint">{rotation}°</div>
              </div>
            ) : (
              <p className="hint">{data?.path ? '此資料夾內沒有 JPG' : '請先選擇資料夾'}</p>
            )}
            <label className="label" style={{ marginTop: 10 }}>呈現方向</label>
            <select
              className="field mono"
              value={rotation}
              onChange={(e) => setRotation(parseInt(e.target.value))}
            >
              {[0, 90, 180, 270].map((r) => <option key={r} value={r}>{r}°</option>)}
            </select>
          </div>
        </div>

        <div className="wiz-actions">
          <button type="button" className="btn" onClick={onClose}>取消</button>
          <button
            type="button"
            className="btn primary"
            disabled={!data?.path}
            onClick={() => data?.path && onPick({ folder: data.path, rotation })}
          >選擇此資料夾</button>
        </div>
      </div>
    </div>
  )
}

function joinPath(base, name) {
  if (base.endsWith('/') || base.endsWith('\\')) return base + name
  return `${base}/${name}`
}
