# 修訂規格書 R7 — NAS 資料夾瀏覽效能、第一張預覽修正與 EXIF SubIFD 正確性修复

> 狀態：`implemented`（含實地量測與追加發現）｜ 前置：`revision-6-import-performance-progress-and-bugfix.md`
> 來源：使用者回報 — (1) 於 SMB/NAS 選擇相機資料夾需 2~3 分鐘才顯示照片列表與預覽（每機位約 3,500 張、單張 ~20-30MB） (2) 修復後預覽縮圖抓到資料夾中間的某張照片，而非第一張 (3) 實地量測時追加發現：真實相機 EXIF 時間解析失敗，全批退回 mtime。
> 範圍：`/api/fs/list` 列舉邏輯、FsBrowser 預覽圖載入、EXIF DateTimeOriginal 解析修正、匯入效能實測工具。不動對齊演算法與寫庫。

---

## Problem Statement

1. **逐檔 stat 造成 SMB 網路往返爆炸**：原 `/api/fs/list` 以 `sorted(target.iterdir())` 列舉後對每個 entry 呼叫 `Path.is_dir()`／`is_file()`。`pathlib.Path` 的屬性檢查每次都是獨立 `stat()` 系統呼叫，在 SMB 上即一次網路往返。3,500 檔 × 每往返 30~50ms ≈ **2~3 分鐘**，與使用者體感一致。
2. **預覽圖抓原圖**：`FsBrowser.jsx` 的 sample 圖 URL 未帶 `w` 參數，後端 `fs_photo` 直接 `FileResponse` 回傳完整原檔（20MB+），NAS 讀取加瀏覽器下載再拖慢數秒至數十秒。
3. **scandir 回歸**：為修問題 1 改用 `os.scandir()` 後，sample 取「第一個列舉到的 JPG」。scandir 回傳順序依檔案系統內部排列而**非檔名序**，導致預覽顯示中間任一張。此 bug **僅影響瀏覽器預覽縮圖選擇**——匯入對齊走 `importer.scan()`（自有檔名排序 + EXIF 時間分組），群組與排序不受影響。

## Solution

- **單次 scandir、零額外 stat**：`/api/fs/list` 改以 `os.scandir()` 列舉；`entry.is_dir()`／`entry.is_file()` 直接使用 readdir 附帶的快取資訊，不另發 stat。子資料夾名稱收集後以 `name.lower()` 排序，維持原本顯示順序。
- **第一張 = 檔名最小**：掃描時以 case-insensitive 檔名比對保留最小者作為 `sample`，行為與舊版 `iterdir + sorted(name.lower())` 完全一致。
- **預覽走縮圖**：`FsBrowser.jsx` 的 `fsPhotoUrl(path)` 補上 `w=320`，與 WizardPage 縮圖路徑一致，命中 `.thumb_cache` 後近乎即時。

### 不變項

- `importer.scan()` / `enumerate()` / 對齊演算法 / 寫庫皆不動。
- `/api/fs/photo` 端點契約不變（`w` 參數本就存在）。
- API 回應欄位（`roots/recent/path/parent/dirs/sample`）契約不變。

## Testing

- 全套回歸 `uv run pytest backend/tests/ -q`：146 passed。
- 手動手動驗證：亂序列舉的目錄中，sample 必為檔名最小之 JPG（含大小寫混合、`.jpg/.jpeg` 混用）。
- 效能驗證：NAS 上 3,500 張資料夾列表由分鐘級降至秒級（剩單次目錄列舉往返）。

---

## 追加發現 A — 真實相機 EXIF DateTimeOriginal 解析失敗（嚴重正確性 bug）

### 問題

以真實資料（Sony ILCE-7RM4A 原圖）實測時發現 `read_photo_time()` / `read_exif_and_dims()` **全批解析失敗**，14,218 張全部退回 mtime 並標記 flagged。

根因：`DateTimeOriginal(36868)` 位於 **Exif SubIFD**（IFD0 經 `0x8769` 指標指向），真實相機皆如此存放；原程式僅查 IFD0 的 `exif.get(36868)` 必然落空。

### 為何既有測試沒抓到（重要教訓）

`test_importer.py::make_jpg()` 以 PIL 產生 fixture，`exif[36868]=...` 會把 tag 寫進 **IFD0**——開發者以「錯誤假設」製造測試資料，再用同一假設驗證實作，循環論證、必然全綠。bug 另被兩層運氣遮蔽：

1. **mtime fallback 安靜降級**：此批檔案上傳時 mtime 被保留（實測與 EXIF 僅差 0~1 秒），退回後分組/偏移/里程「看起來全對」。
2. **警示不夠大聲**：唯一線索是 `flagged_count` / 待檢查數字，UI 未對「無 EXIF 比例過高」提出阻擋級警告。若日後同步工具重設 mtime，排序將無聲崩壞。

### 解法

- `importer.py` 新增 `_extract_dt_original(exif)`：先查 IFD0、再查 `exif.get_ifd(0x8769)[36868]`；`read_photo_time()` 與 `read_exif_and_dims()` 共用。
- 測試新增 `make_camera_jpg()`（SubIFD 版 fixture）與 `TestRealCameraExif` 兩案例：SubIFD 讀取成功、scan 不誤標 flagged。TDD 紅→綠，全套 148 passed。

## 追加發現 B — 實地效能量測（`tools/bench_import.py`）

唯讀量測工具：分段計時列舉 / EXIF 掃描 / 對齊，支援均勻跨目錄抽樣外推全量、多輪冷熱快取對比。

實際環境：WSL2 → 9p(drvfs) → Windows 雲端硬碟 Y:，四機位共 **14,218 張**（各約 3,551~3,557）：

| 階段 | 實測 | 全量外推 |
|---|---|---|
| 列舉（不開檔） | 2.6s | 2.6s |
| EXIF 掃描（冷快取） | 38~63 ms/張 | **~12.5 分** |
| EXIF 掃描（溫快取） | 16~23 ms/張 | ~4.4 分 |
| 對齊運算 | 可忽略 | <1s |

現況架構推估：預覽一遍 ~8.5 分；preview+commit 重掃兩遍 ~17 分；commit 復用掃描結果可砍半；加 12 執行緒併發可再壓至 1~2 分。

修復 SubIFD 後抽樣 240 張 mtime 退回 = **0 張**，EXIF 時間正確。

### 後續建議（未實作）

- 預覽報告對「無 EXIF 比例 > 門檻」顯示紅色警告甚至阻擋提交（防止安靜降級復發）。
- R6 已規劃的掃描結果復用與併發解碼（見 Out of Scope）。

## Out of Scope

- 匯入管線併發解 EXIF、commit 復用 preview 掃描結果、`.scan_cache.db` 中繼快取（R6 已規劃，另案處理）。
- job API 背景化與前端進度條。
- 大於頂層的遞迴列舉。
- 已建立隧道的重新匯入/修復（本次 EXIF 修正僅影響之後的匯入與 realign；舊隧道如需修正請重建）。
