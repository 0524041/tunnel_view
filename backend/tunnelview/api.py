"""FastAPI 應用：隧道、群組視窗、錨點（含 WebSocket 廣播）、照片串流。"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from .db import Workspace
from .fsutil import platform_roots
from .interp import AnchorOrderError, AnchorRangeError
from .importer import CameraInput, ImportRequest, TunnelImporter
from .service import MergeConflict, TunnelService


class CameraBody(BaseModel):
    name: str
    folder: str
    rotation: int = 0
    grid_pos: int = -1


class ImportBody(BaseModel):
    name: str = Field(min_length=1)
    start_m: int
    end_m: int
    tolerance_seconds: float = Field(gt=0)
    layout_cols: str | int = "auto"
    cameras: list[CameraBody] = Field(min_length=1)


class LayoutBody(BaseModel):
    cols: str | int


class FsRecentBody(BaseModel):
    path: str


class AnchorBody(BaseModel):
    mileage_m: int


class RealignBody(BaseModel):
    tolerance_seconds: float = Field(gt=0)


class MergeBody(BaseModel):
    direction: str
    keep: str | None = None


class CameraUpdateBody(BaseModel):
    name: str | None = None
    rotation: int | None = None
    grid_pos: int | None = None


class PhotoRotationBody(BaseModel):
    angle: int


class AnomalyItemBody(BaseModel):
    id: int | None = None
    type_id: int
    note: str | None = None


class AnnotationBody(BaseModel):
    note: str | None = None
    items: list[AnomalyItemBody] = []

class DefectTypeBody(BaseModel):
    name: str = Field(min_length=1)


def _needs_exif_transpose(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            return int((im.getexif() or {}).get(274, 1)) not in (0, 1)
    except Exception:
        return False


def _invalidate_cache(root: Path, tid: int, photo_id: int | None = None) -> None:
    cache_dir = root / ".thumb_cache"
    if not cache_dir.is_dir():
        return
    prefix = f"{tid}_"
    for f in cache_dir.iterdir():
        if (
            f.is_file()
            and f.name.startswith(prefix)
            and (photo_id is None or f"_{photo_id}_" in f.name)
        ):
            f.unlink(missing_ok=True)


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

    def _to_req(body: ImportBody) -> ImportRequest:
        return ImportRequest(
            name=body.name,
            start_m=body.start_m,
            end_m=body.end_m,
            tolerance_seconds=body.tolerance_seconds,
            layout_cols=body.layout_cols,
            cameras=[
                CameraInput(name=c.name, folder=c.folder, rotation=c.rotation, grid_pos=c.grid_pos)
                for c in body.cameras
            ],
        )

    @app.delete("/api/tunnels/{tid}")
    def remove_tunnel(tid: int):
        try:
            workspace.delete_tunnel(tid)
        except KeyError:
            raise HTTPException(404, "隧道不存在")
        return {"ok": True}

    @app.post("/api/tunnels/preview")
    def preview_import(body: ImportBody):
        return importer.preview(_to_req(body))

    @app.post("/api/tunnels")
    def create_tunnel(body: ImportBody):
        info = importer.commit(_to_req(body))
        for cam in body.cameras:
            workspace.add_recent_path(cam.folder)
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

    # ---------- 異狀類型（全工作區共用） ----------

    @app.get("/api/defect-types")
    def list_defect_types():
        return workspace.defect_types()

    @app.post("/api/defect-types")
    def add_defect_type(body: DefectTypeBody):
        try:
            return workspace.add_defect_type(body.name)
        except KeyError as e:
            raise HTTPException(409, str(e.args[0]))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/defect-types/{type_id}")
    def remove_defect_type(type_id: int):
        try:
            action = workspace.remove_defect_type(type_id)
        except KeyError:
            raise HTTPException(404, "類型不存在")
        return {"action": action}

    # ---------- 照片標註（備註＋異狀） ----------

    @app.get("/api/tunnels/{tid}/photos/{pid}/annotation")
    def get_annotation(tid: int, pid: int):
        try:
            return service.annotation(tid, pid)
        except KeyError:
            raise HTTPException(404, "照片不存在")

    @app.put("/api/tunnels/{tid}/photos/{pid}/annotation")
    def put_annotation(tid: int, pid: int, body: AnnotationBody):
        try:
            result = service.set_annotation(tid, pid, body.note, [i.model_dump() for i in body.items])
        except KeyError:
            raise HTTPException(404, "照片不存在")
        except ValueError as e:
            raise HTTPException(400, str(e))
        _invalidate_cache(workspace.root, tid)
        hub.broadcast(
            tid,
            {
                "type": "annotation_updated",
                "photo_id": pid,
                "group_seq": result.get("group_seq"),
                "est_mileage_m": result.get("est_mileage_m"),
            },
        )
        return result

    @app.get("/api/tunnels/{tid}/anomalies")
    def anomalies_overview(
        tid: int,
        type_id: str = "",
        q: str = "",
        order: str = "asc",
    ):
        ids = []
        for part in type_id.split(","):
            part = part.strip()
            if part:
                try:
                    ids.append(int(part))
                except ValueError:
                    raise HTTPException(400, f"無效的 type_id：{part}")
        if order not in ("asc", "desc"):
            raise HTTPException(400, "order 僅接受 asc 或 desc")
        return service.anomaly_overview(tid, type_ids=ids or None, q=q or None, order=order)

    @app.get("/api/fs/list")
    def fs_list(path: str = ""):
        if not path.strip():
            return {
                "roots": platform_roots(),
                "recent": workspace.get_recent_paths(),
                "path": "",
                "parent": None,
                "dirs": [],
                "sample": None,
            }
        target = Path(path).expanduser()
        if not target.is_dir():
            raise HTTPException(404, "資料夾不存在")
        entries = sorted(target.iterdir(), key=lambda x: x.name.lower())
        dirs = [e.name for e in entries if e.is_dir() and not e.name.startswith(".")]
        sample = next(
            (e.name for e in entries if e.is_file() and e.suffix.lower() in {".jpg", ".jpeg"}),
            None,
        )
        return {
            "path": str(target),
            "parent": str(target.parent) if target.parent != target else None,
            "dirs": dirs,
            "sample": sample,
            "recent": workspace.get_recent_paths(),
            "roots": platform_roots(),
        }

    @app.get("/api/fs/photo")
    def fs_photo(path: str):
        f = Path(path).expanduser()
        if not f.is_file() or f.suffix.lower() not in {".jpg", ".jpeg"}:
            raise HTTPException(404, "照片不存在")
        return FileResponse(f, media_type="image/jpeg")

    @app.get("/api/tunnels/{tid}/info")
    def tunnel_info(tid: int):
        return service.info(tid)

    @app.post("/api/tunnels/{tid}/photos/{pid}/mark_missing")
    def mark_missing(tid: int, pid: int):
        try:
            service.mark_missing_photo(tid, pid)
        except KeyError:
            raise HTTPException(404, "照片不存在")
        _invalidate_cache(workspace.root, tid)
        hub.broadcast(tid, {"type": "photo_updated", "photo_id": pid})
        return {"ok": True}

    @app.post("/api/tunnels/{tid}/photos/{pid}/restore")
    def restore_missing(tid: int, pid: int):
        try:
            service.restore_missing_photo(tid, pid)
        except KeyError:
            raise HTTPException(404, "照片不存在或未改判")
        hub.broadcast(tid, {"type": "photo_updated", "photo_id": pid})
        return {"ok": True}

    @app.post("/api/tunnels/{tid}/realign")
    def realign_dry_run(tid: int, body: RealignBody):
        return service.realign_preview(tid, body.tolerance_seconds)

    @app.post("/api/tunnels/{tid}/realign/apply")
    async def realign_apply(tid: int, body: RealignBody):
        result = service.realign_apply(tid, body.tolerance_seconds)
        _invalidate_cache(workspace.root, tid)
        hub.broadcast(tid, {"type": "realigned"})
        return result

    @app.post("/api/tunnels/{tid}/groups/{seq}/merge")
    async def merge_group(tid: int, seq: int, body: MergeBody):
        try:
            result = service.merge_group(tid, seq, body.direction, body.keep)
        except MergeConflict as e:
            raise HTTPException(409, detail={"message": str(e), "conflict_cameras": e.conflict_cameras})
        except KeyError:
            raise HTTPException(404, "群組不存在")
        hub.broadcast(tid, {"type": "merged", **result})
        return result

    @app.put("/api/tunnels/{tid}/cameras/{seq}")
    def update_camera(tid: int, seq: int, body: CameraUpdateBody):
        if body.name is None and body.rotation is None and body.grid_pos is None:
            raise HTTPException(400, "需提供 name、rotation 或 grid_pos")
        if body.rotation is not None and (
            body.rotation % 90 != 0 or not (0 <= body.rotation <= 270)
        ):
            raise HTTPException(400, "旋轉角度僅接受 0/90/180/270")
        try:
            if body.name is not None:
                service.set_camera_name(tid, seq, body.name)
            if body.rotation is not None:
                service.set_camera_rotation(tid, seq, body.rotation)
            if body.grid_pos is not None:
                service.set_camera_grid_pos(tid, seq, body.grid_pos)
        except KeyError:
            raise HTTPException(404, "相機不存在")
        except ValueError as e:
            raise HTTPException(400, str(e))
        _invalidate_cache(workspace.root, tid)
        hub.broadcast(tid, {"type": "camera_updated", "camera_seq": seq})
        return {"ok": True}

    @app.put("/api/tunnels/{tid}/layout")
    def set_layout(tid: int, body: LayoutBody):
        try:
            service.set_layout_cols(tid, body.cols)
        except ValueError as e:
            raise HTTPException(400, str(e))
        hub.broadcast(tid, {"type": "layout_updated"})
        return {"ok": True}

    @app.post("/api/fs/recent")
    def record_recent(body: FsRecentBody):
        target = Path(body.path).expanduser()
        if not target.is_dir():
            raise HTTPException(404, "資料夾不存在")
        workspace.add_recent_path(str(target))
        return {"ok": True}

    @app.put("/api/tunnels/{tid}/photos/{pid}/rotation")
    def set_photo_rotation(tid: int, pid: int, body: PhotoRotationBody):
        if body.angle % 90 != 0 or not (0 <= body.angle <= 270):
            raise HTTPException(400, "旋轉角度僅接受 0/90/180/270")
        try:
            service.set_photo_rotation(tid, pid, body.angle)
        except KeyError:
            raise HTTPException(404, "照片不存在")
        _invalidate_cache(workspace.root, tid, photo_id=pid)
        hub.broadcast(tid, {"type": "photo_updated", "photo_id": pid})
        return {"ok": True}

    @app.get("/api/tunnels/{tid}/camera_thumbs")
    def camera_thumbs(tid: int):
        return service.camera_thumbs(tid)

    @app.get("/api/tunnels/{tid}/photos/{photo_id}")
    def photo(tid: int, photo_id: int, w: int | None = None):
        try:
            info = service.photo_render_info(tid, photo_id)
        except KeyError:
            raise HTTPException(404, "照片不存在")
        path: Path = info["path"]
        extra: int = info["extra_rotation"]
        if not Path(path).exists():
            raise HTTPException(404, "照片檔案遺失（原檔可能被移動）")

        needs_transpose = _needs_exif_transpose(path)
        fast_path = w is None and extra == 0 and not needs_transpose
        if fast_path:
            return FileResponse(path, media_type="image/jpeg")

        suffix = "orig" if w is None else str(w)
        cache_dir = Path(workspace.root) / ".thumb_cache"
        cache = cache_dir / f"{tid}_{photo_id}_{suffix}_{extra}.jpg"
        if not cache.exists():
            img = Image.open(path)
            if needs_transpose:
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
            else:
                img.draft("RGB", (w * 2, w * 2)) if w else None
                img = img.convert("RGB")
            if extra:
                img = img.rotate(-extra, expand=True)
            if w is not None:
                ratio = w / img.width
                img = img.resize((w, max(1, round(img.height * ratio))), Image.BILINEAR)
                cache_dir.mkdir(parents=True, exist_ok=True)
                img.save(cache, "JPEG", quality=87)
            else:
                cache_dir.mkdir(parents=True, exist_ok=True)
                img.save(cache, "JPEG", quality=92)
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
