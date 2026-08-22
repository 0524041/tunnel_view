#!/usr/bin/env bash
# Tunnel View 一鍵啟動（Linux / macOS，bash 優先，相容 zsh 呼叫）
# 依賴：curl 或 wget（僅首次安裝 uv 時需要），其餘由 uv 自動管理（含 Python）
#
# 用法：
#   ./run.sh              正常啟動
#   ./run.sh restart      重啟（不清除快取）
#   ./run.sh clear-cache  清除圖片快取後重啟
#   ./run.sh clean        清除圖片快取 + uv 快取後重啟
#   ./run.sh --help       顯示說明
set -e
cd "$(dirname "$0")"

# 允許 TUNNELVIEW_HOME 環境變數覆寫，未設定則預設 ./data（與 server.py 一致）
THUMB_HOME="${TUNNELVIEW_HOME:-data}"

show_help() {
  cat <<'HELP'
用法: ./run.sh [指令]

指令:
  (無)              正常啟動服務
  restart           重啟（不清除快取，等同直接執行 ./run.sh）
  clear-cache       清除圖片縮圖快取 (.thumb_cache) 後重啟
  clean             清除圖片快取 + uv 快取後重啟
  --help, -h        顯示此說明

快取說明:
  - 圖片快取: $THUMB_HOME/.thumb_cache (動態縮圖，可安全刪除，下次瀏覽自動重建)
  - uv 快取:  ~/.cache/uv (Linux) / ~/Library/Caches/uv (macOS)，由 uv 管理

範例:
  ./run.sh restart          # 一般重啟
  ./run.sh clear-cache      # 縮圖異常、旋轉後仍顯示舊圖時使用
  ./run.sh clean            # 磁碟空間不足或想完全重置時使用
  TUNNELVIEW_HOME=/tmp/tvdata ./run.sh clear-cache
HELP
}

clear_thumb_cache() {
  local dir="$1/.thumb_cache"
  if [ -d "$dir" ]; then
    echo "[run.sh] 清除圖片快取: $dir"
    rm -rf "$dir"
    echo "[run.sh] 已清除"
  else
    echo "[run.sh] 無圖片快取需清除: $dir"
  fi
}

clear_uv_cache() {
  if command -v uv >/dev/null 2>&1; then
    echo "[run.sh] 清除 uv 快取..."
    uv cache clean 2>/dev/null || uv cache prune 2>/dev/null || true
    echo "[run.sh] uv 快取已清除"
  else
    # uv 尚未安裝時，嘗試刪除常見快取目錄
    for d in "$HOME/.cache/uv" "$HOME/Library/Caches/uv" "$HOME/.local/share/uv"; do
      if [ -d "$d" ]; then
        echo "[run.sh] 刪除 $d"
        rm -rf "$d"
      fi
    done
  fi
}

# --- 參數處理 ---
DO_CLEAR_THUMB=0
DO_CLEAR_UV=0
case "${1:-}" in
  --help|-h|help)
    show_help
    exit 0
    ;;
  restart|--restart)
    # 僅重啟，不清除快取
    ;;
  clear-cache|--clear-cache|clear_cache|--clear_cache|--clear_thumb|--clear-thumb)
    DO_CLEAR_THUMB=1
    ;;
  clean|--clean)
    DO_CLEAR_THUMB=1
    DO_CLEAR_UV=1
    ;;
  "")
    ;;
  *)
    echo "[run.sh] 未知參數: $1"
    show_help
    exit 1
    ;;
esac

if [ "$DO_CLEAR_THUMB" = 1 ]; then
  clear_thumb_cache "$THUMB_HOME"
fi
if [ "$DO_CLEAR_UV" = 1 ]; then
  clear_uv_cache
fi

# --- 確保 uv 可用（空 Ubuntu 無 python/pip 也能跑） ---
if ! command -v uv >/dev/null 2>&1; then
  # 已透過安裝腳本裝好但不在 PATH（例如 ~/.local/bin）
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  elif [ -x "$HOME/.cargo/bin/uv" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  else
    echo "[run.sh] 未偵測到 uv，正在自動安裝..."
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | sh
    else
      echo "[錯誤] 需要 curl 或 wget 來安裝 uv。"
      echo "請手動安裝：curl -LsSf https://astral.sh/uv/install.sh | sh"
      echo "或參考 README「安裝 uv」章節。"
      exit 1
    fi
    # 安裝後補 PATH
    if [ -x "$HOME/.local/bin/uv" ]; then
      export PATH="$HOME/.local/bin:$PATH"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
      export PATH="$HOME/.cargo/bin:$PATH"
    fi
    if ! command -v uv >/dev/null 2>&1; then
      echo "[錯誤] uv 安裝後仍無法在 PATH 找到，請重新開啟終端或執行：export PATH=\"\$HOME/.local/bin:\$PATH\""
      exit 1
    fi
  fi
fi

# --- 同步依賴（會自動下載對應 Python 版本，無需系統 python） ---
uv sync --frozen 2>/dev/null || uv sync

if [ ! -d frontend/dist ]; then
  echo "[警告] frontend/dist 不存在，僅提供 API。請先: (cd frontend && npm install && npm run build)"
  echo "       （前端已預建，通常無需此步驟）"
fi

# --- 啟動服務（uv run 自動使用專案虛擬環境） ---
exec uv run python server.py
