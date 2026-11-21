"""消息规范化与命令解析。

OCR 会吞掉/插入空格，因此解析前先把消息中的全部空白去掉，
再用"无空格语法"切分参数（昵称、礼物名、数字本身都不含空格）：

- 送礼@用户名 礼物名 [数量] → 送礼@是你的益达玫瑰2
  按礼物目录从最右侧匹配礼物名，其后的数字为数量，前缀为目标昵称
- 转账@用户名 数量 → 转账@张三100
  末尾连续数字为金额（昵称以数字结尾时无法区分，金额优先）
- 购买奴隶@用户名 / 给他(她)自由@用户名 → 购买奴隶@张三谢谢
  目标为 @ 后整段，由数据层做"精确 → 忽略大小写 → 已知玩家最长前缀"解析
- 指令别名（command_aliases 配置）：如 {"购买奴隶": ["购买", "买下"]}，
  对普通形式与 @用户名 指令 前缀形式同样生效；canonical 关键字优先于别名
"""
from __future__ import annotations

import re

from .config import Config
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
    "调教所有奴隶": "train_all_slaves",
    "奴隶系统": "slaves_help",
}

HELP_COMMANDS = {"coins_help", "charm_help", "gifts_help", "slaves_help"}

# 带目标参数的指令：canonical 关键字 → 命令名
_PARAM_SPECS = [
    ("转账", "transfer"),
    ("送礼", "send_gift"),
    ("购买奴隶", "purchase_slave"),
    ("给他自由", "release_slave"),
    ("给她自由", "release_slave"),
    ("调教", "train_slave"),
    ("赎身", "ransom_slave"),
]

USAGE_KEYWORDS = [
    ("转账", "转账@用户名 数量"),
    ("送礼", "送礼@用户名 礼物名 [数量]"),
    ("购买奴隶", "购买奴隶@用户名"),
    ("给他自由", "给他自由@用户名"),
    ("给她自由", "给他自由@用户名"),
    ("调教", "调教@奴隶名"),
    ("赎身", "赎身@用户名"),
]

USAGE_HINT_TEMPLATE = "指令格式不对。用法：{usage}"

MAX_RAW_TARGET = 40

# @ 前缀形式：@用户名 指令（如 @李四签到 / @李四购买奴隶）
MENTION_QUERY_COMMANDS = {"my_coins", "my_charm", "my_slaves"}
MENTION_TARGET_COMMANDS = {"purchase_slave", "release_slave", "train_slave",
                           "ransom_slave", "transfer", "send_gift"}
MENTION_CMD_LABELS = {
    "sign_in": "签到", "slave_work": "奴隶打工", "rebel": "我要自由",
    "my_coins": "我的金币", "my_charm": "我的魅力", "my_slaves": "我的奴隶",
    "coin_rank": "金币榜", "charm_rank": "魅力榜", "gift_rank": "礼物榜",
    "gift_list": "礼物列表", "coins_help": "金币系统", "charm_help": "魅力系统",
    "gifts_help": "礼物系统", "slaves_help": "奴隶系统",
    "train_all_slaves": "调教所有奴隶",
}

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


def keyword_table(cfg: Config | None) -> list[tuple[str, str, str, str]]:
    """构建关键字表 [(keyword, command_name, kind, canonical_keyword)]。

    kind: exact（整句匹配）/ param（前缀 + @参数）。
    command_aliases 配置为 别名 → 规范关键字；与已有关键字冲突的别名忽略。
    按关键字长度降序排序（canonical 优先于其子串别名），保证
    "购买奴隶" 不会被别名 "购买" 抢先匹配。
    """
    table = []
    for kw, name in EXACT_COMMANDS.items():
        table.append((kw, name, "exact", kw))
    for kw, name in _PARAM_SPECS:
        table.append((kw, name, "param", kw))
    if cfg is not None:
        aliases = cfg.get("command_aliases")
        if isinstance(aliases, dict):
            known = {kw for kw, _, _, _ in table}
            for canonical, alist in aliases.items():
                if (not isinstance(canonical, str) or canonical not in known
                        or not isinstance(alist, list)):
                    continue  # 未知的规范指令名直接忽略
                for alias in alist:
                    if not isinstance(alias, str) or not alias or alias in known:
                        continue
                    if canonical in EXACT_COMMANDS:
                        table.append((alias, EXACT_COMMANDS[canonical], "exact", canonical))
                    else:
                        cname = next(name for ckw, name in _PARAM_SPECS if ckw == canonical)
                        table.append((alias, cname, "param", canonical))
    table.sort(key=lambda e: (-len(e[0]), e[0] != e[3], e[0]))
    return table


