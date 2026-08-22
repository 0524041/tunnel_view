import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

const clampF = (f) => Math.max(-3, Math.min(3, f))

export default function OriginalViewer({ tunnelId, photos, startIndex, onClose }) {
  const [idx, setIdx] = useState(startIndex)
  const [view, setView] = useState({ z: 1, nx: 0, ny: 0 })
  const [version, setVersion] = useState(0)
  const containerRef = useRef(null)
  const dragRef = useRef(null)
  const photo = photos[idx]

  useEffect(() => {
    setView({ z: 1, nx: 0, ny: 0 })
  }, [idx])

  const effAngle = (photo?.rotation_override ?? photo?.camera_rotation ?? 0) % 360

  const applyZoomAt = (px, py, factor) => {
    setView((v) => {
      const z2 = Math.max(1, Math.min(8, v.z * factor))
      if (z2 === v.z && factor > 1) return v
      const k = z2 / v.z
      let nx = px - k * (px - v.nx)
      let ny = py - k * (py - v.ny)
      nx = clampF(nx)
      ny = clampF(ny)
      return { z: z2, nx, ny }
    })
  }

  const onWheel = (e) => {
    e.preventDefault()
    const rect = containerRef.current.getBoundingClientRect()
    const px = (e.clientX - rect.left) / rect.width
    const py = (e.clientY - rect.top) / rect.height
    applyZoomAt(px, py, Math.exp(-e.deltaY * 0.002))
  }

  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { x: e.clientX, y: e.clientY, start: view, moved: false }
  }

  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) return
    const dx = (e.clientX - d.x) / containerRef.current.clientWidth
    const dy = (e.clientY - d.y) / containerRef.current.clientHeight
    if (Math.abs(dx) + Math.abs(dy) > 0.005) d.moved = true
    setView({ z: d.start.z, nx: clampF(d.start.nx + dx), ny: clampF(d.start.ny + dy) })
  }

  const cyclePhoto = (d) => {
    setIdx((i) => (i + d + photos.length) % photos.length)
  }

  const rotateCurrent = () => {
    const next = ((photo.rotation_override ?? photo.camera_rotation ?? 0) + 90) % 360
    api.setPhotoRotation(tunnelId, photo.photo_id, next).then(() => setVersion((v) => v + 1))
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
        <span>{photo ? `${photo.__cameraName} · 群組 #${String(photo.__groupSeq + 1).padStart(4, '0')}` : ''}</span>
        <span className="hint">{Math.round(view.z * 100)}% · 原始解析度</span>
        <div className="row-actions">
          <button type="button" className="btn small" onClick={rotateCurrent}>⟳ 旋轉（R）</button>
          <button type="button" className="btn small" onClick={onClose}>關閉（Esc）</button>
        </div>
      </div>
      <div
        ref={containerRef}
        className="orig-stage"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => {
          dragRef.current = null
        }}
        onDoubleClick={() => setView((v) => (v.z === 1 ? { z: 2, nx: 0, ny: 0 } : { z: 1, nx: 0, ny: 0 }))}
      >
        {photo && (
          <img
            key={`${photo.photo_id}-${version}`}
            src={`${api.photoUrl(tunnelId, photo.photo_id)}?v=${effAngle}-${version}`}
            alt=""
            draggable={false}
            style={{
              transform: `translate(${view.nx * 100}%, ${view.ny * 100}%) scale(${view.z}) rotate(${effAngle}deg)`,
              transformOrigin: '0 0',
            }}
          />
        )}
      </div>
      <div className="orig-foot hint">
        滾輪縮放 · 拖曳平移 · 雙擊 100%／適合 · Tab 切換視角 · R 旋轉 · Esc 關閉
      </div>
    </div>
  )
}
