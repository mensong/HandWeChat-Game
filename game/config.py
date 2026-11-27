"""配置加载与校验。"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULTS = {
    "timezone": "Asia/Shanghai",

    "gateway_url": "ws://127.0.0.1:8100/api/v1/gateway/ws/app",
    "gateway_app_id": "social-game",
    "gateway_token": "",
    "gateway_rules": None,

    "allow_hash_prefix": True,
    "ignore_senders": ["我", "对方", "未知", ""],
    "command_aliases": {},
    "dedupe_window_seconds": 5,
    "command_rate_limit_seconds": 2,
    "help_cooldown_seconds": 60,
    "usage_hint_cooldown_seconds": 60,
    "reply_max_chars": 500,

    "bot_name": "",
    "bot_name_aliases": [],
    "auto_replies": [],

    "send_max_per_minute": 15,
    "send_min_interval_ms": 1500,
    "send_queue_max": 100,

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

    "slave_interactions": [],
    "interaction_coins_min": 1,
    "interaction_coins_max": 5,
    "interaction_charm_min": 1,
    "interaction_charm_max": 5,
    "interaction_weight_coins": 4,
    "interaction_weight_charm": 4,
    "interaction_weight_both": 2,
    "interaction_cooldown_minutes": 10,
    "interaction_max_per_day": 10,

    "ransom_price_coeff": 1.0,
    "ransom_cooldown_minutes": 10,
    "ransom_max_per_day": 10,

    "signin_base_reward": 10,
    "signin_streak_step": 2,
    "signin_max_reward": 24,
    "chat_coins_per_message": 10,
    "chat_coins_daily_cap": 500,
    "transfer_tax_rate": 0.05,
    "transfer_daily_limit": 5000,

    "gift_max_quantity": 99,
    "gift_daily_spend_limit": 20000,
    "gift_rank_days": 30,

    "health_port": 8001,
    "web_host": "0.0.0.0",

    "gifts": [],
    "work_events": [],
}

_INT_KEYS = [
    "reply_max_chars", "send_queue_max",
    "initial_coins", "min_slave_price", "max_slaves",
    "slave_work_max_per_day", "rebel_max_per_day", "rebel_loot_max",
    "rebel_ransom_max", "rebel_compensation_max",
    "signin_base_reward", "signin_streak_step", "signin_max_reward",
    "transfer_daily_limit", "gift_max_quantity", "gift_daily_spend_limit",
    "gift_rank_days", "health_port",
    "interaction_coins_min", "interaction_coins_max",
    "interaction_charm_min", "interaction_charm_max",
    "interaction_cooldown_minutes", "interaction_max_per_day",
    "ransom_cooldown_minutes", "ransom_max_per_day",
]
_FLOAT_KEYS = [
    "charm_base", "charm_decay_rate", "slave_price_coeff", "slave_price_random_min",
    "slave_price_random_max", "release_reward_coeff", "transfer_tax_rate",
    "rebel_master_coeff", "rebel_slave_coeff",
    "interaction_weight_coins", "interaction_weight_charm", "interaction_weight_both",
    "ransom_price_coeff",
]
_POSITIVE_FLOAT_KEYS = [
    "slave_price_coeff", "release_reward_coeff", "rebel_master_coeff", "rebel_slave_coeff",
]


class ConfigError(Exception):
    pass


# 这些参数涉及启动时建立的连接/绑定/时钟，热加载无法生效，改动后需重启
RESTART_KEYS = {"gateway_url", "gateway_app_id", "gateway_token", "gateway_rules",
                "web_host", "health_port", "timezone"}


INTERACTION_TONES = ("褒", "贬", "中性")


class Config:
    def __init__(self, data: dict):
        merged = dict(DEFAULTS)
        for k, v in data.items():
            merged[k] = v
        self._raw = merged
        self._data = self._render_globals(merged)
        self._validate()
        self.gifts = [self._make_gift(g) for g in self._data["gifts"]]
        self.work_events = [self._make_event(e) for e in self._data["work_events"]]
        self.interactions = [models_Interaction(i)
                             for i in self._data["slave_interactions"]]
        self.auto_replies = [self._make_rule(r, i)
                             for i, r in enumerate(self._data["auto_replies"])]
        self.gifts.sort(key=lambda g: g.price)

    def get(self, key: str):
        return self._data[key]

    def as_dict(self) -> dict:
        """原始配置（保留 {bot} 等占位符），供配置页/测试读写。"""
        return dict(self._raw)

    def _render_globals(self, data: dict) -> dict:
        bot = data.get("bot_name")
        if not isinstance(bot, str):
            raise ConfigError("bot_name must be a string")
        if not bot:
            if _contains_bot(data):
                raise ConfigError("bot_name is empty but {bot} is referenced in config")
            return dict(data)
        return {k: _render_value(v, bot, k == "pattern") for k, v in data.items()}

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
    def _make_rule(r, index: int):
        if not isinstance(r, dict):
            raise ConfigError(f"auto_replies[{index}] must be an object")
        name = r.get("name") or f"规则{index + 1}"
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"auto_replies[{index}] name must be a non-empty string")
        pattern = r.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ConfigError(f"auto_replies[{index}] pattern must be a non-empty string")
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ConfigError(f"auto_replies[{index}] invalid pattern: {e}")
        replies = r.get("replies")
        if isinstance(replies, str):
            replies = [replies]
        if not isinstance(replies, list) or not replies \
                or any(not isinstance(x, str) or not x for x in replies):
            raise ConfigError(f"auto_replies[{index}] replies must be a non-empty "
                              f"string or list of non-empty strings")
        cooldown = r.get("cooldown_seconds", 0)
        if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)) \
                or cooldown < 0:
            raise ConfigError(f"auto_replies[{index}] cooldown_seconds must be "
                              f"a number >= 0")
        cooldown_key = r.get("cooldown_key", "{sender}")
        if not isinstance(cooldown_key, str) or not cooldown_key:
            raise ConfigError(f"auto_replies[{index}] cooldown_key must be "
                              f"a non-empty string")
        enabled = r.get("enabled", True)
        allow_ignored = r.get("allow_ignored_senders", False)
        if not isinstance(enabled, bool) or not isinstance(allow_ignored, bool):
            raise ConfigError(f"auto_replies[{index}] enabled / "
                              f"allow_ignored_senders must be booleans")
        return models_AutoReplyRule(
            name=name, regex=regex, replies=list(replies),
            cooldown_seconds=float(cooldown), cooldown_key=cooldown_key,
            allow_ignored_senders=allow_ignored, enabled=enabled)

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
        if not isinstance(d["gateway_url"], str) \
                or not d["gateway_url"].startswith(("ws://", "wss://")):
            raise ConfigError("gateway_url must start with ws:// or wss://")
        if not isinstance(d["gateway_app_id"], str) or not d["gateway_app_id"].strip():
            raise ConfigError("gateway_app_id must be a non-empty string")
        if not isinstance(d["gateway_token"], str):
            raise ConfigError("gateway_token must be a string")
        aliases = d["bot_name_aliases"]
        if not isinstance(aliases, list) or any(
                not isinstance(a, str) or not a.strip() for a in aliases):
            raise ConfigError("bot_name_aliases must be a list of non-empty strings")
        self._validate_gateway_rules(d["gateway_rules"])
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
        ca = d["command_aliases"]
        if not isinstance(ca, dict):
            raise ConfigError("command_aliases must be an object")
        for canonical, alist in ca.items():
            if not isinstance(canonical, str) or not canonical:
                raise ConfigError("command_aliases keys must be non-empty strings")
            if not isinstance(alist, list) or any(not isinstance(a, str) or not a
                                                  for a in alist):
                raise ConfigError(
                    f"command_aliases[{canonical}] must be a list of non-empty strings")
        if not isinstance(d["auto_replies"], list):
            raise ConfigError("auto_replies must be a list")
        for k in ("rebel_master_multipliers", "rebel_slave_multipliers"):
            if not isinstance(d[k], list) or not d[k]:
                raise ConfigError(f"{k} must be a non-empty list")
            if any(not isinstance(x, (int, float)) or x < 0 for x in d[k]):
                raise ConfigError(f"{k} entries must be non-negative numbers")
        if d["interaction_coins_min"] < 1 or d["interaction_coins_max"] < d["interaction_coins_min"]:
            raise ConfigError("interaction_coins range invalid")
        if d["interaction_charm_min"] < 1 or d["interaction_charm_max"] < d["interaction_charm_min"]:
            raise ConfigError("interaction_charm range invalid")
        if min(d["interaction_weight_coins"], d["interaction_weight_charm"],
               d["interaction_weight_both"]) < 0:
            raise ConfigError("interaction weights must be >= 0")
        if d["interaction_weight_coins"] + d["interaction_weight_charm"] + d["interaction_weight_both"] <= 0:
            raise ConfigError("interaction weights sum must be > 0")
        if d["interaction_cooldown_minutes"] < 0:
            raise ConfigError("interaction_cooldown_minutes must be >= 0")
        if d["interaction_max_per_day"] < 1:
            raise ConfigError("interaction_max_per_day must be >= 1")
        if not isinstance(d["slave_interactions"], list):
            raise ConfigError("slave_interactions must be a list")
        for item in d["slave_interactions"]:
            if not isinstance(item, dict):
                raise ConfigError("slave_interactions entries must be objects")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ConfigError("slave_interactions text must be a non-empty string")
            if item.get("tone") not in INTERACTION_TONES:
                raise ConfigError(f"slave_interactions tone must be one of {INTERACTION_TONES}")
        if not 0 <= d["ransom_price_coeff"] <= 1:
            raise ConfigError("ransom_price_coeff must be in [0, 1]")
        if d["ransom_cooldown_minutes"] < 0:
            raise ConfigError("ransom_cooldown_minutes must be >= 0")
        if d["ransom_max_per_day"] < 1:
            raise ConfigError("ransom_max_per_day must be >= 1")

    @staticmethod
    def _validate_gateway_rules(rules) -> None:
        """手写网关规则按网关侧同一套上限校验，避免握手时才被 4400 拒绝。"""
        if rules is None:
            return
        if not isinstance(rules, list):
            raise ConfigError("gateway_rules must be null or a list")
        if len(rules) > 32:
            raise ConfigError("gateway_rules 最多 32 条")
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise ConfigError(f"gateway_rules[{i}] must be an object")
            unknown = set(rule) - {"keywords", "regex", "senders", "chat_types"}
            if unknown:
                raise ConfigError(
                    f"gateway_rules[{i}] 不支持的字段: {sorted(unknown)}")
            for key in ("keywords", "senders", "chat_types"):
                terms = rule.get(key)
                if terms is None:
                    continue
                if not isinstance(terms, list) or len(terms) > 32:
                    raise ConfigError(
                        f"gateway_rules[{i}].{key} 必须是最多 32 项的数组")
                for term in terms:
                    if not isinstance(term, str) or not term.strip():
                        raise ConfigError(
                            f"gateway_rules[{i}].{key} 不能包含空字符串")
            for chat_type in rule.get("chat_types") or []:
                if chat_type not in ("group", "friend"):
                    raise ConfigError(
                        f"gateway_rules[{i}].chat_types 只支持 group / friend")
            regex = rule.get("regex")
            if regex is not None:
                if not isinstance(regex, str) or not regex:
                    raise ConfigError(f"gateway_rules[{i}].regex 必须是非空字符串")
                if len(regex) > 200:
                    raise ConfigError(f"gateway_rules[{i}].regex 最长 200 字符")
                try:
                    re.compile(regex)
                except re.error as e:
                    raise ConfigError(f"gateway_rules[{i}].regex 非法: {e}")
            if not any(rule.get(k) for k in ("keywords", "regex", "senders", "chat_types")):
                raise ConfigError(f"gateway_rules[{i}] 至少需要一个匹配字段")

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


def models_Interaction(i: dict):
    from .models import Interaction
    return Interaction(text=i["text"], tone=i["tone"])


def models_AutoReplyRule(**kwargs):
    from .models import AutoReplyRule
    return AutoReplyRule(**kwargs)


_BOT_PLACEHOLDER = "{bot}"


def _contains_bot(value) -> bool:
    if isinstance(value, str):
        return _BOT_PLACEHOLDER in value
    if isinstance(value, list):
        return any(_contains_bot(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_bot(v) for v in value.values())
    return False


def _render_value(value, bot: str, in_pattern: bool = False):
    """把 {bot} 替换为 bot_name；pattern 内先 re.escape，避免昵称里的元字符生效。"""
    if isinstance(value, str):
        if _BOT_PLACEHOLDER not in value:
            return value
        return value.replace(_BOT_PLACEHOLDER, re.escape(bot) if in_pattern else bot)
    if isinstance(value, list):
        return [_render_value(v, bot, in_pattern) for v in value]
    if isinstance(value, dict):
        return {k: _render_value(v, bot, in_pattern or k == "pattern")
                for k, v in value.items()}
    return value


def read_config_file(path: str | Path) -> tuple[str, dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    return str(p.resolve()), data


def write_config_file(path: str | Path, data: dict) -> None:
    Config(data)  # 先校验，非法配置直接抛错，不落盘
    p = Path(path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")


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
