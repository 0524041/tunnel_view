"""修訂 R2 API 契約：Schema v4 版型欄位、fs roots/recent、版型編輯端點。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tunnelview.anchor_model import SCHEMA_VERSION
from tunnelview.api import create_app
from tunnelview.db import Workspace
from tunnelview.fsutil import platform_roots

BASE_DT = datetime(2026, 5, 28, 20, 49, 0)


def make_jpg(path, dt_original=None):
    img = Image.new("RGB", (32, 24), color=(60, 60, 60))
    if dt_original is not None:
        exif = Image.Exif()
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def env(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init()
    d0, d1 = tmp_path / "cam0", tmp_path / "cam1"
    d0.mkdir()
    d1.mkdir()
    for i, s in enumerate([0, 12, 25]):
        make_jpg(d0 / f"P{i}.JPG", BASE_DT + timedelta(seconds=s))
        make_jpg(d1 / f"Q{i}.JPG", BASE_DT + timedelta(seconds=s))
    c = TestClient(create_app(ws))
    r = c.post(
        "/api/tunnels",
        json={
            "name": "R2隧道",
            "start_m": 23000,
            "end_m": 24200,
            "tolerance_seconds": 2.0,
            "layout_cols": "3",
            "cameras": [
                {"name": "A", "folder": str(d0), "grid_pos": 1},
                {"name": "B", "folder": str(d1), "grid_pos": 0},
            ],
        },
    )
    assert r.status_code == 200, r.text
    c.tid = r.json()["tunnel_id"]
    c.ws_root = ws.root
    return c


class TestSchemaV4:
    def test_create_persists_grid_and_cols(self, env):
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert info["layout_cols"] == "3"
        by_name = {c["name"]: c for c in info["cameras"]}
        assert by_name["A"]["grid_pos"] == 1
        assert by_name["B"]["grid_pos"] == 0

    def test_migration_backfills_grid_pos_and_cols(self, tmp_path):
        ws = Workspace(tmp_path / "ws")
        ws.init()
        d0 = tmp_path / "cam0"
        d0.mkdir()
        make_jpg(d0 / "P.JPG", BASE_DT)
        r = TestClient(create_app(Workspace(tmp_path / "ws"))).post(
            "/api/tunnels",
            json={
                "name": "舊",
                "start_m": 0,
                "end_m": 100,
                "tolerance_seconds": 2.0,
                "cameras": [{"name": "A", "folder": str(d0)}],
            },
        )
        tid = r.json()["tunnel_id"]

        # 退化成 v3：移除 grid_pos 與 layout_cols
        conn = ws.open_tunnel(tid)
        try:
            conn.execute("ALTER TABLE cameras DROP COLUMN grid_pos")
            conn.execute("DELETE FROM meta WHERE key='layout_cols'")
            conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
            conn.commit()
        finally:
            conn.close()

        conn = ws.open_tunnel(tid)  # 重開觸發遷移
        try:
            ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            assert ver == SCHEMA_VERSION
            row = conn.execute("SELECT seq, grid_pos FROM cameras ORDER BY seq").fetchall()
            assert all(r["grid_pos"] == r["seq"] for r in row)
            cols = conn.execute("SELECT value FROM meta WHERE key='layout_cols'").fetchone()[0]
            assert cols == "auto"
        finally:
            conn.close()


class TestLayoutEndpoints:
    def test_put_layout_cols(self, env):
        r = env.put(f"/api/tunnels/{env.tid}/layout", json={"cols": "2"})
        assert r.status_code == 200
        assert env.get(f"/api/tunnels/{env.tid}/info").json()["layout_cols"] == "2"

    def test_put_layout_auto(self, env):
        r = env.put(f"/api/tunnels/{env.tid}/layout", json={"cols": "auto"})
        assert r.status_code == 200
        assert env.get(f"/api/tunnels/{env.tid}/info").json()["layout_cols"] == "auto"

    def test_put_layout_invalid_rejected(self, env):
        assert env.put(f"/api/tunnels/{env.tid}/layout", json={"cols": "9"}).status_code == 400
        assert env.put(f"/api/tunnels/{env.tid}/layout", json={"cols": "x"}).status_code == 400

    def test_put_camera_grid_pos(self, env):
        r = env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"grid_pos": 5})
        assert r.status_code == 200
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert next(c for c in info["cameras"] if c["name"] == "A")["grid_pos"] == 5

    def test_realign_preserves_layout(self, env):
        before = self._snapshot(env)
        env.post(f"/api/tunnels/{env.tid}/realign/apply", json={"tolerance_seconds": 4.0})
        assert self._snapshot(env) == before

    def test_merge_preserves_layout(self, env):
        before = self._snapshot(env)
        env.put(f"/api/tunnels/{env.tid}/anchors/0", json={"mileage_m": 23100})
        r = env.post(
            f"/api/tunnels/{env.tid}/groups/1/merge",
            json={"direction": "next", "keep": "current"},
        )
        assert r.status_code == 200
        assert self._snapshot(env) == before

    @staticmethod
    def _snapshot(env):
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        return {
            "cols": info["layout_cols"],
            "pos": {c["name"]: c["grid_pos"] for c in info["cameras"]},
        }


class TestFsBrowse:
    def test_empty_path_returns_roots(self, env):
        data = env.get("/api/fs/list").json()
        assert isinstance(data["roots"], list) and len(data["roots"]) >= 1

    def test_platform_roots_formats(self):
        posix = platform_roots(is_windows=False)
        assert posix == ["/"]
        win = platform_roots(is_windows=True, drives_mask=0b100)  # C 槽
        assert win == ["C:\\"]

    def test_recent_recorded_on_create(self, env):
        data = env.get("/api/fs/list").json()
        recent = data["recent"]
        assert any("cam0" in p for p in recent)
        assert any("cam1" in p for p in recent)

    def test_recent_lru_cap_eight(self, env):
        for i in range(10):
            d = env.ws_root / f"fake{i}"
            d.mkdir(exist_ok=True)
            r = env.post("/api/fs/recent", json={"path": str(d)})
            assert r.status_code == 200
        data = env.get("/api/fs/list").json()
        assert len(data["recent"]) == 8
        assert any(p.endswith("fake9") for p in data["recent"])  # 最新保留
        assert not any(p.endswith("fake0") for p in data["recent"])  # 最舊淘汰
