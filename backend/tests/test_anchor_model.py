"""錨點模型 v2 行為契約：Schema 升級、遷移、解析鏈。

v2 語意：錨點 = 載體照片 + 里程絕對值；群組由照片即時解析。
"""

import sqlite3

import pytest

from tunnelview.db import Workspace
from tunnelview.anchor_model import (
    SCHEMA_VERSION,
    carrier_photo_for_group,
    list_anchors_resolved,
    mark_missing_with_transfer,
    migrate_if_needed,
    resolve_anchor_seq,
    set_anchor_on_group,
)


def make_v2_workspace(tmp_path):
    ws = Workspace(tmp_path)
    ws.init()
    return ws


def seed_grouped_tunnel(ws, camera_names=("A", "B")):
    """建立隧道並塞 3 群、每群兩機各一張（回傳 tunnel_id）。"""
    info = ws.create_tunnel(
        name="t",
        start_m=0,
        end_m=300,
        cameras=[{"name": n, "root_path": f"/p/{n}"} for n in camera_names],
        tolerance_seconds=2.0,
    )
    conn = ws.open_tunnel(info.tunnel_id)
    with conn:
        for seq in range(3):
            conn.execute(
                "INSERT INTO photo_groups (seq, corrected_time, est_mileage_m, missing_count) "
                "VALUES (?, ?, ?, ?)",
                (seq, f"2026-01-0{seq + 1}T00:00:00", seq * 100 + 50, 0),
            )
        for cam_seq in range(len(camera_names)):
            for seq in range(3):
                conn.execute(
                    "INSERT INTO photos (camera_id, group_id, rel_path, exif_time, corrected_time, time_source) "
                    "VALUES (?, ?, ?, ?, ?, 'exif')",
                    (
                        cam_seq + 1,
                        seq + 1,
                        f"c{cam_seq}_g{seq}.JPG",
                        f"2026-01-0{seq + 1}T00:00:0{cam_seq}",
                        f"2026-01-0{seq + 1}T00:00:0{cam_seq}",
                    ),
                )
    return info


