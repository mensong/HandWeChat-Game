"""服务入口：python -m game.main --config config/game_config.json"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Config, load_config
from .engine import Engine
from .rng import Rng
from .send_queue import SendQueue
from .store import Store
from .util import make_clock
from .wechat_client import ApiError, WechatClient

log = logging.getLogger("game")

BACKOFF_STEPS = [1, 2, 5, 10, 30]


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "game.log", maxBytes=10 * 1024 * 1024,
                                  backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.addHandler(console)


def start_health_server(port: int, engine: Engine) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body = json.dumps(engine.stats(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def bootstrap(client: WechatClient, cfg: Config, engine: Engine) -> int:
    """等待微信在线、启动监听、丢弃积压消息，返回起始游标。"""
    while True:
        try:
            h = await client.health()
        except ApiError as e:
            log.error("health check failed: %s", e)
            await asyncio.sleep(10)
            continue
        engine.handle_health(h)
        if not h.get("online"):
            log.warning("wechat offline, retry in 10s")
            await asyncio.sleep(10)
            continue
        break
    if not h.get("listener_running"):
        try:
            await client.start_listener()
            log.info("ocr listener started")
        except ApiError as e:
            log.error("listener start failed: %s", e)
    cursor = 0
    while True:
        try:
            batch = await client.messages(cursor, cfg.get("poll_limit"), 0)
        except ApiError as e:
            log.error("backlog drain failed: %s", e)
            await asyncio.sleep(10)
            continue
        cursor = int(batch.get("next_cursor", cursor))
        engine.set_cursor(cursor)
        if not batch.get("has_more"):
            break
    log.info("startup: skipped %d backlog messages, cursor=%d", cursor, cursor)
    return cursor


async def poll_loop(client: WechatClient, cfg: Config, engine: Engine, cursor: int) -> None:
    backoff_idx = 0
    while True:
        try:
            batch = await client.messages(cursor, cfg.get("poll_limit"),
                                          cfg.get("poll_timeout_seconds"))
            backoff_idx = 0
        except ApiError as e:
            engine.last_error = f"poll: {e.code}"
            log.warning("poll error: %s", e)
            if e.code in ("WECHAT_OFFLINE", "ATTACH_FAILED"):
                try:
                    await client.attach()
                except ApiError as e2:
                    log.warning("attach failed: %s", e2)
            elif e.code == "OCR_CHANNEL_NOT_RUNNING":
                try:
                    await client.start_listener()
                except ApiError as e2:
                    log.warning("listener start failed: %s", e2)
            elif e.code in ("INVALID_REQUEST",):
                log.error("poll rejected: %s", e)
            await asyncio.sleep(BACKOFF_STEPS[backoff_idx])
            backoff_idx = min(backoff_idx + 1, len(BACKOFF_STEPS) - 1)
            continue
        except Exception as e:
            engine.last_error = f"poll: {type(e).__name__}"
            log.exception("poll unexpected error")
            await asyncio.sleep(BACKOFF_STEPS[backoff_idx])
            backoff_idx = min(backoff_idx + 1, len(BACKOFF_STEPS) - 1)
            continue

        next_cursor = int(batch.get("next_cursor", cursor))
        if next_cursor < cursor:
            log.warning("API_CURSOR_RESET: %d -> %d, discard batch", cursor, next_cursor)
            engine.set_cursor(next_cursor)
            cursor = next_cursor
            continue
        for item in batch.get("items", []):
            engine.handle_message(item)
        cursor = next_cursor
        engine.set_cursor(cursor)


async def health_loop(client: WechatClient, cfg: Config, engine: Engine) -> None:
    while True:
        try:
            h = await client.health()
            engine.handle_health(h)
        except ApiError as e:
            engine.last_error = f"health: {e.code}"
            log.debug("health poll failed: %s", e)
        except Exception:
            log.exception("health poll unexpected error")
        await asyncio.sleep(cfg.get("health_poll_seconds"))


async def async_main(cfg: Config, db_path: str) -> None:
    store = Store(db_path)
    clock = make_clock(cfg.get("timezone"))
    rng = Rng()
    client = WechatClient(cfg.get("api_base_url"), cfg.get("api_timeout_seconds"))
    queue = SendQueue(client, cfg, log)
    engine = Engine(cfg, store, clock, rng, log)
    engine.attach_sender(queue)
    log.info("game service starting, db=%s api=%s", db_path, cfg.get("api_base_url"))

    server = start_health_server(cfg.get("health_port"), engine)
    cursor = await bootstrap(client, cfg, engine)

    tasks = [
        asyncio.create_task(queue.run(), name="send-worker"),
        asyncio.create_task(health_loop(client, cfg, engine), name="health-loop"),
        asyncio.create_task(poll_loop(client, cfg, engine, cursor), name="poll-loop"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.join_with_timeout(10)
        store.close()
        server.shutdown()
        log.info("game service stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="微信群社交游戏服务")
    parser.add_argument("--config", default="config/game_config.json")
    parser.add_argument("--db", default="data/game.db")
    parser.add_argument("--log-dir", default="data/logs")
    args = parser.parse_args(argv)

    setup_logging(Path(args.log_dir))
    try:
        cfg = load_config(args.config)
    except Exception as e:
        log.error("config load failed: %s", e)
        return 1

    try:
        asyncio.run(async_main(cfg, args.db))
    except KeyboardInterrupt:
        log.info("interrupted, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
