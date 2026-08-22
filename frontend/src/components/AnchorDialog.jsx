import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { parseMileage, formatMileage } from '../lib/mileage'

export default function AnchorDialog({ tunnelId, seq, initial, prevAnchor, nextAnchor, onClose }) {
  const [text, setText] = useState(initial != null ? String(initial) : '')
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (initial != null) {
      setText((t) => (t === '' ? String(initial) : t))
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [initial])

  const parsed = parseMileage(text)

  const submit = async () => {
    if (parsed === null) {
      setError('格式無法解析')
      return
    }
    try {
      await api.putAnchor(tunnelId, seq, parsed)
      onClose()
    } catch (e) {
      setError(e.message)
      inputRef.current?.classList.add('error')
    }
  }

  const onKeyDown = (e) => {
    e.stopPropagation()
    if (e.key === 'Enter') submit()
    else if (e.key === 'Escape') onClose()
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" onKeyDown={onKeyDown}>
        <span className="label">錨定里程 · 群組 #{String(seq + 1).padStart(4, '0')}</span>
        <input
          ref={inputRef}
          className={`field mono ${error ? 'error' : ''}`}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setError('')
            inputRef.current?.classList.remove('error')
          }}
          placeholder="K23+150"
        />
        <p className="hint" style={{ marginTop: 8 }}>
          目前推算：<b className="mono" style={{ color: 'var(--amber)' }}>{initial != null ? `~${formatMileage(initial)}` : '—'}</b>
        </p>

        {(prevAnchor || nextAnchor) && (
          <div className="ctx-row mono">
            <span>{prevAnchor ? `← #${String(prevAnchor.group_seq + 1).padStart(4, '0')} ${formatMileage(prevAnchor.mileage_m)}` : ''}</span>
            <span>{nextAnchor ? `${formatMileage(nextAnchor.mileage_m)} #${String(nextAnchor.group_seq + 1).padStart(4, '0')} →` : ''}</span>
          </div>
        )}

        {parsed !== null && (
          <p className="hint">
            將寫入 <b className="mono" style={{ color: 'var(--blue)' }}>{formatMileage(parsed)}</b>
          </p>
        )}
        {error && <p className="err-text">{error} — 已阻擋寫入</p>}

        <div className="wiz-actions">
          <button type="button" className="btn" onClick={onClose}>取消（Esc）</button>
          <button type="button" className="btn primary" disabled={parsed === null} onClick={submit}>錨定（Enter）</button>
        </div>
      </div>
    </div>
  )
}
