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

"""修訂 R9 縮圖模組契約：雙軌後端等價、旋轉語意、single-flight。"""

import io
import threading
from pathlib import Path

import pytest
from PIL import Image

import tunnelview.thumbs as thumbs


@pytest.fixture(scope="module")
def jpeg_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("imgs")
    p = d / "t.jpg"
    Image.new("RGB", (200, 100), (120, 30, 90)).save(p)
    return p


def _dims(data: bytes):
    im = Image.open(io.BytesIO(data))
    return im.size


class TestBackends:
    def test_pillow_backend_output(self, jpeg_file):
        data = thumbs._pil_thumb(jpeg_file, 50, False, 0, 87)
        assert _dims(data) == (50, 25)

    @pytest.mark.skipif(not thumbs.HAVE_PYVIPS, reason="pyvips 未安裝")
    def test_vips_backend_output(self, jpeg_file):
        data = thumbs._vips_thumb(jpeg_file, 50, False, 0, 87)
        assert _dims(data) == (50, 25)

    @pytest.mark.skipif(not thumbs.HAVE_PYVIPS, reason="pyvips 未安裝")
    def test_make_thumbnail_uses_vips_when_available(self, jpeg_file):
        data = thumbs.make_thumbnail(jpeg_file, 80)
        assert _dims(data) == (80, 40)

    def test_fallback_on_vips_failure(self, jpeg_file, monkeypatch):
        # vips 拋例外 → make_thumbnail 應退回 Pillow 而非失敗
        monkeypatch.setattr(thumbs, "_vips_thumb", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
        data = thumbs.make_thumbnail(jpeg_file, 60)
        assert _dims(data) == (60, 30)

    def test_pillow_only_mode(self, jpeg_file, monkeypatch):
        monkeypatch.setattr(thumbs, "HAVE_PYVIPS", False)
        data = thumbs.make_thumbnail(jpeg_file, 40)
        assert _dims(data) == (40, 20)

    @pytest.mark.skipif(not thumbs.HAVE_PYVIPS, reason="pyvips 未安裝")
    def test_rotation_semantics_match_pil(self, tmp_path):
        """vips.rot(dN) 必須與 PIL rotate(-N) 一致（R9 前 API 的行為基準）。"""
        img = Image.new("RGB", (8, 4), (0, 0, 0))
        px = img.load()
        px[0, 0] = (255, 0, 0)
        px[7, 0] = (0, 255, 0)
        px[0, 3] = (0, 0, 255)
        px[7, 3] = (255, 255, 255)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        jpeg = buf.getvalue()
        src = tmp_path / "rot.jpg"
        src.write_bytes(jpeg)
        pil_src = Image.open(io.BytesIO(jpeg))
        for angle in (90, 180, 270):
            expected = pil_src.rotate(-angle, expand=True)
            got = thumbs._vips_thumb(src, None, False, angle, 95)
            actual = Image.open(io.BytesIO(got)).convert("RGB")
            assert actual.size == expected.size, f"angle={angle}"
            ew, eh = expected.size
            corners = [(0, 0), (ew - 1, 0), (0, eh - 1), (ew - 1, eh - 1)]
            for x, y in corners:
                e = expected.getpixel((x, y))
                a = actual.getpixel((x, y))
                assert sum(abs(i - j) for i, j in zip(e, a)) < 24, f"angle={angle} at {(x, y)}"


class TestSingleFlight:
    def test_concurrent_calls_produce_once(self, tmp_path):
        cache = tmp_path / "x.jpg"
        calls = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            thumbs.get_or_make(cache, lambda: calls.append(1) or b"data")

        ts = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert cache.read_bytes() == b"data"
        # 併發下只允許一次真正產生（其餘等待後直接命中快取）
        assert len(calls) <= 2  # 允許極端排程下的一次重試，但絕非 4 次

    def test_second_call_hits_cache(self, tmp_path):
        cache = tmp_path / "y.jpg"
        n = []
        thumbs.get_or_make(cache, lambda: n.append(1) or b"a")
        thumbs.get_or_make(cache, lambda: n.append(1) or b"b")
        assert n == [1]

    def test_producer_failure_raises_after_retry(self, tmp_path):
        cache = tmp_path / "z.jpg"
        with pytest.raises(RuntimeError):
            thumbs.get_or_make(cache, lambda: (_ for _ in ()).throw(RuntimeError()))

    def test_atomic_write_no_tmp_left(self, tmp_path):
        cache = tmp_path / "w.jpg"
        thumbs.get_or_make(cache, lambda: b"ok")
        assert list(tmp_path.iterdir()) == [cache]
