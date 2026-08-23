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

import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { toast } from '../lib/toast'
import { formatMileage } from '../lib/mileage'
import AnnotationEditor from './AnnotationEditor'

export default function AnomalyOverview({ tunnelId, refreshKey, onLocate, onMetaRefresh }) {
  const [rows, setRows] = useState(null)
  const [counts, setCounts] = useState({})
  const [types, setTypes] = useState([])
  const [typeFilter, setTypeFilter] = useState('')
  const [q, setQ] = useState('')
  const [order, setOrder] = useState('asc')
  const [editing, setEditing] = useState(null)

  const load = useCallback(() => {
    api.anomalies(tunnelId, { typeId: typeFilter, q, order })
      .then(setRows)
      .catch((e) => toast(e.message, 'err'))
    // 計數不受類型篩選影響（僅隨搜尋關鍵字變動）
    api.anomalies(tunnelId, { q })
      .then((all) => {
        const c = {}
        for (const r of all) c[r.type_id] = (c[r.type_id] ?? 0) + 1
        setCounts(c)
      })
      .catch(() => {})
  }, [tunnelId, typeFilter, q, order])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  useEffect(() => {
    api.defectTypes().then(setTypes).catch(() => {})
  }, [refreshKey])

  const activeTypes = types.filter((t) => !t.archived)

  return (
    <div className="anomaly-page">
      <div className="anomaly-toolbar">
        <button
          type="button"
          className={`chip filter-chip ${typeFilter === '' ? 'on' : ''}`}
          onClick={() => setTypeFilter('')}
        >全部 · {rows?.length ?? '…'}</button>
        {activeTypes.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`chip filter-chip ${typeFilter === String(t.id) ? 'on' : ''}`}
            onClick={() => setTypeFilter(typeFilter === String(t.id) ? '' : String(t.id))}
          >
            {t.name} · {counts[t.id] ?? 0}
          </button>
        ))}
        <span className="vspacer" />
        <input
          className="field anomaly-search"
          placeholder="搜尋備註關鍵字…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          type="button"
          className="btn small"
          title="切換排序"
          onClick={() => setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))}
        >里程 {order === 'asc' ? '↑' : '↓'}</button>
      </div>

      {rows === null && <div className="cgrid-loading"><div className="spin" /></div>}

      {rows !== null && rows.length === 0 && (
        <div className="anomaly-empty">
          <p>目前沒有任何異狀紀錄。</p>
          <p className="hint">點擊照片格開啟原圖，按「🏷 異狀標註」（A）即可標記裂縫、滲漏水等缺陷。</p>
        </div>
      )}

      {rows !== null && rows.length > 0 && (
        <div className="anomaly-grid">
          {rows.map((r) => (
            <div key={r.anomaly_id} className="anomaly-card panel" onClick={() => setEditing(r)}>
              <div className="anomaly-thumb">
                <img src={api.photoUrl(tunnelId, r.photo_id, 480)} alt="" loading="lazy" />
                <span className="chip cam-chip">{r.camera_name}</span>
              </div>
              <div className="anomaly-body">
                <div className="mono anomaly-mile">{formatMileage(r.est_mileage_m ?? 0)}</div>
                <span className="chip ano-type">{r.type_name}</span>
                {(r.anomaly_note || r.photo_note) && (
                  <p className="hint anomaly-note">{r.anomaly_note || r.photo_note}</p>
                )}
                <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                  <button type="button" className="btn small" onClick={() => setEditing(r)}>✎ 編輯</button>
                  <button
                    type="button"
                    className="btn small ghost"
                    title="跳到檢視模式中的這張照片"
                    onClick={() => {
                      if (r.group_seq == null) return
                      onLocate(r)
                    }}
                  >📍 定位</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && setEditing(null)}>
          <div className="dialog anno-dialog">
            <div className="anno-dialog-head">
              <img src={api.photoUrl(tunnelId, editing.photo_id, 240)} alt="" />
              <div>
                <div className="mono list-main">{editing.rel_path}</div>
                <span className="hint">
                  {editing.camera_name} · {editing.group_seq != null ? `群組 #${String(editing.group_seq + 1).padStart(4, '0')} · ` : ''}
                  {formatMileage(editing.est_mileage_m ?? 0)}
                </span>
                <div className="row-actions" style={{ marginTop: 6 }}>
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => {
                      const row = editing
                      setEditing(null)
                      onLocate(row)
                    }}
                  >📍 在檢視器開啟</button>
                </div>
              </div>
              <button type="button" className="btn small ghost anno-close" onClick={() => setEditing(null)}>✕</button>
            </div>
            <AnnotationEditor
              tunnelId={tunnelId}
              photoId={editing.photo_id}
              onChanged={() => {
                load()
                onMetaRefresh?.()
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
