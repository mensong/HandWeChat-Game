"""通用工具：时钟、时间格式化、数值格式化、文本与群标题规范化。"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

TRAILING_PUNCT = "。！？!?，,、~～…"


def make_clock(tz_name: str) -> Callable[[], datetime]:
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None
    if tz is None:
        tz = timezone(timedelta(hours=8))

    def now() -> datetime:
        return datetime.now(tz)

    now.tz = tz
    return now


def fmt_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _quantize(x, pattern: str) -> Decimal:
    return Decimal(str(x)).quantize(Decimal(pattern), rounding=ROUND_HALF_UP)


def round2(x) -> float:
    return float(_quantize(x, "0.01"))


def fmt_charm(x) -> str:
    return str(_quantize(x, "0.1"))


def normalize_text(text: str | None, allow_hash: bool = True) -> str:
    if text is None:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"\s+", " ", t).strip()
    if allow_hash and t.startswith("#"):
        t = t[1:].lstrip()
    t = t.rstrip(TRAILING_PUNCT).strip()
    return t


def normalize_title(title: str | None) -> str:
    """群标题规范化：NFKC、去掉全部空白（OCR 空格噪声）、去掉尾部成员数。

    例：`888 种田大队 (71)` / `888种田大队（71人）` 都规范化为 `888种田大队`。
    """
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[\(（]\d+人?[\)）]$", "", t)
    return t
