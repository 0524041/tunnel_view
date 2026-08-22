"""里程（樁號）解析與格式化。

規格：接受 `K23+150`、`23K+150`、`23+150`、`23150` 四種輸入，
一律轉為整數公尺；不支援小數。顯示格式統一為 `K23+150`。
"""

import re

_PATTERN = re.compile(
    r"^(?:K(?P<k1>\d+)\+(?P<m1>\d{1,3})|(?P<k2>\d+)K\+(?P<m2>\d{1,3})|(?P<k3>\d+)\+(?P<m3>\d{1,3})|(?P<m4>\d+))$",
    re.IGNORECASE,
)


class MileageParseError(ValueError):
    """輸入不符合任何支援的樁號格式。"""


def parse_mileage(text: str) -> int:
    """將樁號字串解析為整數公尺。"""
    if text is None:
        raise MileageParseError("里程不可為空")
    s = text.strip().replace(" ", "").upper()
    m = _PATTERN.match(s)
    if not m:
        raise MileageParseError(f"無法解析里程：{text!r}")
    km = m.group("k1") or m.group("k2") or m.group("k3") or "0"
    meters_part = m.group("m1") or m.group("m2") or m.group("m3")
    if meters_part is None:
        return int(m.group("m4"))
    return int(km) * 1000 + int(meters_part)


def format_mileage(meters: int) -> str:
    """整數公尺 → 標準樁號顯示（K23+150）。"""
    if meters < 0:
        raise ValueError(f"里程不可為負：{meters}")
    km, rest = divmod(int(meters), 1000)
    return f"K{km}+{rest:03d}"
