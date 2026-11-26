"""启动横幅渲染与启动信息测试。"""
from __future__ import annotations

import io
from pathlib import Path

from game import __version__
from game.banner import render_info, render_logo, use_color
from game.main import startup_info


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_logo_contains_art_and_version():
    text = render_logo(__version__)
    assert "__        __" in text
    assert f"v{__version__}" in text
    assert "微信群社交游戏服务" in text
    assert "\033[" not in text


def test_logo_color_adds_ansi():
    text = render_logo(__version__, color=True)
    assert "\033[1;36m" in text
    assert "\033[0m" in text


def test_info_aligns_labels_by_display_width():
    text = render_info([("机器人", "饭人休闲传"), ("运行环境", "Python 3.11")])
    lines = text.splitlines()
    assert lines[0] == "-" * 66
    assert lines[1] == "  机器人    饭人休闲传"
    assert lines[2] == "  运行环境  Python 3.11"
    assert lines[-1] == "-" * 66
    assert "\033[" not in text


def test_info_color_adds_ansi():
    text = render_info([("机器人", "饭人休闲传")], color=True)
    assert "\033[36m" in text
    assert "\033[2m" in text


def test_use_color_disabled_for_non_tty():
    assert use_color(io.StringIO()) is False


def test_use_color_respects_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_color(FakeTTY()) is False


def test_startup_info_fields(cfg):
    info = dict(startup_info(cfg, "config/game_config.json", "data/game.db",
                             "data/logs"))
    assert info["机器人"] == cfg.get("bot_name")
    assert cfg.get("gateway_url") in info["网关"]
    assert f"app_id={cfg.get('gateway_app_id')}" in info["网关"]
    assert info["群白名单"] == "全部群"
    assert info["配置文件"] == "config/game_config.json"
    assert info["数据库"] == "data/game.db"
    assert info["日志"] == str(Path("data/logs") / "game.log")
    assert str(cfg.get("health_port")) in info["控制台"]
    assert "Python" in info["运行环境"]
    assert len(info["启动时间"]) == len("2026-11-26 21:30:00")
