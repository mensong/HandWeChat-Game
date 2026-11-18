"""网关接入层：通过 handwechat-gateway-sdk 接收询问、回传决策。"""
from __future__ import annotations

import itertools
import logging

from handwechat_gateway_sdk import (
    ChatInfo,
    Decision,
    GatewayClient,
    GatewayContext,
    Offer,
    PinInfo,
    SendResult,
)
from handwechat_gateway_sdk.client import GatewayAuthError

from .util import fmt_iso


class GatewaySender:
    """发送适配器：每次代发带 request_id，回执由 on_send_result 处理。"""

    def __init__(self, client: GatewayClient):
        self.client = client
        self._seq = itertools.count(1)

    async def send(self, text: str, dispatch_id: str = "") -> None:
        await self.client.send(text, request_id=f"r-{next(self._seq)}",
                               dispatch_id=dispatch_id)


class ReplyCollector:
    """接住 Engine 产生的回复，由 on_offer 统一转交发送队列。"""

    def __init__(self, queue=None):
        self.queue = queue
        self.replies: list[str] = []

    def enqueue(self, text: str) -> bool:
        self.replies.append(text)
        return True

    def take(self) -> list[str]:
        replies, self.replies = self.replies, []
        return replies

    @property
    def size(self) -> int:
        return self.queue.size if self.queue is not None else 0


class GatewayApp:
    def __init__(self, cfg, engine, log: logging.Logger):
        self.cfg = cfg
        self.engine = engine
        self.log = log
        self.queue = None
        self.collector = ReplyCollector()
        self.last_error: str | None = None
        self.last_offer_at: str | None = None
        self.offers = 0
        self.consumes = 0
        self.skips = 0
        self.sends_ok = 0
        self.sends_failed = 0
        self.client = GatewayClient(
            app_id=cfg.get("gateway_app_id"),
            token=cfg.get("gateway_token"),
            url=cfg.get("gateway_url"),
            on_offer=self.on_offer,
            on_connected=self.on_connected,
            on_pin_expired=self.on_pin_expired,
            on_upstream_state=self.on_upstream_state,
            on_chat_changed=self.on_chat_changed,
            on_send_result=self.on_send_result,
            logger=log,
        )

    def attach_queue(self, queue) -> None:
        self.queue = queue
        self.collector.queue = queue

    def status(self) -> dict:
        ctx = self.client.context
        return {
            "app_id": self.cfg.get("gateway_app_id"),
            "url": self.cfg.get("gateway_url"),
            "connected": bool(self.client.connected),
            "offers": self.offers,
            "consumes": self.consumes,
            "skips": self.skips,
            "sends_ok": self.sends_ok,
            "sends_failed": self.sends_failed,
            "last_offer_at": self.last_offer_at,
            "last_error": self.last_error,
            "context": None if ctx is None else {
                "online": ctx.online,
                "listener_running": ctx.listener_running,
                "attached": ctx.attached,
                "chat_title": ctx.chat_title,
                "chat_type": ctx.chat_type,
                "health_ok": ctx.health_ok,
                "upstream_connected": ctx.upstream_connected,
            },
        }

    async def run(self) -> None:
        """认证类错误不可恢复，记录后退出（控制台仍可排查）。"""
        try:
            await self.client.run()
        except GatewayAuthError as e:
            self.last_error = str(e)
            self.log.error("gateway auth failed: %s", e)
            self.engine.add_event(kind="gateway_auth_error", message=str(e))

    def on_connected(self, pin: PinInfo | None) -> None:
        self.last_error = None
        ctx = self.client.context
        if ctx is not None:
            self._apply_context(ctx)
        self.log.info("gateway connected: app_id=%s chat=%r listener=%s",
                      self.cfg.get("gateway_app_id"),
                      getattr(ctx, "chat_title", ""), getattr(ctx, "listener_running", None))
        if not (ctx and ctx.chat_title):
            self.log.warning("网关 welcome.context 缺少 chat_title，群标题为空期间消息会被丢弃；"
                             "请确认网关已升级到支持 context 的版本")
        self.engine.add_event(kind="gateway_connected",
                              app_id=self.cfg.get("gateway_app_id"))

    def on_pin_expired(self, pin: PinInfo) -> None:
        self.log.info("gateway pin expired: app_id=%s state=%s", pin.app_id, pin.state)
        self.engine.add_event(kind="pin_expired", app_id=pin.app_id, state=pin.state)

    def on_upstream_state(self, ctx: GatewayContext) -> None:
        self._apply_context(ctx)
        self.engine.add_event(kind="upstream_state", online=ctx.online,
                              listener_running=ctx.listener_running,
                              chat_title=ctx.chat_title,
                              upstream_connected=ctx.upstream_connected)

    def on_chat_changed(self, info: ChatInfo) -> None:
        ctx = self.client.context
        if ctx is not None:
            self._apply_context(ctx)
        self.log.info("chat changed: %r (%s)", info.chat_title, info.chat_type)
        self.engine.add_event(kind="chat_changed", chat_title=info.chat_title,
                              chat_type=info.chat_type)

    def on_send_result(self, result: SendResult) -> None:
        if not result.final:
            return
        if result.ok:
            self.sends_ok += 1
            return
        self.sends_failed += 1
        self.log.error("gateway send failed: request=%s dispatch=%s status=%s error=%s",
                       result.request_id, result.dispatch_id, result.status,
                       result.error)
        self.engine.add_event(kind="send_failed", request_id=result.request_id,
                              dispatch_id=result.dispatch_id, status=result.status,
                              error=result.error, error_code=result.error_code)

    def _apply_context(self, ctx: GatewayContext) -> None:
        self.engine.handle_health({
            "online": ctx.online,
            "listener_running": ctx.listener_running,
            "attached": ctx.attached,
            "chat_title": ctx.chat_title,
            "chat_type": ctx.chat_type,
            "health_ok": ctx.health_ok,
            "upstream_connected": ctx.upstream_connected,
        })

    def on_offer(self, offer: Offer) -> Decision:
        # 网关按消息逐条询问，同批里非最新条目仍按原直连规则丢弃。
        if offer.message.get("is_latest") is not True:
            self.skips += 1
            return Decision.skip()
        self.offers += 1
        self.last_offer_at = fmt_iso(self.engine.clock())
        self.engine.set_cursor(offer.cursor)
        try:
            self.engine.handle_message(offer.message)
        except Exception:
            self.log.exception("gateway offer handler error: id=%s",
                               offer.message.get("id"))
            self.skips += 1
            return Decision.skip()
        replies = self.collector.take()
        if not replies:
            self.skips += 1
            return Decision.skip()
        # 先 consume 结束本轮询问，回复走慢路径 send，避免拖住后面的消息。
        if self.queue is not None:
            for text in replies:
                self.queue.enqueue(text, offer.dispatch_id)
        self.consumes += 1
        return Decision.consume()
