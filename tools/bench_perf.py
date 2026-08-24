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
"""R9 效能基準：掃描快取命中倍率、縮圖冷/熱延遲、視窗查詢查詢數。

唯讀工具（唯一副作用為 .thumb_cache 寫入與 index.db 掃描快取更新）。

用法：
    uv run python tools/bench_perf.py                      # 自動偵測 ./八卦山西行 與 data/
    uv run python tools/bench_perf.py /mnt/nas/Cam1 ...    # 指定機位資料夾
選項：
    --sample N   每機位抽樣張數（0=全掃，預設 200）
    --thumb-n N  縮圖冷/熱實測張數（預設 30）
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from tunnelview.db import Workspace  # noqa: E402
from tunnelview.importer import (  # noqa: E402
    CameraInput,
    ImportRequest,
    TunnelImporter,
)
from tunnelview.service import TunnelService  # noqa: E402
from tunnelview import thumbs  # noqa: E402


def fmt_ms(s: float) -> str:
    return f"{s * 1000:.1f}ms"


def find_default_cameras(root: Path) -> list[Path]:
    base = root / "八卦山西行"
    if base.is_dir():
        return sorted([d for d in base.iterdir() if d.is_dir()])
    return []


def find_tunnel_db(ws_root: Path) -> Path | None:
    cands = sorted(ws_root.glob("tunnel_*.db"))
    return cands[0] if cands else None


def bench_scan_cache(req: ImportRequest, ws: Workspace, imp: TunnelImporter):
    print("\n[基準A] EXIF 掃描快取（同一批檔案連掃兩遍）")
    # 第一遍前先清快取，確保「冷」
    try:
        ws.scan_cache_clear()
    except Exception:
        pass
    t0 = time.perf_counter()
    r1 = imp.scan(req)
    cold = time.perf_counter() - t0

    t0 = time.perf_counter()
    r2 = imp.scan(req)
    warm = time.perf_counter() - t0

    n = len(r1)
    assert len(r2) == n and n > 0, f"兩遍掃描張數不一致或為零（{n}）"
    same = all(
        a.path == b.path and a.t == b.t and a.width == b.width and a.height == b.height and a.time_source == b.time_source
        for a, b in zip(r1, r2)
    )
    ratio = cold / warm if warm > 0 else float("inf")
    print(f"  張數：{n}｜輸出一致：{same}")
    print(f"  冷（填快取）：{cold:.2f}s（{cold / n * 1000:.1f} ms/張）")
    print(f"  熱（全命中）：{warm:.2f}s（{warm / n * 1000:.2f} ms/張）")
    print(f"  ▶ 加速比：{ratio:.1f}x")
    return ratio, same


def bench_thumb(paths: list[Path], tmp_ws: Path, n: int):
    print(f"\n[基準B] 縮圖冷生成 vs 快取命中（各 {min(n, len(paths))} 張，w=1600）")
    cache_dir = tmp_ws / ".thumb_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sample = paths[:n]
    cold_times, warm_times = [], []
    for i, p in enumerate(sample):
        cf = cache_dir / f"bench_{i}_1600_0_v0.jpg"
        cf.unlink(missing_ok=True)
        t0 = time.perf_counter()
        thumbs.get_or_make(cf, lambda p=p: thumbs.make_thumbnail(p, 1600))
        cold_times.append(time.perf_counter() - t0)
    for i in range(len(sample)):
        cf = cache_dir / f"bench_{i}_1600_0_v0.jpg"
        t0 = time.perf_counter()
        thumbs.get_or_make(cf, lambda: (_ for _ in ()).throw(AssertionError("不應重新生成")))
        warm_times.append(time.perf_counter() - t0)
    cold_med = statistics.median(cold_times)
    warm_med = statistics.median(warm_times)
    backend = "pyvips" if thumbs.HAVE_PYVIPS else "pillow"
    print(f"  後端：{backend}")
    print(f"  冷生成中位數：{fmt_ms(cold_med)}")
    print(f"  熱命中中位數：{fmt_ms(warm_med)}")
    print(f"  ▶ 命中/生成 比：{cold_med / max(warm_med, 1e-9):.0f}x")
    shutil.rmtree(tmp_ws, ignore_errors=True)


def bench_get_window(ws: Workspace, tid: int):
    print("\n[基準C] get_window 查詢數（75 群視窗）")
    svc = TunnelService(ws)
    meta = svc.meta(tid)
    total = meta["group_count"]
    around = min(37, max(0, total - 1))
    counts = []

    def make_conn(tunnel_id):
        import sqlite3

        conn = sqlite3.connect(str(next(ws.root.glob("tunnel_*.db"))))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        def trace(stmt):
            if stmt.lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE")):
                counts[-1] += 1

        conn.set_trace_callback(trace)
        return conn

    orig_open = ws.open_tunnel
    ws.open_tunnel = make_conn  # type: ignore[method-assign]
    try:
        for _ in range(3):
            counts.append(0)
            svc.get_window(tid, around=around, before=25, after=50)
    finally:
        ws.open_tunnel = orig_open  # type: ignore[method-assign]
    print(f"  群組總數：{total}｜每次呼叫 SQL 語句數：{counts}")
    print("  ▶ R9 後應為常數小值（JOIN 批次化；R8 前約 150+）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cameras", nargs="*", help="機位資料夾（省略時自動偵測 ./八卦山西行 子資料夾）")
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--thumb-n", type=int, default=30)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cam_folders = [Path(c) for c in args.cameras] or find_default_cameras(root)
    if not cam_folders:
        print("找不到機位資料夾：請傳入資料夾路徑或確認 ./八卦山西行 存在")
        return 1

    ws = Workspace(root / "data")
    ws.init()
    imp = TunnelImporter(ws)

    req = ImportRequest(
        name="bench",
        start_m=0,
        end_m=1000,
        tolerance_seconds=2.0,
        cameras=[CameraInput(name=f"C{i}", folder=str(c)) for i, c in enumerate(cam_folders)],
    )
    enum = imp.enumerate(req)
    totals = [c["valid_jpg"] for c in enum["cameras"]]
    print(f"=== R9 效能基準  機位 {len(cam_folders)}｜總張數 {sum(totals)} ===")

    # 抽樣僅影響縮圖基準；掃描基準掃全部頂層 JPG 以確保兩遍輸出可比
    ratio, same = bench_scan_cache(req, ws, imp)

    all_photos = []
    for c in cam_folders:
        all_photos.extend(sorted(c.glob("*.jpg")) + sorted(c.glob("*.JPG")))
    seen = set()
    uniq = []
    for p in all_photos:
        if p.resolve() not in seen:
            seen.add(p.resolve())
            uniq.append(p)
    if uniq:
        bench_thumb(uniq, root / "data/.thumb_bench_tmp", args.thumb_n)

    tdb = find_tunnel_db(root / "data")
    if tdb is not None:
        with ws._connect(ws.index_path) as conn:
            row = conn.execute("SELECT MIN(id) AS tid FROM tunnels").fetchone()
            tid = row["tid"] if row else None
        if tid is not None:
            bench_get_window(ws, tid)
        else:
            print("\n[基準C] 跳過：index.db 沒有任何隧道")
    else:
        print("\n[基準C] 跳過：data/ 下沒有隧道 db")

    ok = same and ratio >= 10
    print("\n=== 結論 ===")
    print(f"掃描快取加速比 {ratio:.1f}x（門檻 ≥10x）｜兩遍一致：{same} → {'PASS' if ok else 'CHECK'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
