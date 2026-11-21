"""网关规则生成测试：指令、别名、自动回复都要被规则覆盖，闲聊不能被放行。"""
from __future__ import annotations

import re

import pytest

from game.config import Config, ConfigError
from game.rules import MAX_PATTERN, MAX_RULES, build_rules


def matches(rules: list[dict], text: str) -> bool:
    for rule in rules:
        if rule.get("regex") and re.search(rule["regex"], text):
            return True
        if any(term in text for term in rule.get("keywords", ())):
            return True
    return False


def test_rules_cover_all_commands(cfg):
    rules = build_rules(cfg)
    for text in [
        "签到", "#签到", "签到！", "我的金币",
        "金币榜", "金币系统", "魅力值", "魅力榜", "魅力系统",
        "礼物列表", "礼物榜", "礼物系统", "奴隶打工", "我的奴隶",
        "我要自由", "调教所有奴隶", "奴隶系统",
        "转账@张三100", "转账", "送礼@张三玫瑰", "购买奴隶@张三",
        "给他自由@张三", "给她自由@张三", "调教@张三", "赎身@张三",
    ]:
        assert matches(rules, text), text


def test_rules_cover_aliases(cfg):
    data = cfg.as_dict()
    data["command_aliases"] = {
        "购买奴隶": ["购买", "买下"],
        "金币榜": ["金币排名", "金币排行"],
    }
    rules = build_rules(Config(data))
    for text in ["金币排名", "金币排行", "购买@张三", "买下@张三"]:
        assert matches(rules, text), text


def test_rules_cover_mention_and_auto_reply(cfg):
    rules = build_rules(cfg)
    assert matches(rules, "@张三签到")
    assert matches(rules, "@张三 我的金币")
    assert matches(rules, "“张三”拍了拍“童声微蔓”")
    assert matches(rules, " “张三”拍了拍“童声微蔓” ")
    for text in ['"张三"拍了拍"童声微蔓"', "'张三'拍了拍'童声微蔓'",
                 "‘张三’拍了拍‘童声微蔓’"]:
        assert matches(rules, text), text


def test_rules_do_not_tolerate_inner_spaces(cfg):
    """OCR 字间空格交给应用侧处理，网关规则不再为此扩容。"""
    rules = build_rules(cfg)
    for text in ["签 到", "我 的 金 币", "“张三” 拍 了 拍 “童声微蔓”"]:
        assert not matches(rules, text), text
    assert matches(rules, " 签到")
    assert matches(rules, "# 签到")


def test_rules_ignore_plain_chat(cfg):
    rules = build_rules(cfg)
    for text in ["大家早安", "今天 签到 了吗", "拍一拍", "我的"]:
        assert not matches(rules, text), text


def test_disabled_auto_reply_not_reported(cfg):
    data = cfg.as_dict()
    data["auto_replies"][0]["enabled"] = False
    rules = build_rules(Config(data))
    assert not matches(rules, "“张三”拍了拍“童声微蔓”")
    assert len(rules) == len(build_rules(cfg)) - 1


def test_rules_respect_gateway_limits(cfg):
    rules = build_rules(cfg)
    assert 0 < len(rules) <= MAX_RULES
    for rule in rules:
        if "regex" in rule:
            assert len(rule["regex"]) <= MAX_PATTERN
            re.compile(rule["regex"])


def test_config_accepts_and_validates_rules(cfg):
    data = cfg.as_dict()
    data["gateway_rules"] = [{"keywords": ["签到"]}, {"regex": r"^\d+$"}]
    assert Config(data).get("gateway_rules") == data["gateway_rules"]

    for broken in ([{"regex": "("}], [{}], ["签到"], [{"regex": "x" * 201}]):
        data["gateway_rules"] = broken
        with pytest.raises(ConfigError):
            Config(data)
