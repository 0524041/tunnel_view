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
import { fmtMileage, pickStep, clampView, zoomView, followCurrent, idxToX, xToIdx, mileageToIdx } from '../lib/scrubberMath.js'

const SNAP_DISTANCE = 14
const CLUSTER_DISTANCE = 12
const MARKER_LABELS = {
  anchor: '錨點',
  missing: '缺照',
  aspect: '比例異常',
  defect: '異狀',
}

function railColors() {
  const styles = getComputedStyle(document.documentElement)
  const get = (name) => styles.getPropertyValue(name).trim()
  return {
    wall: get('--rail-wall'), tick: get('--rail-tick'), minorTick: get('--rail-minor-tick'),
    labelBg: get('--rail-label-bg'), labelBorder: get('--rail-label-border'), labelText: get('--rail-label-text'),
    start: get('--rail-start'), end: get('--rail-end'), joint: get('--rail-joint'), anchor: get('--rail-anchor'),
    anchorOutline: get('--rail-anchor-outline'), missing: get('--rail-missing'), aspect: get('--rail-aspect'),
    anomaly: get('--rail-anomaly'), current: get('--rail-current'), currentGlow: get('--rail-current-glow'),
    currentFill: get('--rail-current-fill'), currentBorder: get('--rail-current-border'),
  }
}

