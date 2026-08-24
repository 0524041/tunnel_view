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

"""縮圖生成服務：pyvips（libvips）優先、Pillow 自動退回；single-flight 防重複解碼。

pyvips 以 uv 安裝「pyvips[binary]」即可（自帶 libvips binary wheel，WSL 免系統套件）。
實測 libvips 對大量 JPEG 縮放約為 Pillow 的 4.5 倍速、常數級記憶體。
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image, ImageOps

try:
    import pyvips as _pyvips

    HAVE_PYVIPS = True
except Exception:  # pragma: no cover - 環境無 libvips 時走 Pillow
    _pyvips = None
    HAVE_PYVIPS = False

THUMB_QUALITY = 87
ORIG_QUALITY = 92

_ROT_MAP = {90: "d90", 180: "d180", 270: "d270"}

# ---- single-flight：同 key 只允許一個執行緒生成，其餘等待後重查快取 ----
_sf_cond = threading.Condition()
_sf_keys: set[str] = set()


def single_flight(key: str, fn) -> None:
    """確保同 key 的 fn 在併發下只被一個執行緒執行一次；等待者於完成後返回。"""
    with _sf_cond:
        while key in _sf_keys:
            _sf_cond.wait()
        _sf_keys.add(key)
    try:
        fn()
    finally:
        with _sf_cond:
            _sf_keys.discard(key)
            _sf_cond.notify_all()


def get_or_make(cache_file: Path, produce) -> Path:
    """回傳存在的快取檔；不存在時以 single-flight 生成（原子寫入）。

    等待者在生成者完成後會重查快取——同 key 併發只真正生成一次。
    兩輪皆失敗才丟出例外。
    """
    last_err: Exception | None = None
    for _ in range(2):
        if cache_file.exists():
            return cache_file

        def _produce():
            if cache_file.exists():
                return  # 前一位已生成完成，免重做
            data = produce()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_name(cache_file.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(cache_file)

        try:
            single_flight(str(cache_file), _produce)
        except Exception as e:  # noqa: BLE001 - 由呼叫端語意統一為縮圖失敗
            last_err = e
        else:
            if cache_file.exists():
                return cache_file
    if cache_file.exists():
        return cache_file
    if last_err is not None:
        raise RuntimeError(f"縮圖生成失敗：{cache_file}（{last_err}）")
    raise RuntimeError(f"縮圖生成失敗：{cache_file}")


def make_thumbnail(
    path: Path | str,
    target_w: int | None,
    *,
    needs_transpose: bool = False,
    extra_rotation: int = 0,
    quality: int | None = None,
) -> bytes:
    """生成 JPEG 縮圖位元組串。pyvips 可用時優先，任何例外退回 Pillow。

    行為與舊版端點內嵌邏輯一致：transpose → 額外旋轉（順時針）→ 縮放至 target_w。
    """
    q = quality if quality is not None else THUMB_QUALITY
    if HAVE_PYVIPS:
        try:
            return _vips_thumb(path, target_w, needs_transpose, extra_rotation, q)
        except Exception:
            pass
    return _pil_thumb(path, target_w, needs_transpose, extra_rotation, q)


def _vips_thumb(path, target_w, needs_transpose, extra_rotation, q) -> bytes:
    access = "random" if (needs_transpose or extra_rotation) else "sequential"
    im = _pyvips.Image.new_from_file(str(path), access=access)
    if needs_transpose:
        im = im.autorot()
    extra = int(extra_rotation or 0) % 360
    if extra:
        im = im.rot(_ROT_MAP[extra])
    if target_w:
        # 語意＝輸出圖目標寬度（與 Pillow 版一致：先旋轉後縮放）。
        # 不用 thumbnail_image——其 auto_rotate 幾何以未旋轉尺寸計算，會破壞此語意。
        scale = target_w / im.width
        if scale != 1:
            im = im.resize(scale)
    return im.jpegsave_buffer(Q=q)


def _pil_thumb(path, target_w, needs_transpose, extra_rotation, q) -> bytes:
    img = Image.open(path)
    if needs_transpose:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    else:
        if target_w:
            img.draft("RGB", (target_w * 2, target_w * 2))
        img = img.convert("RGB")
    if extra_rotation:
        img = img.rotate(-extra_rotation, expand=True)
    if target_w:
        ratio = target_w / img.width
        img = img.resize((target_w, max(1, round(img.height * ratio))), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return buf.getvalue()
