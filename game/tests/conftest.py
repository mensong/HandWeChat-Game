"""测试公共设施。"""
from __future__ import annotations

import itertools
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from game.config import load_config
from game.engine import Engine
from game.rng import Rng
from game.store import Store

REPO = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=8))


class FakeClock:
    def __init__(self):
        self.t = datetime(2026, 11, 14, 12, 0, 0, tzinfo=TZ)

    def __call__(self):
        return self.t

    def advance(self, **kwargs):
        self.t += timedelta(**kwargs)


class FakeSender:
    def __init__(self):
        self.sent: list[str] = []

    def enqueue(self, text: str) -> bool:
        self.sent.append(text)
        return True

    @property
    def size(self) -> int:
        return 0

    @property
    def last(self):
        return self.sent[-1] if self.sent else None


@pytest.fixture()
def cfg():
    # 测试固定使用规格默认参数，避免用户在配置页面调参后测试失效；
    # 礼物目录与打工事件表仍取自配置文件（游戏逻辑必须用真实目录）。
    from game.config import Config, DEFAULTS, load_config
    data = load_config(REPO / "config" / "game_config.json").as_dict()
    data.update({k: v for k, v in DEFAULTS.items()
                 if k not in ("gifts", "work_events", "slave_interactions",
                              "auto_replies")})
    # 拍一拍用例使用固定昵称与文案，避免随生产配置漂移
    data["bot_name"] = "童声微蔓"
    data["auto_replies"] = [{
        "name": "拍一拍",
        "pattern": r"^[“\"「『]([^”\"」』]+)[”\"」』]拍了拍[“\"「『]({bot}|童声徽蔓)[”\"」』](.*)$",
        "replies": ["{msg1} 拍了拍我，我醒啦～"],
        "cooldown_seconds": 10,
        "cooldown_key": "{msg1}",
        "allow_ignored_senders": True,
    }]
    # 聊天收入默认关闭，避免影响既有用例的金额预期；专用用例见 env_chat
    data["chat_coins_per_message"] = 0
    return Config(data)


def _build_env(cfg, tmp_path):
    store = Store(tmp_path / "test.db")
    clock = FakeClock()
    rng = Rng()
    sender = FakeSender()
    engine = Engine(cfg, store, clock, rng, logging.getLogger("test"))
    engine.attach_sender(sender)
    engine.handle_health({"chat_title": "888 种田大队(32)",
                          "online": True, "listener_running": True})
    counter = itertools.count(1)

    def send(sender_name: str, content: str, advance: float = 3.0):
        if advance:
            clock.advance(seconds=advance)
        n = next(counter)
        msg = {"id": str(n), "cursor": n, "sender": sender_name,
               "content": content, "received_at": clock.t.isoformat()}
        engine.handle_message(msg)
        return sender.last

    ns = type("Env", (), {})()
    ns.cfg = cfg
    ns.store = store
    ns.clock = clock
    ns.rng = rng
    ns.sender = sender
    ns.engine = engine
    ns.send = send
    ns.group = "888种田大队"
    return ns


@pytest.fixture()
def env(tmp_path, cfg):
    yield _build_env(cfg, tmp_path)


@pytest.fixture()
def env_chat(tmp_path, cfg):
    """聊天收入开启（每条 +10，每日上限 500）的独立环境。"""
    from game.config import Config
    data = cfg.as_dict()
    data["chat_coins_per_message"] = 10
    ns = _build_env(Config(data), tmp_path)
    yield ns


@pytest.fixture()
def env_factory(tmp_path, cfg):
    """按覆盖参数构建独立环境，用于自定义 auto_replies 等场景。"""
    from game.config import Config
    seq = itertools.count(1)

    def build(**overrides):
        data = cfg.as_dict()
        data.update(overrides)
        d = tmp_path / f"env{next(seq)}"
        d.mkdir()
        return _build_env(Config(data), d)

    return build
