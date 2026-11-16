"""WechatClient 与假 HandWeChat API 的联调测试。"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from websockets.asyncio.server import serve

from game.wechat_client import ApiError, WechatClient


class FakeApi:
    def __init__(self):
        self.replies = {}

    def handle(self, method, path, query, body):
        if method == "GET" and path == "/api/v1/health":
            return 200, {"status": "ok", "online": True, "listener_running": True,
                         "chat_title": "888 种田大队(32)"}
        if method == "POST" and path == "/api/v1/send":
            task_id = f"send_test_{len(self.replies)}"
            self.replies[task_id] = {"task_id": task_id, "status": "success",
                                     "text": body.get("text")}
            return 202, {"task_id": task_id, "status": "queued"}
        if method == "GET" and path.startswith("/api/v1/send/"):
            task_id = path.rsplit("/", 1)[1]
            if task_id not in self.replies:
                return 404, {"code": "SEND_TASK_NOT_FOUND", "message": "not found"}
            return 200, self.replies[task_id]
        return 404, {"code": "NOT_FOUND", "message": "no route"}


@pytest.fixture()
def fake_api():
    api = FakeApi()

    class Handler(BaseHTTPRequestHandler):
        def _run(self):
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
        resp = await client.send("测试消息")
        task = await client.send_task(resp["task_id"])
        assert task["status"] == "success"

    asyncio.run(run())


def test_client_error_mapping(fake_api):
    api, base = fake_api
    client = WechatClient(base, timeout=5)

    async def run():
        with pytest.raises(ApiError) as e:
            await client.send_task("no_such_task")
        assert e.value.code == "SEND_TASK_NOT_FOUND"

    asyncio.run(run())


def test_ws_messages_url():
    assert WechatClient("http://10.0.0.1:8000/").ws_messages_url == \
        "ws://10.0.0.1:8000/api/v1/ws/messages"
    assert WechatClient("https://host").ws_messages_url == \
        "wss://host/api/v1/ws/messages"
    with pytest.raises(ApiError) as e:
        WechatClient("127.0.0.1:8000").ws_messages_url
    assert e.value.code == "INVALID_REQUEST"


def test_stream_frames():
    async def handler(ws):
        await ws.send(json.dumps({"type": "ready", "cursor": 42, "buffer_size": 3},
                                 ensure_ascii=False))
        await ws.send(json.dumps({"type": "ping", "ts": "2026-11-13T12:01:02+08:00"}))
        await ws.send(json.dumps({
            "type": "messages",
            "items": [{"id": "43", "cursor": 43, "sender": "张三", "content": "收到",
                       "received_at": "2026-11-13T12:01:02+08:00"}],
            "next_cursor": 43, "has_more": False}, ensure_ascii=False))
        await ws.send(json.dumps({"type": "error", "code": "INTERNAL_ERROR",
                                  "message": "服务内部错误"}, ensure_ascii=False))

    async def run():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = WechatClient(f"http://127.0.0.1:{port}", timeout=5)
            frames = []
            with pytest.raises(ApiError) as err:
                async for frame in client.stream_frames():
                    frames.append(frame)
            assert err.value.code == "INTERNAL_ERROR"
            assert err.value.message == "服务内部错误"
        assert [f["type"] for f in frames] == ["ready", "messages"]
        assert frames[0]["cursor"] == 42
        assert frames[1]["items"][0]["content"] == "收到"

    asyncio.run(run())


def test_stream_ends_on_server_close():
    async def handler(ws):
        await ws.send(json.dumps({"type": "ready", "cursor": 7, "buffer_size": 0},
                                 ensure_ascii=False))

    async def run():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = WechatClient(f"http://127.0.0.1:{port}", timeout=5)
            frames = [frame async for frame in client.stream_frames()]
        assert [f["type"] for f in frames] == ["ready"]

    asyncio.run(run())


def test_stream_connection_refused():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    async def run():
        client = WechatClient(f"http://127.0.0.1:{port}", timeout=2)
        with pytest.raises(ApiError) as err:
            async for _ in client.stream_frames():
                pass
        assert err.value.code == "NETWORK_ERROR"

    asyncio.run(run())
