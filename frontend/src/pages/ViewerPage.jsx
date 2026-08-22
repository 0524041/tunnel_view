import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useTunnelSocket } from '../lib/useTunnelSocket'
import CameraGrid from '../components/CameraGrid'
import ScrubberRail from '../components/ScrubberRail'
import AnchorDrawer from '../components/AnchorDrawer'
import AnchorDialog from '../components/AnchorDialog'
import MileageSearch from '../components/MileageSearch'

export default function ViewerPage({ tunnelId, active }) {
  const [ov, setOv] = useState(null)
  const [anchors, setAnchors] = useState([])
  const [current, setCurrent] = useState(0)
  const [groups, setGroups] = useState(() => new Map())
  const cacheRef = useRef(new Map())
  const pendingRef = useRef(new Set())
  const [dialogOpen, setDialogOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(true)

  const refreshMeta = useCallback(() => {
    api.overview(tunnelId).then(setOv).catch(() => {})
    api.anchors(tunnelId).then(setAnchors).catch(() => {})
  }, [tunnelId])

  useEffect(() => {
    setCurrent(0)
    cacheRef.current.clear()
    pendingRef.current.clear()
    setGroups(new Map())
    api.overview(tunnelId).then(setOv).catch(() => {})
    api.anchors(tunnelId).then(setAnchors).catch(() => {})
    ensureWindow(tunnelId, 0, cacheRef.current, pendingRef.current, setGroups)
  }, [tunnelId])

  useTunnelSocket(tunnelId, refreshMeta)

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

  useEffect(() => {
    if (!active || !ov) return
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setDialogOpen(false)
        setSearchOpen(false)
        return
      }
      if (dialogOpen || searchOpen) return
      if (e.target && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return
      if (e.key === 'ArrowLeft') goto(current - 1)
      else if (e.key === 'ArrowRight') goto(current + 1)
      else if (e.key === 'Home') goto(0)
      else if (e.key === 'End') goto(total - 1)
      else if (e.key === 'Enter') setDialogOpen(true)
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'g') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, ov, dialogOpen, searchOpen, current, total, goto])

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
        <button type="button" className="btn small" onClick={() => setDrawerOpen((o) => !o)}>
          {drawerOpen ? '隱藏錨點列' : `錨點列 (${anchors.length})`}
        </button>
      </div>

      <div className="vmid">
        <CameraGrid tunnelId={tunnelId} group={group} cameras={ov.cameras} />
        <AnchorDrawer
          open={drawerOpen}
          anchors={anchors}
          current={current}
          onJump={(seq) => goto(seq)}
          onDelete={(seq) => api.deleteAnchor(tunnelId, seq).catch(() => {})}
        />
      </div>

      <ScrubberRail
        est={ov.groups.est}
        missing={ov.groups.missing}
        anchored={ov.groups.anchored}
        startM={ov.start_m}
        endM={ov.end_m}
        current={current}
        onJump={goto}
      />

      <div className="vhint hint">
        ←/→ 群組 · Enter 錨點 · Home/End 首/末 · 滾輪縮放（同步）· 拖曳平移 · 雙擊復原 · Ctrl+G 跳轉
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
