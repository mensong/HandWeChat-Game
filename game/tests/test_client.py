"""WechatClient 与假 HandWeChat API 的联调测试。"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from game.wechat_client import ApiError, WechatClient


class FakeApi:
    def __init__(self):
        self.replies = {}
        self.messages = []

    def handle(self, method, path, query, body):
        if method == "GET" and path == "/api/v1/health":
            return 200, {"status": "ok", "online": True, "listener_running": True,
                         "chat_title": "888 种田大队(32)"}
        if method == "GET" and path == "/api/v1/messages":
            cursor = int(query.get("cursor", 0))
            items = [{"id": str(m["cursor"]), "cursor": m["cursor"], "sender": m["sender"],
                      "content": m["content"], "received_at": m["received_at"]}
                     for m in self.messages if m["cursor"] > cursor]
            return 200, {"items": items, "next_cursor": max([cursor] + [m["cursor"] for m in self.messages]),
                         "has_more": False}
        if method == "POST" and path == "/api/v1/send":
            task_id = f"send_test_{len(self.replies)}"
            self.replies[task_id] = {"task_id": task_id, "status": "success", "text": body.get("text")}
            return 202, {"task_id": task_id, "status": "queued"}
        if method == "GET" and path.startswith("/api/v1/send/"):
            task_id = path.rsplit("/", 1)[1]
            if task_id not in self.replies:
                return 404, {"code": "SEND_TASK_NOT_FOUND", "message": "not found"}
            return 200, self.replies[task_id]
        if method == "POST" and path == "/api/v1/listener/start":
            return 200, {"status": "running"}
        return 404, {"code": "NOT_FOUND", "message": "no route"}


@pytest.fixture()
def fake_api():
    api = FakeApi()

    class Handler(BaseHTTPRequestHandler):
        def _run(self):
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            body = {}
            if length:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            status, payload = api.handle(self.command, parsed.path, query, body)
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = _run

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield api, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_client_end_to_end(fake_api):
    api, base = fake_api
    client = WechatClient(base, timeout=5)

    async def run():
        health = await client.health()
        assert health["online"] is True
        api.messages.append({"cursor": 7, "sender": "张三", "content": "签到",
                             "received_at": "2026-11-14T12:00:00+08:00"})
        batch = await client.messages(0, 100, 0)
        assert batch["items"][0]["sender"] == "张三"
        assert batch["next_cursor"] == 7
        resp = await client.send("测试消息")
        task = await client.send_task(resp["task_id"])
        assert task["status"] == "success"
        await client.start_listener()

    asyncio.run(run())


def test_client_error_mapping(fake_api):
    api, base = fake_api
    client = WechatClient(base, timeout=5)

    async def run():
        with pytest.raises(ApiError) as e:
            await client.send_task("no_such_task")
        assert e.value.code == "SEND_TASK_NOT_FOUND"

    asyncio.run(run())
