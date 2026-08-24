# 修訂規格書 R6 — 匯入效能、進度可視化與大檔量健壯性修復

> 狀態：`ready-for-agent` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1~5`
> 來源：使用者回報 — (1) NAS 1萬張量級場景下「分析中」耗時極長且無進度條 (2) 預覽/提交重複全掃 (3) `scanned_by_pid` 同檔名碰撞等匯入 bug (4) 時間容差即時調整（realign）往返漂移：1.5s→2s→1.5s 群組數不一致，錨點需跟照片走且 mileage 不可變
> 範圍：匯入管線（掃描→解 EXIF→對齊→寫庫）、本地中繼快取（可丟棄、非 rsync）、進度回饋、大檔量健壯性、realign 冪等性與錨點不動性修復、里程排序顯示與雙層里程軌重做。聊標註/版型不動。
> 設計基準：以 1 萬張為參考量級作彈性設計，無硬上限（>1 萬張仍可運作，僅效能線性下降），所有容量與併發皆為可配置而非拒絕門檻。

---

## Problem Statement

1. **看不到總量、看不到進度**：目前 `TunnelImporter.scan()` `backend/tunnelview/importer.py:148` 循序 `for p in sorted(folder.iterdir())` 且每張 `read_photo_time()` + `read_display_dims()` 各一次 `Image.open`，直到全部讀完才回 `ImportPreview`。前端 `WizardPage.jsx:73` 僅 `busy → "分析中…"`。1 萬張量級（例 4 相機各 2500）× NAS SMB 上需數十秒至數分鐘，使用者無法判斷卡死或進度，已知總檔案數也無法預先顯示（因總數需先掃完 EXIF 才知道）。**不開檔列舉的影響**：僅做 `os.scandir + stat` 不開檔即可得 `total/valid/ignored`，對最終對齊正確率 **零影響**（對齊仍需 EXIF，但 EXIF 讀取延後至階段 B 併發執行，僅提前顯示總量與進度）。

2. **重複做兩次**：`preview()` 與 `commit()` 各自呼叫 `_align() → scan()` `importer.py:166,187`，同一批檔案在 NAS 上讀兩遍，IO 成本翻倍。提交階段另做 `compute_aspect_anomalies` 與逐筆 `INSERT`，但對使用者體感是「預覽完又再等一次同樣久」。

3. **NAS 小檔隨機讀極慢、且不可 rsync**：公司限制不可整批 rsync 原檔到本機；但可接受「本地中繼快取（metadata + 縮圖，可丟棄）」。現行單執行緒、每張開檔兩次、且用已棄用 `Image.open(...)._getexif()` `importer.py:83` 未關檔，放大器效應明顯。**正確率保證**：所有列舉階段不判重、不丟檔，僅統計；解碼階段仍以 `mtime+size` 快取命中為準，miss 才開檔，開檔失敗計 `ignored_broken` 不中斷整批，最終 `align` 輸入仍是完整 `exif_time` 集合，不會因此對不起來。

4. **大檔量健壯性 bug**：
   - `scanned_by_pid = {p.path.name: p}` `importer.py:210` 以檔名為 key，跨相機同名 `DSC0001.JPG` 會碰撞，後相機覆蓋前相機，寫庫時 `rel_path/exif_time` 錯位或 `KeyError`。
   - `read_photo_time` 未用 `with` 關檔，1 萬張併發時可能洩漏 fd。
   - 忽略的非 JPG / 子目錄數量未回報，使用者誤以為「張數不符」是 bug。
   - 群組/照片寫入用逐筆 `conn.execute` 迴圈，1 萬群組時寫入慢；`compute_aspect_anomalies` 每相機多次查詢，O(N) 可優化。
   - `preview` 的 `missing_distribution` key 為 int，`realign_preview` 為 str，前端雖兼容但契約不一致。

5. **時間容差即時調整往返漂移（嚴重）**：`TunnelInfoPanel.jsx:27` 的 `乾跑預覽/套用` 走 `service.realign_preview/apply` `service.py:482,495`，使用者回報 `1.5s 100群 → 2s 120群 → 回 1.5s 僅 10群` 而非回到 100群，研判 `realign` 非冪等。根因待驗但可定位：`realign_preview` 純讀 `photos.exif_time` 重跑 `align` 應冪等，`realign_apply` 卻 `DELETE photo_groups + UPDATE photos.group_id` 並以新 `align` 結果重寫，且 `flagged/missing_count/anchors` 解析鏈可能在二次重排時漂移，導致往返不一致。**錨點不動性要求**：錨點必須綁載體照片 `carrier_photo_id` 跟著照片走，`mileage_m` 數值不可被重算改寫；往返同容差必須回到同分群，否則破壞使用者對容差的信任。
   - `info.report.tolerance_seconds` 存字串，`Number(currentTol)` 在空字串/`NaN` 時後端 `tolerance_seconds: float = Field(gt=0)` 回 422，無前端阻擋與錯誤提示。
   - `realign_apply` 以 `payload` 覆寫 `import_report`，遺漏部分欄位（`imported_at/camera rotation` 等）或型別不一致，資訊面板顯示異常。
   - `realign` 管線仍讀 `photos.exif_time` 重排，但 `flagged` 語意在 `service.py:529` 用 `CASE WHEN time_source='mtime' THEN 1` 與匯入期不一致，導致 `flagged_count` 漂移。

6. **排序顯示未由小到大**：現行 `service.overview/get_window` 與 `ScrubberRail idxToX` 皆以 `seq`（拍攝時序=行進方向）渲染，`start>end` 遞減隧道則里程條左大右小，預覽的「`K24～K23`」亦原序顯示，不利閱讀。需求：建立精靈預覽與里程軌皆預設里程由小到大排序（`min→max`），`start/end` 方向僅影響錨點單調校驗。

7. **缺照標記干擾里程閱讀**：里程軌同時疊加里程刻度、照片群組點、缺照/異常/錨點標記，缺照紅點密集時里程難以判讀。需求：雙層里程軌 — 下層為里程均分刻度（`min→max`、以群組為單位同動縮放）、上層為每群組淺色點位 + 各類標注，且各類標注可點圖例單獨隱藏；缺照隱藏僅限里程條註記，不影響網格與導航，軌道仍完整顯示 `min→max` 全區間。

## Solution

打造「**一次掃描、兩階段可視、本地可丟棄快取、容差冪等 + 錨點不動**」的匯入管線，1 萬張量級（參考量級，無硬上限、8 相機、NAS）體感目標 `<30s` 完成預覽且全程有進度條，>1 萬張線性降速但不拒絕、不 OOM。

- **階段 A — 快速列舉（不開檔）**：以 `os.scandir` 僅做目錄列舉與副檔名過濾，不開檔，即得 `total_files / valid_jpg / ignored`，前端立即顯示總量與「已發現 x 張」。此階段對正確率零影響，對齊仍待階段 B 的完整 EXIF。
- **階段 B — 併發解 EXIF + 顯示尺寸（保證正確率）**：單次 `with Image.open` 同時取 `DateTimeOriginal(36868)` 與 `尺寸+orientation(274)`，以 `ThreadPoolExecutor(8~16, 可配置)` 併發，邊解邊推 `done/total` 進度；每 50 張或 200ms 節流推送。快取命中（`mtime+size`）則跳過開檔，否則必開檔；壞檔計 `ignored_broken` 不中斷整批，確保 `align` 輸入為完整正確集合，不會因不開檔而對不起來。
- **去重複**：`preview` 產生的 `scan_result + align_result` 以 `job_id` 暫存於本機記憶體/快取（TTL 15min），`commit` 帶 `job_id` 直接寫庫，不再重掃 NAS。若 `job_id` 逾期或相機資料夾 `mtime` 變動則退回重掃。
- **本地中繼快取（非 rsync、可丟棄）**：`data/.scan_cache.db`（SQLite）以 `(folder, filename, file_mtime, file_size)` 為 key 快取 `exif_time/time_source/width/height`；`data/.thumb_cache` 續用於動態縮圖。命中時跳過 `Image.open`，僅需 `stat`。快取可整刪，無損資料，彈性 LRU（預設 2 萬筆，可配置，滿時按 `updated_at` 淘汰，無硬上限）。
- **進度可視**：後端提供輪詢式任務 API（SSE 作為可選升級），前端 `WizardPage` 與 `TunnelInfoPanel(realign)` 共用 `<ProgressBar stage, done, total, eta>`。
- **健壯性修復**：以 `(camera_seq, rel_path)` 為唯一鍵、修 `with Image.open`、補 `ignored/duplicate` 檢查報告、批量寫入優化、統一契約、realign 錯誤阻擋與報告回填。
- **容差冪等 + 錨點不動**：`realign` 保證 `realign(1.5) → realign(2) → realign(1.5)` 回到同分群；錨點以 `carrier_photo_id` 綁照片，`mileage_m` 永不被重算改寫，解析時 `resolve_anchor_seq` 跟照片走，`dangling` 時退回時間最近群組並標示。
- **排序顯示里程由小到大**：儲存仍以 `seq` 時序為準，僅顯示層反轉 — `Wizard` 預覽里程區間與 `ScrubberRail` 軸改為 `left=min(start,end)`，`idxToX` 在 `start>end` 時反向，`overview.est` 不動。
- **雙層里程軌（同動、以群組為單位）**：下層里程均分刻度（`min→max` 線性、密度 `50/100/200m` 自動）、上層每群組淺色點位 + 缺照/異常/錨點/待檢查疊加，雙層共用 `v0~v1(seq)` 縮放狀態經 `mileageToIdx→idxToX` 對齊，縮放以群組為單位同動；各類標注可點圖例 `eye/eye-off` 單獨隱藏（`localStorage`），缺照隱藏僅限軌道註記，軌道仍完整顯示全量里程區間，符合現有 `tokens.css` 深色風格。

---

## User Stories

### 進度與可視化

1. As 檢測人員, I want 選完相機資料夾後立刻看到「已發現 N 張 JPG（M 張忽略）」而不用等 EXIF 解完, so that 我能先確認選對資料夾。
2. As 檢測人員, I want 按「執行對齊分析」後看到分段進度「列舉中… / 解析 EXIF 1234/10000 / 對齊運算中…」, so that 我知道不是卡死。
3. As 檢測人員, I want 進度條含百分比與 ETA（剩餘秒數估算）, so that 我能決定是否先做別的事。
4. As 檢測人員, I want 預覽與提交共用一次掃描結果，提交階段不再重跑同樣久, so that 體感時間減半。
5. As 檢測人員, I want 提交階段的寫庫也有「寫入群組 3000/8500」進度, so that 1 萬群組寫入不像卡死。
6. As 檢測人員, I want 重新調整時間容差時也能看到乾跑與套用的進度, so that 長隧道重算不焦慮。

### 效能（1萬張量級，彈性設計，無硬上限）

7. As 檢測人員, I want 4 相機各 2500 張（共 1 萬張量級）在 NAS 上預覽 <30s（區網 1Gbps，HDD NAS）且 >1 萬張仍可運作僅線性變慢, so that 現場可接受且無硬性拒絕。
8. As IT 人員, I want 同隧道重複匯入（資料夾未變）時命中本地快取、預覽 <5s, so that 反覆試容差不痛苦。
9. As 檢測人員, I want 相機 1~8 台、每台張數不均時仍正確對齊且不 OOM（串流/分批處理，無一次性全載入硬上限）, so that 參考量級內外皆穩定。

### 本地快取（非 rsync）

10. As 公司資安, I want 原始照片不被整批複製到本機，僅快取「EXIF 時間/尺寸/縮圖」等衍生資料且可一鍵清除, so that 符合不落地原則。
11. As 檢測人員, I want 快取命中判斷以 `mtime + size` 為準，檔案異動自動失效重讀, so that 不會用到舊資料。
12. As 檢測人員, I want `data/.scan_cache.db` 與 `data/.thumb_cache` 可整包刪除且不影響 `tunnel_*.db`, so that 磁碟滿時可清。

### 照片數量檢查與健壯性

13. As 檢測人員, I want 預覽報告含「各相機有效張數 / 忽略張數（非 JPG/子目錄/壞檔）/ 同檔名跨相機碰撞警告」, so that 張數不符時有原因。
14. As 檢測人員, I want 壞檔（無法解 EXIF/尺寸）被計為 `ignored_broken` 並在報告列出前 20 筆 `rel_path + 原因`, so that 我能清理來源。
15. As 檢測人員, I want 跨相機同檔名 `DSC0001.JPG` 不再導致寫庫錯位, so that 多機同型號相機可正常使用。
16. As 檢測人員, I want 1 萬張場景下記憶體與 fd 不洩漏、任務可取消, so that 中途取消不殘留鎖。
17. As 檢測人員, I want 單隧道群組寫入採用批量 `executemany`，1 萬群組寫入 <2s, so that 提交不卡。

### 時間容差即時調整修復（錨點不動 + 冪等）

18. As 檢測人員, I want 在資訊面板輸入容差時前端阻擋空值/NaN/<=0 並提示「容差需 >0」, so that 不會 422 無回饋。
19. As 檢測人員, I want 乾跑預覽顯示「群組數 8500 → 8200 (-300)」與缺照分布對比, so that 我判斷容差是否合適。
20. As 檢測人員, I want 套用後 `import_report` 保留 `imported_at/各機 rotation/layout_cols` 並更新 `tolerance_seconds/group_count/flagged_count/realigned_at`, so that 資訊面板不丟欄位。
21. As 檢測人員, I want realign 的 `flagged` 語意與匯入期一致（mtime 恆 flagged + 殘差 flagged）, so that 待檢查數不漂移。
22. As 檢測人員, I want realign 的 `missing_distribution` key 型別與匯入期一致（字串化或皆 int，擇一統一）, so that 前端不需兼容。
23. As 檢測人員, I want `1.5s(100群) → 2s(120群) → 回 1.5s` 必回到 100群（冪等），否則視為 bug, so that 容差調整可信任。
24. As 檢測人員, I want 已錨定的群組其 `mileage_m` 在任何容差重排後不變，且錨點跟著載體照片移動到新 `group_seq`（`carrier_photo_id` 綁定），`dangling` 時標示並退回時間最近群組, so that 錨定成果不因重排而丟失或漂移。

### 排序顯示與雙層里程軌

25. As 檢測人員, I want 建立隧道的預覽階段與里程條皆預設里程由小到大排序（即使輸入 `起點 K24+200 迄點 K23+000` 也顯示 `K23+000～K24+200`），方向箭頭僅作提示, so that 閱讀一致。
26. As 檢測人員, I want 里程條分雙層 — 下層為里程均分刻度（`min→max`）、上層為每群組一個淺色點位，雙層縮放時以群組為單位同動且垂直對齊, so that 里程與照片密度同時可讀且不脫鉤。
27. As 檢測人員, I want 上層的各類標注（缺照/異常/待檢查/錨點）可點圖例單獨隱藏/顯示，且符合現有深色 `chip` 風格、hover 顯示 `Kxx+xxx #seq` 詳情, so that 密集時可聚焦且美觀。
28. As 檢測人員, I want 缺照隱藏開關僅隱藏里程條上的缺照註記，不影響中央網格、鍵盤導航與軌道完整里程區間顯示，且狀態 `localStorage` 記憶, so that 為了里程閱讀而隱藏時不丟資料。

