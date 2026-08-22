"""隧道資料存取服務：視窗查詢、里程跳轉、錨點寫入與全線重算。"""

from __future__ import annotations

from pathlib import Path

from .db import Workspace
from .interp import AnchorOrderError, AnchorRangeError, check_anchor, compute_all

__all__ = ["TunnelService", "AnchorOrderError", "AnchorRangeError"]


class TunnelService:
    def __init__(self, workspace: Workspace):
        self.ws = workspace

    def meta(self, tunnel_id: int) -> dict:
        m = self.ws.tunnel_meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM photo_groups").fetchone()["n"]
        finally:
            conn.close()
        return {
            "name": m.get("tunnel_name", ""),
            "start_m": int(m["start_m"]),
            "end_m": int(m["end_m"]),
            "group_count": count,
        }

    def overview(self, tunnel_id: int) -> dict:
        """全線概觀（導航軌用）：緊湊陣列，數千群組也只傳一次。"""
        m = self.ws.tunnel_meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            cams = [r["name"] for r in conn.execute("SELECT name FROM cameras ORDER BY seq").fetchall()]
            rows = conn.execute(
                "SELECT g.seq, g.est_mileage_m, g.missing_count, a.group_seq IS NOT NULL AS anchored "
                "FROM photo_groups g LEFT JOIN anchors a ON a.group_seq = g.seq ORDER BY g.seq"
            ).fetchall()
        finally:
            conn.close()
        return {
            "name": m.get("tunnel_name", ""),
            "start_m": int(m["start_m"]),
            "end_m": int(m["end_m"]),
            "camera_count": len(cams),
            "cameras": cams,
            "group_count": len(rows),
            "groups": {
                "seq": [r["seq"] for r in rows],
                "est": [r["est_mileage_m"] for r in rows],
                "missing": [r["missing_count"] for r in rows],
                "anchored": [bool(r["anchored"]) for r in rows],
            },
        }

    def get_window(self, tunnel_id: int, around: int, before: int, after: int) -> list[dict]:
        lo = max(around - before, 0)
        hi = around + after
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            groups = conn.execute(
                "SELECT g.id, g.seq, g.corrected_time, g.est_mileage_m, g.missing_count, a.group_seq IS NOT NULL AS anchored "
                "FROM photo_groups g LEFT JOIN anchors a ON a.group_seq = g.seq "
                "WHERE g.seq BETWEEN ? AND ? ORDER BY g.seq",
                (lo, hi),
            ).fetchall()
            result = []
            for g in groups:
                photos = conn.execute(
                    "SELECT p.id AS photo_id, c.seq AS camera_seq, p.rel_path, p.flagged "
                    "FROM photos p JOIN cameras c ON c.id = p.camera_id "
                    "WHERE p.group_id = ? ORDER BY c.seq",
                    (g["id"],),
                ).fetchall()
                result.append(
                    {
                        "seq": g["seq"],
                        "corrected_time": g["corrected_time"],
                        "est_mileage_m": g["est_mileage_m"],
                        "missing_count": g["missing_count"],
                        "anchored": bool(g["anchored"]),
                        "photos": [dict(p) for p in photos],
                    }
                )
            return result
        finally:
            conn.close()

    def nearest_by_mileage(self, tunnel_id: int, mileage_m: int) -> dict | None:
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            row = conn.execute(
                "SELECT seq, est_mileage_m FROM photo_groups ORDER BY ABS(est_mileage_m - ?), seq LIMIT 1",
                (mileage_m,),
            ).fetchone()
            return {"seq": row["seq"], "est_mileage_m": row["est_mileage_m"]} if row else None
        finally:
            conn.close()

    def list_anchors(self, tunnel_id: int) -> list[dict]:
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            rows = conn.execute(
                "SELECT group_seq, mileage_m FROM anchors ORDER BY group_seq"
            ).fetchall()
            return [{"group_seq": r["group_seq"], "mileage_m": r["mileage_m"]} for r in rows]
        finally:
            conn.close()

    def set_anchor(self, tunnel_id: int, seq: int, mileage_m: int) -> None:
        """寫入／覆寫錨點並全線重算。違反單調或範圍時丟出例外，不寫入。"""
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                existing = {
                    r["group_seq"]: r["mileage_m"]
                    for r in conn.execute("SELECT group_seq, mileage_m FROM anchors").fetchall()
                }
                check_anchor(
                    seq,
                    mileage_m,
                    group_count=info["group_count"],
                    start_m=info["start_m"],
                    end_m=info["end_m"],
                    anchors=existing,
                )
                existing[seq] = mileage_m
                conn.execute(
                    "INSERT INTO anchors (group_seq, mileage_m) VALUES (?, ?) "
                    "ON CONFLICT(group_seq) DO UPDATE SET mileage_m = excluded.mileage_m, updated_at = datetime('now')",
                    (seq, mileage_m),
                )
                self._recompute(conn, group_count=info["group_count"], start_m=info["start_m"], end_m=info["end_m"], anchors=existing)
        finally:
            conn.close()

    def delete_anchor(self, tunnel_id: int, seq: int) -> None:
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                cur = conn.execute("DELETE FROM anchors WHERE group_seq = ?", (seq,))
                if cur.rowcount == 0:
                    raise KeyError(seq)
                existing = {
                    r["group_seq"]: r["mileage_m"]
                    for r in conn.execute("SELECT group_seq, mileage_m FROM anchors").fetchall()
                }
                self._recompute(conn, group_count=info["group_count"], start_m=info["start_m"], end_m=info["end_m"], anchors=existing)
        finally:
            conn.close()

    def photo_file(self, tunnel_id: int, photo_id: int) -> Path:
        """解析照片絕對路徑：相機根路徑 + 相對路徑。"""
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            row = conn.execute(
                "SELECT c.root_path, p.rel_path FROM photos p JOIN cameras c ON c.id = p.camera_id WHERE p.id = ?",
                (photo_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(photo_id)
        return Path(row["root_path"]) / row["rel_path"]

    @staticmethod
    def _recompute(conn, *, group_count: int, start_m: int, end_m: int, anchors: dict[int, int]) -> None:
        est = compute_all(group_count=group_count, start_m=start_m, end_m=end_m, anchors=anchors)
        conn.executemany(
            "UPDATE photo_groups SET est_mileage_m = ? WHERE seq = ?",
            [(m, s) for s, m in est.items()],
        )
