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
