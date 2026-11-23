"""网关接入层测试：用本地假网关跑通 offer/decision/send 与上游状态。"""
from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.server import serve

from game.config import Config
from game.engine import Engine
from game.gateway_app import GatewayApp, GatewaySender
from game.rng import Rng
from game.send_queue import SendQueue
from game.store import Store
from game.util import make_clock

WELCOME = {
    "type": "welcome", "app_id": "social-game", "protocol": 2,
    "heartbeat_seconds": 20, "pin": None,
    "context": {"online": True, "listener_running": True, "attached": True,
                "chat_title": "888 种田大队(32)", "chat_type": "group",
                "health_ok": True, "upstream_connected": True},
}


def make_offer(content: str, *, is_latest: bool = True, msg_id: str = "1",
               dispatch_id: str = "d-1", offer_id: str = "o-1") -> dict:
    return {
        "type": "offer", "offer_id": offer_id, "dispatch_id": dispatch_id,
        "pinned": False, "deadline_ms": 800, "pin": None,
        "message": {"id": msg_id, "cursor": int(msg_id), "sender": "张三",
                    "content": content,
                    "received_at": "2026-11-14T12:00:03+08:00",
                    "is_latest": is_latest, "confidence": 1.0},
    }


class FakeGateway:
    def __init__(self, offers: list[dict], extra_frames: list[dict] | None = None,
                 send_result: dict | None = None):
        self.offers = offers
        self.extra_frames = extra_frames or []
        self.send_result = send_result
        self.hello = None
        self.decisions: list[dict] = []
        self.sends: list[dict] = []
        self.got_decision = asyncio.Event()

    async def handler(self, ws):
        self.hello = json.loads(await ws.recv())
        await ws.send(json.dumps(WELCOME))
        for frame in self.extra_frames:
            await ws.send(json.dumps(frame, ensure_ascii=False))
        for offer in self.offers:
            await ws.send(json.dumps(offer, ensure_ascii=False))
        async for raw in ws:
            frame = json.loads(raw)
            if frame.get("type") == "decision":
                self.decisions.append(frame)
                self.got_decision.set()
            elif frame.get("type") == "send":
                self.sends.append(frame)
                if self.send_result is not None:
                    payload = {"type": "send_result",
                               "request_id": frame.get("request_id", ""),
                               "dispatch_id": frame.get("dispatch_id", ""),
                               "final": True}
                    payload.update(self.send_result)
                    await ws.send(json.dumps(payload, ensure_ascii=False))


def make_cfg(base: Config, url: str) -> Config:
    data = base.as_dict()
    data.update({
        "gateway_url": url,
        "gateway_app_id": "social-game",
        "gateway_token": "t",
        "send_min_interval_ms": 0,
    })
    return Config(data)


def build(cfg: Config, db_path):
    log = logging.getLogger("test.gateway")
    store = Store(db_path)
    engine = Engine(cfg, store, make_clock(cfg.get("timezone")), Rng(), log)
    gateway = GatewayApp(cfg, engine, log)
    queue = SendQueue(GatewaySender(gateway.client), cfg, log,
                      event_sink=engine.add_event)
    gateway.attach_queue(queue)
    engine.attach_sender(gateway.collector)
    return engine, gateway, queue


async def run_app(fake: FakeGateway, cfg: Config, db_path, wait_decision: bool = True):
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = make_cfg(cfg, f"ws://127.0.0.1:{port}/api/v1/gateway/ws/app")
        engine, gateway, queue = build(cfg, db_path)
        qtask = asyncio.create_task(queue.run())
        gtask = asyncio.create_task(gateway.run())
        try:
            if wait_decision:
                await asyncio.wait_for(fake.got_decision.wait(), 5)
            await asyncio.sleep(0.3)
        finally:
            await gateway.client.stop()
            gtask.cancel()
            qtask.cancel()
            await asyncio.gather(gtask, qtask, return_exceptions=True)
        return engine, gateway


def test_welcome_context_drives_group_and_online(cfg, tmp_path):
    async def run():
        fake = FakeGateway([])
        engine, gateway = await run_app(fake, cfg, tmp_path / "gw0.db",
                                        wait_decision=False)
        return engine, gateway

    engine, gateway = asyncio.run(run())
    assert engine.tracker.key == "888种田大队"
    assert engine.online is True
    assert engine.listener_running is True
    assert gateway.status()["context"]["chat_title"] == "888 种田大队(32)"


