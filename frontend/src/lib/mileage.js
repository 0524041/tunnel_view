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
