# Ticket 01 TDD — two-phase scan, single open, duplicate filenames
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

from tunnelview.db import Workspace
from tunnelview.importer import CameraInput, ImportRequest, TunnelImporter


def make_jpg(path, dt_original=None, size=(8, 6)):
    img = Image.new("RGB", size, color=(30, 30, 30))
    if dt_original is not None:
        exif = Image.Exif()
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


class TestEnumerateWithoutOpen:
    def test_enumerate_does_not_open_images(self, ws, tmp_path):
        base = datetime(2026, 5, 28, 20, 49, 0)
        d0 = tmp_path / "cam0"
        d0.mkdir()
        for i in range(3):
            make_jpg(d0 / f"P{i:04d}.JPG", base + timedelta(seconds=i * 10))
        # also a non-jpg should be counted as ignored
        (d0 / "readme.txt").write_text("hello")
        (d0 / "subdir").mkdir()
        make_jpg(d0 / "subdir" / "inner.JPG", base)  # subdir should be ignored (non-recursive)

        req = ImportRequest(name="t", start_m=23000, end_m=24200, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="A", folder=str(d0))])
        importer = TunnelImporter(ws)
        # enumerate phase should exist and not call Image.open
        assert hasattr(importer, "enumerate"), "TunnelImporter.enumerate not implemented (red)"
        with mock.patch("tunnelview.importer.Image.open", side_effect=Exception("should not open")):
            info = importer.enumerate(req)
            # info should contain per-camera counts without opening
            assert info["cameras"][0]["total_found"] >= 3
            assert info["cameras"][0]["valid_jpg"] == 3


class TestSingleOpen:
    def test_single_open_per_file(self, ws, tmp_path):
        base = datetime(2026, 5, 28, 20, 49, 0)
        d0 = tmp_path / "cam0"
        d0.mkdir()
        for i in range(4):
            make_jpg(d0 / f"X{i}.JPG", base + timedelta(seconds=i * 10))
        req = ImportRequest(name="t", start_m=0, end_m=100, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="A", folder=str(d0))])
        importer = TunnelImporter(ws)
        with mock.patch("tunnelview.importer.Image.open", wraps=Image.open) as m:
            importer.scan(req)
            # each jpg should be opened exactly once (old code opens twice)
            # allow some tolerance for bad files but for 4 valid files expect 4
            assert m.call_count == 4, f"expected single open per file, got {m.call_count}"


class TestDuplicateFilenames:
    def test_cross_camera_same_filename_not_colliding(self, ws, tmp_path):
        base = datetime(2026, 5, 28, 20, 49, 0)
        d0 = tmp_path / "cam0"
        d1 = tmp_path / "cam1"
        d0.mkdir(); d1.mkdir()
        # both cameras have DSC0001.JPG with different timestamps
        make_jpg(d0 / "DSC0001.JPG", base + timedelta(seconds=0))
        make_jpg(d0 / "DSC0002.JPG", base + timedelta(seconds=12))
        make_jpg(d1 / "DSC0001.JPG", base + timedelta(seconds=100))  # +100s offset
        make_jpg(d1 / "DSC0002.JPG", base + timedelta(seconds=112))
        req = ImportRequest(name="t", start_m=23000, end_m=24200, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="左", folder=str(d0)), CameraInput(name="右", folder=str(d1))])
        importer = TunnelImporter(ws)
        info = importer.commit(req)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            rows = conn.execute("SELECT rel_path, exif_time, camera_id FROM photos ORDER BY exif_time").fetchall()
            assert len(rows) == 4
            # each camera should have 2 rows with correct rel_path
            rels = [r["rel_path"] for r in rows]
            assert rels.count("DSC0001.JPG") == 2
            assert rels.count("DSC0002.JPG") == 2
            # ensure exif_time correctly assigned per camera (not swapped due to pid collision)
            # left cam DSC0001 should be earliest
            assert rows[0]["rel_path"] == "DSC0001.JPG"
        finally:
            conn.close()


