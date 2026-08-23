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

import { resolveLayout } from '../lib/layout'

const ROT_OPTIONS = [0, 90, 180, 270]

/**
 * 共用版型編輯器：嚮導步驟二與資訊面板「相機」頁籤共用。
 *
 * props:
 *  - cameras: [{ seq, name, rotation, grid_pos, folder? }]
 *  - thumbs:  { [seq]: 縮圖 URL }
 *  - cols:    'auto' | '1'..'4'
 *  - onChange({ cameras, cols }) — 交換/旋轉/欄數變更時回呼（父層決定持久化）
 *  - onPickFolder(index)         — 開啟資料夾選擇器
 *  - compact                     — 資訊面板模式（較小）
 */
export default function LayoutEditor({
  tunnelId,
  cameras,
  thumbs = {},
  cols = 'auto',
  onChange,
  onPickFolder,
  onRemoveCamera,
  onNameChange,
  compact = false,
}) {
  const { colsNum, cells } = resolveLayout(cameras, cols)

  const setRotation = (seq, rotation) => {
    onChange?.({
      cameras: cameras.map((c) => (c.seq === seq ? { ...c, rotation } : c)),
      cols,
    })
  }

  const setCols = (v) => {
    onChange?.({ cameras, cols: v })
  }

  const setName = (seq, name) => {
    onChange?.({
      cameras: cameras.map((c) => (c.seq === seq ? { ...c, name } : c)),
      cols,
    })
  }


  /**
   * 交換/搬移語意（以視覺格位索引為準）：
   * - 兩格皆有相機 → 雙方寫入對方的明確格位
   * - 目標為空位   → 來源寫入目標格位（來源原值捨棄，即為搬移）
   * grid_pos=-1 的互換若只交換 -1 是無效操作，因此一律落為明確數字。
   */
  const swapSlots = (i, j) => {
    if (i === j) {
      clickCell._sel = null
      return
    }
    const camA = cells[i]
    const camB = cells[j]
    if (!camA && !camB) {
      clickCell._sel = null
      return
    }
    const next = cameras.map((c) => ({ ...c }))
    if (camA) next.find((c) => c.seq === camA.seq).grid_pos = j
    if (camB) next.find((c) => c.seq === camB.seq).grid_pos = i
    clickCell._sel = null
    onChange?.({ cameras: next, cols })
  }

  const clickCell = (camSeq, slotIndex) => {
    if (clickCell._sel == null) {
      clickCell._sel = slotIndex
      clickCell._selSeq = camSeq
    } else {
      const prevSlot = clickCell._sel
      swapSlots(prevSlot, slotIndex)
    }
  }

  return (
    <div className={`layout-editor ${compact ? 'compact' : ''}`}>
      <div className="le-toolbar">
        <span className="label">版型</span>
        <select className="field mono le-cols" value={String(cols)} onChange={(e) => setCols(e.target.value)}>
          <option value="auto">自動</option>
          {[1, 2, 3, 4].map((n) => (
            <option key={n} value={String(n)}>{n} 欄</option>
          ))}
        </select>
        <span className="hint">拖曳或點選兩格互換位置</span>
      </div>

      <div
        className="le-grid"
        style={{ gridTemplateColumns: `repeat(${colsNum}, 1fr)` }}
      >
        {cells.map((cam, i) => (
          <div
            key={`cell-${i}`}
            className={`le-cell ${cam ? 'filled' : 'empty'} ${clickCell._sel === i ? 'selected' : ''}`}
            draggable={!!cam}
            onClick={() => (cam || clickCell._sel != null) && clickCell(cam?.seq ?? null, i)}
            onDragStart={(e) => {
              e.dataTransfer.setData('text/plain', String(i))
              clickCell._sel = null
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              const src = parseInt(e.dataTransfer.getData('text/plain'), 10)
              if (!Number.isNaN(src)) swapSlots(src, i)
            }}
          >
            {cam ? (
              <>
                {thumbs[cam.seq] && (
                  <img
                    src={thumbs[cam.seq]}
                    alt=""
                    style={{ transform: `rotate(${cam.rotation ?? 0}deg)` }}
                    className={(cam.rotation ?? 0) % 180 !== 0 ? 'rot90' : ''}
                    draggable={false}
                  />
                )}
                <span className="chip cam-chip">{cam.name}</span>
                <button
                  type="button"
                  className="le-rot mono"
                  title="旋轉 90°"
                  onClick={(e) => {
                    e.stopPropagation()
                    setRotation(cam.seq, ((cam.rotation ?? 0) + 90) % 360)
                  }}
                >⟳{cam.rotation ?? 0}</button>
              </>
            ) : (
              <span className="hint">空位</span>
            )}
          </div>
        ))}
      </div>

      {!compact && (
        <div className="le-cards">
          {cameras.map((c) => (
            <div key={c.seq} className="panel flag-card">
              <div className="mono list-main">
                #{String(c.seq).padStart(2, '0')}
                <span className="chip" style={{ marginLeft: 6 }}>格位 {c.grid_pos < 0 ? 'auto' : c.grid_pos + 1}</span>
              </div>
              <input
                className="field"
                value={c.name}
                placeholder="視角名稱"
                onChange={(e) => setName(c.seq, e.target.value)}
              />
              <div className="row-actions">
                {onPickFolder && (
                  <button type="button" className="btn small" onClick={() => onPickFolder(c.seq)}>📁 資料夾</button>
                )}
                <select
                  className="field mono"
                  style={{ width: 90 }}
                  value={c.rotation ?? 0}
                  onChange={(e) => setRotation(c.seq, parseInt(e.target.value))}
                >
                  {ROT_OPTIONS.map((r) => <option key={r} value={r}>{r}°</option>)}
                </select>
                {onRemoveCamera && (
                  <button
                    type="button"
                    className="btn danger small"
                    title="移除此相機"
                    disabled={cameras.length <= 1}
                    onClick={() => onRemoveCamera(c.seq)}
                  >✕</button>
                )}
              </div>
              {c.folder && <div className="mono hint" style={{ wordBreak: 'break-all' }}>{c.folder}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
