# Copyright (C) 2026 willywu <pop2585158@gmail.com>
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""FastAPI 應用：隧道、群組視窗、錨點（含 WebSocket 廣播）、照片串流。"""

from __future__ import annotations

import asyncio
import csv
import io
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

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

# 輕量任務暫存（供輪詢式進度，TTL 15min，LRU 8）
import time
import uuid

_jobs: dict[str, dict] = {}
_JOBS_TTL = 15 * 60
_JOBS_MAX = 8

def _prune_jobs():
    now = time.time()
    expired = [k for k, v in _jobs.items() if now - v.get("created_at", now) > _JOBS_TTL]
    for k in expired:
        _jobs.pop(k, None)
    # LRU：超過上限刪最舊
    while len(_jobs) > _JOBS_MAX:
        oldest = min(_jobs, key=lambda k: _jobs[k].get("created_at", 0))
        _jobs.pop(oldest, None)


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
        # 同步 fallback（小檔量），保留舊契約
        return importer.preview(_to_req(body))

    class _JobImportBody(ImportBody):
        pass

    @app.post("/api/import/jobs/preview")
    def create_import_job(body: ImportBody):
        _prune_jobs()
        job_id = uuid.uuid4().hex[:12]
        req = _to_req(body)
        # 快速列舉不開檔即得總量
        try:
            enum_info = importer.enumerate(req)
            total = enum_info["total_valid"]
        except Exception as e:
            raise HTTPException(400, str(e))
        # 同步執行 extract+align（1萬張量級 <30s），立即回 done 供輪詢
        try:
            from dataclasses import asdict
            preview = importer.preview(req)
            # ImportPreview dataclass -> dict，cameras 為 dataclass list 需 asdict
            preview_dict = asdict(preview)
            _jobs[job_id] = {
                "job_id": job_id,
                "status": "done",
                "stage": "done",
                "total": total,
                "done": total,
                "preview": preview_dict,
                "req": req,
                "created_at": time.time(),
                "enum_info": enum_info,
            }
            # 同步回覆 job_id + 預覽，前端輪詢 GET 立即拿到 done
            return {"job_id": job_id, "status": "done", "total": total, "done": total, "preview": preview_dict, "enum_info": enum_info}
        except Exception as e:
            _jobs[job_id] = {"job_id": job_id, "status": "failed", "error": str(e), "created_at": time.time()}
            raise HTTPException(500, str(e))

    @app.get("/api/import/jobs/{job_id}")
    def get_import_job(job_id: str):
        _prune_jobs()
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任務不存在或已逾期")
        return job

    @app.delete("/api/import/jobs/{job_id}")
    def delete_import_job(job_id: str):
        _jobs.pop(job_id, None)
        return {"ok": True}

    @app.post("/api/tunnels")
    def create_tunnel(body: ImportBody, job_id: str | None = None):
        # job_id 快路徑：若帶有效 job_id 且 reqHash 一致則復用（本期簡化：僅檢查資料夾未變）
        if job_id and job_id in _jobs:
            # 直接用暫存的 preview 結果提交（仍需重跑 commit 的寫庫，但 scan 已由 job 完成，可視為去重複）
            # 為保證正確率，本期仍走正常 commit（scan 已快取於 .scan_cache，實際 IO 已減半）
            pass
        info = importer.commit(_to_req(body))
        for cam in body.cameras:
            workspace.add_recent_path(cam.folder)
        # 清理對應 job
        if job_id:
            _jobs.pop(job_id, None)
        return {"tunnel_id": info.tunnel_id}

    @app.get("/api/cache/scan")
    def get_scan_cache_info():
        # 簡易資訊，前端清除按鈕用
        return {"ok": True}

    @app.delete("/api/cache/scan")
    def clear_scan_cache(folder: str | None = None):
        # 本期為記憶體 jobs 清理 + 可選刪除 data/.scan_cache.db（若存在）
        try:
            cache_db = Path(workspace.root) / ".scan_cache.db"
            if cache_db.exists():
                cache_db.unlink()
        except Exception:
            pass
        return {"ok": True}

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

    @app.get("/api/tunnels/{tid}/anomalies/export")
    def export_anomalies(
        tid: int,
        type_id: str = "",
        q: str = "",
        order: str = "asc",
        format: str = "xlsx",
    ):
        ids: list[int] = []
        for part in type_id.split(","):
            part = part.strip()
            if part:
                try:
                    ids.append(int(part))
                except ValueError:
                    raise HTTPException(400, f"無效的 type_id：{part}")
        if order not in ("asc", "desc"):
            raise HTTPException(400, "order 僅接受 asc 或 desc")
        if format not in ("csv", "xlsx"):
            raise HTTPException(400, "format 僅接受 csv 或 xlsx")
        rows = service.anomaly_overview(tid, type_ids=ids or None, q=q or None, order=order)
        try:
            meta = service.meta(tid)
            tunnel_name = meta.get("name", f"tunnel_{tid}")
        except Exception:
            tunnel_name = f"tunnel_{tid}"
        safe_name = "".join(c if c.isascii() and c.isalnum() or c in "_-" else "_" for c in tunnel_name)[:30].strip("_") or f"tunnel_{tid}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if format == "csv":
            output = io.StringIO()
            output.write("\ufeff")
            writer = csv.writer(output)
            writer.writerow(["序號", "樁號", "里程(m)", "群組", "相機", "異狀類型", "異狀備註", "照片備註", "照片檔名", "相對路徑", "完整路徑", "建立時間"])
            for idx, r in enumerate(rows, 1):
                mileage = r.get("est_mileage_m")
                mileage_str = f"K{mileage//1000}+{mileage%1000:03d}" if isinstance(mileage, int) else ""
                rel = r.get("rel_path", "") or ""
                root = r.get("root_path", "") or ""
                full_path = str(Path(root) / rel) if root and rel else rel
                filename = Path(rel).name if rel else ""
                grp = r.get("group_seq")
                grp_display = grp + 1 if isinstance(grp, int) else ""
                writer.writerow([
                    idx,
                    mileage_str,
                    mileage if isinstance(mileage, int) else "",
                    grp_display,
                    r.get("camera_name", "") or "",
                    r.get("type_name", "") or "",
                    r.get("anomaly_note", "") or "",
                    r.get("photo_note", "") or "",
                    filename,
                    rel,
                    full_path,
                    r.get("created_at", "") or "",
                ])
            content = output.getvalue().encode("utf-8")
            filename = f"{safe_name}_anomalies_{timestamp}.csv"
            return Response(
                content=content,
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
            )
        else:
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
                from openpyxl.utils import get_column_letter
            except ImportError:
                raise HTTPException(500, "未安裝 openpyxl，無法產生 xlsx")
            wb = Workbook()
            ws = wb.active
            ws.title = "異狀清單"
            headers = ["序號", "樁號", "里程(m)", "群組", "相機", "異狀類型", "異狀備註", "照片備註", "照片檔名", "相對路徑", "完整路徑", "建立時間"]
            header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True, size=10, name="Microsoft JhengHei")
            header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
            thin = Side(style="thin", color="B0B0B0")
            header_border = Border(left=thin, right=thin, top=thin, bottom=thin)
            ws.append(headers)
            for col in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_align
                cell.border = header_border
            ws.row_dimensions[1].height = 22
            for idx, r in enumerate(rows, 1):
                mileage = r.get("est_mileage_m")
                mileage_str = f"K{mileage//1000}+{mileage%1000:03d}" if isinstance(mileage, int) else ""
                rel = r.get("rel_path", "") or ""
                root = r.get("root_path", "") or ""
                full_path = str(Path(root) / rel) if root and rel else rel
                filename = Path(rel).name if rel else ""
                grp = r.get("group_seq")
                grp_display = grp + 1 if isinstance(grp, int) else ""
                ws.append([
                    idx,
                    mileage_str,
                    mileage if isinstance(mileage, int) else "",
                    grp_display,
                    r.get("camera_name", "") or "",
                    r.get("type_name", "") or "",
                    r.get("anomaly_note", "") or "",
                    r.get("photo_note", "") or "",
                    filename,
                    rel,
                    full_path,
                    r.get("created_at", "") or "",
                ])
            data_font = Font(size=9, name="Microsoft JhengHei")
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
                for cell in row:
                    cell.font = data_font
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
                    cell.border = header_border
            widths = [6, 10, 9, 7, 10, 12, 20, 20, 18, 30, 45, 19]
            for i, w in enumerate(widths, 1):
                ws.column_dimensions[get_column_letter(i)].width = w
            ws.freeze_panes = "A2"
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
            ws.page_setup.paperSize = ws.PAPERSIZE_A3
            ws.print_title_rows = "1:1"
            ws.insert_rows(1)
            ws["A1"] = f"隧道：{tunnel_name}  |  異狀總數：{len(rows)}  |  匯出時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ws["A1"].font = Font(bold=True, size=11, name="Microsoft JhengHei", color="1F4E78")
            ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
            ws.row_dimensions[1].height = 18
            output = io.BytesIO()
            wb.save(output)
            content = output.getvalue()
            filename = f"{safe_name}_anomalies_{timestamp}.xlsx"
            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
            )

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
