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

"""錨點模型 v2：錨點綁定載體照片，群組由照片即時解析。

解析鏈：carrier_photo_id → photos.group_id → photo_groups.seq。
載體未連結任何群組（整組被改判缺照）時，退回時間最近群組並標記失準。
"""

from __future__ import annotations

import sqlite3

from .db import SCHEMA_VERSION, migrate_if_needed  # noqa: F401 (再輸出供測試縫使用)


def carrier_photo_for_group(conn: sqlite3.Connection, group_seq: int) -> int | None:
    """指定 seq 的群組中，第一台（camera_seq 順序）有影像且未被改判相機的照片 id。"""
    row = conn.execute(
        "SELECT p.id FROM photos p "
        "JOIN cameras c ON c.id = p.camera_id "
        "JOIN photo_groups g ON g.id = p.group_id "
        "WHERE g.seq = ? AND COALESCE(p.manual_missing, 0) = 0 "
        "ORDER BY c.seq LIMIT 1",
        (group_seq,),
    ).fetchone()
    return row["id"] if row else None


def resolve_anchor_seq(conn: sqlite3.Connection, carrier_photo_id: int) -> tuple[int | None, bool]:
    """回傳 (解析到的群組 seq, 是否失準)。"""
    row = conn.execute(
        "SELECT exif_time, group_id FROM photos WHERE id = ?",
        (carrier_photo_id,),
    ).fetchone()
    if row is None:
        return None, True
    if row["group_id"] is not None:
        grp = conn.execute("SELECT seq FROM photo_groups WHERE id = ?", (row["group_id"],)).fetchone()
        if grp is not None:
            return grp["seq"], False
    best = conn.execute(
        "SELECT seq FROM photo_groups "
        "ORDER BY ABS(julianday(corrected_time) - julianday(?)) ASC, seq LIMIT 1",
        (row["exif_time"],),
    ).fetchone()
    return (best["seq"] if best else None), True


def mark_missing_with_transfer(conn: sqlite3.Connection, photo_id: int) -> bool:
    """改判缺照：unlink 群組；若該照片是錨點載體則先轉移給同群組下一台。

    回傳是否確實處理了照片（不存在回 False）。
    """
    with conn:
        photo = conn.execute(
            "SELECT group_id FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
        if photo is None:
            return False
        next_carrier = None
        if photo["group_id"] is not None:
            nxt = conn.execute(
                "SELECT p.id FROM photos p JOIN cameras c ON c.id = p.camera_id "
                "WHERE p.group_id = ? AND p.id != ? AND COALESCE(p.manual_missing, 0) = 0 "
                "ORDER BY c.seq LIMIT 1",
                (photo["group_id"], photo_id),
            ).fetchone()
            next_carrier = nxt["id"] if nxt else None
        if next_carrier is not None:
            conn.execute(
                "UPDATE anchors SET carrier_photo_id = ?, updated_at = datetime('now') "
                "WHERE carrier_photo_id = ?",
                (next_carrier, photo_id),
            )
        conn.execute(
            "UPDATE photos SET manual_missing = 1, group_id = NULL WHERE id = ?",
            (photo_id,),
        )
        _recompute_missing_counts(conn)
    return True


def restore_photo(conn: sqlite3.Connection, photo_id: int) -> bool:
    """復原改判缺照：指派回時間最近的現存群組。"""
    with conn:
        row = conn.execute(
            "SELECT exif_time FROM photos WHERE id = ? AND manual_missing = 1", (photo_id,)
        ).fetchone()
        if row is None:
            return False
        target = conn.execute(
            "SELECT id FROM photo_groups "
            "ORDER BY ABS(julianday(corrected_time) - julianday(?)) ASC, seq LIMIT 1",
            (row["exif_time"],),
        ).fetchone()
        if target is None:
            return False
        conn.execute(
            "UPDATE photos SET manual_missing = 0, group_id = ? WHERE id = ?",
            (target["id"], photo_id),
        )
        _recompute_missing_counts(conn)
    return True


def set_anchor_on_group(conn: sqlite3.Connection, *, group_seq: int, mileage_m: int) -> int | None:
    """在指定群組建立／覆寫錨點，載體自動取第一台有影像的相機。回傳載體照片 id。"""
    carrier = carrier_photo_for_group(conn, group_seq)
    if carrier is None:
        return None
    with conn:
        conn.execute(
            "INSERT INTO anchors (carrier_photo_id, mileage_m) VALUES (?, ?) "
            "ON CONFLICT(carrier_photo_id) DO UPDATE SET mileage_m = excluded.mileage_m, updated_at = datetime('now')",
            (carrier, mileage_m),
        )
    return carrier


def anchor_for_group(conn: sqlite3.Connection, group_seq: int) -> dict | None:
    """若指定 seq 的群組已有錨點（經解析），回傳其內容。"""
    for item in list_anchors_resolved(conn):
        if item["group_seq"] == group_seq and not item["dangling"]:
            return item
    return None


def list_anchors_resolved(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT a.carrier_photo_id AS _pid, a.mileage_m AS mileage_m, "
        "c.name AS carrier_camera FROM anchors a JOIN photos p ON p.id = a.carrier_photo_id "
        "LEFT JOIN cameras c ON c.id = p.camera_id"
    ).fetchall()
    result = []
    for r in rows:
        seq, dangling = resolve_anchor_seq(conn, r["_pid"])
        result.append(
            {
                "_pid": r["_pid"],
                "group_seq": seq,
                "mileage_m": r["mileage_m"],
                "dangling": dangling,
                "carrier_camera": r["carrier_camera"],
            }
        )
    result.sort(key=lambda x: (x["group_seq"] is None, x["group_seq"]))
    return result


def _recompute_missing_counts(conn: sqlite3.Connection) -> None:
    """manual_missing 不占群組缺照數——以「機位總數 − 實際影像數」重算。"""
    conn.execute(
        "UPDATE photo_groups SET missing_count = ("
        "  SELECT (SELECT COUNT(*) FROM cameras) - COUNT(DISTINCT p.camera_id)"
        "  FROM photos p WHERE p.group_id = photo_groups.id)"
    )
