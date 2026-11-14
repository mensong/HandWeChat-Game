"""发送队列拆分逻辑测试。"""
from game.send_queue import split_reply


def test_short_reply_untouched():
    text = "签到成功！获得 10 金币。"
    assert split_reply(text, 500) == [text]


def test_long_reply_split_by_lines():
    lines = [f"第{i}行内容" for i in range(100)]
    text = "\n".join(lines)
    parts = split_reply(text, 500)
    assert len(parts) >= 2
    assert all(len(p) <= 500 for p in parts)
    assert parts[0].startswith("(1/")
    assert parts[-1].startswith(f"({len(parts)}/")
    joined = "\n".join(p.split("\n", 1)[1] for p in parts)
    assert joined == text


def test_single_overlong_line_chunked():
    text = "甲" * 1200
    parts = split_reply(text, 500)
    assert len(parts) >= 3
    assert all(len(p) <= 500 for p in parts)
