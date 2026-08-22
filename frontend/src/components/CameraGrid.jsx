import { useRef, useState } from 'react'
import { api } from '../lib/api'

const LAYOUTS = {
  1: [1, 1],
  2: [2, 1],
  3: [3, 1],
  4: [2, 2],
  5: [3, 2],
  6: [3, 2],
  7: [4, 2],
  8: [4, 2],
}

const clampF = (f, s) => Math.max(1 - s, Math.min(0, f))

export default function CameraGrid({ tunnelId, group, cameras, anomalyPaths, onOpenOriginal, onRotate }) {
  const n = cameras.length
  const [cols, rows] = LAYOUTS[n] ?? [4, 2]
  const [view, setView] = useState({ s: 1, nx: 0, ny: 0 })

  if (!group) {
    return (
      <div className="cgrid-loading"><div className="spin" /></div>
    )
  }

  const byCam = new Map(group.photos.map((p) => [p.camera_seq, p]))

  return (
    <div
      className="cgrid"
      style={{ gridTemplateColumns: `repeat(${cols}, 1fr)`, gridTemplateRows: `repeat(${rows}, 1fr)` }}
    >
      {cameras.map((name, i) => {
        const photo = byCam.get(i)
        return photo ? (
          <PhotoTile
            key={`${group.seq}-${i}`}
            tunnelId={tunnelId}
            photo={photo}
            name={name}
            flagged={!!photo.flagged}
            view={view}
            onView={setView}
            showRotate={anomalyPaths?.has(`${i}:${photo.rel_path}`) && photo.rotation_override == null}
            onOpenOriginal={onOpenOriginal}
            onRotate={onRotate}
          />
        ) : (
          <div key={`miss-${group.seq}-${i}`} className="tile tile-missing">
            <div className="miss-icon">⚠</div>
            <div>無影像</div>
            <div className="hint">快門未觸發／缺照</div>
            <span className="chip cam-chip">{name}</span>
          </div>
        )
      })}
    </div>
  )
}

function PhotoTile({ tunnelId, photo, name, flagged, view, onView, showRotate, onOpenOriginal, onRotate }) {
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
      nx = clampF(nx, s2)
      ny = clampF(ny, s2)
      return s2 === 1 ? { s: 1, nx: 0, ny: 0 } : { s: s2, nx, ny }
    })
  }

  const onWheel = (e) => {
    e.preventDefault()
    const rect = ref.current.getBoundingClientRect()
    const px = (e.clientX - rect.left) / rect.width
    const py = (e.clientY - rect.top) / rect.height
    applyZoomAt(px, py, Math.exp(-e.deltaY * 0.0016))
  }

  const onPointerDown = (e) => {
    if (view.s <= 1) return
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
    if (!d) return
    const dx = (e.clientX - d.x) / d.rect.width
    const dy = (e.clientY - d.y) / d.rect.height
    if (Math.abs(dx) + Math.abs(dy) > 0.004) d.moved = true
    onView({
      s: d.start.s,
      nx: clampF(d.start.nx + dx, d.start.s),
      ny: clampF(d.start.ny + dy, d.start.s),
    })
  }

  const onPointerUp = (e) => {
    const wasMoved = dragRef.current?.moved
    dragRef.current = null
    if (!wasMoved && view.s === 1 && onOpenOriginal) {
      onOpenOriginal(photo)
    }
  }

  const effAngle = (photo.rotation_override ?? photo.camera_rotation ?? 0) % 360

  return (
    <div
      ref={ref}
      className={`tile ${flagged ? 'tile-flag' : ''}`}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={() => onView({ s: 1, nx: 0, ny: 0 })}
      style={{ cursor: view.s > 1 ? 'grab' : 'zoom-in', touchAction: 'none' }}
    >
      {!loaded && <div className="tile-spin"><div className="spin" /></div>}
      <img
        className={`tile-img ${loaded ? 'on' : ''}`}
        src={api.photoUrl(tunnelId, photo.photo_id, 1600)}
        alt={name}
        draggable={false}
        onLoad={() => setLoaded(true)}
        style={{
          transform: `translate(${view.nx * 100}%, ${view.ny * 100}%) scale(${view.s})`,
          transformOrigin: '0 0',
        }}
      />
      <span className="chip cam-chip">{name}</span>
      {flagged && <span className="chip red flag-chip">待檢查</span>}
      {showRotate && (
        <button
          type="button"
          className="rotate-btn"
          title="比例異常——點擊旋轉 90°"
          onClick={(e) => {
            e.stopPropagation()
            onRotate?.(photo.photo_id, (effAngle + 90) % 360)
          }}
        >⟳</button>
      )}
    </div>
  )
}
