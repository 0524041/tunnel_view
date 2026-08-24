// Copyright (C) 2026 willywu <pop2585158@gmail.com>
// SPDX-License-Identifier: GPL-3.0-only

// 里程條檢視數學（純函式）：檢視窗夾限、縮放錨定、跟隨當前群組、座標映射。
// 由 ScrubberRail 使用；以 node --test 驗證。

export const STEP_CANDIDATES = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]

export function fmtMileage(m) {
  return `K${Math.floor(m / 1000)}+${String(Math.round(m % 1000)).padStart(3, '0')}`
}

export function pickStep(metersPerPx, minPx = 90) {
  const need = metersPerPx * minPx
  for (const s of STEP_CANDIDATES) {
    if (s >= need) return s
  }
  return 2000
}

/**
 * 夾限檢視窗：視窗必須完全落在 [0, n] 內（不得越界——舊版允許 15% 越界，
 * 導致滿縮時最前段群組被擠出畫面、滑鼠點不到），並維持最小跨度 8。
 */
export function clampView(a, b, n) {
  let s = b - a
  if (s < 8) s = Math.min(8, n)
  if (n - s < 1e-9) return [0, n]
  a = Math.max(0, Math.min(a, n - s))
  return [a, a + s]
}

/** 以游標所在群組為錨縮放：k>1 放大跨度（縮小細節）、k<1 聚焦。 */
export function zoomView(view, idxAtCursor, k, n) {
  const [v0, v1] = view
  let span = Math.max(8, Math.min((v1 - v0) * k, n))
  let a = idxAtCursor - ((idxAtCursor - v0) / Math.max(v1 - v0, 1e-9)) * span
  return clampView(a, a + span, n)
}

/** current 離開可視範圍時平移視窗跟上（保持跨度、夾在邊界內）。 */
export function followCurrent(view, current, n) {
  const [a, b] = view
  if (current >= a && current <= b) return view
  const span = b - a
  return clampView(current - span / 2, current + span / 2, n)
}

/** 群組序號 → 像素 x（顯示座標系，反轉由呼叫端先行換算）。 */
export function idxToX(idx, v0, v1, W, pad) {
  return pad + ((idx - v0) / Math.max(v1 - v0, 1e-6)) * (W - pad * 2)
}

/** 像素 x → 群組序號（idxToX 的反函數）。 */
export function xToIdx(px, v0, v1, W, pad) {
  return v0 + ((px - pad) / Math.max(W - pad * 2, 1e-9)) * (v1 - v0)
}
