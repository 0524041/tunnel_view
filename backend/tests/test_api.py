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

"""API 整合契約：匯入、視窗查詢、里程跳轉、錨點 CRUD＋重算、廣播、照片串流。"""

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tunnelview.api import create_app
from tunnelview.db import Workspace

BASE = {"year": 2026, "month": 5, "day": 28, "hour": 20, "minute": 49, "second": 0}


def make_jpg(path, dt_original=None):
    img = Image.new("RGB", (32, 24), color=(60, 60, 60))
    if dt_original is not None:
        exif = Image.Exif()
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def cam_dirs(tmp_path):
    """兩台相機五個事件（非均勻間隔），cam1 缺事件 0 與事件 3。"""
    from datetime import datetime, timedelta

    base = datetime(**BASE)
    d0, d1 = tmp_path / "cam0", tmp_path / "cam1"
    d0.mkdir()
    d1.mkdir()
    for i, s in enumerate([0, 12, 25, 40, 55]):
        make_jpg(d0 / f"P{i:04d}.JPG", base + timedelta(seconds=s))
    for i, s in enumerate([112, 125, 155]):
        make_jpg(d1 / f"Q{i:04d}.JPG", base + timedelta(seconds=s))
    return d0, d1


@pytest.fixture()
def client(tmp_path, cam_dirs):
    ws = Workspace(tmp_path / "ws")
    ws.init()
    app = create_app(ws)
    c = TestClient(app)
    d0, d1 = cam_dirs
    resp = c.post(
        "/api/tunnels",
        json={
            "name": "八卦山西行",
            "start_m": 23000,
            "end_m": 24200,
            "tolerance_seconds": 2.0,
            "cameras": [
                {"name": "左壁", "folder": str(d0)},
                {"name": "右壁", "folder": str(d1)},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    c.tunnel_id = resp.json()["tunnel_id"]
    return c


class TestTunnelEndpoints:
    def test_list_tunnels(self, client):
        data = client.get("/api/tunnels").json()
        assert len(data) == 1
        assert data[0]["name"] == "八卦山西行"
        assert data[0]["camera_count"] == 2

    def test_preview_does_not_create(self, cam_dirs, tmp_path):
        ws = Workspace(tmp_path / "ws2")
        ws.init()
        c = TestClient(create_app(ws))
        d0, d1 = cam_dirs
        resp = c.post(
            "/api/tunnels/preview",
            json={
                "name": "x",
                "start_m": 23000,
                "end_m": 24200,
                "tolerance_seconds": 2.0,
                "cameras": [
                    {"name": "左壁", "folder": str(d0)},
                    {"name": "右壁", "folder": str(d1)},
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["group_count"] == 5
        assert ws.list_tunnels() == []


class TestImportJobScanReuse:
    """preview→commit 免二次掃描契約：帶有效 job_id 時 commit 不得重掃 EXIF。"""

    @staticmethod
    def _body(d0, d1, name="x"):
        return {
            "name": name,
            "start_m": 23000,
            "end_m": 24200,
            "tolerance_seconds": 2.0,
            "cameras": [
                {"name": "左壁", "folder": str(d0)},
                {"name": "右壁", "folder": str(d1)},
            ],
        }

    @pytest.fixture()
    def scan_spy(self, monkeypatch):
        """包裝 TunnelImporter.scan 記錄呼叫次數。"""
        from tunnelview.importer import TunnelImporter

        calls = []
        orig = TunnelImporter.scan

        def spy(self, req, max_workers=None, progress=None):
            calls.append(1)
            return orig(self, req, max_workers=max_workers, progress=progress)

        monkeypatch.setattr(TunnelImporter, "scan", spy)
        return calls

    @staticmethod
    def _wait_done(c, job_id, timeout=10):
        import time as _time

        deadline = _time.perf_counter() + timeout
        while _time.perf_counter() < deadline:
            job = c.get(f"/api/import/jobs/{job_id}").json()
            if job["status"] != "running":
                return job
            _time.sleep(0.02)
        raise AssertionError("job 未在時限內完成")

    def _fresh_client(self, tmp_path):
        ws = Workspace(tmp_path / "ws_job")
        ws.init()
        return TestClient(create_app(ws))

    def test_commit_with_job_id_reuses_scan(self, cam_dirs, tmp_path, scan_spy):
        d0, d1 = cam_dirs
        c = self._fresh_client(tmp_path)
        r = c.post("/api/import/jobs/preview", json=self._body(d0, d1))
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        assert self._wait_done(c, job_id)["status"] == "done"
        assert len(scan_spy) == 1

        r = c.post("/api/tunnels", params={"job_id": job_id}, json=self._body(d0, d1))
        assert r.status_code == 200
        # 復用掃描：不得對原始資料夾做第二次 EXIF 掃描
        assert len(scan_spy) == 1
        tid = r.json()["tunnel_id"]
        data = c.get("/api/tunnels").json()
        assert len(data) == 1 and data[0]["name"] == "x"
        photos = c.get(f"/api/tunnels/{tid}/groups", params={"around": 2, "before": 2, "after": 2}).json()
        assert len(photos) >= 3

    def test_commit_without_job_id_rescans(self, cam_dirs, tmp_path, scan_spy):
        d0, d1 = cam_dirs
        c = self._fresh_client(tmp_path)
        r = c.post("/api/import/jobs/preview", json=self._body(d0, d1))
        self._wait_done(c, r.json()["job_id"])
        assert len(scan_spy) == 1

        r = c.post("/api/tunnels", json=self._body(d0, d1))
        assert r.status_code == 200
        assert len(scan_spy) == 2  # 無 job_id → 正常重掃

    def test_commit_fingerprint_mismatch_rescans(self, cam_dirs, tmp_path, scan_spy):
        d0, d1 = cam_dirs
        c = self._fresh_client(tmp_path)
        r = c.post("/api/import/jobs/preview", json=self._body(d0, d1))
        job_id = r.json()["job_id"]
        assert self._wait_done(c, job_id)["status"] == "done"

        # 機位順序對調 → 指紋不符，必須重掃且結果仍正確
        body = self._body(d1, d0)
        r = c.post("/api/tunnels", params={"job_id": job_id}, json=body)
        assert r.status_code == 200
        assert len(scan_spy) == 2


class TestImportJobBackground:
    """preview job 必須立即回應、背景執行、可輪詢進度——不得讓 HTTP 請求卡完整個掃描。"""

    @staticmethod
    def _body(d0, d1):
        return {
            "name": "x",
            "start_m": 23000,
            "end_m": 24200,
            "tolerance_seconds": 2.0,
            "cameras": [
                {"name": "左壁", "folder": str(d0)},
                {"name": "右壁", "folder": str(d1)},
            ],
        }

    def test_post_returns_immediately_and_polls_to_done(self, cam_dirs, tmp_path, monkeypatch):
        import time as _time

        from tunnelview.importer import TunnelImporter

        orig = TunnelImporter.scan

        def slow(self, req, max_workers=None, progress=None):
            _time.sleep(0.6)
            return orig(self, req, max_workers=max_workers, progress=progress)

        monkeypatch.setattr(TunnelImporter, "scan", slow)
        ws = Workspace(tmp_path / "ws_bg")
        ws.init()
        c = TestClient(create_app(ws))
        d0, d1 = cam_dirs

        t0 = _time.perf_counter()
        r = c.post("/api/import/jobs/preview", json=self._body(d0, d1))
        elapsed = _time.perf_counter() - t0

        assert r.status_code == 200
        assert elapsed < 0.4, f"POST 應立即回傳，實際等了 {elapsed:.2f}s"
        body = r.json()
        assert body["status"] == "running"
        job_id = body["job_id"]

        deadline = _time.perf_counter() + 10
        job = None
        while _time.perf_counter() < deadline:
            job = c.get(f"/api/import/jobs/{job_id}").json()
            if job["status"] != "running":
                break
            _time.sleep(0.05)
        assert job["status"] == "done"
        assert job["preview"]["group_count"] == 5
        assert job["total"] >= 8
        assert job["done"] == job["total"]

    def test_failed_scan_reports_error(self, cam_dirs, tmp_path, monkeypatch):
        from tunnelview.importer import TunnelImporter

        def boom(self, req, max_workers=None, progress=None):
            raise RuntimeError("網路碟斷線")

        monkeypatch.setattr(TunnelImporter, "scan", boom)
        ws = Workspace(tmp_path / "ws_bg2")
        ws.init()
        c = TestClient(create_app(ws))
        d0, d1 = cam_dirs

        r = c.post("/api/import/jobs/preview", json=self._body(d0, d1))
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        import time as _time

        deadline = _time.perf_counter() + 5
        job = None
        while _time.perf_counter() < deadline:
            job = c.get(f"/api/import/jobs/{job_id}").json()
            if job["status"] != "running":
                break
            _time.sleep(0.05)
        assert job["status"] == "failed"
        assert "網路碟斷線" in job["error"]
        # 失敗後 commit 不得誤用掃描快照：fallback 重掃同樣會撞上壞碟而失敗
        with pytest.raises(RuntimeError, match="網路碟斷線"):
            c.post("/api/tunnels", params={"job_id": job_id}, json=self._body(d0, d1))


class TestGroupWindow:
    def test_window_around_center(self, client):
        tid = client.tunnel_id
        data = client.get(f"/api/tunnels/{tid}/groups", params={"around": 2, "before": 1, "after": 1}).json()
        assert [g["seq"] for g in data] == [1, 2, 3]

    def test_missing_camera_slot_visible(self, client):
        tid = client.tunnel_id
        data = client.get(f"/api/tunnels/{tid}/groups", params={"around": 2, "before": 2, "after": 2}).json()
        # cam1 漏了事件 0（t=0）與事件 3（t=40）→ seq0、seq3 只有左壁相機
        for seq in (0, 3):
            g = next(g for g in data if g["seq"] == seq)
            assert [p["camera_seq"] for p in g["photos"]] == [0]
            assert g["missing_count"] >= 1
            assert g["anchored"] is False
        # 其餘群組兩台俱全
        g2 = next(g for g in data if g["seq"] == 2)
        assert sorted(p["camera_seq"] for p in g2["photos"]) == [0, 1]
        assert g2["missing_count"] == 0

    def test_window_clamps_to_bounds(self, client):
        tid = client.tunnel_id
        data = client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 5, "after": 5}).json()
        assert len(data) == 5

    def test_nearest_group_by_mileage(self, client):
        tid = client.tunnel_id
        resp = client.get(f"/api/tunnels/{tid}/groups/by_mileage", params={"m": 23650})
        assert resp.status_code == 200
        body = resp.json()
        assert body["seq"] == 2  # 初始等分：seq2 ≈ K23+500


class TestAnchors:
    def test_put_anchor_recomputes_all_estimates(self, client):
        tid = client.tunnel_id
        resp = client.put(f"/api/tunnels/{tid}/anchors/2", json={"mileage_m": 23500})
        assert resp.status_code == 200

        groups = client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 4, "after": 4}).json()
        est = {g["seq"]: g["est_mileage_m"] for g in groups}
        assert est[2] == 23500
        # 錨點前的群組應小於錨點值，之後大於
        assert est[1] < 23500 < est[3]
        # 已鎖定標記
        g2 = next(g for g in groups if g["seq"] == 2)
        assert g2["anchored"] is True

    def test_monotonic_violation_rejected_400(self, client):
        tid = client.tunnel_id
        client.put(f"/api/tunnels/{tid}/anchors/2", json={"mileage_m": 23500})
        resp = client.put(f"/api/tunnels/{tid}/anchors/1", json={"mileage_m": 24000})
        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_out_of_range_rejected_400(self, client):
        tid = client.tunnel_id
        resp = client.put(f"/api/tunnels/{tid}/anchors/0", json={"mileage_m": 99999})
        assert resp.status_code == 400

    def test_delete_anchor_restores_auto_interpolation(self, client):
        tid = client.tunnel_id
        before = {
            g["seq"]: g["est_mileage_m"]
            for g in client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 4, "after": 4}).json()
        }
        client.put(f"/api/tunnels/{tid}/anchors/2", json={"mileage_m": 23500})
        after_anchor = {
            g["seq"]: g["est_mileage_m"]
            for g in client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 4, "after": 4}).json()
        }
        assert after_anchor != before

        resp = client.delete(f"/api/tunnels/{tid}/anchors/2")
        assert resp.status_code == 200
        restored = {
            g["seq"]: g["est_mileage_m"]
            for g in client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 4, "after": 4}).json()
        }
        assert restored == before

    def test_list_anchors(self, client):
        tid = client.tunnel_id
        client.put(f"/api/tunnels/{tid}/anchors/2", json={"mileage_m": 23500})
        data = client.get(f"/api/tunnels/{tid}/anchors").json()
        assert data == [{"group_seq": 2, "mileage_m": 23500}]


