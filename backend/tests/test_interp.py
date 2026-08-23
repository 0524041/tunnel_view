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

"""內插引擎行為契約。

規則：
- 無錨點 → 依群組序列在起迄里程間等分。
- 有錨點 → 錨點間依序列線性內插；首末錨點外以最近段斜率線性外插，
  外插結果夾限（clamp）在起迄走廊內。
- 方向：由起訖數值本身表達（end < start 即遞減），引擎不另取方向參數。
- 防呆：新錨點必須「嚴格」落在前後鄰近錨點之間（依方向），且在起迄範圍內。
"""

import pytest

from tunnelview.interp import (
    AnchorOrderError,
    AnchorRangeError,
    check_anchor,
    compute_all,
)


class TestEvenSpread:
    def test_no_anchors_even_spread(self):
        result = compute_all(group_count=10, start_m=0, end_m=900, anchors={})
        assert result == {i: i * 100 for i in range(10)}

    def test_even_spread_rounds_deterministically(self):
        result = compute_all(group_count=4, start_m=0, end_m=1000, anchors={})
        assert result[1] == 333
        assert result[2] == 667

    def test_decreasing_direction_spread(self):
        result = compute_all(group_count=3, start_m=9000, end_m=0, anchors={})
        assert result == {0: 9000, 1: 4500, 2: 0}

    def test_single_group_gets_start(self):
        assert compute_all(group_count=1, start_m=500, end_m=600, anchors={}) == {0: 500}


class TestAnchorInterpolation:
    def test_linear_between_anchors(self):
        result = compute_all(group_count=10, start_m=0, end_m=2000, anchors={2: 200, 7: 1200})
        assert result[4] == 600
        assert result[2] == 200
        assert result[7] == 1200

    def test_extrapolation_before_first_anchor_clamped_to_corridor(self):
        # 錨點集中後段，斜率 200/群，往前外插 g0、g1 會越過起點 → 夾限
        result = compute_all(group_count=10, start_m=0, end_m=2000, anchors={5: 1000, 8: 1600})
        assert result[0] >= 0
        assert result[9] <= 2000

    def test_anchors_at_both_ends_define_whole_line(self):
        result = compute_all(group_count=5, start_m=0, end_m=1000, anchors={0: 0, 4: 1000})
        assert result == {0: 0, 1: 250, 2: 500, 3: 750, 4: 1000}

    def test_single_anchor_others_follow_nearest_slope_or_even_fallback(self):
        # 單錨點無斜率可用：錨點外的區段退回以「全域等分斜率」外插
        result = compute_all(group_count=5, start_m=0, end_m=1000, anchors={2: 500})
        assert result[2] == 500
        assert result[0] == 0
        assert result[4] == 1000


class TestAnchorValidation:
    def test_value_between_neighbors_accepted(self):
        check_anchor(5, 550, group_count=10, start_m=0, end_m=1000, anchors={3: 300, 8: 800})

    def test_value_below_previous_rejected(self):
        with pytest.raises(AnchorOrderError):
            check_anchor(5, 250, group_count=10, start_m=0, end_m=1000, anchors={3: 300, 8: 800})

    def test_equal_to_neighbor_rejected_strictly(self):
        with pytest.raises(AnchorOrderError):
            check_anchor(5, 300, group_count=10, start_m=0, end_m=1000, anchors={3: 300, 8: 800})

    def test_above_next_rejected(self):
        with pytest.raises(AnchorOrderError):
            check_anchor(5, 850, group_count=10, start_m=0, end_m=1000, anchors={3: 300, 8: 800})

    def test_decreasing_direction_order_enforced(self):
        anchors = {2: 7000, 6: 3000}
        check_anchor(4, 4500, group_count=10, start_m=9000, end_m=0, anchors=anchors)
        # 低於後錨點（3000）→ 越過下一個錨點，違反方向
        with pytest.raises(AnchorOrderError):
            check_anchor(4, 2500, group_count=10, start_m=9000, end_m=0, anchors=anchors)
        with pytest.raises(AnchorOrderError):
            check_anchor(4, 7500, group_count=10, start_m=9000, end_m=0, anchors=anchors)

    def test_out_of_tunnel_range_rejected(self):
        with pytest.raises(AnchorRangeError):
            check_anchor(5, 99999, group_count=10, start_m=0, end_m=1000, anchors={})
        with pytest.raises(AnchorRangeError):
            check_anchor(5, -5, group_count=10, start_m=0, end_m=1000, anchors={})

    def test_no_neighbors_only_range_checked(self):
        check_anchor(0, 42, group_count=10, start_m=0, end_m=1000, anchors={})