def test_offer_consumed_and_reply_sent(cfg, tmp_path):
    async def run():
        fake = FakeGateway([make_offer("签到")])
        engine, gateway = await run_app(fake, cfg, tmp_path / "gw1.db")
        return fake, engine, gateway

    fake, engine, gateway = asyncio.run(run())
    assert fake.hello["type"] == "hello"
    assert fake.hello["protocol"] == 2
    assert fake.hello["app_id"] == "social-game"
    assert fake.hello["token"] == "t"
    assert fake.hello["rules"] == gateway.rules
    assert gateway.rules and gateway.status()["rules"] == {
        "source": "auto", "count": len(gateway.rules)}
    assert fake.decisions[0]["action"] == "consume"
    assert fake.decisions[0]["offer_id"] == "o-1"
    assert "reply" not in fake.decisions[0]
    assert fake.sends and "签到成功" in fake.sends[0]["text"]
    assert fake.sends[0]["dispatch_id"] == "d-1"
    assert fake.sends[0]["request_id"].startswith("r-")
    assert engine.cursor == 1


def test_rules_from_config_override(cfg, tmp_path):
    async def run():
        data = cfg.as_dict()
        data["gateway_rules"] = [{"keywords": ["签到"]}]
        fake = FakeGateway([make_offer("签到")])
        engine, gateway = await run_app(fake, Config(data), tmp_path / "gw1b.db")
        return fake, gateway

    fake, gateway = asyncio.run(run())
    assert fake.hello["rules"] == [{"keywords": ["签到"]}]
    assert gateway.status()["rules"] == {"source": "config", "count": 1}


def test_offer_rewritten_without_reply(cfg, tmp_path):
    async def run():
        fake = FakeGateway([make_offer("大家早安")])
        await run_app(fake, cfg, tmp_path / "gw2.db")
        return fake

    fake = asyncio.run(run())
    assert fake.decisions[0]["action"] == "rewrite"
    assert fake.sends == []


def test_offer_ignored_when_not_latest(cfg, tmp_path):
    async def run():
        fake = FakeGateway([make_offer("签到", is_latest=False)])
        engine, gateway = await run_app(fake, cfg, tmp_path / "gw3.db")
        return fake, engine, gateway

    fake, engine, gateway = asyncio.run(run())
    assert fake.decisions[0]["action"] == "rewrite"
    assert fake.sends == []
    assert engine.cursor == 0
    assert gateway.offers == 0
    assert gateway.rewrites == 1


def test_upstream_state_updates_context(cfg, tmp_path):
    async def run():
        fake = FakeGateway([], extra_frames=[{
            "type": "upstream_state", "online": False, "listener_running": False,
            "attached": True, "chat_title": "", "chat_type": None,
            "health_ok": False, "health_error": "WECHAT_OFFLINE",
            "upstream_connected": True}])
        engine, gateway = await run_app(fake, cfg, tmp_path / "gw4.db",
                                        wait_decision=False)
        return engine, gateway

    engine, gateway = asyncio.run(run())
    assert engine.online is False
    assert engine.listener_running is False
    assert gateway.status()["context"]["health_ok"] is False
    assert "upstream_state" in [e["kind"] for e in engine.get_recent_events()]


def test_chat_changed_updates_title(cfg, tmp_path):
    async def run():
        fake = FakeGateway([], extra_frames=[{
            "type": "chat_changed", "chat_title": "测试君群聊 (3)",
            "chat_type": "group", "occurred_at": "2026-11-17T21:00:00+08:00"}])
        engine, gateway = await run_app(fake, cfg, tmp_path / "gw5.db",
                                        wait_decision=False)
        return engine, gateway

    engine, gateway = asyncio.run(run())
    assert engine.tracker.title == "测试君群聊 (3)"
    assert gateway.status()["context"]["chat_title"] == "测试君群聊 (3)"
    assert "chat_changed" in [e["kind"] for e in engine.get_recent_events()]


def test_send_failure_recorded(cfg, tmp_path):
    async def run():
        fake = FakeGateway([make_offer("签到")], send_result={
            "status": "failed", "ok": False,
            "error": "发送失败", "error_code": "SEND_FAILED"})
        engine, gateway = await run_app(fake, cfg, tmp_path / "gw6.db")
        return engine, gateway

    engine, gateway = asyncio.run(run())
    assert gateway.sends_failed == 1
    events = [e for e in engine.get_recent_events() if e["kind"] == "send_failed"]
    assert events and events[0]["error_code"] == "SEND_FAILED"


def test_auth_error_stops_client(cfg, tmp_path):
    async def handler(ws):
        await ws.close(code=4401)

    async def run():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            cfg2 = make_cfg(cfg, f"ws://127.0.0.1:{port}/api/v1/gateway/ws/app")
            engine, gateway, _ = build(cfg2, tmp_path / "gw7.db")
            await asyncio.wait_for(gateway.run(), 5)
            return engine, gateway

    engine, gateway = asyncio.run(run())
    assert "token 不匹配" in (gateway.last_error or "")
    assert [e["kind"] for e in engine.get_recent_events()] == ["gateway_auth_error"]
