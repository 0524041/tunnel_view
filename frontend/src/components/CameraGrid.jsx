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
import { resolveLayout } from '../lib/layout'

export default function CameraGrid({
  tunnelId,
  group,
  cameras,
  cameraMeta = [],
  layoutCols = 'auto',
  fit = 'contain',
  anomalyPaths,
  highlightPhotoId,
  onOpenOriginal,
  onRotate,
}) {
  const [view, setView] = useState({ s: 1, nx: 0, ny: 0 })

  if (!group) {
    return (
      <div className="cgrid-loading"><div className="spin" /></div>
    )
  }

  const byCam = new Map(group.photos.map((p) => [p.camera_seq, p]))
  const meta =
    cameraMeta.length > 0
      ? cameraMeta.map((c) => ({ ...c }))
      : cameras.map((name, seq) => ({ seq, name, grid_pos: -1, rotation: 0 }))

  const { colsNum, cells } = resolveLayout(meta, layoutCols)

  const renderCell = (cam, i) => {
    const name = cam?.name ?? ''
    const photo = cam ? byCam.get(cam.seq) : null

    const emptyTile = (
      <div key={`cell-${i}`} className={`tile tile-missing ${cam ? '' : 'tile-slot'}`}>
        <div className="miss-icon">{cam ? '⚠' : '·'}</div>
        <div>{cam ? '無影像' : '空位'}</div>
        <div className="hint">{cam ? '快門未觸發／缺照' : `格位 ${i + 1}`}</div>
        {cam && <span className="chip cam-chip">{name}</span>}
      </div>
    )

    if (!cam || !photo) return emptyTile

    return (
      <PhotoTile
        key={`${group.seq}-${cam.seq}`}
        tunnelId={tunnelId}
        photo={photo}
        name={name}
        highlighted={photo.photo_id === highlightPhotoId}
        view={view}
        onView={setView}
        showRotate={
          anomalyPaths?.has(`${cam.seq}:${photo.rel_path}`) &&
          photo.rotation_override == null
        }        onOpenOriginal={onOpenOriginal}
        onRotate={onRotate}
        fit={fit}
      />
    )
  }

  return (
    <div
      className={`cgrid fit-${fit}`}
      data-tour="viewer-grid"
      style={{ gridTemplateColumns: `repeat(${colsNum}, minmax(0, 1fr))` }}
    >
      {cells.map((cam, i) => renderCell(cam, i))}
    </div>
  )
}

function PhotoTile({ tunnelId, photo, name, highlighted, view, onView, showRotate, onOpenOriginal, onRotate, fit }) {
  const ref = useRef(null)
  const [loaded, setLoaded] = useState(false)
  const dragRef = useRef(null)

  const applyZoomAt = (px, py, factor) => {
    onView((v) => {
      const s2 = Math.max(1, Math.min(10, v.s * factor))
      if (s2 === v.s && factor > 1) return v
      const k = s2 / v.s
      let nx = px - k * (px - v.nx)
      let ny = py - k * (py - v.ny)
      nx = Math.max(1 - s2, Math.min(0, nx))
      ny = Math.max(1 - s2, Math.min(0, ny))
      return s2 === 1 ? { s: 1, nx: 0, ny: 0 } : { s: s2, nx, ny }
    })
  }

  const applyZoomAtRef = useRef(applyZoomAt)
  applyZoomAtRef.current = applyZoomAt

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const handler = (e) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const px = (e.clientX - rect.left) / rect.width
      const py = (e.clientY - rect.top) / rect.height
      applyZoomAtRef.current(px, py, Math.exp(-e.deltaY * 0.0016))
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = {
      x: e.clientX,
      y: e.clientY,
      rect: ref.current.getBoundingClientRect(),
      start: view,
      moved: false,
    }
  }

  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d || d.start.s <= 1) return
    const dx = (e.clientX - d.x) / d.rect.width
    const dy = (e.clientY - d.y) / d.rect.height
    if (Math.abs(dx) + Math.abs(dy) > 0.004) d.moved = true
    onView({
      s: d.start.s,
      nx: Math.max(1 - d.start.s, Math.min(0, d.start.nx + dx)),
      ny: Math.max(1 - d.start.s, Math.min(0, d.start.ny + dy)),
    })
  }

  const onPointerUp = () => {
    const wasMoved = dragRef.current?.moved
    dragRef.current = null
    if (!wasMoved && onOpenOriginal) {
      onOpenOriginal(photo)
    }
  }

  // 旋轉語義＝疊加：override 是相機旋轉之外的「相對修正」，
  // 單張按鈕送出的新 override = 現有 override +90（不含相機角）
  const nextOverride = ((photo.rotation_override ?? 0) + 90) % 360

  return (
    <div
      ref={ref}
      className={`tile ${highlighted ? 'tile-flash' : ''}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={() => onView({ s: 1, nx: 0, ny: 0 })}
      style={{ cursor: 'zoom-in', touchAction: 'none' }}
    >
      {!loaded && <div className="tile-spin"><div className="spin" /></div>}
      <img
        className={`tile-img ${loaded ? 'on' : ''}`}
        src={api.photoUrl(tunnelId, photo.photo_id, 1600, photo)}
        alt={name}
        draggable={false}
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(true)}
        style={{
          objectFit: fit,
          transform: `translate(${view.nx * 100}%, ${view.ny * 100}%) scale(${view.s})`,
          transformOrigin: '0 0',
        }}
      />
      <span className="chip cam-chip">{name}</span>
      {photo.anomaly_types?.length > 0 && (
        <div className="ano-tags">
          {photo.anomaly_types.map((t) => (
            <span key={t} className="chip ano-tag">{t}</span>
          ))}
        </div>
      )}
      {photo.aspect_anomaly === 1 && <span className="chip amber aspect-chip">比例</span>}
      {showRotate && (
        <button
          type="button"
          className="rotate-btn"
          title="比例異常——點擊旋轉 90°"
          onClick={(e) => {
            e.stopPropagation()
            onRotate?.(photo.photo_id, nextOverride)
          }}
        >⟳</button>
      )}
    </div>
  )
}
