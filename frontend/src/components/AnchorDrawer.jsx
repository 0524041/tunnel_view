const fmt = (m) => `K${Math.floor(m / 1000)}+${String(m % 1000).padStart(3, '0')}`

export default function AnchorDrawer({ open, anchors, current, onJump, onDelete }) {
  if (!open) return null
  return (
    <aside className="drawer">
      <div className="drawer-head">
        <span className="label" style={{ marginBottom: 0 }}>里程錨點 · {anchors.length}</span>
      </div>
      {anchors.length === 0 && (
        <p className="hint drawer-empty">
          尚無錨點。<br />瀏覽至實體里程牌畫面時按 <kbd className="mono">Enter</kbd> 輸入樁號，
          全線推算里程即會即時修正。
        </p>
      )}
      <div className="drawer-list">
        {anchors.map((a) => (
          <div key={a.group_seq} className={`anchor-row ${a.group_seq === current ? 'here' : ''}`}>
            <button type="button" className="ar-jump" onClick={() => onJump(a.group_seq)} title="跳轉至此群組">
              <b className="mono ar-mile">{fmt(a.mileage_m)}</b>
              <span className="mono ar-seq">群組 #{String(a.group_seq + 1).padStart(4, '0')}</span>
            </button>
            <button
              type="button"
              className="btn danger small"
              title="刪除錨點（還原為自動推算）"
              onClick={() => onDelete(a.group_seq)}
            >🗑</button>
          </div>
        ))}
      </div>
    </aside>
  )
}
