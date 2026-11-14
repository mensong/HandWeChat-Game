"""HandWeChat HTTP API 客户端（标准库实现）。"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request


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

    async def health(self) -> dict:
        return await self._request("GET", "/api/v1/health")

    async def attach(self) -> dict:
        return await self._request("POST", "/api/v1/attach", body={})

    async def start_listener(self) -> dict:
        return await self._request("POST", "/api/v1/listener/start", body={})

    async def messages(self, cursor: int, limit: int, timeout: int) -> dict:
        return await self._request(
            "GET", "/api/v1/messages",
            params={"cursor": cursor, "limit": limit, "timeout": timeout},
        )

    async def send(self, text: str) -> dict:
        return await self._request("POST", "/api/v1/send", body={"text": text})

    async def send_task(self, task_id: str) -> dict:
        return await self._request("GET", f"/api/v1/send/{task_id}")
