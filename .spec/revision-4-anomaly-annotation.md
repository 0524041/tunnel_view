# 修訂規格書 R4 — 異狀標註、里程條專業化與資訊欄整理

> 狀態：`ready-for-agent` ｜ 前置：`tunnel-viewer-mvp.md`、`revision-1-alignment-review-display.md`、`revision-2-layout-nas-ux.md`、`revision-3-camera-grid-layout-fix.md`
> 來源：使用者需求訪談（grilling 共識）— 隧道檢測需要將裂縫/滲漏等異狀記錄到照片並在里程軸上定位；既有「待檢查/人工檢查」複核機制實際未使用；資訊欄與側邊欄混合、收合失效。
> 範圍：異狀標註（照片級、類型共用）、照片備註、里程條重繪與圖例/說明、異狀總覽頁、移除複核機制、資訊欄 UI/UX 整理。

---

## Problem Statement

1. **無法記錄異狀**：隧道檢測照片中的裂縫、滲漏水、剝落、白華、鋼筋外露等缺陷，目前只能在腦中或外部文件記錄，無法與特定里程、特定照片關聯，事後無從追溯。
2. **里程條不專業且圖例遮蔽**：底部導航軌刻度粗糙、當前里程讀數不明顯；右上角圖例以絕對定位壓在 canvas 標記區上，右側標記密集時互相遮擋。
3. **舊機制冗餘**：`review_result`（✅檢查OK／🚩標注異常）與自動「待檢查」旗標的使用者實際用不到；資訊欄四個頁籤中兩個為此存在。
4. **資訊欄 UX 混亂**：資訊面板與錨點清單混在同一側欄；「縮小」（mini 44px）只縮外框、內容溢出形同壞掉；相機頁籤沒有改名功能。

## Solution

1. **異狀標註**：點開照片後的 OriginalViewer 內建編輯介面——每張照片可掛 1..n 筆異狀（自訂類型＋備註）與一個照片層級備註。類型全專案共用（存 `index.db`），內建五種，可在編輯介面直接新增；已被使用的類型刪除時自動封存而非消失。
2. **異狀上軌**：里程條以單一固定色標記有異狀的里程位置（hover 顯示縮圖＋類型＋樁號的 tooltip、點擊跳轉），與缺照紅色明確區隔。
3. **異狀總覽頁**：隧道分頁內「檢視 ↔ 異狀總覽」模式切換。總覽為卡片牆（縮圖＋類型 badge＋樁號＋備註），按里程排序，頂部類型計數 chips 篩選＋關鍵字搜尋＋排序切換；卡片點擊＝編輯 modal，卡上「定位」鈕跳回檢視並閃爍該照片格。
4. **里程條專業化**：主/次要刻度自適應密度、`K0+050` 樁號標示、起訖樁號釘選、當前位置醒目讀數；圖例移至軌道下方獨立一排；軌道右端加 `?` 幫助鈕，modal 列出全部快捷鍵與功能說明。
5. **移除複核機制**：待檢查/人工檢查頁籤、review API、照片格紅框自動旗標顯示全部移除（DB 欄位留存不用）；比例異常 chip 與就地旋轉保留。M 鍵合併模式原樣保留（修復既有 `setError` bug）。
6. **資訊欄整理**：頁籤精簡為「報告」「相機」兩個，相機新增改名；收合改為可靠的顯示↔隱藏兩態；錨點清單與資訊面板拆開為可獨立開關的面板。

## User Stories

### 異狀標註

