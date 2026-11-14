"""所有回复模板。"""
from __future__ import annotations

from typing import Optional, Sequence

from .util import fmt_charm

ERROR_REPLY = "系统开小差了，请稍后再试。"
NOT_FOUND_REPLY = "未找到玩家「{target}」，请确认昵称是否正确。"


def my_coins(sender: str, coins: int, rank: Optional[int]) -> str:
    pos = f"群内第 {rank} 名" if rank is not None else "未上榜"
    return f"我的金币：\n{sender} 当前金币 {coins}（{pos}）。"


def sign_in_ok(reward: int, streak: int, coins: int) -> str:
    return f"签到成功！获得 {reward} 金币（连续签到 {streak} 天）。\n当前金币：{coins}。"


def sign_in_dup(sender: str) -> str:
    return f"{sender} 今天已经签到过了，明天再来吧。"


def transfer_ok(sender: str, target: str, net: int, fee: int, coins: int) -> str:
    return (f"转账成功：{sender} → {target} {net} 金币（手续费 {fee} 金币）。\n"
            f"{sender} 当前金币：{coins}。")


def coin_rank(entries: Sequence[tuple[str, int]]) -> str:
    if not entries:
        return "金币榜暂无数据。"
    lines = ["金币榜 TOP10："]
    lines += [f"{i}. {name} {coins}" for i, (name, coins) in enumerate(entries, 1)]
    return "\n".join(lines)


def coins_help() -> str:
    return ("金币系统指令：\n"
            "1. 我的金币 —— 查看余额与排名\n"
            "2. 签到 —— 每日签到领金币\n"
            "3. 转账@用户名 数量 —— 转账（手续费 5%）\n"
            "4. 金币榜 —— 金币排行")


def my_charm(sender: str, charm: float, rank: Optional[int], total_gained: float) -> str:
    pos = f"群内第 {rank} 名" if rank is not None else "未上榜"
    return (f"{sender} 当前魅力值 {fmt_charm(charm)}，{pos}。\n"
            f"累计收到礼物魅力 +{fmt_charm(total_gained)}。")


def charm_rank(entries: Sequence[tuple[str, float]]) -> str:
    if not entries:
        return "魅力榜暂无数据。"
    lines = ["魅力榜 TOP10："]
    lines += [f"{i}. {name} {fmt_charm(c)}" for i, (name, c) in enumerate(entries, 1)]
    return "\n".join(lines)


def charm_help() -> str:
    return ("魅力系统指令：\n"
            "1. 我的魅力 —— 查看魅力值与排名\n"
            "2. 魅力榜 —— 魅力排行\n"
            "说明：收到礼物可增加魅力；魅力每 7 天衰减 10%，最低不低于基础值 10。")


def gift_list(entries: Sequence[tuple[str, int, float]]) -> str:
    lines = ["礼物列表（价格 / 魅力）："]
    lines += [f"{name} {price} 金币 +{fmt_charm(charm)} 魅力"
              for name, price, charm in entries]
    lines.append("用法：送礼@用户名 礼物名 [数量]")
    return "\n".join(lines)


def gift_ok(sender: str, target: str, count: int, gift_name: str, cost: int,
            charm_gain: float, target_charm: float) -> str:
    return (f"{sender} 送给 {target} ×{count} {gift_name}，花费 {cost} 金币。\n"
            f"{target} 魅力 +{fmt_charm(charm_gain)}，当前魅力 {fmt_charm(target_charm)}。")


def gift_rank(days: int, senders: Sequence[tuple[str, int]],
              receivers: Sequence[tuple[str, float]]) -> str:
    lines = [f"送礼榜 TOP5（近 {days} 天）："]
    if senders:
        lines += [f"{i}. {name} {coins} 金币" for i, (name, coins) in enumerate(senders, 1)]
    else:
        lines.append("暂无数据")
    lines.append("")
    lines.append(f"收礼榜 TOP5（近 {days} 天）：")
    if receivers:
        lines += [f"{i}. {name} {fmt_charm(c)} 魅力" for i, (name, c) in enumerate(receivers, 1)]
    else:
        lines.append("暂无数据")
    return "\n".join(lines)


def gifts_help() -> str:
    return ("礼物系统指令：\n"
            "1. 礼物列表 —— 查看可送礼物\n"
            "2. 送礼@用户名 礼物名 [数量] —— 赠送礼物\n"
            "3. 礼物榜 —— 近 30 天送礼 / 收礼排行\n"
            "说明：送礼消耗金币，收礼增加魅力。")


def purchase_ok(sender: str, price: int, slaves: Sequence[str], max_display: int = 20) -> str:
    lines = [f"购买成功，花费 {price} 金币。", f"{sender}的奴隶："]
    shown = slaves[:max_display]
    lines += [f"{i}. {s}" for i, s in enumerate(shown, 1)]
    if len(slaves) > max_display:
        lines.append(f"…（共 {len(slaves)} 个）")
    return "\n".join(lines)


def slave_list(sender: str, slaves: Sequence[str], max_slaves: int,
               max_display: int = 20) -> str:
    if not slaves:
        return f"{sender} 目前没有奴隶。"
    lines = [f"{sender}的奴隶（{len(slaves)}/{max_slaves}）："]
    shown = slaves[:max_display]
    lines += [f"{i}. {s}" for i, s in enumerate(shown, 1)]
    if len(slaves) > max_display:
        lines.append(f"…（共 {len(slaves)} 个）")
    return "\n".join(lines)


def work_report(sender: str, lines: Sequence[str], total: int, coins: int) -> str:
    body = [f"{sender}的奴隶打工："] + list(lines)
    body.append(work_total_line(total, coins))
    return "\n".join(body)


def work_line(slave: str, event_text: str, coins_delta: int) -> str:
    if coins_delta > 0:
        return f"{slave} {event_text}，为主人赚得 {coins_delta} 金币。"
    if coins_delta < 0:
        return f"{slave} {event_text}，让主人损失 {abs(coins_delta)} 金币。"
    return f"{slave} {event_text}，没有收获。"


def work_total_line(total: int, coins: int) -> str:
    if total > 0:
        return f"本次合计：+{total} 金币，当前金币 {coins}。"
    if total < 0:
        return f"本次合计：-{abs(total)} 金币，当前金币 {coins}。"
    return f"本次合计：0 金币，当前金币 {coins}。"


def slaves_help() -> str:
    return ("奴隶系统指令：\n"
            "1. 购买奴隶@用户名 —— 购买奴隶\n"
            "2. 给他自由@用户名 / 给她自由@用户名 —— 释放奴隶\n"
            "3. 奴隶打工 —— 让所有奴隶打工\n"
            "4. 我的奴隶 —— 查看我的奴隶\n"
            "5. 我要自由 —— 反抗奴隶主\n"
            "说明：购买价格 = 目标魅力值 × 系数 × 随机系数；每个主人最多 5 个奴隶。")
