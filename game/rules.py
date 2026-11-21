"""网关规则构建：把本应用真正处理的指令与自动回复翻译成 hello.rules。

网关匹配的是 OCR 原始文本，这里只做前缀式筛选：允许行首空白和锚点两侧空白，
不在关键字或匹配单元之间插入空白。宁可多放行（应用仍会 skip），不能把要处理的
消息挡在网关。
"""
from __future__ import annotations

import re

from .config import ConfigError
from .parser import keyword_table

MAX_RULES = 32
MAX_PATTERN = 200
MAX_TERMS = 32
_PREFIX = r"^[#＃]?\s*"
_CJK = re.compile(r"[一-鿿]")


def build_rules(cfg) -> list[dict]:
    """按指令表、别名和启用中的自动回复生成规则数组。"""
    exact: list[str] = []
    param: list[str] = []
    for keyword, _name, kind, _canonical in keyword_table(cfg):
        bucket = exact if kind == "exact" else param
        if keyword not in bucket:
            bucket.append(keyword)

    rules: list[dict] = []
    rules.extend(_alternation(exact))
    rules.extend(_alternation(param))
    rules.append({"regex": _PREFIX + r"[@＠]"})
    for rule in getattr(cfg, "auto_replies", ()):
        if not rule.enabled:
            continue
        regex = _pad_anchors(rule.regex.pattern)
        if len(regex) <= MAX_PATTERN:
            rules.append({"regex": regex})
            continue
        # 超长正则退化成字面量关键词，只会放宽匹配，不会漏消息。
        terms = _literal_terms(rule.regex.pattern)
        if terms:
            rules.append({"keywords": terms})

    if len(rules) > MAX_RULES:
        raise ConfigError(f"生成的网关规则超过 {MAX_RULES} 条，请减少启用的自动回复")
    return rules


def _alternation(keywords: list[str]) -> list[dict]:
    """把关键字列表压成尽量少的正则规则，每条不超过长度上限。"""
    rules: list[dict] = []
    chunk: list[str] = []
    for keyword in keywords:
        term = re.escape(keyword)
        if chunk and len(_PREFIX + "(?:" + "|".join(chunk + [term]) + ")") > MAX_PATTERN:
            rules.append({"regex": _PREFIX + "(?:" + "|".join(chunk) + ")"})
            chunk = []
        chunk.append(term)
    if chunk:
        rules.append({"regex": _PREFIX + "(?:" + "|".join(chunk) + ")"})
    return rules


def _pad_anchors(pattern: str) -> str:
    """OCR 行首尾可能带空格，给 ^ / $ 锚点留出空白余量。"""
    prefix = ""
    suffix = ""
    body = pattern
    if body.startswith("^"):
        prefix = r"^\s*"
        body = body[1:]
    if body.endswith("$") and not body.endswith("\\$"):
        suffix = r"\s*$"
        body = body[:-1]
    return prefix + body + suffix


def _literal_terms(pattern: str) -> list[str]:
    """从正则里挑出长度 ≥2 的中文字面串，作为退化关键词。"""
    terms: list[str] = []
    run: list[str] = []
    in_class = False
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            i += 2
            if run:
                _flush(terms, run)
            continue
        if char == "[":
            in_class = True
            _flush(terms, run)
        elif char == "]":
            in_class = False
        elif in_class:
            pass
        elif _CJK.match(char):
            run.append(char)
        else:
            _flush(terms, run)
        i += 1
    _flush(terms, run)
    return terms[:MAX_TERMS]


def _flush(terms: list[str], run: list[str]) -> None:
    text = "".join(run)
    run.clear()
    if len(text) >= 2 and text not in terms:
        terms.append(text)
