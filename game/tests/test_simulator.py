"""模拟器测试。"""
from game.config import Config
from game.simulator import RELAXED, Simulator


def make_sim(tmp_path, cfg) -> Simulator:
    data = cfg.as_dict()
    data.update(RELAXED)
    return Simulator(Config(data), str(tmp_path / "sim.db"))


def test_send_and_reply(tmp_path, cfg):
    sim = make_sim(tmp_path, cfg)
    replies = sim.send("张三", "签到")
    assert len(replies) == 1
    assert "签到成功" in replies[0]
    # 放开限流后连续发送同内容，应得到"已签到"而不是被去重丢弃
    replies = sim.send("张三", "签到")
    assert "今天已经签到过了" in replies[0]
    sim.advance(86400)
    replies = sim.send("张三", "签到")
    assert "连续签到 2 天" in replies[0]


def test_state_and_debug_coins(tmp_path, cfg):
    sim = make_sim(tmp_path, cfg)
    sim.send("张三", "我的金币")
    sim.debug_coins("张三", 5000)
    state = sim.state()
    players = {p["name"]: p for p in state["players"]}
    assert players["张三"]["coins"] == 5200
    assert state["group_key"] == "模拟群"
    assert state["log"][-1]["sender"] == "张三"


def test_reset(tmp_path, cfg):
    sim = make_sim(tmp_path, cfg)
    sim.send("张三", "签到")
    sim.reset()
    assert sim.store.get_player("模拟群", "张三") is None
    assert sim.state()["log"] == []


def test_persistence_across_restart(tmp_path, cfg):
    db = str(tmp_path / "persist.db")
    data = cfg.as_dict()
    data.update(RELAXED)
    sim = Simulator(Config(data), db, cfg_path="unused")
    sim.send("张三", "签到")
    # 模拟重启：用同一个数据库文件新建实例
    sim.store.close()
    sim2 = Simulator(Config(data), db, cfg_path="unused")
    p = sim2.store.get_player("模拟群", "张三")
    assert p is not None
    assert p.last_signin_date == sim2.clock().date().isoformat()
    replies = sim2.send("张三", "签到")
    assert "今天已经签到过了" in replies[0]
    # 重置仍应清空
    sim2.reset()
    assert sim2.store.get_player("模拟群", "张三") is None
    sim2.store.close()
