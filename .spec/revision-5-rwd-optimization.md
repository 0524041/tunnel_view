# 修訂規格書 R5 — RWD 全面優化與瀏覽器縮放修復

> 狀態：`ready-for-agent` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1-alignment-review-display.md`、`revision-2-layout-nas-ux.md`、`revision-3-camera-grid-layout-fix.md`、`revision-4-anomaly-annotation.md`
> 來源：使用者回報 — (1) 桌面版瀏覽器視窗比例變動時版面無對應變化 (2) 里程軌縮放時 console 刷 `Unable to preventDefault inside passive event listener` (3) 手機檢視體驗待優化
> 範圍：全站 RWD、字級與縮放、觸控手勢、里程軌被動事件修復

---

## Problem Statement

1. **桌面縮放無反應**：瀏覽器視窗拉寬/拉窄或 `Ctrl +/-` 縮放時，相機網格欄數、側欄寬度與軌道刻度不重算，導致寬螢幕留白、窄螢幕擠壓。
2. **縮放刷錯誤**：在里程軌（及照片瓦片）上滾輪縮放時，React 合成 `onWheel` 預設為 `passive:true`，內部 `preventDefault()` 觸發 `Unable to preventDefault inside passive event listener` 並連續刷屏數十條，雖不影響功能但污染 console 並可能丟失縮放手勢。
3. **手機體驗不足**：`cgrid` 欄數固定（依 `layoutCols` 1-4），390px 寬下 4 欄極擠；字級全 `px` 不跟系統字級；側欄覆蓋無遮罩與手勢關閉；原圖側板 320px 在手機佔 85% 寬度。

## Solution

1. **Fluid RWD**：字級與間距改 `rem` + `clamp()`，網格改 `auto-fit + minmax(160px,1fr)` 並以 Container Query 讓欄數隨容器寬度自動退為 1-2 欄；側欄與原圖面板在窄視口轉為 Bottom Sheet。
2. **被動事件修復**：滾輪縮放改以 `addEventListener('wheel', handler, {passive:false})` 註冊（`useEffect` + `ref`），或移除 `preventDefault` 改 `overscroll-behavior:contain` + `touch-action:none`，消除刷屏且保留縮放體驗。
3. **視口與縮放跟隨**：`html {font-size:16px}` 基準 + `rem` 全替換，`height:100dvh` 取代 `overflow:hidden` 固定高度，使瀏覽器縮放與 OS 放大皆等比生效；軌道與網格監聽 `ResizeObserver` 即時重繪。

## User Stories

### 桌面自適應

1. As 桌機使用者, I want 拖曳瀏覽器邊緣改變寬度時網格欄數與間距平滑重排, so that 寬螢幕不留白、窄視窗不擠壓。
2. As 桌機使用者, I want 按 `Ctrl +/-` 縮放時字級與版面等比縮放, so that 視力需求可被滿足。
3. As 桌機使用者, I want 調高 OS 系統字級時介面字級跟隨放大, so that 無障礙需求生效。
4. As 檢測人員, I want 在 1920px 與 1280px 間切換時側欄保持 300/320px 且內容不被裁切, so that 資訊可讀。

### 被動事件修復

5. As 檢測人員, I want 在里程軌上滾輪縮放時 console 乾淨無 `preventDefault` 警告, so that 開發者工具可用且縮放流暢。
6. As 檢測人員, I want 在照片瓦片上滾輪縮放同樣無警告, so that 兩處體驗一致。
7. As 檢測人員, I want 滾輪縮放時頁面本身不跟著捲動, so that 焦點留在軌道/照片上。

### 手機與平板

8. As 手機使用者, I want 直向 375px 時相機網格自動退為 1-2 欄, so that 每格足夠大可辨識。
9. As 手機使用者, I want 頂欄 `搜尋/完整/檢視|異狀` 在窄螢幕橫向可滑動而非換行擠壓, so that 操作仍可觸及。
10. As 手機使用者, I want 側欄（錨點/資訊）以 Bottom Sheet（55dvh，拖曳手柄）呈現並有遮罩點關閉, so that 不遮擋主視圖且可手勢關閉。
11. As 手機使用者, I want 原圖的異狀面板在手機時置底（42dvh）且可收合為 48px 標題列, so that 原圖可視區足夠。
12. As 手機使用者, I want 里程軌在 640px 以下僅顯示主刻度、圖例縮為 3 項, so that 不擁擠。
13. As 觸控使用者, I want 雙指捏合可縮放照片與軌道, 左右滑動可切群組, so that 無滑鼠也可操作。
14. As 平板使用者, I want 768-1024px 時網格為 2-3 欄、側欄仍為側邊而非覆蓋, so that 空間利用合理。

## Implementation Decisions

### 字級與視口

- `html` 維持 16px 基準，全站 `px` 字級改 `rem`（`14px→0.875rem` 等），`border/outline` 保留 `px`；間距與圖例字級改 `clamp()` 流體值。`base.css` 的 `body{overflow:hidden; height:100%}` 改 `min-height:100dvh`，`viewer` 改 `height:100dvh` 以支援 iOS 工具列與 `dvh`。

### 網格與容器

- 相機網格由固定 `repeat(colsNum,1fr)` 改 `repeat(auto-fit, minmax(160px,1fr))` 並以 `container-type:inline-size` 讓欄數隨容器寬度自適應；`layoutCols` 轉為 `max-cols` 上限而非強制值。間距改 `gap:clamp(4px,1vw,6px)`。

### 頂欄與側欄

- 頂欄在 `≤768px` 將次要按鈕收為圖示，按鈕群 `overflow-x:auto` 可橫滑；`≤640px` 時 `vread` 僅留 `Kxxx+xxx`。
- 側欄在 `≤1024px` 從 `absolute` 側抽屜改 Bottom Sheet（`height:55dvh; border-radius:12px 12px 0 0;` 拖曳手柄，三態：關閉/半開/全開），背景加半透明遮罩，點遮罩關閉。

### 原圖與軌道

- 原圖 `orig-mainrow` 在 `≤768px` 轉 `flex-direction:column`，側板從 `width:320px; border-left` 轉 `height:42dvh; border-top` 置底，預設收合。
- 軌道在 `≤640px` 高度 56→44px，僅主刻度標籤，圖例 5→3 項，快捷鍵字串截短，`rail-help` 放大至 36px 觸控目標。

### 被動事件（前端）

- 里程軌與照片瓦片的 `onWheel` 改 `useEffect` 內 `ref.current.addEventListener('wheel', handler, {passive:false})`，`handler` 內 `e.preventDefault()` 後執行縮放；移除 React 合成 `onWheel` 以避免被動預設。`useEffect` 返回 `removeEventListener`。替代方案：保留合成事件但移除 `preventDefault`，改 CSS `overscroll-behavior:contain` + `touch-action:none`（`viewer.css` 已有）阻止頁面捲動。選前者以保留現有縮放體驗。

### 視窗變動

- 軌道與網格的 `ResizeObserver` 已存在於軌道，擴大至網格容器；瀏覽器 `resize` 與 `visualViewport` 變動時重算 `colsNum` 與刻度密度，無需新增 API。

### 不變項

- `resolveLayout` 的 `auto` 映射規則與 `grid_pos` 交換語意不變，僅增加容器自適應層。
- 後端無變更，`frontend/dist` 需重建。

## Testing Decisions

- **良好測試只驗外部行為**：斷言「給定視口寬度，看到的欄數/字級符合預期」與「滾輪縮放時 console 無警告」，不綁定 `transform` 字串或事件註冊細節。
- **主要縫**：
  - 純樣式：Playwright 視口矩陣 `375/768/1024/1680` 截圖對比（`e2e_check.py` 擴充），斷言 `cgrid` 欄數與 `rail-legend` 換行
  - 互動：`wheel` 事件在軌道與瓦片上觸發後 `console` 無 `preventDefault` 警告（`page.on("console")` 收集）
  - 可及性：`html` 字級改 `rem` 後，`page.evaluate(()=>getComputedStyle(document.documentElement).fontSize)` 隨 `page.setViewportSize` 變動
- **Prior art**：`e2e_check.py` 的 Playwright 全流程、`test_revision_api.py` 的版型測試、`viewer.css` 現有斷點。
- **回歸**：`uv run pytest -q` 全綠與 `vite build` 成功。

## Out of Scope

- 後端里程內插、對齊引擎、異狀標註資料模型變更
- 圖片多解析度 `srcset`（縮圖仍 `w=1600`，後續再議）
- 深色主題切換、i18n

## Further Notes

- 本修復兌現 R4「常駐側板在手機過寬」的遺留問題；`320px` 側板在 375px 的過寬由 Bottom Sheet 解決。
- 被動事件修復與 `viewer.css:touch-action:none` 互補；未來若改用合成事件，需同步移除 `preventDefault`。
- `frontend/dist` 為提交物，重建後需一併提交。
