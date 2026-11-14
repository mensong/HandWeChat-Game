"""配置加载与校验。"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "api_base_url": "http://127.0.0.1:8000",
    "api_timeout_seconds": 30,
    "poll_timeout_seconds": 25,
    "poll_limit": 100,
    "health_poll_seconds": 2,
    "timezone": "Asia/Shanghai",

    "allow_hash_prefix": True,
    "ignore_senders": ["我", "对方", "未知", ""],
    "dedupe_window_seconds": 5,
    "command_rate_limit_seconds": 2,
    "help_cooldown_seconds": 60,
    "usage_hint_cooldown_seconds": 60,
    "reply_max_chars": 500,

    "send_max_per_minute": 15,
    "send_min_interval_ms": 1500,
    "send_queue_max": 100,
    "send_task_timeout_seconds": 30,

    "allowed_groups": [],
    "group_title_stable_seconds": 10,

    "initial_coins": 200,
    "auto_create_target": True,

    "charm_base": 10,
    "charm_decay_period_days": 7,
    "charm_decay_rate": 0.10,

    "max_slaves": 5,
    "slave_price_coeff": 2.0,
    "slave_price_random_min": 0.0,
    "slave_price_random_max": 10.0,
    "min_slave_price": 10,
    "release_reward_coeff": 2.0,

    "slave_work_cooldown_minutes": 30,
    "slave_work_max_per_day": 8,

    "rebel_cooldown_minutes": 180,
    "rebel_max_per_day": 3,
    "rebel_master_coeff": 1.0,
    "rebel_slave_coeff": 1.0,
    "rebel_master_multipliers": [0.0, 1.0, 2.0],
    "rebel_slave_multipliers": [0.0, 0.5, 1.0],
    "rebel_loot_max": 500,
    "rebel_ransom_max": 500,
    "rebel_compensation_max": 200,

    "signin_base_reward": 10,
    "signin_streak_step": 2,
    "signin_max_reward": 24,
    "transfer_tax_rate": 0.05,
    "transfer_daily_limit": 5000,

    "gift_max_quantity": 99,
    "gift_daily_spend_limit": 20000,
    "gift_rank_days": 30,

    "health_port": 8001,

    "gifts": [],
    "work_events": [],
}

_INT_KEYS = [
    "poll_limit", "reply_max_chars", "send_queue_max", "send_task_timeout_seconds",
    "initial_coins", "min_slave_price", "max_slaves",
    "slave_work_max_per_day", "rebel_max_per_day", "rebel_loot_max",
    "rebel_ransom_max", "rebel_compensation_max",
    "signin_base_reward", "signin_streak_step", "signin_max_reward",
    "transfer_daily_limit", "gift_max_quantity", "gift_daily_spend_limit",
    "gift_rank_days", "health_port",
]
_FLOAT_KEYS = [
    "charm_base", "charm_decay_rate", "slave_price_coeff", "slave_price_random_min",
    "slave_price_random_max", "release_reward_coeff", "transfer_tax_rate",
    "rebel_master_coeff", "rebel_slave_coeff",
]
_POSITIVE_FLOAT_KEYS = [
    "slave_price_coeff", "release_reward_coeff", "rebel_master_coeff", "rebel_slave_coeff",
]


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, data: dict):
        merged = dict(DEFAULTS)
        for k, v in data.items():
            merged[k] = v
        self._data = merged
        self._validate()
        self.gifts = [self._make_gift(g) for g in merged["gifts"]]
        self.work_events = [self._make_event(e) for e in merged["work_events"]]
        self.gifts.sort(key=lambda g: g.price)

    def get(self, key: str):
        return self._data[key]

    def as_dict(self) -> dict:
        return dict(self._data)

    @staticmethod
    def _make_gift(g: dict):
        for k in ("id", "name", "price", "charm"):
            if k not in g:
                raise ConfigError(f"gift missing key: {k}")
        if not isinstance(g["price"], int) or g["price"] <= 0:
            raise ConfigError(f"gift {g['id']} price must be positive int")
        if not isinstance(g["charm"], (int, float)) or g["charm"] <= 0:
            raise ConfigError(f"gift {g['id']} charm must be positive number")
        return models_Gift(g)

    @staticmethod
    def _make_event(e: dict):
        for k in ("text", "coins_min", "coins_max", "weight"):
            if k not in e:
                raise ConfigError(f"work_event missing key: {k}")
        lo, hi = int(e["coins_min"]), int(e["coins_max"])
        if lo > hi:
            raise ConfigError(f"work_event coins_min > coins_max: {e['text']}")
        if lo < 0 and hi > 0:
            raise ConfigError(f"work_event must not cross zero sign: {e['text']}")
        if not isinstance(e["weight"], (int, float)) or e["weight"] <= 0:
            raise ConfigError(f"work_event weight must be positive: {e['text']}")
        return models_WorkEvent(e)

    def _validate(self) -> None:
        d = self._data
        for k in _INT_KEYS:
            if not isinstance(d[k], int):
                raise ConfigError(f"{k} must be int, got {type(d[k]).__name__}")
        for k in _FLOAT_KEYS:
            if not isinstance(d[k], (int, float)):
                raise ConfigError(f"{k} must be number")
        for k in _POSITIVE_FLOAT_KEYS:
            if d[k] <= 0:
                raise ConfigError(f"{k} must be > 0")
        if d["send_max_per_minute"] > 20:
            raise ConfigError("send_max_per_minute must be <= 20")
        if d["slave_price_random_min"] < 0 or d["slave_price_random_max"] < d["slave_price_random_min"]:
            raise ConfigError("invalid slave_price_random range")
        if not 0 <= d["charm_decay_rate"] < 1:
            raise ConfigError("charm_decay_rate must be in [0, 1)")
        if d["charm_decay_period_days"] <= 0:
            raise ConfigError("charm_decay_period_days must be > 0")
        if not 0 <= d["transfer_tax_rate"] < 1:
            raise ConfigError("transfer_tax_rate must be in [0, 1)")
        if d["initial_coins"] < 0:
            raise ConfigError("initial_coins must be >= 0")
        if d["min_slave_price"] < 0:
            raise ConfigError("min_slave_price must be >= 0")
        if not isinstance(d["gifts"], list) or not d["gifts"]:
            raise ConfigError("gifts must be a non-empty list")
        if not isinstance(d["work_events"], list) or not d["work_events"]:
            raise ConfigError("work_events must be a non-empty list")
        if not isinstance(d["allowed_groups"], list):
            raise ConfigError("allowed_groups must be a list")
        if not isinstance(d["ignore_senders"], list):
            raise ConfigError("ignore_senders must be a list")
        for k in ("rebel_master_multipliers", "rebel_slave_multipliers"):
            if not isinstance(d[k], list) or not d[k]:
                raise ConfigError(f"{k} must be a non-empty list")
            if any(not isinstance(x, (int, float)) or x < 0 for x in d[k]):
                raise ConfigError(f"{k} entries must be non-negative numbers")

    def find_gift(self, token: str):
        t = token.lower()
        for g in self.gifts:
            if g.name.lower() == t or any(a.lower() == t for a in g.aliases):
                return g
        return None


def models_Gift(g: dict):
    from .models import Gift
    return Gift(id=g["id"], name=g["name"], aliases=list(g.get("aliases", [])),
                price=g["price"], charm=g["charm"])


def models_WorkEvent(e: dict):
    from .models import WorkEvent
    return WorkEvent(text=e["text"], coins_min=int(e["coins_min"]),
                     coins_max=int(e["coins_max"]), weight=e["weight"])


def load_config(path: str | Path) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {p}: {e}")
    if not isinstance(data, dict):
        raise ConfigError("config root must be a JSON object")
    return Config(data)
