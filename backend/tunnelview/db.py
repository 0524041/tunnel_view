"""工作區資料層：index.db 索引 + 一隧道一 SQLite 檔。

所有連線啟用 WAL（讀寫不互斥）與外鍵約束。
照片以「相機根路徑 + 相對路徑」引用，不複製原檔。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = "3"

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
    rotation INTEGER NOT NULL DEFAULT 0 CHECK (rotation IN (0, 90, 180, 270))
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
    aspect_anomaly INTEGER NOT NULL DEFAULT 0
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
            conn.execute("PRAGMA journal_mode=WAL")

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

    def create_tunnel(
        self,
        *,
        name: str,
        start_m: int,
        end_m: int,
        cameras: list[dict],
        tolerance_seconds: float,
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
                ],
            )
            tconn.executemany(
                "INSERT INTO cameras (seq, name, root_path, rotation) VALUES (?, ?, ?, ?)",
                [(i, c["name"], c["root_path"], int(c.get("rotation", 0))) for i, c in enumerate(cameras)],
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
