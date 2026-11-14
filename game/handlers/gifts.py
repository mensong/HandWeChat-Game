"""礼物系统处理器。"""
from __future__ import annotations

from datetime import timedelta

from .. import replies
from ..util import fmt_iso, round2
from .charm import effective_charm


def send_gift(ctx, group: str, sender: str, target_name: str,
              gift_token: str, count) -> str:
    count = count if count is not None else 1
    gift = ctx.cfg.find_gift(gift_token)
    if gift is None:
        return f"送礼失败：没有找到礼物「{gift_token}」，发送「礼物列表」查看可送礼物。"
    if not 1 <= count <= ctx.cfg.get("gift_max_quantity"):
        return f"送礼失败：数量必须在 1~{ctx.cfg.get('gift_max_quantity')} 之间。"
    if target_name == sender:
        return "送礼失败：不能送给自己。"
    now = ctx.now()
    ts = fmt_iso(now)
    today = now.date().isoformat()
    receiver = ctx.store.get_or_create_target(
        group, target_name, ts, ctx.cfg.get("initial_coins"),
        ctx.cfg.get("charm_base"), ctx.cfg.get("auto_create_target"))
    if receiver is None:
        return replies.NOT_FOUND_REPLY.format(target=target_name)
    player = ctx.store.get_player(group, sender)
    cost = gift.price * count
    charm_gain = gift.charm * count
    used = ctx.store.get_daily(group, today, sender, "gift_spend")[1]
    remaining = ctx.cfg.get("gift_daily_spend_limit") - used
    if cost > remaining:
        return f"送礼失败：今日送礼额度不足（剩余 {remaining} 金币）。"
    if player.coins < cost:
        return f"送礼失败：金币不足（需要 {cost} 金币，当前 {player.coins} 金币）。"
    balance = ctx.store.adjust_coins(group, sender, -cost, "gift", receiver.name, ts)
    receiver = ctx.store.get_player(group, receiver.name)
    charm, anchor = effective_charm(ctx, group, receiver, now)
    new_charm = round2(charm + charm_gain)
    ctx.store.update_charm(group, receiver.name, new_charm, anchor)
    ctx.store.insert_gift_event(group, ts, sender, receiver.name,
                                gift.id, gift.name, count, cost, charm_gain)
    return replies.gift_ok(sender, receiver.name, count, gift.name,
                           cost, charm_gain, new_charm)


def gift_list(ctx, group: str) -> str:
    entries = [(g.name, g.price, g.charm) for g in ctx.cfg.gifts]
    return replies.gift_list(entries)


def gift_rank(ctx, group: str) -> str:
    now = ctx.now()
    since = fmt_iso(now - timedelta(days=ctx.cfg.get("gift_rank_days")))
    senders = ctx.store.gift_send_rank(group, since, 5)
    receivers = ctx.store.gift_recv_rank(group, since, 5)
    return replies.gift_rank(ctx.cfg.get("gift_rank_days"), senders, receivers)


def help(ctx, group: str) -> str:
    return replies.gifts_help()
