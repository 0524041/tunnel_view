# AGENTS.md

## Purpose
TunnelView — multi-camera tunnel inspection viewer. Aligns photos by EXIF time, locates each shot group by mileage (anchor interpolation), and provides synchronized multi-view inspection with defect annotation.

## Stack
- Backend: Python 3.11+, FastAPI, Pillow, SQLite (WAL), `uv`
- Frontend: React 19, Vite, `oxlint`
- Prebuilt `frontend/dist` is committed; Node.js only needed to rebuild.

## Build & Run
```bash
./run.sh              # smart deploy + start (http://localhost:8000)
./run.sh build        # frontend only: npm install + vite build
./run.sh stop|status|logs

# manual
uv sync                           # install deps + create .venv
cd frontend && npm install && npm run build
uv run python server.py           # start
```

Env: `TUNNELVIEW_HOME` (default `./data`), `TUNNELVIEW_PORT` (default `8000`).

## Test
```bash
uv run pytest backend/tests/ -q              # 132 tests (pytest pythonpath=backend)
uv run python e2e_check.py ./八卦山西行      # e2e (requires: uv run playwright install chromium)

# lint
cd frontend && npx oxlint src
```

## Layout
- `backend/tunnelview/` — `align.py`, `interp.py`, `db.py`, `service.py`, `api.py`, `importer.py`
- `frontend/src/` — `pages/ViewerPage.jsx`, `components/*`, `lib/api.js`
- `data/` — `index.db` + `tunnel_*.db` (gitignored)
- `.spec/` — specs

## Notes
- VS Code: interpreter is `.venv/bin/python`; `python.analysis.extraPaths` includes `backend` (see `.vscode/settings.json`).
- License: GPL-3.0-only. Source headers required.
