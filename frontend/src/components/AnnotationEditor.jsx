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

import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { toast } from '../lib/toast'

let keySeq = 1

export default function AnnotationEditor({ tunnelId, photoId, onChanged, footer }) {
  const [note, setNote] = useState('')
  const [items, setItems] = useState([])
  const [types, setTypes] = useState([])
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [newType, setNewType] = useState('')
  const [showTypeMgr, setShowTypeMgr] = useState(false)

  useEffect(() => {
    let alive = true
    setDirty(false)
    Promise.all([
      api.annotation(tunnelId, photoId),
      api.defectTypes(),
    ]).then(([anno, ts]) => {
      if (!alive) return
      setNote(anno.note ?? '')
      setItems(anno.items.map((i) => ({ key: `k${keySeq++}`, id: i.id, type_id: i.type_id, note: i.note ?? '', type_name: i.type_name })))
      setTypes(ts)
    }).catch((e) => toast(e.message, 'err'))
    return () => {
      alive = false
    }
  }, [tunnelId, photoId])

  const activeTypes = types.filter((t) => !t.archived)
  const typeNameOf = (tid) => types.find((t) => t.id === tid)?.name ?? '?'

  const addItem = () => {
    if (!activeTypes.length) {
      toast('請先新增類型', 'err')
      return
    }
    setItems((xs) => [...xs, { key: `k${keySeq++}`, id: null, type_id: activeTypes[0].id, note: '' }])
    setDirty(true)
  }

  const patchItem = (key, patch) => {
    setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...patch } : x)))
    setDirty(true)
  }

  const removeItem = (key) => {
    setItems((xs) => xs.filter((x) => x.key !== key))
    setDirty(true)
  }

  const save = async () => {
    // 前端預檢：避免送出 NaN / undefined 導致後端 422 變成 Object,Object
    for (const it of items) {
      if (!Number.isFinite(it.type_id) || !types.some((t) => t.id === it.type_id)) {
        toast(`異狀類型無效（id=${String(it.type_id)}），請重新選擇`, 'err')
        return
      }
    }
    setBusy(true)
    try {
      const result = await api.setAnnotation(tunnelId, photoId, note, items)
      // 用後端回傳的正規化結果覆蓋本地，避免 id:null 殘留導致重複送出
      setNote(result.note ?? '')
      setItems(result.items.map((i) => ({ key: `k${keySeq++}`, id: i.id, type_id: i.type_id, note: i.note ?? '', type_name: i.type_name })))
      setDirty(false)
      onChanged?.()
      toast('已儲存')
    } catch (e) {
      const msg = e && typeof e.message === 'string' ? e.message : (() => { try { return JSON.stringify(e); } catch { return String(e); } })()
      toast(msg || '儲存失敗', 'err')
    } finally {
      setBusy(false)
    }
  }

  const addType = async () => {
    const name = newType.trim()
    if (!name) return
    try {
      const t = await api.addDefectType(name)
      setTypes((xs) => [...xs, t].sort((a, b) => a.id - b.id))
      setNewType('')
      onChanged?.()
    } catch (e) {
      toast(e.message, 'err')
    }
  }

  const removeType = async (t) => {
    try {
      const { action } = await api.removeDefectType(t.id)
      if (action === 'archived') {
        toast(`「${t.name}」已封存（既有紀錄保留顯示）`)
        setTypes((xs) => xs.map((x) => (x.id === t.id ? { ...x, archived: true } : x)))
      } else {
        toast(`「${t.name}」已刪除`)
        setTypes((xs) => xs.filter((x) => x.id !== t.id))
        setItems((xs) => xs.filter((x) => x.type_id !== t.id))
        setDirty(true)
      }
      onChanged?.()
    } catch (e) {
      toast(e.message, 'err')
    }
  }

  return (
    <div className="anno-editor">
      <div className="anno-field">
        <span className="label">照片備註</span>
        <textarea
          className="field anno-note"
          rows={2}
          placeholder="此照片的補充說明…"
          value={note}
          onChange={(e) => {
            setNote(e.target.value)
            setDirty(true)
          }}
        />
      </div>

      <div className="anno-field">
        <span className="label">異狀 {items.length > 0 && `· ${items.length}`}</span>
        {items.length === 0 && <p className="hint">尚未標註異狀。</p>}
        {items.map((it) => (
          <div key={it.key} className="anno-item">
            <select
              className="field"
              value={it.type_id}
              onChange={(e) => patchItem(it.key, { type_id: Number(e.target.value) })}
            >
              {activeTypes.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
              {!activeTypes.some((t) => t.id === it.type_id) && (
                <option value={it.type_id}>{typeNameOf(it.type_id)}（已封存）</option>
              )}
            </select>
            <input
              className="field"
              placeholder="備註（選填）"
              value={it.note}
              onChange={(e) => patchItem(it.key, { note: e.target.value })}
            />
            <button type="button" className="btn small danger" title="移除此異狀" onClick={() => removeItem(it.key)}>✕</button>
          </div>
        ))}
        <button type="button" className="btn small" onClick={addItem}>＋ 新增異狀</button>
      </div>

      <div className="anno-types">
        <button type="button" className="btn small ghost" onClick={() => setShowTypeMgr((v) => !v)}>
          {showTypeMgr ? '▾' : '▸'} 類型管理（{activeTypes.length}）
        </button>
        {showTypeMgr && (
          <>
            <div className="anno-typelist">
              {types.map((t) => (
                <span key={t.id} className={`chip ${t.archived ? 'dim' : ''}`}>
                  {t.name}{t.archived ? '（封存）' : ''}
                  {!t.archived && (
                    <button type="button" className="anno-x" title={`刪除／封存「${t.name}」`} onClick={() => removeType(t)}>×</button>
                  )}
                </span>
              ))}
            </div>
            <div className="anno-addtype">
              <input
                className="field"
                placeholder="新類型名稱，如：施工縫滲水"
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addType()}
              />
              <button type="button" className="btn small" onClick={addType}>＋ 新增類型</button>
            </div>
            <p className="hint">類型為所有隧道專案共用；已被使用的類型刪除時會自動封存。</p>
          </>
        )}
      </div>

      {footer}
      <div className="anno-save">
        <button type="button" className="btn primary small" disabled={!dirty || busy} onClick={save}>
          {busy ? '儲存中…' : dirty ? '儲存標註' : '已儲存'}
        </button>
      </div>
    </div>
  )
}
