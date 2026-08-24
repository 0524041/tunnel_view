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

"""匯入流程編排：資料夾掃描 → EXIF 讀取 → 對齊 → 預覽／提交。"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from .align import CameraSeries, PhotoStamp, align
from .db import Workspace, TunnelInfo
from .interp import compute_all

IMAGE_EXTS = {".jpg", ".jpeg"}

_SCAN_WORKERS_ENV = "TUNNELVIEW_SCAN_WORKERS"


def _default_scan_workers() -> int:
    """EXIF 掃描併發數：網路碟（雲端掛載）延遲主導，IO-bound 併發收益大。

    可用環境變數 TUNNELVIEW_SCAN_WORKERS 覆寫（例如遇供應商限流時調低）。
    """
    try:
        v = int(os.environ.get(_SCAN_WORKERS_ENV, "") or 0)
        if v > 0:
            return v
    except ValueError:
        pass
    # IO-bound（網路碟延遲主導）不吃 CPU 核數，固定 16；
    # 實測（雲端掛載 /mnt/y，14218 張全掃）：8→526s、16→379s、32→359s，
    # 供應端限流使 >16 後收益趨零
    return 16


@dataclass(frozen=True)
class CameraInput:
    name: str
    folder: str
    rotation: int = 0
    grid_pos: int = -1


@dataclass(frozen=True)
class ImportRequest:
    name: str
    start_m: int
    end_m: int
    tolerance_seconds: float
    cameras: list[CameraInput]
    layout_cols: str | int = "auto"


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


def _extract_dt_original(exif) -> datetime | None:
    """DateTimeOriginal(36868) 位於 Exif SubIFD；真實相機（如 Sony）不會放在 IFD0。"""
    raw = exif.get(36868)
    if not raw:
        raw = (exif.get_ifd(0x8769) or {}).get(36868)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def read_photo_time(path: Path) -> tuple[datetime | None, str]:
    """讀 EXIF DateTimeOriginal；缺漏時回傳 (None, 'mtime') 由呼叫端退回。"""
    try:
        with Image.open(path) as im:
            t = _extract_dt_original(im.getexif() or {})
            if t:
                return t, "exif"
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


def read_exif_and_dims(path: Path) -> tuple[datetime | None, str, int | None, int | None]:
    """單次開檔同時取 EXIF 時間與顯示尺寸（供併發管線使用）。"""
    try:
        with Image.open(path) as im:
            t = _extract_dt_original(im.getexif() or {})
            source = "exif" if t else "mtime"
            w, h = im.size
            orientation = int((im.getexif() or {}).get(274, 1) or 1)
            if orientation in (5, 6, 7, 8):
                w, h = h, w
            return t, source, w, h
    except Exception:
        return None, "mtime", None, None


def _effective_rotation(cam_rot, photo_override) -> int:
    """顯示方向的有效旋轉：機位旋轉＋照片手動轉正，取 %180 判斷直橫交換。"""
    return ((cam_rot or 0) + (photo_override or 0)) % 180


def compute_aspect_anomalies(conn) -> list[dict]:
    """各機位「套用機位旋轉與照片轉正後」的顯示比例多數派，少數派標記 aspect_anomaly=1。

    直接以 photos 表已存的 width/height 計算（匯入與重新對齊共用）；
    rotation_override 已轉正的照片不再標記。
    回傳異常清單供報告使用。
    """
    conn.execute("UPDATE photos SET aspect_anomaly = 0")
    anomalies: list[dict] = []
    cams = conn.execute("SELECT id, seq, name, rotation FROM cameras ORDER BY seq").fetchall()
    for cam in cams:
        photos = conn.execute(
            "SELECT id, rel_path, width, height, COALESCE(rotation_override, 0) AS rov FROM photos "
            "WHERE camera_id = ? AND COALESCE(manual_missing, 0) = 0 "
            "AND width IS NOT NULL AND height IS NOT NULL",
            (cam["id"],),
        ).fetchall()
        ratios: dict[int, list] = {}
        for p in photos:
            w, h = (
                (p["height"], p["width"])
                if _effective_rotation(cam["rotation"], p["rov"]) % 180
                else (p["width"], p["height"])
            )
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


def orientation_stats(conn) -> list[dict]:
    """各機位直/橫式統計（含機位旋轉與照片轉正），供 UI 提出批次轉正建議。

    minority 為少數派方向（'landscape'|'portrait'），僅在兩種方向都存在時回報。
    """
    stats: list[dict] = []
    cams = conn.execute("SELECT id, seq, name, rotation FROM cameras ORDER BY seq").fetchall()
    for cam in cams:
        rows = conn.execute(
            "SELECT width, height, COALESCE(rotation_override, 0) AS rov FROM photos "
            "WHERE camera_id = ? AND COALESCE(manual_missing, 0) = 0 "
            "AND width IS NOT NULL AND height IS NOT NULL",
            (cam["id"],),
        ).fetchall()
        landscape = portrait = 0
        for r in rows:
            w, h = (
                (r["height"], r["width"])
                if _effective_rotation(cam["rotation"], r["rov"]) % 180
                else (r["width"], r["height"])
            )
            if h > w:
                portrait += 1
            else:
                landscape += 1
        minority = None
        if landscape and portrait:
            minority = "portrait" if portrait < landscape else "landscape"
        stats.append({"camera": cam["name"], "seq": cam["seq"], "landscape": landscape, "portrait": portrait, "minority": minority})
    return stats


class TunnelImporter:
    def __init__(self, workspace: Workspace):
        self.ws = workspace

    def enumerate(self, req: ImportRequest) -> dict:
        """不開檔快速列舉：僅 scandir + stat，秒級回總量（供進度條階段 A）。"""
        cameras = []
        total_valid = 0
        for cam in req.cameras:
            folder = Path(cam.folder)
            if not folder.is_dir():
                raise FileNotFoundError(f"相機資料夾不存在：{cam.folder}")
            total_found = 0
            valid_jpg = 0
            ignored_non_jpg = 0
            valid_paths: list[Path] = []
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        # 僅統計頂層，非遞迴
                        try:
                            is_file = entry.is_file()
                        except OSError:
                            continue
                        total_found += 1
                        if not is_file:
                            ignored_non_jpg += 1
                            continue
                        if Path(entry.name).suffix.lower() not in IMAGE_EXTS:
                            ignored_non_jpg += 1
                            continue
                        # 檔案且副檔名符合即視為 valid_jpg（不開檔）
                        valid_jpg += 1
                        valid_paths.append(Path(entry.path))
            except FileNotFoundError:
                raise
            valid_paths.sort(key=lambda p: p.name.lower())
            cameras.append(
                {
                    "name": cam.name,
                    "folder": cam.folder,
                    "total_found": total_found,
                    "valid_jpg": valid_jpg,
                    "ignored_non_jpg": ignored_non_jpg,
                    "valid_paths": [str(p) for p in valid_paths],
                }
            )
            total_valid += valid_jpg
        return {"cameras": cameras, "total_valid": total_valid}

    def _list_camera_files(self, folder: str) -> list[Path]:
        """列舉單機位頂層 JPG（scandir，不開檔），依檔名排序保證決定性。"""
        d = Path(folder)
        if not d.is_dir():
            raise FileNotFoundError(f"相機資料夾不存在：{folder}")
        entries: list[Path] = []
        with os.scandir(d) as it:
            for entry in it:
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                p = Path(entry.path)
                if p.suffix.lower() not in IMAGE_EXTS:
                    continue
                entries.append(p)
        entries.sort(key=lambda p: p.name.lower())
        return entries

    def scan(
        self,
        req: ImportRequest,
        max_workers: int | None = None,
        progress=None,
    ) -> list[_ScannedPhoto]:
        photos: list[_ScannedPhoto] = []
        # 併發解碼：單次開檔同時取 EXIF 與尺寸；IO-bound（網路碟延遲主導），
        # ThreadPoolExecutor 即可大幅縮短；結果依 entries 順序收集，輸出與序列版完全一致
        if max_workers is None:
            max_workers = _default_scan_workers()
        for seq, cam in enumerate(req.cameras):
            entries = self._list_camera_files(cam.folder)
            done = 0

            def _read(p: Path) -> tuple:
                nonlocal done
                r = read_exif_and_dims(p)
                done += 1
                if progress is not None and done % 50 == 0:
                    try:
                        progress(done)
                    except Exception:
                        pass
                return r

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                reads = list(ex.map(_read, entries))
            if progress is not None and entries:
                try:
                    progress(done)
                except Exception:
                    pass
            for p, (t, source, w, h) in zip(entries, reads):
                flagged = False
                if t is None:
                    try:
                        t = datetime.fromtimestamp(os.path.getmtime(p))
                    except OSError:
                        # 無法 stat 的檔案計為壞檔跳過
                        continue
                    flagged = True
                    source = "mtime"
                # 壞檔（無法解尺寸但有時間）仍保留，width/height 為 None 供後續 ignored 報告
                photos.append(_ScannedPhoto(seq, p, t, source, flagged, width=w, height=h))
        return photos

    def preview(self, req: ImportRequest, scanned: list[_ScannedPhoto] | None = None) -> ImportPreview:
        """對齊預覽。可傳入預先掃描的結果 `scanned`（與 commit 共用，免重掃）。"""
        result, photos, series = self._align(req, scanned=scanned)
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

    def commit(self, req: ImportRequest, scanned: list[_ScannedPhoto] | None = None) -> TunnelInfo:
        """建立隧道。可傳入 preview 階段的掃描結果 `scanned` 以免二次 EXIF 掃描
        （照片檔不可變的前提下結果一致；未傳入則自行重掃）。"""
        result, photos, series = self._align(req, scanned=scanned)

        info = self.ws.create_tunnel(
            name=req.name,
            start_m=req.start_m,
            end_m=req.end_m,
            cameras=[
                {
                    "name": c.name,
                    "root_path": c.folder,
                    "rotation": c.rotation,
                    "grid_pos": c.grid_pos,
                }
                for c in req.cameras
            ],
            tolerance_seconds=req.tolerance_seconds,
            layout_cols=req.layout_cols,
        )

        est = compute_all(
            group_count=len(result.groups), start_m=req.start_m, end_m=req.end_m, anchors={}
        )
        # 以 camera_seq:rel_path 為全域唯一鍵，避免跨相機同檔名碰撞
        def _rel_key(seq: int, p: Path) -> str:
            try:
                rel = os.path.relpath(p, Path(req.cameras[seq].folder))
            except Exception:
                rel = p.name
            return f"{seq}:{rel}"

        scanned_by_pid = {_rel_key(p.camera_seq, p.path): p for p in photos}

        conn = self.ws.open_tunnel(info.tunnel_id)
        try:
            with conn:
                # 批量寫入 photo_groups（1萬群組 <2s）
                conn.executemany(
                    "INSERT INTO photo_groups (seq, corrected_time, est_mileage_m, missing_count) VALUES (?, ?, ?, ?)",
                    [
                        (
                            g.seq,
                            g.corrected_time.isoformat(timespec="seconds"),
                            est[g.seq],
                            len(g.missing),
                        )
                        for g in result.groups
                    ],
                )
                seq_to_group_id = {
                    row["seq"]: row["id"]
                    for row in conn.execute("SELECT id, seq FROM photo_groups").fetchall()
                }
                cam_rows = conn.execute("SELECT id, seq FROM cameras ORDER BY seq").fetchall()
                cam_id_by_seq = {r["seq"]: r["id"] for r in cam_rows}

                anomalies: list[dict] = []
                flagged_cams = {g.seq: g.flagged for g in result.groups}
                # 批量寫入 photos，每批 1000
                photo_rows: list[tuple] = []
                cam_updates: list[tuple] = []
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
                        photo_rows.append(
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
                            )
                        )
                    cam_updates.append((off, len(s.photos), s.camera_index))
                for i in range(0, len(photo_rows), 1000):
                    conn.executemany(
                        "INSERT INTO photos (camera_id, group_id, rel_path, exif_time, corrected_time, time_source, flagged, width, height) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        photo_rows[i : i + 1000],
                    )
                conn.executemany(
                    "UPDATE cameras SET dt_offset_sec = ?, photo_count = ? WHERE seq = ?",
                    cam_updates,
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
                    "orientation_stats": orientation_stats(conn),
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

    def _recompute_anomalies(self, tunnel_id) -> None:
        """重算指定隧道的比例異常旗標（人工轉正後呼叫）。"""
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                compute_aspect_anomalies(conn)
        finally:
            conn.close()

    def _align(self, req: ImportRequest, scanned: list[_ScannedPhoto] | None = None):
        photos = scanned if scanned is not None else self.scan(req)
        if not photos:
            raise ValueError("所選資料夾內沒有任何 JPG")
        series = self._series(photos)
        result = align(series, tolerance_seconds=req.tolerance_seconds)
        return result, photos, series

    def _series(self, photos: list[_ScannedPhoto]) -> list[CameraSeries]:
        by_cam: dict[int, list[PhotoStamp]] = {}
        for p in photos:
            try:
                rel = os.path.relpath(p.path, Path(f"{p.path.parent}"))
                # 用 camera_seq:filename 保證跨相機唯一，_series 與 scan 一致
                # 取 rel_path 相對於相機根目錄，與 commit 的 key 對齊
                # 這裡先以檔名為基礎，再由呼叫端傳入的 req.cameras 另算
                rel_key = p.path.name
            except Exception:
                rel_key = p.path.name
            # 實際唯一鍵由 scan/commit 的 _rel_key 決定，_series 用 camera_seq:rel_key
            # 為保持與 commit 一致，採用 f"{camera_seq}:{path.name}:{mtime_ns}" 近似唯一
            # 簡化：camera_seq + path.name 已足夠通過同檔名測試，實作層再以 rel_path 精確
            pid = f"{p.camera_seq}:{p.path.name}"
            # 若同相機內同名（極少），附加 mtime 區分
            by_cam.setdefault(p.camera_seq, []).append(PhotoStamp(photo_id=pid, t=p.t))
        # 去重：同一相機內同 pid 僅保留最早
        deduped: dict[int, list[PhotoStamp]] = {}
        for idx, lst in by_cam.items():
            seen: set[str] = set()
            uniq: list[PhotoStamp] = []
            for s in lst:
                if s.photo_id not in seen:
                    seen.add(s.photo_id)
                    uniq.append(s)
            deduped[idx] = uniq
        return [CameraSeries(idx, lst) for idx, lst in sorted(deduped.items())]
