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

const fmt = (m) => `K${Math.floor(m / 1000)}+${String(m % 1000).padStart(3, '0')}`
const STEP_CANDIDATES = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
const ANOMALY_COLOR = '#e857a0'

function pickStep(metersPerPx, minPx = 90) {
  const need = metersPerPx * minPx
  for (const s of STEP_CANDIDATES) {
    if (s >= need) return s
  }
  return 2000
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
  onJump,
  onOpenHelp,
}) {
  const canvasRef = useRef(null)
  const wrapRef = useRef(null)
  const n = est?.length ?? 0
  const [view, setView] = useState([0, Math.min(n, 60)])
  const viewRef = useRef(view)
  viewRef.current = view
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

  useEffect(() => {
    setView(([a, b]) => (b > n ? [0, Math.min(n, b)] : [a, b]))
  }, [n])

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
  const isReversed = (startM ?? 0) > (endM ?? 0)

  const idxToX = (idx, W) => {
    const [v0, v1] = viewRef.current
    const dispIdx = isReversed ? (n - 1 - idx) : idx
    const dispV0 = isReversed ? (n - 1 - v1) : v0
    const dispV1 = isReversed ? (n - 1 - v0) : v1
    return PAD + ((dispIdx - dispV0) / Math.max(dispV1 - dispV0, 1e-6)) * (W - PAD * 2)
  }

  // 里程 → x：在可視群組區間內以 est 線性內插，讓刻度落在真實樁號位置（支援遞增/遞減）
  const mileageToIdx = (m) => {
    const [v0, v1] = viewRef.current
    let lo = Math.max(0, Math.floor(v0))
    let hi = Math.min(n - 1, Math.ceil(v1))
    if (hi <= lo) return lo
    // 區間外插：按該側斜率外插，無論增減
    const eLo = est[lo]
    const eHi = est[hi]
    const loNext = est[Math.min(lo + 1, n - 1)]
    const hiPrev = est[Math.max(hi - 1, 0)]
    const slopeLo = loNext - eLo
    const slopeHi = eHi - hiPrev
    const minE = Math.min(eLo, eHi)
    const maxE = Math.max(eLo, eHi)
    if (m < minE) {
      // 在較小里程外
      if (eHi < eLo) return hi + (m - eHi) / Math.max(slopeHi, 1e-6)
      return lo - (eLo - m) / Math.max(slopeLo, 1e-6)
    }
    if (m > maxE) {
      if (eHi > eLo) return hi + (m - eHi) / Math.max(slopeHi, 1e-6)
      return lo - (eLo - m) / Math.max(-slopeLo, 1e-6)
    }
    // 區間內線性內插，線性掃描找跨段（n≤10k，刻度≤~30，O(n*刻度) 可接受且穩健處理遞增/遞減）
    for (let i = lo; i < hi; i++) {
      const a = est[i]
      const b = est[i + 1]
      if ((a <= m && m <= b) || (a >= m && m >= b)) {
        const t = (m - a) / Math.max(b - a, 1e-6)
        return i + t
      }
    }
    // 兜底二分（遞增/遞減皆處理）
    const isInc = (est[0] ?? 0) <= (est[n - 1] ?? 0)
    let l = lo, h = hi
    while (h - l > 1) {
      const mid = (l + h) >> 1
      if (isInc ? est[mid] < m : est[mid] > m) l = mid
      else h = mid
    }
    const e0 = est[l]
    const e1 = est[h]
    return l + ((m - e0) / Math.max(e1 - e0, 1e-6)) * (h - l)
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
    // 雙層佈局：上層 28px（照片群組點位），下層 44px（里程均分刻度），共 72px
    const upperH = 28
    const gapY = upperH
    const lowerAxisY = upperH + 14
    const lowerLabelY = lowerAxisY + 12
    const totalH = 72

    // 下層里程刻度：由小到大均分（與群組同動，以 seq 為單位）
    const sortedStart = Math.min(startM ?? est[0] ?? 0, endM ?? est[n - 1] ?? 0)
    const sortedEnd = Math.max(startM ?? est[0] ?? 0, endM ?? est[n - 1] ?? 0)
    // 可視里程區間由 v0~v1 的 est 推算，確保縮放同動
    const m0vis = est[Math.max(0, Math.round(v0))] ?? sortedStart
    const m1vis = est[Math.min(n - 1, Math.round(v1))] ?? sortedEnd
    const visMin = Math.min(m0vis, m1vis, sortedStart)
    const visMax = Math.max(m0vis, m1vis, sortedEnd)
    const metersPerPx = Math.max((Math.abs(m1vis - m0vis)) / Math.max(W - PAD * 2, 1), 0.5)
    const step = pickStep(metersPerPx)
    const minorStep = step / 5
    const firstM = Math.ceil(sortedStart / minorStep) * minorStep
    const lastM = sortedEnd

    ctx.font = '10px "IBM Plex Mono", monospace'
    ctx.textAlign = 'center'
    for (let m = firstM; m <= lastM + 1e-6; m += minorStep) {
      const x = idxToX(mileageToIdx(m), W)
      if (x < PAD - 2 || x > W - PAD + 2) continue
      const isMajor = Math.abs(m % step) < 1e-6 || Math.abs((m % step) - step) < 1e-6
      ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.42)' : 'rgba(255,255,255,0.12)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(x + 0.5, isMajor ? lowerAxisY - 8 : lowerAxisY - 3)
      ctx.lineTo(x + 0.5, lowerAxisY)
      ctx.stroke()
      if (isMajor) {
        ctx.fillStyle = 'rgba(154,163,173,0.95)'
        ctx.fillText(fmt(Math.round(m)), x, lowerLabelY)
      }
    }

    // 下層基準軸
    ctx.strokeStyle = 'rgba(255,255,255,0.24)'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(PAD - 6, lowerAxisY + 0.5)
    ctx.lineTo(W - PAD + 6, lowerAxisY + 0.5)
    ctx.stroke()

    // 起訖樁號釘選（由小到大顯示）
    ctx.fillStyle = 'rgba(89,98,108,0.95)'
    ctx.textAlign = 'left'
    ctx.fillText(fmt(sortedStart), PAD - 10, lowerAxisY - 12)
    ctx.textAlign = 'right'
    ctx.fillText(fmt(sortedEnd), W - PAD + 10, lowerAxisY - 12)

    // 上層：每群組淺色點位 + 分層標注（與下層同動、以 seq 為單位）
    const hits = []
    for (let i = Math.max(0, Math.ceil(v0)); i < Math.min(n, v1 + 1); i++) {
      const x = idxToX(i, W)
      // 淺色群組點位（每群組一刻度）
      ctx.fillStyle = 'rgba(255,255,255,0.32)'
      ctx.fillRect(x - 0.5, 8, 1, 8)
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
      if (ano?.[i] > 0 && !hideAnomaly) {
        ctx.fillStyle = ANOMALY_COLOR
        const w = ano[i] > 1 ? 5 : 3
        ctx.beginPath()
        ctx.roundRect(x - w / 2, 6, w, 7, 1.5)
        ctx.fill()
        hits.push({ x, seq: i })
      } else if (ano?.[i] > 0) {
        hits.push({ x, seq: i })
      }
    }
    // 上下層分隔線
    ctx.strokeStyle = 'rgba(255,255,255,0.08)'
    ctx.beginPath()
    ctx.moveTo(PAD - 6, gapY + 0.5)
    ctx.lineTo(W - PAD + 6, gapY + 0.5)
    ctx.stroke()
    hitRef.current = hits

    // 當前位置指示＋樁號浮標
    if (current >= v0 && current <= v1) {
      const x = idxToX(current, W)
      ctx.strokeStyle = '#ffb300'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x, 2)
      ctx.lineTo(x, H - 10)
      ctx.stroke()
      ctx.fillStyle = '#ffb300'
      ctx.beginPath()
      ctx.moveTo(x - 5, H - 10)
      ctx.lineTo(x + 5, H - 10)
      ctx.lineTo(x, H - 2)
      ctx.closePath()
      ctx.fill()

      const label = fmt(est[current] ?? 0)
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

  const clampView = ([a, b]) => {
    let s = b - a
    if (s < 8) s = Math.min(8, n)
    a = Math.max(-s * 0.15, Math.min(a, n - s * 0.85))
    return [a, a + s]
  }

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const handler = (e) => {
      e.preventDefault()
      const { w } = sizeRef.current
      const rect = el.getBoundingClientRect()
      const px = e.clientX - rect.left
      const [v0, v1] = viewRef.current
      const dispV0 = isReversed ? (n - 1 - v1) : v0
      const dispV1 = isReversed ? (n - 1 - v0) : v1
      const dispAtCursor = dispV0 + ((px - PAD) / (w - PAD * 2)) * (dispV1 - dispV0)
      const idxAtCursor = isReversed ? (n - 1 - dispAtCursor) : dispAtCursor
      const k = Math.exp(e.deltaY * 0.0015)
      let span = Math.max(8, Math.min((v1 - v0) * k, n))
      let a = idxAtCursor - ((idxAtCursor - v0) / (v1 - v0)) * span
      setView(clampView([a, a + span]))
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
      // hover：偵測異狀標記
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
    setView(clampView([d.start[0] + shift, d.start[1] + shift]))
  }

  const onPointerUp = (e) => {
    const d = dragRef.current
    dragRef.current = null
    if (!d || d.moved) return
    const rect = wrapRef.current.getBoundingClientRect()
    const px = e.clientX - rect.left
    // 點擊異狀標記優先跳轉
    const hit = findHit(px)
    const [v0, v1] = d.start
    const frac = (px - PAD) / Math.max(d.w - PAD * 2, 1)
    const dispV0 = isReversed ? (n - 1 - v1) : v0
    const dispV1 = isReversed ? (n - 1 - v0) : v1
    const dispIdx = dispV0 + frac * (dispV1 - dispV0)
    const idx = Math.max(0, Math.min(n - 1, Math.round(isReversed ? (n - 1 - dispIdx) : dispIdx)))
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
              <b className="mono">{fmt(est[tip.seq] ?? 0)}</b>
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
        <em className="hint rail-shortcuts">←/→ 群組 · Enter 錨點 · M 合併邊界 · Home/End · Ctrl+G 跳轉 · 點照片開原圖 · 滾輪縮放/拖曳 · 上層群組點/下層里程均分</em>
        <span className="vspacer" />
        <button type="button" className="btn small ghost rail-help" title="說明與快捷鍵" onClick={() => onOpenHelp?.()}>?</button>
      </div>
    </div>
  )
}
