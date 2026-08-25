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

// 方向預覽容器：固定方框，CSS 旋轉模擬套用後的外觀（順時針 = 正角度，與後端一致）
function PreviewBox({ url, deg }) {
  return (
    <div style={{ width: 120, height: 90, display: 'grid', placeItems: 'center', overflow: 'hidden', background: 'rgba(0,0,0,.25)', borderRadius: 6 }}>
      {url ? (
        <img
          src={url}
          alt=""
          style={{
            maxWidth: deg % 180 === 90 ? 84 : 116,
            maxHeight: deg % 180 === 90 ? 84 : 86,
            transform: `rotate(${deg}deg)`,
            transition: 'transform .15s ease',
          }}
        />
      ) : (
        <span className="hint">…</span>
      )}
    </div>
  )
}

/**
 * 批次轉正對話框：列出混合直橫式的機位，選擇轉正方向，
 * 即時預覽「少數派樣本旋轉後」與「多數派參考照」並排比對。
 *
 * items: [{ seq, camera, landscape, portrait, minority }]
 */
export default function UnifyDialog({ tunnelId, items, onClose, onApplied }) {
  const [choices, setChoices] = useState(() => Object.fromEntries(items.map((s) => [s.seq, 'cw'])))
  const [samples, setSamples] = useState({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // 取樣：每個混合機位抓一張少數派照片＋一張多數派參考照
  useEffect(() => {
    let alive = true
    api.groups(tunnelId, 0, 10, 10).then((groups) => {
      if (!alive || !Array.isArray(groups)) return
      const photos = groups.flatMap((g) => g.photos || [])
      const out = {}
      for (const it of items) {
        const mine = photos.filter((p) => p.camera_seq === it.seq && p.width && p.height)
        if (!mine.length) continue
        const minorityIsPortrait = it.minority === 'portrait'
        out[it.seq] = {
          minorityPid: (mine.find((p) => p.width < p.height === minorityIsPortrait) || mine[0]).photo_id,
          majorityPid: mine.find((p) => p.width < p.height !== minorityIsPortrait)?.photo_id || null,
        }
      }
      setSamples(out)
    }).catch(() => {})
    return () => {
      alive = false
    }
  }, [tunnelId, items])

  const apply = async () => {
    setBusy(true)
    setErr('')
    try {
      for (const it of items) {
        const c = choices[it.seq]
        if (c === 'skip') continue
        await api.unifyCameraOrientation(tunnelId, it.seq, c === 'cw' ? 90 : 270)
      }
      onApplied?.()
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }

  const anyChosen = items.some((it) => choices[it.seq] !== 'skip')

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 80, display: 'grid', placeItems: 'center' }}
      onClick={busy ? undefined : onClose}
    >
      <div className="panel" style={{ minWidth: 560, maxWidth: 720, maxHeight: '85vh', overflow: 'auto', padding: 20 }} onClick={(e) => e.stopPropagation()}>
        <div className="display" style={{ marginBottom: 6 }}>批次轉正——混合直橫式機位</div>
        <p className="hint" style={{ marginTop: 0 }}>
          預覽＝左邊是「套用後」的少數派樣本，右邊是同機位多數派參考照。兩者牆面/拱頂方向一致即是正確角度。
        </p>

        {items.map((it) => {
          const c = choices[it.seq]
          const deg = c === 'cw' ? 90 : c === 'ccw' ? 270 : 0
          const s = samples[it.seq]
          return (
            <div key={it.seq} className="panel" style={{ padding: 12, marginTop: 10 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <b>{it.camera}</b>
                <span className="chip">橫 {it.landscape}</span>
                <span className="chip">直 {it.portrait}</span>
                <span className="chip amber">少數派＝{it.minority === 'portrait' ? '直式' : '橫式'}</span>
              </div>
              <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 10 }}>
                <div>
                  <div className="hint" style={{ textAlign: 'center', marginBottom: 4 }}>
                    轉後預覽{c !== 'skip' ? `（${c === 'cw' ? '↻ 順時針 90°' : '↺ 逆時針 90°'}）` : ''}
                  </div>
                  <PreviewBox url={s ? api.photoUrl(tunnelId, s.minorityPid, 320) : null} deg={deg} />
                </div>
                <div style={{ fontSize: 22 }}>vs</div>
                <div>
                  <div className="hint" style={{ textAlign: 'center', marginBottom: 4 }}>多數派參考</div>
                  <PreviewBox url={s?.majorityPid ? api.photoUrl(tunnelId, s.majorityPid, 320) : null} deg={0} />
                </div>
                <div style={{ marginLeft: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <button type="button" className={`btn small ${c === 'cw' ? 'primary' : ''}`} onClick={() => setChoices((m) => ({ ...m, [it.seq]: 'cw' }))}>↻ 順時針</button>
                  <button type="button" className={`btn small ${c === 'ccw' ? 'primary' : ''}`} onClick={() => setChoices((m) => ({ ...m, [it.seq]: 'ccw' }))}>↺ 逆時針</button>
                  <button type="button" className={`btn small ${c === 'skip' ? 'primary' : ''}`} onClick={() => setChoices((m) => ({ ...m, [it.seq]: 'skip' }))}>略過</button>
                </div>
              </div>
            </div>
          )
        })}

        {err && <p className="err-text">{err}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <button type="button" className="btn" disabled={busy} onClick={onClose}>取消</button>
          <button type="button" className="btn primary" disabled={busy || !anyChosen} onClick={apply}>
            {busy ? '套用中…' : '套用轉正'}
          </button>
        </div>
      </div>
    </div>
  )
}
