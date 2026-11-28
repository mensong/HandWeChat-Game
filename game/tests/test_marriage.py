"""结婚系统测试：求婚 / 同意 / 拒绝 / 抢婚 / 逼婚 / 超时结算。"""
from game.util import fmt_iso


def _coins(env, name):
    return env.store.get_player(env.group, name).coins


def _spouse(env, name):
    return env.store.get_player(env.group, name).spouse


def test_propose_and_accept(env):
    env.rng.set_sequence([1.0, 0.5])  # 彩礼系数 1.0，未触发直接成婚
    reply = env.send("张三", "求婚@李四")
    assert "彩礼 5 金币已由系统托管" in reply
    assert _coins(env, "张三") == 195
    assert _coins(env, "李四") == 200
    assert env.store.get_proposal(env.group, "李四").proposer == "张三"

    reply = env.send("李四", "同意")
    assert "喜结连理" in reply and "[玫瑰]" in reply
    assert _spouse(env, "张三") == "李四"
    assert _spouse(env, "李四") == "张三"
    assert _coins(env, "李四") == 205
    assert env.store.get_proposal(env.group, "李四") is None


def test_propose_mention_form(env):
    env.rng.set_sequence([1.0, 0.5])
    reply = env.send("张三", "@李四求婚")
    assert "向 李四 求婚" in reply


def test_propose_auto_marry(env):
    env.rng.set_sequence([1.0, 0.01])
    reply = env.send("张三", "求婚@李四")
    assert "喜结连理" in reply
    assert _spouse(env, "张三") == "李四"
    assert _coins(env, "李四") == 205
    assert env.store.get_proposal(env.group, "李四") is None


def test_propose_insufficient_coins(env):
    env.send("张三", "我的金币")
    env.store.adjust_coins(env.group, "张三", -198, "admin", None, fmt_iso(env.clock.t))
    env.rng.set_sequence([1.0])
    reply = env.send("张三", "求婚@李四")
    assert "彩礼需要 5 金币" in reply
    assert _coins(env, "张三") == 2


def test_reject_refunds(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    reply = env.send("李四", "拒绝")
    assert "彩礼 5 金币已退回" in reply
    assert _coins(env, "张三") == 200
    assert _spouse(env, "张三") is None
    assert env.store.get_proposal(env.group, "李四") is None


def test_one_proposal_per_target_and_proposer(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    assert "你已有待处理的求婚" in env.send("张三", "求婚@王五")
    assert "已经有一个待处理的求婚" in env.send("赵六", "求婚@李四")


def test_steal_success(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("王五", "我的金币")
    env.store.admin_set_charm(env.group, "王五", 100)
    env.rng.set_sequence([1.0, 0.1, 0.5])  # 彩礼 / 抢婚掷骰(30%) / 直婚掷骰
    reply = env.send("王五", "抢婚")
    assert "抢婚成功" in reply
    assert _coins(env, "张三") == 200  # 原求婚者全额退回
    assert _coins(env, "王五") == 195
    assert env.store.get_proposal(env.group, "李四").proposer == "王五"

    env.send("李四", "同意")
    assert _spouse(env, "王五") == "李四"
    assert _coins(env, "李四") == 205


def test_steal_fail_keeps_proposal(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("王五", "我的金币")
    env.store.admin_set_charm(env.group, "王五", 100)
    env.rng.set_sequence([1.0, 0.9])  # 高于 30%
    reply = env.send("王五", "抢婚")
    assert "抢婚失败" in reply
    assert _coins(env, "王五") == 200
    assert env.store.get_proposal(env.group, "李四").proposer == "张三"


def test_steal_by_self_or_proposer(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    assert "这就是你自己的求婚" in env.send("张三", "抢婚")
    assert "不能抢自己的求婚" in env.send("李四", "抢婚")


def test_steal_after_reject_fails(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("李四", "拒绝")
    env.send("王五", "我的金币")
    assert "当前没有进行中的求婚" in env.send("王五", "抢婚")


def test_force_by_proposer_uses_escrow(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.rng.set_sequence([0.1])  # 魅力相同 → 30%，0.1 命中
    reply = env.send("张三", "逼婚")
    assert "逼婚成功" in reply
    assert _coins(env, "张三") == 195  # 只扣了一次彩礼
    assert _coins(env, "李四") == 205
    assert _spouse(env, "张三") == "李四"


def test_force_pending_by_third_party(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("王五", "我的金币")
    env.rng.set_sequence([1.0, 0.1])  # 新彩礼 / 逼婚掷骰(30%)
    reply = env.send("王五", "逼婚")
    assert "逼婚成功" in reply
    assert _coins(env, "张三") == 200
    assert _coins(env, "王五") == 195
    assert _spouse(env, "王五") == "李四"


def test_force_after_reject_pays_again(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("李四", "拒绝")
    assert _coins(env, "张三") == 200  # 已退款
    env.send("王五", "我的金币")
    env.rng.set_sequence([1.0, 0.1])
    reply = env.send("王五", "逼婚")
    assert "逼婚成功" in reply
    assert _coins(env, "王五") == 195
    assert _coins(env, "李四") == 205


def test_force_window_expired(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("李四", "拒绝")
    env.send("王五", "我的金币")
    env.clock.advance(seconds=61)
    reply = env.send("王五", "逼婚", advance=0)
    assert "当前没有可逼婚的求婚" in reply


def test_force_fail_message(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.rng.set_sequence([0.9])  # 高于 30%
    reply = env.send("张三", "逼婚")
    assert "逼婚失败" in reply
    assert _spouse(env, "张三") is None
    assert env.store.get_proposal(env.group, "李四") is not None


def test_proposal_ttl_refund(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    assert _coins(env, "张三") == 195
    env.clock.advance(seconds=601)
    env.send("王五", "我的金币", advance=0)
    assert env.store.get_proposal(env.group, "李四") is None
    assert _coins(env, "张三") == 200


def test_married_cannot_propose(env):
    env.rng.set_sequence([1.0, 0.5])
    env.send("张三", "求婚@李四")
    env.send("李四", "同意")
    assert "你已经有配偶了" in env.send("张三", "求婚@王五")
    assert "张三 已经有配偶了" in env.send("王五", "求婚@张三")


def test_help_and_no_proposal(env):
    assert "结婚系统指令" in env.send("张三", "结婚系统")
    assert "没有人向你求婚" in env.send("张三", "同意")
