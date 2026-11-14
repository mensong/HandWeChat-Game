"""消息规范化与命令解析。"""
from __future__ import annotations

import re

from .models import Command
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

PARAM_PATTERNS = [
    ("transfer",
     re.compile(r"^转账\s*@\s*(?P<target>\S+)\s+(?P<amount>\d+)(?:\s+.*)?$"),
     "转账@用户名 数量"),
    ("send_gift",
     re.compile(r"^送礼\s*@\s*(?P<target>\S+)\s+(?P<gift>\S+?)(?:\s+(?P<count>\d+))?(?:\s+.*)?$"),
     "送礼@用户名 礼物名 [数量]"),
    ("purchase_slave",
     re.compile(r"^购买奴隶\s*@\s*(?P<target>\S+)(?:\s+.*)?$"),
     "购买奴隶@用户名"),
    ("release_slave",
     re.compile(r"^给(?:他|她)自由\s*@\s*(?P<target>\S+)(?:\s+.*)?$"),
     "给他自由@用户名 / 给她自由@用户名"),
]

USAGE_KEYWORDS = [
    ("转账", "转账@用户名 数量"),
    ("送礼", "送礼@用户名 礼物名 [数量]"),
    ("购买奴隶", "购买奴隶@用户名"),
    ("给他自由", "给他自由@用户名"),
    ("给她自由", "给他自由@用户名"),
]

USAGE_HINT_TEMPLATE = "指令格式不对。用法：{usage}"


def _clean_target(token: str) -> str | None:
    t = token.strip(TRAILING_PUNCT)
    if not t or len(t) > 20:
        return None
    if any(c in t for c in "@#") or any(c.isspace() for c in t):
        return None
    return t


def parse(text: str) -> Command | None:
    if text in EXACT_COMMANDS:
        return Command(name=EXACT_COMMANDS[text])

    for name, regex, _usage in PARAM_PATTERNS:
        m = regex.match(text)
        if not m:
            continue
        target = _clean_target(m.group("target"))
        if target is None:
            return None
        cmd = Command(name=name, target=target)
        if name == "transfer":
            cmd.amount = int(m.group("amount"))
        elif name == "send_gift":
            cmd.gift = m.group("gift").strip(TRAILING_PUNCT)
            if not cmd.gift:
                return None
            if m.group("count") is not None:
                cmd.count = int(m.group("count"))
        return cmd
    return None


def usage_hint(text: str) -> str | None:
    for kw, usage in USAGE_KEYWORDS:
        if text == kw:
            return USAGE_HINT_TEMPLATE.format(usage=usage)
        if text.startswith(kw) and len(text) > len(kw) and text[len(kw)] in " @":
            return USAGE_HINT_TEMPLATE.format(usage=usage)
    return None
