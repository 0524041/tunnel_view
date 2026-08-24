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

"""方向統一契約：混合直橫式偵測、rotation_override 納入異常計算、批次轉正端點。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tunnelview.api import create_app
from tunnelview.db import Workspace


def make_jpg(path, dt_original, size=(40, 30)):
    """size 預設橫式 4:3；(30,40) 為直式。"""
    img = Image.new("RGB", size, color=(60, 60, 60))
    exif = Image.Exif()
    exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
    img.save(path, exif=exif.tobytes())


@pytest.fixture()
def mixed_dirs(tmp_path):
    """cam0：3 橫 + 2 直（少數派=直）；cam1：全橫。"""
    base = datetime(2026, 5, 28, 20, 49, 0)
    d0, d1 = tmp_path / "cam0", tmp_path / "cam1"
    d0.mkdir()
    d1.mkdir()
    for i, s in enumerate([0, 12, 25]):
        make_jpg(d0 / f"L{i}.JPG", base + timedelta(seconds=s))            # 橫
    for i, s in enumerate([12, 25]):
        make_jpg(d0 / f"P{i}.JPG", base + timedelta(seconds=s), (30, 40))  # 直
    for i, s in enumerate([0, 12, 25]):
        make_jpg(d1 / f"Q{i}.JPG", base + timedelta(seconds=s))
    return d0, d1


@pytest.fixture()
def env(mixed_dirs, tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init()
    c = TestClient(create_app(ws))
    d0, d1 = mixed_dirs
    r = c.post(
        "/api/tunnels",
        json={
            "name": "t",
            "start_m": 23000,
            "end_m": 24200,
            "tolerance_seconds": 2.0,
            "cameras": [
                {"name": "左壁", "folder": str(d0)},
                {"name": "右壁", "folder": str(d1)},
            ],
        },
    )
    assert r.status_code == 200
    c.tid = r.json()["tunnel_id"]
    return c


class TestOrientationStatsInReport:
    def test_commit_report_contains_per_camera_orientation(self, mixed_dirs, tmp_path):
        from tunnelview.importer import CameraInput, ImportRequest, TunnelImporter

        ws = Workspace(tmp_path / "ws2")
        ws.init()
        d0, d1 = mixed_dirs
        info = TunnelImporter(ws).commit(
            ImportRequest(
                name="t",
                start_m=23000,
                end_m=24200,
                tolerance_seconds=2.0,
                cameras=[CameraInput(name="左壁", folder=str(d0)), CameraInput(name="右壁", folder=str(d1))],
            )
        )
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            report = conn.execute("SELECT value FROM meta WHERE key='import_report'").fetchone()
            import json

            stats = json.loads(report["value"])["orientation_stats"]
        finally:
            conn.close()
        by_name = {s["camera"]: s for s in stats}
        assert by_name["左壁"]["landscape"] == 3
        assert by_name["左壁"]["portrait"] == 2
        assert by_name["左壁"]["minority"] == "portrait"
        assert by_name["右壁"]["minority"] is None


class TestAspectAnomalyHonorsOverride:
    def test_recompute_clears_flag_for_overridden_photo(self, mixed_dirs, tmp_path):
        from tunnelview.importer import CameraInput, ImportRequest, TunnelImporter

        ws = Workspace(tmp_path / "ws3")
        ws.init()
        d0, d1 = mixed_dirs
        info = TunnelImporter(ws).commit(
            ImportRequest(
                name="t",
                start_m=23000,
                end_m=24200,
                tolerance_seconds=2.0,
                cameras=[CameraInput(name="左壁", folder=str(d0)), CameraInput(name="右壁", folder=str(d1))],
            )
        )
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            # 兩張直式照片：一張給 override 90（已人工轉正），一張不動
            rows = conn.execute(
                "SELECT p.id FROM photos p JOIN cameras c ON c.id=p.camera_id "
                "WHERE c.name='左壁' AND p.width < p.height ORDER BY p.id"
            ).fetchall()
            assert len(rows) == 2
            conn.execute("UPDATE photos SET rotation_override=90 WHERE id=?", (rows[0]["id"],))
            conn.commit()
        finally:
            conn.close()

        TunnelImporter(ws)._recompute_anomalies(info.tunnel_id)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            flagged = {
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM photos WHERE aspect_anomaly=1 AND camera_id="
                    "(SELECT id FROM cameras WHERE name='左壁')"
                ).fetchall()
            }
        finally:
            conn.close()
        assert rows[0]["id"] not in flagged  # 已轉正 → 不再標記
        assert rows[1]["id"] in flagged      # 未處理 → 仍標記


class TestUnifyEndpoint:
    def test_unify_sets_override_and_clears_flags(self, env):
        tid = env.tid
        # 取得左壁的直式照片 id（未轉正前）
        groups = env.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 10, "after": 10}).json()
        portrait_pids = [
            p["photo_id"]
            for g in groups
            for p in g["photos"]
            if p["camera_seq"] == 0 and p["width"] < p["height"]
        ]
        assert len(portrait_pids) == 2

        r = env.post(f"/api/tunnels/{tid}/cameras/0/unify", json={"angle": 90})
        assert r.status_code == 200
        assert r.json()["updated"] >= 2

        # override 生效且比例異常旗標清空
        g2 = env.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 10, "after": 10}).json()
        fixed = {p["photo_id"]: p for g in g2 for p in g["photos"]}
        for pid in portrait_pids:
            assert fixed[pid]["rotation_override"] == 90
        assert all(p["aspect_anomaly"] == 0 for p in fixed.values())

    def test_unify_rejects_bad_angle(self, env):
        r = env.post(f"/api/tunnels/{env.tid}/cameras/0/unify", json={"angle": 45})
        assert r.status_code == 400
