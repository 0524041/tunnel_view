# 修訂規格書 R2 — 自由版型、NAS 路徑與檢視器版面

> 狀態：`ready-for-agent` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1-alignment-review-display.md`
> 來源：第三輪需求討論共識
> 範圍：相機自由排序版型（含建立精靈重做）、NAS／UNC／跨硬碟路徑支援、檢視器常駐資訊欄＋RWD＋照片呈現模式、資訊面板 UX 批次優化

---

## Problem Statement

1. **資料夾選擇受限**：檔案瀏覽器在 Windows 下看不到其他磁碟代號，也沒有最近路徑；照片實務上常放在 **NAS**（以對應磁碟機或 UNC 存取），現有介面對這種部署不友善。
2. **版型寫死**：相機的網格位置由匯入順序與固定映射決定，無法指定「哪台相機出現在哪一格」；建立精靈視窗窄小、缺乏即時版型預覽。
3. **檢視器版面僵硬**：右側錨點列與資訊面板互斥且非常駐；無響應式設計；照片以 cover 模式裁切塞滿格子，「固定顯示比例」不符合檢查需求。
4. **資訊面板 UX 粗糙**：相機旋轉變更後預覽不刷新（廣播未清群組快取的 bug）、操作無回饋提示、段落不可摺疊、重新對齊乾跑缺少與現值的差異比較。

## Solution

- **路徑層**：Windows 以系統 API 列舉所有磁碟代號作為頂層根；UNC 路徑（`\\NAS\share\...`）全程支援；index.db 記住最近使用的相機資料夾供一鍵跳躍；README 補充 NAS 部署指引。
- **版型編輯器**：每台相機一個 `grid_pos` 格位，拖曳或點選交換即可重排；建立精靈步驟二整段重做為即時版型編輯器（真實首張縮圖、所見即所得），同一編輯器複用於資訊面板的事後調整。
- **檢視器版面**：右側單一侧欄常駐（錨點｜資訊頁籤並存、可收合）；三段 RWD 斷點；照片呈現模式改為「完整呈現（contain）」預設＋「填滿（cover）」切換並記憶偏好。
- **UX 批次**：旋轉變更廣播同時刷新群組快取（修復預覽不更新）、待檢查卡片縮圖、操作 toast 回饋、面板段落摺疊、重新對齊乾跑差異高亮。

---

## User Stories

### 路徑與 NAS

1. As Windows 伺服器管理者, I want 檔案瀏覽器頂層直接列出所有磁碟代號, so that 不必手動輸入 `D:\`、`E:\` 就能起頭瀏覽。
2. As 使用 NAS 的檢測人員, I want 在路徑欄直接貼上 `\\NAS\share\tunnel\Cam1` 並瀏覽其內容, so that 不依賴磁碟機對應、任何啟動方式都讀得到照片。
3. As 檢測人員, I want 最近選過的相機資料夾出現在瀏覽器頂部可一鍵跳躍, so that 同一批專案反覆匯入時不用每次翻目錄。
4. As IT 人員, I want README 說明 UNC／WSL 掛載／macOS 卷宗三種情境與快取行為, so that 部署時不再猜測哪種路徑格式可用。

### 版型編輯

5. As 檢測人員, I want 在建立精靈中以拖曳（或點選兩張互換）安排每台相機的網格格位, so that 頂拱／邊牆／路面照我習慣的位置呈現。
6. As 檢測人員, I want 版型編輯器中每格顯示該台相機的真實第一張縮圖並套用其旋轉值, so that 所見即所得、當場發現方向錯誤。
7. As 檢測人員, I want 建立後仍能在資訊面板用同一個編輯器調整位置、旋轉與欄數, so that 事後修正不需重建專案。
8. As 檢測人員, I want 合併／重新對齊等操作完全不改動我的版型設定, so that 版型是一次性的穩定決策。
9. As 檢測人員, I want 欄數可自訂（1–4）且預設沿用依台數的自動映射, so that 少台數不必設定、多台數能強制單行排列。

### 檢視器版面

10. As 檢測人員, I want 右側常駐側欄同時提供錨點與資訊兩個頁籤, so that 錨定作業與品質工具不再互相切換排擠。
11. As 檢測人員, I want 側欄可收合成細欄以最大化照片區域, so that 專注檢查時不被壓縮視野。
12. As 檢測人員, I want 預設以完整呈現（contain）檢視照片、需要時一鍵切回填滿（cover）, so that 牆面邊緣不被裁掉且偏好被記住。
13. As 使用 1280px 筆電的使用者, I want 側欄自動收窄或改浮出、網格保持可用, so that 小螢幕不會破版。

### UX 批次

14. As 檢測人員, I want 相機旋轉變更後所有格子立即反映新方向, so that 不再懷疑「到底存了沒」。
15. As 檢測人員, I want 待檢查卡片顯示縮圖, so that 不跳轉就能完成大部分初判。
16. As 檢測人員, I want 每次寫入操作有成功／失敗的 toast 提示, so that 明確知道系統狀態。
17. As 檢測人員, I want 資訊面板各段落可摺疊且記住狀態, so that 常用的段落常開、其他收起。
18. As 檢測人員, I want 重新對齊乾跑結果以「297 → 281 群 (−16)」形式高亮差異, so that 影響幅度一目瞭然。

---

## Implementation Decisions

### Schema（SCHEMA_VERSION → "4"，延續既有防禦式遷移）

- `cameras` 新增 `grid_pos INTEGER NOT NULL DEFAULT -1`：格位索引（0 起，左上逐行）。遷移時回填 `grid_pos = seq` 保持既有順序。
- 隧道 `meta` 新增 `layout_cols`（值為 `'auto'` 或 `"1".."4"` 字串；讀取端解析）。遷移時預設 `'auto'`。
- `grid_pos = -1` 表示「未指定」，渲染時按 seq 遞補到剩餘空格——確保舊資料與新建立的隧道在任何欄數下都有合法版型。

### 相機排序與版型 API

- 建立隧道請求體的 `cameras[]` 增加可選 `grid_pos`；新增可選頂層 `layout_cols`。匯入時寫入。
- `GET /api/tunnels/{tid}/info` 的 `cameras[]` 增加 `grid_pos`，頂層增加 `layout_cols`。
- `PUT /api/tunnels/{tid}/cameras/{seq}` 擴充接受 `grid_pos`；另新增 `PUT /api/tunnels/{tid}/layout {cols}` 更新欄數。
- 兩者皆經 WebSocket 廣播（`camera_updated` / `layout_updated`），且**廣播前先使前端群組快取失效**——修復「旋轉後預覽不更新」：`camera_updated` / `layout_updated` / `photo_updated` 一律觸發群組重抓。
- 重新對齊與合併不触碰 `grid_pos`／`layout_cols`。

### 版型編輯器（共用元件）

- 單一元件服務兩個場景：嚮導步驟二（建立時）與資訊面板「相機」頁籤（事後）。
- 上半部即時網格：`layout_cols` 解析後的欄數 × 依 `grid_pos` 排列，每格渲染該台相機第一張真實縮圖（套用旋轉）；空格顯示虛線佔位。
- 移動語意＝**交換**：HTML5 DnD 拖曳到目標格，或點選來源再點目標（兩者等效）；不支援插入擠位。
- 卡片列（下方）：名稱、資料夾 📁（開啟既有 FsBrowser）、旋轉下拉、`grid_pos` 徽章。
- 儲存行為：嚮導內隨建立提交；資訊面板內逐項即時儲存（沿用 onChange 即時語意，不做確認鈕——依賴修復後的即時刷新）。

### 檔案瀏覽器強化

- `GET /api/fs/list?path=` 擴充：`path` 為空時回傳 `roots`（Windows：`GetLogicalDrives` 位元遮罩列舉的代號列表；POSIX：`/`），前端以此渲染頂層；UNC 路徑原樣接受（`Path` 原生支援）。
- index.db 新增 `recent_paths(path TEXT PRIMARY KEY, used_at TEXT)`：**挑選資料夾確認時**記錄（去重、上限 8 筆、LRU 淘汰）；`fs_list` 回傳 `recent` 欄位供前端渲染快速跳躍列。
- 平台差異集中在一個根列舉函式（注入平台旗標以便非 Windows 測試）。

### 檢視器版面與 RWD

- 右側改為**單一側欄元件**：內含「錨點｜資訊」頁籤（資料來源不變）；寬度三態——展開 300px／收合 44px 細欄（僅圖示）／隱藏；狀態存 localStorage。
- 斷點：`≥1600px` 側欄展開＋網格全寬；`1280–1599px` 側欄預設收合；`<1280px` 側欄改為浮出層（按鈕呼出、關閉還原）。斷點僅影響側欄與間距，網格永遠存在。
- 照片呈現模式：`contain`（預設，完整呈現留黑黑邊）↔ `cover`（填滿裁切）切換鈕置於檢視器頂欄；偏好存 localStorage；原圖覆蓋層不受影響。

### UX 批次

- **Toast**：全域輕量 toast 元件；所有寫入型 API 呼叫統一接上（成功綠、失敗紅、3 秒自动消失）。
- **摺疊**：資訊面板 Section 改為可摺疊（預設展開第一段，其餘收起；狀態存 localStorage）。
- **待檢查縮圖**：flagged 清單已含 rel_path——卡片左側加 80px 高縮圖（复用既有串流端點 w=160）。
- **乾跑差異**：realign preview 回傳 `group_count`，前端與 overview 現值比較渲染「N → M 群 (+K/−K)」，正綠負紅；缺照分佈比對同理（僅顯示有變化的鍵）。

### 建立精靈重做

- 容器加寬至 1100px+、步驟指示器固定於頂、每一步內容獨立捲動。
- 步驟二＝版型編輯器本體；步驟三（對齊預覽）版面配合放寬。
- 建立流程順序不變：基本 → 版型＋相機 → 對齊預覽 → 建立（成功後自動關閉嚮導分頁）。

---

## Testing Decisions

延續既有三縫，本期新增集中在 API 整合縫：

1. **API 整合（主要縫）**：
   - 版型：建立帶 `grid_pos`／`layout_cols` → `/info` 回讀一致；`PUT layout` 後 overview/info 反映；重新對齊與合併前後 grid_pos/layout_cols 不變。
   - 遷移 v3→v4：舊庫開啟後 `grid_pos` 回填等於 seq、`layout_cols='auto'`；六執行緒併發開啟沿用既有回歸測試模式。
   - fs：空 path 回傳 roots 結構（POSIX 下至少含 `/`；Windows 分支以注入式旗標模擬，斷言代號格式）；UNC 路徑字串可被 list 端點處理不存在時回 404。
   - recent_paths：挑選確認（建立隧道）後 top-1 等於該資料夾；上限 8 筆 LRU。
2. **純函式小縫**：欄數解析（'auto'/1..4/非法值退回 auto）與 grid_pos→CSS 座标的映射規則（若抽成可測函式）。
3. **前端**：RWD 斷點與拖曳互動以手動驗收；E2E 增補「版型編輯器交換兩格 → 建立後 /info 順序一致」「照片 fit 切換」兩個場景。

Prior art：`test_revision_api.py`（info 聚合、旋轉端點）、`test_migration_and_delete.py`（併發遷移模式）。

---

## Out of Scope

- 網格跨欄／跨列的大格位（span）
- 手機直向版面
- 插入式擠位排序（僅交換）
- 拖曳跨群組搬移照片（版型只管相機格位）
- NAS 連線管理（掛載本身由作業系統負責）
- 伺服器端檔案對話框

## Further Notes

- 「遠端使用者看到的是 Server 的目錄」為刻意設計：照片在 Server 可及之處即可，瀏覽端零安裝。
- Windows 對應網路磁碟機（E:）屬登入工作階段，建議 NAS 直接使用 UNC 路徑；文件化於 README。
- 縮圖首次生成需跨網路讀 NAS 原檔（較慢），之後命中伺服器本機 `.thumb_cache`；日常瀏覽不吃網路。
- `layout_cols='auto'` 的映射沿用現行規則（1→1×1、2→2×1、3→3×1、4→2×2、5~6→3×2、7~8→4×2）。
