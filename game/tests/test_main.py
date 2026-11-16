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


def test_ws_loop_dispatches_and_tracks_cursor():
    client = FakeClient([
        {"type": "ready", "cursor": 10, "buffer_size": 0},
        {"type": "messages", "next_cursor": 11,
         "items": [{"id": "11", "sender": "张三", "content": "签到"}]},
    ], error=ApiError("NETWORK_ERROR", "closed"))
    engine = FakeEngine()

    async def run():
        task = asyncio.create_task(ws_loop(client, engine))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert engine.cursor == 11
    assert [m["id"] for m in engine.messages] == ["11"]
    assert engine.last_error == "ws: NETWORK_ERROR"
