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

"""修訂 R9 匯入層契約：orientation 入庫、掃描快取命中、job 快路徑復用。"""

from datetime import datetime, timedelta

import pytest
from PIL import Image

from tunnelview.db import Workspace
from tunnelview.importer import CameraInput, ImportRequest, TunnelImporter

BASE_DT = datetime(2026, 8, 24, 10, 0, 0)


def make_jpg(path, dt_original=None, size=(32, 24), orientation=None):
    img = Image.new("RGB", size, color=(60, 60, 60))
    exif = Image.Exif()
    if dt_original is not None:
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
    if orientation is not None:
        exif[274] = orientation
    if dt_original is not None or orientation is not None:
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def env(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init()
    d0 = tmp_path / "cam0"
    d0.mkdir()
    for i in range(4):
        make_jpg(d0 / f"P{i:04d}.JPG", BASE_DT + timedelta(seconds=i * 10))
    req = ImportRequest(
        name="R9",
        start_m=0,
        end_m=1000,
        tolerance_seconds=2.0,
        cameras=[CameraInput(name="C0", folder=str(d0))],
    )
    return ws, TunnelImporter(ws), req, d0


class TestOrientationCapture:
    def test_scan_returns_orientation(self, env):
        ws, imp, req, d0 = env
        photos = imp.scan(req)
        assert all(p.orientation == 1 for p in photos)

    def test_commit_persists_orientation(self, env):
        ws, imp, req, d0 = env
        info = imp.commit(req)
        with ws.open_tunnel(info.tunnel_id) as conn:
            rows = conn.execute("SELECT orientation FROM photos").fetchall()
        assert rows and all(r["orientation"] == 1 for r in rows)


class TestScanCache:
    def test_second_scan_hits_cache_no_reopen(self, env, monkeypatch):
        ws, imp, req, d0 = env
        first = imp.scan(req)
        # 第二遍：攔截 read_exif_and_dims——快取全命中時不應被呼叫
        import tunnelview.importer as mod

        calls = []
        orig = mod.read_exif_and_dims

        def spy(p):
            calls.append(p)
            return orig(p)

        monkeypatch.setattr(mod, "read_exif_and_dims", spy)
        second = imp.scan(req)
        assert calls == []
        assert [(p.path.name, p.t, p.width) for p in second] == [
            (p.path.name, p.t, p.width) for p in first
        ]
        assert [p.time_source for p in second] == [p.time_source for p in first]

    def test_modified_file_is_rescanned(self, env):
        ws, imp, req, d0 = env
        imp.scan(req)
        # 改寫檔案內容（mtime/size 變）→ 應重掃且取得新值
        target = d0 / "P0002.JPG"
        make_jpg(target, BASE_DT + timedelta(seconds=999), size=(64, 48))
        photos = imp.scan(req)
        by_name = {p.path.name: p for p in photos}
        assert by_name["P0002.JPG"].t == BASE_DT + timedelta(seconds=999)
        assert by_name["P0002.JPG"].width == 64

    def test_cache_disabled_reads_every_time(self, env):
        ws, imp, req, d0 = env
        import tunnelview.importer as mod

        imp.scan(req)
        calls = []
        orig = mod.read_exif_and_dims

        def spy(p):
            calls.append(p)
            return orig(p)

        monkeypatch_mod = mod
        import unittest.mock as mock

        with mock.patch.object(mod, "read_exif_and_dims", side_effect=spy):
            imp.scan(req, use_cache=False)
        assert len(calls) == 4

    def test_clear_api_resets(self, env):
        ws, imp, req, d0 = env
        imp.scan(req)
        ws.scan_cache_clear()
        import tunnelview.importer as mod
        import unittest.mock as mock

        calls = []
        orig = mod.read_exif_and_dims

        def spy(p):
            calls.append(p)
            return orig(p)

        with mock.patch.object(mod, "read_exif_and_dims", side_effect=spy):
            imp.scan(req)
        assert len(calls) == 4

    def test_missing_exif_uses_mtime_and_caches(self, env, tmp_path):
        ws, imp, req, d0 = env
        d1 = tmp_path / "camx"
        d1.mkdir()
        make_jpg(d1 / "N0000.JPG")  # 無 EXIF → mtime 退回
        req2 = ImportRequest(
            name="x",
            start_m=0,
            end_m=100,
            tolerance_seconds=2.0,
            cameras=[CameraInput(name="CX", folder=str(d1))],
        )
        a = imp.scan(req2)
        b = imp.scan(req2)
        assert a[0].flagged and b[0].flagged
        assert a[0].t == b[0].t
        assert a[0].time_source == b[0].time_source == "mtime"
