"""消息规范化与命令解析。

OCR 会吞掉/插入空格，因此解析前先把消息中的全部空白去掉，
再用"无空格语法"切分参数（昵称、礼物名、数字本身都不含空格）：

- 送礼@用户名 礼物名 [数量] → 送礼@是你的益达玫瑰2
  按礼物目录从最右侧匹配礼物名，其后的数字为数量，前缀为目标昵称
- 转账@用户名 数量 → 转账@张三100
  末尾连续数字为金额（昵称以数字结尾时无法区分，金额优先）
- 购买奴隶@用户名 / 给他(她)自由@用户名 → 购买奴隶@张三谢谢
  目标为 @ 后整段，由数据层做"精确 → 忽略大小写 → 已知玩家最长前缀"解析
"""
from __future__ import annotations

import re

from .config import Config
from .models import Command, Pat
from .util import TRAILING_PUNCT

EXACT_COMMANDS = {
    "我的金币": "my_coins",
    "签到": "sign_in",
    "金币榜": "coin_rank",
    "金币系统": "coins_help",
    "我的魅力": "my_charm",
    "魅力值": "my_charm",
    "魅力榜": "charm_rank",
    "魅力系统": "charm_help",
    "礼物列表": "gift_list",
    "礼物榜": "gift_rank",
    "礼物系统": "gifts_help",
    "奴隶打工": "slave_work",
    "我的奴隶": "my_slaves",
    "我要自由": "rebel",
    "奴隶系统": "slaves_help",
}

HELP_COMMANDS = {"coins_help", "charm_help", "gifts_help", "slaves_help"}

_PARAM_PATTERNS = [
    ("transfer", re.compile(r"^转账@(.+)$")),
    ("send_gift", re.compile(r"^送礼@(.+)$")),
    ("purchase_slave", re.compile(r"^购买奴隶@(.+)$")),
    ("release_slave", re.compile(r"^给(?:他|她)自由@(.+)$")),
]

USAGE_KEYWORDS = [
    ("转账", "转账@用户名 数量"),
    ("送礼", "送礼@用户名 礼物名 [数量]"),
    ("购买奴隶", "购买奴隶@用户名"),
    ("给他自由", "给他自由@用户名"),
    ("给她自由", "给他自由@用户名"),
]

USAGE_HINT_TEMPLATE = "指令格式不对。用法：{usage}"

MAX_RAW_TARGET = 40
MAX_PAT_NAME = 40

# 微信拍一拍是居中系统行：OCR 给的 sender 是"我"，参与者只能从正文解析。
# 兼容常用引号写法与 OCR 在"拍了拍"两侧插入的空格。
_PAT_RE = re.compile(
    r"^[“\"＂「『]\s*(?P<pat>.+?)\s*[”\"＂」』]\s*拍\s*了\s*拍\s*"
    r"[“\"＂「『]\s*(?P<patted>.+?)\s*[”\"＂」』](?P<what>.*)$",
    re.DOTALL,
)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _clean_target(raw: str) -> str | None:
    raw = raw.strip(TRAILING_PUNCT)
    if not raw or len(raw) > MAX_RAW_TARGET:
        return None
    if any(c in raw for c in "@#"):
        return None
    return raw


def _split_transfer(rest: str):
    m = re.match(r"^(.*?)(\d+)$", rest)
    if not m or not m.group(1):
        return None
    return m.group(1), int(m.group(2))


def _split_gift(rest: str, cfg: Config | None):
    """在去掉空格的参数串中按礼物目录切分，返回 (target, gift_name, count)。

    从最右侧的礼物名 occurrence 切分：前缀是目标昵称，紧随其后的
    数字（若有）是数量，再往后的文字视为闲聊忽略。找不到礼物名返回 None。
    """
    if cfg is None:
        return None
    low = rest.lower()
    best = None  # (end, pos, gift)
    for g in cfg.gifts:
        tokens = {g.name.lower()}
        tokens.update(a.lower() for a in g.aliases)
        for tok in tokens:
            pos = low.rfind(tok)
            if pos < 0:
                continue
            end = pos + len(tok)
            if best is None or end > best[0]:
                best = (end, pos, g)
    if best is None:
        return None
    end, pos, gift = best
    target = rest[:pos]
    m = re.match(r"(\d{1,3})", rest[end:])
    count = int(m.group(1)) if m else None
    return target, gift.name, count


def _clean_pat_name(raw: str) -> str | None:
    name = re.sub(r"\s+", "", raw)
    if not name or len(name) > MAX_PAT_NAME:
        return None
    return name


def parse_pat(text: str) -> Pat | None:
    """解析拍一拍：`“A”拍了拍“B”` / `“A”拍了拍“B”叫了一声“嗯~”`。

    只认带引号的格式；OCR 丢失引号时按普通消息忽略，避免闲聊误触发。
    """
    m = _PAT_RE.match(text)
    if not m:
        return None
    pat = _clean_pat_name(m.group("pat"))
    patted = _clean_pat_name(m.group("patted"))
    if pat is None or patted is None:
        return None
    return Pat(pat=pat, patted=patted, what=m.group("what").strip())


def parse(text: str, cfg: Config | None = None) -> Command | None:
    compact = _compact(text)
    if compact in EXACT_COMMANDS:
        return Command(name=EXACT_COMMANDS[compact])

    for name, regex in _PARAM_PATTERNS:
        m = regex.match(compact)
        if not m:
            continue
        rest = m.group(1)

        if name == "transfer":
            split = _split_transfer(rest)
            if split is None:
                return None
            target = _clean_target(split[0])
            if target is None:
                return None
            return Command(name=name, target=target, amount=split[1])

        if name == "send_gift":
            split = _split_gift(rest, cfg)
            if split is None:
                # 空格被吞后无法区分"缺礼物名"与"未知礼物名"，统一交给用法提示
                return None
            target, gift_name, count = split
            target = _clean_target(target)
            if target is None:
                return None
            return Command(name=name, target=target, gift=gift_name, count=count)

        # purchase / release：单参数，尾部可能粘连闲聊，
        # 由数据层做 精确 → 忽略大小写 → 已知玩家最长前缀 解析
        target = _clean_target(rest)
        if target is None:
            return None
        return Command(name=name, target=target)

    return None


def usage_hint(text: str) -> str | None:
    for kw, usage in USAGE_KEYWORDS:
        if text == kw:
            return USAGE_HINT_TEMPLATE.format(usage=usage)
        if text.startswith(kw) and len(text) > len(kw) and text[len(kw)] in " @":
            return USAGE_HINT_TEMPLATE.format(usage=usage)
    return None