1. As 隧道檢測人員, I want 點開照片後在原圖檢視介面直接新增異狀（選類型＋寫備註）, so that 看到裂縫當下立即記錄。
2. As 隧道檢測人員, I want 一張照片掛多筆異狀（如同時裂縫＋滲漏水）, so that 複合缺陷完整記錄。
3. As 隧道檢測人員, I want 每筆異狀有自己的備註（如「縱向裂縫約 2m」）, so that 記錄工程細節。
4. As 隧道檢測人員, I want 照片本身有一個備註欄位, so that 記錄不屬於特定異狀的補充資訊。
5. As 隧道檢測人員, I want 修改已建立異狀的類型與備註、或刪除誤標的異狀, so that 資料保持正確。
6. As 隧道檢測人員, I want 系統預先提供 裂縫/滲漏水/剝落/白華/鋼筋外露 五種類型, so that 不需初始設定。
7. As 隧道檢測人員, I want 在標註介面輸入名稱即新增自訂類型, so that 不用離開工作流程去設定頁。
8. As 隧道檢測人員, I want 自訂類型跨所有隧道專案可用, so that 全案場詞彙一致。
9. As 隧道檢測人員, I want 刪除未被使用的類型直接生效、刪除已被使用的類型自動封存並提示, so that 歷史紀錄不失真又不留垃圾選項。
10. As 隧道檢測人員, I want 封存的類型不再出現在選擇器但既有紀錄正常顯示, so that 舊報告可讀。
11. As 多視窗使用者, I want 另一視窗標了異狀後我的畫面同步更新, so that 協作不一致。

### 異狀上軌與總覽

12. As 隧道檢測人員, I want 里程條上有異狀的位置出現醒目標記（單一固定色、與缺照區隔）, so that 掃一眼就知道哪段有問題。
13. As 隧道檢測人員, I want hover 異狀標記看到縮圖＋類型＋樁號, so that 不跳轉即可確認內容。
14. As 隧道檢測人員, I want 點擊異狀標記跳到該群組, so that 快速到達現場照片。
15. As 隧道檢測人員, I want 一個總覽頁一次看完全部異狀與對應縮圖, so that 撰寫報告時不必逐頁翻找。
16. As 隧道檢測人員, I want 總覽按里程排序並可切換升降冪, so that 對應現場行進方向。
17. As 隧道檢測人員, I want 總覽頂部以類型 chips（含計數）篩選, so that 例如只看滲漏水分佈。
18. As 隧道檢測人員, I want 總覽可搜尋備註關鍵字, so that 用文字找回特定紀錄。
19. As 隧道檢測人員, I want 在總覽卡片直接編輯（輕量 modal：縮圖＋類型＋備註）, so that 不用進原圖也能修資料。
20. As 隧道檢測人員, I want 卡上「定位」跳回檢視模式並閃爍該照片格, so that 知道它在網格哪一格。
21. As 隧道檢測人員, I want 被改判缺照的照片其異狀不出現在軌道與總覽（資料保留）, so that 合併後不留幽靈標記。

### 里程條與幫助

22. As 隧道檢測人員, I want 主/次刻度隨縮放層級自適應、樁號以 `K0+050` 格式標示、起訖樁號釘選, so that 里程判讀專業直觀。
23. As 隧道檢測人員, I want 當前位置以醒目樁號浮標顯示, so that 隨時知道自己在哪。
24. As 隧道檢測人員, I want 圖例移到軌道下方獨立一排不再遮擋標記, so that 標記密集處也清晰。
25. As 新手使用者, I want 按 `?` 或點幫助鈕跳出全部快捷鍵與功能說明, so that 不需背文件。

### 清理與資訊欄

26. As 使用者, I want 待檢查/人工檢查相關 UI 全部消失, so that 介面只剩我用得到的功能。
27. As 使用者, I want M 鍵合併模式維持可用, so that 缺照合併流程不變。
28. As 使用者, I want 資訊欄只剩「報告」「相機」兩頁籤, so that 資訊密度合理。
29. As 使用者, I want 相機頁籤能重新命名相機（如「頂拱左」→「左側壁」）, so that 名稱貼合現場。
30. As 使用者, I want 收合按鈕確實把側欄收起來、再點展開, so that 版面可控。
31. As 使用者, I want 錨點清單與資訊面板各自獨立開關、互不混雜, so that 兩種工作互不干擾（錨點功能本身保留）。

## Implementation Decisions

### 資料模型（schema v4→v5，冪等遷移）

- **index.db** 新增共用類型表：

```sql
CREATE TABLE IF NOT EXISTS defect_types (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  archived INTEGER NOT NULL DEFAULT 0
);
```

種子資料（冪等 INSERT OR IGNORE）：裂縫、滲漏水、剝落、白華、鋼筋外露。類型不綁隧道、不需顏色欄位（Q13：統一單色）。

