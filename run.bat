@echo off
rem Tunnel View 一鍵啟動（Windows，uv 管理 Python 與依賴）
cd /d %~dp0

where uv >nul 2>nul
if %errorlevel% neq 0 (
  echo [run.bat] 未偵測到 uv，正在嘗試透過 pip 安裝...
  where python >nul 2>nul
  if %errorlevel% equ 0 (
    python -m pip install -q uv
  ) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
      py -m pip install -q uv
    ) else (
      echo [錯誤] 找不到 uv 且無可用 Python。
      echo 請先安裝 uv：powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
      echo 或參考 README「安裝 uv」章節。
      pause
      exit /b 1
    )
  )
  where uv >nul 2>nul
  if %errorlevel% neq 0 (
    echo [錯誤] uv 安裝後仍無法在 PATH 找到，請重新開啟終端後再試。
    pause
    exit /b 1
  )
)

uv sync --frozen >nul 2>nul || uv sync
if %errorlevel% neq 0 (
  echo [錯誤] 依賴同步失敗
  pause
  exit /b 1
)

if not exist frontend\dist (
  echo [警告] frontend\dist 不存在，僅提供 API。請先執行: cd frontend ^&^& npm install ^&^& npm run build
)

start "" http://localhost:8000
uv run python server.py
pause