### 錯誤處理

29. As 檢測人員, I want 相機資料夾不存在/無 JPG/權限不足時，預覽前即以 400 + 明確 `detail` 阻擋, so that 我立刻修正。
30. As 檢測人員, I want 任務失敗時看到「哪一階段失敗 + 前 3 個錯誤檔 + 建議動作（檢查 NAS 連線/清理壞檔）」, so that 可自助排解。

---

## Implementation Decisions

### 掃描管線重構

- **兩階段掃描**：`scan()` 拆為 `enumeratePhase(req) -> {perCamera: {total, validPaths, ignored: {nonJpg, broken}}}`（僅 `os.scandir` + `stat`，不開檔）與 `extractPhase(validPaths) -> _ScannedPhoto`（開檔解 EXIF/尺寸）。列舉階段即可回前端總量；解碼階段併發並推進度。
- **單次開檔**：合併 `read_photo_time` 與 `read_display_dims` 為 `read_exif_and_dims(path) -> (t,time_source,w,h)`，單次 `with Image.open(path) as im: exif=im.getexif(); t=exif[36868]; w,h=im.size + orientation`，棄用 `_getexif()`。
- **併發**：`ThreadPoolExecutor(max_workers = min(16, cpu*2, perCameraValid//100 + 4))`，IO 密集型；對每相機分片提交，結果按 `camera_seq` 回填，保持 `_ScannedPhoto` 順序語意不變。
- **鍵修正（bugfix）**：`scanned_by_pid` 與 `PhotoStamp.photo_id` 改為 `f"{camera_seq}:{rel_path}"`（或 `f"{camera_seq}:{path.name}:{mtime_ns}"`）全域唯一；`rel_path` 以 `os.path.relpath(p, camFolder)` 計算並作為 `photos.rel_path` 唯一鍵的一部分寫入前做重複檢查，若同相機內重名則後者加 `~1` 後綴並警告。`_series` 以新 `photo_id` 建 `CameraSeries`。
- **資源管理**：所有 `Image.open` 改 `with`，例外時回 `(None,'mtime') + (None,None)` 並計入 `ignored_broken`，不拋中斷整批。

