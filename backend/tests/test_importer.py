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

"""匯入服務行為契約：預覽不寫庫、提交落库、mtime 退回標記。"""

import pytest
from PIL import Image

from tunnelview.db import Workspace
from tunnelview.importer import CameraInput, ImportRequest, TunnelImporter


def make_jpg(path, dt_original=None):
    """產生測試用小 JPG；dt_original 給定時寫入 EXIF DateTimeOriginal。"""
    img = Image.new("RGB", (8, 6), color=(30, 30, 30))
    if dt_original is not None:
        exif = Image.Exif()
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def cam_dirs(tmp_path):
    """兩台相機、三個事件；cam1 缺第一發且時鐘快 100 秒。"""
    from datetime import datetime, timedelta

    base = datetime(2026, 5, 28, 20, 49, 0)
    d0 = tmp_path / "cam0"
    d1 = tmp_path / "cam1"
    d0.mkdir()
    d1.mkdir()
    for i, s in enumerate([0, 12, 25]):
        make_jpg(d0 / f"P{i:04d}.JPG", base + timedelta(seconds=s))
    # cam1 對應事件 1、2（漏事件 0），時間戳 +100 秒
    for i, s in enumerate([112, 125]):
        make_jpg(d1 / f"Q{i:04d}.JPG", base + timedelta(seconds=s))
    return d0, d1


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


def _request(cam_dirs, tmp_path):
    d0, d1 = cam_dirs
    return ImportRequest(
        name="測試隧道",
        start_m=23000,
        end_m=24200,
        tolerance_seconds=2.0,
        cameras=[
            CameraInput(name="左壁", folder=str(d0)),
            CameraInput(name="右壁", folder=str(d1)),
        ],
    )


class TestPreview:
    def test_preview_returns_stats_without_writing(self, ws, cam_dirs):
        req = _request(cam_dirs, None)
        preview = TunnelImporter(ws).preview(req)

        assert preview.group_count == 3
        assert len(preview.cameras) == 2
        assert preview.cameras[0].photo_count == 3
        assert preview.cameras[1].photo_count == 2
        assert preview.cameras[1].offset_seconds == pytest.approx(-100.0, abs=2.0)
        # 缺照分佈：兩群完整、一群缺 1 台
        assert preview.missing_distribution == {0: 2, 1: 1}
        assert ws.list_tunnels() == []  # 未寫入索引


class TestCommit:
    def test_commit_creates_tunnel_and_persists_groups(self, ws, cam_dirs):
        req = _request(cam_dirs, None)
        importer = TunnelImporter(ws)
        info = importer.commit(req)

        tunnels = ws.list_tunnels()
        assert len(tunnels) == 1
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            groups = conn.execute("SELECT seq, est_mileage_m, missing_count FROM photo_groups ORDER BY seq").fetchall()
            assert len(groups) == 3
            assert groups[0]["missing_count"] == 1
            assert groups[1]["missing_count"] == 0
            # 初始等分：起 23000 迄 24200，三群 → 中間群組 23600
            assert groups[1]["est_mileage_m"] == 23600
            n_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            assert n_photos == 5
        finally:
            conn.close()

    def test_mtime_fallback_flagged_when_exif_missing(self, ws, cam_dirs):
        d0, d1 = cam_dirs
        make_jpg(d0 / "NOEXIF.JPG")  # 無 EXIF
        req = ImportRequest(
            name="t",
            start_m=23000,
            end_m=24200,
            tolerance_seconds=2.0,
            cameras=[CameraInput(name="A", folder=str(d0)), CameraInput(name="B", folder=str(d1))],
        )
        info = TunnelImporter(ws).commit(req)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            row = conn.execute(
                "SELECT time_source, flagged FROM photos WHERE rel_path LIKE '%NOEXIF%'"
            ).fetchone()
            assert row["time_source"] == "mtime"
            assert row["flagged"] == 1
        finally:
            conn.close()


class TestScannedReuse:
    """commit 復用 preview 掃描結果：結果與自行重掃完全一致，免二次 EXIF IO。"""

    def test_commit_with_scanned_matches_fresh_commit(self, ws, cam_dirs):
        req = _request(cam_dirs, None)
        importer = TunnelImporter(ws)

        scanned = importer.scan(req)
        preview = importer.preview(req, scanned=scanned)
        assert preview.group_count == 3

        info = importer.commit(req, scanned=scanned)
        tunnels = ws.list_tunnels()
        assert len(tunnels) == 1
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            n_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            assert n_photos == 5
            rows = conn.execute(
                "SELECT rel_path, exif_time, time_source FROM photos ORDER BY id"
            ).fetchall()
            assert all(r["time_source"] == "exif" for r in rows)
            assert len({r["rel_path"] for r in rows}) == 5
        finally:
            conn.close()

    def test_scan_output_deterministic_under_concurrency(self, ws, cam_dirs):
        req = _request(cam_dirs, None)
        importer = TunnelImporter(ws)
        a = [(p.camera_seq, p.path.name, p.t) for p in importer.scan(req)]
        b = [(p.camera_seq, p.path.name, p.t) for p in importer.scan(req)]
        c = [(p.camera_seq, p.path.name, p.t) for p in importer.scan(req, max_workers=1)]
        assert a == b == c


def make_camera_jpg(path, dt_original):
    """模擬真實相機（Sony）JPG：DateTimeOriginal 存於 Exif SubIFD 而非 IFD0。"""
    img = Image.new("RGB", (8, 6), color=(30, 30, 30))
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
    img.save(path, exif=exif.tobytes())


class TestRealCameraExif:
    """真實相機把 DateTimeOriginal 放在 Exif SubIFD；退回 mtime 會破壞對齊正確性。"""

    def test_read_photo_time_from_sub_ifd(self, tmp_path):
        from datetime import datetime

        from tunnelview.importer import read_photo_time

        p = tmp_path / "DSC0001.JPG"
        make_camera_jpg(p, datetime(2026, 5, 28, 20, 49, 3))
        t, source = read_photo_time(p)
        assert source == "exif"
        assert t is not None
        assert t.year == 2026 and t.second == 3

    def test_scan_not_flagged_for_camera_files(self, ws, cam_dirs):
        from datetime import datetime, timedelta

        d0, d1 = cam_dirs
        base = datetime(2026, 5, 28, 20, 49, 0)
        make_jpg(d0 / "KEEP.JPG", base + timedelta(seconds=40))
        make_camera_jpg(d1 / "CAM.JPG", base + timedelta(seconds=140))
        req = ImportRequest(
            name="t",
            start_m=23000,
            end_m=24200,
            tolerance_seconds=2.0,
            cameras=[CameraInput(name="A", folder=str(d0)), CameraInput(name="B", folder=str(d1))],
        )
        preview = TunnelImporter(ws).preview(req)
        # CAM.JPG 若退回 mtime 會被標記 flagged；讀到 SubIFD EXIF 則不應 flagged
        assert preview.flagged_count == 0
