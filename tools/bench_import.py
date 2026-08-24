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

#!/usr/bin/env python3
"""匯入管線效能實測：量測列舉 / EXIF 掃描 / 對齊各階段耗時並外推全量時間。

唯讀工具——不寫庫、不建立隧道、不修改照片。

用法：
    uv run python tools/bench_import.py /mnt/nas/Cam1 [/mnt/nas/Cam2 ...] \
        [--sample 300] [--runs 2] [--tolerance 2.0]

--sample N：每機位均勻抽樣 N 張實測，外推全量；0 = 全掃。
--runs R：連跑 R 次觀察 OS 讀取快取效應（第 2 次起通常明顯變快）。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from tunnelview.align import align  # noqa: E402
from tunnelview.importer import (  # noqa: E402
    IMAGE_EXTS,
    CameraInput,
    ImportRequest,
    TunnelImporter,
    read_exif_and_dims,
)


def list_jpgs(folder: Path) -> list[Path]:
    entries = []
    with os.scandir(folder) as it:
        for entry in it:
            try:
                if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS:
                    entries.append(Path(entry.path))
            except OSError:
                continue
    entries.sort(key=lambda p: p.name.lower())
    return entries


def stride_sample(paths: list[Path], n: int) -> list[Path]:
    """均勻跨整個目錄抽樣，避免只取開頭造成磁碟/快取偏誤。"""
    if n <= 0 or len(paths) <= n:
        return paths
    step = len(paths) / n
    return [paths[min(len(paths) - 1, int(i * step))] for i in range(n)]


def bench_scan(paths: list[Path]) -> tuple[float, int]:
    t0 = time.perf_counter()
    ok = 0
    for i, p in enumerate(paths, 1):
        t, source, w, h = read_exif_and_dims(p)
        if t is not None or w is not None:
            ok += 1
        if i % 200 == 0:
            rate = (time.perf_counter() - t0) / i * 1000
            print(f"    ... {i}/{len(paths)} 張（{rate:.0f} ms/張）", flush=True)
    return time.perf_counter() - t0, ok


def fmt_sec(s: float) -> str:
    if s < 90:
        return f"{s:.1f}s"
    return f"{int(s // 60)}m{int(s % 60):02d}s"


class _FakeWorkspace:
    root = Path(".")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cameras", nargs="+", help="機位資料夾路徑（server 本機視角）")
    ap.add_argument("--sample", type=int, default=300, help="每機位抽樣張數，0=全掃")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--tolerance", type=float, default=2.0)
    args = ap.parse_args()

    req = ImportRequest(
        name="bench",
        start_m=0,
        end_m=1000,
        tolerance_seconds=args.tolerance,
        cameras=[CameraInput(name=f"Cam{i}", folder=c) for i, c in enumerate(args.cameras)],
    )
    importer = TunnelImporter(_FakeWorkspace())

    print(f"=== 匯入效能實測  {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    print(f"機位數：{len(args.cameras)}｜抽樣：{'全掃' if args.sample == 0 else f'{args.sample}/機位'}")

    t0 = time.perf_counter()
    enum_info = importer.enumerate(req)
    t_enum = time.perf_counter() - t0
    totals = {c["folder"]: c["valid_jpg"] for c in enum_info["cameras"]}
    grand_total = sum(totals.values())
    print(f"\n[階段A] 列舉（不開檔）：{fmt_sec(t_enum)}")
    for c in enum_info["cameras"]:
        print(f"  {Path(c['folder']).name}: {c['valid_jpg']} 張 JPG（忽略 {c['ignored_non_jpg']}）")

    all_paths = [stride_sample(list_jpgs(Path(c.folder)), args.sample) for c in req.cameras]
    sampled_total = sum(len(p) for p in all_paths)

    results = []
    for run in range(1, args.runs + 1):
        per_cam = []
        for cam, paths in zip(req.cameras, all_paths):
            dt, ok = bench_scan(paths)
            per_cam.append((dt, ok, len(paths)))
        total_dt = sum(d for d, _, _ in per_cam)
        results.append(total_dt)
        tag = "冷" if run == 1 else "溫"
        print(f"\n[階段B] EXIF 掃描 第{run}次（{tag}）：{fmt_sec(total_dt)}")
        for cam, (dt, ok, n) in zip(req.cameras, per_cam):
            ms = dt / n * 1000 if n else 0
            full_n = totals[cam.folder]
            eta = dt / n * full_n if n else 0
            print(
                f"  {Path(cam.folder).name}: {n} 張實測 {fmt_sec(dt)}"
                f"（{ms:.0f} ms/張）→ 全量 {full_n} 張外推 {fmt_sec(eta)}"
            )
        # 外推總覽
        if args.sample:
            scale = grand_total / sampled_total
            print(f"  ▶ 四機位全量 {grand_total} 張單遍掃描外推：{fmt_sec(total_dt * scale)}")

    # 階段C：對齊（純運算，直接用抽樣讀取結果，不重掃資料夾）
    from tunnelview.importer import _ScannedPhoto
    from tunnelview.align import CameraSeries, PhotoStamp

    photos: list[_ScannedPhoto] = []
    by_cam: dict[int, list[PhotoStamp]] = {}
    for seq, (cam, paths) in enumerate(zip(req.cameras, all_paths)):
        stamps = []
        for p in paths:
            t, source, w, h = read_exif_and_dims(p)
            if t is None:
                t = datetime.fromtimestamp(p.stat().st_mtime)
                source = "mtime"
            photos.append(_ScannedPhoto(seq, p, t, source, source == "mtime", w, h))
            stamps.append(PhotoStamp(photo_id=f"{seq}:{p.name}", t=t))
        if stamps:
            by_cam[seq] = stamps
    series = [CameraSeries(idx, lst) for idx, lst in sorted(by_cam.items())]
    t0 = time.perf_counter()
    result = align(series, tolerance_seconds=req.tolerance_seconds)
    t_align = time.perf_counter() - t0
    flagged_n = sum(1 for p in photos if p.flagged)
    print(f"\n[階段C] 對齊運算（{len(series)} 機位 / {len(photos)} 張）：{t_align*1000:.0f}ms → {len(result.groups)} 群")
    print(f"  ⚠ mtime 退回（無 EXIF 時間）張數：{flagged_n} / {len(photos)}")

    med = statistics.median(results)
    if args.sample:
        scale = grand_total / sampled_total
        est_preview = t_enum + med * scale
        print("\n=== 全量預估（目前單執行緒架構）===")
        print(f"預覽一遍：{fmt_sec(est_preview)}")
        print(f"預覽+建立（現況重掃兩遍）：{fmt_sec(est_preview * 2)}")
        print(f"若 commit 復用掃描結果：{fmt_sec(est_preview)}")
        print(f"若再加 12 執行緒併發（÷8 樂觀估）：{fmt_sec(est_preview / 8)}")
    else:
        print(f"\n=== 實測（全掃）=== 預覽一遍：{fmt_sec(t_enum + med)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
