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

"""工作區資料層：index.db 索引 + 一隧道一 SQLite 檔。

所有連線啟用 WAL（讀寫不互斥）與外鍵約束。
照片以「相機根路徑 + 相對路徑」引用，不複製原檔。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = "6"

# 全工作區共用的異狀類型（跨隧道專案）
BUILTIN_DEFECT_TYPES = ("裂縫", "滲漏水", "剝落", "白華", "鋼筋外露")

_SCHEMA_TUNNEL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    dt_offset_sec REAL NOT NULL DEFAULT 0.0,
    photo_count INTEGER NOT NULL DEFAULT 0,
    rotation INTEGER NOT NULL DEFAULT 0 CHECK (rotation IN (0, 90, 180, 270)),
    grid_pos INTEGER NOT NULL DEFAULT -1
);

CREATE TABLE IF NOT EXISTS photo_groups (
    id INTEGER PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    corrected_time TEXT NOT NULL,
    est_mileage_m INTEGER NOT NULL,
    missing_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_groups_mileage ON photo_groups(est_mileage_m);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    camera_id INTEGER NOT NULL REFERENCES cameras(id),
    group_id INTEGER REFERENCES photo_groups(id),
    rel_path TEXT NOT NULL,
    exif_time TEXT NOT NULL,
    corrected_time TEXT NOT NULL,
    time_source TEXT NOT NULL CHECK (time_source IN ('exif', 'mtime')),
    flagged INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    manual_missing INTEGER NOT NULL DEFAULT 0,
    rotation_override INTEGER CHECK (rotation_override IN (0, 90, 180, 270)),
    review_result TEXT CHECK (review_result IN ('ok', 'anomaly')),
    aspect_anomaly INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    orientation INTEGER,
    pixel_version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_photos_group ON photos(group_id);
CREATE INDEX IF NOT EXISTS idx_photos_camera ON photos(camera_id);

CREATE TABLE IF NOT EXISTS anchors (
    id INTEGER PRIMARY KEY,
    carrier_photo_id INTEGER NOT NULL UNIQUE REFERENCES photos(id),
    mileage_m INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS photo_anomalies (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id),
    type_id INTEGER NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_anomalies_photo ON photo_anomalies(photo_id);
"""

