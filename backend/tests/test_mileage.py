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

import pytest

from tunnelview.mileage import MileageParseError, format_mileage, parse_mileage


class TestParseMileage:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("K23+150", 23150),
            ("23K+150", 23150),
            ("23+150", 23150),
            ("23150", 23150),
            ("k7+8", 7008),
            (" K 23 + 150 ", 23150),
            ("0", 0),
            ("007K+005", 7005),
        ],
    )
    def test_accepts_all_supported_formats(self, text, expected):
        assert parse_mileage(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            None,
            "K23",
            "+150",
            "-100",
            "K23+1500",
            "K23+150.5",
            "23.5",
            "abc",
            "KK23+150",
            "K-23+150",
        ],
    )
    def test_rejects_invalid_input(self, text):
        with pytest.raises(MileageParseError):
            parse_mileage(text)


class TestFormatMileage:
    @pytest.mark.parametrize(
        ("meters", "expected"),
        [
            (0, "K0+000"),
            (7, "K0+007"),
            (23000, "K23+000"),
            (23150, "K23+150"),
            (123456, "K123+456"),
        ],
    )
    def test_canonical_display(self, meters, expected):
        assert format_mileage(meters) == expected

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            format_mileage(-1)

    def test_round_trip(self):
        assert format_mileage(parse_mileage("12K+034")) == "K12+034"
