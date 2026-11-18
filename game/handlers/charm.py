"""魅力系统处理器。"""
from __future__ import annotations

from datetime import timedelta

from .. import replies
from ..util import fmt_iso, parse_iso, round2


def effective_charm(ctx, group: str, player, now=None) -> tuple[float, str]:
    """惰性魅力衰减结算，返回 (当前魅力, 新的衰减锚点)。"""
    if now is None:
        now = ctx.now()
    base = ctx.cfg.get("charm_base")
    anchor = parse_iso(player.charm_anchor)
    period_days = ctx.cfg.get("charm_decay_period_days")
    periods = int((now - anchor).total_seconds() // (period_days * 86400))
    if periods > 0 and player.charm > base:
        rate = ctx.cfg.get("charm_decay_rate")
        new_charm = round2(base + (player.charm - base) * ((1 - rate) ** periods))
        new_anchor = anchor + timedelta(days=period_days * periods)
        ctx.store.update_charm(group, player.name, new_charm, fmt_iso(new_anchor))
        ctx.log.debug("charm decay: %s %s -> %s", group, player.name, new_charm)
        return new_charm, fmt_iso(new_anchor)
    return player.charm, player.charm_anchor


def my_charm(ctx, group: str, sender: str, subject: str | None = None) -> str:
    name = subject or sender
    player = ctx.store.get_player(group, name)
    if player is None:
        return replies.my_charm(name, ctx.cfg.get("charm_base"), None, 0)
    charm, _anchor = effective_charm(ctx, group, player)
    rank = None
    if not player.is_phantom and player.last_signin_date:
        rank = ctx.store.charm_rank_position(group, charm)
    return replies.my_charm(name, charm, rank, player.total_charm_gained)


def charm_rank(ctx, group: str) -> str:
    entries = ctx.store.charm_rank(group, 10)
    return replies.charm_rank(entries)


def help(ctx, group: str) -> str:
    return replies.charm_help()
