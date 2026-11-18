"""发送队列拆分与投递逻辑测试。"""
from __future__ import annotations

import asyncio
import logging

from game.send_queue import SendQueue, split_reply


def test_short_reply_untouched():
    text = "签到成功！获得 10 金币。"
    assert split_reply(text, 500) == [text]


def test_long_reply_split_by_lines():
    lines = [f"第{i}行内容" for i in range(100)]
    text = "\n".join(lines)
    parts = split_reply(text, 500)
    assert len(parts) >= 2
    assert all(len(p) <= 500 for p in parts)
    assert parts[0].startswith("(1/")
    assert parts[-1].startswith(f"({len(parts)}/")
    joined = "\n".join(p.split("\n", 1)[1] for p in parts)
    assert joined == text


def test_single_overlong_line_chunked():
    text = "甲" * 1200
    parts = split_reply(text, 500)
    assert len(parts) >= 3
    assert all(len(p) <= 500 for p in parts)


class StubCfg:
    def __init__(self, **overrides):
        self.data = {
            "send_queue_max": 10,
            "reply_max_chars": 500,
            "send_max_per_minute": 15,
            "send_min_interval_ms": 0,
        }
        self.data.update(overrides)

    def get(self, key):
        return self.data[key]


class RecordingSender:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    async def send(self, text: str, dispatch_id: str = "") -> None:
        if self.fail:
            raise RuntimeError("gateway closed")
        self.sent.append((text, dispatch_id))


def drain(queue: SendQueue) -> None:
    async def run():
        task = asyncio.create_task(queue.run())
        await queue.q.join()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_queue_sends_with_dispatch_id():
    sender = RecordingSender()
    queue = SendQueue(sender, StubCfg(), logging.getLogger("test.queue"))
    queue.enqueue("签到成功", "d-1")
    drain(queue)
    assert sender.sent == [("签到成功", "d-1")]


def test_queue_records_send_failure():
    events: list[dict] = []
    sender = RecordingSender(fail=True)
    queue = SendQueue(sender, StubCfg(), logging.getLogger("test.queue"),
                      event_sink=lambda **kw: events.append(kw))
    queue.enqueue("签到成功", "d-2")
    drain(queue)
    assert events and events[0]["kind"] == "send_failed"
    assert sender.sent == []