### 去重複與任務模型

- **Job 暫存**：`preview` 產生 `job_id = uuid4().hex[:12]`，記憶體 `jobs[job_id] = {reqHash, scannedPhotos, series, alignResult, createdAt}`，TTL 15min、LRU 8 項；`commit` 介面新增可選 `job_id`，命中且 `reqHash` 一致且 `folder mtimes` 未變則跳過 `scan`/`align` 直接寫庫，否則退回全掃。`reqHash` = `sha1(name+start+end+tolerance+sorted(cameras{folder,mtime}))`。
- **任務 API 契約**：
  - `POST /api/import/jobs/preview` → `{job_id, status:"running"}` 併 `202 Accepted` 啟動背景任務（`BackgroundTasks` + `asyncio.to_thread` 包 `extractPhase+align`，避免阻塞 event loop）。
  - `GET /api/import/jobs/{job_id}` → `{status:"enumerating"|"extracting"|"aligning"|"done"|"failed", total, done, stage, preview?, error?}` 輪詢 500ms。
  - `POST /api/tunnels` 新增 `job_id?: string`；若提供則走快路徑。
  - 保留同步 `POST /api/tunnels/preview` 與 `POST /api/tunnels` 作為 fallback（小檔量 <500 張直接同步回應，省一次輪詢）。
  - `DELETE /api/import/jobs/{job_id}` 取消。
