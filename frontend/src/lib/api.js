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

function _formatDetail(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === 'string') return d
        if (d && typeof d.msg === 'string') {
          const loc = Array.isArray(d.loc) ? d.loc.slice(1).join('.') : ''
          return loc ? `${loc}: ${d.msg}` : d.msg
        }
        try {
          return JSON.stringify(d)
        } catch {
          return String(d)
        }
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail)
}

async function handle(resp) {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body.detail != null) detail = _formatDetail(body.detail)
      else if (body.message) detail = String(body.message)
    } catch {}
    const err = new Error(String(detail))
    err.status = resp.status
    throw err
  }
  return resp.json()
}

export const api = {
  listTunnels: () => fetch('/api/tunnels').then(handle),

  renameTunnel: async (tid, name) => {
    const r = await fetch(`/api/tunnels/${tid}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    return handle(r)
  },

  previewImport: (body) =>
    fetch('/api/tunnels/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),

  // 背景 job 版：立即回 running，輪詢 getImportJob 取掃描進度
  createImportJob: (body) =>
    fetch('/api/import/jobs/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),

  getImportJob: (id) => fetch(`/api/import/jobs/${id}`).then(handle),

  createTunnel: (body, jobId) =>
    fetch(`/api/tunnels${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),

  unifyCameraOrientation: async (tid, seq, angle) => {
    const r = await fetch(`/api/tunnels/${tid}/cameras/${seq}/unify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ angle }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  },

  orientationStats: (tid) => fetch(`/api/tunnels/${tid}/orientation-stats`).then(handle),

  overview: (tid) => fetch(`/api/tunnels/${tid}/overview`).then(handle),

  groups: (tid, around, before, after) =>
    fetch(`/api/tunnels/${tid}/groups?around=${around}&before=${before}&after=${after}`).then(handle),

  nearestByMileage: (tid, m) =>
    fetch(`/api/tunnels/${tid}/groups/by_mileage?m=${m}`).then(handle),

  setGroupHidden: async (tid, seq, hidden) => {
    const r = await fetch(`/api/tunnels/${tid}/groups/${seq}/visibility`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden }),
    })
    return handle(r)
  },

  anchors: (tid) => fetch(`/api/tunnels/${tid}/anchors`).then(handle),

  putAnchor: async (tid, seq, mileageM) => {
    const r = await fetch(`/api/tunnels/${tid}/anchors/${seq}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mileage_m: mileageM }),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail != null ? _formatDetail(body.detail) : `HTTP ${r.status}`)
    }
  },

  deleteAnchor: async (tid, seq) => {
    const r = await fetch(`/api/tunnels/${tid}/anchors/${seq}`, { method: 'DELETE' })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail != null ? _formatDetail(body.detail) : `HTTP ${r.status}`)
    }
  },

  photoUrl: (tid, photoId, w, photo) => {
    let u = `/api/tunnels/${tid}/photos/${photoId}`
    const qs = []
    if (w) qs.push(`w=${w}`)
    // R9：像素版本入 URL → 後端回 immutable 快取標頭；旋轉等操作遞增版本自然失效
    if (photo?.pixel_version != null) qs.push(`pv=${photo.pixel_version}`)
    return u + (qs.length ? `?${qs.join('&')}` : '')
  },

  listProjects: () => fetch('/api/projects').then(handle),

  createProject: async (name) => {
    const r = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    return handle(r)
  },

  // 專案管理端點沿用本檔既有的簡潔錯誤風格（見 deleteTunnel/markMissing）
  renameProject: async (id, name) => {
    const r = await fetch(`/api/projects/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail != null ? _formatDetail(body.detail) : `HTTP ${r.status}`)
    }
  },

  deleteProject: async (id) => {
    const r = await fetch(`/api/projects/${id}`, { method: 'DELETE' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  moveTunnel: async (tid, projectId) => {
    const r = await fetch(`/api/tunnels/${tid}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  cameraThumbs: (tid) => fetch(`/api/tunnels/${tid}/camera_thumbs`).then(handle),

  setCameraGridPos: async (tid, seq, gridPos) => {
    const r = await fetch(`/api/tunnels/${tid}/cameras/${seq}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grid_pos: gridPos }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  setLayoutCols: async (tid, cols) => {
    const r = await fetch(`/api/tunnels/${tid}/layout`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cols }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  fsList: (path) =>
    fetch(`/api/fs/list?path=${encodeURIComponent(path || '')}`).then(handle),

  fsPhotoUrl: (path, w) => {
    const qs = `path=${encodeURIComponent(path)}${w ? `&w=${w}` : ''}`
    return `/api/fs/photo?${qs}`
  },

  info: (tid) => fetch(`/api/tunnels/${tid}/info`).then(handle),

  deleteTunnel: async (tid) => {
    const r = await fetch(`/api/tunnels/${tid}`, { method: 'DELETE' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  markMissing: async (tid, pid) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/mark_missing`, { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  restorePhoto: async (tid, pid) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/restore`, { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  realignPreview: (tid, tolerance) =>
    fetch(`/api/tunnels/${tid}/realign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tolerance_seconds: tolerance }),
    }).then(handle),

  realignApply: async (tid, tolerance) => {
    const r = await fetch(`/api/tunnels/${tid}/realign/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tolerance_seconds: tolerance }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  },

  mergeGroup: async (tid, seq, direction, keep) => {
    const r = await fetch(`/api/tunnels/${tid}/groups/${seq}/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction, keep: keep ?? null }),
    })
    if (r.status === 409) {
      const body = await r.json()
      const err = new Error(body.detail?.message || '需裁決')
      err.conflictCameras = body.detail?.conflict_cameras || []
      throw err
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  },

  setCameraRotation: async (tid, seq, rotation) => {
    const r = await fetch(`/api/tunnels/${tid}/cameras/${seq}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rotation }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  setPhotoRotation: async (tid, pid, angle) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/rotation`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ angle }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  defectTypes: () => fetch('/api/defect-types').then(handle),

  addDefectType: async (name) => {
    const r = await fetch('/api/defect-types', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    return handle(r)
  },

  removeDefectType: async (id) => {
    const r = await fetch(`/api/defect-types/${id}`, { method: 'DELETE' })
    return handle(r)
  },

  annotation: (tid, pid) => fetch(`/api/tunnels/${tid}/photos/${pid}/annotation`).then(handle),

  setAnnotation: async (tid, pid, note, items) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/annotation`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        note: note ?? null,
        items: items.map((i) => ({ id: i.id ?? null, type_id: i.type_id, note: i.note ?? null })),
      }),
    })
    return handle(r)
  },

  anomalies: (tid, { typeId = '', q = '', order = 'asc' } = {}) => {
    const qs = new URLSearchParams()
    if (typeId) qs.set('type_id', typeId)
    if (q) qs.set('q', q)
    qs.set('order', order)
    return fetch(`/api/tunnels/${tid}/anomalies?${qs}`).then(handle)
  },

  exportAnomalies: async (tid, { typeId = '', q = '', order = 'asc', format = 'xlsx' } = {}) => {
    const qs = new URLSearchParams()
    if (typeId) qs.set('type_id', typeId)
    if (q) qs.set('q', q)
    qs.set('order', order)
    qs.set('format', format)
    const r = await fetch(`/api/tunnels/${tid}/anomalies/export?${qs}`)
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail != null ? _formatDetail(body.detail) : `HTTP ${r.status}`)
    }
    const blob = await r.blob()
    const disposition = r.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match ? match[1] : `anomalies.${format}`
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },

  setCameraName: async (tid, seq, name) => {
    const r = await fetch(`/api/tunnels/${tid}/cameras/${seq}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },
}