_ANOMALIES_DDL = """
CREATE TABLE IF NOT EXISTS photo_anomalies (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id),
    type_id INTEGER NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def migrate_if_needed(conn: sqlite3.Connection) -> None:
    """隧道 db 開啟時的冪等升級：v1（group_seq 綁定）→ v2（載體照片綁定）。

    以 BEGIN IMMEDIATE 序列化：檢視器會並行發出多個請求、各自開連線，
    沒有寫鎖時兩個連線會同時判定「欄位不存在」而互撞 duplicate column。
    """
    if _schema_version(conn) == SCHEMA_VERSION:
        return

    previous_isolation = conn.isolation_level
    conn.isolation_level = None  # 手動控制交易邊界
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _schema_version(conn) == SCHEMA_VERSION:
                conn.execute("COMMIT")
                return

            photo_cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
            if "manual_missing" not in photo_cols:
                conn.execute("ALTER TABLE photos ADD COLUMN manual_missing INTEGER NOT NULL DEFAULT 0")
            if "width" not in photo_cols:
                conn.execute("ALTER TABLE photos ADD COLUMN width INTEGER")
            if "height" not in photo_cols:
                conn.execute("ALTER TABLE photos ADD COLUMN height INTEGER")
            if "rotation_override" not in photo_cols:
                conn.execute(
                    "ALTER TABLE photos ADD COLUMN rotation_override "
                    "CHECK (rotation_override IN (0, 90, 180, 270))"
                )
            if "review_result" not in photo_cols:
                conn.execute(
                    "ALTER TABLE photos ADD COLUMN review_result TEXT "
                    "CHECK (review_result IN ('ok', 'anomaly'))"
                )
            if "aspect_anomaly" not in photo_cols:
                conn.execute("ALTER TABLE photos ADD COLUMN aspect_anomaly INTEGER NOT NULL DEFAULT 0")
            cam_cols = {r[1] for r in conn.execute("PRAGMA table_info(cameras)")}
            if "rotation" not in cam_cols:
                conn.execute(
                    "ALTER TABLE cameras ADD COLUMN rotation INTEGER NOT NULL DEFAULT 0 "
                    "CHECK (rotation IN (0, 90, 180, 270))"
                )
            anchor_cols = {r[1] for r in conn.execute("PRAGMA table_info(anchors)")}
            if anchor_cols and "carrier_photo_id" not in anchor_cols:
                _migrate_anchors_v1_to_v2(conn)
            elif not anchor_cols:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS anchors (
                        id INTEGER PRIMARY KEY,
                        carrier_photo_id INTEGER NOT NULL UNIQUE REFERENCES photos(id),
                        mileage_m INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
            cam_cols2 = {r[1] for r in conn.execute("PRAGMA table_info(cameras)")}
            if "grid_pos" not in cam_cols2:
                conn.execute("ALTER TABLE cameras ADD COLUMN grid_pos INTEGER NOT NULL DEFAULT -1")
                # 回填：舊資料以 seq 作為格位，保持既有順序
                conn.execute("UPDATE cameras SET grid_pos = seq WHERE grid_pos < 0")
            meta_keys = {r[0] for r in conn.execute("SELECT key FROM meta")}
            if "layout_cols" not in meta_keys:
                conn.execute("INSERT INTO meta (key, value) VALUES ('layout_cols', 'auto')")

            photo_cols2 = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
            if "note" not in photo_cols2:
                conn.execute("ALTER TABLE photos ADD COLUMN note TEXT")
            # v6：EXIF orientation 入庫（NULL=未知，首次 serve 時 lazy backfill）
            # 與像素版本（僅真正改變像素的操作遞增，供 immutable 縮圖快取失效）
            photo_cols3 = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
            if "orientation" not in photo_cols3:
                conn.execute("ALTER TABLE photos ADD COLUMN orientation INTEGER")
            if "pixel_version" not in photo_cols3:
                conn.execute(
                    "ALTER TABLE photos ADD COLUMN pixel_version INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(_ANOMALIES_DDL)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_anomalies_photo ON photo_anomalies(photo_id)"
            )

            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = previous_isolation


def _schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _migrate_anchors_v1_to_v2(conn: sqlite3.Connection) -> None:
    """舊錨點（group_seq 綁定）→ 載體照片綁定；載體＝該群組第一張照片。

    注意：不可用 executescript——它會隱式 COMMIT，拆毀外層 BEGIN IMMEDIATE 交易。
    """
    old_rows = conn.execute("SELECT group_seq, mileage_m FROM anchors").fetchall()
    conn.execute("ALTER TABLE anchors RENAME TO anchors_old")
    conn.execute(
        """
        CREATE TABLE anchors (
            id INTEGER PRIMARY KEY,
            carrier_photo_id INTEGER NOT NULL UNIQUE REFERENCES photos(id),
            mileage_m INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    for r in old_rows:
        carrier = conn.execute(
            "SELECT p.id FROM photos p JOIN cameras c ON c.id = p.camera_id "
            "WHERE p.group_id = (SELECT id FROM photo_groups WHERE seq = ?) "
            "ORDER BY c.seq LIMIT 1",
            (r["group_seq"],),
        ).fetchone()
        if carrier is not None:
            conn.execute(
                "INSERT INTO anchors (carrier_photo_id, mileage_m) VALUES (?, ?)",
                (carrier["id"], r["mileage_m"]),
            )
    conn.execute("DROP TABLE anchors_old")


@dataclass(frozen=True)
class TunnelInfo:
    tunnel_id: int
    name: str
    db_filename: str
    start_m: int
    end_m: int
    camera_count: int


class Workspace:
    """管理一個工作目錄下的 index.db 與各隧道 .db。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = threading.Lock()

    @property
    def index_path(self) -> Path:
        return self.root / "index.db"

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connect(self.index_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS tunnels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, db_filename TEXT NOT NULL UNIQUE, start_m INTEGER NOT NULL, end_m INTEGER NOT NULL, camera_count INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
            conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recent_paths (
                path TEXT PRIMARY KEY,
                used_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
            conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_home_tables(conn)
            self._ensure_defect_types(conn)

    @staticmethod
    def _ensure_home_tables(conn: sqlite3.Connection) -> None:
        """R9：專案歸檔、EXIF 掃描快取、匯入 job 持久化（冪等，既有/新工作區皆適用）。"""
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        tunnel_cols = {r[1] for r in conn.execute("PRAGMA table_info(tunnels)")}
        if "project_id" not in tunnel_cols:
            # 刪除專案時隧道回未分類（ON DELETE SET NULL 需預設 NULL）
            conn.execute(
                "ALTER TABLE tunnels ADD COLUMN project_id INTEGER "
                "REFERENCES projects(id) ON DELETE SET NULL"
            )
        if "last_opened_at" not in tunnel_cols:
            conn.execute("ALTER TABLE tunnels ADD COLUMN last_opened_at TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_cache (
                folder_root TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                exif_time TEXT,
                time_source TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                orientation INTEGER,
                PRIMARY KEY (folder_root, rel_path)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS import_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                preview_json TEXT,
                scan_json TEXT,
                error TEXT,
                fingerprint TEXT,
                created_at REAL NOT NULL
            )
            """
        )

    @staticmethod
    def _ensure_defect_types(conn: sqlite3.Connection) -> None:
        """共用異狀類型表＋內建種子（冪等，既有/新工作區皆適用）。"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_types (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.executemany(
            "INSERT OR IGNORE INTO defect_types (name) VALUES (?)",
            [(name,) for name in BUILTIN_DEFECT_TYPES],
        )

    def defect_types(self) -> list[dict]:
        with self._connect(self.index_path) as conn:
            self._ensure_defect_types(conn)
            rows = conn.execute(
                "SELECT id, name, archived FROM defect_types ORDER BY id"
            ).fetchall()
        return [{"id": r["id"], "name": r["name"], "archived": bool(r["archived"])} for r in rows]

    def add_defect_type(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("類型名稱不可空白")
        with self._connect(self.index_path) as conn:
            self._ensure_defect_types(conn)
            existing = conn.execute(
                "SELECT id, name FROM defect_types WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if existing is not None:
                raise KeyError(f"類型已存在：{existing['name']}")
            try:
                cur = conn.execute("INSERT INTO defect_types (name) VALUES (?)", (name,))
            except sqlite3.IntegrityError:
                raise KeyError(f"類型已存在：{name}")
            row = conn.execute(
                "SELECT id, name, archived FROM defect_types WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return {"id": row["id"], "name": row["name"], "archived": bool(row["archived"])}

    def remove_defect_type(self, type_id: int) -> str:
        """刪除共用類型：未被任何隧道異狀引用→硬刪；已被使用→封存。回傳動作字串。"""
        with self._connect(self.index_path) as conn:
            self._ensure_defect_types(conn)
            row = conn.execute(
                "SELECT id FROM defect_types WHERE id = ?", (type_id,)
            ).fetchone()
            if row is None:
                raise KeyError(type_id)
        in_use = False
        for t in self.list_tunnels():
            with self.open_tunnel(t.tunnel_id) as tconn:
                if tconn.execute(
                    "SELECT 1 FROM photo_anomalies WHERE type_id = ? LIMIT 1", (type_id,)
                ).fetchone():
                    in_use = True
                    break
        with self._connect(self.index_path) as conn:
            if in_use:
                conn.execute("UPDATE defect_types SET archived = 1 WHERE id = ?", (type_id,))
                return "archived"
            conn.execute("DELETE FROM defect_types WHERE id = ?", (type_id,))
        return "deleted"

    def _connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def list_tunnels(self) -> list[TunnelInfo]:
        if not self.index_path.exists():
            return []
        with self._connect(self.index_path) as conn:
            rows = conn.execute(
                "SELECT id, name, db_filename, start_m, end_m, camera_count FROM tunnels ORDER BY id"
            ).fetchall()
        return [TunnelInfo(*r) for r in rows]

    def list_tunnels_full(self) -> list[dict]:
        """首頁用完整欄位：含專案歸屬與最近開啟時間（R9）。"""
        if not self.index_path.exists():
            return []
        with self._connect(self.index_path) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT t.id AS tunnel_id, t.name, t.start_m, t.end_m, t.camera_count,
                           t.db_filename AS db_filename,
                           t.project_id AS project_id, p.name AS project_name,
                           t.last_opened_at AS last_opened_at,
                           t.created_at AS created_at
                    FROM tunnels t LEFT JOIN projects p ON p.id = t.project_id
                    ORDER BY t.id
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                return [
                    {
                        "tunnel_id": t.tunnel_id, "name": t.name,
                        "start_m": t.start_m, "end_m": t.end_m,
                        "camera_count": t.camera_count, "project_id": None,
                        "project_name": None, "last_opened_at": None, "created_at": None,
                    }
                    for t in self.list_tunnels()
                ]
        out = []
        for r in rows:
            d = dict(r)
            # 模型最後修改＝隧道 DB 檔（含 -wal）的 mtime 最大值：
            # 任何寫入（錨點/合併/realign/標記缺照…）都會反映，無需各端點逐一維護欄位
            mt = 0.0
            base = self.root / r["db_filename"]
            for suffix in ("", "-wal"):
                try:
                    mt = max(mt, Path(str(base) + suffix).stat().st_mtime)
                except OSError:
                    pass
            d["updated_at"] = (
                datetime.fromtimestamp(mt).isoformat(timespec="seconds") if mt else None
            )
            out.append(d)
        return out

    def create_tunnel(
        self,
        *,
        name: str,
        start_m: int,
        end_m: int,
        cameras: list[dict],
        tolerance_seconds: float,
        layout_cols: str | int = "auto",
    ) -> TunnelInfo:
        if not cameras:
            raise ValueError("至少需要一台相機")
        db_filename = f"tunnel_{uuid4().hex[:12]}.db"
        with self._lock, self._connect(self.index_path) as conn:
            cur = conn.execute(
                "INSERT INTO tunnels (name, db_filename, start_m, end_m, camera_count) VALUES (?, ?, ?, ?, ?)",
                (name, db_filename, start_m, end_m, len(cameras)),
            )
            tunnel_id = cur.lastrowid

        tunnel_path = self.root / db_filename
        with self._connect(tunnel_path) as tconn:
            tconn.executescript(_SCHEMA_TUNNEL)
            tconn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [
                    ("tunnel_name", name),
                    ("start_m", str(start_m)),
                    ("end_m", str(end_m)),
                    ("tolerance_seconds", str(tolerance_seconds)),
                    ("layout_cols", str(layout_cols)),
                ],
            )
            tconn.executemany(
                "INSERT INTO cameras (seq, name, root_path, rotation, grid_pos) VALUES (?, ?, ?, ?, ?)",
                [
                    (i, c["name"], c["root_path"], int(c.get("rotation", 0)), int(c.get("grid_pos", -1)))
                    for i, c in enumerate(cameras)
                ],
            )
        return TunnelInfo(tunnel_id, name, db_filename, start_m, end_m, len(cameras))

    def get_tunnel_info(self, tunnel_id: int) -> TunnelInfo:
        row = self._tunnel_row(tunnel_id)
        return TunnelInfo(row["id"], row["name"], row["db_filename"], row["start_m"], row["end_m"], row["camera_count"])

    def open_tunnel(self, tunnel_id: int) -> sqlite3.Connection:
        row = self._tunnel_row(tunnel_id)
        conn = self._connect(self.root / row["db_filename"])
        migrate_if_needed(conn)
        return conn

    def tunnel_meta(self, tunnel_id: int) -> dict[str, str]:
        row = self._tunnel_row(tunnel_id)
        with self._connect(self.root / row["db_filename"]) as tconn:
            return dict(tconn.execute("SELECT key, value FROM meta").fetchall())

    def delete_tunnel(self, tunnel_id: int) -> None:
        """刪除隧道：移除索引列並刪除 .db／-wal／-shm 檔。照片原檔不動。"""
        row = self._tunnel_row(tunnel_id)
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute("DELETE FROM tunnels WHERE id = ?", (tunnel_id,))
        base = self.root / row["db_filename"]
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(base) + suffix)
            if p.exists():
                p.unlink()

    def add_recent_path(self, path: str, limit: int = 8) -> None:
        """記錄最近使用的相機資料夾；超出上限時淘汰最舊。

        used_at 使用毫秒級時間戳——同一秒內的多次記錄才能保序。
        """
        with self._lock, self._connect(self.index_path) as conn:
            now_ms = conn.execute(
                "SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO recent_paths (path, used_at) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET used_at = excluded.used_at",
                (path, now_ms),
            )
            conn.execute(
                "DELETE FROM recent_paths WHERE path IN ("
                "SELECT path FROM recent_paths ORDER BY used_at DESC, path LIMIT -1 OFFSET ?)",
                (limit,),
            )

    def get_recent_paths(self, limit: int = 8) -> list[str]:
        if not self.index_path.exists():
            return []
        with self._connect(self.index_path) as conn:
            try:
                rows = conn.execute(
                    "SELECT path FROM recent_paths ORDER BY used_at DESC, path LIMIT ?", (limit,)
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [r["path"] for r in rows]

    def set_camera_root(self, tunnel_id: int, camera_seq: int, root_path: str) -> None:
        """換機器／換硬碟時，重映射單一相機的根路徑。"""
        with self.open_tunnel(tunnel_id) as tconn:
            tconn.execute(
                "UPDATE cameras SET root_path = ? WHERE seq = ?", (root_path, camera_seq)
            )

    def _tunnel_row(self, tunnel_id: int) -> sqlite3.Row:
        if not self.index_path.exists():
            raise KeyError(tunnel_id)
        with self._connect(self.index_path) as conn:
            row = conn.execute(
                "SELECT * FROM tunnels WHERE id = ?", (tunnel_id,)
            ).fetchone()
        if row is None:
            raise KeyError(tunnel_id)
        return row

    # ---------- 專案歸檔（R9） ----------

    def list_projects(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        with self._connect(self.index_path) as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.name, p.created_at, COUNT(t.id) AS tunnel_count
                FROM projects p LEFT JOIN tunnels t ON t.project_id = p.id
                GROUP BY p.id
                ORDER BY p.name COLLATE NOCASE, p.id
                """
            ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "tunnel_count": r["tunnel_count"]}
            for r in rows
        ]

    def create_project(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("專案名稱不可空白")
        with self._lock, self._connect(self.index_path) as conn:
            self._ensure_home_tables(conn)
            try:
                cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
            except sqlite3.IntegrityError:
                raise KeyError(f"專案已存在：{name}")
            pid = cur.lastrowid
        return {"id": pid, "name": name, "tunnel_count": 0}

    def rename_project(self, project_id: int, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("專案名稱不可空白")
        with self._lock, self._connect(self.index_path) as conn:
            if conn.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise KeyError(project_id)
            try:
                conn.execute(
                    "UPDATE projects SET name = ? WHERE id = ?", (name, project_id)
                )
            except sqlite3.IntegrityError:
                raise KeyError(f"專案已存在：{name}")

    def delete_project(self, project_id: int) -> None:
        """刪除專案：底下隧道回到未分類（FK ON DELETE SET NULL），隧道本身不受影響。"""
        with self._lock, self._connect(self.index_path) as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            if cur.rowcount == 0:
                raise KeyError(project_id)

    def move_tunnel(self, tunnel_id: int, project_id: int | None) -> None:
        """把隧道移入專案（None＝移回未分類）。"""
        self._tunnel_row(tunnel_id)  # 不存在時 KeyError
        if project_id is not None:
            with self._connect(self.index_path) as conn:
                if conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?", (project_id,)
                ).fetchone() is None:
                    raise KeyError(project_id)
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute(
                "UPDATE tunnels SET project_id = ? WHERE id = ?", (project_id, tunnel_id)
            )

    def get_tunnel_project(self, tunnel_id: int) -> int | None:
        row = self._tunnel_row(tunnel_id)
        return row["project_id"] if "project_id" in row.keys() else None

    def touch_tunnel(self, tunnel_id: int) -> None:
        """記錄進入檢視器的時間。last_opened_at 存 TEXT（毫秒精度時間戳，
        同 recent_paths 慣例——字串比較即可保序）。"""
        with self._lock, self._connect(self.index_path) as conn:
            now_ms = conn.execute(
                "SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')"
            ).fetchone()[0]
            conn.execute(
                "UPDATE tunnels SET last_opened_at = ? WHERE id = ?",
                (now_ms, tunnel_id),
            )

    def get_last_opened(self, tunnel_id: int) -> str | None:
        row = self._tunnel_row(tunnel_id)
        keys = row.keys()
        return row["last_opened_at"] if "last_opened_at" in keys else None

    # ---------- EXIF 掃描快取（R9，index.db 全域共用） ----------

    def scan_cache_load(self, folder_root: str) -> dict[str, dict]:
        if not self.index_path.exists():
            return {}
        with self._connect(self.index_path) as conn:
            try:
                rows = conn.execute(
                    "SELECT rel_path, size, mtime, exif_time, time_source, "
                    "width, height, orientation FROM scan_cache WHERE folder_root = ?",
                    (folder_root,),
                ).fetchall()
            except sqlite3.OperationalError:
                return {}
        return {
            r["rel_path"]: {
                "size": r["size"],
                "mtime": r["mtime"],
                "exif_time": r["exif_time"],
                "time_source": r["time_source"],
                "width": r["width"],
                "height": r["height"],
                "orientation": r["orientation"],
            }
            for r in rows
        }

    def scan_cache_put(self, folder_root: str, rows: list[tuple]) -> None:
        """rows: (rel_path, size, mtime, exif_time_iso|None, time_source, width, height, orientation)"""
        if not rows:
            return
        with self._lock, self._connect(self.index_path) as conn:
            conn.executemany(
                """
                INSERT INTO scan_cache (folder_root, rel_path, size, mtime, exif_time,
                                        time_source, width, height, orientation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(folder_root, rel_path) DO UPDATE SET
                    size=excluded.size, mtime=excluded.mtime, exif_time=excluded.exif_time,
                    time_source=excluded.time_source, width=excluded.width,
                    height=excluded.height, orientation=excluded.orientation
                """,
                [(folder_root, *r) for r in rows],
            )

    def scan_cache_clear(self) -> None:
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute("DELETE FROM scan_cache")

    # ---------- 匯入 job 持久化（R9） ----------

    def job_save(
        self,
        job_id: str,
        *,
        status: str,
        stage: str | None = None,
        done: int = 0,
        total: int = 0,
        preview_json=None,
        scan_json=None,
        error: str | None = None,
        fingerprint: str | None = None,
    ) -> None:
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute(
                """
                INSERT INTO import_jobs (job_id, status, stage, done, total, preview_json,
                                         scan_json, error, fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status, stage=excluded.stage, done=excluded.done,
                    total=excluded.total,
                    preview_json=COALESCE(excluded.preview_json, import_jobs.preview_json),
                    scan_json=COALESCE(excluded.scan_json, import_jobs.scan_json),
                    error=excluded.error, fingerprint=excluded.fingerprint
                """,
                (
                    job_id,
                    status,
                    stage,
                    done,
                    total,
                    json.dumps(preview_json, ensure_ascii=False) if preview_json is not None else None,
                    json.dumps(scan_json, ensure_ascii=False) if scan_json is not None else None,
                    error,
                    fingerprint,
                    datetime.now().timestamp(),
                ),
            )

    def job_get(self, job_id: str) -> dict | None:
        if not self.index_path.exists():
            return None
        with self._connect(self.index_path) as conn:
            try:
                row = conn.execute(
                    "SELECT * FROM import_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if row is None:
            return None
        d = dict(row)
        d["preview"] = json.loads(d.pop("preview_json")) if d.get("preview_json") else None
        d["scan"] = json.loads(d.pop("scan_json")) if d.get("scan_json") else None
        d.pop("preview_json", None)
        d.pop("scan_json", None)
        return d

    def job_delete(self, job_id: str) -> None:
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute("DELETE FROM import_jobs WHERE job_id = ?", (job_id,))

    def job_interrupt_running(self) -> None:
        """server 啟動還原：上次執行中的 job 已無執行緒，標記為 interrupted。"""
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute("UPDATE import_jobs SET status = 'interrupted' WHERE status = 'running'")

    def job_prune(self, ttl_sec: float, max_n: int) -> None:
        cutoff = datetime.now().timestamp() - ttl_sec
        with self._lock, self._connect(self.index_path) as conn:
            conn.execute("DELETE FROM import_jobs WHERE created_at < ?", (cutoff,))
            conn.execute(
                "DELETE FROM import_jobs WHERE job_id IN ("
                "SELECT job_id FROM import_jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                (max_n,),
            )

    def job_count(self) -> int:
        with self._connect(self.index_path) as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM import_jobs").fetchone()["n"]