def _build_param_command(name: str, rest: str, cfg: Config | None,
                         target: str | None = None) -> Command | None:
    """构造带目标指令的 Command。

    rest 为关键字之后的参数串（已去空格）。target 为 @ 前缀形式
    （@用户名 指令）携带的目标；标准形式 rest 以 @ 开头、目标取自 rest。
    """
    if name == "transfer":
        if rest.startswith("@"):
            split = _split_transfer(rest[1:])
            if split is None:
                return None
            t = _clean_target(split[0]) or target
            if t is None:
                return None
            return Command(name=name, target=t, amount=split[1])
        m = re.match(r"^(\d+)$", rest)
        if m is None or target is None:
            return None
        return Command(name=name, target=target, amount=int(m.group(1)))
    if name == "send_gift":
        body = rest[1:] if rest.startswith("@") else rest
        split = _split_gift(body, cfg)
        if split is None:
            return None
        t = _clean_target(split[0]) or target
        if t is None:
            return None
        return Command(name=name, target=t, gift=split[1], count=split[2])
    # purchase / release / train / ransom：@目标；
    # 或 @ 前缀形式（目标来自提及），尾部闲聊由数据层前缀解析兜底
    own = None
    if rest.startswith("@"):
        own = _clean_target(rest[1:])
    if own is not None:
        return Command(name=name, target=own)
    if target is not None:
        return Command(name=name, target=target)
    return None


def _build_mention_command(target: str, body: str, cfg: Config | None,
                           table) -> Command | None:
    """构造 @用户名 指令 的 Command。

    - 查询类（我的金币/我的魅力/我的奴隶）：mention=目标，由引擎按被查对象执行
    - 带目标指令：目标 = 指令自带的 @参数 > 提及目标
    - 其余（签到/打工/反抗/帮助/榜单）：带 mention 返回，由引擎拒绝并提示
    """
    exact_map = {kw: name for kw, name, kind, _ in table if kind == "exact"}
    name = exact_map.get(body)
    if name is not None:
        return Command(name=name, mention=target)
    for kw, cname, kind, _canonical in table:
        if kind != "param":
            continue
        if body == kw or body.startswith(kw):
            rest2 = body[len(kw):]
            cmd = _build_param_command(cname, rest2, cfg, target=target)
            if cmd is not None:
                cmd.mention = target
                return cmd
            return None
    return None


def _parse_mention(rest: str, cfg: Config | None, table,
                   name_matcher) -> Command | None:
    if not rest:
        return None
    matched = name_matcher(rest) if name_matcher else None
    if matched:
        return _build_mention_command(matched, rest[len(matched):], cfg, table)
    # 目标不在用户列表（未注册新群友）：按最早出现的指令关键字切分
    best = None  # (pos, keyword, command_name)
    for kw, cname, kind, _canonical in table:
        if kind != "param":
            continue
        pos = rest.find(kw)
        if pos > 0 and (best is None or pos < best[0]):
            best = (pos, kw, cname)
    if best is None:
        return None
    pos, kw, _cname = best
    target = _clean_target(rest[:pos])
    if target is None:
        return None
    cmd = _build_param_command(_cname, rest[pos + len(kw):], cfg, target=target)
    if cmd is not None:
        cmd.mention = target
    return cmd


def parse(text: str, cfg: Config | None = None,
          name_matcher=None) -> Command | None:
    compact = _compact(text)
    table = keyword_table(cfg)
    exact_map = {kw: name for kw, name, kind, _ in table if kind == "exact"}
    if compact in exact_map:
        return Command(name=exact_map[compact])

    # @ 前缀形式：@用户名 指令（用户列表匹配优先，未注册目标按关键字切分）
    if compact.startswith("@") and name_matcher is not None:
        cmd = _parse_mention(compact[1:], cfg, table, name_matcher)
        if cmd is not None:
            return cmd

    for kw, name, kind, _canonical in table:
        if kind != "param":
            continue
        if compact.startswith(kw) and len(compact) > len(kw) \
                and compact[len(kw)] == "@":
            cmd = _build_param_command(name, compact[len(kw):], cfg)
            if cmd is not None:
                return cmd
            # 命中指令但参数不合法 → None（由引擎回复用法提示）
            return None
    return None


def usage_hint(text: str) -> str | None:
    for kw, usage in USAGE_KEYWORDS:
        if text == kw:
            return USAGE_HINT_TEMPLATE.format(usage=usage)
        if text.startswith(kw) and len(text) > len(kw) and text[len(kw)] in " @":
            return USAGE_HINT_TEMPLATE.format(usage=usage)
    return None
