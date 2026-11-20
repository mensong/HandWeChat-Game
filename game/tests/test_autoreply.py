"""自动回复规则：匹配、变量渲染与配置校验。"""
import re

import pytest

from game.autoreply import match_rule, render
from game.config import Config, ConfigError
from game.models import AutoReplyRule


def _rule(pattern, replies=("x",), **kw):
    return AutoReplyRule(name=kw.pop("name", "规则"), regex=re.compile(pattern),
                         replies=list(replies), **kw)


def test_match_variables():
    rule = _rule(r"“([^”]+)”拍了拍“([^”]+)”(.*)")
    matched = match_rule([rule], "“是你的益达”拍了拍“饭人休闲传”的屁股", "我")
    assert matched is not None
    got_rule, variables = matched
    assert got_rule is rule
    assert variables == {"sender": "我", "msg1": "是你的益达",
                         "msg2": "饭人休闲传", "msg3": "的屁股"}


def test_missing_group_is_empty():
    rule = _rule(r"“([^”]+)”拍了拍“([^”]+)”(.*)")
    _, variables = match_rule([rule], "“是你的益达”拍了拍“饭人休闲传”", "我")
    assert variables["msg3"] == ""


def test_render_keeps_unknown_placeholder():
    assert render("{sender} {msg1} {nope}", {"sender": "A", "msg1": "B"}) == "A B {nope}"


def test_enabled_and_ignored_senders():
    disabled = _rule(r".*", name="关")
    disabled.enabled = False
    assert match_rule([disabled], "x", "张三") is None
    blocked = _rule(r".*")
    assert match_rule([blocked], "x", "我", ("我",)) is None
    allowed = _rule(r".*", allow_ignored_senders=True)
    assert match_rule([allowed], "x", "我", ("我",)) is not None


def test_invalid_pattern_rejected(cfg):
    data = cfg.as_dict()
    data["auto_replies"] = [{"pattern": "(", "replies": "x"}]
    with pytest.raises(ConfigError):
        Config(data)


def test_reply_validation(cfg):
    data = cfg.as_dict()
    for bad in ({"pattern": "x", "replies": []},
                {"pattern": "x", "replies": ""},
                {"pattern": "x", "replies": "y", "cooldown_seconds": -1}):
        with pytest.raises(ConfigError):
            Config({**data, "auto_replies": [bad]})


def test_bot_variable_rendered_everywhere(cfg):
    data = cfg.as_dict()
    data["bot_name"] = "小助手"
    data["auto_replies"] = [{
        "name": "问名字", "pattern": r"^{bot}$", "replies": "我是{bot}",
        "cooldown_key": "{bot}"}]
    data["work_events"] = [{"text": "{bot} 摸鱼", "coins_min": 0,
                            "coins_max": 1, "weight": 1}]
    c = Config(data)
    rule = c.get("auto_replies")[0]
    assert rule["pattern"] == "^小助手$"
    assert rule["replies"] == "我是小助手"
    assert c.auto_replies[0].replies == ["我是小助手"]
    assert rule["cooldown_key"] == "小助手"
    assert c.work_events[0].text == "小助手 摸鱼"
    assert c.auto_replies[0].regex.search("小助手") is not None
    # as_dict 保留占位符，配置页读写不受替换影响
    assert c.as_dict()["auto_replies"][0]["pattern"] == "^{bot}$"


def test_bot_variable_escaped_in_pattern(cfg):
    data = cfg.as_dict()
    data["bot_name"] = "A.B"
    data["auto_replies"] = [{"pattern": "^({bot})$", "replies": "{bot}"}]
    c = Config(data)
    assert c.auto_replies[0].regex.pattern == r"^(A\.B)$"
    assert c.auto_replies[0].regex.search("AXB") is None
    assert c.auto_replies[0].regex.search("A.B") is not None


def test_empty_bot_referenced_rejected(cfg):
    data = cfg.as_dict()
    data["bot_name"] = ""
    data["auto_replies"] = [{"pattern": "^{bot}$", "replies": "x"}]
    with pytest.raises(ConfigError):
        Config(data)
