"""HandWeChat API 客户端：HTTP 请求 + WebSocket 消息推送。"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class WechatClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def ws_messages_url(self) -> str:
        if self.base.startswith("https://"):
            rest, scheme = self.base[len("https://"):], "wss://"
        elif self.base.startswith("http://"):
            rest, scheme = self.base[len("http://"):], "ws://"
        else:
            raise ApiError("INVALID_REQUEST",
                           f"api_base_url must start with http:// or https://: {self.base}")
        return f"{scheme}{rest}/api/v1/ws/messages"

    async def _request(self, method: str, path: str,
                       params: dict | None = None, body: dict | None = None) -> dict:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        def do() -> tuple[int, bytes]:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()

        try:
            status, raw = await asyncio.to_thread(do)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}
            raise ApiError(payload.get("code", "HTTP_ERROR"),
                           payload.get("message", str(e)), e.code)
        except urllib.error.URLError as e:
            raise ApiError("NETWORK_ERROR", str(e.reason))
        except TimeoutError:
            raise ApiError("NETWORK_ERROR", "request timeout")
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ApiError("HTTP_ERROR", f"invalid JSON response: {e}", status)

    async def stream_frames(self) -> AsyncIterator[dict]:
        """接收 WS 推送帧：原样产出 ready / messages，忽略 ping，error 帧抛 ApiError。

        proxy=None：服务部署在内网，不能被系统代理接管，否则 ws 连接会被劫持。
        """
        try:
            async with connect(self.ws_messages_url, open_timeout=self.timeout,
                               ping_interval=20, ping_timeout=20, proxy=None) as ws:
                async for raw in ws:
                    frame = self._parse_frame(raw)
                    kind = frame.get("type")
                    if kind == "error":
                        raise ApiError(frame.get("code", "INTERNAL_ERROR"),
                                       frame.get("message", "websocket error"))
                    if kind in ("ready", "messages"):
                        yield frame
        except WebSocketException as e:
            raise ApiError("NETWORK_ERROR", f"websocket closed: {e}") from e
        except TimeoutError as e:
            raise ApiError("NETWORK_ERROR", "websocket timeout") from e
        except OSError as e:
            raise ApiError("NETWORK_ERROR", str(e)) from e

    @staticmethod
    def _parse_frame(raw: str | bytes) -> dict:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            frame = json.loads(text)
        except json.JSONDecodeError as e:
            raise ApiError("INTERNAL_ERROR", f"invalid frame: {e}") from e
        if not isinstance(frame, dict):
            raise ApiError("INTERNAL_ERROR", "frame is not a JSON object")
        return frame

    async def health(self) -> dict:
        return await self._request("GET", "/api/v1/health")

    async def send(self, text: str) -> dict:
        return await self._request("POST", "/api/v1/send", body={"text": text})

    async def send_task(self, task_id: str) -> dict:
        return await self._request("GET", f"/api/v1/send/{task_id}")
