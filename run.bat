REM Copyright (C) 2026 willywu <pop2585158@gmail.com>
REM SPDX-License-Identifier: GPL-3.0-only
REM
REM This program is free software: you can redistribute it and/or modify
REM it under the terms of the GNU General Public License as published by
REM the Free Software Foundation, either version 3 of the License, or
REM (at your option) any later version.

@echo off
rem Tunnel View 一鍵啟動（Windows，uv 管理 Python 與依賴）
rem 用法:
rem   run.bat              正常啟動
rem   run.bat restart      重啟（不清除快取）
rem   run.bat clear-cache  清除圖片快取後重啟
rem   run.bat clean        清除圖片快取 + uv 快取後重啟
cd /d %~dp0

if "%~1"=="--help" goto :help
if "%~1"=="-h" goto :help
if "%~1"=="help" goto :help
if /I "%~1"=="restart" goto :ensure_uv
if /I "%~1"=="--restart" goto :ensure_uv
if /I "%~1"=="clear-cache" goto :clear_thumb
if /I "%~1"=="--clear-cache" goto :clear_thumb
if /I "%~1"=="clear_cache" goto :clear_thumb
if /I "%~1"=="clean" goto :clear_all
if /I "%~1"=="--clean" goto :clear_all
if not "%~1"=="" (
  echo [run.bat] 未知參數: %~1
  goto :help
)
goto :ensure_uv

:help
echo 用法: run.bat [指令]
echo.
echo 指令:
echo   (無)              正常啟動服務
echo   restart           重啟（不清除快取）
echo   clear-cache       清除圖片縮圖快取 (.thumb_cache) 後重啟
echo   clean             清除圖片快取 + uv 快取後重啟
echo   --help            顯示此說明
echo.
echo 快取說明:
echo   - 圖片快取: data\.thumb_cache (可安全刪除，下次瀏覽自動重建)
echo   - uv 快取: %%LOCALAPPDATA%%\uv\cache (由 uv 管理)
echo.
echo 範例:
echo   run.bat restart
echo   run.bat clean
exit /b 0

:clear_thumb
echo [run.bat] 清除圖片快取...
if exist data\.thumb_cache (
  rmdir /s /q data\.thumb_cache 2>nul
  echo [run.bat] 已清除 data\.thumb_cache
) else (
  echo [run.bat] 無圖片快取需清除
)
if /I "%~1"=="clean" goto :clear_uv
if /I "%~1"=="--clean" goto :clear_uv
goto :ensure_uv

:clear_all
echo [run.bat] 清除圖片快取...
if exist data\.thumb_cache rmdir /s /q data\.thumb_cache 2>nul
echo [run.bat] 已清除
:clear_uv
echo [run.bat] 清除 uv 快取...
where uv >nul 2>nul
if %errorlevel% equ 0 (
  uv cache clean 2>nul || uv cache prune 2>nul
  echo [run.bat] uv 快取已清除
) else (
  echo [run.bat] 未找到 uv，跳過 uv 快取清除
)
goto :ensure_uv

:ensure_uv
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
