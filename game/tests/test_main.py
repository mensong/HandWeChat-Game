"""main.ws_loop 的消息分发与游标处理。"""
from __future__ import annotations

import asyncio

from game.main import ws_loop
from game.wechat_client import ApiError


class FakeClient:
    def __init__(self, frames, error=None):
        self.frames = frames
        self.error = error
        self.connects = 0

    async def stream_frames(self):
        self.connects += 1
        if self.connects > 1:
            await asyncio.sleep(3600)
        for frame in self.frames:
            yield frame
        if self.error is not None:
            raise self.error


class FakeEngine:
    def __init__(self):
        self.cursor = 0
        self.messages = []
        self.last_error = None

    def set_cursor(self, cursor):
        self.cursor = cursor

    def handle_message(self, msg):
        self.messages.append(msg)


def run_loop(client):
    engine = FakeEngine()

    async def run():
        task = asyncio.create_task(ws_loop(client, engine))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    return engine


def test_ws_loop_dispatches_and_tracks_last_message():
    client = FakeClient([
        {"type": "ready", "buffer_size": 0},
        {"type": "messages", "has_more": False,
         "items": [{"id": "11", "cursor": 11, "sender": "张三", "content": "签到",
                    "is_latest": True, "confidence": 1.0}]},
    ], error=ApiError("NETWORK_ERROR", "closed"))

    engine = run_loop(client)

    assert engine.cursor == 11
    assert [m["id"] for m in engine.messages] == ["11"]
    assert engine.last_error == "ws: NETWORK_ERROR"


def test_ws_loop_dispatches_only_latest_item_of_batch():
    client = FakeClient([
        {"type": "ready", "buffer_size": 0},
        {"type": "messages", "has_more": False, "items": [
            {"id": "11", "cursor": 11, "sender": "张三", "content": "签到",
             "is_latest": False, "confidence": 1.0},
            {"id": "12", "cursor": 12, "sender": "李四", "content": "我的金币",
             "is_latest": True, "confidence": 1.0},
        ]},
    ], error=ApiError("NETWORK_ERROR", "closed"))

    engine = run_loop(client)

    assert engine.cursor == 12
    assert [m["id"] for m in engine.messages] == ["12"]


def test_ws_loop_processes_repeated_message():
    client = FakeClient([
        {"type": "ready", "buffer_size": 0},
        {"type": "messages", "has_more": False,
         "items": [{"id": "11", "cursor": 11, "sender": "张三", "content": "签到",
                    "is_latest": True, "confidence": 0.7}]},
    ], error=ApiError("NETWORK_ERROR", "closed"))

    engine = run_loop(client)

    assert engine.cursor == 11
    assert [m["id"] for m in engine.messages] == ["11"]


def test_ws_loop_drops_frame_without_is_latest():
    client = FakeClient([
        {"type": "ready", "buffer_size": 0},
        {"type": "messages", "has_more": False,
         "items": [{"id": "11", "cursor": 11, "sender": "张三", "content": "签到"}]},
    ], error=ApiError("NETWORK_ERROR", "closed"))

    engine = run_loop(client)

    assert engine.cursor == 11
    assert engine.messages == []
