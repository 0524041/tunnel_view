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

"""檔案系統工具：平台磁碟根列舉。"""

from __future__ import annotations

import os


def platform_roots(is_windows: bool | None = None, drives_mask: int | None = None) -> list[str]:
    """回傳頂層可瀏覽根。

    Windows：以 GetLogicalDrives 位元遮罩列舉存在的磁碟代號（避免對斷線
    網路碟做存在性探測造成凍結）；drives_mask 可注入以便測試。
    POSIX：固定 ['/']。
    """
    if is_windows is None:
        is_windows = os.name == "nt"
    if not is_windows:
        return ["/"]
    if drives_mask is None:
        try:
            import ctypes

            drives_mask = int(ctypes.windll.kernel32.GetLogicalDrives())
        except Exception:
            return []
    return [
        f"{chr(65 + i)}:\\"
        for i in range(26)
        if (drives_mask >> i) & 1
    ]
