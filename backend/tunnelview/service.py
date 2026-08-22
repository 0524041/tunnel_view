"""隧道資料存取服務：視窗查詢、里程跳轉、錨點寫入與全線重算。

錨點模型 v2：錨點綁定載體照片，群組 seq 由解析鏈即時得出。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .align import CameraSeries, PhotoStamp, align
from .anchor_model import (
    anchor_for_group,
    list_anchors_resolved,
    mark_missing_with_transfer,
    restore_photo,
    set_anchor_on_group,
    _recompute_missing_counts,
)
from .db import Workspace
from .importer import compute_aspect_anomalies
from .interp import AnchorOrderError, AnchorRangeError, check_anchor, compute_all

__all__ = ["TunnelService", "AnchorOrderError", "AnchorRangeError", "MergeConflict"]


class MergeConflict(Exception):
    def __init__(self, conflict_cameras: list[int]):
        super().__init__(f"相機 {conflict_cameras} 在兩側群組皆有照片，需指定保留哪側")
        self.conflict_cameras = conflict_cameras


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

    def _resolved_anchors(self, conn) -> dict[int, int]:
        """seq → mileage（排除失準者）。"""
        return {
            a["group_seq"]: a["mileage_m"]
            for a in list_anchors_resolved(conn)
            if not a["dangling"] and a["group_seq"] is not None
        }

    def overview(self, tunnel_id: int) -> dict:
        """全線概觀（導航軌用）：緊湊陣列，數千群組也只傳一次。"""
        m = self.ws.tunnel_meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            cams = [r["name"] for r in conn.execute("SELECT name FROM cameras ORDER BY seq").fetchall()]
            anchored = set(self._resolved_anchors(conn))
            anomaly_counts = {
                r["seq"]: r["n"]
                for r in conn.execute(
                    "SELECT g.seq AS seq, COUNT(*) AS n FROM photos p "
                    "JOIN photo_groups g ON g.id = p.group_id "
                    "WHERE p.aspect_anomaly = 1 AND COALESCE(p.manual_missing, 0) = 0 "
                    "GROUP BY g.seq"
                ).fetchall()
            }
            rows = conn.execute(
                "SELECT seq, est_mileage_m, missing_count FROM photo_groups ORDER BY seq"
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
                "anchored": [r["seq"] in anchored for r in rows],
                "anomaly": [anomaly_counts.get(r["seq"], 0) for r in rows],
            },
        }

    def get_window(self, tunnel_id: int, around: int, before: int, after: int) -> list[dict]:
        lo = max(around - before, 0)
        hi = around + after
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            anchored = set(self._resolved_anchors(conn))
            groups = conn.execute(
                "SELECT id, seq, corrected_time, est_mileage_m, missing_count "
                "FROM photo_groups WHERE seq BETWEEN ? AND ? ORDER BY seq",
                (lo, hi),
            ).fetchall()
            result = []
            for g in groups:
                photos = conn.execute(
                    "SELECT p.id AS photo_id, c.seq AS camera_seq, p.rel_path, p.flagged, "
                    "p.width, p.height, p.rotation_override AS rotation_override, c.rotation AS camera_rotation, "
                    "p.exif_time, p.corrected_time, p.time_source, p.aspect_anomaly, "
                    "(p.width IS NOT NULL AND p.height IS NOT NULL) AS has_dims "
                    "FROM photos p JOIN cameras c ON c.id = p.camera_id "
                    "WHERE p.group_id = ? AND COALESCE(p.manual_missing, 0) = 0 ORDER BY c.seq",
                    (g["id"],),
                ).fetchall()
                result.append(
                    {
                        "seq": g["seq"],
                        "corrected_time": g["corrected_time"],
                        "est_mileage_m": g["est_mileage_m"],
                        "missing_count": g["missing_count"],
                        "anchored": g["seq"] in anchored,
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
            resolved = list_anchors_resolved(conn)
        finally:
            conn.close()
        out = []
        for a in resolved:
            if a["group_seq"] is None or a["dangling"]:
                continue
            out.append({"group_seq": a["group_seq"], "mileage_m": a["mileage_m"]})
        out.sort(key=lambda x: x["group_seq"])
        return out

    def set_anchor(self, tunnel_id: int, seq: int, mileage_m: int) -> None:
        """寫入／覆寫錨點並全線重算。違反單調或範圍時丟出例外，不寫入。"""
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                existing = self._resolved_anchors(conn)
                check_anchor(
                    seq,
                    mileage_m,
                    group_count=info["group_count"],
                    start_m=info["start_m"],
                    end_m=info["end_m"],
                    anchors=existing,
                )
                if set_anchor_on_group(conn, group_seq=seq, mileage_m=mileage_m) is None:
                    raise ValueError(f"群組 {seq} 沒有影像可作為錨點載體")
                existing[seq] = mileage_m
                self._recompute(conn, group_count=info["group_count"], start_m=info["start_m"], end_m=info["end_m"], anchors=existing)
        finally:
            conn.close()

    def delete_anchor(self, tunnel_id: int, seq: int) -> None:
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                target = anchor_for_group(conn, seq)
                if target is None:
                    raise KeyError(seq)
                conn.execute("DELETE FROM anchors WHERE carrier_photo_id = ?", (target["_pid"],))
                existing = self._resolved_anchors(conn)
                self._recompute(conn, group_count=info["group_count"], start_m=info["start_m"], end_m=info["end_m"], anchors=existing)
        finally:
            conn.close()

    def photo_file(self, tunnel_id: int, photo_id: int) -> Path:
        """解析照片絕對路徑：相機根路徑 + 相對路徑。"""
        return self.photo_render_info(tunnel_id, photo_id)["path"]

    def photo_render_info(self, tunnel_id: int, photo_id: int) -> dict:
        """照片串流資訊：絕對路徑＋額外旋轉角（單張 override > 機位預設）。"""
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            row = conn.execute(
                "SELECT c.root_path, p.rel_path, p.rotation_override AS ro, c.rotation AS cam_rot "
                "FROM photos p JOIN cameras c ON c.id = p.camera_id WHERE p.id = ?",
                (photo_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(photo_id)
        extra = row["ro"] if row["ro"] is not None else (row["cam_rot"] or 0)
        return {
            "path": Path(row["root_path"]) / row["rel_path"],
            "extra_rotation": int(extra or 0) % 360,
        }

    @staticmethod
    def _recompute(conn, *, group_count: int, start_m: int, end_m: int, anchors: dict[int, int]) -> None:
        est = compute_all(group_count=group_count, start_m=start_m, end_m=end_m, anchors=anchors)
        conn.executemany(
            "UPDATE photo_groups SET est_mileage_m = ? WHERE seq = ?",
            [(m, s) for s, m in est.items()],
        )

    # ---------- 待檢查 / 改判缺照 ----------

    def confirm_flag(self, tunnel_id: int, photo_id: int) -> None:
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                cur = conn.execute("UPDATE photos SET flagged = 0 WHERE id = ?", (photo_id,))
                if cur.rowcount == 0:
                    raise KeyError(photo_id)
        finally:
            conn.close()

    def review_photo(self, tunnel_id: int, photo_id: int, result: str) -> dict:
        """人工複核結論：'ok' 清除旗標；'anomaly' 標記確認異常。回傳所在群組 seq。"""
        if result not in ("ok", "anomaly"):
            raise ValueError("result 必須為 ok 或 anomaly")
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                row = conn.execute(
                    "UPDATE photos SET review_result = ?, flagged = 0 WHERE id = ? "
                    "AND COALESCE(manual_missing, 0) = 0",
                    (result, photo_id),
                )
                if row.rowcount == 0:
                    raise KeyError(photo_id)
                seq_row = conn.execute(
                    "SELECT g.seq AS seq FROM photos p JOIN photo_groups g ON g.id = p.group_id "
                    "WHERE p.id = ?",
                    (photo_id,),
                ).fetchone()
            return {"group_seq": seq_row["seq"] if seq_row else None}
        finally:
            conn.close()

    def reset_review(self, tunnel_id: int, photo_id: int) -> None:
        """撤銷人工複核結論，回到待檢查狀態。"""
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                row = conn.execute(
                    "UPDATE photos SET review_result = NULL, flagged = 1 "
                    "WHERE id = ? AND review_result IS NOT NULL",
                    (photo_id,),
                )
                if row.rowcount == 0:
                    raise KeyError(photo_id)
        finally:
            conn.close()

    def mark_missing_photo(self, tunnel_id: int, photo_id: int) -> None:
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                if not mark_missing_with_transfer(conn, photo_id):
                    raise KeyError(photo_id)
                existing = self._resolved_anchors(conn)
                self._recompute(conn, group_count=info["group_count"], start_m=info["start_m"], end_m=info["end_m"], anchors=existing)
        finally:
            conn.close()

    def restore_missing_photo(self, tunnel_id: int, photo_id: int) -> None:
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                if not restore_photo(conn, photo_id):
                    raise KeyError(photo_id)
                existing = self._resolved_anchors(conn)
                self._recompute(conn, group_count=info["group_count"], start_m=info["start_m"], end_m=info["end_m"], anchors=existing)
        finally:
            conn.close()

    # ---------- 重新對齊 ----------

    def _series_from_db(self, conn) -> tuple[list[CameraSeries], dict[int, str]]:
        rows = conn.execute(
            "SELECT p.id, p.exif_time, c.seq AS camera_seq FROM photos p "
            "JOIN cameras c ON c.id = p.camera_id "
            "WHERE COALESCE(p.manual_missing, 0) = 0"
        ).fetchall()
        by_cam: dict[int, list[PhotoStamp]] = {}
        for r in rows:
            by_cam.setdefault(r["camera_seq"], []).append(PhotoStamp(str(r["id"]), datetime.fromisoformat(r["exif_time"])))
        series = [CameraSeries(idx, lst) for idx, lst in sorted(by_cam.items())]
        cam_names = {r["seq"]: r["name"] for r in conn.execute("SELECT seq, name FROM cameras ORDER BY seq")}
        return series, cam_names

    @staticmethod
    def _preview_payload(series, result) -> dict:
        cams = [
            {
                "name": idx,
                "photo_count": len(s.photos),
                "offset_seconds": result.offsets_seconds[s.camera_index],
            }
            for s in series
            for idx in [s.camera_index]
        ]
        dist: dict[int, int] = {}
        for g in result.groups:
            dist[len(g.missing)] = dist.get(len(g.missing), 0) + 1
        flagged_n = sum(1 for g in result.groups for _ in g.flagged)
        return {
            "group_count": len(result.groups),
            "cameras": cams,
            "missing_distribution": {str(k): v for k, v in sorted(dist.items())},
            "flagged_count": flagged_n,
        }

    def realign_preview(self, tunnel_id: int, tolerance_seconds: float) -> dict:
        m = self.ws.tunnel_meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            series, cam_names = self._series_from_db(conn)
        finally:
            conn.close()
        result = align(series, tolerance_seconds=tolerance_seconds)
        payload = self._preview_payload(series, result)
        for c in payload["cameras"]:
            c["name"] = cam_names.get(c["name"], f"相機{c['name']}")
        return payload

    def realign_apply(self, tunnel_id: int, tolerance_seconds: float) -> dict:
        """以新容差重建群組歸屬。錨點綁定照片，自動落位、零遺失。"""
        info = self.meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                series, cam_names = self._series_from_db(conn)
                result = align(series, tolerance_seconds=tolerance_seconds)

                # 錨點參照 photos.id，與 photo_groups 無 FK——刪群組不影響錨點。
                conn.execute("UPDATE photos SET group_id = NULL WHERE group_id IS NOT NULL")
                conn.execute("DELETE FROM photo_groups")
                for g in result.groups:
                    conn.execute(
                        "INSERT INTO photo_groups (seq, corrected_time, est_mileage_m, missing_count) "
                        "VALUES (?, ?, 0, ?)",
                        (
                            g.seq,
                            g.corrected_time.isoformat(timespec="seconds"),
                            len(g.missing),
                        ),
                    )
                gid_by_seq = {
                    r["seq"]: r["id"]
                    for r in conn.execute("SELECT id, seq FROM photo_groups").fetchall()
                }

                flagged_n = 0
                for g in result.groups:
                    gid = gid_by_seq[g.seq]
                    residual = set(g.flagged)
                    for cam_idx, pid_str in g.members.items():
                        pid = int(pid_str)
                        keep_mtime_flag = 1 if cam_idx in residual else 0
                        conn.execute(
                            "UPDATE photos SET group_id = ?, "
                            "flagged = CASE WHEN time_source = 'mtime' THEN 1 ELSE ? END "
                            "WHERE id = ?",
                            (gid, keep_mtime_flag, pid),
                        )
                        if keep_mtime_flag:
                            flagged_n += 1

                _recompute_missing_counts(conn)
                compute_aspect_anomalies(conn)
                existing = self._resolved_anchors(conn)
                self._recompute(
                    conn,
                    group_count=len(result.groups),
                    start_m=info["start_m"],
                    end_m=info["end_m"],
                    anchors=existing,
                )

                payload = self._preview_payload(series, result)
                payload.update(
                    {
                        "tolerance_seconds": tolerance_seconds,
                        "realigned_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('import_report', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (json.dumps(payload, ensure_ascii=False),),
                )
            return {
                "group_count": len(result.groups),
                "flagged": flagged_n,
                "anchors_preserved": len(existing),
            }
        finally:
            conn.close()

    # ---------- 合併 ----------

    def merge_group(self, tunnel_id: int, seq: int, direction: str, keep: str | None = None) -> dict:
        """將相鄰群組併入 seq。衝突（同機兩側皆有照片）時要求裁決。"""
        if direction not in ("prev", "next"):
            raise ValueError("direction 必須為 prev 或 next")
        if keep not in (None, "current", "neighbor"):
            raise ValueError("keep 必須為 current 或 neighbor")
        info = self.meta(tunnel_id)
        neighbor_seq = seq - 1 if direction == "prev" else seq + 1

        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                groups = {
                    r["seq"]: r["id"]
                    for r in conn.execute(
                        "SELECT id, seq FROM photo_groups WHERE seq IN (?, ?)",
                        (seq, neighbor_seq),
                    ).fetchall()
                }
                if seq not in groups or neighbor_seq not in groups:
                    raise KeyError(neighbor_seq)
                current_gid, neighbor_gid = groups[seq], groups[neighbor_seq]

                cams_current = {
                    r["camera_id"]
                    for r in conn.execute(
                        "SELECT camera_id FROM photos WHERE group_id=? AND COALESCE(manual_missing,0)=0",
                        (current_gid,),
                    )
                }
                cams_neighbor = {
                    r["camera_id"]
                    for r in conn.execute(
                        "SELECT camera_id FROM photos WHERE group_id=? AND COALESCE(manual_missing,0)=0",
                        (neighbor_gid,),
                    )
                }
                conflicts = sorted(cams_current & cams_neighbor)
                if conflicts and keep is None:
                    cam_seqs = [
                        r["seq"]
                        for cid in conflicts
                        for r in [conn.execute("SELECT seq FROM cameras WHERE id=?", (cid,)).fetchone()]
                        if r
                    ]
                    raise MergeConflict(cam_seqs)

                # 錨點保護：衝突照片若承載錨點，一律保留該側、由勝側同相機照片接手
                for cid in conflicts:
                    loser_gid = neighbor_gid if keep == "current" else current_gid
                    winner_gid = current_gid if keep == "current" else neighbor_gid
                    loser_photo = conn.execute(
                        "SELECT p.id FROM photos p WHERE p.group_id=? AND p.camera_id=? "
                        "AND COALESCE(p.manual_missing,0)=0 LIMIT 1",
                        (loser_gid, cid),
                    ).fetchone()
                    if loser_photo is None:
                        continue
                    anchor = conn.execute(
                        "SELECT id FROM anchors WHERE carrier_photo_id = ?", (loser_photo["id"],)
                    ).fetchone()
                    if anchor is None:
                        continue
                    winner_photo = conn.execute(
                        "SELECT p.id FROM photos p WHERE p.group_id=? AND p.camera_id=? "
                        "AND COALESCE(p.manual_missing,0)=0 LIMIT 1",
                        (winner_gid, cid),
                    ).fetchone()
                    if winner_photo is not None:
                        conn.execute(
                            "UPDATE anchors SET carrier_photo_id = ?, updated_at = datetime('now') "
                            "WHERE id = ?",
                            (winner_photo["id"], anchor["id"]),
                        )

                if conflicts:
                    loser_gid = neighbor_gid if keep == "current" else current_gid
                    losers = conn.execute(
                        "SELECT id FROM photos WHERE group_id=? AND camera_id IN (%s)"
                        % ",".join("?" * len(conflicts)),
                        (loser_gid, *conflicts),
                    ).fetchall()
                    for r in losers:
                        mark_missing_with_transfer(conn, r["id"])

                conn.execute(
                    "UPDATE photos SET group_id = ? WHERE group_id = ?",
                    (current_gid, neighbor_gid),
                )
                conn.execute("DELETE FROM photo_groups WHERE id = ?", (neighbor_gid,))
                if direction == "next":
                    conn.execute(
                        "UPDATE photo_groups SET seq = seq - 1 WHERE seq > ?", (seq,)
                    )
                else:
                    conn.execute(
                        "UPDATE photo_groups SET seq = seq - 1 WHERE seq > ?", (neighbor_seq,)
                    )
                _recompute_missing_counts(conn)

                new_total = conn.execute("SELECT COUNT(*) AS n FROM photo_groups").fetchone()["n"]
                existing = self._resolved_anchors(conn)
                self._recompute(
                    conn,
                    group_count=new_total,
                    start_m=info["start_m"],
                    end_m=info["end_m"],
                    anchors=existing,
                )
            return {"merged_into": seq, "group_count": new_total}
        finally:
            conn.close()

    # ---------- 旋轉 ----------

    def set_camera_rotation(self, tunnel_id: int, camera_seq: int, angle: int) -> None:
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE cameras SET rotation = ? WHERE seq = ?", (angle, camera_seq)
                )
                if cur.rowcount == 0:
                    raise KeyError(camera_seq)
        finally:
            conn.close()

    def set_photo_rotation(self, tunnel_id: int, photo_id: int, angle: int) -> None:
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE photos SET rotation_override = ? WHERE id = ?", (angle, photo_id)
                )
                if cur.rowcount == 0:
                    raise KeyError(photo_id)
        finally:
            conn.close()

    # ---------- 資訊面板聚合 ----------

    def info(self, tunnel_id: int) -> dict:
        m = self.ws.tunnel_meta(tunnel_id)
        conn = self.ws.open_tunnel(tunnel_id)
        try:
            report_raw = conn.execute(
                "SELECT value FROM meta WHERE key = 'import_report'"
            ).fetchone()
            report = json.loads(report_raw["value"]) if report_raw else {}

            cameras = [
                dict(r)
                for r in conn.execute(
                    "SELECT seq, name, rotation FROM cameras ORDER BY seq"
                ).fetchall()
            ]
            flagged = [
                dict(r)
                for r in conn.execute(
                    "SELECT p.id AS photo_id, c.name AS camera, p.rel_path, p.exif_time, g.seq AS group_seq, "
                    "CASE WHEN p.time_source = 'mtime' THEN 'exif缺漏' ELSE '對齊殘差' END AS reason "
                    "FROM photos p JOIN cameras c ON c.id = p.camera_id "
                    "LEFT JOIN photo_groups g ON g.id = p.group_id "
                    "WHERE p.flagged = 1 AND p.review_result IS NULL AND COALESCE(p.manual_missing, 0) = 0"
                ).fetchall()
            ]
            reviewed = [
                dict(r)
                for r in conn.execute(
                    "SELECT p.id AS photo_id, c.name AS camera, p.rel_path, g.seq AS group_seq, "
                    "p.review_result AS result "
                    "FROM photos p JOIN cameras c ON c.id = p.camera_id "
                    "LEFT JOIN photo_groups g ON g.id = p.group_id "
                    "WHERE p.review_result IS NOT NULL"
                ).fetchall()
            ]
            manual_missing = [
                dict(r)
                for r in conn.execute(
                    "SELECT p.id AS photo_id, c.name AS camera, p.rel_path, p.exif_time "
                    "FROM photos p JOIN cameras c ON c.id = p.camera_id "
                    "WHERE p.manual_missing = 1"
                ).fetchall()
            ]
            rotation_overrides = [
                {"photo_id": r["id"], "angle": r["rotation_override"]}
                for r in conn.execute(
                    "SELECT id, rotation_override FROM photos WHERE rotation_override IS NOT NULL"
                ).fetchall()
            ]
            dangling = [
                a for a in list_anchors_resolved(conn) if a["dangling"] or a["group_seq"] is None
            ]
        finally:
            conn.close()
        return {
            "name": m.get("tunnel_name", ""),
            "start_m": int(m["start_m"]),
            "end_m": int(m["end_m"]),
            "report": report,
            "cameras": cameras,
            "flagged": flagged,
            "reviewed": reviewed,
            "manual_missing": manual_missing,
            "rotation_overrides": rotation_overrides,
            "dangling_anchors": dangling,
        }

