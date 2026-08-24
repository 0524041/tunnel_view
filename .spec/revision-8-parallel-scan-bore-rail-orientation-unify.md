# 修訂規格書 R8 — 雲端碟匯入加速、背景掃描進度、孔腔里程軌與方向批次轉正

> 狀態：`implemented` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1~7`
> 來源：使用者實測回報 — (1) 台14線/台76線實案（4 機位 14,218 張、雲端硬碟掛載 `/mnt/y`）「對期分析」30–40 分鐘且「建立新隧道」又再等 7 分鐘，優化未達預期 (2) 里程條最前段（K27+ 段）看得到樁號卻點不到群組，滿縮也無法觸及，需用左右鍵才能到最前面 (3) 同機位混合直橫式照片觸發比例異常提示，逐張手轉不切實際
> 實實測基準：單張 EXIF 讀取中位數 53 ms（序列全掃外推 13.5 分）；本機 CPU 僅 0.4 ms/張——瓶頸 99% 為網路往返；併發實測 8→526s、16→379s、32→359s（供應端限流使 >16 收益趨零）；`align()` 對齊運算本身 1200 張僅 30 ms。

---

## Problem Statement

1. **前端從未接上 job API**：R6 已提供 `/api/import/jobs/preview` 與 `job_id` 提交快路徑，但前端 `WizardPage` 仍呼叫同步 `/api/tunnels/preview` 且 `POST /api/tunnels` 不帶 `job_id`，導致 preview 與 commit 各做一次完整雲端碟 EXIF 掃描。
2. **掃描併發預設吃 CPU 核數**：`min(16, cpu*4)` 在小 VM（2 核）只給 8 workers；IO-bound 併發不吃核數，應固定上限。
3. **job 端點為同步假 job**：即使接上，`create_import_job` 也是做完才回 `done`，HTTP 請求仍卡全程，前端無從顯示「已掃 x/14218 張」。
4. **里程條夾限越界**：`clampView` 允許視窗兩端越界 15%（`a = max(-s*0.15, …)`）。滿縮時若最後手勢游標在左半邊，視窗停在 `[0.15n, 1.15n]`——前 15% 群組不被繪製、點擊映射不到；但起訖樁號標籤無條件釘在螢幕兩端繪製，形成「看得到 K27+ 卻點不到」的幽靈標籤。約 3000 群量級下即前 ~450 組不可達。
5. **檢視不跟隨**：鍵盤 `←/→`、`Ctrl+G` 跳轉後，若目標在可視窗外，軌道視窗不自動平移，位置指示消失於畫外。
6. **直橫式混雜無批次解法**：`compute_aspect_anomalies` 以機位多數派比例標記少數派照片，但只能逐張手動旋轉；且旗標重算未納入 `rotation_override`，人工轉正後仍被誤標。直/橫可自動偵測，但**轉 90° 或 270° 的內容方向無法自動判斷**。

## Solution

- **方案 A — 平行 EXIF 掃描**：`TunnelImporter.scan()` 以 `ThreadPoolExecutor`（預設固定 **16** workers，環境變數 `TUNNELVIEW_SCAN_WORKERS` 可覆寫）併發讀取；結果依檔名排序收集，輸出與序列版完全一致（決定性測試覆蓋）。支援 `progress(done)` 回呼供進度回報。原檔唯讀。
- **方案 B — preview→commit 免二次掃描**：preview 的 `_ScannedPhoto` 快照暫存於 job；commit 帶同一 `job_id` 且機位資料夾指紋（有序 JSON）一致時直接復用，否則退回正常重掃。
- **真背景 job**：`POST /api/import/jobs/preview` 改為建立 daemon 執行緒後立即回 `{status:"running", total}`；執行緒內更新 `done`（每 50 張推進）、完成寫入 preview 快照、失敗寫入 error。`GET /api/import/jobs/{id}` 輪詢。commit 若收到未完成的 job 會 join（timeout 600s）防禦。失敗的 job 不得被誤用為掃描快照。
- **前端接線**：`WizardPage.runPreview()` 改走 job API，1.2s 輪詢顯示進度條（琥珀色、百分比）；commit 傳 `job_id`。`api.js` 新增 `createImportJob/getImportJob/unifyCameraOrientation`，`createTunnel(body, jobId)`。
- **里程軌重做（孔腔風格）**：
  - 檢視數學抽成純函式模組 `frontend/src/lib/scrubberMath.js`（`clampView/zoomView/followCurrent/idxToX/xToIdx/pickStep/fmtMileage`），以 Node 內建 test runner 驗證（11 tests）。
  - `clampView` 視窗**完全夾在 [0, n]**（不得越界），最小跨度 8；滿縮必為 `[0, n]`——最前段永遠可點。
  - 新增檢視跟隨：`current` 離開可視範圍時視窗保持跨度平移跟上。
  - 視覺以隧道工程意象重繪（canvas）：下層里程軸改為「孔腔」——雙壁線＋枕木式刻度，主刻度上方浮出圓角樁號牌；起訖樁號僅在進入可視範圍時顯示（▶/◀ 標示，消除幽靈標籤）；上層每群組為襯砌環片點位（密度自適應的環片接縫加重）；當前位置為頭燈光束＋游標三角。語義色維持不變（錨點藍／缺照紅／異常琥珀／粉紅）。
- **方向批次轉正**：
  - `import_report.orientation_stats`：每機位 `{landscape, portrait, minority}`（有效方向＝機位旋轉＋照片 override 後判斷）。
  - `compute_aspect_anomalies` 納入 `rotation_override`（`(cam.rotation + override) % 180` 換算顯示寬高），人工轉正後不再誤標。
  - `service.unify_camera_orientation(tid, seq, angle)`：將機位內顯示方向異於多數派的照片批次設 `rotation_override=angle`（僅接受 90/270——180 不變換直橫），同交易重算異常旗標；端點 `POST /api/tunnels/{tid}/cameras/{seq}/unify` 含縮圖快取失效與 WebSocket 廣播。
  - Wizard 建立隧道後偵測混合機位，彈出確認表格（橫/直張數、↻順時針／↺逆時針／略過），套用後進入檢視；略過者之後仍可單張旋轉。舊隧道不受影響。

## Acceptance Criteria

1. 序列掃描與併發掃描對同一資料夾輸出逐欄一致（順序、時間、尺寸、flagged）。
2. `_default_scan_workers()` 不受 `os.cpu_count()` 影響恆為 16（env 可覆寫）。
3. `POST /api/import/jobs/preview` 在掃描未完成時 <0.4s 回應 `running`；輪詢至 `done` 後 `done==total` 且含 preview；掃描拋例外 → `failed` + error，且其後帶該 `job_id` 的 commit 不得使用任何掃描快照。
4. 帶有效 `job_id` 的 commit 全程只掃一次（spy 計數 =1）；不帶或指紋不符則重掃（=2）。
5. `clampView` 對任意輸入輸出皆落在 `[0, n]`；滿縮輸出恰為 `[0, n]`；`zoomView` 游標錨定點不動；`followCurrent` 範圍內 no-op、範圍外平移且夾邊界、跨度不變。
6. 匯入報告含 `orientation_stats`；override 已轉正的照片重算後 `aspect_anomaly=0`；unify 端點回報 `updated` 張數且旗標清空；非 90/270 回 400。
7. `uv run pytest backend/tests/ -q` 全綠（161 tests）；`node --test frontend/src/lib/scrubberMath.test.js` 11 tests 全綠；`npx oxlint src` 不新增警告；`npm run build` 成功且 dist 更新入庫。
