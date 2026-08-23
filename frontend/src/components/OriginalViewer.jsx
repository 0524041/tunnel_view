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
import AnnotationEditor from './AnnotationEditor'

const clampF = (f) => Math.max(-3, Math.min(3, f))

export default function OriginalViewer({ tunnelId, photos, startIndex, onClose, onAnnotationChanged }) {
  const [idx, setIdx] = useState(startIndex)
  const [view, setView] = useState({ z: 1, nx: 0, ny: 0 })
  const [angleOverride, setAngleOverride] = useState(null)
  const [version, setVersion] = useState(0)
  const [imgError, setImgError] = useState(null)
  const [annoOpen, setAnnoOpen] = useState(false)
  const containerRef = useRef(null)
  const dragRef = useRef(null)
  const rootRef = useRef(null)

  useEffect(() => {
    rootRef.current?.focus()
  }, [])

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
    setImgError(null)
  }, [idx])

  useEffect(() => {
    setView({ z: 1, nx: 0, ny: 0 })
    setImgError(null)
  }, [version, angleOverride])

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
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
    if (e.key === 'Tab') {
      e.preventDefault()
      cyclePhoto(e.shiftKey ? -1 : 1)
    } else if (e.key.toLowerCase() === 'r') rotateCurrent()
    else if (e.key.toLowerCase() === 'a') setAnnoOpen((v) => !v)
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') cyclePhoto(e.key === 'ArrowRight' ? 1 : -1)
  }

  return (
    <div className="orig-overlay" ref={rootRef} onKeyDown={onKeyDown} tabIndex={-1}>
      <div className="orig-head mono">
        <span className="list-main">{photo.rel_path}</span>
        <span className="chip blue">{Math.round(view.z * 100)}%</span>
        <div className="row-actions">
          <button
            type="button"
            className={`btn small ${annoOpen ? 'primary' : ''}`}
            onClick={() => setAnnoOpen((v) => !v)}
          >🏷 異狀標註（A）</button>
          <button type="button" className="btn small" onClick={rotateCurrent}>⟳ 旋轉（R）</button>
          <button type="button" className="btn small" onClick={onClose}>關閉（Esc）</button>
        </div>
      </div>

      <div className="orig-mainrow">
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
            onError={(e) => {
              const msg = `載入失敗: ${e?.target?.src?.slice(0, 80)}`
              setImgError(msg)
            }}
            onLoad={() => setImgError(null)}
            style={{
              transform: `translate(${view.nx * 100}%, ${view.ny * 100}%) scale(${view.z})`,
              transformOrigin: '0 0',
            }}
          />
          {imgError && (
            <div style={{ position:'absolute', inset:0, display:'grid', placeItems:'center', background:'rgba(0,0,0,0.6)', color:'#ff4d4f', fontSize:13, padding:16, textAlign:'center' }}>
              {imgError}<br /><span style={{color:'#aaa', fontSize:11}}>請檢查網路或稍後重試（R 再轉一次可重載）</span>
            </div>
          )}
        </div>

        {annoOpen && (
          <aside className="anno-panel">
            <div className="anno-panel-head">
              <span className="label">異狀標註</span>
              <span className="hint">{photo.__cameraName} · 群組 #{String(photo.__groupSeq + 1).padStart(4, '0')}</span>
              <button type="button" className="btn small ghost" onClick={() => setAnnoOpen(false)}>✕</button>
            </div>
            <div className="anno-panel-body">
              <AnnotationEditor
                tunnelId={tunnelId}
                photoId={photo.photo_id}
                onChanged={() => onAnnotationChanged?.()}
              />
            </div>
          </aside>
        )}
      </div>

      <div className="orig-exif mono">
        <span className={`chip ${noExif ? 'red' : 'blue'}`}>{noExif ? '⚠ 無 EXIF（檔案時間）' : 'EXIF'}</span>
        <span>原始：{photo.exif_time || '—'}</span>
        <span className="arrow">→</span>
        <span className="hl">對齊：{photo.corrected_time || '—'}</span>
        <span className="hint">{`群組 #${String(photo.__groupSeq + 1).padStart(4, '0')} · ${photo.__cameraName}`}</span>
      </div>

      <div className="orig-foot hint">
        滾輪縮放 · 拖曳平移 · 雙擊復原 · Tab 切換視角 · A 異狀標註 · R 旋轉 · Esc 關閉
      </div>
    </div>
  )
}
