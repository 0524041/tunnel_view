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

const ANOMALY_COLOR = '#e857a0'

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
  const [view, setView] = useState([0, Math.min(n, 60)])
  const viewRef = useRef(view)
  viewRef.current = n ? clampView(view[0], view[1], n) : view
  const dragRef = useRef(null)
  const sizeRef = useRef({ w: 0, h: 0 })
  const hitRef = useRef([])
  const [tip, setTip] = useState(null)
  const [hideMissing, setHideMissing] = useState(() => localStorage.getItem('tv_hide_missing_marks') === '1')
  const [hideAnomaly, setHideAnomaly] = useState(() => localStorage.getItem('tv_hide_anomaly') === '1')
  const findHit = (px) => hitRef.current.find((h) => Math.abs(h.x - px) <= 6)
  const toggleMissing = () => {
    setHideMissing((v) => {
      localStorage.setItem('tv_hide_missing_marks', v ? '0' : '1')
      return !v
    })
  }
  const toggleAnomaly = () => {
    setHideAnomaly((v) => {
      localStorage.setItem('tv_hide_anomaly', v ? '0' : '1')
      return !v
    })
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
    ctx.strokeStyle = 'rgba(154,163,173,0.38)'
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
      ctx.strokeStyle = isMajor ? 'rgba(200,208,216,0.55)' : 'rgba(154,163,173,0.22)'
      ctx.lineWidth = isMajor ? 1.5 : 1
      ctx.beginPath()
      ctx.moveTo(x + 0.5, boreTopY + (isMajor ? 0 : 3))
      ctx.lineTo(x + 0.5, boreBotY - (isMajor ? 0 : 3))
      ctx.stroke()
      if (isMajor) {
        // 樁號牌：壁上方的小圓角標籤
        const label = fmtMileage(Math.round(m))
        const tw = ctx.measureText(label).width
        ctx.fillStyle = 'rgba(23,27,33,0.9)'
        ctx.beginPath()
        ctx.roundRect(x - tw / 2 - 4, labelPlateY, tw + 8, 13, 3)
        ctx.fill()
        ctx.strokeStyle = 'rgba(154,163,173,0.35)'
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.fillStyle = 'rgba(178,186,194,0.95)'
        ctx.fillText(label, x, labelPlateY + 10)
      }
    }

    // 起訖樁號：僅在進入可視範圍時顯示（避免「看得到 27k 卻點不到」的幽靈標籤）
    const xStart = mileageToX(sortedStart, W)
    const xEnd = mileageToX(sortedEnd, W)
    ctx.font = '600 10px "IBM Plex Mono", monospace'
    if (xStart >= PAD - 2 && xStart <= W - PAD + 2) {
      ctx.fillStyle = 'rgba(120,200,120,0.85)'
      ctx.textAlign = 'left'
      ctx.fillText('▶ ' + fmtMileage(sortedStart), Math.max(PAD - 8, xStart + 5), boreBotY + 10)
    }
    if (xEnd >= PAD - 2 && xEnd <= W - PAD + 2) {
      ctx.fillStyle = 'rgba(232,87,87,0.85)'
      ctx.textAlign = 'right'
      ctx.fillText(fmtMileage(sortedEnd) + ' ◀', Math.min(W - PAD + 8, xEnd - 5), boreBotY + 10)
    }

    // ── 上層：襯砌環片點位 ──
    const hits = []
    const ringJointEvery = Math.max(1, Math.round((v1 - v0) / 80))
    for (let i = Math.max(0, Math.ceil(v0)); i < Math.min(n, v1 + 1); i++) {
      const x = idxToX(toDispIdx(i), ...dispPair(), W, PAD)
      const isRingJoint = i % ringJointEvery === 0
      ctx.fillStyle = isRingJoint ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.28)'
      ctx.fillRect(x - 0.5, isRingJoint ? 6 : 8, 1, isRingJoint ? 10 : 8)
      if (anchored[i]) {
        ctx.fillStyle = '#4fa3ff'
        ctx.fillRect(x - 4, 3, 8, 7)
        ctx.strokeStyle = 'rgba(0,0,0,0.6)'
        ctx.lineWidth = 1
        ctx.strokeRect(x - 3.5, 3.5, 7, 6)
      }
      if (!hideMissing && missing[i] > 0) {
        ctx.fillStyle = '#ff4d4f'
        ctx.fillRect(x - 1.25, 10, 2.5, 9)
      }
      if (anomaly?.[i] > 0) {
        ctx.fillStyle = hideAnomaly ? 'rgba(255,179,0,0.18)' : '#ffb300'
        ctx.beginPath()
        ctx.moveTo(x, 19)
        ctx.lineTo(x - 4, 24)
        ctx.lineTo(x, 29)
        ctx.lineTo(x + 4, 24)
        ctx.closePath()
        ctx.fill()
      }
      if (ano?.[i] > 0) {
        if (!hideAnomaly) {
          ctx.fillStyle = ANOMALY_COLOR
          const w = ano[i] > 1 ? 5 : 3
          ctx.beginPath()
          ctx.roundRect(x - w / 2, 6, w, 7, 1.5)
          ctx.fill()
        }
        hits.push({ x, seq: i })
      }
    }
    hitRef.current = hits

    // ── 當前位置：頭燈光束＋游標 ──
    if (current >= v0 && current <= v1) {
      const x = idxToX(toDispIdx(current), ...dispPair(), W, PAD)
      const glow = ctx.createLinearGradient(x, 0, x, H)
      glow.addColorStop(0, 'rgba(255,179,0,0.22)')
      glow.addColorStop(1, 'rgba(255,179,0,0.04)')
      ctx.strokeStyle = glow
      ctx.lineWidth = 6
      ctx.beginPath()
      ctx.moveTo(x, 2)
      ctx.lineTo(x, boreBotY - 2)
      ctx.stroke()
      ctx.strokeStyle = '#ffb300'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x, 2)
      ctx.lineTo(x, boreBotY)
      ctx.stroke()
      ctx.fillStyle = '#ffb300'
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
      ctx.fillStyle = 'rgba(255,179,0,0.16)'
      ctx.beginPath()
      ctx.roundRect(bx, 1, tw + 16, 17, 8)
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,179,0,0.55)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.roundRect(bx + 0.5, 1.5, tw + 15, 16, 8)
      ctx.stroke()
      ctx.fillStyle = '#ffb300'
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
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { x: e.clientX, moved: false, start: viewRef.current, w: sizeRef.current.w }
  }

  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) {
      const rect = wrapRef.current.getBoundingClientRect()
      const hit = findHit(e.clientX - rect.left)
      setTip(hit ? { ...hit, px: e.clientX - rect.left } : null)
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
    // 點擊異狀標記優先跳轉
    const hit = findHit(px)
    const [dv0, dv1] = isReversed ? [n - 1 - d.start[1], n - 1 - d.start[0]] : d.start
    const dispIdx = xToIdx(px, dv0, dv1, d.w, PAD)
    const idx = Math.max(0, Math.min(n - 1, Math.round(fromDispIdx(dispIdx))))
    onJump(hit ? hit.seq : idx)
  }

  const tipData = tip ? anomsBySeq?.[tip.seq] : null

  return (
    <div className="rail-block">
      <div className="rail-wrap" ref={wrapRef} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={() => setTip(null)}>
        <canvas ref={canvasRef} />
        {tip && tipData && (
          <div className="rail-tip" style={{ left: Math.min(Math.max(tip.px, 120), (sizeRef.current.w || 400) - 130) }}>
            <img src={`/api/tunnels/${tunnelId}/photos/${tipData.photo_id}?w=240`} alt="" />
            <div className="rail-tip-body">
              <b className="mono">{fmtMileage(est[tip.seq] ?? 0)}</b>
              <span>{tipData.types.join('、')}</span>
            </div>
          </div>
        )}
      </div>
      <div className="rail-legend">
        <span style={{ opacity: 1 }}><i style={{ background: '#4fa3ff' }} /> 錨點</span>
        <button type="button" className={`chip ${hideMissing ? 'ghost' : ''}`} onClick={toggleMissing} title="隱藏/顯示缺照標記（僅里程條）" style={{ opacity: hideMissing ? 0.45 : 1 }}>
          <i style={{ background: '#ff4d4f' }} /> 缺照 {hideMissing ? '◯' : '👁'}
        </button>
        <span><i className="legend-diamond" /> 比例異常</span>
        <button type="button" className={`chip ${hideAnomaly ? 'ghost' : ''}`} onClick={toggleAnomaly} title="隱藏/顯示異常" style={{ opacity: hideAnomaly ? 0.45 : 1 }}>
          <i style={{ background: ANOMALY_COLOR }} /> 異狀 {hideAnomaly ? '◯' : '👁'}
        </button>
        <span><i style={{ background: '#ffb300', height: 2 }} /> 當前位置</span>
        <em className="hint rail-shortcuts">←/→ 群組 · Enter 錨點 · M 合併邊界 · Home/End · Ctrl+G 跳轉 · 點照片開原圖 · 滾輪縮放/拖曳 · 上層環片點位／下層孔腔里程</em>
        <span className="vspacer" />
        <button type="button" className="btn small ghost rail-help" title="說明與快捷鍵" onClick={() => onOpenHelp?.()}>?</button>
      </div>
    </div>
  )
}
