#!/usr/bin/env bash
# Copyright (C) 2026 willywu <pop2585158@gmail.com>
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Tunnel View 一鍵啟動（Linux / macOS，bash 優先，相容 zsh 呼叫）
# 依賴：curl 或 wget（僅首次安裝 uv 時需要），其餘由 uv 自動管理（含 Python）
#
# Smart Deploy：比對前端原始碼雜湊（.deploy_state），有變更才重新編譯（需 Node.js）；
# 無 Node.js 時沿用現有 frontend/dist。服務以背景進程執行：
# 日誌寫入 server.log，PID 記錄於 .server.pid。
#
# 用法：
#   ./run.sh              Smart Deploy 啟動（背景執行）
#   ./run.sh restart      重啟
#   ./run.sh stop         停止服務
#   ./run.sh status       查看狀態
#   ./run.sh logs [-f]    查看日誌（-f 動態追蹤）
#   ./run.sh build        只編譯前端，不啟動
#   ./run.sh clear-cache  清除圖片快取後啟動
#   ./run.sh clean        清除圖片快取 + uv 快取後啟動
#   ./run.sh --help       顯示說明
set -e
cd "$(dirname "$0")"

PORT="${TUNNELVIEW_PORT:-8000}"
THUMB_HOME="${TUNNELVIEW_HOME:-data}"
LOG_FILE="server.log"
PID_FILE=".server.pid"
STATE_FILE=".deploy_state"

log()  { echo "[run.sh] $*"; }
warn() { echo "[run.sh][警告] $*"; }
die()  { echo "[run.sh][錯誤] $*" >&2; exit 1; }

show_help() {
  cat <<HELP
用法: ./run.sh [指令]

指令:
  (無)              Smart Deploy 啟動：前端有變更才重新編譯，背景執行
  restart           重啟（Smart Deploy）
  stop              停止服務
  status            查看服務狀態
  logs [-f]         查看日誌（-f 動態追蹤）
  build             只編譯前端，不啟動
  clear-cache       清除圖片縮圖快取 (.thumb_cache) 後啟動
  clean             清除圖片快取 + uv 快取後啟動
  --help, -h        顯示此說明

說明:
  - 服務以背景進程執行：日誌 server.log、PID .server.pid、部署狀態 .deploy_state
  - 前端編譯需 Node.js；未安裝時沿用現有 frontend/dist（畫面可能非最新）
  - 圖片快取: \$TUNNELVIEW_HOME/.thumb_cache，可安全刪除，下次瀏覽自動重建

範例:
  ./run.sh                  # Smart 啟動
  ./run.sh logs -f          # 動態追蹤日誌
  ./run.sh clear-cache      # 縮圖異常、旋轉後仍顯示舊圖時使用
  TUNNELVIEW_PORT=9000 ./run.sh restart
HELP
}

clear_thumb_cache() {
  local dir="$1/.thumb_cache"
  if [ -d "$dir" ]; then
    log "清除圖片快取: $dir"
    rm -rf "$dir"
    log "已清除"
  else
    log "無圖片快取需清除: $dir"
  fi
}

clear_uv_cache() {
  if command -v uv >/dev/null 2>&1; then
    log "清除 uv 快取..."
    uv cache clean >/dev/null 2>&1 || uv cache prune >/dev/null 2>&1 || true
    log "uv 快取已清除"
  else
    for d in "$HOME/.cache/uv" "$HOME/Library/Caches/uv" "$HOME/.local/share/uv"; do
      if [ -d "$d" ]; then
        log "刪除 $d"
        rm -rf "$d"
      fi
    done
  fi
}

# --- 確保 uv 可用（空 Ubuntu 無 python/pip 也能跑） ---
ensure_uv() {
  command -v uv >/dev/null 2>&1 && return 0
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  elif [ -x "$HOME/.cargo/bin/uv" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  else
    log "未偵測到 uv，正在自動安裝..."
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | sh
    else
      die "需要 curl 或 wget 來安裝 uv。請手動安裝：curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
    if [ -x "$HOME/.local/bin/uv" ]; then
      export PATH="$HOME/.local/bin:$PATH"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
      export PATH="$HOME/.cargo/bin:$PATH"
    fi
  fi
  command -v uv >/dev/null 2>&1 || \
    die "uv 安裝後仍無法在 PATH 找到，請重新開啟終端或執行：export PATH=\"\$HOME/.local/bin:\$PATH\""
}

# ============================================
# Smart Deploy 變更偵測
# ============================================
hash_stdin() {
  if command -v shasum >/dev/null 2>&1; then
    shasum | cut -d' ' -f1
  elif command -v sha1sum >/dev/null 2>&1; then
    sha1sum | cut -d' ' -f1
  elif command -v md5sum >/dev/null 2>&1; then
    md5sum | cut -d' ' -f1
  else
    md5 -q
  fi
}

src_hash() {
  find frontend/src frontend/index.html frontend/vite.config.js -type f 2>/dev/null \
    | sort | hash_stdin
}

lock_hash() {
  if [ -f frontend/package-lock.json ]; then
    cat frontend/package-lock.json | hash_stdin
  else
    echo "missing"
  fi
}

read_state() { grep "^$1=" "$STATE_FILE" 2>/dev/null | cut -d= -f2-; }

save_state() {
  printf 'src=%s\nlock=%s\n' "$(src_hash)" "$(lock_hash)" > "$STATE_FILE"
}

need_install() {
  [ ! -d frontend/node_modules ] && return 0
  [ "$(read_state lock)" != "$(lock_hash)" ]
}

need_build() {
  [ ! -f frontend/dist/index.html ] && return 0
  [ "$(read_state src)" != "$(src_hash)" ]
}

smart_frontend() {
  if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
    need_build && warn "偵測到前端原始碼變更，但無 Node.js/npm 可編譯——沿用現有 dist（畫面可能非最新）"
    return 0
  fi
  if need_install; then
    log "安裝前端依賴 (npm install)..."
    (cd frontend && npm install --no-audit --no-fund) || die "npm install 失敗"
  fi
  if need_build; then
    log "偵測到前端變更，重新編譯..."
    (cd frontend && npm run build) || die "前端編譯失敗"
    log "前端編譯完成"
  else
    log "前端無變更，跳過編譯"
  fi
  save_state
}

build_only() {
  command -v npm >/dev/null 2>&1 || die "需要 Node.js/npm 才能編譯前端"
  if need_install; then
    log "安裝前端依賴 (npm install)..."
    (cd frontend && npm install --no-audit --no-fund) || die "npm install 失敗"
  fi
  log "編譯前端..."
  (cd frontend && npm run build) || die "前端編譯失敗"
  save_state
  log "前端編譯完成"
}

# ============================================
# 進程管理（背景執行）
# ============================================
running_pid() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null)"
  case "$pid" in ''|*[!0-9]*) rm -f "$PID_FILE"; return 1 ;; esac
  ps -p "$pid" -o command= 2>/dev/null | grep -q 'server\.py' || { rm -f "$PID_FILE"; return 1; }
  echo "$pid"
}

