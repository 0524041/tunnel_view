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
    photo_count INTEGER NOT NULL DEFAULT 0
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
    flagged INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_photos_group ON photos(group_id);
CREATE INDEX IF NOT EXISTS idx_photos_camera ON photos(camera_id);

CREATE TABLE IF NOT EXISTS anchors (
    id INTEGER PRIMARY KEY,
    group_seq INTEGER NOT NULL UNIQUE REFERENCES photo_groups(seq) ON DELETE CASCADE,
    mileage_m INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


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
                "INSERT INTO cameras (seq, name, root_path) VALUES (?, ?, ?)",
                [(i, c["name"], c["root_path"]) for i, c in enumerate(cameras)],
            )
        return TunnelInfo(tunnel_id, name, db_filename, start_m, end_m, len(cameras))

    def get_tunnel_info(self, tunnel_id: int) -> TunnelInfo:
        row = self._tunnel_row(tunnel_id)
        return TunnelInfo(row["id"], row["name"], row["db_filename"], row["start_m"], row["end_m"], row["camera_count"])

    def open_tunnel(self, tunnel_id: int) -> sqlite3.Connection:
        row = self._tunnel_row(tunnel_id)
        return self._connect(self.root / row["db_filename"])

    def tunnel_meta(self, tunnel_id: int) -> dict[str, str]:
        row = self._tunnel_row(tunnel_id)
        with self._connect(self.root / row["db_filename"]) as tconn:
            return dict(tconn.execute("SELECT key, value FROM meta").fetchall())

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
