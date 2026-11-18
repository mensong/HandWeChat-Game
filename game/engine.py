"""消息引擎：群识别、去重、限流、指令分发。"""
from __future__ import annotations

import logging
import time
from collections import deque

from .config import Config
from .context import Ctx
from .dispatcher import Dispatcher
from .models import Pat
from .parser import (HELP_COMMANDS, MENTION_CMD_LABELS, MENTION_QUERY_COMMANDS,
                     MENTION_TARGET_COMMANDS, parse, parse_pat, usage_hint)
from .replies import pat_reply
from .store import Store
from .util import fmt_iso, normalize_text, normalize_title


class GroupTracker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.key: str | None = None
        self.title: str | None = None
        self._pending: str | None = None
        self._pending_since = None

    def update(self, title: str | None, now) -> str | None:
        norm = normalize_title(title)
        self.title = title or None
        if not norm:
            return self.key
        if self.key is None or norm == self.key:
            self.key = norm
            self._pending = None
            return self.key
        if norm != self._pending:
            self._pending = norm
            self._pending_since = now
            return self.key
        if (now - self._pending_since).total_seconds() >= self.cfg.get("group_title_stable_seconds"):
            self.key = norm
            self._pending = None
        return self.key


class Engine:
    def __init__(self, cfg: Config, store: Store, clock, rng, log: logging.Logger):
        self.cfg = cfg
        self.store = store
        self.clock = clock
        self.rng = rng
        self.log = log
        self.ctx = Ctx(cfg, store, rng, clock, log)
        self.dispatcher = Dispatcher(self.ctx)
        self.tracker = GroupTracker(cfg)
        self._sender = None
        self._gateway = None
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._content_seen: dict[tuple[str, str, str], float] = {}
        self._last_cmd: dict[tuple[str, str], float] = {}
        self._last_help: dict[tuple[str, str], float] = {}
        self._last_usage: dict[tuple[str, str], float] = {}
        self._last_error: dict[tuple[str, str], float] = {}
        self._last_pat: dict[tuple[str, str], float] = {}
        self.paused = False
        self._paused_group: str | None = None
        self.cursor = 0  # 最后一条已接收消息的 id，不是流位置
        self.processed_total = 0
        self.last_error: str | None = None
        self.online: bool | None = None
        self.listener_running: bool | None = None
        self.recent_events: deque = deque(maxlen=500)
        self.last_upstream_context: dict | None = None

    def attach_sender(self, sender) -> None:
        self._sender = sender

    def attach_gateway(self, gateway) -> None:
        self._gateway = gateway

    def set_cursor(self, cursor: int) -> None:
        self.cursor = cursor

    def handle_health(self, health: dict) -> None:
        """接收网关透传的上游状态快照（微信在线、OCR 监听、当前聊天标题）。"""
        now = self.clock()
        self.last_upstream_context = dict(health)
        self.online = bool(health.get("online"))
        self.listener_running = bool(health.get("listener_running"))
        key = self.tracker.update(health.get("chat_title"), now)
        allowed = self.cfg.get("allowed_groups")
        paused = bool(allowed) and (key is None or key not in allowed)
        if paused != self.paused or (paused and key != self._paused_group):
            if paused:
                self.log.warning("group paused (not allowed): %r", key)
            elif self.paused:
                self.log.info("group resumed: %r", key)
            self.paused = paused
            self._paused_group = key if paused else None

    def handle_message(self, msg: dict) -> None:
        sender = (msg.get("sender") or "").strip()
        text = normalize_text(msg.get("content"), self.cfg.get("allow_hash_prefix"))
        if not text:
            return
        now = self.clock()
        group = self.tracker.key
        if not group or self.paused:
            return
        mid = str(msg.get("id"))
        if not self._mark_seen_id(mid):
            self.log.info("dup message id: %s", mid)
            return
        if self._content_dupe(group, sender, text, now):
            self.log.info("dup content: group=%s sender=%s", group, sender)
            return
        # 拍一拍是居中系统行，OCR 把 sender 标成"我"，需赶在 ignore_senders 之前解析；
        # 参与双方只能从正文取，不能依赖 sender。
        pat = parse_pat(text)
        if pat is not None:
            self._handle_pat(group, pat, now)
            return
        if sender in self.cfg.get("ignore_senders"):
            return
        self.store.upsert_player(group, sender, fmt_iso(now),
                                 self.cfg.get("initial_coins"), self.cfg.get("charm_base"))
        self._award_chat_coins(group, sender, now)
        cmd = parse(text, self.cfg, self._match_mention_name)
        started = time.monotonic()
        if cmd is None:
            hint = usage_hint(text)
            if hint:
                self._maybe_send(group, sender, hint, self._last_usage,
                                 self.cfg.get("usage_hint_cooldown_seconds"), now)
            self._log_command(group, sender, "none", "ignored", started)
            return
        if cmd.mention and cmd.name not in MENTION_QUERY_COMMANDS \
                and cmd.name not in MENTION_TARGET_COMMANDS:
            label = MENTION_CMD_LABELS.get(cmd.name, cmd.name)
            self._log_command(group, sender, cmd.name, "mention_rejected", started)
            if self._sender is not None:
                self._sender.enqueue(f"「{label}」不支持@别人代执行。")
            return
        if cmd.name in HELP_COMMANDS:
            last = self._last_help.get((group, sender))
            if last and (now.timestamp() - last) < self.cfg.get("help_cooldown_seconds"):
                self.log.info("help cooldown: %s", sender)
                return
            self._last_help[(group, sender)] = now.timestamp()
        last_cmd = self._last_cmd.get((group, sender))
        if last_cmd is not None and (now.timestamp() - last_cmd) < self.cfg.get("command_rate_limit_seconds"):
            self.log.info("rate limited: %s", sender)
            self._log_command(group, sender, cmd.name, "rate_limited", started)
            return
        try:
            with self.store.transaction():
                reply = self.dispatcher.dispatch(cmd, group, sender)
        except Exception:
            self.log.exception("handler error: cmd=%s sender=%s", cmd.name, sender)
            self.last_error = f"handler error: {cmd.name}"
            self.add_event(kind="error", group=group, sender=sender,
                           cmd=cmd.name, message="handler error")
            self._maybe_send(group, sender, "系统开小差了，请稍后再试。",
                             self._last_error, self.cfg.get("usage_hint_cooldown_seconds"), now)
            return
        self._last_cmd[(group, sender)] = now.timestamp()
        self.processed_total += 1
        detail = (reply or "").split("\n", 1)[0][:120]
        self._log_command(group, sender, cmd.name, "ok", started, detail)
        if reply and self._sender is not None:
            self._sender.enqueue(reply)

    def _match_mention_name(self, prefix: str) -> str | None:
        return self.store.match_player_prefix(self.tracker.key or "", prefix)

    # ---------- internals ----------

    def _mark_seen_id(self, mid: str) -> bool:
        if mid in self._seen_ids:
            return False
        self._seen_ids.add(mid)
        self._seen_order.append(mid)
        while len(self._seen_order) > 10000:
            old = self._seen_order.popleft()
            self._seen_ids.discard(old)
        return True

    def _content_dupe(self, group: str, sender: str, text: str, now) -> bool:
        window = self.cfg.get("dedupe_window_seconds")
        cutoff = now.timestamp() - window
        if len(self._content_seen) > 5000:
            self._content_seen = {k: v for k, v in self._content_seen.items() if v >= cutoff}
        key = (group, sender, text)
        last = self._content_seen.get(key)
        if last is not None and last >= cutoff:
            return True
        self._content_seen[key] = now.timestamp()
        return False

    def _maybe_send(self, group: str, sender: str, text: str,
                    tracker: dict, cooldown: float, now) -> None:
        last = tracker.get((group, sender))
        if last and (now.timestamp() - last) < cooldown:
            return
        tracker[(group, sender)] = now.timestamp()
        if self._sender is not None:
            self._sender.enqueue(text)

    def _handle_pat(self, group: str, pat: Pat, now) -> None:
        if not self.cfg.is_bot(pat.patted):
            return
        texts = self.cfg.get("pat_reply_texts")
        if not texts:
            return
        key = (group, pat.pat)
        last = self._last_pat.get(key)
        if last is not None and (now.timestamp() - last) < self.cfg.get("pat_reply_cooldown_seconds"):
            self.log.info("pat cooldown: group=%s pat=%s", group, pat.pat)
            return
        self._last_pat[key] = now.timestamp()
        started = time.monotonic()
        reply = pat_reply(self.rng.choice(texts), pat.pat, pat.patted, pat.what)
        self._log_command(group, pat.pat, "pat", "ok", started,
                          detail=reply.split("\n", 1)[0][:120])
        if self._sender is not None:
            self._sender.enqueue(reply)

    def apply_config(self, new_cfg: Config) -> None:
        """热加载：整体替换运行时配置引用。

        消息处理在事件循环内单线程串行，本方法通过 loop.call_soon_threadsafe
        调度执行，保证替换发生在两条指令之间，不会出现新旧参数混用。
        """
        self.cfg = new_cfg
        self.ctx.cfg = new_cfg
        self.tracker.cfg = new_cfg

    def _award_chat_coins(self, group: str, sender: str, now) -> None:
        """聊天收入：每条消息 +chat_coins_per_message 金币，每日累计不超过
        chat_coins_daily_cap（cap<=0 表示不设上限；per_message<=0 关闭该来源）。"""
        per = self.cfg.get("chat_coins_per_message")
        if per <= 0:
            return
        cap = self.cfg.get("chat_coins_daily_cap")
        today = now.date().isoformat()
        _, used = self.store.get_daily(group, today, sender, "chat")
        award = min(per, cap - used) if cap > 0 else per
        if award <= 0:
            return
        ts = fmt_iso(now)
        with self.store.transaction():
            self.store.adjust_coins(group, sender, award, "chat", None, ts)
            self.store.incr_daily(group, today, sender, "chat", 1, award)

    def add_event(self, kind: str, **fields) -> None:
        entry = {"ts": fmt_iso(self.clock()), "kind": kind}
        entry.update(fields)
        self.recent_events.append(entry)

    def get_recent_events(self, limit: int = 200) -> list[dict]:
        events = list(self.recent_events)
        return events[-limit:] if limit > 0 else events

    def _log_command(self, group: str, sender: str, cmd: str, result: str,
                     started: float, detail: str = "") -> None:
        cost_ms = int((time.monotonic() - started) * 1000)
        self.log.info("group=%s sender=%s cmd=%s result=%s cost_ms=%d",
                      group, sender, cmd, result, cost_ms)
        self.add_event(kind="command", group=group, sender=sender, cmd=cmd,
                       result=result, cost_ms=cost_ms, detail=detail)

    def stats(self) -> dict:
        return {
            "status": "ok",
            "online": self.online,
            "listener_running": self.listener_running,
            "chat_title": self.tracker.title,
            "group_key": self.tracker.key,
            "cursor": self.cursor,
            "queue_size": self._sender.size if self._sender else 0,
            "gateway": self._gateway.status() if self._gateway is not None else None,
            "processed_total": self.processed_total,
            "last_error": self.last_error,
        }
