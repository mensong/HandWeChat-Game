"""解析器与规范化测试（含 OCR 空格容错）。"""
from game.parser import parse, parse_pat, usage_hint
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


def test_invalid_target_rejected(cfg):
    assert p(cfg, "购买奴隶@#") is None
    assert p(cfg, "购买奴隶@") is None
    assert p(cfg, "购买奴隶@" + "超" * 45) is None


def test_fullwidth_digits(cfg):
    assert p(cfg, "转账＠张三　１００").amount == 100
    assert p(cfg, "签到\n").name == "sign_in"


# ---------- 拍一拍 ----------

def test_pat_parse():
    pat = parse_pat("“是你的益达”拍了拍“童声微蔓”")
    assert (pat.pat, pat.patted, pat.what) == ("是你的益达", "童声微蔓", "")


def test_pat_parse_with_what():
    pat = parse_pat("“是你的益达”拍了拍“童声微蔓”叫了一声“嗯~”")
    assert (pat.pat, pat.patted, pat.what) == ("是你的益达", "童声微蔓", "叫了一声“嗯~”")


def test_pat_quote_and_space_variants():
    pat = parse_pat('"张三" 拍 了 拍 "李四"')
    assert (pat.pat, pat.patted, pat.what) == ("张三", "李四", "")
    pat = parse_pat("「张三」拍了拍「李四」的头发")
    assert (pat.pat, pat.patted, pat.what) == ("张三", "李四", "的头发")
    pat = parse_pat("“ 是 你 的 益 达 ” 拍了拍 “ 童 声 微 蔓 ”")
    assert (pat.pat, pat.patted) == ("是你的益达", "童声微蔓")


def test_pat_parse_rejects():
    assert parse_pat("我今天拍了拍你的头") is None
    assert parse_pat("张三拍了拍李四") is None
    assert parse_pat("“张三”拍了拍“”") is None
