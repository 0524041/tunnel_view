const AUTO_COLS = { 1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4 }

/**
 * 解析版型：回傳實際欄數與格位陣列（null = 空位）。
 *
 * 規則（R2）：
 * - cols='auto' → 依台數的既有映射
 * - grid_pos >= 0 的相機優先入座；grid_pos=-1 者遞補剩餘空格
 * - 衝突（同格多人）時，後到者進入遞補佇列
 */
export function resolveLayout(cameras, cols) {
  const n = cameras.length
  const colsNum = cols === 'auto' ? AUTO_COLS[n] ?? Math.min(4, Math.max(1, Math.ceil(Math.sqrt(n)))) : Number(cols)
  const rows = Math.max(1, Math.ceil(n / colsNum))
  const cells = new Array(rows * colsNum).fill(null)

  const queue = []
  for (const cam of [...cameras].sort((a, b) => a.grid_pos - b.grid_pos || a.seq - b.seq)) {
    if (cam.grid_pos >= 0 && cam.grid_pos < cells.length && !cells[cam.grid_pos]) {
      cells[cam.grid_pos] = cam
    } else {
      queue.push(cam)
    }
  }
  for (let i = 0; i < cells.length && queue.length; i++) {
    if (!cells[i]) cells[i] = queue.shift()
  }
  return { colsNum, rows, cells }
}

export function autoColsFor(n) {
  return AUTO_COLS[n] ?? Math.min(4, Math.max(1, Math.ceil(Math.sqrt(n))))
}
