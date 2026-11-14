"""金币系统处理器。"""
from __future__ import annotations

import math
from datetime import timedelta

from .. import replies
from ..util import fmt_iso


def my_coins(ctx, group: str, sender: str) -> str:
    player = ctx.store.get_player(group, sender)
    rank = None
    if not player.is_phantom:
        rank = ctx.store.coin_rank_position(group, player.coins)
    return replies.my_coins(sender, player.coins, rank)


def sign_in(ctx, group: str, sender: str) -> str:
    now = ctx.now()
    today = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    player = ctx.store.get_player(group, sender)
    if player.last_signin_date == today:
        return replies.sign_in_dup(sender)
    if player.last_signin_date == yesterday:
        streak = player.signin_streak + 1
    else:
        streak = 1
    cfg = ctx.cfg
    reward = min(cfg.get("signin_base_reward") + (streak - 1) * cfg.get("signin_streak_step"),
                 cfg.get("signin_max_reward"))
    balance = ctx.store.adjust_coins(group, sender, reward, "signin", None, fmt_iso(now))
    ctx.store.set_player_field(group, sender, "last_signin_date", today)
    ctx.store.set_player_field(group, sender, "signin_streak", streak)
    return replies.sign_in_ok(reward, streak, balance)


def transfer(ctx, group: str, sender: str, target_name: str, amount: int) -> str:
    if amount < 1:
        return "转账失败：数量必须大于 0。"
    if target_name == sender:
        return "转账失败：不能转账给自己。"
    now = ctx.now()
    ts = fmt_iso(now)
    today = now.date().isoformat()
    receiver = ctx.store.get_or_create_target(
        group, target_name, ts, ctx.cfg.get("initial_coins"),
        ctx.cfg.get("charm_base"), ctx.cfg.get("auto_create_target"))
    if receiver is None:
        return replies.NOT_FOUND_REPLY.format(target=target_name)
    player = ctx.store.get_player(group, sender)
    used = ctx.store.get_daily(group, today, sender, "transfer_out")[1]
    remaining = ctx.cfg.get("transfer_daily_limit") - used
    if amount > remaining:
        return f"转账失败：今日转账额度不足（剩余 {remaining} 金币）。"
    if player.coins < amount:
        return f"转账失败：金币不足（需要 {amount} 金币，当前 {player.coins} 金币）。"
    fee = math.ceil(amount * ctx.cfg.get("transfer_tax_rate"))
    net = amount - fee
    balance = ctx.store.adjust_coins(group, sender, -amount, "transfer", receiver.name, ts)
    ctx.store.adjust_coins(group, receiver.name, net, "transfer", sender, ts)
    ctx.store.incr_daily(group, today, sender, "transfer_out", 1, amount)
    return replies.transfer_ok(sender, receiver.name, net, fee, balance)


def coin_rank(ctx, group: str) -> str:
    return replies.coin_rank(ctx.store.coin_rank(group, 10))


def help(ctx, group: str) -> str:
    return replies.coins_help()
