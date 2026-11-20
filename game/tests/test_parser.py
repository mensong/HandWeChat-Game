"""解析器与规范化测试（含 OCR 空格容错）。"""
from game.parser import parse, usage_hint
from game.util import normalize_text


def n(text):
    return normalize_text(text, allow_hash=True)


def p(cfg, text):
    return parse(n(text), cfg)


def test_exact_commands(cfg):
    for text, name in [
        ("我的金币", "my_coins"),
        ("签到", "sign_in"),
        ("金币榜", "coin_rank"),
        ("金币系统", "coins_help"),
        ("我的魅力", "my_charm"),
        ("魅力值", "my_charm"),
        ("魅力榜", "charm_rank"),
        ("魅力系统", "charm_help"),
        ("礼物列表", "gift_list"),
        ("礼物榜", "gift_rank"),
        ("礼物系统", "gifts_help"),
        ("奴隶打工", "slave_work"),
        ("我的奴隶", "my_slaves"),
        ("我要自由", "rebel"),
        ("调教所有奴隶", "train_all_slaves"),
        ("奴隶系统", "slaves_help"),
        # OCR 插入空格也能命中
        ("签 到", "sign_in"),
        ("奴 隶 打 工", "slave_work"),
        ("  金币榜  ", "coin_rank"),
    ]:
        assert p(cfg, text).name == name, text


def test_hash_prefix_and_punct(cfg):
    assert p(cfg, "#签到").name == "sign_in"
    assert p(cfg, "签到！").name == "sign_in"
    assert p(cfg, "#奴隶系统。").name == "slaves_help"
    assert p(cfg, "# 奴 隶 系 统 ！").name == "slaves_help"


def test_purchase_target_variants(cfg):
    assert p(cfg, "购买奴隶@张三").target == "张三"
    assert p(cfg, "购买奴隶 ＠ 张三").target == "张三"
    assert p(cfg, "购买奴隶@张三。").target == "张三"
    # 空格被 OCR 吞掉/闲聊粘连时，目标为 @ 后整段，
    # 由数据层做精确/前缀解析（见 test_game 的粘连用例）
    assert p(cfg, "购买奴隶@张三 谢谢").target == "张三谢谢"
    assert p(cfg, "购买奴隶@张 三").target == "张三"


def test_release_variants(cfg):
    assert p(cfg, "给他自由@李四").name == "release_slave"
    assert p(cfg, "给她自由@李四。").name == "release_slave"
    assert p(cfg, "给她自由@李四").target == "李四"


def test_train_variants(cfg):
    cmd = p(cfg, "调教@李四")
    assert (cmd.name, cmd.target) == ("train_slave", "李四")
    cmd = p(cfg, "调教 ＠ 李 四。")
    assert cmd.target == "李四"
    cmd = p(cfg, "调教所有奴隶")
    assert (cmd.name, cmd.target) == ("train_all_slaves", None)
    assert p(cfg, "调教所有奴 隶").name == "train_all_slaves"


def test_ransom_variants(cfg):
    cmd = p(cfg, "赎身@李四")
    assert (cmd.name, cmd.target) == ("ransom_slave", "李四")
    cmd = p(cfg, "赎身 ＠ 李 四。")
    assert cmd.target == "李四"


def test_transfer_parse(cfg):
    cmd = p(cfg, "转账@张三 100")
    assert (cmd.name, cmd.target, cmd.amount) == ("transfer", "张三", 100)
    cmd = p(cfg, "转账＠张三　１００")
    assert cmd.amount == 100
    # 空格被吞：末尾数字为金额
    cmd = p(cfg, "转账@张三100")
    assert (cmd.target, cmd.amount) == ("张三", 100)


def test_transfer_without_amount_is_hint(cfg):
    assert p(cfg, "转账@张三") is None
    assert usage_hint(n("转账@张三")) is not None


def test_gift_parse(cfg):
    cmd = p(cfg, "送礼@张三 玫瑰")
    assert (cmd.name, cmd.target, cmd.gift, cmd.count) == ("send_gift", "张三", "玫瑰", None)
    cmd = p(cfg, "送礼@张三 玫瑰 2 谢谢")
    assert (cmd.gift, cmd.count) == ("玫瑰", 2)
    cmd = p(cfg, "送礼@张三 rose 3")
    assert (cmd.gift, cmd.count) == ("玫瑰", 3)  # 英文别名归一为规范名


def test_gift_parse_no_spaces(cfg):
    cmd = p(cfg, "送礼@是你的益达玫瑰")
    assert (cmd.target, cmd.gift, cmd.count) == ("是你的益达", "玫瑰", None)
    cmd = p(cfg, "送礼@是你的益达玫瑰2")
    assert (cmd.target, cmd.gift, cmd.count) == ("是你的益达", "玫瑰", 2)
    # 最右侧礼物名优先：昵称包含礼物名也能切对
    cmd = p(cfg, "送礼@玫瑰哥送玫瑰3")
    assert (cmd.target, cmd.gift, cmd.count) == ("玫瑰哥送", "玫瑰", 3)
    # 长别名优先切分（返回规范名）
    cmd = p(cfg, "送礼@张三玫瑰花2")
    assert (cmd.target, cmd.gift, cmd.count) == ("张三", "玫瑰", 2)
    # 数量后有闲聊：闲聊忽略
    cmd = p(cfg, "送礼@张三玫瑰2哈哈")
    assert (cmd.target, cmd.gift, cmd.count) == ("张三", "玫瑰", 2)


def test_gift_unknown_name(cfg):
    # 空格被吞后无法区分"缺礼物名"与"未知礼物名"，统一走用法提示
    assert p(cfg, "送礼@张三 钻石") is None
    assert usage_hint(n("送礼@张三 钻石")) is not None


