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
  const findHit = (px) => hitRef.current.find((h) => Math.abs(h.x - px) <= 6)

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

  const idxToX = (idx, W) => {
    const [v0, v1] = viewRef.current
    return PAD + ((idx - v0) / Math.max(v1 - v0, 1e-6)) * (W - PAD * 2)
  }

  // 里程 → x：在可視群組區間內以 est 線性內插，讓刻度落在真實樁號位置
  const mileageToIdx = (m) => {
    const [v0, v1] = viewRef.current
    let lo = Math.max(0, Math.floor(v0))
    let hi = Math.min(n - 1, Math.ceil(v1))
    if (hi <= lo) return lo
    if (m <= est[lo]) return lo - (est[lo] - m) / Math.max(est[Math.min(lo + 1, n - 1)] - est[lo], 1)
    if (m >= est[hi]) return hi + (m - est[hi]) / Math.max(est[hi] - est[Math.max(hi - 1, 0)], 1)
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (est[mid] < m) lo = mid
      else hi = mid
    }
    const e0 = est[lo]
    const e1 = est[hi]
    return lo + ((m - e0) / Math.max(e1 - e0, 1e-6)) * (hi - lo)
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
    const axisY = 34

    // 主／次刻度（依公尺密度自適應）
    const m0 = est[Math.max(0, Math.round(v0))]
    const m1 = est[Math.min(n - 1, Math.round(v1))]
    const metersPerPx = Math.max((m1 - m0) / Math.max(W - PAD * 2, 1), 1e-6)
    const step = pickStep(metersPerPx)
    const minorStep = step / 5
    const firstM = Math.ceil(Math.min(m0, m1) / minorStep) * minorStep
    const lastM = Math.max(m0, m1)

    ctx.font = '10px "IBM Plex Mono", monospace'
    ctx.textAlign = 'center'
    for (let m = firstM; m <= lastM + 1e-6; m += minorStep) {
      const x = idxToX(mileageToIdx(m), W)
      if (x < PAD - 2 || x > W - PAD + 2) continue
      const isMajor = Math.abs(m % step) < 1e-6 || Math.abs((m % step) - step) < 1e-6
      ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.14)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(x + 0.5, isMajor ? axisY - 9 : axisY - 4)
      ctx.lineTo(x + 0.5, axisY)
      ctx.stroke()
      if (isMajor) {
        ctx.fillStyle = 'rgba(154,163,173,0.95)'
        ctx.fillText(fmt(Math.round(m)), x, axisY + 15)
      }
    }

    // 基準軸
    ctx.strokeStyle = 'rgba(255,255,255,0.28)'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(PAD - 6, axisY + 0.5)
    ctx.lineTo(W - PAD + 6, axisY + 0.5)
    ctx.stroke()

    // 起訖樁號釘選
    ctx.fillStyle = 'rgba(89,98,108,0.95)'
    ctx.textAlign = 'left'
    ctx.fillText(fmt(startM ?? est[0] ?? 0), PAD - 10, axisY - 14)
    ctx.textAlign = 'right'
    ctx.fillText(fmt(endM ?? est[n - 1] ?? 0), W - PAD + 10, axisY - 14)

    // 標記帶：錨點（上）、缺照、比例異常、異狀
    const hits = []
    for (let i = Math.max(0, Math.ceil(v0)); i < Math.min(n, v1 + 1); i++) {
      const x = idxToX(i, W)
      if (anchored[i]) {
        ctx.fillStyle = '#4fa3ff'
        ctx.fillRect(x - 4, 3, 8, 7)
        ctx.strokeStyle = 'rgba(0,0,0,0.6)'
        ctx.lineWidth = 1
        ctx.strokeRect(x - 3.5, 3.5, 7, 6)
      }
      if (missing[i] > 0) {
        ctx.fillStyle = '#ff4d4f'
        ctx.fillRect(x - 1.25, 12, 2.5, 8)
      }
      if (anomaly?.[i] > 0) {
        ctx.fillStyle = '#ffb300'
        ctx.beginPath()
        ctx.moveTo(x, 22)
        ctx.lineTo(x - 4, 27)
        ctx.lineTo(x, 32)
        ctx.lineTo(x + 4, 27)
        ctx.closePath()
        ctx.fill()
      }
      if (ano?.[i] > 0) {
        ctx.fillStyle = ANOMALY_COLOR
        const w = ano[i] > 1 ? 5 : 3
        ctx.beginPath()
        ctx.roundRect(x - w / 2, 37.5, w, 9, 1.5)
        ctx.fill()
        hits.push({ x, seq: i })
      }
    }
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

  const onWheel = (e) => {
    e.preventDefault()
    const { w } = sizeRef.current
    const rect = wrapRef.current.getBoundingClientRect()
    const px = e.clientX - rect.left
    const [v0, v1] = viewRef.current
    const idxAtCursor = v0 + ((px - PAD) / (w - PAD * 2)) * (v1 - v0)
    const k = Math.exp(e.deltaY * 0.0015)
    let span = Math.max(8, Math.min((v1 - v0) * k, n))
    let a = idxAtCursor - ((idxAtCursor - v0) / (v1 - v0)) * span
    setView(clampView([a, a + span]))
  }

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
    const idx = Math.max(0, Math.min(n - 1, Math.round(v0 + frac * (v1 - v0))))
    onJump(hit ? hit.seq : idx)
  }

  const tipData = tip ? anomsBySeq?.[tip.seq] : null

  return (
    <div className="rail-block">
      <div className="rail-wrap" ref={wrapRef} onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={() => setTip(null)}>
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
        <span><i style={{ background: '#4fa3ff' }} /> 錨點</span>
        <span><i style={{ background: '#ff4d4f' }} /> 缺照</span>
        <span><i className="legend-diamond" /> 比例異常</span>
        <span><i style={{ background: ANOMALY_COLOR }} /> 異狀</span>
        <span><i style={{ background: '#ffb300', height: 2 }} /> 當前位置</span>
        <em className="hint rail-shortcuts">←/→ 群組 · Enter 錨點 · M 合併邊界 · Home/End · Ctrl+G 跳轉 · 點照片開原圖 · 滾輪縮放/拖曳</em>
        <span className="vspacer" />
        <button type="button" className="btn small ghost rail-help" title="說明與快捷鍵" onClick={() => onOpenHelp?.()}>?</button>
      </div>
    </div>
  )
}
