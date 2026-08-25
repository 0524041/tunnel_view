// Copyright (C) 2026 willywu <pop2585158@gmail.com>
// SPDX-License-Identifier: GPL-3.0-only

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  fmtMileage,
  pickStep,
  clampView,
  zoomView,
  followCurrent,
  idxToX,
  xToIdx,
} from './scrubberMath.js'

const EPS = 1e-6

test('fmtMileage 格式化樁號', () => {
  assert.equal(fmtMileage(0), 'K0+000')
  assert.equal(fmtMileage(27123), 'K27+123')
  assert.equal(fmtMileage(28500), 'K28+500')
})

test('pickStep 選出足夠寬的最小刻度', () => {
  assert.equal(pickStep(0.05), 5) // need=4.5 → 5
  assert.equal(pickStep(0.4), 50) // need=36 → 50
  assert.equal(pickStep(1), 100) // need=90 → 100
  assert.equal(pickStep(50), 2000) // 超過所有候選
})

test('clampView：滿縮時視窗必為 [0, n]——最前段不可被擠出畫面', () => {
  // 回歸測試：舊版允許 15% 越界，導致前 15% 群組點不到
  const n = 3000
  assert.deepEqual(clampView(n * 0.15, n * 1.15, n), [0, n])
  assert.deepEqual(clampView(-n * 0.15, n * 0.85, n), [0, n])
})

test('clampView：一般檢視不得越界且維持最小跨度', () => {
  const n = 3000
  let [a, b] = clampView(2998, 3010, n)
  assert.ok(b <= n && a >= 0)
  ;[a, b] = clampView(-50, -38, n)
  assert.deepEqual([Math.round(a), Math.round(b)], [0, 12]) // 跨度 12 ≥ 最小值，僅夾進邊界
  ;[a, b] = clampView(100, 103, n)
  assert.deepEqual([a, b], [100, 108]) // 跨度 <8 → 拉到最小 8
})

test('zoomView：游標下的群組位置不動（錨定縮放）', () => {
  const n = 3000
  const pad = 16
  const W = 1000
  const before = [100, 200]
  const cursorIdx = 150
  const xBefore = idxToX(cursorIdx, before[0], before[1], W, pad)
  const after = zoomView(before, cursorIdx, Math.exp(0.5), n)
  const xAfter = idxToX(cursorIdx, after[0], after[1], W, pad)
  assert.ok(Math.abs(xBefore - xAfter) < 0.01)
})

test('zoomView：滿縮上限為全部群組且含起點', () => {
  const n = 3000
  const after = zoomView([500, 520], 510, 1e6, n)
  assert.deepEqual(after, [0, n])
})

test('zoomView：最小跨度 8', () => {
  const after = zoomView([100, 200], 150, 1e-9, 3000)
  assert.equal(Math.round(after[1] - after[0]), 8)
})

test('followCurrent：範圍內不動', () => {
  assert.deepEqual(followCurrent([100, 160], 130, 3000), [100, 160])
})

test('followCurrent：current 跑出可視範圍時平移視窗跟上並夾在邊界內', () => {
  const n = 3000
  let v = followCurrent([100, 160], 90, n) // 往左跑出
  assert.ok(v[0] <= 90 && 90 <= v[1])
  v = followCurrent(v, 0, n) // 跳到最前面
  assert.ok(v[0] <= 0 + EPS)
  v = followCurrent([2900, 2960], 2999, n) // 往右跑出、貼右邊界
  assert.ok(v[1] <= n + EPS && v[0] <= 2999 && 2999 <= v[1])
})

test('followCurrent：維持原跨度', () => {
  const n = 3000
  const v = followCurrent([100, 260], 400, n)
  assert.equal(Math.round((v[1] - v[0]) * 100) / 100, 160)
})

test('idxToX / xToIdx 互為反函數', () => {
  const pad = 16
  const W = 1200
  const v = [40, 140]
  for (const idx of [40, 77.5, 140]) {
    const x = idxToX(idx, v[0], v[1], W, pad)
    assert.ok(Math.abs(xToIdx(x, v[0], v[1], W, pad) - idx) < 1e-9)
  }
})

import { mileageToIdx } from './scrubberMath.js'

test('mileageToIdx：遞增里程在區間內線性內插', () => {
  const est = Array.from({ length: 101 }, (_, i) => i * 10) // 0,10,...1000
  const idx = mileageToIdx(est, 505, 0, 100)
  assert.ok(idx > 49 && idx < 52, `idx=${idx}`)
})

test('mileageToIdx：遞增里程低於可視下界時向外插', () => {
  const est = Array.from({ length: 101 }, (_, i) => i * 10)
  const idx = mileageToIdx(est, -30, 20, 80)
  assert.ok(idx < 20, `idx=${idx}`)
})

test('mileageToIdx：遞減里程（反向隧道）同樣成立——回歸：不可全部塌縮成一點', () => {
  // 回歸測試：R8 版把顯示空間索引拿去 index est，反向時 hi<=lo 恆成立，
  // 所有刻度回傳同一點（全部擠到旁邊）
  const est = Array.from({ length: 101 }, (_, i) => 1000 - i * 10) // 1000→0
  const out = []
  for (let m = 0; m <= 1000; m += 100) {
    out.push(mileageToIdx(est, m, 0, 100))
  }
  // 不同里程必須對應不同索引且嚴格遞減
  for (let k = 1; k < out.length; k++) {
    assert.ok(out[k] < out[k - 1], `m=${k * 100}: ${out[k]} !< ${out[k - 1]}`)
  }
})

test('mileageToIdx：單調性——里程越大索引位置越靠該方向的深處', () => {
  const inc = Array.from({ length: 51 }, (_, i) => 27000 + i * 7)
  assert.ok(mileageToIdx(inc, 27200, 0, 50) > mileageToIdx(inc, 27100, 0, 50))
  const dec = Array.from({ length: 51 }, (_, i) => 30400 - i * 7)
  // 遞減：est[0]=30400 最大 → 里程越大、真實索引越小
  assert.ok(mileageToIdx(dec, 30200, 0, 50) > mileageToIdx(dec, 30300, 0, 50))
})
