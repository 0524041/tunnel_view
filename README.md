# TunnelView 隧道多視角檢視平台

車載多相機隧道檢測照片的**時間對齊、里程定位與多視角同步檢視**工具。
以「隧道」為專案單位、「快門群組」為最小檢視單元，透過實體里程牌錨定達成公尺級照片定位。

```
┌──────────────────────────────────────────────────┐
│  頂欄：隧道名 │ 里程搜尋 Ctrl+G │ 群組/推算里程讀數      │
├──────────────────────────────────────────────────┤
│                                                  │
│        相機網格（1–8 格自適應、同步平移縮放）           │
│                                                  │
├──────────────────────────────────────────────────┤
│  Scrubber 導航軌：錨點🔵 缺照🔴 比例異常🔶 當前位置      │
└──────────────────────────────────────────────────┘
          右側抽屜：錨點管理 / 隧道資訊面板
```

## 核心功能

| 領域 | 能力 |
|---|---|
| 匯入對齊 | EXIF 時間排序、未對時相機 Δt 校正、**單調一對一序列對齊**（缺照補 NULL、首張漏拍自動救回、秒級量化精煉） |
| 里程定位 | 實體里程牌錨定（`K23+150`／`23K+150`／`23+150`／`23150` 四格式）、分段線性內插＋外插、全線毫秒重算 |
| 檢視 | 多視角同步 pan/zoom、動態縮圖＋原圖逐像素放大、鍵盤全程操作 |
| 版型 | 相機自由排序（拖曳／點選交換格位）、欄數自訂、建立精靈即時縮圖預覽、事後於資訊面板調整 |
| 路徑 | 伺服器端目錄瀏覽器：磁碟代號列舉、UNC（`\\NAS\share`）支援、最近路徑書籤——NAS 照片直接讀 |
| 品質工具 | 待檢查清單（確認／標注異常、自動跳下一筆、卡片縮圖）、檢閱模式三聯比較與群組合併、比例異常偵測（導航軌菱形標記）與就地旋轉 |
| 檢視體驗 | 完整呈現（contain）／填滿（cover）切換、常駐資訊側欄（錨點｜資訊頁籤）、三段響應式斷點、操作 toast 回饋 |
| 維運 | 一隧道一 SQLite 檔隨身交付、區網多機即時協同（WebSocket）、舊庫開啟自動遷移 |

## 快速開始

