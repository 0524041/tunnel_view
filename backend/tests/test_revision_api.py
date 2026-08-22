"""修訂 R1 API 契約：改判/復原、重新對齊、合併、旋轉、資訊面板。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tunnelview.api import create_app
from tunnelview.db import Workspace

BASE_DT = datetime(2026, 5, 28, 20, 49, 0)


def make_jpg(path, dt_original=None, size=(32, 24)):
    img = Image.new("RGB", size, color=(60, 60, 60))
    if dt_original is not None:
        exif = Image.Exif()
        exif[36868] = dt_original.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


@pytest.fixture()
def env(tmp_path):
    """兩機五事件；cam1 缺事件 0 與事件 3。"""
    ws = Workspace(tmp_path / "ws")
    ws.init()
    d0, d1 = tmp_path / "cam0", tmp_path / "cam1"
    d0.mkdir()
    d1.mkdir()
    events = [0, 12, 25, 40, 55]
    for i, s in enumerate(events):
        make_jpg(d0 / f"P{i:04d}.JPG", BASE_DT + timedelta(seconds=s))
    for i, s in enumerate([112, 125, 155]):
        make_jpg(d1 / f"Q{i:04d}.JPG", BASE_DT + timedelta(seconds=s))
    app = create_app(ws)
    c = TestClient(app)
    r = c.post(
        "/api/tunnels",
        json={
            "name": "R1隧道",
            "start_m": 23000,
            "end_m": 24200,
            "tolerance_seconds": 2.0,
            "cameras": [
                {"name": "左壁", "folder": str(d0)},
                {"name": "右壁", "folder": str(d1)},
            ],
        },
    )
    assert r.status_code == 200, r.text
    c.tid = r.json()["tunnel_id"]
    c.ws_root = ws.root
    return c


def _window(client, around, before=6, after=14):
    return {
        g["seq"]: g
        for g in client.get(
            f"/api/tunnels/{client.tid}/groups",
            params={"around": around, "before": before, "after": after},
        ).json()
    }


class TestFlagAndMissing:
    def test_mark_missing_hides_and_restores(self, env):
        win = _window(env, 1)
        g1 = win[1]
        pid = g1["photos"][0]["photo_id"]

        r = env.post(f"/api/tunnels/{env.tid}/photos/{pid}/mark_missing")
        assert r.status_code == 200

        win2 = _window(env, 1)
        assert pid not in [p["photo_id"] for p in win2[1]["photos"]]
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert len(info["manual_missing"]) == 1

        r = env.post(f"/api/tunnels/{env.tid}/photos/{pid}/restore")
        assert r.status_code == 200
        win3 = _window(env, 1)
        restored_back = pid in [p["photo_id"] for p in win3[1]["photos"]] or any(
            p["photo_id"] == pid for g in win3.values() for p in g["photos"]
        )
        assert restored_back

    def test_mark_missing_carrier_transfers_anchor(self, env):
        # 在群組 2 錨定，載體應為 cam0 的照片
        env.put(f"/api/tunnels/{env.tid}/anchors/2", json={"mileage_m": 23500})
        win = _window(env, 2)
        carrier_pid = win[2]["photos"][0]["photo_id"]

        r = env.post(f"/api/tunnels/{env.tid}/photos/{carrier_pid}/mark_missing")
        assert r.status_code == 200

        anchors = env.get(f"/api/tunnels/{env.tid}/anchors").json()
        assert len(anchors) == 1
        assert anchors[0]["mileage_m"] == 23500
        assert anchors[0]["group_seq"] == 2  # 錨點存活且仍在群組 2


class TestRealign:
    def test_dry_run_does_not_write(self, env):
        before_ov = env.get(f"/api/tunnels/{env.tid}/overview").json()
        before_est = list(before_ov["groups"]["est"])

        r = env.post(f"/api/tunnels/{env.tid}/realign", json={"tolerance_seconds": 8.0})
        assert r.status_code == 200
        body = r.json()
        assert body["group_count"] == 5
        assert "missing_distribution" in body and "cameras" in body

        after_ov = env.get(f"/api/tunnels/{env.tid}/overview").json()
        assert after_ov["group_count"] == before_ov["group_count"]
        assert list(after_ov["groups"]["est"]) == before_est

    def test_apply_preserves_anchors(self, env):
        env.put(f"/api/tunnels/{env.tid}/anchors/1", json={"mileage_m": 23250})
        env.put(f"/api/tunnels/{env.tid}/anchors/3", json={"mileage_m": 23900})

        with env.websocket_connect(f"/ws/tunnels/{env.tid}") as ws_conn:
            r = env.post(f"/api/tunnels/{env.tid}/realign/apply", json={"tolerance_seconds": 4.0})
            assert r.status_code == 200
            msg = ws_conn.receive_json()
            assert msg["type"] == "realigned"

        anchors = env.get(f"/api/tunnels/{env.tid}/anchors").json()
        assert {a["mileage_m"] for a in anchors} == {23250, 23900}
        assert all(isinstance(a["group_seq"], int) for a in anchors)

        ov = env.get(f"/api/tunnels/{env.tid}/overview").json()
        assert ov["group_count"] >= 4
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert info["report"]["tolerance_seconds"] == 4.0


class TestMerge:
    def test_merge_without_conflict(self, env):
        # 群組 4 只有右壁（事件55 缺左壁？實際上事件55 兩機都有）——改用直接構造：
        # 先把群組 3 的左壁照片改判缺照，使群組 3 只剩右壁，與群組 4 合併不衝突
        win = _window(env, 3)
        left_pid = next(p["photo_id"] for p in win[3]["photos"] if p["camera_seq"] == 0)
        env.post(f"/api/tunnels/{env.tid}/photos/{left_pid}/mark_missing")

        before = env.get(f"/api/tunnels/{env.tid}/overview").json()["group_count"]
        r = env.post(
            f"/api/tunnels/{env.tid}/groups/3/merge",
            json={"direction": "next"},
        )
        assert r.status_code == 200, r.text

        ov = env.get(f"/api/tunnels/{env.tid}/overview").json()
        assert ov["group_count"] == before - 1

    def test_merge_conflict_requires_keep(self, env):
        r = env.post(f"/api/tunnels/{env.tid}/groups/1/merge", json={"direction": "next"})
        assert r.status_code == 409
        assert "conflict_cameras" in r.json()["detail"]

        r2 = env.post(
            f"/api/tunnels/{env.tid}/groups/1/merge",
            json={"direction": "next", "keep": "current"},
        )
        assert r2.status_code == 200
        # 落選者（群組2的衝突相機照片）應被改判缺照
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert len(info["manual_missing"]) >= 1

    def test_merge_keeps_anchors_resolvable(self, env):
        env.put(f"/api/tunnels/{env.tid}/anchors/2", json={"mileage_m": 23500})
        r = env.post(
            f"/api/tunnels/{env.tid}/groups/1/merge",
            json={"direction": "next", "keep": "current"},
        )
        assert r.status_code == 200
        anchors = env.get(f"/api/tunnels/{env.tid}/anchors").json()
        assert any(a["mileage_m"] == 23500 for a in anchors)


class TestRotation:
    def test_camera_rotation_swaps_served_dimensions(self, env):
        win = _window(env, 0)
        pid = win[0]["photos"][0]["photo_id"]

        r0 = env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 16})
        import io

        first = Image.open(io.BytesIO(r0.content)).size
        assert first == (16, 12)  # 橫式原圖 32×24 → 縮圖寬 16

        r = env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"rotation": 90})
        assert r.status_code == 200

        r90 = env.get(f"/api/tunnels/{env.tid}/photos/{pid}", params={"w": 16})
        second = Image.open(io.BytesIO(r90.content)).size
        # w 參數語意＝目標寬度；旋轉後為直式 → (16, 較高)
        assert second[0] == 16 and second[1] > second[0] and second != first

    def test_photo_override_wins_over_camera(self, env):
        win = _window(env, 0)
        pid = win[0]["photos"][0]["photo_id"]
        env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"rotation": 90})

        r = env.put(f"/api/tunnels/{env.tid}/photos/{pid}/rotation", json={"angle": 180})
        assert r.status_code == 200
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        override = next(p for p in info["rotation_overrides"] if p["photo_id"] == pid)
        assert override["angle"] == 180

    def test_invalid_angle_rejected(self, env):
        win = _window(env, 0)
        pid = win[0]["photos"][0]["photo_id"]
        assert env.put(f"/api/tunnels/{env.tid}/photos/{pid}/rotation", json={"angle": 45}).status_code == 400
        assert env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"rotation": 33}).status_code == 400


class TestInfoPanel:
    def test_info_aggregates_everything(self, env):
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert info["name"] == "R1隧道"
        assert info["report"]["tolerance_seconds"] == 2.0
        assert len(info["report"]["cameras"]) == 2
        assert info["cameras"][0]["rotation"] == 0
        assert isinstance(info["manual_missing"], list)
        assert isinstance(info["rotation_overrides"], list)
        assert isinstance(info["dangling_anchors"], list)

    def test_import_records_dimensions_for_anomaly_detection(self, env):
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert info["report"]["aspect_anomalies"] == []
