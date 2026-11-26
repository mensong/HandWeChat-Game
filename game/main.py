"""服务入口：python -m game.main --config config/game_config.json"""
from __future__ import annotations

import argparse
import asyncio
import logging
import platform
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .banner import print_info, print_logo
from .config import Config, load_config
from .console import build_console_server, make_reload_callback
from .engine import Engine
from .gateway_app import GatewayApp, GatewaySender
from .rng import Rng
from .send_queue import SendQueue
from .store import Store
from .util import make_clock

log = logging.getLogger("game")


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


async def async_main(cfg: Config, db_path: str, cfg_path: str) -> None:
    store = Store(db_path)
    clock = make_clock(cfg.get("timezone"))
    rng = Rng()
    engine = Engine(cfg, store, clock, rng, log)
    gateway = GatewayApp(cfg, engine, log)
    queue = SendQueue(GatewaySender(gateway.client), cfg, log,
                      event_sink=engine.add_event)
    gateway.attach_queue(queue)
    engine.attach_sender(gateway.collector)
    engine.attach_gateway(gateway)
    log.info("game service starting, db=%s gateway=%s app_id=%s",
             db_path, cfg.get("gateway_url"), cfg.get("gateway_app_id"))

    loop = asyncio.get_running_loop()
    reload_callback = make_reload_callback(engine, queue, loop, log)
    server = build_console_server(engine, cfg, cfg_path, reload_callback)
    log.info("console listening on http://%s:%d/", cfg.get("web_host"),
             cfg.get("health_port"))

    tasks = [
        asyncio.create_task(queue.run(), name="send-worker"),
        asyncio.create_task(gateway.run(), name="gateway"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        await gateway.client.stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.join_with_timeout(10)
        store.close()
        server.shutdown()
        log.info("game service stopped")


def startup_info(cfg: Config, cfg_path: str, db_path: str,
                 log_dir: str) -> list[tuple[str, str]]:
    groups = cfg.get("allowed_groups") or []
    group_text = "、".join(str(g) for g in groups) if groups else "全部群"
    host = cfg.get("web_host") or "0.0.0.0"
    port = cfg.get("health_port")
    return [
        ("机器人", str(cfg.get("bot_name") or "-")),
        ("网关", f"{cfg.get('gateway_url')}  app_id={cfg.get('gateway_app_id')}"),
        ("群白名单", group_text),
        ("配置文件", cfg_path),
        ("数据库", db_path),
        ("日志", str(Path(log_dir) / "game.log")),
        ("控制台", f"http://127.0.0.1:{port}/  监听 {host}:{port}"),
        ("运行环境", (f"Python {platform.python_version()} · "
                      f"{platform.system()} {platform.release()}")),
        ("启动时间", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="微信群社交游戏服务")
    parser.add_argument("--config", default="config/game_config.json")
    parser.add_argument("--db", default="data/game.db")
    parser.add_argument("--log-dir", default="data/logs")
    args = parser.parse_args(argv)

    print_logo(__version__)
    setup_logging(Path(args.log_dir))
    try:
        cfg = load_config(args.config)
    except Exception as e:
        log.error("config load failed: %s", e)
        return 1
    print_info(startup_info(cfg, args.config, args.db, args.log_dir))

    try:
        asyncio.run(async_main(cfg, args.db, args.config))
    except KeyboardInterrupt:
        log.info("interrupted, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
