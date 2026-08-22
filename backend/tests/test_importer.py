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