- **進度節流**：每 50 張或 200ms 更新一次 `jobs[job_id].done`，前端以 `requestAnimationFrame` 節流渲染。

### 本地中繼快取（非 rsync）

- **Scan Cache DB**：`data/.scan_cache.db` 單表 `scan_cache(folder TEXT, filename TEXT, mtime_ns INTEGER, size INTEGER, exif_time TEXT, time_source TEXT, width INTEGER, height INTEGER, updated_at TEXT, PRIMARY KEY(folder, filename))`，`PRAGMA journal_mode=WAL`。`extractPhase` 前先 `SELECT`，命中且 `mtime_ns/size` 一致則直接採用，否則開檔後 `INSERT OR REPLACE`。支援 `DELETE FROM scan_cache WHERE folder=?` 清理單相機，API `DELETE /api/cache/scan?folder=` 與 `DELETE /api/cache/scan` 全清。
- **Thumb Cache 續用**：`data/.thumb_cache/{tid}_{pid}_{w}_{rot}.jpg` 已存在 `api.py:620`，本期不新增永久縮圖倉庫；匯入期不預生成縮圖（避免 1 萬張一次爆 IO），僅在寫庫後可選背景預熱前 20 群組縮圖（低優先 `BackgroundTasks`）。
- **容量（彈性，無硬上限）**：LRU 以 `updated_at` 淘汰，預設軟上限 2 萬筆（可配置 `TUNNELVIEW_SCAN_CACHE_LIMIT`），超過時 `DELETE ... ORDER BY updated_at LIMIT 5000`；>1 萬張量級時不拒絕，僅循序淘汰，保證正確性優先於快取命中率。

