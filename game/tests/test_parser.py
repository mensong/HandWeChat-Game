"""解析器与规范化测试。"""
from game.parser import parse, usage_hint
from game.util import normalize_text


def n(text):
    return normalize_text(text, allow_hash=True)


def test_exact_commands():
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
    ]:
        assert parse(n(text)).name == name


def test_hash_prefix_and_punct():
    assert parse(n("#签到")).name == "sign_in"
    assert parse(n("签到！")).name == "sign_in"
    assert parse(n("#奴隶系统。")).name == "slaves_help"


def test_purchase_target_variants():
    assert parse(n("购买奴隶@张三")).target == "张三"
    assert parse(n("购买奴隶 ＠ 张三")).target == "张三"
    assert parse(n("购买奴隶@张三。")).target == "张三"
    assert parse(n("购买奴隶@张三 谢谢")).target == "张三"
    assert parse(n("购买奴隶@张 三")).target == "张"


def test_release_variants():
    assert parse(n("给他自由@李四")).name == "release_slave"
    assert parse(n("给她自由@李四。")).name == "release_slave"
    assert parse(n("给她自由@李四")).target == "李四"


def test_transfer_parse():
    cmd = parse(n("转账@张三 100"))
    assert cmd.name == "transfer"
    assert cmd.target == "张三"
    assert cmd.amount == 100
    assert parse(n("转账＠张三　１００")).amount == 100


def test_gift_parse():
    cmd = parse(n("送礼@张三 玫瑰"))
    assert (cmd.name, cmd.target, cmd.gift, cmd.count) == ("send_gift", "张三", "玫瑰", None)
    cmd = parse(n("送礼@张三 玫瑰 2 谢谢"))
    assert (cmd.gift, cmd.count) == ("玫瑰", 2)
    cmd = parse(n("送礼@张三 rose 3"))
    assert (cmd.gift, cmd.count) == ("rose", 3)


def test_non_command_silent():
    assert parse(n("我想购买奴隶@张三")) is None
    assert usage_hint(n("我想购买奴隶@张三")) is None
    assert parse(n("奴隶打工 谢谢")) is None
    assert usage_hint(n("奴隶打工 谢谢")) is None
    assert parse(n("今天天气不错")) is None
    assert usage_hint(n("今天天气不错")) is None


def test_usage_hints():
    assert usage_hint(n("购买奴隶 张三")) is not None
    assert usage_hint(n("购买奴隶")) is not None
    assert usage_hint(n("购买奴隶@")) is not None
    assert usage_hint(n("转账@张三")) is not None
    assert usage_hint(n("送礼@张三")) is not None
    assert usage_hint(n("给他自由 李四")) is not None


def test_invalid_target_rejected():
    assert parse(n("购买奴隶@#")) is None
    assert parse(n("购买奴隶@")) is None


def test_multiline_and_fullwidth():
    assert parse(n("签到\n")) is None or parse(n("签到\n")).name == "sign_in"
    assert parse(n("转账＠张三 １００")).amount == 100