- **隧道庫**：`photos` 加 `note TEXT`；新增異狀表：

```sql
CREATE TABLE IF NOT EXISTS photo_anomalies (
  id INTEGER PRIMARY KEY,
  photo_id INTEGER NOT NULL REFERENCES photos(id),
  type_id INTEGER NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_anomalies_photo ON photo_anomalies(photo_id);
```

- `flagged`/`review_result` 欄位留存 DB 不做破壞性遷移，僅移除一切讀寫引用。
- 匯入既有隧道庫時自動遷移（沿用 `meta.schema_version` + `PRAGMA table_info()` 冪等檢查模式）。

### API 契約

- `GET /api/defect-types` → `[{id,name,archived}]`；`POST /api/defect-types {name}`（重名回 409）；`DELETE /api/defect-types/{id}` → 未使用則硬刪 `{action:"deleted"}`，已使用則封存 `{action:"archived"}`。
- `PUT /photos/{pid}/annotation` `{note, items:[{id?, type_id, note}]}` → 整批取代語意（原子性、配合編輯 modal 一次儲存），回傳正規化後的結果。刪除整筆＝從 items 移除。
- `overview` 回應的 groups 緊湊陣列增加平行欄位 `ano`（該群組異狀照片數，排除 manual_missing），供軌道繪製，避免新端點二次查詢。
- `GET /api/tunnels/{tid}/anomalies?type_id=&q=&order=asc|desc` → 總覽列資料（join defect_types/photos/photo_groups/cameras：縮圖路徑、camera 名稱、群組 est_mileage_m、類型名稱、備註），排除 manual_missing。
- 移除端點：`POST /photos/{pid}/review`、`POST /photos/{pid}/reset_review`、`POST /photos/{pid}/confirm_flag`（前端本就死碼）。`mark_missing`/`restore` 保留（合併流程用）。
- WebSocket：異狀/備註變更廣播 `annotation_updated`（含 photo_id、群組里程摘要），沿用既有房間模式。
- `PUT /cameras/{seq}` 擴充接受 `name` 欄位（改名），廣播 `camera_updated`。

### 前端 — 編輯介面（OriginalViewer）

- 底部 EXIF 資訊列旁新增「異狀」編輯區（或可摺疊面板）：照片備註 textarea＋異狀列表（每筆：類型下拉/chip 選擇＋備註輸入＋刪除）＋「＋新增異狀」＋「＋新增類型」（inline 輸入框）＋儲存鈕（呼叫批次 PUT）。
- 類型列表每項附 ×：未使用→刪除；已使用→封存＋toast 說明。封存項目不出現在任何選擇器。
- 樣式沿用既有 tokens/components.css 變數與元件語彙，不引入新樣式體系。

### 前端 — 里程條（ScrubberRail 重繪）

- 保持 canvas 實作。刻度引擎：依可視寬度與群組密度自適應主刻度間距（候選 5/10/20/50/100 m），次要刻度細線、主要刻度粗線＋`K{km}+{mmm}` 標籤；左右端起訖樁號釘選顯示。
- 當前位置：琥珀色指示線＋箭頭升級為含樁號的醒目浮標（pill 讀數）。
- 異狀標記：單一固定色（紫紅色系，與缺照系，與缺照紅、錨點藍、比例異常琥珀區隔）於軌道下方緣短線；同位置多筆合併為單一標記。hover tooltip（HTML 層非 canvas）：縮圖＋類型名列表＋樁號；點擊跳轉該群組。
- 圖例改渲染於 canvas 下方獨立 flex row（`.rail-wrap` 高度調整），絕對定位重疊問題消除；圖例項目更新為最終標記集（錨點/缺照/比例異常/異狀/當前位置）。
- 幫助：軌道右端 `?` 按鈕 → 全螢幕 modal，分區列出快捷鍵（Esc/Ctrl+G/←→/Home/End/Enter/M/R/Tab/? 等）與各功能一段說明。

### 前端 — 異狀總覽頁

