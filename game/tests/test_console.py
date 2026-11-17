"""Web 控制台端点与管理员操作测试。"""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from game.console import build_console_handler
from game.config import Config, read_config_file, write_config_file


def make_server(env, tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(env.cfg.as_dict(), ensure_ascii=False),
                        encoding="utf-8")
    handler = build_console_handler(env.engine, env.cfg, str(cfg_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", cfg_path


def test_store_admin_ops(env):
    env.send("张三", "我的金币")
    balance = env.store.admin_add_coins(env.group, "张三", 500,
                                        env.clock.t.isoformat())
    assert balance == 700
    rows = env.store._conn.execute(
        "SELECT reason FROM coin_ledger WHERE actor='张三' AND reason='admin'"
    ).fetchall()
    assert len(rows) == 1
    env.store.admin_set_charm(env.group, "张三", 88.5)
    assert env.store.get_player(env.group, "张三").charm == 88.5
    with pytest.raises(ValueError):
        env.store.admin_set_charm(env.group, "张三", -1)
    with pytest.raises(ValueError):
        env.store.admin_add_coins(env.group, "张三", -800, env.clock.t.isoformat())
    # 解除奴隶
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.store.admin_clear_master(env.group, "李四")
    assert env.store.get_player(env.group, "李四").master is None
    with pytest.raises(LookupError):
        env.store.admin_clear_master(env.group, "不存在")


def test_console_end_to_end(env, tmp_path):
    server, base, cfg_path = make_server(env, tmp_path)
    try:
        env.send("张三", "签到")
        status = json.loads(urllib.request.urlopen(base + "/api/status").read())
        assert status["game"]["group_key"] == env.group
        assert status["wechat"]["online"] is True
        assert "cfg.json" in status["cfg_path"]

        players = json.loads(urllib.request.urlopen(
            base + "/api/players").read())
        assert players["group"] == env.group
        names = [p["name"] for p in players["players"]]
        assert "张三" in names

        logs = json.loads(urllib.request.urlopen(base + "/api/logs").read())
        cmds = [e for e in logs["events"] if e["kind"] == "command"]
        assert cmds and cmds[-1]["cmd"] == "sign_in"
        assert "签到成功" in cmds[-1]["detail"]

        # 管理员加金币
        req = urllib.request.Request(
            base + "/api/players/edit",
            data=json.dumps({"name": "张三", "action": "add_coins",
                             "amount": 300}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["coins"] == 210 + 300

        # 未知动作 / 不存在玩家 → 400
        req = urllib.request.Request(
            base + "/api/players/edit",
            data=json.dumps({"name": "张三", "action": "bogus"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            assert False, "should fail"
        except urllib.error.HTTPError as e:
            assert e.code == 400

        page = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "游戏控制台" in page
        health = json.loads(urllib.request.urlopen(base + "/health").read())
        assert health["status"] == "ok"
    finally:
        server.shutdown()


def test_console_config_roundtrip(env, tmp_path):
    server, base, cfg_path = make_server(env, tmp_path)
    try:
        _, data = read_config_file(str(cfg_path))
        data["initial_coins"] = 777
        req = urllib.request.Request(
            base + "/api/config/save",
            data=json.dumps({"data": data}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["status"] == "saved"
        assert json.loads(urllib.request.urlopen(base + "/api/config").read())[
            "data"]["initial_coins"] == 777

        data["initial_coins"] = -5
        req = urllib.request.Request(
            base + "/api/config/save",
            data=json.dumps({"data": data}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            assert False, "invalid config should be rejected"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        _, data2 = read_config_file(str(cfg_path))
        assert data2["initial_coins"] == 777
    finally:
        server.shutdown()
        write_config_file(str(cfg_path), env.cfg.as_dict())


def test_apply_config_swaps_refs(env):
    old = env.engine.cfg
    new = Config({**old.as_dict(), "initial_coins": 999, "max_slaves": 8})
    env.engine.apply_config(new)
    assert env.engine.cfg.get("initial_coins") == 999
    assert env.engine.ctx.cfg.get("max_slaves") == 8
    assert env.engine.tracker.cfg.get("initial_coins") == 999
    env.engine.apply_config(old)  # 还原
    assert env.engine.cfg.get("initial_coins") == 200


def test_hot_reload_callback(env, tmp_path):
    import asyncio
    import logging
    from game.console import make_reload_callback

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        cb = make_reload_callback(env.engine, env.sender, loop,
                                  logging.getLogger("test.reload"))
        old = env.engine.cfg.as_dict()
        data = {**old, "initial_coins": 555, "max_slaves": 9}
        info = cb(data)
        assert "initial_coins" in info["changed"]
        assert info["restart_required"] == []
        assert env.engine.cfg.get("initial_coins") == 555
        assert env.engine.ctx.cfg.get("max_slaves") == 9

        data2 = {**old, "initial_coins": 555, "api_base_url": "http://1.2.3.4:8000"}
        info2 = cb(data2)
        assert info2["restart_required"] == ["api_base_url"]

        with pytest.raises(Exception):
            cb({**old, "gifts": []})  # 非法配置 → 校验失败
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_console_save_triggers_hot_reload(env, tmp_path):
    server, base = make_server_with_reload(env, tmp_path)
    try:
        _, data = read_config_file(str(tmp_path / "cfg.json"))
        data["initial_coins"] = 888
        code, resp = post(base, "/api/config/save", {"data": data})
        assert code == 200 and resp["status"] == "saved"
        assert resp["changed"] == ["initial_coins"]
        assert resp["restart_required"] == []
        assert env.engine.cfg.get("initial_coins") == 888
    finally:
        server.shutdown()
        write_config_file(str(tmp_path / "cfg.json"), env.cfg.as_dict())


def post(base, path, body):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        return 200, json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def make_server_with_reload(env, tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(env.cfg.as_dict(), ensure_ascii=False),
                        encoding="utf-8")
    import asyncio
    import logging
    from game.console import make_reload_callback
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    cb = make_reload_callback(env.engine, env.sender, loop,
                              logging.getLogger("test.reload"))
    handler = build_console_handler(env.engine, env.cfg, str(cfg_path), cb)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
