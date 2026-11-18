"""出站发送队列：限速、拆分与失败记录。发送统一走网关。"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

PREFIX_RESERVE = 10


def split_reply(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    budget = max_chars - PREFIX_RESERVE
    groups: list[str] = []
    cur = ""
    for line in text.split("\n"):
        candidate = line if not cur else cur + "\n" + line
        if len(candidate) <= budget:
            cur = candidate
            continue
        if cur:
            groups.append(cur)
            cur = ""
        while len(line) > budget:
            groups.append(line[:budget])
            line = line[budget:]
        cur = line
    if cur:
        groups.append(cur)
    n = len(groups)
    return [f"({i}/{n})\n{g}" for i, g in enumerate(groups, 1)]


class SendQueue:
    """sender 只需实现 `async send(text, dispatch_id="")`。"""

    def __init__(self, sender, cfg, log: logging.Logger, event_sink=None):
        self.sender = sender
        self.cfg = cfg
        self.log = log
        self.event_sink = event_sink
        self.q: asyncio.Queue = asyncio.Queue(maxsize=cfg.get("send_queue_max"))
        self._sent_times: deque[float] = deque()

    def _event(self, kind: str, **fields) -> None:
        if self.event_sink is not None:
            self.event_sink(kind=kind, **fields)

    def enqueue(self, text: str, dispatch_id: str = "") -> bool:
        try:
            self.q.put_nowait((text, dispatch_id))
            return True
        except asyncio.QueueFull:
            self.log.warning("SEND_QUEUE_FULL, drop reply (%d chars)", len(text))
            self._event("send_queue_full", text_len=len(text))
            return False

    @property
    def size(self) -> int:
        return self.q.qsize()

    async def join_with_timeout(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self.q.join(), timeout)
        except asyncio.TimeoutError:
            pass

    async def run(self) -> None:
        while True:
            text, dispatch_id = await self.q.get()
            try:
                for part in split_reply(text, self.cfg.get("reply_max_chars")):
                    await self._send_with_rate_limit(part, dispatch_id)
            except Exception:
                self.log.exception("send worker error")
            finally:
                self.q.task_done()

    async def _send_with_rate_limit(self, text: str, dispatch_id: str = "") -> None:
        loop = asyncio.get_running_loop()
        max_per_min = self.cfg.get("send_max_per_minute")
        min_interval = self.cfg.get("send_min_interval_ms") / 1000
        while True:
            now = loop.time()
            while self._sent_times and now - self._sent_times[0] > 60:
                self._sent_times.popleft()
            if len(self._sent_times) >= max_per_min:
                await asyncio.sleep(60 - (now - self._sent_times[0]) + 0.05)
                continue
            if self._sent_times and now - self._sent_times[-1] < min_interval:
                await asyncio.sleep(min_interval - (now - self._sent_times[-1]) + 0.05)
                continue
            break
        self._sent_times.append(loop.time())
        await self._send_one(text, dispatch_id)

    async def _send_one(self, text: str, dispatch_id: str = "") -> None:
        try:
            await self.sender.send(text, dispatch_id=dispatch_id)
        except Exception as e:
            self.log.error("send failed: %s", e)
            self._event("send_failed", error=str(e), text_len=len(text))
