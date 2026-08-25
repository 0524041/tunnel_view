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

import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { formatMileage } from '../lib/mileage'

// created_at 由 SQLite datetime('now') 產生＝UTC；updated_at 為本機 ISO
function fmtDateTime(s, utc = false) {
  if (!s) return null
  const d = new Date(utc ? String(s).replace(' ', 'T') + 'Z' : s)
  if (isNaN(d)) return null
  const p = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function TunnelCard({ t, projectName, onOpen, onDelete, onMove }) {
  const createdAt = fmtDateTime(t.created_at, true)
  const updatedAt = fmtDateTime(t.updated_at)
  return (
    <button type="button" className="tunnel-card panel" onClick={() => onOpen(t.tunnel_id, t.name)}>
      <div className="tc-top">
        <span className="display tc-name">{t.name}</span>
        <span className="chip">{t.camera_count} 台相機</span>
      </div>
      {projectName && <div className="hint" style={{ textAlign: 'left' }}>📁 {projectName}</div>}
      <div className="mono tc-range">
        {formatMileage(t.start_m)} <span className="arrow">⟶</span> {formatMileage(t.end_m)}
      </div>
      {(createdAt || updatedAt) && (
        <div className="hint mono" style={{ textAlign: 'left', fontSize: 11 }}>
          建 {createdAt || '—'}
          {updatedAt && updatedAt !== createdAt ? ` · 改 ${updatedAt}` : ''}
        </div>
      )}
      <div className="tc-foot hint">
        <span>開啟檢視 <span className="mono">#{String(t.tunnel_id).padStart(3, '0')}</span></span>
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button
            type="button"
            className="btn small"
            title="移動到其他專案"
            onClick={(e) => { e.stopPropagation(); onMove(t) }}
          >📁 移動</button>
          <button
            type="button"
            className="btn danger small tc-del"
            title="刪除此隧道"
            onClick={(e) => { e.stopPropagation(); onDelete(t) }}
          >🗑 刪除</button>
        </span>
      </div>
    </button>
  )
}

export default function HomePage({ onOpenTunnel, onNewTunnel }) {
  const [tunnels, setTunnels] = useState(null)
  const [projects, setProjects] = useState([])
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState(() => new Set())
  const [moveTarget, setMoveTarget] = useState(null) // 隧道物件
  // 專案輸入視窗：{ mode:'create', moveTo:tunnel|null } | { mode:'rename', project }
  const [projModal, setProjModal] = useState(null)

  const refresh = () => {
    api.listTunnels().then(setTunnels).catch(() => {})
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }
  useEffect(() => {
    refresh()
  }, [])

  const q = query.trim().toLowerCase()
  const hasQ = q.length > 0

  // 搜尋過濾：比對到專案名 → 整個專案顯示；只比對到隧道名 → 僅顯示該隧道
  const filteredByProject = useMemo(() => {
    const out = new Map() // project_id -> tunnels[]
    for (const p of projects) {
      if (!out.has(p.id)) out.set(p.id, [])
    }
    for (const t of tunnels || []) {
      if (!out.has(t.project_id)) out.set(t.project_id, [])
      out.get(t.project_id).push(t)
    }
    return out
  }, [tunnels, projects])

  const visibleProjects = useMemo(() => {
    const hitT = (t) => !hasQ || String(t?.name || '').toLowerCase().includes(q)
    const hitP = (p) => !hasQ || String(p?.name || '').toLowerCase().includes(q)
    return projects
      .filter((p) => hitP(p) || (filteredByProject.get(p.id) || []).some(hitT))
      .map((p) => ({
        ...p,
        tunnels: (filteredByProject.get(p.id) || []).filter((t) => hitP(p) || hitT(t)),
      }))
  }, [projects, filteredByProject, hasQ, q])

  const ungrouped = useMemo(() => {
    return (filteredByProject.get(null) || []).filter(
      (t) => !hasQ || String(t?.name || '').toLowerCase().includes(q)
    )
  }, [filteredByProject, hasQ, q])

  const recents = useMemo(() => {
    if (hasQ) return []
    return [...(tunnels || [])]
      .filter((t) => t.last_opened_at)
      .sort((a, b) => String(b.last_opened_at).localeCompare(String(a.last_opened_at)))
      .slice(0, 5)
  }, [tunnels, hasQ])

  const removeTunnel = (t) => {
    if (!window.confirm(`確定刪除「${t.name}」？\n此操作會移除對齊資料與所有錨點，且無法復原（照片原檔不受影響）。`)) return
    api.deleteTunnel(t.tunnel_id).then(refresh).catch((e) => alert(e.message))
  }

  const toggleCollapse = (pid) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(pid)) {
        next.delete(pid)
      } else {
        next.add(pid)
      }
      return next
    })
  }

  const doMove = async (projectId) => {
    try {
      await api.moveTunnel(moveTarget.tunnel_id, projectId ?? null)
      setMoveTarget(null)
      refresh()
    } catch (e) {
      alert(e.message)
    }
  }

  // 專案輸入視窗確認：create（可選擇順手把隧道移入）或 rename
  const submitProjModal = async (name) => {
    if (!name || !name.trim()) return
    const trimmed = name.trim()
    try {
      if (projModal.mode === 'rename') {
        if (trimmed === projModal.project.name) return setProjModal(null)
        await api.renameProject(projModal.project.id, trimmed)
      } else {
        const p = await api.createProject(trimmed)
        if (projModal.moveTo) {
          await api.moveTunnel(projModal.moveTo.tunnel_id, p.id)
          setMoveTarget(null)
        }
      }
      setProjModal(null)
      refresh()
    } catch (e) {
      alert(e.message)
    }
  }

  const deleteProject = (p) => {
    if (!window.confirm(`確定刪除專案「${p.name}」？\n底下 ${p.tunnel_count} 條隧道會回到未分類，隧道本身不受影響。`)) return
    api.deleteProject(p.id).then(refresh).catch((e) => alert(e.message))
  }

  const renderCard = (t) => (
    <TunnelCard
      key={t.tunnel_id}
      t={t}
      onOpen={onOpenTunnel}
      onDelete={removeTunnel}
      onMove={setMoveTarget}
    />
  )

  const empty = tunnels !== null && (tunnels || []).length === 0

  return (
    <div className="home">
      <header className="home-hero display">
        <h1>隧道多視角檢視平台</h1>
        <p className="hint">多相機同步影像 · 即時里程錨定 · 公尺級定位</p>
      </header>

      <main className="home-body">
        <div className="home-head">
          <input
            className="field"
            style={{ maxWidth: 320 }}
            placeholder="🔍 搜尋專案或隧道…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span style={{ display: 'inline-flex', gap: 8 }}>
            <button type="button" className="btn" onClick={() => setProjModal({ mode: 'create', moveTo: null })}>＋ 新增專案</button>
            <button type="button" className="btn primary" onClick={onNewTunnel}>＋ 建立新隧道</button>
          </span>
        </div>

        {tunnels === null && (
          <div className="home-loading"><div className="spin" /></div>
        )}

        {empty && (
          <div className="empty panel">
            <svg width="72" height="40" viewBox="0 0 96 52" fill="none" aria-hidden>
              <path d="M4 50V30C4 15.5 15.5 4 30 4s26 11.5 26 26v20" stroke="#2a2f37" strokeWidth="3" />
              <path d="M18 50V32a12 12 0 0 1 24 0v18" stroke="#2a2f37" strokeWidth="2" />
              <line x1="60" y1="50" x2="92" y2="50" stroke="#2a2f37" strokeWidth="2" />
              <circle cx="76" cy="38" r="5" stroke="#ffb300" strokeWidth="2" opacity="0.6" />
            </svg>
            <p>尚無隧道專案</p>
            <p className="hint">建立第一條隧道，匯入各相機資料夾即可開始檢視</p>
          </div>
        )}

        {recents.length > 0 && (
          <section style={{ marginBottom: 28 }}>
            <span className="label">最近使用</span>
            <div className="cards">
              {recents.map((t) => (
                <TunnelCard
                  key={`r-${t.tunnel_id}`}
                  t={t}
                  projectName={projects.find((p) => p.id === t.project_id)?.name || null}
                  onOpen={onOpenTunnel}
                  onDelete={removeTunnel}
                  onMove={setMoveTarget}
                />
              ))}
            </div>
          </section>
        )}

        {visibleProjects.map((p) => (
          <section key={`p-${p.id}`} style={{ marginBottom: 24 }}>
            <div className="home-head" style={{ marginBottom: 10 }}>
              <button
                type="button"
                className="label"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
                onClick={() => toggleCollapse(p.id)}
                title={collapsed.has(p.id) ? '展開' : '收合'}
              >
                {collapsed.has(p.id) ? '▸' : '▾'} 📁 {p.name}
                <span className="chip" style={{ marginLeft: 8 }}>{p.tunnels.length}</span>
              </button>
              <span style={{ display: 'inline-flex', gap: 6 }}>
                <button type="button" className="btn small" onClick={() => setProjModal({ mode: 'rename', project: p })}>✏️ 改名</button>
                <button type="button" className="btn danger small" onClick={() => deleteProject(p)}>🗑 刪除專案</button>
              </span>
            </div>
            {!collapsed.has(p.id) && (
              <div className="cards">
                {p.tunnels.length === 0 && <p className="hint" style={{ gridColumn: '1/-1' }}>此專案尚無隧道</p>}
                {p.tunnels.map(renderCard)}
              </div>
            )}
          </section>
        ))}

        {(ungrouped.length > 0 || (q && ungrouped.length === 0 && visibleProjects.length === 0 && tunnels?.length)) && (
          <section style={{ marginBottom: 24 }}>
            <span className="label">📁 未分類</span>
            {ungrouped.length >= 3 && !q && (
              <p className="hint" style={{ margin: '4px 0 0' }}>
                💡 有 {ungrouped.length} 條隧道未歸檔。點上方「＋ 新增專案」建立案子（例：台76線八卦山隧道），
                再用各卡片的「📁 移動」把西行／東行／不同年份的隧道收進去。
              </p>
            )}
            <div className="cards" style={{ marginTop: 10 }}>
              {ungrouped.length === 0
                ? <p className="hint" style={{ gridColumn: '1/-1' }}>沒有符合搜尋的隧道</p>
                : ungrouped.map(renderCard)}
            </div>
          </section>
        )}
        {q && visibleProjects.length === 0 && ungrouped.length === 0 && tunnels?.length > 0 && (
          <p className="hint">沒有符合「{query}」的專案或隧道</p>
        )}
      </main>

      {moveTarget && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 60,
            display: 'grid', placeItems: 'center',
          }}
          onClick={() => setMoveTarget(null)}
        >
          <div className="panel" style={{ minWidth: 320, padding: 20 }} onClick={(e) => e.stopPropagation()}>
            <div className="display" style={{ marginBottom: 12 }}>
              移動「{moveTarget.name}」到：
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button type="button" className="btn" onClick={() => doMove(null)}>📁 未分類</button>
              {projects.map((p) => (
                <button key={p.id} type="button" className="btn" onClick={() => doMove(p.id)}>
                  📁 {p.name}{moveTarget.project_id === p.id ? '（目前）' : ''}
                </button>
              ))}
              <button type="button" className="btn primary" onClick={() => setProjModal({ mode: 'create', moveTo: moveTarget })}>＋ 新增專案並移入</button>
              <button type="button" className="btn" onClick={() => setMoveTarget(null)}>取消</button>
            </div>
          </div>
        </div>
      )}

      {projModal && (() => {
        const isRename = projModal.mode === 'rename'
        const title = isRename ? '重新命名專案' : '新增專案'
        const initial = isRename ? projModal.project.name : ''
        const close = () => setProjModal(null)
        const submit = () => submitProjModal(document.getElementById('proj-name-input')?.value)
        return (
          <div
            style={{
              position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 70,
              display: 'grid', placeItems: 'center',
            }}
            onClick={close}
          >
            <div className="panel" style={{ minWidth: 320, padding: 20 }} onClick={(e) => e.stopPropagation()}>
              <div className="display" style={{ marginBottom: 12 }}>
                {title}
                {!isRename && projModal.moveTo && (
                  <span className="hint" style={{ marginLeft: 8 }}>建立後將「{projModal.moveTo.name}」移入</span>
                )}
              </div>
              <input
                id="proj-name-input"
                className="field"
                placeholder="專案名稱，例：台14線鳥踏坑隧道"
                defaultValue={initial}
                onKeyDown={(e) => e.key === 'Enter' && submit()}
                autoFocus
              />
              <p className="hint" style={{ marginTop: 8 }}>
                專案＝案子層級（如「台76線八卦山隧道」）；底下可放西行／東行／不同年份的多條隧道。
              </p>
              <div style={{ display: 'flex', gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
                <button type="button" className="btn" onClick={close}>取消</button>
                <button type="button" className="btn primary" onClick={submit}>確定</button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
