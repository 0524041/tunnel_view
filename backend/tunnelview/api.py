"""FastAPI 應用：隧道、群組視窗、錨點（含 WebSocket 廣播）、照片串流。"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from .db import Workspace
from .interp import AnchorOrderError, AnchorRangeError
from .importer import CameraInput, ImportRequest, TunnelImporter
from .service import TunnelService


class CameraBody(BaseModel):
    name: str
    folder: str


class ImportBody(BaseModel):
    name: str = Field(min_length=1)
    start_m: int
    end_m: int
    tolerance_seconds: float = Field(gt=0)
    cameras: list[CameraBody] = Field(min_length=1)


class AnchorBody(BaseModel):
    mileage_m: int


class _Hub:
    """每條隧道一個房間；寫入事件廣播給所有連線中的檢視端。"""

    def __init__(self):
        self._rooms: dict[int, list[WebSocket]] = defaultdict(list)
        self._loops: dict[int, asyncio.AbstractEventLoop] = {}

    async def join(self, tunnel_id: int, ws: WebSocket) -> None:
        self._loops[tunnel_id] = asyncio.get_running_loop()
        await ws.accept()
        self._rooms[tunnel_id].append(ws)

    def leave(self, tunnel_id: int, ws: WebSocket) -> None:
        try:
            self._rooms[tunnel_id].remove(ws)
        except ValueError:
            pass

    def broadcast(self, tunnel_id: int, payload: dict) -> None:
        conns = [w for w in self._rooms.get(tunnel_id, []) if w.client_state.name == "CONNECTED"]
        loop = self._loops.get(tunnel_id)
        if not conns or loop is None:
            return

        async def _send():
            for w in conns:
                try:
                    await w.send_json(payload)
                except Exception:
                    self.leave(tunnel_id, w)

        try:
            asyncio.run_coroutine_threadsafe(_send(), loop)
        except RuntimeError:
            pass


def create_app(workspace: Workspace) -> FastAPI:
    app = FastAPI(title="Tunnel View", docs_url=None, redoc_url=None)
    service = TunnelService(workspace)
    importer = TunnelImporter(workspace)
    hub = _Hub()

    @app.get("/api/tunnels")
    def list_tunnels():
        return [
            {
                "tunnel_id": t.tunnel_id,
                "name": t.name,
                "start_m": t.start_m,
                "end_m": t.end_m,
                "camera_count": t.camera_count,
            }
            for t in workspace.list_tunnels()
        ]

    @app.post("/api/tunnels/preview")
    def preview_import(body: ImportBody):
        req = ImportRequest(
            name=body.name,
            start_m=body.start_m,
            end_m=body.end_m,
            tolerance_seconds=body.tolerance_seconds,
            cameras=[CameraInput(name=c.name, folder=c.folder) for c in body.cameras],
        )
        return importer.preview(req)

    @app.post("/api/tunnels")
    def create_tunnel(body: ImportBody):
        req = ImportRequest(
            name=body.name,
            start_m=body.start_m,
            end_m=body.end_m,
            tolerance_seconds=body.tolerance_seconds,
            cameras=[CameraInput(name=c.name, folder=c.folder) for c in body.cameras],
        )
        info = importer.commit(req)
        return {"tunnel_id": info.tunnel_id}

    @app.get("/api/tunnels/{tid}/meta")
    def tunnel_meta(tid: int):
        return service.meta(tid)

    @app.get("/api/tunnels/{tid}/overview")
    def tunnel_overview(tid: int):
        return service.overview(tid)

    @app.get("/api/tunnels/{tid}/groups")
    def groups(tid: int, around: int = 0, before: int = 25, after: int = 50):
        return service.get_window(tid, around=max(around, 0), before=max(before, 0), after=max(after, 0))

    @app.get("/api/tunnels/{tid}/groups/by_mileage")
    def group_by_mileage(tid: int, m: int):
        hit = service.nearest_by_mileage(tid, m)
        if hit is None:
            raise HTTPException(404, "此隧道沒有任何群組")
        return hit

    @app.get("/api/tunnels/{tid}/anchors")
    def anchors(tid: int):
        return service.list_anchors(tid)

    @app.put("/api/tunnels/{tid}/anchors/{seq}")
    async def put_anchor(tid: int, seq: int, body: AnchorBody):
        try:
            service.set_anchor(tid, seq, body.mileage_m)
        except (AnchorOrderError, AnchorRangeError) as e:
            raise HTTPException(400, str(e))
        hub.broadcast(tid, {"type": "anchor_update", "anchor": {"group_seq": seq, "mileage_m": body.mileage_m}})
        return {"ok": True}

    @app.delete("/api/tunnels/{tid}/anchors/{seq}")
    async def delete_anchor(tid: int, seq: int):
        try:
            service.delete_anchor(tid, seq)
        except KeyError:
            raise HTTPException(404, "錨點不存在")
        hub.broadcast(tid, {"type": "anchor_delete", "group_seq": seq})
        return {"ok": True}

    @app.get("/api/tunnels/{tid}/photos/{photo_id}")
    def photo(tid: int, photo_id: int, w: int | None = None):
        path = _safe_photo(service, tid, photo_id)
        if w is None:
            return FileResponse(path, media_type="image/jpeg")
        cache = Path(workspace.root) / ".thumb_cache" / f"{tid}_{photo_id}_{w}.jpg"
        if not cache.exists():
            img = Image.open(path)
            img.draft("RGB", (w * 2, w * 2))
            img = img.convert("RGB")
            ratio = w / img.width
            resized = img.resize((w, max(1, round(img.height * ratio))), Image.BILINEAR)
            cache.parent.mkdir(parents=True, exist_ok=True)
            resized.save(cache, "JPEG", quality=87)
        return FileResponse(cache, media_type="image/jpeg")

    @app.websocket("/ws/tunnels/{tid}")
    async def ws_room(websocket: WebSocket, tid: int):
        await hub.join(tid, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.leave(tid, websocket)

    dist = _find_dist()
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")

    return app


def _find_dist():
    env = os.environ.get("TUNNELVIEW_DIST")
    if env and Path(env).is_dir():
        return Path(env)
    candidate = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if candidate.is_dir():
        return candidate
    return None


def _safe_photo(service: TunnelService, tid: int, photo_id: int) -> Path:
    try:
        path = service.photo_file(tid, photo_id)
    except KeyError:
        raise HTTPException(404, "照片不存在")
    if not Path(path).exists():
        raise HTTPException(404, "照片檔案遺失（原檔可能被移動）")
    return Path(path)
