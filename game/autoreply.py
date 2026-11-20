"""通用自动回复规则：正则匹配消息并渲染 {sender}/{msgN} 变量。"""
from __future__ import annotations

import re

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def match_rule(rules, text: str, sender: str, ignored_senders=()):
    """按配置顺序返回第一条命中的启用规则及其变量。

    返回 (rule, variables)；全部未命中返回 None。变量含 sender 与
    msg1..msgN（第 N 个捕获组，未匹配到为空串）。
    """
    ignored = sender in ignored_senders
    for rule in rules:
        if not rule.enabled or (ignored and not rule.allow_ignored_senders):
            continue
        m = rule.regex.search(text)
        if m is None:
            continue
        variables = {"sender": sender}
        for i, value in enumerate(m.groups(), 1):
            variables[f"msg{i}"] = value or ""
        return rule, variables
    return None


def render(template: str, variables: dict) -> str:
    """替换 {name}；未知占位符原样保留，便于发现配置笔误。"""
    return _PLACEHOLDER_RE.sub(
        lambda m: variables.get(m.group(1), m.group(0)), template)
