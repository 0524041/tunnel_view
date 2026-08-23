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

"""遷移併發安全與刪除隧道。"""

import sqlite3
import threading

from tunnelview.db import Workspace


def make_v1_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('tunnel_name', '舊');
        CREATE TABLE cameras (
            id INTEGER PRIMARY KEY, seq INTEGER UNIQUE, name TEXT, root_path TEXT,
            dt_offset_sec REAL DEFAULT 0, photo_count INTEGER DEFAULT 0);
        INSERT INTO cameras VALUES (1, 0, 'A', '/p', 0, 0);
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
        INSERT INTO anchors VALUES (1, 0, 777, 'x', 'x');
        """
    )
    conn.commit()
    conn.close()


class TestConcurrentMigration:
    def test_parallel_opens_do_not_collide(self, tmp_path):
        """多請求同時開啟 v1 資料庫：遷移必須序列化，不得 duplicate column。"""
        make_v1_db(tmp_path / "old.db")
        ws = Workspace(tmp_path)
        ws.init()
        with ws._connect(ws.index_path) as ic:
            ic.execute(
                "INSERT INTO tunnels (name, db_filename, start_m, end_m, camera_count) "
                "VALUES ('舊', 'old.db', 0, 300, 1)"
            )

        barrier = threading.Barrier(6)
        errors = []

        def opener():
            try:
                barrier.wait(timeout=5)
                conn = ws.open_tunnel(1)
                conn.execute("SELECT COUNT(*) FROM anchors").fetchone()
                conn.close()
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        threads = [threading.Thread(target=opener) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        conn = ws.open_tunnel(1)
        try:
            from tunnelview.anchor_model import SCHEMA_VERSION
            ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            assert ver == SCHEMA_VERSION
            mileage = conn.execute("SELECT mileage_m FROM anchors").fetchone()["mileage_m"]
            assert mileage == 777
        finally:
            conn.close()


class TestDeleteTunnel:
    def test_delete_removes_index_row_and_db_file(self, tmp_path):
        ws = Workspace(tmp_path)
        ws.init()
        rec = ws.create_tunnel(
            name="t",
            start_m=0,
            end_m=100,
            cameras=[{"name": "A", "root_path": "/p"}],
            tolerance_seconds=2.0,
        )
        assert (tmp_path / rec.db_filename).exists()

        ws.delete_tunnel(rec.tunnel_id)

        assert ws.list_tunnels() == []
        assert not (tmp_path / rec.db_filename).exists()
        assert not (tmp_path / f"{rec.db_filename}-wal").exists()

    def test_delete_unknown_raises(self, tmp_path):
        ws = Workspace(tmp_path)
        ws.init()
        import pytest

        with pytest.raises(KeyError):
            ws.delete_tunnel(999)
