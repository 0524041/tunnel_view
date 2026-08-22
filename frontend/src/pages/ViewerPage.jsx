import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { toast } from '../lib/toast'
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
  const [railTab, setRailTab] = useState(() => localStorage.getItem('tv_rail_tab') || 'anchors')
  const [railMode, setRailMode] = useState(
    () => localStorage.getItem('tv_rail_mode') || (window.innerWidth < 1280 ? 'mini' : 'open'),
  )
  const [fit, setFit] = useState(() => localStorage.getItem('tv_fit') || 'contain')
  const [reviewOpen, setReviewOpen] = useState(false)
  const [origView, setOrigView] = useState(null)

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
    if (['realigned', 'merged', 'camera_updated', 'layout_updated'].includes(msg.type)) {
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
        new Image().src = api.photoUrl(tunnelId, p.photo_id, 1600, p)
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
      if (origView || dialogOpen || searchOpen || reviewOpen) return
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

  const setRail = (patch) => {
    setRailTab((prevTab) => patch.tab ?? prevTab)
    setRailMode((prevMode) => {
      const next = patch.mode ?? prevMode
      localStorage.setItem('tv_rail_mode', next)
      return next
    })
    if (patch.tab) localStorage.setItem('tv_rail_tab', patch.tab)
  }

  if (!ov) {
    return (
      <div className="viewer-loading"><div className="spin" /></div>
    )
  }

  const group = groups.get(current) ?? null
  const anchoredHere = ov.groups.anchored[current]
  const cameraMeta = info?.cameras ?? []
  const layoutCols = info?.layout_cols ?? 'auto'

  return (
    <div className="viewer">
      <div className="vtop">
        <button type="button" className="btn small" onClick={() => setSearchOpen(true)}>
          搜尋里程 <kbd className="mono">Ctrl G</kbd>
        </button>
        <button
          type="button"
          className="btn small"
          title="照片呈現模式：完整（contain）／填滿（cover）"
          onClick={() => {
            const next = fit === 'contain' ? 'cover' : 'contain'
            setFit(next)
            localStorage.setItem('tv_fit', next)
          }}
        >
          {fit === 'contain' ? '▭ 完整' : '▩ 填滿'}
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
        <button type="button" className="btn small" onClick={() => setReviewOpen(true)}>檢閱邊界（M）</button>
        <button
          type="button"
          className={`btn small ${railTab === 'anchors' && railMode !== 'hidden' ? 'primary' : ''}`}
          onClick={() => setRail(railTab === 'anchors' && railMode === 'open' ? { mode: 'hidden' } : { tab: 'anchors', mode: 'open' })}
        >錨點列</button>
        <button
          type="button"
          className={`btn small ${railTab === 'info' && railMode !== 'hidden' ? 'primary' : ''}`}
          onClick={() => setRail(railTab === 'info' && railMode === 'open' ? { mode: 'hidden' } : { tab: 'info', mode: 'open' })}
        >
          資訊{info?.flagged?.length ? ` (${info.flagged.length}⚠)` : ''}
        </button>
      </div>

      <div className="vmid">
        <CameraGrid
          tunnelId={tunnelId}
          group={group}
          cameras={ov.cameras}
          cameraMeta={cameraMeta}
          layoutCols={layoutCols}
          fit={fit}
          anomalyPaths={anomalyPaths(info)}
          onOpenOriginal={(photo) => openOriginal(photo)}
          onRotate={(pid, angle) =>
            api.setPhotoRotation(tunnelId, pid, angle)
              .then(refreshMeta)
              .then(() => toast('已旋轉'))
              .catch((e) => toast(e.message, 'err'))
          }
        />
        {railMode !== 'hidden' && (
          <div className={`siderail ${railMode}`}>
            <div className="siderail-tabs">
              <button type="button" className={railTab === 'anchors' ? 'on' : ''} onClick={() => setRail({ tab: 'anchors', mode: 'open' })}>⚓</button>
              <button type="button" className={railTab === 'info' ? 'on' : ''} onClick={() => setRail({ tab: 'info', mode: 'open' })}>ℹ</button>
              {railMode === 'open' && (
                <>
                  {info?.flagged?.length > 0 && railTab === 'info' && (
                    <span className="chip amber rail-badge">{info.flagged.length}</span>
                  )}
                  <span className="vspacer" />
                  <button type="button" title="收合" onClick={() => setRail({ mode: 'mini' })}>»</button>
                </>
              )}
              {railMode === 'mini' && <button type="button" title="展開" onClick={() => setRail({ mode: 'open' })}>«</button>}
              <button type="button" title="隱藏" onClick={() => setRail({ mode: 'hidden' })}>×</button>
            </div>
            <div className="siderail-body">
              {railTab === 'anchors' ? (
                <AnchorDrawer
                  open
                  anchors={anchors}
                  current={current}
                  onJump={(s) => goto(s)}
                  onDelete={(s) =>
                    api.deleteAnchor(tunnelId, s)
                      .then(() => toast('錨點已刪除'))
                      .then(refreshMeta)
                      .catch((e) => toast(e.message, 'err'))
                  }
                />
              ) : (
                <TunnelInfoPanel
                  tunnelId={tunnelId}
                  info={info}
                  onChanged={refreshMeta}
                  onJump={jumpFromFlag(goto)}
                  onJumpSeq={goto}
                  currentGroupCount={ov.group_count}
                />
              )}
            </div>
          </div>
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

function jumpFromFlag(goto) {
  return (kind, item) => {
    if (kind === 'flag' && item?.group_seq != null) {
      goto(item.group_seq)
      return
    }
    if (item?.photo_id) {
      // fallback：以快取搜尋所在群組
      return
    }
  }
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

function anomalyPaths(info) {
  const names = new Map((info?.cameras ?? []).map((c) => [c.name, c.seq]))
  return new Set(
    (info?.report?.aspect_anomalies ?? [])
      .map((a) => `${names.get(a.camera)}:${a.rel_path}`)
      .filter((k) => !k.startsWith('undefined')),
  )
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
