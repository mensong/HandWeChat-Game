"""端到端处理器测试（内存库 + 固定随机源）。"""
from game.replies import pat_reply
from game.rng import Rng


def coins(env, name):
    return env.store.get_player(env.group, name).coins


def charm(env, name):
    return env.store.get_player(env.group, name).charm


# ---------- 金币系统 ----------

def test_my_coins_registers_player(env):
    reply = env.send("张三", "我的金币")
    assert "当前金币 200" in reply
    assert "第 1 名" in reply
    p = env.store.get_player(env.group, "张三")
    assert p.coins == 200 and p.is_phantom == 0


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
    assert "3. 王五 200" in reply


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
    env.rng.set_sequence([3.0])  # weighted point 3/100 -> first positive event +2
    reply = env.send("张三", "奴隶打工")
    assert "为主人赚得 2 金币" in reply
    assert coins(env, "张三") == 180 + 2
    env.clock.advance(minutes=5)
    reply = env.send("张三", "奴隶打工")
    assert "奴隶们还在休息" in reply
    env.clock.advance(minutes=26)
    env.rng.set_sequence([61.0])  # negative zone -> 扶起摔倒老人，被讹 -5
    reply = env.send("张三", "奴隶打工")
    assert "让主人损失 5 金币" in reply
    assert coins(env, "张三") == 182 - 5


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
    reply = env.send("李四", "我的魅力")
    assert "当前魅力值 13.0" in reply
    assert "累计收到礼物魅力 +3.0" in reply
    assert "群内第 1 名" in reply


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


# ---------- 拍一拍 ----------

def test_pat_bot_replies(env):
    template = env.cfg.get("pat_reply_texts")[0]
    env.rng.set_sequence([template])
    reply = env.send("我", "“是你的益达”拍了拍“童声微蔓”")
    assert reply == pat_reply(template, "是你的益达", "童声微蔓", "")
    # 系统行的 sender 是"我"，不能因此注册成玩家
    assert env.store.get_player(env.group, "我") is None


def test_pat_bot_alias_and_what(env):
    template = env.cfg.get("pat_reply_texts")[0]
    env.rng.set_sequence([template])
    reply = env.send("我", "“是你的益达”拍了拍“童声徽蔓”叫了一声“嗯~”")
    assert reply == pat_reply(template, "是你的益达", "童声徽蔓", "叫了一声“嗯~”")


def test_pat_other_member_silent(env):
    env.send("我", "“是你的益达”拍了拍“老婆”")
    assert env.sender.sent == []


def test_pat_reply_cooldown(env):
    texts = env.cfg.get("pat_reply_texts")
    env.rng.set_sequence([texts[0], texts[0]])
    env.send("我", "“A”拍了拍“童声微蔓”")
    assert len(env.sender.sent) == 1
    env.clock.advance(seconds=3)  # 距上次 6 秒，仍在 10 秒冷却内
    env.send("我", "“A”拍了拍“童声微蔓”叫了一声“嗯~”", advance=0)
    assert len(env.sender.sent) == 1
    env.clock.advance(seconds=10)
    env.send("我", "“A”拍了拍“童声微蔓”叫了一声“嘿嘿”", advance=0)
    assert len(env.sender.sent) == 2


def test_pat_disabled_without_texts(env):
    from game.config import Config
    from game.engine import Engine
    data = {k: env.cfg.get(k) for k in env.cfg._data}
    data["pat_reply_texts"] = []
    engine2 = Engine(Config(data), env.store, env.clock, env.rng, env.engine.ctx.log)
    engine2.attach_sender(env.sender)
    engine2.handle_health({"chat_title": "888 种田大队(32)",
                           "online": True, "listener_running": True})
    engine2.handle_message({"id": "600", "cursor": 600, "sender": "我",
                            "content": "“A”拍了拍“童声微蔓”",
                            "received_at": env.clock.t.isoformat()})
    assert env.sender.sent == []
