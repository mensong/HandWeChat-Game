"""所有回复模板。"""
from __future__ import annotations

from typing import Optional, Sequence

from .util import fmt_charm

ERROR_REPLY = "系统开小差了，请稍后再试。"
NOT_FOUND_REPLY = "未找到玩家「{target}」，请确认昵称是否正确。"

_TONE_EXPECT = {"褒": 1, "贬": -1}


def fmt_delta(value) -> str:
    if float(value).is_integer():
        return f"{int(value):+d}"
    return f"{round(float(value), 1):+.1f}"


def interaction_effect(slave: str, tone: str, changes) -> str:
    """changes 为 [(字段, 变化值)]，字段取 coins/charm；语气相反时加“但…却”。"""
    expect = _TONE_EXPECT.get(tone)
    parts = []
    for field, delta in changes:
        if not delta:
            continue
        label = "金币" if field == "coins" else "魅力"
        if expect is not None and delta * expect < 0:
            parts.append(f"但 {slave} 的{label}却{fmt_delta(delta)}")
        else:
            parts.append(f"{slave} 的{label}{fmt_delta(delta)}")
    if not parts:
        return f"{slave} 这次没有任何变化。"
    return "，".join(parts)


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


def ransom_ok(sender: str, target: str, price: int, master: str) -> str:
    if price:
        return (f"{sender} 为 {target} 赎身，支付 {price} 金币。\n"
                f"{target} 已恢复自由身，{master} 获得 {price} 金币。")
    return (f"{sender} 为 {target} 赎身，没有花费金币。\n"
            f"{target} 已恢复自由身（原主人 {master}）。")


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
            "6. 调教@奴隶名 —— 与自己的奴隶互动\n"
            "7. 调教所有奴隶 —— 调教全部奴隶\n"
            "8. 赎身@奴隶名 —— 为别人的奴隶赎身\n"
            "说明：购买价格 = 目标魅力值 × 系数 × 随机系数；每个主人最多 5 个奴隶。")


def propose_pending(sender: str, target: str, price: int) -> str:
    return (f"{sender} 向 {target} 求婚，彩礼 {price} 金币已由系统托管。\n"
            f"{target} 回复「同意」或「拒绝」，其他人可回复「抢婚」。")


def steal_ok(sender: str, target: str, price: int, old_proposer: str) -> str:
    return (f"抢婚成功！{sender} 抢下了对 {target} 的求婚，彩礼 {price} 金币已托管。\n"
            f"{old_proposer} 的彩礼已全额退回。\n"
            f"{target} 回复「同意」或「拒绝」，其他人仍可继续「抢婚」。")


def steal_fail(sender: str, target: str, proposer: str) -> str:
    return f"抢婚失败，{target} 的求婚仍由 {proposer} 保持。"


def reject_ok(target: str, proposer: str, price: int, window_minutes: int) -> str:
    return (f"{target} 拒绝了 {proposer} 的求婚。\n"
            f"彩礼 {price} 金币已退回 {proposer}。\n"
            f"（{window_minutes} 分钟内仍可被「逼婚」）")


def force_fail(target: str, rejected: bool) -> str:
    if rejected:
        return f"逼婚失败，{target} 仍是自由身。"
    return f"逼婚失败，{target} 的求婚仍在进行中。"


def marriage_blessing(payer: str, target: str, price: int,
                      art: Sequence[str], prefix: str = "") -> str:
    lines = [f"{prefix}恭喜 {payer} 与 {target} 喜结连理！",
             f"彩礼 {price} 金币已归 {target}。"]
    lines.extend(art)
    lines.append("愿你们百年好合～")
    return "\n".join(lines)


def marriage_help(window_minutes: int) -> str:
    return ("结婚系统指令：\n"
            "1. 求婚@用户名 —— 支付彩礼向对方求婚\n"
            "2. 同意 / 拒绝 —— 回应向你发起的求婚\n"
            "3. 抢婚 —— 抢下别人正在进行中的求婚\n"
            f"4. 逼婚 —— 强行求婚（被拒后 {window_minutes} 分钟内仍有效）\n"
            "说明：彩礼由系统托管，成婚归对象，被拒或超时退回；成婚需双方未婚。")