export default function ScrubberRail({
  tunnelId,
  est,
  missing,
  anchored,
  anomaly,
  ano,
  anomsBySeq,
  current,
  startM,
  endM,
  isReversed: isReversedProp,
  onJump,
  onOpenHelp,
}) {
  const canvasRef = useRef(null)
  const wrapRef = useRef(null)
  const n = est?.length ?? 0
  const legendColors = railColors()
  const [view, setView] = useState([0, Math.min(n, 60)])
  const viewRef = useRef(view)
  viewRef.current = n ? clampView(view[0], view[1], n) : view
  const dragRef = useRef(null)
  const sizeRef = useRef({ w: 0, h: 0 })
  const markerRef = useRef([])
  const [tip, setTip] = useState(null)
  const [snapped, setSnapped] = useState(null)
  const [picker, setPicker] = useState(null)
  const [hideAnchors, setHideAnchors] = useState(() => localStorage.getItem('tv_hide_anchor_marks') === '1')
  const [hideMissing, setHideMissing] = useState(() => localStorage.getItem('tv_hide_missing_marks') === '1')
  const [hideAspect, setHideAspect] = useState(() => localStorage.getItem('tv_hide_aspect_marks') === '1')
  const [hideDefects, setHideDefects] = useState(() => localStorage.getItem('tv_hide_anomaly_marks') === '1' || localStorage.getItem('tv_hide_anomaly') === '1')
  const [snapEnabled, setSnapEnabled] = useState(() => localStorage.getItem('tv_marker_snap') !== '0')
  const findNearestMarker = (px, maxDistance = SNAP_DISTANCE) => {
    let nearest = null
    for (const marker of markerRef.current) {
      const distance = Math.abs(marker.x - px)
      if (distance > maxDistance || (nearest && distance >= nearest.distance)) continue
      nearest = { ...marker, distance }
    }
    return nearest
  }
  const clearPicker = () => setPicker(null)
  const clearMarkerUi = () => {
    setPicker(null)
    setSnapped(null)
    setTip(null)
  }
  const toggleAnchors = () => {
    setHideAnchors((v) => {
      localStorage.setItem('tv_hide_anchor_marks', v ? '0' : '1')
      return !v
    })
    clearMarkerUi()
  }
  const toggleMissing = () => {
    setHideMissing((v) => {
      localStorage.setItem('tv_hide_missing_marks', v ? '0' : '1')
      return !v
    })
    clearMarkerUi()
  }
  const toggleAspect = () => {
    setHideAspect((v) => {
      localStorage.setItem('tv_hide_aspect_marks', v ? '0' : '1')
      return !v
    })
    clearMarkerUi()
  }
  const toggleDefects = () => {
    setHideDefects((v) => {
      localStorage.setItem('tv_hide_anomaly_marks', v ? '0' : '1')
      return !v
    })
    clearMarkerUi()
  }
  const toggleSnap = () => {
    setSnapEnabled((v) => {
      localStorage.setItem('tv_marker_snap', v ? '0' : '1')
      return !v
    })
    clearMarkerUi()
  }

  // 檢視窗狀態與資料長度同步（n 變動時夾回合法範圍）
  useEffect(() => {
    if (n > 0) setView(([a, b]) => clampView(a, b, n))
  }, [n])

  // 檢視跟隨：鍵盤/跳轉讓 current 離開可視範圍時，視窗自動平移跟上
  useEffect(() => {
    if (!n || current == null) return
    setView((v) => followCurrent(clampView(v[0], v[1], n), current, n))
  }, [current, n])

  useEffect(() => {
    const wrap = wrapRef.current
    const ro = new ResizeObserver(draw)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    draw()
  })

  const PAD = 16
  // isReversed 由外層 Viewer 依 displayOrder 決定，fallback 為 start>end（小→大預設）
  const _fallbackReversed = (startM ?? 0) > (endM ?? 0)
  const isReversed = isReversedProp ?? _fallbackReversed

  const dispPair = () => {
    const [v0, v1] = viewRef.current
    return isReversed ? [n - 1 - v1, n - 1 - v0] : [v0, v1]
  }
  const toDispIdx = (idx) => (isReversed ? n - 1 - idx : idx)
  const fromDispIdx = (dispIdx) => (isReversed ? n - 1 - dispIdx : dispIdx)

  // 里程 → x：mileageToIdx 在「真實 seq 空間」以 est 內插（純函式、正反方向皆可），
  // 最後一步才轉換到顯示空間取 x。不可把顯示空間視窗值傳給內插——反向隧道會塌縮。
  const mileageToX = (m, W) => {
    const [v0, v1] = viewRef.current
    return idxToX(toDispIdx(mileageToIdx(est, m, v0, v1)), ...dispPair(), W, PAD)
  }

  function draw() {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap || !n) return
    const dpr = window.devicePixelRatio || 1
    const W = wrap.clientWidth
    const H = wrap.clientHeight
    sizeRef.current = { w: W, h: H }
    canvas.width = W * dpr
    canvas.height = H * dpr
    canvas.style.width = `${W}px`
    canvas.style.height = `${H}px`
    const ctx = canvas.getContext('2d')
    const colors = railColors()
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, W, H)

    const [v0, v1] = viewRef.current
    // 版面：上層 30px 環片點位帶，下層「孔腔」里程軸 42px
    const boreTopY = 46
    const boreMidY = 52
    const boreBotY = 60
    const labelPlateY = boreTopY - 15

    const sortedStart = Math.min(startM ?? est[0] ?? 0, endM ?? est[n - 1] ?? 0)
    const sortedEnd = Math.max(startM ?? est[0] ?? 0, endM ?? est[n - 1] ?? 0)
    const m0vis = est[Math.max(0, Math.round(v0))] ?? sortedStart
    const m1vis = est[Math.min(n - 1, Math.round(v1))] ?? sortedEnd
    const metersPerPx = Math.max(Math.abs(m1vis - m0vis) / Math.max(W - PAD * 2, 1), 0.5)
    const step = pickStep(metersPerPx)
    const minorStep = step / 5
    const firstM = Math.ceil(sortedStart / minorStep) * minorStep
    const lastM = sortedEnd

    // ── 孔腔雙壁（隧道斷面意象：兩條壁線夾出通道）──
    ctx.strokeStyle = colors.wall
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(PAD - 6, boreTopY + 0.5)
    ctx.lineTo(W - PAD + 6, boreTopY + 0.5)
    ctx.moveTo(PAD - 6, boreBotY + 0.5)
    ctx.lineTo(W - PAD + 6, boreBotY + 0.5)
    ctx.stroke()

    // ── 枕木刻度＋樁號牌 ──
    ctx.font = '10px "IBM Plex Mono", monospace'
    ctx.textAlign = 'center'
    for (let m = firstM; m <= lastM + 1e-6; m += minorStep) {
      const x = mileageToX(m, W)
      if (x < PAD - 2 || x > W - PAD + 2) continue
      const isMajor = Math.abs(m % step) < 1e-6 || Math.abs((m % step) - step) < 1e-6
      // 枕木：貫穿雙壁之間的短橫木
      ctx.strokeStyle = isMajor ? colors.tick : colors.minorTick
      ctx.lineWidth = isMajor ? 1.5 : 1
      ctx.beginPath()
      ctx.moveTo(x + 0.5, boreTopY + (isMajor ? 0 : 3))
      ctx.lineTo(x + 0.5, boreBotY - (isMajor ? 0 : 3))
      ctx.stroke()
      if (isMajor) {
        // 樁號牌：壁上方的小圓角標籤
        const label = fmtMileage(Math.round(m))
        const tw = ctx.measureText(label).width
        ctx.fillStyle = colors.labelBg
        ctx.beginPath()
        ctx.roundRect(x - tw / 2 - 4, labelPlateY, tw + 8, 13, 3)
        ctx.fill()
        ctx.strokeStyle = colors.labelBorder
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.fillStyle = colors.labelText
        ctx.fillText(label, x, labelPlateY + 10)
      }
    }

    // 起訖樁號：僅在進入可視範圍時顯示（避免「看得到 27k 卻點不到」的幽靈標籤）
    const xStart = mileageToX(sortedStart, W)
    const xEnd = mileageToX(sortedEnd, W)
    ctx.font = '600 10px "IBM Plex Mono", monospace'
    if (xStart >= PAD - 2 && xStart <= W - PAD + 2) {
      ctx.fillStyle = colors.start
      ctx.textAlign = 'left'
      ctx.fillText('▶ ' + fmtMileage(sortedStart), Math.max(PAD - 8, xStart + 5), boreBotY + 10)
    }
    if (xEnd >= PAD - 2 && xEnd <= W - PAD + 2) {
      ctx.fillStyle = colors.end
      ctx.textAlign = 'right'
      ctx.fillText(fmtMileage(sortedEnd) + ' ◀', Math.min(W - PAD + 8, xEnd - 5), boreBotY + 10)
    }

    // ── 上層：襯砌環片點位 ──
    const markers = []
    const ringJointEvery = Math.max(1, Math.round((v1 - v0) / 80))
    for (let i = Math.max(0, Math.ceil(v0)); i < Math.min(n, v1 + 1); i++) {
      const x = idxToX(toDispIdx(i), ...dispPair(), W, PAD)
      const isRingJoint = i % ringJointEvery === 0
      ctx.fillStyle = colors.joint
      ctx.fillRect(x - 0.5, isRingJoint ? 6 : 8, 1, isRingJoint ? 10 : 8)
      const types = []
      if (!hideAnchors && anchored[i]) {
        ctx.fillStyle = colors.anchor
        ctx.fillRect(x - 4, 3, 8, 7)
        ctx.strokeStyle = colors.anchorOutline
        ctx.lineWidth = 1
        ctx.strokeRect(x - 3.5, 3.5, 7, 6)
        types.push('anchor')
      }
      if (!hideMissing && missing[i] > 0) {
        ctx.fillStyle = colors.missing
        ctx.fillRect(x - 1.25, 10, 2.5, 9)
        types.push('missing')
      }
      if (!hideAspect && anomaly?.[i] > 0) {
        ctx.fillStyle = colors.aspect
        ctx.beginPath()
        ctx.moveTo(x, 19)
        ctx.lineTo(x - 4, 24)
        ctx.lineTo(x, 29)
        ctx.lineTo(x + 4, 24)
        ctx.closePath()
        ctx.fill()
        types.push('aspect')
      }
      if (ano?.[i] > 0) {
        if (!hideDefects) {
          ctx.fillStyle = colors.anomaly
          const w = ano[i] > 1 ? 5 : 3
          ctx.beginPath()
          ctx.roundRect(x - w / 2, 6, w, 7, 1.5)
          ctx.fill()
          types.push('defect')
        }
      }
      if (types.length) markers.push({ x, seq: i, types })
    }
    markerRef.current = markers

    // ── 當前位置：頭燈光束＋游標 ──
    if (current >= v0 && current <= v1) {
      const x = idxToX(toDispIdx(current), ...dispPair(), W, PAD)
      const glow = ctx.createLinearGradient(x, 0, x, H)
      glow.addColorStop(0, colors.currentGlow)
      glow.addColorStop(1, 'transparent')
      ctx.strokeStyle = glow
      ctx.lineWidth = 6
      ctx.beginPath()
      ctx.moveTo(x, 2)
      ctx.lineTo(x, boreBotY - 2)
      ctx.stroke()
      ctx.strokeStyle = colors.current
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x, 2)
      ctx.lineTo(x, boreBotY)
      ctx.stroke()
      ctx.fillStyle = colors.current
      ctx.beginPath()
      ctx.moveTo(x - 5, boreBotY - 1)
      ctx.lineTo(x + 5, boreBotY - 1)
      ctx.lineTo(x, boreBotY + 8)
      ctx.closePath()
      ctx.fill()

      const label = fmtMileage(est[current] ?? 0)
      ctx.font = '600 11px "IBM Plex Mono", monospace'
      const tw = ctx.measureText(label).width
      const bx = Math.min(Math.max(x - tw / 2 - 8, PAD - 8), W - PAD + 8 - tw - 16)
      ctx.fillStyle = colors.currentFill
      ctx.beginPath()
      ctx.roundRect(bx, 1, tw + 16, 17, 8)
      ctx.fill()
      ctx.strokeStyle = colors.currentBorder
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.roundRect(bx + 0.5, 1.5, tw + 15, 16, 8)
      ctx.stroke()
      ctx.fillStyle = colors.current
      ctx.textAlign = 'center'
      ctx.fillText(label, bx + tw / 2 + 8, 13)
    }
  }

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const handler = (e) => {
      e.preventDefault()
      const { w } = sizeRef.current
      const rect = el.getBoundingClientRect()
      const px = e.clientX - rect.left
      const [dv0, dv1] = dispPair()
      const dispAtCursor = xToIdx(px, dv0, dv1, w, PAD)
      const idxAtCursor = fromDispIdx(dispAtCursor)
      const k = Math.exp(e.deltaY * 0.0015)
      setView((v) => zoomView(v, idxAtCursor, k, n))
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [n, isReversed])

  const onPointerDown = (e) => {
    clearPicker()
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { x: e.clientX, moved: false, start: viewRef.current, w: sizeRef.current.w }
  }

  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) {
      const rect = wrapRef.current.getBoundingClientRect()
      const px = e.clientX - rect.left
      const nearest = findNearestMarker(px)
      const activeSnap = snapEnabled ? nearest : null
      const tipMarker = activeSnap || findNearestMarker(px, 6)
      setSnapped(activeSnap)
      setTip(tipMarker?.types.includes('defect') ? { ...tipMarker, px: tipMarker.x } : null)
      return
    }
    const dx = e.clientX - d.x
    if (Math.abs(dx) > 4) d.moved = true
    if (!d.moved) return
    const span = d.start[1] - d.start[0]
    const shift = (-dx / Math.max(d.w - PAD * 2, 1)) * span
    setView(clampView(d.start[0] + shift, d.start[1] + shift, n))
  }

  const onPointerUp = (e) => {
    const d = dragRef.current
    dragRef.current = null
    if (!d || d.moved) return
    const rect = wrapRef.current.getBoundingClientRect()
    const px = e.clientX - rect.left
    const snappedMarker = snapEnabled ? findNearestMarker(px) : null
    if (snappedMarker) {
      const choices = markerRef.current.filter((marker) => Math.abs(marker.x - snappedMarker.x) <= CLUSTER_DISTANCE)
      if (choices.length > 1) {
        setPicker({ x: snappedMarker.x, choices })
      } else {
        onJump(snappedMarker.seq)
      }
      return
    }
    const [dv0, dv1] = isReversed ? [n - 1 - d.start[1], n - 1 - d.start[0]] : d.start
    const dispIdx = xToIdx(px, dv0, dv1, d.w, PAD)
    const idx = Math.max(0, Math.min(n - 1, Math.round(fromDispIdx(dispIdx))))
    onJump(idx)
  }

  const tipData = tip ? anomsBySeq?.[tip.seq] : null

  return (
    <div className="rail-block" data-tour="viewer-rail">
      <div className="rail-wrap" ref={wrapRef} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={() => { setTip(null); setSnapped(null) }}>
        <canvas ref={canvasRef} />
        {snapped && (
          <div className="rail-snap" style={{ left: snapped.x }}>
            {snapped.types.map((type) => MARKER_LABELS[type]).join('、')}
          </div>
        )}
        {tip && tipData && (
          <div className="rail-tip" style={{ left: Math.min(Math.max(tip.px, 120), (sizeRef.current.w || 400) - 130) }}>
            <img src={`/api/tunnels/${tunnelId}/photos/${tipData.photo_id}?w=240`} alt="" />
            <div className="rail-tip-body">
              <b className="mono">{fmtMileage(est[tip.seq] ?? 0)}</b>
              <span>{tipData.types.join('、')}</span>
            </div>
          </div>
        )}
        {picker && (
          <div className="rail-marker-picker" style={{ left: Math.min(Math.max(picker.x, 130), (sizeRef.current.w || 400) - 150) }} onPointerDown={(e) => e.stopPropagation()}>
            <span className="label">選擇標記</span>
            {picker.choices.map((marker) => (
              <button key={marker.seq} type="button" onClick={() => { onJump(marker.seq); clearPicker() }}>
                <b className="mono">{fmtMileage(est[marker.seq] ?? 0)}</b>
                <span>群組 #{String(marker.seq + 1).padStart(4, '0')} · {marker.types.map((type) => MARKER_LABELS[type]).join('、')}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="rail-legend">
        <button type="button" className={`chip ${hideAnchors ? 'ghost' : ''}`} onClick={toggleAnchors} title="隱藏/顯示錨點標記" style={{ opacity: hideAnchors ? 0.45 : 1 }}>
          <i style={{ background: legendColors.anchor }} /> 錨點 {hideAnchors ? '◯' : '👁'}
        </button>
        <button type="button" className={`chip ${hideMissing ? 'ghost' : ''}`} onClick={toggleMissing} title="隱藏/顯示缺照標記（僅里程條）" style={{ opacity: hideMissing ? 0.45 : 1 }}>
          <i style={{ background: legendColors.missing }} /> 缺照 {hideMissing ? '◯' : '👁'}
        </button>
        <button type="button" className={`chip ${hideAspect ? 'ghost' : ''}`} onClick={toggleAspect} title="隱藏/顯示比例異常標記" style={{ opacity: hideAspect ? 0.45 : 1 }}>
          <i className="legend-diamond" /> 比例異常 {hideAspect ? '◯' : '👁'}
        </button>
        <button type="button" className={`chip ${hideDefects ? 'ghost' : ''}`} onClick={toggleDefects} title="隱藏/顯示異狀標記" style={{ opacity: hideDefects ? 0.45 : 1 }}>
          <i style={{ background: legendColors.anomaly }} /> 異狀 {hideDefects ? '◯' : '👁'}
        </button>
        <span><i style={{ background: legendColors.current, height: 2 }} /> 當前位置</span>
        <button type="button" className={`chip ${snapEnabled ? 'amber' : 'ghost'}`} onClick={toggleSnap} title="開啟時，游標會吸附至最近的可見標記">
          ◎ 吸附 {snapEnabled ? '開' : '關'}
        </button>
        <em className="hint rail-shortcuts">←/→ 群組 · Enter 錨點 · M 合併邊界 · Home/End · Ctrl+G 跳轉 · 點照片開原圖 · 滾輪縮放/拖曳 · 上層環片點位／下層孔腔里程</em>
        <span className="vspacer" />
        <button type="button" className="btn small ghost rail-help" title="說明與快捷鍵" onClick={() => onOpenHelp?.()}>?</button>
      </div>
    </div>
  )
}
