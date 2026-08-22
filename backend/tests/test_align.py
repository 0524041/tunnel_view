"""對齊引擎行為契約。

輸入：各相機照片序列（photo_id + naive EXIF 時間）。
輸出：群組劃分、各機時間偏移、缺照、殘差旗標。
不變量：每張照片恰好歸入一個群組；同一群組同一相機至多一張。
"""

from datetime import datetime, timedelta

from tunnelview.align import align

BASE = datetime(2026, 5, 28, 20, 49, 0)


def ts(*seconds_list):
    """秒數清單 → PhotoStamp 友善的 datetime 清單。"""
    return [BASE + timedelta(seconds=s) for s in seconds_list]


def series(camera_index, seconds_list):
    from tunnelview.align import CameraSeries, PhotoStamp

    return CameraSeries(
        camera_index=camera_index,
        photos=[PhotoStamp(photo_id=f"c{camera_index}_{i}", t=t) for i, t in enumerate(ts(*seconds_list))],
    )


class TestBasicGrouping:
    def test_perfectly_synced_cameras_group_together(self):
        result = align([series(0, [0, 10, 20]), series(1, [0.2, 10.1, 19.9])], tolerance_seconds=0.5)

        assert result.reference_camera == 0
        assert len(result.groups) == 3
        assert result.groups[0].members == {0: "c0_0", 1: "c1_0"}
        assert result.groups[1].members == {0: "c0_1", 1: "c1_1"}
        assert result.groups[2].members == {0: "c0_2", 1: "c1_2"}
        assert all(g.missing == [] for g in result.groups)

    def test_missing_slot_becomes_null(self):
        result = align([series(0, [0, 10, 20]), series(1, [0.2, 10.1])], tolerance_seconds=0.5)

        assert len(result.groups) == 3
        assert result.groups[2].members == {0: "c0_2"}
        assert result.groups[2].missing == [1]

    def test_unsorted_input_is_sorted_internally(self):
        shuffled = [series(0, [20, 0, 10]), series(1, [19.9, 0.2, 10.1])]
        result = align(shuffled, tolerance_seconds=0.5)

        times = [g.corrected_time for g in result.groups]
        assert times == sorted(times)
        assert result.groups[0].members == {0: "c0_1", 1: "c1_1"}

    def test_single_camera_each_photo_own_group(self):
        result = align([series(0, [0, 10, 20])], tolerance_seconds=0.5)

        assert len(result.groups) == 3
        assert result.reference_camera == 0


class TestClockOffsets:
    def test_constant_clock_shift_is_absorbed(self):
        result = align([series(0, [0, 10, 20]), series(1, [100.3, 109.9, 119.8])], tolerance_seconds=0.5)

        assert result.offsets_seconds[0] == 0
        # fixture 各事件真實偏移 +100 秒，各張含 ±0.5 秒內抖動；恢復值應落在抖動範圍
        assert -101.0 < result.offsets_seconds[1] < -99.0
        assert all(set(g.members.values()) == {"c0_%d" % i, "c1_%d" % i} for i, g in enumerate(result.groups))

    def test_reference_camera_is_the_most_complete_series(self):
        result = align([series(0, [0, 10]), series(1, [0.1, 10.1, 20.1, 30.1])], tolerance_seconds=0.5)

        assert result.reference_camera == 1
        assert result.offsets_seconds[1] == 0
        assert set(result.groups[0].members.keys()) == {0, 1}


class TestFirstShotMissingRecovery:
    def test_camera_that_missed_first_event_realigned_by_search(self):
        # cam0（基準）事件格：0, 8, 17, 31（不等間隔）。cam1 快門慢了第一發且時鐘快 100 秒。
        result = align([series(0, [0, 8, 17, 31]), series(1, [108, 117, 131])], tolerance_seconds=0.5)

        # cam1 的三張應分別配到事件 8, 17, 31；事件 0 只有 cam0
        assert result.groups[0].members == {0: "c0_0"}
        assert result.groups[0].missing == [1]
        assert result.groups[1].members == {0: "c0_1", 1: "c1_0"}
        assert result.groups[2].members == {0: "c0_2", 1: "c1_1"}
        assert result.groups[3].members == {0: "c0_3", 1: "c1_2"}

    def test_second_level_quantization_absorbed(self):
        # EXIF 只有整秒解析度：真實偏移 +0.6 秒量化後，同事件時間戳差 {0,1} 秒跳動。
        result = align([series(0, [0, 10, 20, 30]), series(1, [1, 10, 21, 30])], tolerance_seconds=2.0)

        assert len(result.groups) == 4
        assert all(len(g.members) == 2 for g in result.groups)
        assert all(g.flagged == [] for g in result.groups)


class TestInvariantsAndFlags:
    def test_same_camera_double_press_never_merges(self):
        result = align([series(0, [0, 0.2, 10]), series(1, [10.1])], tolerance_seconds=0.5)

        assert len(result.groups) == 3
        for group in result.groups:
            assert len(set(group.members.keys())) == len(group.members)

    def test_every_photo_assigned_exactly_once(self):
        result = align([series(0, [0, 10, 20, 30]), series(1, [0.1, 25, 41])], tolerance_seconds=0.5)

        assigned = [pid for g in result.groups for pid in g.members.values()]
        assert sorted(assigned) == ["c0_0", "c0_1", "c0_2", "c0_3", "c1_0", "c1_1", "c1_2"]

    def test_one_off_outlier_within_tolerance_is_flagged(self):
        # cam1 整體只慢 0.05 秒，但第 2 張慢了 0.45 秒（超過容差 60%＝0.3 秒）
        result = align([series(0, [0, 10, 20]), series(1, [0.05, 10.45, 20.05])], tolerance_seconds=0.5)

        flagged_pairs = {(g.seq, cam) for g in result.groups for cam in g.flagged}
        assert any(cam == 1 for _, cam in flagged_pairs)
        # 其餘兩張不被旗標
        normal = [g.flagged for g in result.groups if g.members.get(1) == "c1_0"]
        assert normal and normal[0] == []

    def test_systematic_small_offset_not_flagged_after_calibration(self):
        result = align([series(0, [0, 10, 20]), series(1, [0.15, 10.15, 20.15])], tolerance_seconds=0.5)

        assert all(g.flagged == [] for g in result.groups)

    def test_empty_input_raises(self):
        import pytest

        with pytest.raises(ValueError):
            align([], tolerance_seconds=0.5)
