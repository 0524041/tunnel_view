# 修訂規格書 R9 — 縮圖管線改造、掃描快取持久化、隧道專案分組

> 狀態：`ready-for-agent` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1~8`
> 來源：效能盤點（評分 7/10）＋ 使用者建檔需求 — 同一條隧道會多次掃描（西行／東行／不同年份），首頁平鋪列表難以歸檔與搜尋；部署環境為 Windows WSL，套件一律經 uv 管理。
> 實測基礎：EXIF 掃描瓶頸 99% 為網路往返（16 workers 已近供應商限流）；縮圖冷生成於請求執行緒同步解碼 NAS 原檔；libvips 官方 benchmark 1000 張 JPEG resize 1.2s vs Pillow 5.4s（約 4.5x）、尖峰記憶體 18MB vs 420MB。

---

## Problem Statement

1. **縮圖冷啟風暴**：縮圖採查詢時惰性生成，首次瀏覽長隧道時每張 w=1600 都要在請求執行緒內開 NAS 原檔＋解碼＋縮放，造成白屏等待，並擠佔 FastAPI 共享 thread pool 拖累其他 API。
2. **無差別縮圖失效**：annotation、mark_missing、realign apply 等**不改變像素**的操作也呼叫 `_invalidate_cache` 清掉整條隧道的縮圖快取（7 個呼叫點中僅 3 個真的改變像素），改個備註就要全隧道重新生成。
3. **HTTP 快取缺置**：圖片回應未帶 `Cache-Control`、不做 If-None-Match 304 判斷；前端 `cr=/pr=` cache-buster 參數後端根本忽略，反覆翻頁可能整張重下。
4. **每次 serve 重開原檔讀 orientation**：`_needs_exif_transpose` 每請求開一次檔讀 EXIF tag 274，DB 已存 width/height 卻沒存 orientation。
5. **Job 易失**：匯入 job 只存記憶體（TTL 15min／LRU 8），server 重啟或逾時後 commit 觸發整批 NAS 重掃（數分鐘）。`.scan_cache.db` 只有遺跡端點、無人寫入。
6. **視窗查詢 N+1**：`get_window` 對 75 群約發 150 queries/request。
7. **無專案歸檔**：同一隧道多次掃描在首頁平鋪堆疊，無法以「專案」歸檔、無搜尋、無最近使用入口。

## Solution

- **A. 縮圖管線改造**
  - **像素版本機制**：`photos` 新增 `pixel_version`（整數，預設 0），僅真正改變像素的操作遞增：相機旋轉、unify（機位全體）、單張旋轉（該張）。前端 `photoUrl()` 帶 `&pv={n}` 取代虛設的 cr/pr；縮圖回應帶 `Cache-Control: public, max-age=31536000, immutable`。原檔 fast path 帶 `Cache-Control: public, max-age=3600` ＋既有 ETag（不 immutable，原檔可能被外部取代）。
  - **精準失效**：刪除 annotation PUT、mark_missing、realign apply 三處 `_invalidate_cache` 呼叫；改像素操作改為「遞增 pixel_version ＋ 刪除該照片（或該機位各照片）舊縮圖檔」，不留孤兒檔。
  - **orientation 入庫**：隧道 schema 升 v6，`photos.orientation` 於掃描時一併寫入（`read_exif_and_dims` 本來就讀了）；serve 時改查 DB。既有隧道欄位為 NULL 時 lazy backfill（首次 serve 開檔讀一次並 UPDATE，之後永久走 DB）。
  - **pyvips 雙軌**：`uv add "pyvips[binary]"`（PyPI 官方 binary wheel 自帶 libvips，Linux x64/WSL 免 apt）；新增縮圖模組，ImportError 時退回 Pillow 現行 draft() 邏輯。品質參數維持 quality=87。
  - **背景預生成**：commit 完成後排背景 daemon worker 逐張（依群組序）生成 w=1600 縮圖，跳過已存在者；失敗靜默（留待請求時重試）。worker 數 `TUNNELVIEW_THUMB_WORKERS` 預設 **4**（NAS 友善、不擠佔瀏覽請求）。**single-flight**：模組級 `(tid, pid, w)` 鎖，背景 worker 與請求內生成共用，同一張不重複解碼、併發請求等待同一結果。480px 不預生成。
- **B. 掃描快取持久化**
  - index.db 新增 `scan_cache(folder_root, rel_path, size, mtime, exif_time, time_source, width, height, orientation, PRIMARY KEY(folder_root, rel_path))`。`scan()` 先將該 folder_root 全表載入記憶體 dict，size+mtime 相符即免開檔，不符才讀檔並 UPSERT。跨隧道共用。接上既有 `DELETE /api/cache/scan` 端點清空。
  - **job 落地**：index.db 新增 `import_jobs(job_id PK, status, stage, done, total, preview_json NULL, error NULL, created_at)`。TTL 24h、上限 32（超額清最舊）。server 啟動時將 running 標記為 **interrupted**；輪詢回 interrupted，前端提示「伺服器曾重啟，請重新執行分析」；commit 帶 interrupted job 走 fingerprint 失配＝正常重掃。不自動續跑。
- **C. get_window 批次化**：N+1 改單一 JOIN 查詢後組裝，回應形狀不變（前端零改動）。
- **D. 隧道專案分組**
  - index.db 新增 `projects(id PK, name, created_at)` **單層**（不巢狀）；`tunnels` 加 `project_id NULL REFERENCES projects(id) ON DELETE SET NULL`、`last_opened_at NULL`。隧道名稱維持自由文字（方向／年份寫在名稱裡，不做獨立欄位）。
  - API：`GET/POST /api/projects`、`PUT/DELETE /api/projects/{id}`（刪除＝底下隧道回未分類）、`POST /api/tunnels/{tid}/move {project_id|null}`、`POST /api/tunnels` body 加 `project_id`、`GET /api/tunnels` 回應加 project 資訊與 `last_opened_at`。進入 ViewerPage 時（`GET /api/tunnels/{tid}/info`）更新 `last_opened_at`。
  - HomePage：頂部「最近使用」顯示最近 **5 條隧道**（依 last_opened_at DESC，卡片標注所屬專案）；主體為專案摺疊列表（排前、依名稱）＋未分類隧道（依建立時間）；「⋯」選單提供移動到…（彈出專案挑選器，可就地新建）、改名、刪除（刪除專案＝底下隧道回未分類，需確認對話框）；Wizard 建立隧道步驟加「所屬專案」下拉（可新建）。**不做拖放**（之後加分項）。
  - 搜尋：首頁一個搜尋框，輸入即時**前端過濾**，同時比對專案名＋隧道名；匹配專案顯示整個專案、匹配隧道只顯示該隧道。不做後端搜尋 API。
- **E. 性能量測工具**：新增唯讀基準腳本（沿襲 bench_import.py 慣例），以工作區既有的 `./八卦山西行`（804 張、4 機位真實照片）與 `data/tunnel_*.db` 量測優化前後差異（見 Testing Decisions）。

## User Stories

1. As a 巡檢員, I want 剛建立的隧道點進去照片立即呈現（已在背景預生成）, so that 不再面對白屏等待。
2. As a 巡檢員, I want 翻閱過的照片再次瀏覽時從瀏覽器快取直接呈現, so that 來回巡視流暢且省頻寬。
3. As a 巡檢員, I want 標註缺陷、寫備註、標記缺照時畫面不重載圖片, so that 標註作業連貫不被打斷。
4. As a 巡檢員, I want 旋轉照片或批次轉正後立刻看到新方向的縮圖, so that 確認修正生效而不會看到舊圖。
5. As a 巡檢員, I want 對同一批照片第二次執行分析時秒級完成, so that 反覆調校容差不用每次等數分鐘。
6. As a 巡檢員, I want 原始照片被更動（mtime 改變）後重新分析能取得新結果, so that 快取不會欺騙我。
7. As a 巡檢員, I want server 重啟後提交分析結果時收到明確的「請重新分析」提示, so that 我知道系統誠實重掃而不是莫名卡住。
8. As a 巡檢員, I want 分析完成後一小時內回來按「確認建立」仍免二次掃描, so that 中斷的工作流程不被懲罰。
9. As a 部署者, I want libvips 缺失或載入失敗時自動退回 Pillow, so that 部署永不因選配套件而失敗。
10. As a 部署者（WSL）, I want 所有新依賴都能用 uv 安裝管理, so that 不需要額外的系統套件程序。
11. As a 巡檢員, I want 把西行／東行／不同年份的多條隧道歸入同一個專案, so that 建檔有序。
12. As a 巡檢員, I want 建立隧道時直接指定所屬專案（可就地新增專案）, so that 歸檔一步完成。
13. As a 巡檢員, I want 把既有隧道移動到其他專案或移回未分類, so that 歸檔可事後調整。
14. As a 巡檢員, I want 刪除專案時底下隧道自動回到未分類, so that 不會誤刪任何隧道資料。
15. As a 巡檢員, I want 首頁頂部看到最近使用的 5 條隧道, so that 日常巡檢一键直达。
16. As a 巡檢員, I want 一個搜尋框同時過濾專案名與隧道名, so that 大量建檔後仍能快速定位。
17. As a 巡檢員, I want 專案可以改名, so that 命名錯誤可修正。
18. As a 巡檢員, I want 未分類的隧道永遠有清楚的位置, so that 沒有任何隧道會消失不見。
19. As a 開發者, I want 基準腳本量化二次掃描、縮圖冷熱路徑、視窗查詢的改善幅度, so that 效能提升可被驗證而非口說。
20. As a 開發者, I want 既有 132+ 測試與 e2e 全綠, so that 重構不破壞現有行為。

## Implementation Decisions

- **Schema**：
  - index.db：新增 `projects`、`scan_cache`、`import_jobs` 三表；`tunnels` 加 `project_id`、`last_opened_at`（冪等 ALTER，沿襲既有 migration 慣例）。
  - 隧道 DB：schema v5 → **v6**，`photos` 加 `orientation INTEGER`（NULL=未知）、`pixel_version INTEGER NOT NULL DEFAULT 0`。
- **縮圖服務模組**：統一進入點 `make_thumbnail(path, target_w) -> bytes`，內部 pyvips（`access="sequential"` ＋ thumbnail_image ＋ jpegsave_buffer quality=87）或 Pillow（draft() ＋ BILINEAR）雙軌；呼叫方（請求內與背景 worker）皆經 single-flight 鎖。
- **URL 契約**：`GET /api/tunnels/{tid}/photos/{pid}?w=&pv=`；`pv` 進入 Cache-Control immutable 語意；`groups`/`overview` 回應的 photo 物件附帶 `pixel_version`；前端移除 cr/pr。
- **失效語意**：`bump_pixel_version(tid, photo_ids)`＝UPDATE version＋unlink 該照片舊縮圖；相機層級操作（旋轉/unify）對機位全體照片逐一執行；annotation/mark_missing/realign/merge/restore 不再碰快取。
- **掃描快取**：`scan()` 於列檔後先載入該 folder_root 的快取 dict；命中判定 `size == cached.size and mtime == cached.mtime`；`preview→commit` 復用機制與 fingerprint 保持不變，快取在其之下獨立運作。
- **Job 生命週期**：`running → done | failed | interrupted`；interrupted 僅由啟動還原產生；preview_json 持久化使 commit 復用不受重啟影響的前提是狀態為 done 且 fingerprint 相符。
- **專案 API 形狀**：projects 列表含 `tunnel_count`；tunnels 列表含 `project_id/project_name/last_opened_at`；排序固定：專案（前，依名稱）→ 未分類隧道（依建立時間），不做自訂排序欄位。
- **last_opened_at 更新點**：僅 `GET /api/tunnels/{tid}/info`（即進入檢視器）觸發，其他讀取端點不更新。
- **部署**：`uv add "pyvips[binary]"`；WSL Ubuntu 免 apt；run.sh/run.bat 無需變更。

## Testing Decisions

- **接縫（最高優先沿用既有）**：
  1. **HTTP API seam**（FastAPI TestClient，沿襲 `test_revision_api.py`/`test_api.py`）：Cache-Control/pv 契約、304 行為、失效呼叫點的行為差異（改備註後縮圖檔仍在；旋轉後 pixel_version 遞增且舊檔清除）、projects/move/info-touch 端點、job persisted/interrupted 流程、scan cache 命中（spy 開檔計數）。
  2. **Importer/service 單元 seam**（沿襲 `test_importer.py`）：快取命中/失敗（size、mtime 各自變動）輸出與直讀一致；orientation 寫入；pyvips/Pillow 雙軌各自產出合法 JPEG。
  3. **效能驗證 seam**（新工具腳本，唯讀、沿襲 `tools/bench_import.py` 介面慣例）：以 `./八卦山西行`（804 張真實照片）與 `data/tunnel_f0443406efcc.db` 量測並印出：(a) EXIF 掃描第一遍（填快取）vs 第二遍（全命中）耗時與倍率；(b) 縮圖冷生成平均延遲 vs 快取命中延遲；(c) get_window 查詢耗時（JOIN 化前後）。**驗收門檻**：二次掃描 ≥10x 加速（或絕對值 <5s）；縮圖熱路徑明顯低於冷路徑（目標 <50ms 本地碟）；get_window 呈單一查詢。無大量照片時即以 804 張實測外推，腳本支援 `--sample` 抽樣。
- **好測試的定義**：只驗外部行為（HTTP 回應、檔案存在性、DB 可觀察狀態、腳本輸出的數值門檻），不測內部函式呼叫細節；唯一例外是 spy 開檔計數（快取命中與否本質上就是 IO 次數）。
- **迴歸**：`uv run pytest backend/tests/ -q` 全綠；`node --test frontend/src/lib/*.test.js` 全綠；`cd frontend && npx oxlint src` 無新警告；`npm run build` 成功且 dist 入庫；`uv run python e2e_check.py ./八卦山西行` 通過。

## Acceptance Criteria

1. 縮圖回應（含 pv）帶 `Cache-Control: public, max-age=31536000, immutable`；原檔 fast path 帶 `max-age=3600`＋ETag；重複請求帶 If-None-Match 得 304。
2. annotation/mark_missing/realign/merge 操作前後，受影響照片的縮圖檔與 pixel_version **均不改變**；相機旋轉/unify/單張旋轉後 pixel_version 遞增、舊縮圖清除、前端取得新圖。
3. 新隧道匯入後 photos.orientation 全數入庫；既有隧道首次 serve 後 orientation 完成 lazy backfill；serve 路徑不再開檔讀 EXIF tag 274（以 spy 驗證）。
4. commit 完成後背景 worker 生成全部 1600px 縮圖；生成期間同時請求同一張不觸發第二次解碼（single-flight）；worker 數受 env 控制。
5. 同一資料夾第二次 `scan()` 對未變動檔案零開檔；size 或 mtime 變動的檔案重新讀取且快取更新；`DELETE /api/cache/scan` 清空後恢復全掃。
6. job 持久化：重啟模擬（重建 app）後 done job 的 preview 仍可被 fingerprint 相符的 commit 復用；running job 變 interrupted；前端輪詢顯示重啟提示；TTL 24h／上限 32 生效。
7. get_window 對 75 群視窗只發 1 次照片查詢（JOIN），回應形狀與現行完全一致。
8. 專案 CRUD、move、刪除回退未分類、info 觸碰 last_opened_at、最近使用 5 條、搜尋即時過濾（比對專案＋隧道名）全部符合 Implementation Decisions 描述。
9. pyvips 移除（模擬 ImportError）時全系統以 Pillow 運作，測試雙軌皆綠。
10. 效能基準腳本產出報告且達 Testing Decisisons 所列門檻；pytest／node test／oxlint/e2e 全綠。

## Out of Scope

- 拖放式移動（DnD）UI——列為之後加分項。
- 自訂拖曳排序（sort_order 欄位）。
- 多對多標籤、巢狀子資料夾。
- 480px 縮圖預生成；WebP/AVIF 格式轉換。
- 後端搜尋 API（前端過濾已足）。
- Job 自動續跑（重掃＋誠實提示已是正確語意）。
- 縮圖快取的常駐 GC 背景（僅隨寫隨清）。

## Further Notes

- **WSL 部署**：`uv add "pyvips[binary]"` 即完成，官方 binary wheel 支援 Linux x64，自帶 libvips 共享庫；缺 PDF/OpenSlide 功能但我們只用 JPEG，無影響。若 binary wheel 在目標環境不可用，fallback Pillow 保證功能正確、僅損失生成速度。
- **授權**：所有新檔案維持 GPL-3.0-only 檔頭慣例。
- **前端**：prebuilt `frontend/dist` 入庫，完成後需 rebuild。
- 效能基準腳本命名沿襲 `tools/` 目錄慣例（如 `bench_perf.py`），唯讀、不寫庫、不動原檔。