class TestEnumerateCorrectness:
    def test_enumerate_then_scan_group_count_same_as_full_scan(self, ws, tmp_path):
        base = datetime(2026, 5, 28, 20, 49, 0)
        d0 = tmp_path / "cam0"
        d1 = tmp_path / "cam1"
        d0.mkdir(); d1.mkdir()
        for i, s in enumerate([0, 12, 25]):
            make_jpg(d0 / f"P{i}.JPG", base + timedelta(seconds=s))
        for i, s in enumerate([112, 125]):
            make_jpg(d1 / f"Q{i}.JPG", base + timedelta(seconds=s))
        req = ImportRequest(name="t", start_m=23000, end_m=24200, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="A", folder=str(d0)), CameraInput(name="B", folder=str(d1))])
        importer = TunnelImporter(ws)
        enum_info = importer.enumerate(req)
        preview = importer.preview(req)
        # enumerate valid count should equal preview photo counts sum
        total_enum = sum(c["valid_jpg"] for c in enum_info["cameras"])
        total_preview = sum(c.photo_count for c in preview.cameras)
        assert total_enum == total_preview == 5
        assert preview.group_count == 3


class TestBadFileHandling:
    def test_broken_jpg_counted_in_ignored(self, ws, tmp_path):
        d0 = tmp_path / "cam0"
        d0.mkdir()
        base = datetime(2026, 5, 28, 20, 49, 0)
        make_jpg(d0 / "good.JPG", base)
        (d0 / "broken.JPG").write_bytes(b"not a jpg")
        (d0 / "notes.txt").write_text("ignore me")
        req = ImportRequest(name="t", start_m=0, end_m=100, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="A", folder=str(d0))])
        importer = TunnelImporter(ws)
        info = importer.enumerate(req)
        # enumerate should see broken.JPG as valid jpg but later extract will mark broken
        # at least valid_jpg includes both good and broken (both .jpg)
        assert info["cameras"][0]["valid_jpg"] == 2
        # preview should still succeed and count at least good file
        preview = importer.preview(req)
        assert preview.cameras[0].photo_count >= 1


class TestScanWorkersAndProgress:
    """掃描併發預設值與進度回報契約。"""

    def test_default_scan_workers_fixed_16(self, monkeypatch):
        import os

        from tunnelview.importer import _default_scan_workers

        # IO-bound 併發不吃 CPU 核數：小 VM（2核）也應得 16，而非 cpu*4
        monkeypatch.setattr(os, "cpu_count", lambda: 2)
        assert _default_scan_workers() == 16

    def test_scan_reports_progress(self, ws, tmp_path):
        base = datetime(2026, 5, 28, 20, 49, 0)
        d0 = tmp_path / "cam0"
        d0.mkdir()
        for i in range(10):
            make_jpg(d0 / f"P{i:02d}.JPG", base + timedelta(seconds=i))
        req = ImportRequest(name="t", start_m=0, end_m=100, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="A", folder=str(d0))])
        ticks = []
        photos = TunnelImporter(ws).scan(req, progress=ticks.append)
        assert len(photos) == 10
        assert ticks and ticks[-1] == 10

    def test_scan_progress_reports_increments_not_cumulative(self, ws, tmp_path):
        """progress 契約＝增量：所有回呼數值總和必須等於總張數。

        回歸歸測試：舊版送「每相機累計值」（50,100,...），api 端當增量累加，
        導致 job.done 瞬間衝到 total（進度條假滿格）。
        """
        from datetime import datetime, timedelta

        base = datetime(2026, 5, 28, 20, 49, 0)
        d0, d1 = tmp_path / "cam0", tmp_path / "cam1"
        d0.mkdir()
        d1.mkdir()
        for i in range(120):
            make_jpg(d0 / f"A{i:03d}.JPG", base + timedelta(seconds=i))
        for i in range(30):
            make_jpg(d1 / f"B{i:03d}.JPG", base + timedelta(seconds=i))
        req = ImportRequest(name="t", start_m=0, end_m=100, tolerance_seconds=2.0,
                            cameras=[CameraInput(name="A", folder=str(d0)), CameraInput(name="B", folder=str(d1))])
        ticks = []
        photos = TunnelImporter(ws).scan(req, progress=ticks.append)
        assert len(photos) == 150
        assert sum(ticks) == 150          # 增量總和 == 總張數
        assert all(0 < t <= 50 for t in ticks)  # 每次增量不超過批次大小