### 寫庫優化

- `photo_groups` 與 `photos` 改 `executemany` 批量寫入；`photos` 每 1000 筆一批 `executemany`，交易單一 `with conn:` 包裹。
- `compute_aspect_anomalies` 改單次 `GROUP BY` 取多數派，減少每相機 N+1 查詢。
- `missing_distribution` 契約統一為 `dict[str,int]`（字串 key），前後端皆以字串處理。

### Realign 修復（冪等 + 錨點不動）

- **前端校驗** `TunnelInfoPanel.jsx:152`：`onChange` 內 `if (!Number.isFinite(v) || v<=0) { setError("容差需 >0"); return }`，按鈕 `disabled` 直到合法；顯示 `422 detail` 於 `err-text`。
- **後端報告回填** `service.py:556`：改為 `existingReport = json.loads(meta.import_report); existingReport.update(payload); payload["imported_at"]=existingReport["imported_at"]` 保留欄位，僅覆寫 `tolerance_seconds/group_count/missing_distribution/flagged_count/realigned_at/cameras(offsets)`。
- **flagged 一致化**：`service.py:529` 對齊 `importer.py:254` 語意 `flagged = 1 if (time_source=='mtime' or cam in residualFlagged) else 0`。
- **冪等保證**：`service._series_from_db` 必須純讀 `photos.exif_time`（不含 `corrected_time`）重建 `CameraSeries`，`align` 為純函式；`realign_preview` 與 `realign_apply` 共用同一 `align` 路徑，往返同容差必同結果。新增回歸：`realign(1.5)→realign(2)→realign(1.5)` 斷言最終 `group_count` 與首次 1.5 一致。
- **錨點不動性**：錨點以 `anchors.carrier_photo_id` 綁照片 `anchor_model.py:120`，`mileage_m` 永不參與 `_recompute` 重算；`realign_apply` 流程為 `existing=_resolved_anchors → DELETE photo_groups → 重建 groups → UPDATE photos.group_id → _recompute_missing_counts → _recompute(anchors=existing)`，`existing` 的 `mileage_m` 原值保留，`list_anchors_resolved` 經 `resolve_anchor_seq` 跟照片落到新 `group_seq`，`dangling` 時退回時間最近群組。不新增、不改寫 `mileage_m`。
- **realign 也走任務 API**：`POST /api/tunnels/{tid}/realign` 回 `job_id`，前端同進度條複用，避免大檔量乾跑無回饋假死。`realign/apply` 需帶 `job_id` 或 `tolerance` 二選一。