**套件與 Python 皆由 [uv](https://docs.astral.sh/uv/) 管理，無需手動安裝 Python / pip。** 前端已預建於 `frontend/dist`，**不需要 Node.js**。

```bash
# macOS / Linux（bash 為主，相容 zsh；會自動處理 uv 與 Python）
./run.sh

# Windows
run.bat
```

啟動後瀏覽 `http://localhost:8000`。資料目錄預設為 `./data`，可用環境變數調整：

| 變數 | 預設 | 說明 |
|---|---|---|
| `TUNNELVIEW_HOME` | `./data` | index.db 與各隧道 .db 所在目錄 |
| `TUNNELVIEW_PORT` | `8000` | 監聽埠 |
| `TUNNELVIEW_DIST` | 自動偵測 | 前端靜態檔目錄 |

### 安裝 uv（僅需一次）

`run.sh` 若偵測不到 `uv` 會嘗試自動安裝（需 `curl` 或 `wget`），建議先手動安裝一次，空 Ubuntu 也能一鍵起飛：

```bash
# Linux / macOS 官方獨立安裝（不依賴系統 python/pip）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 讓當前 shell 生效（擇一）
source $HOME/.local/bin/env
# 或
export PATH="$HOME/.local/bin:$PATH"

uv --version  # 驗證
```

其他安裝方式：

| 平台 | 指令 |
|---|---|
| Windows (PowerShell) | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Homebrew | `brew install uv` |
| pipx / pip | `pipx install uv` 或 `pip install uv` |

> 空 Ubuntu 一鍵部署範例（什麼都沒有的機器）：
> ```bash
> sudo apt update && sudo apt install -y curl git
> git clone <repo-url> && cd tunnel_view
> curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
> ./run.sh  # 自動下載 Python 3.11+、同步依賴並啟動
> ```

### 從原始碼建置前端（僅開發時需要）

```bash
cd frontend && npm install && npm run build
```

### 快取與重啟

| 快取 | 位置 | 說明 | 刪除方式 |
|---|---|---|---|
| 圖片縮圖 | `$TUNNELVIEW_HOME/.thumb_cache`（預設 `data/.thumb_cache`） | 動態縮圖（`w=1600` / 原圖旋轉後），可安全刪除，下次瀏覽自動重建 | `rm -rf data/.thumb_cache` 或一鍵指令 |
| uv 下載快取 | `~/.cache/uv`（Linux）/ `~/Library/Caches/uv`（macOS）/ `%LOCALAPPDATA%\uv\cache`（Windows） | `uv` 下載的 wheel 與 Python 版本 | `uv cache clean` |

```bash
# 正常啟動 / 重啟（不清除快取）
./run.sh
./run.sh restart
run.bat
run.bat restart

# 單獨清除快取（縮圖異常、旋轉後仍顯示舊圖時使用）
./run.sh clear-cache
run.bat clear-cache

# 完全重置：圖片快取 + uv 快取（磁碟空間不足時使用，下次啟動會重新下載）
./run.sh clean
run.bat clean

# 查看說明
./run.sh --help
```

### 手動啟動（不等於一鍵腳本）

```bash
uv sync                  # 同步依賴（自動下載 Python）
uv run python server.py  # 啟動服務
uv run pytest backend/tests/ -q  # 測試

# 手動清快取
rm -rf data/.thumb_cache          # 圖片快取
uv cache clean                    # uv 快取（或 uv cache prune）
```

## 使用流程

1. **建立隧道**：首頁 →「建立新隧道」→ 名稱＋起訖樁號（方向由此決定）→ 步驟二為**版型編輯器**：逐台 📁 選資料夾（首張縮圖自動載入、旋轉當場預覽）、拖曳或點選兩格安排相機位置與欄數 → 對齊分析預覽（Δt 表、缺照分佈）→ 建立
2. **巡覽檢查**：`←`/`→` 逐群組翻閱（每按一次＝一次快門事件）
3. **里程錨定**：看到實體里程碑按 `Enter`，預填推算值直接改數字；全線推算里程即時更新（`~` 前綴＝推算值）
4. **精修**：資訊面板可調容差「乾跑預覽」後重新對齊——錨點綁定照片，重建零遺失
5. **複核**：待檢查清單逐筆跳轉、✅檢查OK／🚩標注異常並自動前進；`M` 檢閱邊界合併拆裂群組

### 快捷鍵

| 鍵 | 動作 |
|---|---|
| `←` `→` | 前／後一群組 |
| `Enter` | 錨點對話框（預填推算值） |
| `M` | 檢閱模式（三聯比較、合併群組） |
| `Ctrl+G` | 里程跳轉搜尋 |
| `Home` / `End` | 首／末群組 |
| 滾輪 / 拖曳 | 同步縮放 / 平移（雙擊復原） |
| 點擊照片格 | 全螢幕原圖（滾輪逐像素放大、`Tab` 切換視角、`R` 旋轉、`Esc` 關閉） |

## NAS / 網路路徑部署

照片可放在 NAS，伺服器經網路讀取即可：

| Server 環境 | 建議路徑格式 |
|---|---|
| Windows | **UNC 直接貼上**：`\\NAS名稱\分享\Cam1`（不建議依賴對應磁碟機代號——代號綁定登入工作階段，服務化執行後會失效） |
| WSL | CIFS 掛載後使用 `/mnt/nas/Cam1` |
| macOS | `/Volumes/nas/Cam1` |

- 遠端瀏覽器使用者看到的是 **Server 的目錄**（設計如此，瀏覽端零安裝）
- 縮圖首次生成需跨網路讀原檔（較慢），之後快取在伺服器本機 `.thumb_cache`——日常瀏覽不吃網路；放大看原圖才再次存取 NAS
- Windows 磁碟代號由系統 API 列舉，斷線的網路碟不會凍結介面

## 架構

```
backend/tunnelview/
  align.py       時間對齊引擎（純函式核心）
                 完整度搜尋救回首張漏拍 → 配對差中位數迭代精煉吸收
                 EXIF 秒級量化 → 單調一對一掃描配對 → 殘差旗標
  interp.py      里程內插引擎：等分初始化、分段線性、外插夾限、單調防呆
  mileage.py     樁號解析（四種格式 → 整數公尺）
  anchor_model.py 錨點模型 v2：綁定載體照片而非群組 seq，
                 重新對齊／合併重排後自動落位、零遺失
  db.py          一隧道一 SQLite（WAL）+ index.db 索引；
                 schema 版本化，舊庫開啟自動遷移
  importer.py    資料夾掃描、EXIF 讀取（缺漏退 mtime 並標記）、
                 比例異常偵測（唯讀檔頭，不解碼全圖）
  service.py     視窗查詢、里程跳轉、重新對齊、合併、複核、旋轉、版型
  fsutil.py      平台磁碟根列舉（Windows GetLogicalDrives）
  api.py         FastAPI 路由 + WebSocket 房間廣播 + 動態縮圖（磁碟快取）+ 目錄瀏覽

frontend/src/
  pages/HomePage.jsx      首頁隧道清單（含刪除）
  pages/WizardPage.jsx    建立精靈（資料夾瀏覽器、對齊預覽）
  pages/ViewerPage.jsx    檢視器主體（狀態編排、快捷鍵）
  components/CameraGrid   自適應網格、同步 pan/zoom、缺照佔位、⟳ 旋轉鈕
  components/ScrubberRail canvas 導航軌（縮放、四種標記）
  components/TunnelInfoPanel 報告 / 重新對齊 / 待檢查 / 相機旋轉
  components/LayoutEditor 自由版型編輯器（拖曳交換、真實縮圖、嚮導與面板共用）
  components/FsBrowser    伺服器端目錄瀏覽器（磁碟根、最近路徑、首張預覽）
  components/ReviewMode   三聯比較與合併裁決
  components/OriginalViewer 原圖覆蓋層 + 底部 EXIF 資訊列
```

### 資料模型要點

- **照片原地引用**：每台相機存一個根路徑，照片只記相對路徑——不複製、不入庫；換機器改一個欄位即可
- **推算里程具體化**：錨點變更以批次 SQL 重算 `photo_groups.est_mileage_m`，導航軌與跳轉直接範圍查詢
- **併發語意**：所有寫入走 API 單一管道，WAL 保證讀寫不互斥；錨點變更經 WebSocket 廣播，同群組衝突採後寫勝
- ⚠️ `.db` 與照片必須在**伺服器本機磁碟**（SQLite 不容忍網路共用磁碟）

## 測試

```bash
uv run pytest backend/tests/ -q     # 後端單元 + API 整合（119 tests）
# 或
uv run python -m pytest backend/tests/ -q

# 端對端（需 Playwright chromium；以樣本資料夾跑完整使用者流程）
TUNNELVIEW_HOME=/tmp/tvdata uv run python \
  /path/to/webapp-testing/scripts/with_server.py \
  --server "uv run python server.py" --port 8000 \
  -- uv run python e2e_check.py ./八卦山西行
```

測試縫：① 對齊引擎純函式核心（合成 fixture：漏拍／漂移／雙拍／量化）② 內插與防呆 ③ FastAPI 整合層（匯入→查詢→錨點→廣播→併發遷移）。

## 規格文件

- `.spec/tunnel-viewer-mvp.md` — MVP 規格（含效能預算與實測值）
- `.spec/revision-1-alignment-review-display.md` — R1 修訂（錨點 v2、重新對齊、檢閱合併、原圖檢視、旋轉體系）
