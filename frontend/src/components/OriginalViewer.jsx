import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

const clampF = (f) => Math.max(-3, Math.min(3, f))

export default function OriginalViewer({ tunnelId, photos, startIndex, onClose }) {
  const [idx, setIdx] = useState(startIndex)
  const [view, setView] = useState({ z: 1, nx: 0, ny: 0 })
  const [angleOverride, setAngleOverride] = useState(null)
  const [version, setVersion] = useState(0)
  const containerRef = useRef(null)
  const dragRef = useRef(null)

  const applyZoomAt = (px, py, factor) => {
    setView((v) => {
      const z2 = Math.max(1, Math.min(8, v.z * factor))
      if (z2 === v.z && factor > 1) return v
      const k = z2 / v.z
      let nx = px - k * (px - v.nx)
      let ny = py - k * (py - v.ny)
      return { z: z2, nx: clampF(nx), ny: clampF(ny) }
    })
  }

  const applyZoomAtRef = useRef(applyZoomAt)
  applyZoomAtRef.current = applyZoomAt

  useEffect(() => {
    setView({ z: 1, nx: 0, ny: 0 })
    setAngleOverride(null)
  }, [idx])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const handler = (e) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const px = (e.clientX - rect.left) / rect.width
      const py = (e.clientY - rect.top) / rect.height
      applyZoomAtRef.current(px, py, Math.exp(-e.deltaY * 0.002))
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  const photo = photos[idx]
  if (!photo) return null

  const effAngle = (angleOverride ?? photo.rotation_override ?? photo.camera_rotation ?? 0) % 360
  const noExif = photo.time_source === 'mtime'

  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { x: e.clientX, y: e.clientY, start: view }
  }

  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) return
    const dx = (e.clientX - d.x) / containerRef.current.clientWidth
    const dy = (e.clientY - d.y) / containerRef.current.clientHeight
    setView({ z: d.start.z, nx: clampF(d.start.nx + dx), ny: clampF(d.start.ny + dy) })
  }

  const onPointerUp = () => {
    dragRef.current = null
  }

  const cyclePhoto = (d) => {
    setIdx((i) => (i + d + photos.length) % photos.length)
  }

  const rotateCurrent = () => {
    const next = (effAngle + 90) % 360
    api
      .setPhotoRotation(tunnelId, photo.photo_id, next)
      .then(() => {
        setAngleOverride(next)
        setVersion((v) => v + 1)
      })
      .catch(() => {})
  }

  const onKeyDown = (e) => {
    e.stopPropagation()
    if (e.key === 'Escape') onClose()
    else if (e.key === 'Tab') {
      e.preventDefault()
      cyclePhoto(e.shiftKey ? -1 : 1)
    } else if (e.key.toLowerCase() === 'r') rotateCurrent()
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') cyclePhoto(e.key === 'ArrowRight' ? 1 : -1)
  }

  return (
    <div className="orig-overlay" onKeyDown={onKeyDown} tabIndex={-1}>
      <div className="orig-head mono">
        <span className="list-main">{photo.rel_path}</span>
        <span className="chip blue">{Math.round(view.z * 100)}%</span>
        <div className="row-actions">
          <button type="button" className="btn small" onClick={rotateCurrent}>⟳ 旋轉（R）</button>
          <button type="button" className="btn small" onClick={onClose}>關閉（Esc）</button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="orig-stage"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDoubleClick={() => setView((v) => (v.z === 1 ? { z: 2, nx: 0, ny: 0 } : { z: 1, nx: 0, ny: 0 }))}
      >
        <img
          key={`${photo.photo_id}-${version}`}
          src={`${api.photoUrl(tunnelId, photo.photo_id)}?cr=${photo.camera_rotation ?? 0}&pr=${angleOverride ?? photo.rotation_override ?? -1}&v=${version}`}
          alt=""
          draggable={false}
          style={{
            transform: `translate(${view.nx * 100}%, ${view.ny * 100}%) scale(${view.z})`,
            transformOrigin: '0 0',
          }}
        />
      </div>

      <div className="orig-exif mono">
        <span className={`chip ${noExif ? 'red' : 'blue'}`}>{noExif ? '⚠ 無 EXIF（檔案時間）' : 'EXIF'}</span>
        <span>原始：{photo.exif_time || '—'}</span>
        <span className="arrow">→</span>
        <span className="hl">對齊：{photo.corrected_time || '—'}</span>
        <span className="hint">{`群組 #${String(photo.__groupSeq + 1).padStart(4, '0')} · ${photo.__cameraName}`}</span>
      </div>

      <div className="orig-foot hint">
        滾輪縮放 · 拖曳平移 · 雙擊 100%／適合 · Tab 切換視角 · R 旋轉 · Esc 關閉
      </div>
    </div>
  )
}
