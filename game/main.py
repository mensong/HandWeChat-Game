"""服务入口：python -m game.main --config config/game_config.json"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Config, load_config
from .console import build_console_server
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


async def bootstrap(client: WechatClient, engine: Engine) -> None:
    """等待微信在线；OCR 监听由使用端负责，本服务不主动启动。连接前已产生的消息不回补。"""
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
    log.info("wechat online, listener_running=%s, waiting for websocket messages",
             bool(h.get("listener_running")))


async def ws_loop(client: WechatClient, engine: Engine) -> None:
    backoff_idx = 0
    while True:
        try:
            async for frame in client.stream_frames():
                if frame.get("type") == "ready":
                    backoff_idx = 0
                    cursor = int(frame.get("cursor", 0))
                    if cursor < engine.cursor:
                        log.warning("API_CURSOR_RESET: %d -> %d", engine.cursor, cursor)
                    engine.set_cursor(cursor)
                    log.info("websocket ready: cursor=%d buffer_size=%s",
                             cursor, frame.get("buffer_size"))
                    continue
                for item in frame.get("items", []):
                    engine.handle_message(item)
                engine.set_cursor(int(frame.get("next_cursor", engine.cursor)))
            log.warning("websocket closed by server")
            engine.add_event(kind="ws_closed")
        except ApiError as e:
            engine.last_error = f"ws: {e.code}"
            engine.add_event(kind="ws_error", message=str(e))
            log.warning("websocket error: %s", e)
        except Exception as e:
            engine.last_error = "ws: unexpected"
            engine.add_event(kind="ws_error", message=type(e).__name__)
            log.exception("websocket unexpected error")
        await asyncio.sleep(BACKOFF_STEPS[backoff_idx])
        backoff_idx = min(backoff_idx + 1, len(BACKOFF_STEPS) - 1)


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


async def async_main(cfg: Config, db_path: str, cfg_path: str) -> None:
    store = Store(db_path)
    clock = make_clock(cfg.get("timezone"))
    rng = Rng()
    client = WechatClient(cfg.get("api_base_url"), cfg.get("api_timeout_seconds"))
    engine = Engine(cfg, store, clock, rng, log)
    queue = SendQueue(client, cfg, log, event_sink=engine.add_event)
    engine.attach_sender(queue)
    log.info("game service starting, db=%s api=%s", db_path, cfg.get("api_base_url"))

    server = build_console_server(engine, cfg, cfg_path)
    log.info("console listening on http://%s:%d/", cfg.get("web_host"),
             cfg.get("health_port"))
    await bootstrap(client, engine)

    tasks = [
        asyncio.create_task(queue.run(), name="send-worker"),
        asyncio.create_task(health_loop(client, cfg, engine), name="health-loop"),
        asyncio.create_task(ws_loop(client, engine), name="ws-loop"),
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
        asyncio.run(async_main(cfg, args.db, args.config))
    except KeyboardInterrupt:
        log.info("interrupted, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
