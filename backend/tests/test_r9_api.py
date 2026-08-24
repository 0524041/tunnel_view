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

"""修訂 R9 API 契約：縮圖快取標頭、像素版本失效、job 持久化、專案分組。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tunnelview.api import create_app
from tunnelview.db import Workspace

BASE_DT = datetime(2026, 8, 24, 10, 0, 0)


def make_jpg(path, dt_original=None, size=(64, 48)):
    img = Image.new("RGB", size, color=(60, 60, 60))
    if dt_original is not None:
        exif = Image.Exif()
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # 多數測試不驗背景預生成——停用以避免與快取斷言競爭（專用測試自行開啟）
    monkeypatch.setenv("TUNNELVIEW_THUMB_PREGEN", "0")
    ws = Workspace(tmp_path / "ws")
    ws.init()
    d0, d1 = tmp_path / "cam0", tmp_path / "cam1"
    d0.mkdir()
    d1.mkdir()
    for i, s in enumerate([0, 12, 25, 40]):
        make_jpg(d0 / f"P{i:04d}.JPG", BASE_DT + timedelta(seconds=s))
    for i, s in enumerate([112, 125]):
        make_jpg(d1 / f"Q{i:04d}.JPG", BASE_DT + timedelta(seconds=s))
    app = create_app(ws)
    c = TestClient(app)
    body = {
        "name": "R9隧道",
        "start_m": 0,
        "end_m": 1000,
        "tolerance_seconds": 2.0,
        "cameras": [
            {"name": "左壁", "folder": str(d0)},
            {"name": "右壁", "folder": str(d1)},
        ],
    }
    r = c.post("/api/tunnels", json=body)
    assert r.status_code == 200, r.text
    c.tid = r.json()["tunnel_id"]
    c.ws = ws
    c.body = body
    c.d0, c.d1 = d0, d1
    return c


def _window(client, around=0, before=6, after=14):
    return client.get(
        f"/api/tunnels/{client.tid}/groups",
        params={"around": around, "before": before, "after": after},
    ).json()


def _first_photo(client):
    g = _window(client)[0]
    return g["photos"][0]


class TestThumbCacheHeaders:
    def test_thumb_response_immutable(self, env):
        pid = _first_photo(env)["photo_id"]
        r = env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 240, "pv": 0})
        assert r.status_code == 200
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_thumb_cache_file_named_with_pv(self, env):
        pid = _first_photo(env)["photo_id"]
        env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 240, "pv": 3})
        cache_dir = env.ws.root / ".thumb_cache"
        names = [f.name for f in cache_dir.iterdir() if f.name.startswith(f"{env.tid}_{pid}_")]
        assert any("_v3" in n for n in names)

    def test_fastpath_original_max_age(self, env):
        pid = _first_photo(env)["photo_id"]
        r = env.get(f"/api/tunnels/{env.tid}/photos/{pid}")
        assert r.status_code == 200
        assert "max-age=3600" in r.headers.get("cache-control", "")


class TestPixelVersionInvalidation:
    def test_groups_expose_pixel_version(self, env):
        p = _first_photo(env)
        assert "pixel_version" in p

    def test_annotation_does_not_invalidate(self, env):
        pid = _first_photo(env)["photo_id"]
        # 先生成一張縮圖
        env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 240, "pv": 0})
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": "備註", "items": []},
        )
        assert r.status_code == 200
        cache_dir = env.ws.root / ".thumb_cache"
        names = [f.name for f in cache_dir.iterdir() if f.name.startswith(f"{env.tid}_{pid}_")]
        assert names, "改備註不應刪除縮圖快取"
        with env.ws.open_tunnel(env.tid) as conn:
            pv = conn.execute("SELECT pixel_version FROM photos WHERE id=?", (pid,)).fetchone()["pixel_version"]
        assert pv == 0

    def test_mark_missing_and_realign_do_not_invalidate(self, env):
        pid = _first_photo(env)["photo_id"]
        env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 240, "pv": 0})
        r = env.post(f"/api/tunnels/{env.tid}/photos/{pid}/mark_missing")
        assert r.status_code == 200
        r2 = env.post(f"/api/tunnels/{env.tid}/realign/apply", json={"tolerance_seconds": 2.0})
        assert r2.status_code == 200
        with env.ws.open_tunnel(env.tid) as conn:
            pv = conn.execute("SELECT pixel_version FROM photos WHERE id=?", (pid,)).fetchone()["pixel_version"]
        assert pv == 0

    def test_photo_rotation_bumps_single(self, env):
        pid = _first_photo(env)["photo_id"]
        env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 240, "pv": 0})
        r = env.put(f"/api/tunnels/{env.tid}/photos/{pid}/rotation", json={"angle": 90})
        assert r.status_code == 200
        cache_dir = env.ws.root / ".thumb_cache"
        names = [f.name for f in cache_dir.iterdir() if f.name.startswith(f"{env.tid}_{pid}_")]
        assert names == [], "單張旋轉後舊縮圖應被清除"
        with env.ws.open_tunnel(env.tid) as conn:
            pv = conn.execute("SELECT pixel_version FROM photos WHERE id=?", (pid,)).fetchone()["pixel_version"]
        assert pv == 1

    def test_camera_rotation_bumps_all_camera_photos(self, env):
        win = _window(env)
        cam_pids = [p["photo_id"] for g in win for p in g["photos"] if p["camera_seq"] == 0]
        other_pid = next(p["photo_id"] for g in win for p in g["photos"] if p["camera_seq"] != 0)
        r = env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"rotation": 90})
        assert r.status_code == 200
        with env.ws.open_tunnel(env.tid) as conn:
            pvs = {
                r["id"]: r["pixel_version"]
                for r in conn.execute("SELECT id, pixel_version FROM photos").fetchall()
            }
        for pid in cam_pids:
            assert pvs[pid] == 1
        assert pvs[other_pid] == 0


class TestOrientationFromDB:
    def test_serve_backfills_null_orientation(self, env):
        # 模擬舊隧道：orientation 為 NULL
        with env.ws.open_tunnel(env.tid) as conn:
            conn.execute("UPDATE photos SET orientation = NULL")
            pid = conn.execute("SELECT id FROM photos LIMIT 1").fetchone()["id"]
        r = env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 120, "pv": 0})
        assert r.status_code == 200
        with env.ws.open_tunnel(env.tid) as conn:
            v = conn.execute("SELECT orientation FROM photos WHERE id=?", (pid,)).fetchone()["orientation"]
        assert v is not None

    def test_serve_does_not_open_file_when_orientation_known(self, env, monkeypatch):
        """AC3：orientation 已入庫時，serve 路徑不得再開原檔讀 tag 274。"""
        import tunnelview.api as api_mod

        pid = _first_photo(env)["photo_id"]
        with env.ws.open_tunnel(env.tid) as conn:
            conn.execute("UPDATE photos SET orientation = 6 WHERE id = ?", (pid,))

        def _boom(path):
            raise AssertionError("orientation 已知時不應開檔讀 EXIF")

        monkeypatch.setattr(api_mod, "_read_orientation_tag", _boom)
        r = env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 120, "pv": 0})
        assert r.status_code == 200


class TestConditionalRequest304:
    def test_thumb_304_on_if_none_match(self, env):
        pid = _first_photo(env)["photo_id"]
        url = f"/api/tunnels/{env.tid}/photos/{pid}"
        r1 = env.get(url, params={"w": 240, "pv": 0})
        assert r1.status_code == 200
        etag = r1.headers["etag"]
        r2 = env.get(url, params={"w": 240, "pv": 0}, headers={"If-None-Match": etag})
        assert r2.status_code == 304
        assert r2.headers["etag"] == etag

    def test_fastpath_original_304(self, env):
        pid = _first_photo(env)["photo_id"]
        url = f"/api/tunnels/{env.tid}/photos/{pid}"
        r1 = env.get(url)
        assert r1.status_code == 200
        etag = r1.headers.get("etag")
        assert etag
        r2 = env.get(url, headers={"If-None-Match": etag})
        assert r2.status_code == 304


class TestJobPersistence:
    def _mk_job(self, client, **body_overrides):
        body = {**client.body, **body_overrides}
        r = client.post("/api/import/jobs/preview", json=body)
        assert r.status_code == 200, r.text
        return r.json()["job_id"]

    def test_job_row_persisted_and_done_has_preview(self, env):
        jid = self._mk_job(env)
        deadline = datetime.now() + timedelta(seconds=30)
        while True:
            j = env.get(f"/api/import/jobs/{jid}").json()
            if j["status"] != "running":
                break
            assert datetime.now() < deadline
            import time as _t

            _t.sleep(0.05)
        assert j["status"] == "done"
        assert j["preview"]["group_count"] >= 1
        row = env.ws.job_get(jid)
        assert row is not None and row["status"] == "done"

    def test_commit_after_restart_reuses_scan_no_rescan(self, env):
        jid = self._mk_job(env)
        import time as _t

        deadline = datetime.now() + timedelta(seconds=30)
        while env.get(f"/api/import/jobs/{jid}").json()["status"] == "running":
            assert datetime.now() < deadline
            _t.sleep(0.05)
        # 重啟模擬：同一 workspace 建新 app（runtime 記憶體全失）
        app2 = create_app(env.ws)
        c2 = TestClient(app2)
        # 掃描計數器：重掃會呼叫 importer.scan
        from tunnelview.importer import TunnelImporter

        calls = []
        orig_scan = TunnelImporter.scan

        def spy(self, req, *a, **k):
            calls.append(1)
            return orig_scan(self, req, *a, **k)

        TunnelImporter.scan = spy
        try:
            r = c2.post("/api/tunnels", json={**env.body, "name": "重啟後"}, params={"job_id": jid})
        finally:
            TunnelImporter.scan = orig_scan
        assert r.status_code == 200, r.text
        assert calls == [], "fingerprint 相符的 done job 應從持久化掃描結果復用，不得重掃"

    def test_running_marked_interrupted_on_boot(self, env):
        jid = self._mk_job(env)
        env.ws.job_interrupt_running()
        app2 = create_app(env.ws)
        c2 = TestClient(app2)
        j = c2.get(f"/api/import/jobs/{jid}").json()
        assert j["status"] in ("interrupted", "done")  # 可能已完成也可能被打斷
        if j["status"] == "interrupted":
            assert j["preview"] is None

    def test_delete_job_removes_db_row(self, env):
        jid = self._mk_job(env)
        r = env.delete(f"/api/import/jobs/{jid}")
        assert r.status_code == 200
        assert env.ws.job_get(jid) is None


class TestProjectsAPI:
    def test_crud_and_move(self, env):
        r = env.post("/api/projects", json={"name": "八卦山隧道"})
        assert r.status_code == 200
        pid = r.json()["id"]
        lst = env.get("/api/projects").json()
        assert lst[0]["name"] == "八卦山隧道" and lst[0]["tunnel_count"] == 0

        r = env.post(f"/api/tunnels/{env.tid}/move", json={"project_id": pid})
        assert r.status_code == 200
        lst = env.get("/api/projects").json()
        assert lst[0]["tunnel_count"] == 1
        tunnels = {t["tunnel_id"]: t for t in env.get("/api/tunnels").json()}
        assert tunnels[env.tid]["project_name"] == "八卦山隧道"

        r = env.put(f"/api/projects/{pid}", json={"name": "八卦山"})
        assert r.status_code == 200
        # 刪除專案 → 隧道回未分類
        r = env.delete(f"/api/projects/{pid}")
        assert r.status_code == 200
        tunnels = {t["tunnel_id"]: t for t in env.get("/api/tunnels").json()}
        assert tunnels[env.tid]["project_name"] is None

    def test_duplicate_project_conflict(self, env):
        env.post("/api/projects", json={"name": "A"})
        r = env.post("/api/projects", json={"name": "a"})  # 不分大小寫視為重複
        assert r.status_code == 409

    def test_create_tunnel_with_project(self, env):
        pid = env.post("/api/projects", json={"name": "P1"}).json()["id"]
        body = {
            **env.body,
            "name": "帶專案",
            "project_id": pid,
            "cameras": [
                {"name": "L", "folder": str(env.d0)},
                {"name": "R", "folder": str(env.d1)},
            ],
        }
        r = env.post("/api/tunnels", json=body)
        assert r.status_code == 200
        tid = r.json()["tunnel_id"]
        tunnels = {t["tunnel_id"]: t for t in env.get("/api/tunnels").json()}
        assert tunnels[tid]["project_id"] == pid

    def test_move_to_unknown_project_404(self, env):
        r = env.post(f"/api/tunnels/{env.tid}/move", json={"project_id": 987654})
        assert r.status_code == 404


class TestRecentAndTouch:
    def test_info_touches_last_opened(self, env):
        r = env.get(f"/api/tunnels/{env.tid}/info")
        assert r.status_code == 200
        tunnels = {t["tunnel_id"]: t for t in env.get("/api/tunnels").json()}
        assert tunnels[env.tid]["last_opened_at"] is not None


class TestGetWindowShape:
    def test_join_shape_matches_legacy(self, env):
        win = env.get(f"/api/tunnels/{env.tid}/groups", params={"around": 0, "before": 6, "after": 14}).json()
        assert len(win) >= 3
        g = win[0]
        assert set(g.keys()) >= {"seq", "corrected_time", "est_mileage_m", "missing_count", "anchored", "photos"}
        for p in g["photos"]:
            assert set(p.keys()) >= {
                "photo_id", "camera_seq", "rel_path", "flagged", "width", "height",
                "rotation_override", "camera_rotation", "exif_time", "corrected_time",
                "time_source", "aspect_anomaly", "has_dims", "anomaly_types",
            }
        # 群組內照片依相機序排序
        seqs = [p["camera_seq"] for p in g["photos"]]
        assert seqs == sorted(seqs)


class TestBackgroundPreGenerate:
    def test_commit_pregens_1600_thumbs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TUNNELVIEW_THUMB_WORKERS", "2")
        monkeypatch.delenv("TUNNELVIEW_THUMB_PREGEN", raising=False)
        ws = Workspace(tmp_path / "ws")
        ws.init()
        d = tmp_path / "cam"
        d.mkdir()
        for i in range(3):
            make_jpg(d / f"P{i}.JPG", BASE_DT + timedelta(seconds=i * 10))
        app = create_app(ws)
        c = TestClient(app)
        r = c.post(
            "/api/tunnels",
            json={
                "name": "預生成",
                "start_m": 0,
                "end_m": 100,
                "tolerance_seconds": 2.0,
                "cameras": [{"name": "C", "folder": str(d)}],
            },
        )
        tid = r.json()["tunnel_id"]
        cache_dir = ws.root / ".thumb_cache"
        deadline = datetime.now() + timedelta(seconds=20)
        while True:
            done_files = list(cache_dir.glob(f"{tid}_*_1600_0_v0.jpg"))
            if len(done_files) == 3:
                break
            assert datetime.now() < deadline, f"預生成未完成：{len(done_files)}/3"
            import time as _t

            _t.sleep(0.1)

    def test_pregen_disabled_by_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TUNNELVIEW_THUMB_PREGEN", "0")
        ws = Workspace(tmp_path / "ws2")
        ws.init()
        d = tmp_path / "cam2"
        d.mkdir()
        make_jpg(d / "P.JPG", BASE_DT)
        app = create_app(ws)
        c = TestClient(app)
        r = c.post(
            "/api/tunnels",
            json={
                "name": "停用",
                "start_m": 0,
                "end_m": 100,
                "tolerance_seconds": 2.0,
                "cameras": [{"name": "C", "folder": str(d)}],
            },
        )
        tid = r.json()["tunnel_id"]
        import time as _t

        _t.sleep(1.0)
        cache_dir = ws.root / ".thumb_cache"
        if cache_dir.is_dir():
            assert not list(cache_dir.glob(f"{tid}_*"))
