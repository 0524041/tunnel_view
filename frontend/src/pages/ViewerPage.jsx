import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useTunnelSocket } from '../lib/useTunnelSocket'
import CameraGrid from '../components/CameraGrid'
import ScrubberRail from '../components/ScrubberRail'
import AnchorDrawer from '../components/AnchorDrawer'
import AnchorDialog from '../components/AnchorDialog'
import MileageSearch from '../components/MileageSearch'
import TunnelInfoPanel from '../components/TunnelInfoPanel'
import ReviewMode from '../components/ReviewMode'
import OriginalViewer from '../components/OriginalViewer'

export default function ViewerPage({ tunnelId, active }) {
  const [ov, setOv] = useState(null)
  const [info, setInfo] = useState(null)
  const [anchors, setAnchors] = useState([])
  const [current, setCurrent] = useState(0)
  const [groups, setGroups] = useState(() => new Map())
  const cacheRef = useRef(new Map())
  const pendingRef = useRef(new Set())
  const [dialogOpen, setDialogOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [panel, setPanel] = useState('anchors') // 'anchors' | 'info' | 'none'
  const [reviewOpen, setReviewOpen] = useState(false)
  const [origView, setOrigView] = useState(null) // { photos: [...decorated], index }

  const refreshMeta = useCallback(() => {
    api.overview(tunnelId).then(setOv).catch(() => {})
    api.anchors(tunnelId).then(setAnchors).catch(() => {})
    api.info(tunnelId).then(setInfo).catch(() => {})
  }, [tunnelId])

  useEffect(() => {
    setCurrent(0)
    cacheRef.current.clear()
    pendingRef.current.clear()
    setGroups(new Map())
    api.overview(tunnelId).then(setOv).catch(() => {})
    api.anchors(tunnelId).then(setAnchors).catch(() => {})
    api.info(tunnelId).then(setInfo).catch(() => {})
    ensureWindow(tunnelId, 0, cacheRef.current, pendingRef.current, setGroups)
  }, [tunnelId])

  useTunnelSocket(tunnelId, (msg) => {
    if (!msg.type) return
    refreshMeta()
    if (['realigned', 'merged'].includes(msg.type)) {
      cacheRef.current.clear()
      pendingRef.current.clear()
      setGroups(new Map())
      ensureWindow(tunnelId, current, cacheRef.current, pendingRef.current, setGroups)
    }
  })

  const total = ov?.group_count ?? 0

  useEffect(() => {
    if (!total) return
    ensureWindow(tunnelId, current, cacheRef.current, pendingRef.current, setGroups)
  }, [current, total, tunnelId])

  const goto = useCallback(
    (seq) => {
      if (!total) return
      setCurrent(Math.max(0, Math.min(total - 1, seq)))
    },
    [total],
  )

  useEffect(() => {
    if (!ov || !active) return
    const nxt = groups.get(current + 1)
    if (nxt) {
      for (const p of nxt.photos) {
        new Image().src = api.photoUrl(tunnelId, p.photo_id, 1600)
      }
    }
  }, [current, groups, ov, active, tunnelId])

  const openOriginal = useCallback(
    (photo) => {
      const g = groups.get(current)
      if (!g) return
      const decorated = g.photos.map((p) => ({
        ...p,
        __cameraName: ov.cameras[p.camera_seq],
        __groupSeq: g.seq,
      }))
      const index = Math.max(0, decorated.findIndex((p) => p.photo_id === photo.photo_id))
      setOrigView({ photos: decorated, index })
    },
    [groups, current, ov],
  )

  const jumpFromFlag = useCallback(
    (kind, item) => {
      if (kind === 'flag' && item?.photo_id) {
        for (const [seq, g] of cacheRef.current.entries()) {
          if (g.photos.some((p) => p.photo_id === item.photo_id)) {
            goto(seq)
            return
          }
        }
      }
      refreshMeta()
    },
    [goto, refreshMeta],
  )

  const anomalyPaths = (() => {
    const names = new Map((info?.cameras ?? []).map((c) => [c.name, c.seq]))
    return new Set(
      (info?.report?.aspect_anomalies ?? [])
        .map((a) => `${names.get(a.camera)}:${a.rel_path}`)
        .filter((k) => !k.startsWith('undefined')),
    )
  })()

  useEffect(() => {
    if (!active || !ov) return
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setOrigView(null)
        setReviewOpen(false)
        setDialogOpen(false)
        setSearchOpen(false)
        return
      }
      if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'g') {
        e.preventDefault()
        setSearchOpen(true)
        return
      }
      if (origView || dialogOpen || searchOpen) return
      if (reviewOpen) return
      if (e.key === 'ArrowLeft') goto(current - 1)
      else if (e.key === 'ArrowRight') goto(current + 1)
      else if (e.key === 'Home') goto(0)
      else if (e.key === 'End') goto(total - 1)
      else if (e.key === 'Enter') setDialogOpen(true)
      else if (e.key.toLowerCase() === 'm') setReviewOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, ov, origView, dialogOpen, searchOpen, reviewOpen, current, total, goto])

  if (!ov) {
    return (
      <div className="viewer-loading"><div className="spin" /></div>
    )
  }

  const group = groups.get(current) ?? null
  const anchoredHere = ov.groups.anchored[current]

  return (
    <div className="viewer">
      <div className="vtop">
        <button type="button" className="btn small" onClick={() => setSearchOpen(true)}>
          搜尋里程 <kbd className="mono">Ctrl G</kbd>
        </button>
        <div className="vread mono">
          <span className="vread-seq">
            群組 <b>{String(current + 1).padStart(4, '0')}</b> / {ov.group_count}
          </span>
          <span className={`vread-mile ${anchoredHere ? 'lock' : ''}`}>
            {anchoredHere ? '' : '~'}
            {estOf(ov, group, current)}
          </span>
          {anchoredHere && <span className="chip blue">🔒 已錨定</span>}
        </div>
        <div className="vspacer" />
        <button type="button" className="btn small" onClick={() => setReviewOpen(true)}>
          檢閱邊界（M）
        </button>
        <button
          type="button"
          className={`btn small ${panel === 'anchors' ? 'primary' : ''}`}
          onClick={() => setPanel((p) => (p === 'anchors' ? 'none' : 'anchors'))}
        >
          錨點列 ({anchors.length})
        </button>
        <button
          type="button"
          className={`btn small ${panel === 'info' ? 'primary' : ''}`}
          onClick={() => setPanel((p) => (p === 'info' ? 'none' : 'info'))}
        >
          資訊{info?.flagged?.length ? ` (${info.flagged.length}⚠)` : ''}
        </button>
      </div>

      <div className="vmid">
        <CameraGrid
          tunnelId={tunnelId}
          group={group}
          cameras={ov.cameras}
          anomalyPaths={anomalyPaths}
          onOpenOriginal={(photo) => openOriginal(photo)}
          onRotate={(pid, angle) =>
            api.setPhotoRotation(tunnelId, pid, angle).then(refreshMeta)
          }
        />
        {panel === 'anchors' ? (
          <AnchorDrawer
            open
            anchors={anchors}
            current={current}
            onJump={(seq) => goto(seq)}
            onDelete={(s) => api.deleteAnchor(tunnelId, s).then(refreshMeta).catch(() => {})}
          />
        ) : (
          panel === 'info' && (
            <TunnelInfoPanel
              tunnelId={tunnelId}
              info={info}
              onChanged={refreshMeta}
              onJump={jumpFromFlag}
              onJumpSeq={goto}
            />
          )
        )}
      </div>

      <ScrubberRail
        est={ov.groups.est}
        missing={ov.groups.missing}
        anchored={ov.groups.anchored}
        anomaly={ov.groups.anomaly}
        startM={ov.start_m}
        endM={ov.end_m}
        current={current}
        onJump={goto}
      />

      <div className="vhint hint">
        ←/→ 群組 · Enter 錨點 · M 檢閱邊界 · Home/End 首/末 · 點照片開原圖 · Ctrl+G 跳轉
      </div>

      {dialogOpen && (
        <AnchorDialog
          tunnelId={tunnelId}
          seq={current}
          initial={group ? group.est_mileage_m : null}
          prevAnchor={nearestAnchor(anchors, current, -1)}
          nextAnchor={nearestAnchor(anchors, current, 1)}
          onClose={() => setDialogOpen(false)}
        />
      )}

      {searchOpen && (
        <MileageSearch
          onJump={(m) => {
            api.nearestByMileage(tunnelId, m).then((h) => {
              goto(h.seq)
              setSearchOpen(false)
            })
          }}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {reviewOpen && (
        <ReviewMode
          tunnelId={tunnelId}
          current={current}
          cameras={ov.cameras}
          onClose={() => setReviewOpen(false)}
          onChanged={refreshMeta}
        />
      )}

      {origView && (
        <OriginalViewer
          tunnelId={tunnelId}
          photos={origView.photos}
          startIndex={origView.index}
          onClose={() => setOrigView(null)}
        />
      )}
    </div>
  )
}

function estOf(ov, group, current) {
  const m = ov?.groups?.est?.[current] ?? group?.est_mileage_m
  if (!Number.isFinite(m)) return '—'
  return `K${Math.floor(m / 1000)}+${String(m % 1000).padStart(3, '0')}`
}

function nearestAnchor(anchors, seq, dir) {
  const list = anchors.filter((a) => (dir > 0 ? a.group_seq > seq : a.group_seq < seq))
  if (!list.length) return null
  return dir > 0 ? list[0] : list[list.length - 1]
}

async function ensureWindow(tunnelId, around, cache, pending, setGroups) {
  if (cache.has(around) || pending.has(around)) return
  pending.add(around)
  try {
    const rows = await api.groups(tunnelId, Math.max(around, 6), 6, 14)
    for (const g of rows) cache.set(g.seq, g)
    setGroups(new Map(cache))
  } catch {
  } finally {
    pending.delete(around)
  }
}
