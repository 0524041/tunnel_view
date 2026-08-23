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

"""時間對齊引擎（單調一對一序列對齊）。

公開介面：align(camera_series_list, tolerance_seconds) -> AlignmentResult

語意：
- offsets_seconds[i]：加到第 i 台相機原始 EXIF 時間上的秒數，得到校正時間。
- 群組＝同一快門事件；每台相機在單一群組至多一張（同機雙拍自動另開新群組）。
- 演算法：以最早照片求初始 Δt → 完整度搜尋修正整體位移（救回首張漏拍）→
  對基準相機的配對差取中位數迭代精煉（吸收 EXIF 秒級量化偏移）→
  全域時間軸掃描配對 → 殘差超過容差 60% 旗標異常照片。
- 容差建議值：實測（Sony A7RIV 群組、EXIF 秒級）以 2.0 秒最穩；0.5 秒會被
  量化誤差撕裂。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_ORIGIN = datetime(2000, 1, 1)
_FLAG_RATIO = 0.6
_SEARCH_STEPS = (-2, -1, 0, 1, 2)
_MAX_FIRST_ALIGN = 8
_REFINE_ROUNDS = 3
_MIN_REFINE_PAIRS = 3
_REFINE_EPS = 1e-4


def _time_lookup(series_list: list[CameraSeries], offsets: dict[int, float]) -> dict[tuple[int, str], float]:
    return {
        (s.camera_index, p.photo_id): _to_seconds(p.t) + offsets[s.camera_index]
        for s in series_list
        for p in s.photos
    }


@dataclass(frozen=True)
class PhotoStamp:
    photo_id: str
    t: datetime


@dataclass(frozen=True)
class CameraSeries:
    camera_index: int
    photos: list[PhotoStamp]


@dataclass(frozen=True)
class AlignedGroup:
    seq: int
    corrected_time: datetime
    members: dict[int, str]
    missing: list[int]
    flagged: list[int]


@dataclass(frozen=True)
class AlignmentResult:
    reference_camera: int
    offsets_seconds: dict[int, float]
    groups: list[AlignedGroup]

    @property
    def total_photos(self) -> int:
        return sum(len(g.members) for g in self.groups)


def _to_seconds(dt: datetime) -> float:
    return (dt - _ORIGIN).total_seconds()


def _sweep(events: list[tuple[float, int, str]], tolerance: float) -> list[dict]:
    """依校正時間掃描合併。events 已排序。回傳 [{t0, members: {cam: photo_id}}]。"""
    groups: list[dict] = []
    current: dict | None = None
    for t, cam, pid in events:
        if current is not None and cam not in current["members"] and abs(t - current["t0"]) <= tolerance:
            current["members"][cam] = pid
        else:
            current = {"t0": t, "members": {cam: pid}}
            groups.append(current)
    return groups


def _build_events(series_list: list[CameraSeries], offsets: dict[int, float]):
    events = []
    for s in series_list:
        off = offsets[s.camera_index]
        for p in s.photos:
            events.append((_to_seconds(p.t) + off, s.camera_index, p.photo_id))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def align(camera_series: list[CameraSeries], tolerance_seconds: float) -> AlignmentResult:
    if not camera_series:
        raise ValueError("至少需要一個相機序列")
    if tolerance_seconds <= 0:
        raise ValueError("容差必須為正數")

    series_list = []
    for s in camera_series:
        photos = sorted(s.photos, key=lambda p: (_to_seconds(p.t), p.photo_id))
        series_list.append(CameraSeries(s.camera_index, photos))

    ref = max(series_list, key=lambda s: (len(s.photos), -s.camera_index))
    ref_first = _to_seconds(ref.photos[0].t)

    offsets = {}
    for s in series_list:
        offsets[s.camera_index] = ref_first - _to_seconds(s.photos[0].t)

    # 完整度搜尋：對各非基準相機，候選偏移包含——
    #   (a) 將該機第一張對齊基準相機前 K 個事件（救回「首張漏拍」造成的整體位移）
    #   (b) 初始偏移 ± j × 該機中位間隔（吸收亞事件級誤差）
    # 評分：多相機群組數最多者勝，平手時取平均殘差較小者。
    ref_times = [_to_seconds(p.t) for p in ref.photos]
    for s in series_list:
        idx = s.camera_index
        if idx == ref.camera_index or len(s.photos) < 2:
            continue

        first_raw = _to_seconds(s.photos[0].t)
        candidates = [rt - first_raw for rt in ref_times[:_MAX_FIRST_ALIGN]]

        raw_ts = [_to_seconds(p.t) for p in s.photos]
        gaps = [b - a for a, b in zip(raw_ts, raw_ts[1:])]
        step = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
        if step > 0:
            candidates += [offsets[idx] + j * step for j in _SEARCH_STEPS]
        candidates.append(offsets[idx])

        best = None
        for cand in dict.fromkeys(candidates):
            trial = dict(offsets)
            trial[idx] = cand
            groups = _sweep(_build_events(series_list, trial), tolerance_seconds)
            t_of_trial = _time_lookup(series_list, trial)
            residuals = [
                abs(t_of_trial[(cam, pid)] - g["t0"])
                for g in groups
                for cam, pid in g["members"].items()
            ]
            score = (
                sum(len(g["members"]) - 1 for g in groups if len(g["members"]) >= 2),
                -sum(residuals) / len(residuals),
            )
            if best is None or score > best[0]:
                best = (score, trial)
        assert best is not None
        offsets = best[1]

    # 迭代精煉：對各非基準相機，取其與基準相機同群組配對的校正時間差平均，
    # 扣除該偏誤後重掃。修正秒級 EXIF 量化造成的亞秒系統偏移。
    for _ in range(_REFINE_ROUNDS):
        raw_groups = _sweep(_build_events(series_list, offsets), tolerance_seconds)
        t_of = _time_lookup(series_list, offsets)
        new_offsets = dict(offsets)
        for s in series_list:
            idx = s.camera_index
            if idx == ref.camera_index:
                continue
            deltas = []
            for g in raw_groups:
                if idx in g["members"] and ref.camera_index in g["members"]:
                    deltas.append(t_of[(idx, g["members"][idx])] - t_of[(ref.camera_index, g["members"][ref.camera_index])])
            if len(deltas) < _MIN_REFINE_PAIRS:
                continue
            bias = sorted(deltas)[len(deltas) // 2]
            if abs(bias) < _REFINE_EPS:
                continue
            new_offsets[idx] = offsets[idx] - bias
        if new_offsets == offsets:
            break
        offsets = new_offsets

    events = _build_events(series_list, offsets)
    raw_groups = _sweep(events, tolerance_seconds)

    all_cameras = sorted(s.camera_index for s in series_list)
    t_of = _time_lookup(series_list, offsets)

    result_groups = []
    threshold = tolerance_seconds * _FLAG_RATIO
    for seq, g in enumerate(raw_groups):
        flagged = sorted(cam for cam, pid in g["members"].items() if abs(t_of[(cam, pid)] - g["t0"]) > threshold)
        missing = [c for c in all_cameras if c not in g["members"]]
        result_groups.append(
            AlignedGroup(
                seq=seq,
                corrected_time=_ORIGIN + timedelta(seconds=g["t0"]),
                members=dict(g["members"]),
                missing=missing,
                flagged=flagged,
            )
        )

    return AlignmentResult(
        reference_camera=ref.camera_index,
        offsets_seconds=dict(sorted(offsets.items())),
        groups=result_groups,
    )
