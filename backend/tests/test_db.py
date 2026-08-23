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

"""工作區與隧道資料庫行為契約。

一個工作目錄 = index.db（隧道索引）+ N 個隧道 .db。
所有連線必須啟用 WAL 與外鍵約束。
"""

import sqlite3

import pytest

from tunnelview.db import Workspace


@pytest.fixture()
def ws(tmp_path):
    w = Workspace(tmp_path)
    w.init()
    return w


CAMERAS = [
    {"name": "Cam1_拱頂左", "root_path": "/photos/cam1"},
    {"name": "Cam2_拱頂右", "root_path": "/photos/cam2"},
]


class TestIndex:
    def test_init_creates_index_db_idempotent(self, tmp_path):
        w1 = Workspace(tmp_path)
        w1.init()
        w2 = Workspace(tmp_path)
        w2.init()
        assert (tmp_path / "index.db").exists()

    def test_empty_workspace_lists_nothing(self, ws):
        assert ws.list_tunnels() == []


class TestCreateTunnel:
    def test_create_returns_record_and_registers_in_index(self, ws):
        rec = ws.create_tunnel(
            name="八卦山西行",
            start_m=23000,
            end_m=24200,
            cameras=CAMERAS,
            tolerance_seconds=2.0,
        )
        tunnels = ws.list_tunnels()
        assert len(tunnels) == 1
        t = tunnels[0]
        assert t.name == "八卦山西行"
        assert t.start_m == 23000
        assert t.end_m == 24200
        assert t.camera_count == 2
        assert t.tunnel_id == rec.tunnel_id

    def test_tunnel_db_exists_with_wal_mode(self, ws, tmp_path):
        rec = ws.create_tunnel(
            name="t", start_m=0, end_m=1000, cameras=CAMERAS, tolerance_seconds=2.0
        )
        conn = ws.open_tunnel(rec.tunnel_id)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()

    def test_tunnel_schema_tables_exist(self, ws):
        rec = ws.create_tunnel(
            name="t", start_m=0, end_m=1000, cameras=CAMERAS, tolerance_seconds=2.0
        )
        conn = ws.open_tunnel(rec.tunnel_id)
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert {"cameras", "photos", "photo_groups", "anchors", "meta"} <= tables
        finally:
            conn.close()

    def test_camera_rows_written_with_offsets(self, ws):
        rec = ws.create_tunnel(
            name="t", start_m=0, end_m=1000, cameras=CAMERAS, tolerance_seconds=2.0
        )
        conn = ws.open_tunnel(rec.tunnel_id)
        try:
            rows = conn.execute("SELECT seq, name, root_path, dt_offset_sec FROM cameras ORDER BY seq").fetchall()
            assert [r[1] for r in rows] == ["Cam1_拱頂左", "Cam2_拱頂右"]
            assert rows[0][0] == 0
        finally:
            conn.close()

    def test_anchor_carrier_unique(self, ws):
        rec = ws.create_tunnel(
            name="t", start_m=0, end_m=1000, cameras=CAMERAS, tolerance_seconds=2.0
        )
        conn = ws.open_tunnel(rec.tunnel_id)
        try:
            conn.execute(
                "INSERT INTO photo_groups (seq, corrected_time, est_mileage_m, missing_count) VALUES (0, '2026-01-01T00:00:00', 0, 0)"
            )
            conn.execute(
                "INSERT INTO photos (camera_id, group_id, rel_path, exif_time, corrected_time, time_source) "
                "VALUES (1, 1, 'a.JPG', '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'exif')"
            )
            conn.execute("INSERT INTO anchors (carrier_photo_id, mileage_m) VALUES (1, 100)")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO anchors (carrier_photo_id, mileage_m) VALUES (1, 200)")
        finally:
            conn.close()

    def test_foreign_keys_enforced(self, ws):
        rec = ws.create_tunnel(
            name="t", start_m=0, end_m=1000, cameras=CAMERAS, tolerance_seconds=2.0
        )
        conn = ws.open_tunnel(rec.tunnel_id)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO photos (camera_id, group_id, rel_path, exif_time, corrected_time, time_source, flagged) "
                    "VALUES (99, NULL, 'x.JPG', '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'exif', 0)"
                )
        finally:
            conn.close()

    def test_open_unknown_tunnel_raises(self, ws):
        with pytest.raises(KeyError):
            ws.open_tunnel(999)
