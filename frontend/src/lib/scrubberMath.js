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

/**
 * 里程 → 群組序號（真實 seq 空間分數索引）。
 *
 * 在可視視窗 [v0, v1]（真實序號、v0<v1）內以 est 線性內插；超出時按該側斜率外插。
 * 支援遞增與遞減里程——所有除法保留符號（不得用 max(denom, ε) 夾正，
 * 否則遞減里程會產生巨大負索引、刻度全部塌縮亂擠）。
 */
export function mileageToIdx(est, m, v0, v1) {
  const n = est.length
  let lo = Math.max(0, Math.floor(v0))
  let hi = Math.min(n - 1, Math.ceil(v1))
  if (hi <= lo) return lo
  const eLo = est[lo]
  const eHi = est[hi]
  const loNext = est[Math.min(lo + 1, n - 1)]
  const hiPrev = est[Math.max(hi - 1, 0)]
  const slopeLo = loNext - eLo
  const slopeHi = eHi - hiPrev
  const minE = Math.min(eLo, eHi)
  const maxE = Math.max(eLo, eHi)
  if (m < minE) {
    // 落在較小里程之外：沿該側端點外插
    if (eHi < eLo) return slopeHi === 0 ? hi : hi + (m - eHi) / slopeHi
    return slopeLo === 0 ? lo : lo + (m - eLo) / slopeLo
  }
  if (m > maxE) {
    // 落在較大里程之外
    if (eHi > eLo) return slopeHi === 0 ? hi : hi + (m - eHi) / slopeHi
    return slopeLo === 0 ? lo : lo + (m - eLo) / slopeLo
  }
  for (let i = lo; i < hi; i++) {
    const a = est[i]
    const b = est[i + 1]
    if (a === b) continue
    if ((a <= m && m <= b) || (a >= m && m >= b)) {
      return i + (m - a) / (b - a)
    }
  }
  // 兜底二分（帶符號）
  const isInc = (est[0] ?? 0) <= (est[n - 1] ?? 0)
  let l = lo, h = hi
  while (h - l > 1) {
    const mid = (l + h) >> 1
    if (isInc ? est[mid] < m : est[mid] > m) l = mid
    else h = mid
  }
  const denom = est[h] - est[l]
  return l + (denom === 0 ? 0 : (m - est[l]) / denom)
}