def test_gift_target_only_is_hint(cfg):
    # 只有目标没有礼物名 → 用法提示
    assert p(cfg, "送礼@张三") is None
    assert usage_hint(n("送礼@张三")) is not None


def test_non_command_silent(cfg):
    assert p(cfg, "我想购买奴隶@张三") is None
    assert usage_hint(n("我想购买奴隶@张三")) is None
    assert p(cfg, "奴隶打工 谢谢") is None
    assert usage_hint(n("奴隶打工 谢谢")) is None
    assert p(cfg, "今天天气不错") is None
    assert usage_hint(n("今天天气不错")) is None
    # 无空格粘连的闲聊，无法与指令区分，静默忽略
    assert p(cfg, "奴隶打工好累") is None
    assert usage_hint(n("奴隶打工好累")) is None


def test_usage_hints():
    assert usage_hint(n("购买奴隶 张三")) is not None
    assert usage_hint(n("购买奴隶")) is not None
    assert usage_hint(n("购买奴隶@")) is not None
    assert usage_hint(n("转账@张三")) is not None
    assert usage_hint(n("送礼@张三")) is not None
    assert usage_hint(n("给他自由 李四")) is not None
    assert usage_hint(n("调教")) is not None
    assert usage_hint(n("调教 李四")) is not None
    assert usage_hint(n("赎身")) is not None
    assert usage_hint(n("赎身 李四")) is not None


def test_invalid_target_rejected(cfg):
    assert p(cfg, "购买奴隶@#") is None
    assert p(cfg, "购买奴隶@") is None
    assert p(cfg, "购买奴隶@" + "超" * 45) is None


def test_fullwidth_digits(cfg):
    assert p(cfg, "转账＠张三　１００").amount == 100
    assert p(cfg, "签到\n").name == "sign_in"


def _matcher(names):
    def match(text):
        low = text.lower()
        cands = [n for n in names if n and low.startswith(n.lower())]
        return max(cands, key=len) if cands else None
    return match


def test_mention_query(cfg):
    m = _matcher(["李四"])
    cmd = parse(n("@李四我的金币"), cfg, m)
    assert (cmd.name, cmd.mention) == ("my_coins", "李四")
    cmd = parse(n("@李四我的奴隶"), cfg, m)
    assert (cmd.name, cmd.mention) == ("my_slaves", "李四")


def test_mention_target_commands(cfg):
    m = _matcher(["李四"])
    cmd = parse(n("@李四购买奴隶"), cfg, m)
    assert (cmd.name, cmd.target, cmd.mention) == ("purchase_slave", "李四", "李四")
    cmd = parse(n("@李四给他自由"), cfg, m)
    assert (cmd.name, cmd.target) == ("release_slave", "李四")
    cmd = parse(n("@李四赎身"), cfg, m)
    assert (cmd.name, cmd.target) == ("ransom_slave", "李四")
    cmd = parse(n("@李四送礼玫瑰2"), cfg, m)
    assert (cmd.target, cmd.gift, cmd.count) == ("李四", "玫瑰", 2)
    cmd = parse(n("@李四转账100"), cfg, m)
    assert (cmd.target, cmd.amount) == ("李四", 100)


def test_mention_longest_name_wins(cfg):
    m = _matcher(["张三", "张三丰"])
    cmd = parse(n("@张三丰签到"), cfg, m)
    assert cmd.mention == "张三丰"


def test_mention_unregistered_fallback(cfg):
    m = _matcher(["李四"])
    cmd = parse(n("@新张三购买奴隶"), cfg, m)
    assert (cmd.name, cmd.target) == ("purchase_slave", "新张三")
    # 未注册目标 + 不含指令关键字 → 静默忽略
    assert parse(n("@路人甲你好"), cfg, m) is None


def test_mention_own_target_wins(cfg):
    m = _matcher(["李四"])
    cmd = parse(n("@李四购买奴隶@王五"), cfg, m)
    assert cmd.target == "王五"


def test_mention_alone_ignored(cfg):
    m = _matcher(["李四"])
    assert parse(n("@李四"), cfg, m) is None
    assert parse(n("@李四你好"), cfg, m) is None


def test_command_aliases(cfg):
    from game.config import Config
    data = {**cfg.as_dict(), "command_aliases": {"购买奴隶": ["购买", "买下"],
                                                 "签到": ["打卡"]}}
    cfg2 = Config(data)
    # 别名 + @ 参数
    cmd = parse(n("购买@李四"), cfg2)
    assert (cmd.name, cmd.target) == ("purchase_slave", "李四")
    cmd = parse(n("买下@李四"), cfg2)
    assert cmd.target == "李四"
    # 整句别名
    assert parse(n("打卡"), cfg2).name == "sign_in"
    # canonical 关键字不受子串别名影响（最长优先）
    cmd = parse(n("购买奴隶@李四"), cfg2)
    assert cmd.target == "李四"
    # @ 前缀形式同样生效
    cmd = parse(n("@李四买下"), cfg2, _matcher(["李四"]))
    assert (cmd.name, cmd.target, cmd.mention) == ("purchase_slave", "李四", "李四")


def test_command_alias_conflict_with_canonical_ignored(cfg):
    from game.config import Config
    data = {**cfg.as_dict(), "command_aliases": {"签到": ["我的金币"]}}
    cfg2 = Config(data)
    # 别名与已有指令关键字冲突 → 忽略，"我的金币" 仍是原指令
    assert parse(n("我的金币"), cfg2).name == "my_coins"
    assert parse(n("签到"), cfg2).name == "sign_in"
