"""端到端处理器测试（内存库 + 固定随机源）。"""


def coins(env, name):
    return env.store.get_player(env.group, name).coins


def charm(env, name):
    return env.store.get_player(env.group, name).charm


# ---------- 金币系统 ----------

def test_my_coins_registers_player(env):
    reply = env.send("张三", "我的金币")
    assert "当前金币 200" in reply
    assert "未上榜" in reply  # 未签到不上榜
    p = env.store.get_player(env.group, "张三")
    assert p.coins == 200 and p.is_phantom == 0
    env.send("张三", "签到")
    assert "群内第 1 名" in env.send("张三", "我的金币")


def test_signin_flow(env):
    assert "获得 10 金币（连续签到 1 天）" in env.send("张三", "签到")
    env.send("张三", "签到")  # 3s later, still same day
    assert "今天已经签到过了" in env.send("张三", "签到")
    env.clock.advance(days=1)
    assert "获得 12 金币（连续签到 2 天）" in env.send("张三", "签到")
    env.clock.advance(days=3)
    assert "获得 10 金币（连续签到 1 天）" in env.send("张三", "签到")
    assert coins(env, "张三") == 200 + 10 + 12 + 10


def test_signin_cap(env):
    env.send("张三", "我的金币")
    env.store.set_player_field(env.group, "张三", "signin_streak", 7)
    env.store.set_player_field(env.group, "张三", "last_signin_date", "2026-11-13")
    assert "获得 24 金币（连续签到 8 天）" in env.send("张三", "签到")


def test_transfer(env):
    env.send("李四", "签到")
    reply = env.send("张三", "转账@李四 100")
    assert "转账成功：张三 → 李四 95 金币（手续费 5 金币）" in reply
    assert coins(env, "张三") == 100
    assert coins(env, "李四") == 200 + 10 + 95


def test_transfer_self_and_insufficient(env):
    assert "不能转账给自己" in env.send("张三", "转账@张三 10")
    assert "金币不足" in env.send("张三", "转账@李四 1000")
    assert coins(env, "张三") == 200


def test_transfer_daily_limit(env):
    env.send("张三", "我的金币")
    env.store.adjust_coins(env.group, "张三", 10000, "test", None, env.clock.t.isoformat())
    assert "转账成功" in env.send("张三", "转账@李四 5000")
    assert "今日转账额度不足" in env.send("张三", "转账@李四 100")


def test_coin_rank(env):
    env.send("张三", "签到")
    env.send("李四", "签到")
    reply = env.send("王五", "金币榜")
    assert "金币榜 TOP10" in reply
    assert "1. 张三 210" in reply
    assert "2. 李四 210" in reply
    assert "王五" not in reply  # 未签到不进榜


def test_coin_rank_only_signed_in_players(env):
    env.send("张三", "我的金币")  # 注册但从未签到
    env.store.adjust_coins(env.group, "张三", 500, "test", None, env.clock.t.isoformat())
    env.send("李四", "签到")
    reply = env.send("李四", "金币榜")
    assert "1. 李四 210" in reply
    assert "张三" not in reply
    assert "未上榜" in env.send("张三", "我的金币")
    env.clock.advance(days=30)
    env.send("张三", "签到")  # 隔很久才签到，同样算签到过
    reply = env.send("李四", "金币榜")
    assert "1. 张三 710" in reply
    assert "2. 李四 210" in reply


# ---------- 奴隶系统 ----------

def test_purchase_success(env):
    env.rng.set_sequence([1.0])
    reply = env.send("张三", "购买奴隶@李四")
    assert "购买成功，花费 20 金币" in reply
    assert "1. 李四" in reply
    assert coins(env, "张三") == 180
    assert env.store.get_player(env.group, "李四").master == "张三"


def test_purchase_min_price(env):
    env.rng.set_sequence([0.0])
    reply = env.send("张三", "购买奴隶@李四")
    assert "购买成功，花费 10 金币" in reply


def test_purchase_insufficient(env):
    env.send("张三", "我的金币")
    env.store.adjust_coins(env.group, "张三", -190, "test", None, env.clock.t.isoformat())
    env.rng.set_sequence([5.0])  # price = ceil(10*2*5) = 100 > 10
    reply = env.send("张三", "购买奴隶@李四")
    assert "购买失败：金币不足" in reply
    assert env.store.get_player(env.group, "李四").master is None


