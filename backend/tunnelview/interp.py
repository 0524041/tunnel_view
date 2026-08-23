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

"""里程內插引擎。

輸入群組數、起迄里程與錨點（group_seq → 公尺），輸出全線各群組的推算里程。
方向由起訖數值表達（end < start 即行進方向遞減）。所有輸出為整數公尺。
"""

__all__ = [
    "AnchorOrderError",
    "AnchorRangeError",
    "check_anchor",
    "compute_all",
]


class AnchorOrderError(ValueError):
    """錨點值違反沿行進方向的嚴格單調限制。"""


class AnchorRangeError(ValueError):
    """錨點值超出隧道起迄範圍。"""


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_all(group_count: int, start_m: int, end_m: int, anchors: dict[int, int]) -> dict[int, int]:
    """計算全線推算里程。"""
    if group_count < 1:
        raise ValueError("群組數必須為正")
    seqs = list(range(group_count))
    if not anchors:
        if group_count == 1:
            return {0: start_m}
        span = (end_m - start_m) / (group_count - 1)
        return {s: round(start_m + span * s) for s in seqs}

    anchored = sorted(anchors.items())
    lo, hi = min(start_m, end_m), max(start_m, end_m)
    result: dict[int, int] = {}
    for s in seqs:
        if s in anchors:
            result[s] = anchors[s]
            continue
        prev = max((sq for sq, _ in anchored if sq < s), default=None)
        nxt = min((sq for sq, _ in anchored if sq > s), default=None)
        if prev is not None and nxt is not None:
            m_prev, m_next = anchors[prev], anchors[nxt]
            t = (s - prev) / (nxt - prev)
            result[s] = round(m_prev + (m_next - m_prev) * t)
        elif prev is not None or nxt is not None:
            # 首末錨點之外：以最近段斜率外插；單錨點時以全域等分斜率外插
            if len(anchored) >= 2:
                pair = anchored[-2:] if prev is not None else anchored[:2]
                (sa, ma), (sb, mb) = pair
                slope = (mb - ma) / (sb - sa)
            else:
                slope = (end_m - start_m) / max(group_count - 1, 1)
            if prev is not None:
                base_seq, base_m = prev, anchors[prev]
            else:
                assert nxt is not None
                base_seq, base_m = nxt, anchors[nxt]
            result[s] = round(_clamp(base_m + slope * (s - base_seq), lo, hi))
    return result


def check_anchor(
    seq: int,
    value_m: int,
    *,
    group_count: int,
    start_m: int,
    end_m: int,
    anchors: dict[int, int],
) -> None:
    """驗證新錨點（或覆寫值）；違規時丟出 AnchorOrderError / AnchorRangeError。"""
    lo, hi = min(start_m, end_m), max(start_m, end_m)
    if not (lo <= value_m <= hi):
        raise AnchorRangeError(f"里程 {value_m} 超出隧道範圍 [{lo}, {hi}]")

    going_up = end_m >= start_m
    others = {sq: m for sq, m in anchors.items() if sq != seq}
    prev_sq = max((sq for sq in others if sq < seq), default=None)
    next_sq = min((sq for sq in others if sq > seq), default=None)

    if prev_sq is not None:
        ok = value_m > others[prev_sq] if going_up else value_m < others[prev_sq]
        if not ok:
            raise AnchorOrderError(
                f"里程 {value_m} 違反方向限制（前錨點 @群組{prev_sq} 為 {others[prev_sq]}）"
            )
    if next_sq is not None:
        ok = value_m < others[next_sq] if going_up else value_m > others[next_sq]
        if not ok:
            raise AnchorOrderError(
                f"里程 {value_m} 違反方向限制（後錨點 @群組{next_sq} 為 {others[next_sq]}）"
            )
