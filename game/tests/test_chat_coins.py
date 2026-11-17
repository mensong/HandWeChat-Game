"""聊天收入（每条消息加金币）测试。"""


def coins(e, name):
    return e.store.get_player(e.group, name).coins


def ledger_chat_rows(e, name):
    return e.store._conn.execute(
        "SELECT amount FROM coin_ledger WHERE actor=? AND reason='chat' ORDER BY id",
        (name,)).fetchall()


def test_chat_coins_awarded_per_message(env_chat):
    env_chat.send("张三", "今天天气不错")  # 非指令消息也计入
    env_chat.send("张三", "哈哈")
    assert coins(env_chat, "张三") == 200 + 20
    rows = ledger_chat_rows(env_chat, "张三")
    assert len(rows) == 2 and all(r["amount"] == 10 for r in rows)


def test_chat_coins_daily_cap(env_chat):
    for text in ("1", "2", "3", "4"):
        env_chat.send("张三", text)
    assert coins(env_chat, "张三") == 200 + 40
    # 手动把今日已计入额度推到接近上限（500），验证封顶与零头补齐
    env_chat.store.incr_daily(env_chat.group, env_chat.clock.t.date().isoformat(),
                              "张三", "chat", 0, 455)
    env_chat.send("张三", "5")
    assert coins(env_chat, "张三") == 240 + 5  # 只补齐剩余 5 金币
    env_chat.send("张三", "6")
    assert coins(env_chat, "张三") == 245  # 达到上限后不再发放
    rows = ledger_chat_rows(env_chat, "张三")
    assert rows[-1]["amount"] == 5


def test_chat_coins_not_for_ignored_senders(env_chat):
    env_chat.send("我", "签到", advance=0)
    env_chat.send("对方", "哈哈", advance=0)
    assert env_chat.store.get_player(env_chat.group, "我") is None
    assert env_chat.store.get_player(env_chat.group, "对方") is None


def test_chat_coins_dup_content_not_awarded_twice(env_chat):
    env_chat.send("张三", "水一贴")
    env_chat.send("张三", "水一贴", advance=0)  # 5 秒内容去重命中
    assert coins(env_chat, "张三") == 210
    assert len(ledger_chat_rows(env_chat, "张三")) == 1


def test_chat_coins_disabled_by_config(env_chat):
    from game.config import Config
    from game.engine import Engine
    data = {k: env_chat.cfg.get(k) for k in env_chat.cfg._data}
    data["chat_coins_per_message"] = 0
    engine2 = Engine(Config(data), env_chat.store, env_chat.clock,
                     env_chat.rng, env_chat.engine.ctx.log)
    engine2.attach_sender(env_chat.sender)
    engine2.handle_health({"chat_title": "888 种田大队(32)",
                           "online": True, "listener_running": True})
    engine2.handle_message({"id": "900", "cursor": 900, "sender": "张三",
                            "content": "水一贴",
                            "received_at": env_chat.clock.t.isoformat()})
    assert env_chat.store.get_player(env_chat.group, "张三").coins == 200