def test_purchase_self(env):
    assert "不能购买自己" in env.send("张三", "购买奴隶@张三")


def test_purchase_already_slave(env):
    env.rng.set_sequence([1.0, 1.0])
    env.send("张三", "购买奴隶@李四")
    reply = env.send("张三", "购买奴隶@李四", advance=6)
    assert "已经是你的奴隶" in reply
    reply = env.send("王五", "购买奴隶@李四")
    assert "已经是 张三 的奴隶" in reply


def test_purchase_own_master(env):
    env.rng.set_sequence([1.0, 1.0])
    env.send("张三", "购买奴隶@李四")
    reply = env.send("李四", "购买奴隶@张三")
    assert "不能购买自己的主人" in reply


def test_purchase_max_slaves(env):
    env.rng.set_sequence([0.0] * 10)
    for name in ["甲", "乙", "丙", "丁", "戊"]:
        env.send("张三", f"购买奴隶@{name}")
    reply = env.send("张三", "购买奴隶@己")
    assert "已达上限（5 个）" in reply


def test_release(env):
    env.rng.set_sequence([1.0, 2.0])
    env.send("张三", "购买奴隶@李四")
    reply = env.send("张三", "给他自由@李四")
    assert "恭喜李四恢复自由身" in reply
    assert "张三 获得 40 金币" in reply  # ceil(10*2*2) = 40
    assert env.store.get_player(env.group, "李四").master is None
    assert coins(env, "张三") == 180 + 40
    reply = env.send("张三", "给她自由@李四")
    assert "没有 李四" in reply


def test_work_no_slaves(env):
    assert "你还没有奴隶" in env.send("张三", "奴隶打工")


def test_work_events_and_cooldown(env):
    env.rng.set_sequence([1.0, 1.0])  # purchase r=1 -> price 20
    env.send("张三", "购买奴隶@李四")
    env.rng.set_sequence([3.0])  # weighted point 3/100 -> first positive event +20
    reply = env.send("张三", "奴隶打工")
    assert "为主人赚得 20 金币" in reply
    assert coins(env, "张三") == 180 + 20
    env.clock.advance(minutes=5)
    reply = env.send("张三", "奴隶打工")
    assert "奴隶们还在休息" in reply
    env.clock.advance(minutes=26)
    env.rng.set_sequence([61.0])  # negative zone -> 扶起摔倒老人，被讹 -50
    reply = env.send("张三", "奴隶打工")
    assert "让主人损失 50 金币" in reply
    assert coins(env, "张三") == 200 - 50


