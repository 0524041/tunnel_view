#!/bin/zsh
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "建立 Python 虛擬環境..."
  python3 -m venv .venv || exit 1
fi
. .venv/bin/activate
pip install -q -r requirements.txt
if [ ! -d frontend/dist ]; then
  echo "[警告] frontend/dist 不存在，僅提供 API。請先: (cd frontend && npm install && npm run build)"
fi
python server.py
