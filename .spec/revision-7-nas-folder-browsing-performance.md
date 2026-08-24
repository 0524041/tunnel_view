# 修訂規格書 R7 — NAS 資料夾瀏覽效能與第一張預覽修正

> 狀態：`implemented` ｜ 前置：`revision-6-import-performance-progress-and-bugfix.md`
> 來源：使用者回報 — (1) 於 SMB/NAS 選擇相機資料夾需 2~3 分鐘才顯示照片列表與預覽（每機位約 3,500 張、單張 ~20-30MB） (2) 修復後預覽縮圖抓到資料夾中間的某張照片，而非第一張。
> 範圍：僅 `/api/fs/list` 列舉邏輯與 FsBrowser 預覽圖載入。不動匯入掃描（`importer.scan`）、對齊、寫庫。

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

## Out of Scope

- 匯入管線併發解 EXIF、commit 復用 preview 掃描結果、`.scan_cache.db` 中繼快取（R6 已規劃，另案處理）。
- job API 背景化與前端進度條。
- 大於頂層的遞迴列舉。