### 排序顯示與雙層里程軌

- **排序顯示**：`WizardPage.jsx:275` 與 `ScrubberRail` 軸改顯示 `min(start,end)～max(start,end)` 由小到大，`dirLabel` 保留 `⟶/⟵` 僅提示方向；`overview.est` 與 `photo_groups.seq` 儲存不動，`interp.check_anchor` 單調校驗仍以 `end>=start` 方向為準。
- **雙層里程軌（同動、以群組為單位）**：`ScrubberRail.jsx` 拆 `rail-upper(28px)` + `rail-lower(44px)` + `1px` 分隔線，共用 `v0~v1`（seq 區間）縮放狀態；`idxToX(seq)` 為主映射，下層里程刻度經 `mileageToIdx(m)→idxToX` 對齊上層，縮放平移同動。下層刻度密度由可視里程 `m1-m0` 自動選 `50/100/200m`；上層每群組 `1×8px` 淺色點 `opacity .35`，缺照/異常/待檢查/錨點以 `紅空心/橘實心/黃/藍鎖` 疊加，`hover` 放大 1.2 + `tooltip Kxx+xxx #seq`。圖例 `chip` 點 `eye/eye-off` 單類隱藏（`localStorage tv_rail_filter_*`），缺照隱藏僅限軌道註記，軌道仍完整顯示 `min→max`。
- **風格**：總高 `72px`，沿用 `tokens.css` 深色毛玻璃、`mono 10px` 刻度、`chip` 色板，不引入新主色；`canvas` 分區繪製或雙 `canvas` 皆可，`ResizeObserver` 已有，僅改映射。

### 前端

- `WizardPage.jsx` 與 `TunnelInfoPanel.jsx` 共用 `useImportJob(jobId)` hook 輪詢與 `<ProgressBar>`；`WizardPage` 步驟 2→3 間插入「已發現 N 張」即時表（各相機 valid/ignored 迷你表格），不等 EXIF 完即可見。
- 錯誤態：`status==="failed"` 時顯示 `error.stage + error.files.slice(0,3)` 與建議動作按鈕（重試/清快取/看報告）。

### 不變項

