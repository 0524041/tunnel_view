# 修訂規格書 R10 — 機位整體水平／垂直鏡像

> 狀態：`implemented` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1~9`
> 來源：使用者需求 — 既有機位 90° 旋轉外，需對整個機位做水平鏡像、垂直鏡像，且可再切回正常；確認不需要預建三套縮圖。

---

## Problem Statement

1. 既有機位方向只有 `rotation`（0/90/180/270），無法修正左右或上下顛倒的安裝方向。
2. 影像由後端實際轉向輸出，若只做前端 CSS 翻轉，重整、原圖與縮圖快取會不一致。
3. 鏡像必須是機位層級、作用於該機位全部照片，且可反覆開關。

## Solution

- **資料模型**：`cameras` 新增 `mirror_h`、`mirror_v`（0/1，預設 0）；隧道 schema 升 **v8**，舊庫冪等遷移補欄位。
- **匯入**：`CameraInput`、`CameraBody`、`ImportRequest`、`import_report.cameras` 攜帶鏡像旗標並寫入新隧道。
- **更新 API**：`PUT /api/tunnels/{tid}/cameras/{seq}` 接受 `mirror_h`、`mirror_v`；空更新錯誤訊息改為「需提供相機更新內容」；鏡像變更視為像素變更，遞增該機位全部照片 `pixel_version` 並清其縮圖，廣播 `camera_updated`。
- **渲染管線**：統一順序為 `EXIF transpose → 機位旋轉＋單張旋轉 → 水平／垂直鏡像 → 縮放`；Pillow 與 pyvips 雙軌一致。
- **快取相容**：正常模式沿用舊快取檔名；僅開啟鏡像時檔名附加鏡像鍵，不預建正常／水平／垂直三套。
- **讀取模型**：`info.cameras`、`get_window.photos`、`photo_render_info` 皆回傳鏡像旗標。
- **前端**：
  - Wizard 相機預設雙旗標 `false`，資料夾選擇器提供水平／垂直勾選與即時預覽。
  - `LayoutEditor` 共用控制：縮圖格提供水平、垂直、旋轉按鈕；詳細卡片提供鏡像切換。
  - 既有隧道資訊面板可持久化鏡像變更並刷新縮圖。
- **回退語意**：任一旗標再按一次即關閉；兩者可同時開啟；原檔不修改。

## Testing Decisions

- 沿用 HTTP API seam：機位鏡像開關可持久化、可再關閉；`info` 預設雙 `false`。
- 像素失效 seam：單一機位鏡像只遞增該機位照片版本，不影響其他機位。
- 縮圖 seam：Pillow 水平／垂直鏡像改變對應側像素。
- 遷移 seam：新隧道含鏡像欄位；版本期望值升至 `8`。
- 迴歸：`uv run pytest backend/tests/ -q` 全綠；`npm run build` 成功且 `frontend/dist` 入庫。

## Acceptance Criteria

1. 任一機位可獨立開啟水平或垂直鏡像，該機位全部照片同步翻轉。
2. 關閉旗標後同一機位照片恢復正常，不需重建隧道。
3. 正常模式不造成既有縮圖快取全部失效或重建。
4. 新建與既有隧道皆可設定鏡像；舊隧道開啟自動遷移。
5. pytest、前端建置全綠，`frontend/dist` 已更新。

## Out of Scope

- 單張照片層級鏡像。
- 任意角度旋轉或鏡像與旋轉之外的新幾何變換。
- 鏡像狀態的縮圖預生成策略變更。
