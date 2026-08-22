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
