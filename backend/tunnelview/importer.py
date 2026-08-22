"""匯入流程編排：資料夾掃描 → EXIF 讀取 → 對齊 → 預覽／提交。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from .align import CameraSeries, PhotoStamp, align
from .db import Workspace, TunnelInfo
from .interp import compute_all

IMAGE_EXTS = {".jpg", ".jpeg"}


@dataclass(frozen=True)
class CameraInput:
    name: str
    folder: str
    rotation: int = 0


@dataclass(frozen=True)
class ImportRequest:
    name: str
    start_m: int
    end_m: int
    tolerance_seconds: float
    cameras: list[CameraInput]


@dataclass(frozen=True)
class CameraPreview:
    name: str
    photo_count: int
    offset_seconds: float


@dataclass(frozen=True)
class ImportPreview:
    group_count: int
    cameras: list[CameraPreview]
    missing_distribution: dict[int, int]  # 缺照台數 → 群組數
    flagged_count: int


@dataclass
class _ScannedPhoto:
    camera_seq: int
    path: Path
    t: datetime
    time_source: str  # 'exif' | 'mtime'
    flagged: bool
    width: int | None = None
    height: int | None = None


def read_photo_time(path: Path) -> tuple[datetime | None, str]:
    """讀 EXIF DateTimeOriginal；缺漏時回傳 (None, 'mtime') 由呼叫端退回。"""
    try:
        exif = Image.open(path)._getexif() or {}
        raw = exif.get(36868)
        if raw:
            return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S"), "exif"
    except Exception:
        pass
    return None, "mtime"


def read_display_dims(path: Path) -> tuple[int | None, int | None]:
    """EXIF orientation 套用後的顯示尺寸。

    僅讀檔頭 orientation 標籤並算術交換寬高——絕不解碼全圖
    （exif_transpose 對需轉正的照片會觸發完整解碼，數百張會拖垮匯入）。
    """
    try:
        with Image.open(path) as im:
            w, h = im.size
            orientation = int((im.getexif() or {}).get(274, 1))
            if orientation in (5, 6, 7, 8):
                w, h = h, w
            return w, h
    except Exception:
        return None, None


def compute_aspect_anomalies(conn) -> list[dict]:
    """各機位「套用機位旋轉後」的顯示比例多數派，少數派標記 aspect_anomaly=1。

    直接以 photos 表已存的 width/height 計算（匯入與重新對齊共用）。
    回傳異常清單供報告使用。
    """
    conn.execute("UPDATE photos SET aspect_anomaly = 0")
    anomalies: list[dict] = []
    cams = conn.execute("SELECT id, seq, name, rotation FROM cameras ORDER BY seq").fetchall()
    for cam in cams:
        rot = (cam["rotation"] or 0) % 180
        photos = conn.execute(
            "SELECT id, rel_path, width, height FROM photos "
            "WHERE camera_id = ? AND COALESCE(manual_missing, 0) = 0 "
            "AND width IS NOT NULL AND height IS NOT NULL",
            (cam["id"],),
        ).fetchall()
        ratios: dict[int, list] = {}
        for p in photos:
            w, h = (p["height"], p["width"]) if rot else (p["width"], p["height"])
            ratios.setdefault(round(w / h * 100), []).append(p)
        if not ratios:
            continue
        majority = max(ratios, key=lambda k: len(ratios[k]))
        for ratio_key, plist in ratios.items():
            if ratio_key == majority:
                continue
            for p in plist:
                conn.execute("UPDATE photos SET aspect_anomaly = 1 WHERE id = ?", (p["id"],))
                anomalies.append(
                    {"camera": cam["name"], "rel_path": p["rel_path"], "width": p["width"], "height": p["height"]}
                )
    return anomalies


class TunnelImporter:
    def __init__(self, workspace: Workspace):
        self.ws = workspace

    def scan(self, req: ImportRequest) -> list[_ScannedPhoto]:
        photos: list[_ScannedPhoto] = []
        for seq, cam in enumerate(req.cameras):
            folder = Path(cam.folder)
            if not folder.is_dir():
                raise FileNotFoundError(f"相機資料夾不存在：{cam.folder}")
            for p in sorted(folder.iterdir()):
                if p.suffix.lower() not in IMAGE_EXTS or not p.is_file():
                    continue
                t, source = read_photo_time(p)
                flagged = False
                if t is None:
                    t = datetime.fromtimestamp(os.path.getmtime(p))
                    flagged = True
                w, h = read_display_dims(p)
                photos.append(_ScannedPhoto(seq, p, t, source, flagged, width=w, height=h))
        return photos

    def preview(self, req: ImportRequest) -> ImportPreview:
        result, photos, series = self._align(req)
        cams = [
            CameraPreview(
                name=req.cameras[s.camera_index].name,
                photo_count=len(s.photos),
                offset_seconds=result.offsets_seconds[s.camera_index],
            )
            for s in series
        ]
        dist: dict[int, int] = {}
        for g in result.groups:
            dist[len(g.missing)] = dist.get(len(g.missing), 0) + 1
        flagged_n = sum(1 for p in photos if p.flagged)
        return ImportPreview(
            group_count=len(result.groups),
            cameras=cams,
            missing_distribution=dict(sorted(dist.items())),
            flagged_count=flagged_n,
        )

    def commit(self, req: ImportRequest) -> TunnelInfo:
        result, photos, series = self._align(req)

        info = self.ws.create_tunnel(
            name=req.name,
            start_m=req.start_m,
            end_m=req.end_m,
            cameras=[
                {"name": c.name, "root_path": c.folder, "rotation": c.rotation}
                for c in req.cameras
            ],
            tolerance_seconds=req.tolerance_seconds,
        )

        est = compute_all(
            group_count=len(result.groups), start_m=req.start_m, end_m=req.end_m, anchors={}
        )
        scanned_by_pid = {p.path.name: p for p in photos}

        conn = self.ws.open_tunnel(info.tunnel_id)
        try:
            with conn:
                for g in result.groups:
                    conn.execute(
                        "INSERT INTO photo_groups (seq, corrected_time, est_mileage_m, missing_count) VALUES (?, ?, ?, ?)",
                        (
                            g.seq,
                            g.corrected_time.isoformat(timespec="seconds"),
                            est[g.seq],
                            len(g.missing),
                        ),
                    )
                seq_to_group_id = {
                    row["seq"]: row["id"]
                    for row in conn.execute("SELECT id, seq FROM photo_groups").fetchall()
                }
                cam_rows = conn.execute("SELECT id, seq FROM cameras ORDER BY seq").fetchall()
                cam_id_by_seq = {r["seq"]: r["id"] for r in cam_rows}

                anomalies: list[dict] = []
                flagged_cams = {g.seq: g.flagged for g in result.groups}
                for s in series:
                    off = result.offsets_seconds[s.camera_index]
                    cam_dir = Path(req.cameras[s.camera_index].folder)
                    group_seq_of_pid = {
                        pid: g.seq for g in result.groups for cam_idx, pid in g.members.items() if cam_idx == s.camera_index
                    }
                    for stamp in s.photos:
                        sp = scanned_by_pid[stamp.photo_id]
                        gseq = group_seq_of_pid[stamp.photo_id]
                        residual_flagged = s.camera_index in flagged_cams[gseq]
                        corrected = stamp.t + timedelta(seconds=off)
                        conn.execute(
                            "INSERT INTO photos (camera_id, group_id, rel_path, exif_time, corrected_time, time_source, flagged, width, height) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                cam_id_by_seq[s.camera_index],
                                seq_to_group_id[gseq],
                                os.path.relpath(sp.path, cam_dir),
                                sp.t.isoformat(timespec="seconds"),
                                corrected.isoformat(timespec="seconds"),
                                sp.time_source,
                                1 if (sp.flagged or residual_flagged) else 0,
                                sp.width,
                                sp.height,
                            ),
                        )
                    conn.execute(
                        "UPDATE cameras SET dt_offset_sec = ?, photo_count = ? WHERE seq = ?",
                        (off, len(s.photos), s.camera_index),
                    )

                # 比例異常偵測（以已寫入的顯示尺寸計算，含 group_seq 供概覽標記）
                anomalies = compute_aspect_anomalies(conn)
                anomalies = [
                    {
                        **a,
                        "group_seq": (
                            conn.execute(
                                "SELECT g.seq AS seq FROM photos p "
                                "JOIN cameras c ON c.id = p.camera_id "
                                "LEFT JOIN photo_groups g ON g.id = p.group_id "
                                "WHERE c.name = ? AND p.rel_path = ? AND COALESCE(p.manual_missing,0)=0",
                                (a["camera"], a["rel_path"]),
                            ).fetchone()["seq"]
                        ),
                    }
                    for a in anomalies
                ]

                dist: dict[str, int] = {}
                for g in result.groups:
                    key = str(len(g.missing))
                    dist[key] = dist.get(key, 0) + 1
                report = {
                    "tolerance_seconds": req.tolerance_seconds,
                    "group_count": len(result.groups),
                    "missing_distribution": dist,
                    "flagged_count": sum(1 for p in photos if p.flagged),
                    "cameras": [
                        {
                            "name": req.cameras[s.camera_index].name,
                            "photo_count": len(s.photos),
                            "offset_seconds": result.offsets_seconds[s.camera_index],
                            "rotation": req.cameras[s.camera_index].rotation,
                        }
                        for s in series
                    ],
                    "aspect_anomalies": anomalies,
                    "imported_at": datetime.now().isoformat(timespec="seconds"),
                }
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('import_report', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (json.dumps(report, ensure_ascii=False),),
                )
        finally:
            conn.close()
        return info

    def _align(self, req: ImportRequest):
        photos = self.scan(req)
        if not photos:
            raise ValueError("所選資料夾內沒有任何 JPG")
        series = self._series(photos)
        result = align(series, tolerance_seconds=req.tolerance_seconds)
        return result, photos, series

    def _series(self, photos: list[_ScannedPhoto]) -> list[CameraSeries]:
        by_cam: dict[int, list[PhotoStamp]] = {}
        for p in photos:
            by_cam.setdefault(p.camera_seq, []).append(PhotoStamp(photo_id=p.path.name, t=p.t))
        return [CameraSeries(idx, lst) for idx, lst in sorted(by_cam.items())]
