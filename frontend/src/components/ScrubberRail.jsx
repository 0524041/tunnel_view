import { useEffect, useRef, useState } from 'react'

const fmt = (m) => `K${Math.floor(m / 1000)}+${String(m % 1000).padStart(3, '0')}`

function niceStep(rawSteps) {
  const mag = 10 ** Math.floor(Math.log10(Math.max(rawSteps, 1e-6)))
  for (const m of [1, 2, 5, 10]) {
    if (m * mag >= rawSteps) return m * mag
  }
  return 10 * mag
}

export default function ScrubberRail({ est, missing, anchored, current, onJump }) {
  const canvasRef = useRef(null)
  const wrapRef = useRef(null)
  const n = est?.length ?? 0
  const [view, setView] = useState([0, Math.min(n, 60)])
  const viewRef = useRef(view)
  viewRef.current = view
  const dragRef = useRef(null)
  const sizeRef = useRef({ w: 0, h: 0 })

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

  const idxToX = (idx, W) => {
    const [v0, v1] = viewRef.current
    const pad = 14
    return pad + ((idx - v0) / Math.max(v1 - v0, 1e-6)) * (W - pad * 2)
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

    const midY = H - 26
    const [v0, v1] = viewRef.current
    const span = Math.max(v1 - v0, 1)

    ctx.strokeStyle = 'rgba(255,255,255,0.22)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(10, midY + 0.5)
    ctx.lineTo(W - 10, midY + 0.5)
    ctx.stroke()

    const rawStep = (span / Math.max(W - 28, 1)) * 110
    const step = niceStep(rawStep)
    const minor = step / 5
    const startIdx = Math.max(0, Math.floor(v0 / minor) * minor)
    for (let i = startIdx; i <= Math.min(n - 1, v1); i += minor) {
      const x = idxToX(i, W)
      const isMajor = Math.round(i) % step === 0
      ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.12)'
      ctx.beginPath()
      ctx.moveTo(x + 0.5, midY - (isMajor ? 7 : 3))
      ctx.lineTo(x + 0.5, midY)
      ctx.stroke()
      if (isMajor && i >= v0 && i <= v1) {
        ctx.fillStyle = 'rgba(154,163,173,0.9)'
        ctx.font = '10px "IBM Plex Mono", monospace'
        ctx.textAlign = 'center'
        ctx.fillText(fmt(est[Math.round(i)] ?? 0), x, midY + 15)
      }
    }

    for (let i = Math.max(0, Math.ceil(v0)); i < Math.min(n, v1 + 1); i++) {
      const x = idxToX(i, W)
      if (missing[i] > 0) {
        ctx.fillStyle = '#ff4d4f'
        ctx.fillRect(x - 1, 8, 2.5, 9)
      }
      if (anchored[i]) {
        ctx.fillStyle = '#4fa3ff'
        ctx.fillRect(x - 4, 4, 8, 8)
        ctx.strokeStyle = 'rgba(0,0,0,0.6)'
        ctx.strokeRect(x - 3.5, 4.5, 7, 7)
      }
    }

    if (current >= v0 && current <= v1) {
      const x = idxToX(current, W)
      ctx.strokeStyle = '#ffb300'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x, 2)
      ctx.lineTo(x, H - 8)
      ctx.stroke()
      ctx.fillStyle = '#ffb300'
      ctx.beginPath()
      ctx.moveTo(x - 5, H - 8)
      ctx.lineTo(x + 5, H - 8)
      ctx.lineTo(x, H - 1)
      ctx.closePath()
      ctx.fill()
    }

    ctx.fillStyle = 'rgba(89,98,108,0.9)'
    ctx.font = '10px "IBM Plex Mono", monospace'
    ctx.textAlign = 'left'
    ctx.fillText(`${n} 群組`, 12, 14)
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
    const idxAtCursor = v0 + ((px - 14) / (w - 28)) * (v1 - v0)
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
    if (!d) return
    const dx = e.clientX - d.x
    if (Math.abs(dx) > 4) d.moved = true
    if (!d.moved) return
    const span = d.start[1] - d.start[0]
    const shift = (-dx / Math.max(d.w - 28, 1)) * span
    setView(clampView([d.start[0] + shift, d.start[1] + shift]))
  }

  const onPointerUp = (e) => {
    const d = dragRef.current
    dragRef.current = null
    if (!d || d.moved) return
    const rect = wrapRef.current.getBoundingClientRect()
    const px = e.clientX - rect.left
    const [v0, v1] = d.start
    const frac = (px - 14) / Math.max(d.w - 28, 1)
    const idx = Math.max(0, Math.min(n - 1, Math.round(v0 + frac * (v1 - v0))))
    onJump(idx)
  }

  return (
    <div className="rail-wrap" ref={wrapRef} onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
      <canvas ref={canvasRef} />
      <div className="rail-legend">
        <span><i style={{ background: '#4fa3ff' }} /> 錨點</span>
        <span><i style={{ background: '#ff4d4f' }} /> 缺照</span>
        <span><i style={{ background: '#ffb300' }} /> 當前位置</span>
        <em className="hint">滾輪縮放 · 拖曳平移 · 點擊跳轉</em>
      </div>
    </div>
  )
}
