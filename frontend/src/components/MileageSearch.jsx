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

import { useEffect, useRef, useState } from 'react'
import { parseMileage, formatMileage } from '../lib/mileage'

export default function MileageSearch({ onJump, onClose }) {
  const [text, setText] = useState('')
  const inputRef = useRef(null)
  const parsed = parseMileage(text)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const onKeyDown = (e) => {
    e.stopPropagation()
    if (e.key === 'Escape') onClose()
    else if (e.key === 'Enter' && parsed !== null) onJump(parsed)
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" onKeyDown={onKeyDown}>
        <span className="label">跳轉至里程</span>
        <input
          ref={inputRef}
          className={`field mono ${text && parsed === null ? 'error' : ''}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="K23+200 / 23K+200 / 23+200 / 23200"
        />
        <p className="hint" style={{ marginTop: 8 }}>
          {text && parsed !== null ? (
            <>跳轉至 <b className="mono" style={{ color: 'var(--amber)' }}>{formatMileage(parsed)}</b> 的最近群組</>
          ) : (
            '支援 K23+200、23K+200、23+200、23200 四種格式（整數公尺）'
          )}
        </p>
        <div className="wiz-actions">
          <button type="button" className="btn" onClick={onClose}>取消（Esc）</button>
          <button type="button" className="btn primary" disabled={parsed === null} onClick={() => onJump(parsed)}>
            跳轉（Enter）
          </button>
        </div>
      </div>
    </div>
  )
}
