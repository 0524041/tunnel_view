# 修訂規格書 R3 — 版型、旋轉呈現與互動事件修復

> 狀態：`ready-for-agent` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1-alignment-review-display.md`、`revision-2-layout-nas-ux.md`
> 來源：使用者回報 — (1) 版型 2 欄預覽與實際不一致 (2) 頂拱左調整旋轉後點開無圖 (3) Console `Unable to preventDefault inside passive event listener` 刷屏
> 範圍：檢視器 CameraGrid 欄數、原圖覆蓋層旋轉呈現、滾輪/拖曳被動事件

---

## Problem Statement

1. **版型失效**：嚮導步驟二以 `repeat(colsNum,1fr)` 正確預覽 `2 欄 = 2×2`，但檢視器 `CameraGrid` 以 `cells.length (=4)` 推導為 4 欄單列，使用者質疑「預覽的用意何在」。
2. **旋轉後原圖空白**：八卦山 西行 `頂拱左`（原始 `orientation=6`）經資訊面板將 `camera_rotation` 改為 `90` 後，網格縮圖（`w=1600`）正常，但點擊開 `OriginalViewer` 原圖（`w=None`）僅見 EXIF/檔名、圖面空白。後端 `TestClient` 驗證 `GET /photos/1` 與 `?w=1600` 皆 `200`，縮圖快取 `1_1_1600_90.jpg` 正常，非 404/500。
3. **Console 刷屏**：滾輪縮放時 `index-*.js:8 Unable to preventDefault inside passive event listener invocation` 連續數十條，`CameraGrid` 與 `OriginalViewer` 的 `onWheel(e.preventDefault())` 在 Chrome 預設 `passive:true` 下失效。

## Solution

1. **版型**：讓 `CameraGrid` 與 `LayoutEditor` 共用 `resolveLayout` 的 `colsNum` 作為 `gridTemplateColumns` 欄數，而非 `cells.length`，達成所見即所得。
2. **旋轉**：統一「伺服器烘焙為準」語意。`CameraGrid` 已正確（伺服器 `rotate(-extra)` 後不做 CSS 旋轉）；`OriginalViewer` 過去「伺服器烘焙 + CSS `rotate(effAngle)`」導致淨旋轉不一致（縮圖 `-90`、原圖 `0`）且 `transformOrigin:0 0` 使圖片移出 `overflow:hidden` 視口。修復為原圖改 `transformOrigin:center` 並移除重複 CSS 旋轉（或改為僅 CSS、不烘焙，二選一以「僅伺服器」為準），並補 `onError` 佔位。
3. **被動事件**：滾輪縮放改以 `addEventListener('wheel', handler, {passive:false})` 註冊（`useEffect` + `ref`），或移除 `preventDefault` 改 `overscroll-behavior:contain`，消除刷屏且保留縮放體驗。

## User Stories

### 版型

1. As 檢測人員, I want 在嚮導選 `2 欄` 後檢視器以 2 欄 2 列呈現 4 台相機, so that 預覽與實際一致。
2. As 檢測人員, I want 選 `1 欄` 時為單欄垂直堆疊, so that 縱向捲動比對。
3. As 檢測人員, I want 選 `3 欄` 時為 3+1（含空位佔位）, so that 欄數語意與編輯器一致。
4. As 檢測人員, I want 選 `4 欄` 時為單列 4 欄, so that 寬螢幕一覽。
5. As 檢測人員, I want `auto` 仍依台數映射（4 台→2 欄）, so that 不設定也合理。
6. As 檢測人員, I want 空位以虛線佔位顯示, so that 版型空格可識別。
7. As 檢測人員, I want 交換兩格後即時反映, so that 版型是穩定決策。

### 旋轉呈現

8. As 檢測人員, I want 將 `頂拱左` 設為 `90` 後，網格縮圖與點開原圖皆為同一正確面向, so that 調整有意義。
9. As 檢測人員, I want 原圖彈窗內 `R` 旋轉與 `⟳` 按鈕皆即時更新且不黑畫面, so that 比例異常可就地修正。
10. As 檢測人員, I want `orientation=6/8` 的照片（頂拱左/左側壁/右側壁）在未設定旋轉時已自動轉正, so that 不需手動。
11. As 檢測人員, I want 單張 `rotation_override` 與整機 `camera_rotation` 的疊加語意明確（`override` 優先）, so that 個別修正不影響整機。

### 互動事件

12. As 檢測人員, I want 滾輪在照片格上縮放時不刷 console 警告, so that 開發者工具乾淨且縮放流暢。
13. As 檢測人員, I want 拖曳平移與滾輪縮放在 `cover/contain` 兩模式下皆一致, so that 檢視體驗統一。

## Implementation Decisions

### 版型（前端）

- 檢視器 `CameraGrid` 改 `const {colsNum,cells}=resolveLayout(meta,layoutCols)` 並 `style={{gridTemplateColumns:`repeat(${colsNum},1fr)`}}`，空位 `cells[i]==null` 仍以 `tile-missing tile-slot` 佔位。`ViewerPage` 的 `layoutCols` 來源（`info.layout_cols`）與 `resolveLayout` 規則不變。
- 不新增 Schema/API，`layout_cols` 儲存與 `PUT /layout`、`camera_updated/layout_updated` 廣播沿用 R2。

### 旋轉（前後端）

- **語意**：`extra = rotation_override ?? camera_rotation`。`api.py:photo` 對 `w=1600` 縮圖與 `w=None` 原圖皆 `ImageOps.exif_transpose`（處理 `orientation 6/8`）後 `rotate(-extra, expand=True)` 烘焙，前端不再重複旋轉。
- **OriginalViewer 修正**：`OriginalViewer.jsx:22,108-114` 移除 `rotate(${effAngle}deg)` 的重複 CSS，或改 `transformOrigin:center` 並將 `rotate` 置於 `translate/scale` 之前；`effAngle` 僅用於徽章顯示。`img` 補 `onError` 顯示「載入失敗」與重試，`key` 含 `extra` 使快取失效後重載。
- **CameraGrid 保持**：縮圖不做 CSS 旋轉，與後端一致。
- **快取**：`api.py:404` `cache = {tid}_{photo_id}_{suffix}_{extra}.jpg`，`TunnelInfoPanel.saveLayout` 調 `setCameraRotation` 後 `api.py:349` `_invalidate_cache(tid)` 已清全部，前端 `useTunnelSocket:camera_updated` 清 `cacheRef`，無需額外失效。

### 被動事件（前端）

- `CameraGrid.PhotoTile` 的 `onWheel` 與 `OriginalViewer` 的 `onWheel` 改 `useEffect` 內 `ref.current.addEventListener('wheel', handler, {passive:false})`，`handler` 內 `e.preventDefault()` 後執行 `applyZoomAt`。移除 React 合成事件的 `onWheel={onWheel}` 以避免被動默認。
- 替代方案：若保留合成事件，則 `e.preventDefault()` 改為不呼叫，改 CSS `overscroll-behavior:contain` + `touchAction:none`（`viewer.css:449` 已有）阻止頁面滾動，犧牲精確 `preventDefault` 但零警告。選前者以保留現有縮放體驗。
- 清理：`useEffect` 返回 `removeEventListener`。

### 不變項

- `importer.py:read_display_dims` 的顯示尺寸計算、`compute_aspect_anomalies` 的多數派比例判斷不變。
- R2 的 `grid_pos` 交換語意（拖曳/點選互換）不變。

## Testing Decisions

- **良好測試只驗外部行為**：斷言「給定 rotation/layout，看到的圖面尺寸與面向正確」，不綁定 `transform` 字串或 Pillow 內部呼叫。
- **主要縫**：
  - 純函式：`resolveLayout` 在 `1/2/3/4/auto` × 1–8 台 × `grid_pos` 交換/空位下的 `colsNum/rows/cells`（沿用 `AUTO_COLS`）。
  - API 整合：`TestClient` 對 `orientation=6/8` 且 `camera_rotation=90` 的照片，`GET /photos/{id}?w=1600` 與 `GET /photos/{id}` 皆 `200 image/jpeg` 且 `Image.open(cache).size` 符合預期（`5552×4160` 轉後），`PUT /cameras/{seq} {rotation:90}` 後快取檔名含 `_90` 且舊 `_0` 已刪。
  - 前端手動：嚮導 `2 欄` 預覽=檢視器 2×2；`頂拱左 90` 後縮圖與彈窗同向；`R` 鍵循環 0→90→180→270；Console 無 `preventDefault` 警告；滾輪縮放/拖曳在 `contain/cover` 皆正常。
- **Prior art**：`test_revision_api.py`（版型/旋轉/遷移）、`test_db.py: layout_cols`、既有 `e2e_check.py` 的 Playwright 全流程。
- **回歸**：`uv run pytest -q`（119 tests）與 `uv run python e2e_check.py ./八卦山西行` 在 `layout_cols=2` 隧道上重跑。

## Out of Scope

- 版型編輯器拖曳邏輯、跨欄/跨列 span、插入式擠位
- `grid_pos`/`layout_cols` 持久化格式變更、SCHEMA 升級
- 比例異常偵測演算法變更、里程內插
- 永久縮圖倉庫、NAS 掛載管理

## Further Notes

- 本修復兌現 R2「所見即所得」承諾；`2 欄` 在 5–8 台時會含 `rows*colsNum - n` 個空位，屬預期。
- 輪播的 `passive` 修復與 `viewer.css:449 touch-action:none` 互補；未來若改用 `wheel` 合成事件，需同步移除 `preventDefault`。
- 建議後續將 `OriginalViewer` 的 `effAngle` 計算改為僅顯示用，註解「烘焙已由後端完成」避免回歸。
