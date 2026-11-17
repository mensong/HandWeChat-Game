"""玩家删除功能测试（单个删除 / 影子清理 / 清空整群 / 控制台端点）。"""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from game.console import build_console_handler


def make_server(env, tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(env.cfg.as_dict(), ensure_ascii=False),
                        encoding="utf-8")
    handler = build_console_handler(env.engine, env.cfg, str(cfg_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def post(base, path, body):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        return 200, json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_delete_player_cascades(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    result = env.store.delete_player(env.group, "张三")
    assert result["released_slaves"] == 1
    assert env.store.get_player(env.group, "张三") is None
    li = env.store.get_player(env.group, "李四")
    assert li is not None and li.master is None
    rows = env.store._conn.execute(
        "SELECT COUNT(*) AS c FROM coin_ledger WHERE actor='张三'").fetchone()
    assert rows["c"] > 0  # 流水默认保留


def test_delete_player_purge_history(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.store.delete_player(env.group, "张三", purge_history=True)
    rows = env.store._conn.execute(
        "SELECT COUNT(*) AS c FROM coin_ledger "
        "WHERE actor='张三' OR counterparty='张三'").fetchone()
    assert rows["c"] == 0


def test_delete_player_not_found(env):
    with pytest.raises(LookupError):
        env.store.delete_player(env.group, "不存在")


def test_delete_phantoms(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@影子甲")
    n = env.store.delete_phantom_players(env.group)
    assert n >= 1
    assert env.store.get_player(env.group, "影子甲") is None
    assert env.store.get_player(env.group, "张三") is not None


def test_clear_group(env):
    env.send("张三", "我的金币")
    env.send("李四", "我的金币")
    result = env.store.clear_group_data(env.group)
    assert result["players"] == 2
    assert env.store.get_player(env.group, "张三") is None
    assert env.store.get_player(env.group, "李四") is None


def test_console_delete_endpoints(env, tmp_path):
    server, base = make_server(env, tmp_path)
    try:
        env.rng.set_sequence([1.0])
        env.send("张三", "购买奴隶@李四")

        code, _ = post(base, "/api/players/delete", {"name": "不存在"})
        assert code == 400

        code, data = post(base, "/api/players/delete", {"name": "张三"})
        assert code == 200 and data["released_slaves"] == 1

        env.send("李四", "我的金币")  # 影子转正
        env.rng.set_sequence([1.0])
        env.send("王五", "购买奴隶@影子乙")
        code, data = post(base, "/api/players/delete_phantoms", {})
        assert code == 200 and data["deleted"] >= 1

        code, _ = post(base, "/api/players/clear_group", {"confirm": "错误"})
        assert code == 400
        code, data = post(base, "/api/players/clear_group", {"confirm": env.group})
        assert code == 200 and data["players"] == 2

        players = json.loads(urllib.request.urlopen(
            base + "/api/players").read())
        assert players["players"] == []
    finally:
        server.shutdown()
