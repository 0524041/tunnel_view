#!/usr/bin/env bash
# Tunnel View 一鍵啟動（Linux / macOS，bash 優先，相容 zsh 呼叫）
# 依賴：curl 或 wget（僅首次安裝 uv 時需要），其餘由 uv 自動管理（含 Python）
set -e
cd "$(dirname "$0")"

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