- `align.py` 演算法與容差語意不變；`interp.py` 里程內插不變。
- 照片仍引用 `root_path + rel_path`，不複製原檔；`SQLite WAL` 與單 API 寫入通道不變。
- `TUNNELVIEW_HOME / TUNNELVIEW_PORT` 環境變數不變。

## Testing Decisions

- **良好測試只驗外部行為**：斷言「給定 NAS 模擬資料夾與容差，預覽/提交回的群組數、偏移、缺照分布與 tagged 數正確」與「輪詢任務最終 `done===total` 且進度單調遞增」與「`1.5→2→1.5` 冪等」，不綁定 `ThreadPoolExecutor` 執行緒數或快取表結構。

- **主要縫（三層）**：
  1. **純函式核心（最重要）**：`align` 與 `interp` 現有 `test_align.py`、`test_interp.py` 擴充 1 萬張量級合成時間序列（首張漏拍、時鐘漂移、亞秒偏移）斷言收斂與效能 `<1s`，且 `align(tol=1.5)` 往返斷言冪等。
  2. **匯入管線（新重點）**：`test_importer.py` 新增 `TestScanCache`（mock `Image.open` 計數，驗命中時不開檔）、`TestDuplicateFilenames`（兩相機同名 `DSC0001.JPG` 各 3 張，提交後 `photos` 各 3 筆且 `rel_path` 正確）、`TestEnumerateWithoutOpen`（列舉階段 `Image.open` 呼叫次數為 0 仍回 total）、`TestBrokenFiles`（壞檔計入 `ignored_broken` 不中斷）、`TestCorrectnessWithoutOpen`（列舉不開檔 vs 全開檔的最終 `group_count/offsets` 一致）。
  3. **API 整合（TestClient + 暫存目錄）**：`test_api.py` 新增 `TestImportJobs`（`POST /jobs/preview → 輪詢 done/total 單調 → GET preview → POST /tunnels {job_id} 寫庫驗 jobs 快路徑無重掃`）、`TestCommitWithJobIdExpired`（逾期退回重掃）、`TestRealignValidation`（`NaN/<=0` 阻擋 422）、`TestRealignReportMerge`（套用後 `import_report` 保留 `imported_at`）、`TestRealignIdempotentAndAnchorSticky`（`1.5→2→1.5` 群組數回到首次且 `anchors[].mileage_m` 不變、`group_seq` 跟照片走）。

- **Prior art**：`test_importer.py::TestPreview/TestCommit`、`test_api.py::TestTunnelEndpoints`、`test_revision_api.py::realign` 乾跑/套用與廣播、`e2e_check.py` Playwright 全流程。

- **效能回歸**：`pytest -k "not e2e"` 全綠；以 `tmp_path` 生成 1 萬張小 JPG（`make_jpg` 迴圈）跑 `preview` 斷言 `elapsed <30s`（CI 可跳過，標 `slow`）。

## Out of Scope

- 整批 rsync 原檔到本機、永久縮圖倉庫、照片搬移入庫。
- OCR 里程牌、瑕疵標註模型變更、帳號權限。
- WebSocket 推送進度（本期用輪詢，SSE 作為後續可選升級）。
- `align` 演算法重寫、增量匯入已建隧道的追加相機。
- 前端虛擬滾動 / 1 萬群組導航軌優化（另案）。

## Further Notes

- **為何不用 rsync yet 能快**：瓶頸是「每張兩次隨機讀 + 單執行緒」，改單次開檔 + 併發 + 快取已可 5~10 倍；快取以 `stat` 命中時 1 萬張僅 ~1 萬次 `stat`（<< 1 萬次 `Image.open`），NAS 亦可接受。
- **快取可丟棄性**：`data/.scan_cache.db` 與 `data/.thumb_cache` 整刪不影響 `tunnel_*.db` 與 `index.db`，文件需註明「可安全刪除」。
- **向下相容**：舊 `POST /api/tunnels/preview` 同步回應保留；新任務 API 為加法，前端先探 `jobs` 再退回同步，避免一次全切風險。
- **風險**：NAS 併發 16 線程可能觸發限流；實作時對 `OSError: Too many open files` 退避為 `max_workers=4` 重試。`folder mtime` 以 `max(file mtimes)` 近似判斷是否需失效快取。

