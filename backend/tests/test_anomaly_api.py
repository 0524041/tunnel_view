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

"""修訂 R4 API 契約：異狀類型共用表、照片標註批次寫入、總覽查詢、遷移 v5。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tunnelview.api import create_app
from tunnelview.db import BUILTIN_DEFECT_TYPES, SCHEMA_VERSION, Workspace

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
    """兩機五事件隧道。"""
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
            "name": "R4隧道",
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


class TestDefectTypes:
    def test_builtin_seeded(self, env):
        types = env.get("/api/defect-types").json()
        names = [t["name"] for t in types]
        for builtin in BUILTIN_DEFECT_TYPES:
            assert builtin in names
        assert all(t["archived"] is False for t in types)

    def test_create_and_duplicate(self, env):
        r = env.post("/api/defect-types", json={"name": "施工縫滲水"})
        assert r.status_code == 200
        created = r.json()
        assert created["name"] == "施工縫滲水"

        r2 = env.post("/api/defect-types", json={"name": "施工縫滲水"})
        assert r2.status_code == 409

    def test_delete_unused_hard_deletes(self, env):
        created = env.post("/api/defect-types", json={"name": "暫用類型"}).json()
        r = env.delete(f"/api/defect-types/{created['id']}")
        assert r.status_code == 200
        assert r.json() == {"action": "deleted"}
        names = [t["name"] for t in env.get("/api/defect-types").json()]
        assert "暫用類型" not in names

    def test_delete_used_archives(self, env):
        crack = next(
            t for t in env.get("/api/defect-types").json() if t["name"] == "裂縫"
        )
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": crack["id"], "note": "縱向"}]},
        )
        assert r.status_code == 200

        r = env.delete(f"/api/defect-types/{crack['id']}")
        assert r.status_code == 200
        assert r.json() == {"action": "archived"}

        types = {t["id"]: t for t in env.get("/api/defect-types").json()}
        assert types[crack["id"]]["archived"] is True

        # 封存後既有紀錄仍正常顯示
        anno = env.get(f"/api/tunnels/{env.tid}/photos/{pid}/annotation").json()
        assert anno["items"][0]["type_name"] == "裂縫"


class TestAnnotation:
    def test_roundtrip_batch_replace(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}

        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={
                "note": "此處襯砌有明顯劣化",
                "items": [
                    {"type_id": types["裂縫"], "note": "縱向約 2m"},
                    {"type_id": types["滲漏水"], "note": None},
                ],
            },
        )
        assert r.status_code == 200
        saved = r.json()
        assert saved["note"] == "此處襯砌有明顯劣化"
        assert len(saved["items"]) == 2
        assert {i["type_name"] for i in saved["items"]} == {"裂縫", "滲漏水"}
        first_item_id = saved["items"][0]["id"]

        # 整批取代：留一刪一加一；保留既有 id 的建立時間
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={
                "note": "更新備註",
                "items": [
                    {"id": first_item_id, "type_id": types["裂縫"], "note": "延長至 3m"},
                    {"type_id": types["白華"], "note": None},
                ],
            },
        )
        assert r.status_code == 200
        saved2 = r.json()
        assert [i["type_name"] for i in saved2["items"]] == ["裂縫", "白華"]
        kept = next(i for i in saved2["items"] if i["id"] == first_item_id)
        original_created = next(i for i in saved["items"] if i["id"] == first_item_id)["created_at"]
        assert kept["created_at"] == original_created
        assert kept["note"] == "延長至 3m"

    def test_unknown_type_rejected(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": 99999}]},
        )
        assert r.status_code == 400

    def test_missing_photo_404(self, env):
        r = env.get(f"/api/tunnels/{env.tid}/photos/999999/annotation")
        assert r.status_code == 404


class TestAnomalyOverview:
    def test_overview_and_filters(self, env):
        win = _window(env, 1)
        pid1 = win[1]["photos"][0]["photo_id"]
        pid2 = win[2]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid1}/annotation",
            json={"note": "群組1備註", "items": [{"type_id": types["裂縫"], "note": "關鍵字甲"}]},
        )
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid2}/annotation",
            json={"note": None, "items": [{"type_id": types["滲漏水"], "note": "關鍵字乙"}]},
        )

        rows = env.get(f"/api/tunnels/{env.tid}/anomalies").json()
        assert len(rows) == 2
        ests = [r["est_mileage_m"] for r in rows]
        assert ests == sorted(ests)
        assert all({"anomaly_id", "photo_id", "rel_path", "camera_name", "group_seq", "type_name"} <= set(r) for r in rows)

        rows_desc = env.get(
            f"/api/tunnels/{env.tid}/anomalies", params={"order": "desc"}
        ).json()
        assert [r["est_mileage_m"] for r in rows_desc] == sorted(ests, reverse=True)

        rows_type = env.get(
            f"/api/tunnels/{env.tid}/anomalies", params={"type_id": str(types["裂縫"])}
        ).json()
        assert len(rows_type) == 1
        assert rows_type[0]["type_name"] == "裂縫"

        rows_q = env.get(f"/api/tunnels/{env.tid}/anomalies", params={"q": "關鍵字乙"}).json()
        assert len(rows_q) == 1

        rows_notephoto = env.get(f"/api/tunnels/{env.tid}/anomalies", params={"q": "群組1備註"}).json()
        assert len(rows_notephoto) == 1

    def test_manual_missing_excluded_everywhere(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": types["裂縫"], "note": None}]},
        )
        overview = env.get(f"/api/tunnels/{env.tid}/overview").json()
        seqs = overview["groups"]["seq"]
        ano = dict(zip(seqs, overview["groups"]["ano"]))
        assert any(v > 0 for v in ano.values())

        env.post(f"/api/tunnels/{env.tid}/photos/{pid}/mark_missing")

        overview2 = env.get(f"/api/tunnels/{env.tid}/overview").json()
        ano2 = dict(zip(overview2["groups"]["seq"], overview2["groups"]["ano"]))
        assert all(v == 0 for v in ano2.values())
        assert env.get(f"/api/tunnels/{env.tid}/anomalies").json() == []

    def test_invalid_params(self, env):
        assert (
            env.get(f"/api/tunnels/{env.tid}/anomalies", params={"order": "x"}).status_code
            == 400
        )
        assert (
            env.get(f"/api/tunnels/{env.tid}/anomalies", params={"type_id": "abc"}).status_code
            == 400
        )


class TestCameraRename:
    def test_rename_camera(self, env):
        r = env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"name": "頂拱左"})
        assert r.status_code == 200
        info = env.get(f"/api/tunnels/{env.tid}/info").json()
        assert info["cameras"][0]["name"] == "頂拱左"

        r = env.put(f"/api/tunnels/{env.tid}/cameras/0", json={"name": "   "})
        assert r.status_code == 400

        r = env.put(f"/api/tunnels/{env.tid}/cameras/999", json={"name": "不存在"})
        assert r.status_code == 404


class TestReviewRemoved:
    def test_review_endpoints_gone(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        # 端點已移除；StaticFiles mount 使未匹配路徑回 405，兩者皆代表不存在
        assert (
            env.post(
                f"/api/tunnels/{env.tid}/photos/{pid}/review", json={"result": "ok"}
            ).status_code
            in (404, 405)
        )
        assert (
            env.post(f"/api/tunnels/{env.tid}/photos/{pid}/reset_review").status_code
            in (404, 405)
        )
        assert (
            env.post(f"/api/tunnels/{env.tid}/photos/{pid}/confirm_flag").status_code
            in (404, 405)
        )


class TestMigrationV5:
    def test_version_and_columns(self, env):
        import os
        import sqlite3

        db_file = next(f for f in os.listdir(env.ws_root) if f.endswith(".db") and f != "index.db")
        conn = sqlite3.connect(str(env.ws_root / db_file))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        conn.close()
        assert version == SCHEMA_VERSION == "7"
        assert "note" in cols
        assert "photo_anomalies" in tables

    def test_v4_db_upgrades_and_reopens_idempotently(self, env, tmp_path):
        """模擬 v4 舊庫（無 note/photo_anomalies）開啟自動升級；重複遷移不變。"""
        import os
        import sqlite3

        ws = env.ws_root
        db_file = next(f for f in os.listdir(ws) if f.endswith(".db") and f != "index.db")
        conn = sqlite3.connect(str(ws / db_file))
        conn.execute("ALTER TABLE photos DROP COLUMN note")
        conn.execute("DROP TABLE photo_anomalies")
        conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        conn.commit()
        conn.close()

        tid = env.tid
        c1 = env.ws_root  # 透過 API 觸發 open_tunnel → migrate
        assert c1 is not None
        r = env.get(f"/api/tunnels/{tid}/overview")
        assert r.status_code == 200

        conn = sqlite3.connect(str(ws / db_file))
        cols = {x[1] for x in conn.execute("PRAGMA table_info(photos)")}
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        conn.close()
        assert version == "7"
        assert "note" in cols

        # 冪等：再次開啟不改變版本與資料
        overview_before = env.get(f"/api/tunnels/{tid}/overview").json()
        env.get(f"/api/tunnels/{tid}/overview")
        overview_after = env.get(f"/api/tunnels/{tid}/overview").json()
        assert overview_after["group_count"] == overview_before["group_count"]


class TestAnomalyAbnormal:
    def test_missing_type_id_returns_422(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"note": "no type"}]},
        )
        assert r.status_code == 422
        body = r.json()
        assert isinstance(body["detail"], list)
        # 前端 handle 應能將其轉為可讀字串而非 [object Object]
        assert any("type_id" in str(d.get("loc", "")) for d in body["detail"])

    def test_invalid_type_id_string_returns_422(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": "abc", "note": "x"}]},
        )
        assert r.status_code == 422

    def test_valid_archived_type_usable_for_existing(self, env):
        # 已封存的類型仍可被舊紀錄沿用（編輯時保留）
        crack = next(t for t in env.get("/api/defect-types").json() if t["name"] == "裂縫")
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": crack["id"]}]},
        )
        env.delete(f"/api/defect-types/{crack['id']}")  # 封存
        # 以封存類型再次儲存（模擬編輯舊紀錄不換類型）
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": crack["id"], "note": "保留封存"}]},
        )
        assert r.status_code == 200
        assert r.json()["items"][0]["type_name"] == "裂縫"

    def test_duplicate_type_ids_in_same_save(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        r = env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [
                {"type_id": types["裂縫"]},
                {"type_id": types["裂縫"], "note": "重複"},
            ]},
        )
        assert r.status_code == 200
        assert len(r.json()["items"]) == 2

    def test_window_returns_anomaly_types(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": types["白華"]}]},
        )
        w = _window(env, 1)
        photo = next(p for p in w[1]["photos"] if p["photo_id"] == pid)
        assert "anomaly_types" in photo
        assert "白華" in photo["anomaly_types"]

    def test_overview_keeps_type_id_for_counts(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": types["剝落"]}]},
        )
        rows = env.get(f"/api/tunnels/{env.tid}/anomalies").json()
        assert any("type_id" in r for r in rows)
        assert any(r["type_id"] == types["剝落"] for r in rows)


class TestAnomalyExport:
    def test_export_csv_contains_headers_and_paths(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": "照片備註", "items": [{"type_id": types["鋼筋外露"], "note": "異狀備註"}]},
        )
        r = env.get(f"/api/tunnels/{env.tid}/anomalies/export", params={"format": "csv"})
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        text = r.content.decode("utf-8-sig")
        assert "序號" in text and "完整路徑" in text
        assert "鋼筋外露" in text
        assert "照片備註" in text or "異狀備註" in text
        # 路徑與檔名欄位
        assert ".JPG" in text or ".jpg" in text

    def test_export_xlsx_valid_zip(self, env):
        win = _window(env, 1)
        pid = win[1]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(
            f"/api/tunnels/{env.tid}/photos/{pid}/annotation",
            json={"note": None, "items": [{"type_id": types["裂縫"]}]},
        )
        r = env.get(f"/api/tunnels/{env.tid}/anomalies/export", params={"format": "xlsx"})
        assert r.status_code == 200
        assert "application/vnd.openxmlformats" in r.headers["content-type"]
        # xlsx 為 zip 開頭 PK
        assert r.content[:2] == b"PK"
        assert 'filename' in r.headers["content-disposition"]

    def test_export_respects_filters(self, env):
        win = _window(env, 1)
        pid1 = win[1]["photos"][0]["photo_id"]
        pid2 = win[2]["photos"][0]["photo_id"]
        types = {t["name"]: t["id"] for t in env.get("/api/defect-types").json()}
        env.put(f"/api/tunnels/{env.tid}/photos/{pid1}/annotation", json={"note": None, "items": [{"type_id": types["裂縫"]}]})
        env.put(f"/api/tunnels/{env.tid}/photos/{pid2}/annotation", json={"note": None, "items": [{"type_id": types["滲漏水"]}]})
        r_all = env.get(f"/api/tunnels/{env.tid}/anomalies/export", params={"format": "csv"})
        r_one = env.get(f"/api/tunnels/{env.tid}/anomalies/export", params={"format": "csv", "type_id": str(types["裂縫"])})
        assert r_all.content.count(b"\n") > r_one.content.count(b"\n")
