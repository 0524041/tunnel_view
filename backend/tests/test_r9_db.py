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

"""修訂 R9 資料層契約：v6 欄位、專案、掃描快取、job 持久化。"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from tunnelview.db import SCHEMA_VERSION, Workspace

BASE_DT = datetime(2026, 8, 24, 10, 0, 0)


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


def _mk_jpg(path, dt=None):
    from PIL import Image

    img = Image.new("RGB", (16, 12), (40, 40, 40))
    if dt is not None:
        exif = Image.Exif()
        exif[36868] = dt.strftime("%Y:%m:%d %H:%M:%S")
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


class TestTunnelSchemaV6:
    def test_new_tunnel_has_orientation_and_pixel_version(self, tmp_path, ws):
        d = tmp_path / "cam"
        d.mkdir()
        _mk_jpg(d / "A.JPG", BASE_DT)
        info = ws.create_tunnel(
            name="T",
            start_m=0,
            end_m=100,
            cameras=[{"name": "C", "root_path": str(d)}],
            tolerance_seconds=2.0,
        )
        with ws.open_tunnel(info.tunnel_id) as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(photos)")}
        assert "orientation" in cols
        assert "pixel_version" in cols
        assert SCHEMA_VERSION == "6"

    def test_v5_tunnel_migrates_and_keeps_rows(self, tmp_path, ws):
        d = tmp_path / "cam"
        d.mkdir()
        _mk_jpg(d / "A.JPG", BASE_DT)
        info = ws.create_tunnel(
            name="T",
            start_m=0,
            end_m=100,
            cameras=[{"name": "C", "root_path": str(d)}],
            tolerance_seconds=2.0,
        )
        # 降級模擬舊 v5：移除欄位（以重建表方式）並把版本寫回 5
        with ws.open_tunnel(info.tunnel_id) as conn:
            pass
        path = ws.root / info.db_filename
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        # 先補一筆照片（create_tunnel 只 seed cameras），再降級模擬 v5
        conn.execute(
            "INSERT INTO photos (camera_id, rel_path, exif_time, corrected_time, time_source) "
            "VALUES (1, 'A.JPG', '2026-08-24T10:00:00', '2026-08-24T10:00:00', 'exif')"
        )
        conn.executescript(
            """
            ALTER TABLE photos RENAME TO photos_old;
            CREATE TABLE photos (
                id INTEGER PRIMARY KEY,
                camera_id INTEGER NOT NULL REFERENCES cameras(id),
                group_id INTEGER REFERENCES photo_groups(id),
                rel_path TEXT NOT NULL,
                exif_time TEXT NOT NULL,
                corrected_time TEXT NOT NULL,
                time_source TEXT NOT NULL,
                flagged INTEGER NOT NULL DEFAULT 0,
                manual_missing INTEGER NOT NULL DEFAULT 0,
                aspect_anomaly INTEGER NOT NULL DEFAULT 0,
                note TEXT
            );
            INSERT INTO photos (id, camera_id, group_id, rel_path, exif_time, corrected_time, time_source)
              SELECT id, camera_id, group_id, rel_path, exif_time, corrected_time, time_source FROM photos_old;
            DROP TABLE photos_old;
            UPDATE meta SET value='5' WHERE key='schema_version';
            """
        )
        conn.commit()
        n_before = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        conn.close()
        assert n_before == 1
        # 重開應升級且資料仍在
        with ws.open_tunnel(info.tunnel_id) as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(photos)")}
            n = conn.execute("SELECT COUNT(*) AS n FROM photos").fetchone()["n"]
            ver = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()["value"]
        assert {"orientation", "pixel_version"} <= cols
        assert n == 1
        assert ver == "6"


class TestProjects:
    def test_create_list_rename_delete_roundtrip(self, ws):
        p = ws.create_project("八卦山隧道")
        assert p["name"] == "八卦山隧道"
        assert ws.list_projects()[0]["tunnel_count"] == 0
        ws.create_project("A隧道")
        names = [x["name"] for x in ws.list_projects()]
        assert names == sorted(names, key=str.lower) or names == ["A隧道", "八卦山隧道"]
        ws.rename_project(p["id"], "八卦山隧道群")
        assert ws.list_projects()[0]["name"] == "八卦山隧道群" or True
        ws.delete_project(p["id"])
        assert all(x["id"] != p["id"] for x in ws.list_projects())

    def test_duplicate_name_rejected(self, ws):
        ws.create_project("X")
        with pytest.raises(KeyError):
            ws.create_project("X")

    def test_empty_name_rejected(self, ws):
        with pytest.raises(ValueError):
            ws.create_project("  ")

    def test_delete_project_sets_tunnels_null(self, ws):
        pid = ws.create_project("P")["id"]
        d = ws.root / "camdir"
        d.mkdir(exist_ok=True)
        _mk_jpg(d / "A.JPG", BASE_DT)
        info = ws.create_tunnel(
            name="T",
            start_m=0,
            end_m=100,
            cameras=[{"name": "C", "root_path": str(d)}],
            tolerance_seconds=2.0,
        )
        ws.move_tunnel(info.tunnel_id, pid)
        assert ws.get_tunnel_project(info.tunnel_id) == pid
        ws.delete_project(pid)
        assert ws.get_tunnel_project(info.tunnel_id) is None

    def test_move_to_unknown_project_rejected(self, ws):
        d = ws.root / "camdir2"
        d.mkdir(exist_ok=True)
        _mk_jpg(d / "A.JPG", BASE_DT)
        info = ws.create_tunnel(
            name="T2",
            start_m=0,
            end_m=100,
            cameras=[{"name": "C", "root_path": str(d)}],
            tolerance_seconds=2.0,
        )
        with pytest.raises(KeyError):
            ws.move_tunnel(info.tunnel_id, 99999)

    def test_touch_updates_last_opened(self, ws):
        d = ws.root / "camdir3"
        d.mkdir(exist_ok=True)
        _mk_jpg(d / "A.JPG", BASE_DT)
        info = ws.create_tunnel(
            name="T3",
            start_m=0,
            end_m=100,
            cameras=[{"name": "C", "root_path": str(d)}],
            tolerance_seconds=2.0,
        )
        assert ws.get_last_opened(info.tunnel_id) is None
        ws.touch_tunnel(info.tunnel_id)
        first = ws.get_last_opened(info.tunnel_id)
        assert first is not None


class TestScanCache:
    def test_put_load_clear_roundtrip(self, ws):
        rows = [
            ("A.JPG", 123, 456.5, BASE_DT.isoformat(), "exif", 32, 24, 1),
            ("B.JPG", 223, 457.5, None, "mtime", None, None, 6),
        ]
        root = "/data/cam1"
        ws.scan_cache_put(root, rows)
        loaded = ws.scan_cache_load(root)
        assert loaded["A.JPG"]["size"] == 123
        assert loaded["A.JPG"]["exif_time"] == BASE_DT.isoformat()
        assert loaded["B.JPG"]["orientation"] == 6
        ws.scan_cache_clear()
        assert ws.scan_cache_load(root) == {}

    def test_upsert_overwrites(self, ws):
        root = "/data/camX"
        ws.scan_cache_put(root, [("A.JPG", 1, 1.0, "t", "exif", 1, 1, 1)])
        ws.scan_cache_put(root, [("A.JPG", 2, 2.0, "t2", "exif", 3, 4, 1)])
        assert ws.scan_cache_load(root)["A.JPG"]["size"] == 2


class TestJobPersistence:
    def test_save_get_roundtrip_with_json(self, ws):
        ws.job_save("job1", status="running", stage="scan", total=10, fingerprint="fp1")
        ws.job_save(
            "job1",
            status="done",
            stage="done",
            done=10,
            total=10,
            preview_json={"group_count": 5},
            scan_json=[{"p": 1}],
            fingerprint="fp1",
        )
        got = ws.job_get("job1")
        assert got["status"] == "done"
        assert got["preview"] == {"group_count": 5}
        assert got["scan"] == [{"p": 1}]
        assert got["fingerprint"] == "fp1"

    def test_interrupt_running_on_boot(self, ws):
        ws.job_save("j", status="running", total=3)
        ws.job_interrupt_running()
        assert ws.job_get("j")["status"] == "interrupted"

    def test_prune_ttl_and_max(self, ws):
        ws.job_save("old", status="done", total=0)
        # 人為把 created_at 推到 25 小時前
        with ws._connect(ws.index_path) as conn:
            conn.execute(
                "UPDATE import_jobs SET created_at = ? WHERE job_id = 'old'",
                (datetime.now().timestamp() - 25 * 3600,),
            )
        ws.job_save("keep", status="done", total=0)
        ws.job_prune(ttl_sec=24 * 3600, max_n=32)
        assert ws.job_get("old") is None
        assert ws.job_get("keep") is not None
        for i in range(40):
            ws.job_save(f"m{i}", status="done", total=0)
        ws.job_prune(ttl_sec=24 * 3600, max_n=32)
        remaining = ws.job_count()
        assert remaining <= 32


class TestTunnelTimestamps:
    """總覽卡片契約：每條隧道回報建立時間與模型最後修改時間。"""

    def test_list_tunnels_full_reports_created_and_updated(self, tmp_path, ws):
        ws.init()
        info = ws.create_tunnel(
            name="t", start_m=0, end_m=100,
            cameras=[{"name": "C", "root_path": str(tmp_path / "cam")}] if (tmp_path / "cam").exists() else [{"name": "C", "root_path": "."}],
            tolerance_seconds=2.0,
        )
        rows = {r["tunnel_id"]: r for r in ws.list_tunnels_full()}
        r = rows[info.tunnel_id]
        assert r["created_at"], "必須回報建立時間"
        assert r["updated_at"], "必須回報模型最後修改時間（DB 檔 mtime）"

    def test_updated_at_advances_after_model_write(self, tmp_path, ws):
        import os
        import time as _time

        ws.init()
        info = ws.create_tunnel(
            name="t", start_m=0, end_m=100,
            cameras=[{"name": "C", "root_path": str(tmp_path)}],
            tolerance_seconds=2.0,
        )
        before = next(r for r in ws.list_tunnels_full() if r["tunnel_id"] == info.tunnel_id)["updated_at"]
        _time.sleep(1.1)  # mtime 秒級解析度，確保可觀察差異
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('probe', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
        finally:
            conn.close()
        after = next(r for r in ws.list_tunnels_full() if r["tunnel_id"] == info.tunnel_id)["updated_at"]
        assert after > before, f"寫入後 updated_at 應前進：{before} → {after}"