class TestSchemaV2:
    def test_new_tunnel_has_v2_schema(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)

        conn = ws.open_tunnel(info.tunnel_id)
        try:
            ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            assert ver is not None and ver[0] == SCHEMA_VERSION
            anchor_cols = {r[1] for r in conn.execute("PRAGMA table_info(anchors)")}
            assert "carrier_photo_id" in anchor_cols and "group_seq" not in anchor_cols
            photo_cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
            assert {"width", "height", "manual_missing", "rotation_override"} <= photo_cols
            cam_cols = {r[1] for r in conn.execute("PRAGMA table_info(cameras)")}
            assert "rotation" in cam_cols
        finally:
            conn.close()

    def test_v1_database_auto_migrates(self, tmp_path):
        """舊版 v1 結構開啟時自動升級，錨點指定群組第一張照片為載體。"""
        db_path = tmp_path / "old_tunnel.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('tunnel_name', '舊隧道');
            CREATE TABLE cameras (
                id INTEGER PRIMARY KEY, seq INTEGER UNIQUE, name TEXT, root_path TEXT,
                dt_offset_sec REAL DEFAULT 0, photo_count INTEGER DEFAULT 0);
            INSERT INTO cameras VALUES (1, 0, 'A', '/p/A', 0, 0);
            CREATE TABLE photo_groups (
                id INTEGER PRIMARY KEY, seq INTEGER UNIQUE, corrected_time TEXT,
                est_mileage_m INTEGER, missing_count INTEGER DEFAULT 0);
            INSERT INTO photo_groups VALUES (10, 0, '2026-01-01T00:00:00', 50, 0);
            CREATE TABLE photos (
                id INTEGER PRIMARY KEY, camera_id INT, group_id INT, rel_path TEXT,
                exif_time TEXT, corrected_time TEXT, time_source TEXT, flagged INT DEFAULT 0);
            INSERT INTO photos VALUES (100, 1, 10, 'x.JPG', '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'exif', 0);
            CREATE TABLE anchors (
                id INTEGER PRIMARY KEY, group_seq INTEGER UNIQUE REFERENCES photo_groups(seq),
                mileage_m INTEGER, created_at TEXT, updated_at TEXT);
            INSERT INTO anchors VALUES (1, 0, 123, '2026-01-01', '2026-01-01');
            """
        )
        conn.commit()
        conn.close()

        ws = make_v2_workspace(tmp_path)
        # 直接以檔名註冊進 index 後開啟觸發遷移
        with ws._connect(ws.index_path) as ic:
            ic.execute(
                "INSERT INTO tunnels (name, db_filename, start_m, end_m, camera_count) "
                "VALUES ('舊隧道', 'old_tunnel.db', 0, 300, 1)"
            )
        conn = ws.open_tunnel(1)
        try:
            ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            assert ver == SCHEMA_VERSION
            row = conn.execute("SELECT carrier_photo_id, mileage_m FROM anchors").fetchone()
            assert row["carrier_photo_id"] == 100
            assert row["mileage_m"] == 123
            seq, dangling = resolve_anchor_seq(conn, row["carrier_photo_id"])
            assert (seq, dangling) == (0, False)
        finally:
            conn.close()


class TestResolutionChain:
    def test_carrier_resolves_to_its_group(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            carrier = carrier_photo_for_group(conn, group_seq=1)
            assert carrier is not None
            seq, dangling = resolve_anchor_seq(conn, carrier)
            assert (seq, dangling) == (1, False)
        finally:
            conn.close()

    def test_unlinked_carrier_falls_back_to_nearest_group_by_time(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            # 群組 2 的載體被 unlink（模擬整組改判缺照）
            conn.execute(
                "UPDATE photos SET group_id=NULL WHERE id=(SELECT id FROM photos WHERE group_id=2 ORDER BY camera_id LIMIT 1)"
            )
            orphan = conn.execute(
                "SELECT id FROM photos WHERE group_id IS NULL"
            ).fetchone()["id"]
            seq, dangling = resolve_anchor_seq(conn, orphan)
            assert dangling is True
            assert seq in (1, 2)
        finally:
            conn.close()


class TestMarkMissingTransfer:
    def test_mark_missing_transfers_carrier_to_next_camera(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            set_anchor_on_group(conn, group_seq=0, mileage_m=42)
            original = conn.execute("SELECT carrier_photo_id FROM anchors").fetchone()["carrier_photo_id"]

            ok = mark_missing_with_transfer(conn, photo_id=original)
            assert ok is True

            row = conn.execute("SELECT carrier_photo_id FROM anchors").fetchone()
            assert row["carrier_photo_id"] != original
            left = conn.execute("SELECT manual_missing FROM photos WHERE id=?", (original,)).fetchone()
            assert left["manual_missing"] == 1
            new_seq, dangling = resolve_anchor_seq(conn, row["carrier_photo_id"])
            assert (new_seq, dangling) == (0, False)
        finally:
            conn.close()

    def test_mark_missing_without_anchor_still_unlinks(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            gid_of_seq2 = conn.execute("SELECT id FROM photo_groups WHERE seq=2").fetchone()["id"]
            victim = carrier_photo_for_group(conn, 2)
            ok = mark_missing_with_transfer(conn, photo_id=victim)
            assert ok is True
            row = conn.execute("SELECT manual_missing, group_id FROM photos WHERE id=?", (victim,)).fetchone()
            assert row["manual_missing"] == 1 and row["group_id"] is None
            rest = conn.execute(
                "SELECT COUNT(*) AS n FROM photos WHERE group_id=?", (gid_of_seq2,)
            ).fetchone()["n"]
            assert rest == 1
        finally:
            conn.close()


class TestSetAndListAnchorsV2:
    def test_set_anchor_picks_first_available_carrier(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            set_anchor_on_group(conn, group_seq=1, mileage_m=150)
            listing = [
                {k: v for k, v in a.items() if not k.startswith("_")}
                for a in list_anchors_resolved(conn)
            ]
            assert listing == [
                {
                    "group_seq": 1,
                    "mileage_m": 150,
                    "dangling": False,
                    "carrier_camera": "A",
                }
            ]
        finally:
            conn.close()

    def test_edit_existing_anchor_by_resolved_group(self, tmp_path):
        ws = make_v2_workspace(tmp_path)
        info = seed_grouped_tunnel(ws)
        conn = ws.open_tunnel(info.tunnel_id)
        try:
            set_anchor_on_group(conn, group_seq=1, mileage_m=150)
            set_anchor_on_group(conn, group_seq=1, mileage_m=160)
            rows = conn.execute("SELECT COUNT(*) AS n FROM anchors").fetchone()["n"]
            assert rows == 1
            assert list_anchors_resolved(conn)[0]["mileage_m"] == 160
        finally:
            conn.close()
