@echo off
rem Tunnel View 一鍵啟動（Windows）
cd /d %~dp0
if not exist .venv (
  echo 建立 Python 虛擬環境...
  python -m venv .venv || (echo 需要 Python 3.11+ & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
if not exist frontend\dist (
  echo [警告] frontend\dist 不存在，僅提供 API。請先執行: cd frontend ^&^& npm install ^&^& npm run build
)
start "" http://localhost:8000
python server.py
pause
