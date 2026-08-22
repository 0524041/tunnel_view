const RE = /^(?:K(\d+)\+(\d{1,3})|(\d+)K\+(\d{1,3})|(\d+)\+(\d{1,3})|(\d+))$/

export function parseMileage(text) {
  if (text == null) return null
  const s = String(text).trim().replace(/\s+/g, '').toUpperCase()
  const m = RE.exec(s)
  if (!m) return null
  if (m[7] !== undefined) return parseInt(m[7], 10)
  const km = m[1] ?? m[3] ?? m[5]
  const rest = m[2] ?? m[4] ?? m[6]
  return parseInt(km, 10) * 1000 + parseInt(rest, 10)
}

export function formatMileage(m) {
  if (!Number.isFinite(m)) return '—'
  const km = Math.floor(m / 1000)
  const rest = m % 1000
  return `K${km}+${String(rest).padStart(3, '0')}`
}