- ViewerPage 頂部工具列加 segmented control「檢視｜異狀總覽」（同分頁內模式切換，不新增 App tab）。
- 總覽版面：頂部工具列（類型 chips＋計數、搜尋框、排序切換、返回檢視）＋卡片牆（響應式 grid）。卡片：縮圖、類型 badges、樁號大字、相機名、備註摘要、編輯鈕、定位鈕。
- 卡片點擊＝編輯 modal（縮圖＋備註＋異狀 items 編輯，複用編輯介面的表單邏輯）；「定位」＝切回檢視模式、跳轉群組、該 tile 閃爍提示（不自動開原圖）。
- 資料載入走 `/anomalies` 端點；WS `annotation_updated` 到达時局部刷新。

### 移除複核機制

- 前端：TunnelInfoPanel 移除「待檢查/人工檢查」頁籤與其列表邏輯；CameraGrid 移除 flagged 紅框與「待檢查」chip；api.js 移除 reviewPhoto/resetReview/confirmFlag 死碼包裝；ReviewMode（M）功能不變，修復 `setError` 未宣告 bug；快捷鍵說明同步更新。
- 後端：service/api 移除 review 相關路由與 info() 的 reviewed/flagged 輸出；importer 內部旗標計算留存不動（零風險），匯入報告 JSON 結構不變。

### 資訊欄整理

- TunnelInfoPanel 頁籤精簡為「報告」「相機」；相機頁籤加改名輸入（blur/Enter 送出）。
- 收合：移除 `.siderail.mini` 三態邏輯，改單一布林顯示↔隱藏（頂欄資訊鈕切換），CSS 同步清理。
- 錨點面板解耦：AnchorDrawer 改為獨立可開關面板（自有切換鈕，不再嵌於資訊側欄內），功能（跳轉/刪除）不變；AnchorDialog（Enter）不變。

### 測試縫（seams）

沿既有最高縫，不新增縫：

1. **API 整合縫**（FastAPI TestClient）：`backend/tests/` 新增異狀測試——類型 CRUD＋封存語意、annotation 批次 PUT roundtrip、overview `ano` 計數、manual_missing 排除、`/anomalies` 篩選排序、遷移 v4→v5 冪等、review 端點已移除（404）。Prior art：`test_revision_api.py`、`test_revision2_api.py`。
2. **純函式縫**：ScrubberRail 刻度間距選擇函式抽為純函式（輸入寬度/密度→主刻度間距），單元測試候選值映射。Prior art：`test_interp.py`。
3. **E2E/手動縫**：`e2e_check.py` Playwright 流程回歸＋手動檢核清單（標註→軌道標記→tooltip→總覽→定位→幫助 modal→收合→錨點面板獨立）。
4. 回歸門檻：`uv run pytest -q` 全綠（受影響舊測試同步修正）、`oxlint`、`vite build` 成功。

## Out of Scope

- 照片圖面上的空間座標標註（點/框選）——schema 已預留日後擴充空間
- 異狀嚴重度、處理狀態、位置描述欄位（Q4：後續擴充）
- 類型自選顏色、per-type 彩色軌道標記
- 總覽頁里程範圍篩選、CSV/PDF 匯出報告
- `flagged`/`review_result` DB 欄位移除（破壞性遷移不做）
- 錨點功能變更（僅面板解耦）
- ReviewMode 行為變更（僅修 bug）

## Further Notes

- 所有新 UI 需符合既有設計語彙（tokens.css 變數、components.css 元件樣式），不得引入新視覺體系——使用者特別要求風格一致性。
- 完成驗證後須：更新 README（新功能說明＋快捷鍵表）、git commit & push。
- 異狀標記色票採 `#e857a0`（紫紅），與缺照紅、錨點藍、比例異常琥珀並排可辨。
- `photo_anomalies.type_id` 不設 FK 約束（SQLite 跨庫引用不可能，防呆由 service 層保證），封存/刪除語意已涵蓋孤兒情境。
- 實作差異記錄：刻度間距選擇 `pickStep` 保留於 ScrubberRail 元件內（前端尚無測試運行器，未抽 lib 未單測）；刻度候選值擴充至 5–2000s 共 10 檔；總覽頁類型計數以未過濾請求維持（篩選不影響其他 chips 數字）；`?` 幫助入口同時存在於頂欄與圖例列。