def test_work_loss_capped_at_zero(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.store.adjust_coins(env.group, "张三", -180, "test", None, env.clock.t.isoformat())
    env.rng.set_sequence([61.0])
    reply = env.send("张三", "奴隶打工")
    assert "没有收获" in reply
    assert coins(env, "张三") == 0


def test_my_slaves(env):
    env.rng.set_sequence([0.0, 0.0])
    env.send("张三", "购买奴隶@李四")
    env.send("张三", "购买奴隶@王五")
    reply = env.send("张三", "我的奴隶")
    assert "张三的奴隶（2/5）" in reply
    assert "1. 李四" in reply and "2. 王五" in reply
    assert "目前没有奴隶" in env.send("李四", "我的奴隶")


# ---------- 调教 ----------

def _buy(env, master, slave, price_rng=0.0):
    env.rng.set_sequence([price_rng])
    return env.send(master, f"购买奴隶@{slave}")


def test_train_requires_own_slave(env):
    _buy(env, "张三", "李四")
    assert "不是你的奴隶" in env.send("王五", "调教@李四")
    assert "不能调教自己" in env.send("张三", "调教@张三")


def test_train_opposite_tone_adds_but(env):
    _buy(env, "张三", "李四")
    item = env.cfg.interactions[0]
    assert item.tone == "贬"
    # 贬义文案却让魅力上涨：金币 -4 正常，魅力 +5 加“但…却”
    env.rng.set_sequence([item, 8.5, 4, -1, 5, 1])
    reply = env.send("张三", "调教@李四")
    assert reply.splitlines()[0] == "张三 抡起沙包甘大的拳头，上去就给 李四 一拳。"
    assert "李四 的金币-4，但 李四 的魅力却+5" in reply
    assert coins(env, "李四") == 196
    assert charm(env, "李四") == 15


def test_train_neutral_has_no_but(env):
    _buy(env, "张三", "李四")
    item = env.cfg.interactions[4]
    assert item.tone == "中性"
    env.rng.set_sequence([item, 0.5, 3, 1])  # 只变金币 +3
    reply = env.send("张三", "调教@李四")
    assert "李四 的金币+3" in reply
    assert "但" not in reply and "却" not in reply
    assert coins(env, "李四") == 203


def test_train_cooldown_and_daily_limit(env):
    _buy(env, "张三", "李四")
    item = env.cfg.interactions[0]
    env.rng.set_sequence([item, 0.5, 1, -1])
    env.send("张三", "调教@李四")
    assert "调教冷却中" in env.send("张三", "调教@李四", advance=6)
    env.clock.advance(minutes=11)
    today = env.clock.t.date().isoformat()
    env.store.incr_daily(env.group, today, "张三", "interaction", 10, 0)
    env.clock.advance(minutes=11)
    assert "今天的调教次数已用完（10 次）" in env.send("张三", "调教@李四")


def test_train_all(env):
    env.rng.set_sequence([0.0, 0.0])
    env.send("张三", "购买奴隶@李四")
    env.send("张三", "购买奴隶@王五")
    env.store.update_charm(env.group, "王五", 15.0, env.clock.t.isoformat())
    seq = [env.cfg.interactions[0], 0.5, 2, 1,           # 李四：金币 +2
           env.cfg.interactions[1], 8.5, 3, -1, 4, -1]   # 王五：金币 -3、魅力 -4（褒义反向）
    env.rng.set_sequence(seq)
    reply = env.send("张三", "调教所有奴隶")
    lines = reply.splitlines()
    assert lines[0] == "张三 调教奴隶："
    assert lines[1].startswith("1. 张三 抡起沙包")
    assert lines[1].endswith("但 李四 的金币却+2")
    assert lines[2].startswith("2. 张三 揉了揉 王五")
    assert "但 王五 的金币却-3，但 王五 的魅力却-4" in lines[2]
    assert coins(env, "李四") == 202
    assert coins(env, "王五") == 197
    assert charm(env, "王五") == 11


def test_train_all_caps_display(env):
    env.send("张三", "我的金币")
    now = env.clock.t.isoformat()
    for i in range(21):
        name = f"奴{i:02d}"
        env.store.upsert_player(env.group, name, now, 200, 10)
        env.store.set_master(env.group, name, "张三", now)
    seq = []
    for _ in range(21):
        seq += [env.cfg.interactions[2], 0.5, 1, 1]
    env.rng.set_sequence(seq)
    reply = env.send("张三", "调教所有奴隶")
    assert "…（共 21 个）" in reply
    assert "20. " in reply
    assert "21. " not in reply
    # 未展示的第 21 个奴隶也要实际受到调教
    assert coins(env, "奴20") == 201


def test_train_all_no_slaves(env):
    assert "你还没有奴隶" in env.send("张三", "调教所有奴隶")
    assert "不是你的奴隶" in env.send("张三", "调教@李四")


def test_train_floors(env):
    _buy(env, "张三", "李四")
    env.store.adjust_coins(env.group, "李四", -200, "test", None,
                           env.clock.t.isoformat())
    item = env.cfg.interactions[0]
    env.rng.set_sequence([item, 0.5, 5, -1])  # 金币 -5，但余额为 0
    assert "这次没有任何变化" in env.send("张三", "调教@李四")
    assert coins(env, "李四") == 0
    env.clock.advance(minutes=11)
    env.rng.set_sequence([item, 4.0, 5, -1])  # 魅力 -5，直接按变化值结算
    reply = env.send("张三", "调教@李四")
    assert "李四 的魅力-5" in reply
    assert charm(env, "李四") == 5


def test_train_charm_floor_zero(env):
    _buy(env, "张三", "李四")
    env.store.update_charm(env.group, "李四", 3.0, env.clock.t.isoformat())
    item = env.cfg.interactions[0]
    env.rng.set_sequence([item, 4.0, 5, -1])  # 魅力 3，扣 5 → 实际只扣 3
    reply = env.send("张三", "调教@李四")
    assert "李四 的魅力-3" in reply
    assert charm(env, "李四") == 0


def test_train_ignores_charm_base(env):
    from game.config import Config
    from game.engine import Engine

    _buy(env, "张三", "李四")
    data = {k: env.cfg.get(k) for k in env.cfg._data}
    data["charm_base"] = 1000
    engine2 = Engine(Config(data), env.store, env.clock, env.rng, env.engine.ctx.log)
    engine2.attach_sender(env.sender)
    engine2.handle_health({"chat_title": "888 种田大队(32)",
                           "online": True, "listener_running": True})
    env.rng.set_sequence([env.cfg.interactions[1], 4.0, 5, 1])  # 魅力 +5
    engine2.handle_message({"id": "998", "cursor": 998, "sender": "张三",
                            "content": "调教@李四",
                            "received_at": env.clock.t.isoformat()})
    reply = env.sender.last
    assert "李四 的魅力+5" in reply
    assert "990" not in reply
    assert charm(env, "李四") == 15


def test_train_disabled_without_interactions(env):
    from game.config import Config
    from game.engine import Engine

    _buy(env, "张三", "李四")
    data = {k: env.cfg.get(k) for k in env.cfg._data}
    data["slave_interactions"] = []
    engine2 = Engine(Config(data), env.store, env.clock, env.rng, env.engine.ctx.log)
    engine2.attach_sender(env.sender)
    engine2.handle_health({"chat_title": "888 种田大队(32)",
                           "online": True, "listener_running": True})
    engine2.handle_message({"id": "999", "cursor": 999, "sender": "张三",
                            "content": "调教@李四",
                            "received_at": env.clock.t.isoformat()})
    assert "暂无可用的互动内容" in env.sender.last


def test_interaction_config_validation(env):
    import pytest

    from game.config import Config, ConfigError

    data = {k: env.cfg.get(k) for k in env.cfg._data}
    data["slave_interactions"] = [{"text": "x", "tone": "未知"}]
    with pytest.raises(ConfigError):
        Config(data)
    data["slave_interactions"] = []
    Config(data)


def test_store_migrates_last_interact_at(tmp_path):
    import sqlite3

    from game.store import Store

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE players (
        group_key TEXT NOT NULL, name TEXT NOT NULL,
        coins INTEGER NOT NULL DEFAULT 200, charm REAL NOT NULL DEFAULT 10,
        charm_anchor TEXT NOT NULL, master TEXT, enslaved_at TEXT,
        is_phantom INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL, last_signin_date TEXT,
        signin_streak INTEGER NOT NULL DEFAULT 0, last_work_at TEXT,
        last_rebel_at TEXT, total_charm_gained REAL NOT NULL DEFAULT 0,
        total_gift_spent INTEGER NOT NULL DEFAULT 0,
        total_gift_charm REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (group_key, name))""")
    conn.commit()
    conn.close()

    store = Store(path)
    player = store.upsert_player("群", "张三", "2026-11-16T12:00:00+08:00", 200, 10)
    assert player.last_interact_at is None
    assert player.last_ransom_at is None
    store.set_player_field("群", "张三", "last_interact_at",
                           "2026-11-16T12:10:00+08:00")
    store.set_player_field("群", "张三", "last_ransom_at",
                           "2026-11-16T12:20:00+08:00")
    saved = store.get_player("群", "张三")
    assert saved.last_interact_at == "2026-11-16T12:10:00+08:00"
    assert saved.last_ransom_at == "2026-11-16T12:20:00+08:00"
    store.close()


# ---------- 赎身 ----------

def test_ransom_success(env):
    env.rng.set_sequence([0.0])  # 王五 买 李四，价格 10
    env.send("王五", "购买奴隶@李四")
    env.rng.set_sequence([1.5])  # 10 × 1.0 × 1.5 = 15
    reply = env.send("张三", "赎身@李四")
    assert "张三 为 李四 赎身，支付 15 金币。" in reply
    assert "李四 已恢复自由身，王五 获得 15 金币。" in reply
    assert env.store.get_player(env.group, "李四").master is None
    assert coins(env, "张三") == 185
    assert coins(env, "王五") == 205


def test_ransom_free(env):
    env.rng.set_sequence([0.0])
    env.send("王五", "购买奴隶@李四")
    env.rng.set_sequence([0.0])  # 价格为 0
    reply = env.send("张三", "赎身@李四")
    assert "没有花费金币" in reply
    assert "原主人 王五" in reply
    assert coins(env, "张三") == 200
    assert coins(env, "王五") == 190
    assert env.store.get_player(env.group, "李四").master is None


def test_ransom_permissions(env):
    env.rng.set_sequence([0.0])
    env.send("王五", "购买奴隶@李四")
    assert "不能给自己赎身" in env.send("李四", "赎身@李四")
    assert "不能赎自己的奴隶" in env.send("王五", "赎身@李四")
    assert "不是奴隶" in env.send("张三", "赎身@赵六")


def test_ransom_insufficient(env):
    env.rng.set_sequence([0.0])
    env.send("王五", "购买奴隶@李四")
    env.send("张三", "我的金币")
    env.store.adjust_coins(env.group, "张三", -200, "test", None,
                           env.clock.t.isoformat())
    env.rng.set_sequence([3.0])  # 10 × 1.0 × 3 = 30
    reply = env.send("张三", "赎身@李四")
    assert "金币不足（需要 30 金币，当前 0 金币）" in reply
    assert env.store.get_player(env.group, "李四").master == "王五"


def test_ransom_cooldown_and_daily_limit(env):
    env.rng.set_sequence([0.0, 0.0])
    env.send("王五", "购买奴隶@李四")
    env.send("王五", "购买奴隶@赵六")
    env.rng.set_sequence([1.0])
    env.send("张三", "赎身@李四")
    assert "赎身冷却中" in env.send("张三", "赎身@赵六", advance=6)
    env.clock.advance(minutes=11)
    today = env.clock.t.date().isoformat()
    env.store.incr_daily(env.group, today, "张三", "ransom", 10, 0)
    env.clock.advance(minutes=11)
    assert "今天的赎身次数已用完（10 次）" in env.send("张三", "赎身@赵六")


def test_ransom_config_validation(env):
    import pytest

    from game.config import Config, ConfigError

    data = {k: env.cfg.get(k) for k in env.cfg._data}
    data["ransom_price_coeff"] = 1.5
    with pytest.raises(ConfigError):
        Config(data)
    data["ransom_price_coeff"] = 1.0
    Config(data)


def test_rebel_not_slave(env):
    assert "你现在是自由身" in env.send("张三", "我要自由")


def test_rebel_success_tie(env):
    env.rng.set_sequence([1.0])  # 张三 buys 李四, price 20
    env.send("张三", "购买奴隶@李四")
    env.rng.set_sequence([0.5, 0.5, 1])  # master mult 0.5, slave mult 0.5, branch 1
    reply = env.send("李四", "我要自由")
    assert reply == "恭喜李四恢复自由身。"
    assert env.store.get_player(env.group, "李四").master is None


def test_rebel_fail_penalty(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.rng.set_sequence([2.0, 0.5, 2, 30])  # master 2.0, slave 0.5 -> fail; branch 2; penalty 30
    reply = env.send("李四", "我要自由")
    assert "反抗失败，遭到张三镇压，上缴主人30金币" in reply
    assert env.store.get_player(env.group, "李四").master == "张三"
    assert coins(env, "李四") == 200 - 30
    assert coins(env, "张三") == 180 + 30


def test_rebel_success_loot(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.rng.set_sequence([0.5, 0.5, 2, 50])  # tie success; branch 2; loot 50
    reply = env.send("李四", "我要自由")
    assert "并拿走张三的50金币" in reply
    assert coins(env, "张三") == 180 - 50
    assert coins(env, "李四") == 200 + 50


def test_rebel_cooldown(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.rng.set_sequence([2.0, 0.5, 1])  # fail, plain failure
    env.send("李四", "我要自由")
    assert "反抗失败" in env.sender.sent[-1]
    env.clock.advance(minutes=10)
    reply = env.send("李四", "我要自由")
    assert "你刚反抗过" in reply


# ---------- 礼物 / 魅力 ----------

def test_gift_flow(env):
    reply = env.send("张三", "送礼@李四 玫瑰 2")
    assert "张三 送给 李四 ×2 玫瑰，花费 20 金币" in reply
    assert "李四 魅力 +2.0，当前魅力 12.0" in reply
    assert coins(env, "张三") == 180
    assert charm(env, "李四") == 12.0


def test_gift_failures(env):
    assert "不能送给自己" in env.send("张三", "送礼@张三 玫瑰")
    # 空格被吞后未知礼物名无法切分，统一回复用法提示
    assert "指令格式不对" in env.send("张三", "送礼@李四 钻石")
    assert "数量必须在 1~99" in env.send("张三", "送礼@李四 玫瑰 100")
    assert "数量必须在 1~99" in env.send("张三", "送礼@李四 玫瑰 100")
    env.store.adjust_coins(env.group, "张三", -195, "test", None, env.clock.t.isoformat())
    assert "金币不足" in env.send("张三", "送礼@李四 玫瑰")
    assert charm(env, "李四") == 10


def test_gift_daily_limit(env):
    env.send("张三", "我的金币")
    env.store.adjust_coins(env.group, "张三", 30000, "test", None, env.clock.t.isoformat())
    assert "送礼失败：今日送礼额度不足" in env.send("张三", "送礼@李四 城堡 4")  # 4*5200=20800
    assert charm(env, "李四") == 10


def test_gift_creates_phantom(env):
    env.send("张三", "送礼@路人甲 玫瑰")
    p = env.store.get_player(env.group, "路人甲")
    assert p.is_phantom == 1 and p.charm == 11.0
    reply = env.send("王五", "魅力榜")
    assert "路人甲" not in reply


def test_my_charm_and_rank(env):
    env.send("张三", "送礼@李四 玫瑰 3")
    env.send("李四", "签到")
    reply = env.send("李四", "我的魅力")
    assert "当前魅力值 13.0" in reply
    assert "累计收到礼物魅力 +3.0" in reply
    assert "群内第 1 名" in reply


def test_charm_rank_only_signed_in_players(env):
    env.send("张三", "送礼@李四 玫瑰 3")
    reply = env.send("王五", "魅力榜")
    assert "魅力榜暂无数据" in reply
    env.send("李四", "签到")
    reply = env.send("王五", "魅力榜")
    assert "1. 李四 13.0" in reply
    assert "张三" not in reply


def test_charm_decay(env):
    from datetime import timedelta
    from game.util import fmt_iso
    env.send("张三", "送礼@李四 城堡")  # 李四 charm = 10 + 520 = 530
    env.store.update_charm(env.group, "李四", 110, fmt_iso(env.clock.t - timedelta(days=8)))
    reply = env.send("李四", "我的魅力")  # decay: 10 + 100*0.9 = 100
    assert "当前魅力值 100.0" in reply
    assert charm(env, "李四") == 100.0


def test_gift_rank(env):
    env.send("张三", "送礼@李四 玫瑰 2")
    reply = env.send("王五", "礼物榜")
    assert "送礼榜 TOP5" in reply
    assert "1. 张三 20 金币" in reply
    assert "1. 李四 2.0 魅力" in reply


def test_gift_list(env):
    reply = env.send("张三", "礼物列表")
    assert "玫瑰 10 金币 +1.0 魅力" in reply
    assert "城堡 5200 金币 +520.0 魅力" in reply


# ---------- 引擎行为 ----------

def test_ignored_senders(env):
    env.send("我", "签到", advance=0)
    env.send("对方", "签到", advance=0)
    assert env.store.get_player(env.group, "我") is None
    assert env.store.get_player(env.group, "对方") is None
    assert env.sender.sent == []


def test_unrelated_message_silent_but_registers(env):
    env.send("张三", "今天天气不错")
    assert env.sender.sent == []
    assert env.store.get_player(env.group, "张三") is not None


def test_dup_message_id(env):
    msg = {"id": "999", "cursor": 999, "sender": "张三",
           "content": "签到", "received_at": env.clock.t.isoformat()}
    env.engine.handle_message(msg)
    env.engine.handle_message(msg)
    assert len([t for t in env.sender.sent if "签到成功" in t]) == 1


def test_dup_content_window(env):
    env.send("张三", "签到", advance=0)
    env.send("张三", "签到", advance=0)
    assert len(env.sender.sent) == 1  # second dropped by content dedupe
    env.clock.advance(seconds=6)
    r3 = env.send("张三", "签到", advance=0)
    assert "今天已经签到过了" in r3


def test_rate_limit(env):
    env.send("张三", "我的金币", advance=0)
    env.send("张三", "我的金币", advance=0)
    assert len(env.sender.sent) == 1
    env.clock.advance(seconds=3)
    env.send("张三", "我的金币")
    assert len(env.sender.sent) == 2


def test_usage_hint_once(env):
    env.send("张三", "购买奴隶 张三", advance=0)
    env.send("张三", "转账@李四", advance=0)
    assert len(env.sender.sent) == 1
    env.clock.advance(seconds=61)
    r3 = env.send("张三", "购买奴隶 张三")
    assert len(env.sender.sent) == 2
    assert "指令格式不对" in r3


def test_help_cooldown(env):
    env.send("张三", "奴隶系统", advance=0)
    env.send("张三", "奴隶系统", advance=0)
    assert len(env.sender.sent) == 1


def test_multi_group_isolation(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.engine.handle_health({"chat_title": "另一个群(10)",
                              "online": True, "listener_running": True})
    env.clock.advance(seconds=30)
    env.engine.handle_health({"chat_title": "另一个群(10)",
                              "online": True, "listener_running": True})
    reply = env.send("张三", "我的金币")
    assert "当前金币 200" in reply
    assert env.store.get_player("另一个群", "张三").coins == 200
    assert env.store.get_player("另一个群", "李四") is None


def test_allowed_groups_pause(env):
    from game.config import Config
    from game.engine import Engine
    data = {k: env.cfg.get(k) for k in env.cfg._data}
    data["allowed_groups"] = ["别的群"]
    cfg2 = Config(data)
    engine2 = Engine(cfg2, env.store, env.clock, env.rng, env.engine.ctx.log)
    engine2.attach_sender(env.sender)
    engine2.handle_health({"chat_title": "888 种田大队(32)",
                           "online": True, "listener_running": True})
    engine2.handle_message({"id": "500", "cursor": 500, "sender": "张三",
                            "content": "签到", "received_at": env.clock.t.isoformat()})
    assert env.sender.sent == []


def test_charm_used_in_price(env):
    env.send("张三", "我的金币")
    env.store.adjust_coins(env.group, "张三", 6000, "test", None, env.clock.t.isoformat())
    env.send("张三", "送礼@李四 城堡")  # 李四 charm 530
    env.send("王五", "我的金币")
    env.store.adjust_coins(env.group, "王五", 5000, "test", None, env.clock.t.isoformat())
    env.rng.set_sequence([1.0])
    reply = env.send("王五", "购买奴隶@李四")
    assert "购买成功，花费 1060 金币" in reply  # ceil(530*2*1)


# ---------- OCR 空格吞字兼容 ----------

def test_purchase_glued_chatter_prefix(env):
    env.rng.set_sequence([1.0])
    env.send("张三", "购买奴隶@李四")
    env.rng.set_sequence([1.0])
    reply = env.send("王五", "购买奴隶@李四谢谢")  # 粘连闲聊 → 前缀命中李四
    assert "购买失败：李四 已经是 张三 的奴隶" in reply


def test_release_glued_chatter_prefix(env):
    env.rng.set_sequence([1.0, 2.0])
    env.send("张三", "购买奴隶@李四")
    reply = env.send("张三", "给他自由@李四哈哈")
    assert "恭喜李四恢复自由身" in reply


def test_gift_no_spaces(env):
    reply = env.send("张三", "送礼@李四玫瑰2")
    assert "张三 送给 李四 ×2 玫瑰，花费 20 金币" in reply
    assert charm(env, "李四") == 12.0


def test_gift_glued_chatter_prefix(env):
    env.send("李四", "签到")
    reply = env.send("张三", "送礼@李四谢谢玫瑰")
    assert "张三 送给 李四 ×1 玫瑰，花费 10 金币" in reply


def test_transfer_no_spaces(env):
    env.send("李四", "签到")
    reply = env.send("张三", "转账@李四100")
    assert "转账成功：张三 → 李四 95 金币（手续费 5 金币）" in reply


def test_transfer_missing_amount_hint(env):
    reply = env.send("张三", "转账@李四")
    assert "指令格式不对" in reply


def test_gift_unknown_glued(env):
    reply = env.send("张三", "送礼@李四钻石")
    assert "指令格式不对" in reply


def test_exact_command_with_random_spaces(env):
    reply = env.send("张三", "签  到")
    assert "签到成功" in reply


# ---------- 自动回复规则 ----------

def test_pat_rule_replies(env):
    reply = env.send("我", "“是你的益达”拍了拍“童声微蔓”")
    assert reply == "是你的益达 拍了拍我，我醒啦～"
    # 系统行的 sender 是"我"，不能因此注册成玩家
    assert env.store.get_player(env.group, "我") is None


def test_pat_rule_alias_and_what(env):
    reply = env.send("我", "“是你的益达”拍了拍“童声徽蔓”叫了一声“嗯~”")
    assert reply == "是你的益达 拍了拍我，我醒啦～"


def test_pat_rule_quote_variants(env):
    cases = [
        ('"张三"拍了拍"童声微蔓"', "张三"),
        ("'李四'拍了拍'童声微蔓'", "李四"),
        ("‘王五’拍了拍‘童声微蔓’", "王五"),
    ]
    for text, name in cases:
        assert env.send("我", text) == f"{name} 拍了拍我，我醒啦～"


def test_pat_rule_other_member_silent(env):
    env.send("我", "“是你的益达”拍了拍“老婆”")
    assert env.sender.sent == []


def test_pat_rule_cooldown(env):
    env.send("我", "“A”拍了拍“童声微蔓”")
    assert len(env.sender.sent) == 1
    env.clock.advance(seconds=3)  # 距上次 6 秒，仍在 10 秒冷却内
    env.send("我", "“A”拍了拍“童声微蔓”叫了一声“嗯~”", advance=0)
    assert len(env.sender.sent) == 1
    env.clock.advance(seconds=10)
    env.send("我", "“A”拍了拍“童声微蔓”叫了一声“嘿嘿”", advance=0)
    assert len(env.sender.sent) == 2


def test_rule_sender_variable(env_factory):
    e = env_factory(auto_replies=[{
        "name": "点名", "pattern": r"^你好$", "replies": "{sender} 你好呀"}])
    assert e.send("张三", "你好") == "张三 你好呀"


def test_rule_missing_group_is_empty(env_factory):
    e = env_factory(auto_replies=[{
        "name": "括号", "pattern": r"^头(.*)尾(.*)$",
        "replies": "[{msg1}][{msg2}]"}])
    assert e.send("张三", "头尾") == "[][]"


def test_rule_matches_ignoring_spaces(env_factory):
    e = env_factory(auto_replies=[{
        "name": "空格", "pattern": r"^你好啊$", "replies": "嗨"}])
    assert e.send("张三", "你 好 啊") == "嗨"


def test_rule_first_match_wins(env_factory):
    e = env_factory(auto_replies=[
        {"name": "一", "pattern": r"^测试$", "replies": "第一条"},
        {"name": "二", "pattern": r"^测试$", "replies": "第二条"},
    ])
    assert e.send("张三", "测试") == "第一条"


def test_rule_runs_before_commands(env_factory):
    e = env_factory(auto_replies=[{
        "name": "拦截", "pattern": r"^签到$", "replies": "今天不签"}])
    assert e.send("张三", "签到") == "今天不签"
    assert e.store.get_player(e.group, "张三") is None


def test_rule_ignored_sender_blocked(env_factory):
    e = env_factory(auto_replies=[{
        "name": "全匹配", "pattern": r"^任意$", "replies": "收到"}])
    e.send("我", "任意")
    assert e.sender.sent == []


def test_rule_allow_ignored_sender(env_factory):
    e = env_factory(auto_replies=[{
        "name": "系统行", "pattern": r"^任意$", "replies": "收到",
        "allow_ignored_senders": True}])
    assert e.send("我", "任意") == "收到"


def test_rule_disabled(env_factory):
    e = env_factory(auto_replies=[{
        "name": "关闭", "pattern": r"^测试$", "replies": "不该出现",
        "enabled": False}])
    e.send("张三", "测试")
    assert e.sender.sent == []


def test_rule_bot_variable(env_factory):
    e = env_factory(bot_name="小助手", auto_replies=[{
        "name": "问名字", "pattern": r"^你是谁$", "replies": "我是{bot}"}])
    assert e.send("张三", "你是谁") == "我是小助手"


# ---------- @ 前缀形式 ----------

def test_mention_query(env):
    env.send("李四", "我的金币")
    reply = env.send("张三", "@李四我的金币")
    assert "李四 当前金币" in reply


def test_mention_action_rejected(env):
    env.send("李四", "我的金币")
    reply = env.send("张三", "@李四签到")
    assert "「签到」不支持@别人代执行" in reply


def test_mention_purchase_fallback(env):
    env.rng.set_sequence([1.0])
    reply = env.send("张三", "@李四购买奴隶")  # 李四未注册 → 关键字切分兜底
    assert "购买成功，花费 20 金币" in reply
    assert env.store.get_player(env.group, "李四").master == "张三"


def test_mention_gift(env):
    reply = env.send("张三", "@李四送礼玫瑰")
    assert "送给 李四 ×1 玫瑰，花费 10 金币" in reply