stop_service() {
  local pid i
  if pid="$(running_pid)"; then
    log "停止服務 (PID $pid)..."
    kill -TERM "$pid" 2>/dev/null || true
    i=0
    while kill -0 "$pid" 2>/dev/null && [ $i -lt 20 ]; do sleep 0.5; i=$((i+1)); done
    if kill -0 "$pid" 2>/dev/null; then
      warn "未在時限內退出，強制終止"
      kill -9 "$pid" 2>/dev/null || true
    fi
    log "服務已停止"
  elif command -v lsof >/dev/null 2>&1 && lsof -ti:"$PORT" >/dev/null 2>&1; then
    warn "PID 檔不存在但埠 $PORT 被占用，嘗試釋放..."
    lsof -ti:"$PORT" | xargs kill 2>/dev/null || true
    sleep 1
    if lsof -ti:"$PORT" >/dev/null 2>&1; then
      lsof -ti:"$PORT" | xargs kill -9 2>/dev/null || true
    fi
    log "埠 $PORT 已釋放"
  else
    log "服務未運行"
  fi
  rm -f "$PID_FILE"
}

status_service() {
  local pid
  if pid="$(running_pid)"; then
    log "服務運行中：PID $pid · http://127.0.0.1:${PORT} （日誌: ${LOG_FILE}）"
  else
    log "服務未運行（埠 ${PORT}）"
  fi
}

show_logs() {
  [ -f "$LOG_FILE" ] || die "尚無日誌檔 ${LOG_FILE}（服務可能從未啟動）"
  if [ "${1:-}" = "-f" ]; then
    log "動態追蹤 ${LOG_FILE}（Ctrl+C 離開）..."
    tail -f "$LOG_FILE"
  else
    tail -50 "$LOG_FILE"
  fi
}

health_wait() {
  local i=0
  while [ $i -lt 40 ]; do
    if command -v curl >/dev/null 2>&1; then
      curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/tunnels" && { log "服務就緒 ✓"; return 0; }
    elif command -v wget >/dev/null 2>&1; then
      wget -qO /dev/null "http://127.0.0.1:$PORT/api/tunnels" && { log "服務就緒 ✓"; return 0; }
    else
      sleep 2; log "（無 curl/wget，跳過健康檢查）"; return 0
    fi
    sleep 0.5; i=$((i+1))
  done
  warn "服務未在 20 秒內就緒，請查看: ./run.sh logs"
}

start_service() {
  local pid
  if pid="$(running_pid)"; then
    log "服務已在運行 (PID $pid)：http://127.0.0.1:${PORT}"
    return 0
  fi
  ensure_uv
  log "同步 Python 依賴 (uv sync)..."
  uv sync --frozen >/dev/null 2>&1 || uv sync

  smart_frontend

  if [ ! -x ".venv/bin/python" ]; then
    warn "找不到 .venv/bin/python，改以 uv run 啟動"
    nohup uv run python server.py > "$LOG_FILE" 2>&1 &
  else
    nohup .venv/bin/python server.py > "$LOG_FILE" 2>&1 &
  fi
  echo $! > "$PID_FILE"
  disown 2>/dev/null || true

  health_wait
  log "Tunnel View → http://127.0.0.1:${PORT} （PID $(cat "$PID_FILE")，資料目錄: $(cd "$THUMB_HOME" && pwd)）"
  log "管理：./run.sh status｜logs｜logs -f｜stop"
}

restart_service() {
  stop_service
  start_service
}

# --- 參數處理 ---
case "${1:-}" in
  --help|-h|help)
    show_help
    exit 0
    ;;
  restart|--restart)
    restart_service
    ;;
  stop|--stop)
    stop_service
    ;;
  status|--status)
    status_service
    ;;
  logs|--logs)
    shift
    show_logs "${1:-}"
    ;;
  build|--build)
    build_only
    ;;
  clear-cache|--clear-cache|clear_cache|--clear_cache|--clear-thumb|--clear-thumb)
    clear_thumb_cache "$THUMB_HOME"
    start_service
    ;;
  clean|--clean)
    clear_thumb_cache "$THUMB_HOME"
    clear_uv_cache
    start_service
    ;;
  "")
    start_service
    ;;
  *)
    log "未知參數: $1"
    show_help
    exit 1
    ;;
esac
