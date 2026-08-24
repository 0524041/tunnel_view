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
import AnomalyOverview from '../components/AnomalyOverview'
import HelpModal from '../components/HelpModal'

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
  const [anchorsOpen, setAnchorsOpen] = useState(() => localStorage.getItem('tv_anchor_open') === '1')
  const [infoOpen, setInfoOpen] = useState(() => localStorage.getItem('tv_info_open') !== '0')
  const [fit, setFit] = useState(() => localStorage.getItem('tv_fit') || 'contain')
  const [reviewOpen, setReviewOpen] = useState(false)
  const [origView, setOrigView] = useState(null)
  const [mode, setMode] = useState('view')
  const [helpOpen, setHelpOpen] = useState(false)
  const [anoRefresh, setAnoRefresh] = useState(0)
  const [anomsBySeq, setAnomsBySeq] = useState({})
  const [locateTarget, setLocateTarget] = useState(null)

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

  // 異狀摘要：里程軌 tooltip 與總覽頁共用
  useEffect(() => {
    let alive = true
    api.anomalies(tunnelId).then((rows) => {
      if (!alive) return
      const bySeq = {}
      for (const r of rows) {
        if (r.group_seq == null) continue
        if (!(r.group_seq in bySeq)) bySeq[r.group_seq] = { photo_id: r.photo_id, types: [] }
        if (!bySeq[r.group_seq].types.includes(r.type_name)) bySeq[r.group_seq].types.push(r.type_name)
      }
      setAnomsBySeq(bySeq)
    }).catch(() => {})
    return () => {
      alive = false
    }
  }, [tunnelId, anoRefresh])

  useTunnelSocket(tunnelId, (msg) => {
    if (!msg.type) return
    refreshMeta()
    if (msg.type === 'annotation_updated') {
      setAnoRefresh((k) => k + 1)
      return
    }
    if (['realigned', 'merged', 'camera_updated', 'layout_updated', 'photo_updated'].includes(msg.type)) {
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

  const isReversed = (ov?.start_m ?? 0) > (ov?.end_m ?? 0)
  useEffect(() => {
    if (!active || !ov) return
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setOrigView(null)
        setReviewOpen(false)
        setDialogOpen(false)
        setSearchOpen(false)
        setHelpOpen(false)
        return
      }
      if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'g') {
        e.preventDefault()
        setSearchOpen(true)
        return
      }
      if (origView || dialogOpen || searchOpen || reviewOpen) return
      if (e.key === '?') {
        setHelpOpen((v) => !v)
        return
      }
      if (helpOpen) return
      if (mode === 'anomalies') return
      if (e.key === 'ArrowLeft') goto(isReversed ? current + 1 : current - 1)
      else if (e.key === 'ArrowRight') goto(isReversed ? current - 1 : current + 1)
      else if (e.key === 'Home') goto(isReversed ? total - 1 : 0)
      else if (e.key === 'End') goto(isReversed ? 0 : total - 1)
      else if (e.key === 'Enter') setDialogOpen(true)
      else if (e.key.toLowerCase() === 'm') setReviewOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, ov, isReversed, origView, dialogOpen, searchOpen, reviewOpen, helpOpen, mode, current, total, goto])

  const togglePanel = (which) => {
    if (which === 'anchors') {
      setAnchorsOpen((v) => {
        localStorage.setItem('tv_anchor_open', v ? '0' : '1')
        return !v
      })
    } else {
      setInfoOpen((v) => {
        localStorage.setItem('tv_info_open', !v ? '1' : '0')
        return !v
      })
    }
  }

  const locateInViewer = (row) => {
    if (row.group_seq == null) return
    setMode('view')
    goto(row.group_seq)
    setLocateTarget({ photoId: row.photo_id, seq: row.group_seq })
    setTimeout(() => setLocateTarget(null), 2200)
  }

  const onAnnotationChanged = useCallback(() => {
    refreshMeta()
    setAnoRefresh((k) => k + 1)
  }, [refreshMeta])

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
        <div className="mode-seg">
          <button type="button" className={mode === 'view' ? 'on' : ''} onClick={() => setMode('view')}>檢視</button>
          <button type="button" className={mode === 'anomalies' ? 'on' : ''} onClick={() => setMode('anomalies')}>異狀總覽</button>
        </div>
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
        <button type="button" className="btn small" onClick={() => setReviewOpen(true)}>合併邊界（M）</button>
        <button
          type="button"
          className={`btn small ${anchorsOpen ? 'primary' : ''}`}
          onClick={() => togglePanel('anchors')}
        >錨點列</button>
        <button
          type="button"
          className={`btn small ${infoOpen ? 'primary' : ''}`}
          onClick={() => togglePanel('info')}
        >資訊</button>
        <button type="button" className="btn small ghost" title="說明與快捷鍵（?）" onClick={() => setHelpOpen(true)}>?</button>
      </div>

      {mode === 'view' ? (
        <>
          <div className="vmid">
            <CameraGrid
              tunnelId={tunnelId}
              group={group}
              cameras={ov.cameras}
              cameraMeta={cameraMeta}
              layoutCols={layoutCols}
              fit={fit}
              anomalyPaths={anomalyPaths(info)}
              highlightPhotoId={current === locateTarget?.seq ? locateTarget?.photoId : null}
              onOpenOriginal={(photo) => openOriginal(photo)}
              onRotate={(pid, angle) =>
                api.setPhotoRotation(tunnelId, pid, angle)
                  .then(refreshMeta)
                  .then(() => toast('已旋轉'))
                  .catch((e) => toast(e.message, 'err'))
              }
            />
            {anchorsOpen && (
              <div className="siderail open anchor-panel">
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
              </div>
            )}
            {infoOpen && (
              <div className="siderail open info-panel">
                <TunnelInfoPanel
                  tunnelId={tunnelId}
                  info={info}
                  onChanged={refreshMeta}
                  currentGroupCount={ov.group_count}
                />
              </div>
            )}
          </div>

          <ScrubberRail
            tunnelId={tunnelId}
            est={ov.groups.est}
            missing={ov.groups.missing}
            anchored={ov.groups.anchored}
            anomaly={ov.groups.anomaly}
            ano={ov.groups.ano}
            anomsBySeq={anomsBySeq}
            startM={ov.start_m}
            endM={ov.end_m}
            current={current}
            onJump={goto}
            onOpenHelp={() => setHelpOpen(true)}
          />
        </>
      ) : (
        <div className="vmid">
          <AnomalyOverview
            tunnelId={tunnelId}
            refreshKey={anoRefresh}
            onLocate={locateInViewer}
            onMetaRefresh={refreshMeta}
          />
        </div>
      )}

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

      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} />}

      {origView && (
        <OriginalViewer
          tunnelId={tunnelId}
          photos={origView.photos}
          startIndex={origView.index}
          onClose={() => setOrigView(null)}
          onAnnotationChanged={onAnnotationChanged}
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