class TestBroadcast:
    def test_anchor_change_broadcasts_over_websocket(self, client):
        tid = client.tunnel_id
        with client.websocket_connect(f"/ws/tunnels/{tid}") as ws_conn:
            resp = client.put(f"/api/tunnels/{tid}/anchors/2", json={"mileage_m": 23500})
            assert resp.status_code == 200
            msg = json.loads(ws_conn.receive_text())
            assert msg["type"] == "anchor_update"
            assert msg["anchor"]["group_seq"] == 2


class TestOverview:
    def test_compact_full_line_payload(self, client):
        tid = client.tunnel_id
        ov = client.get(f"/api/tunnels/{tid}/overview").json()
        assert ov["group_count"] == 5
        assert ov["cameras"] == ["左壁", "右壁"]
        assert ov["start_m"] == 23000 and ov["end_m"] == 24200
        assert len(ov["groups"]["seq"]) == 5
        assert ov["groups"]["missing"][0] >= 1  # seq0 缺右壁
        assert sum(ov["groups"]["anchored"]) == 0


class TestPhotoStreaming:
    def test_serve_resized_photo(self, client):
        tid = client.tunnel_id
        groups = client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 0, "after": 0}).json()
        pid = groups[0]["photos"][0]["photo_id"]
        resp = client.get(f"/api/tunnels/{tid}/photos/{pid}", params={"w": 16})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        img = Image.open(__import__("io").BytesIO(resp.content))
        assert img.size[0] == 16

    def test_serve_original_when_no_width(self, client):
        tid = client.tunnel_id
        groups = client.get(f"/api/tunnels/{tid}/groups", params={"around": 0, "before": 0, "after": 0}).json()
        pid = groups[0]["photos"][0]["photo_id"]
        resp = client.get(f"/api/tunnels/{tid}/photos/{pid}")
        assert resp.status_code == 200
        img = Image.open(__import__("io").BytesIO(resp.content))
        assert img.size == (32, 24)

    def test_unknown_photo_404(self, client):
        tid = client.tunnel_id
        assert client.get(f"/api/tunnels/{tid}/photos/99999").status_code == 404
