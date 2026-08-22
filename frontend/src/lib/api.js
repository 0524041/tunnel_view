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

  photoUrl: (tid, photoId, w) =>
    `/api/tunnels/${tid}/photos/${photoId}${w ? `?w=${w}` : ''}`,
}
