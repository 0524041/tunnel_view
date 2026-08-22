async function handle(resp) {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body.detail) detail = body.detail
    } catch {}
    const err = new Error(detail)
    err.status = resp.status
    throw err
  }
  return resp.json()
}

export const api = {
  listTunnels: () => fetch('/api/tunnels').then(handle),

  previewImport: (body) =>
    fetch('/api/tunnels/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),

  createTunnel: (body) =>
    fetch('/api/tunnels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),

  overview: (tid) => fetch(`/api/tunnels/${tid}/overview`).then(handle),

  groups: (tid, around, before, after) =>
    fetch(`/api/tunnels/${tid}/groups?around=${around}&before=${before}&after=${after}`).then(handle),

  nearestByMileage: (tid, m) =>
    fetch(`/api/tunnels/${tid}/groups/by_mileage?m=${m}`).then(handle),

  anchors: (tid) => fetch(`/api/tunnels/${tid}/anchors`).then(handle),

  putAnchor: async (tid, seq, mileageM) => {
    const r = await fetch(`/api/tunnels/${tid}/anchors/${seq}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mileage_m: mileageM }),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail || `HTTP ${r.status}`)
    }
  },

  deleteAnchor: async (tid, seq) => {
    const r = await fetch(`/api/tunnels/${tid}/anchors/${seq}`, { method: 'DELETE' })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(body.detail || `HTTP ${r.status}`)
    }
  },

  photoUrl: (tid, photoId, w, photo) => {
    let u = `/api/tunnels/${tid}/photos/${photoId}`
    const qs = []
    if (w) qs.push(`w=${w}`)
    if (photo) {
      qs.push(`cr=${photo.camera_rotation ?? 0}`)
      qs.push(`pr=${photo.rotation_override ?? -1}`)
    }
    return u + (qs.length ? `?${qs.join('&')}` : '')
  },

  reviewPhoto: async (tid, pid, result) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ result }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  },

  resetReview: async (tid, pid) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/reset_review`, { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  fsList: (path) =>
    fetch(`/api/fs/list?path=${encodeURIComponent(path || '')}`).then(handle),

  fsPhotoUrl: (path) => `/api/fs/photo?path=${encodeURIComponent(path)}`,

  info: (tid) => fetch(`/api/tunnels/${tid}/info`).then(handle),

  deleteTunnel: async (tid) => {
    const r = await fetch(`/api/tunnels/${tid}`, { method: 'DELETE' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  },

  confirmFlag: async (tid, pid) => {
    const r = await fetch(`/api/tunnels/${tid}/photos/${pid}/confirm_flag`, { method: 'POST' })
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
}
