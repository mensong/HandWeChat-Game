"""结婚系统处理器。"""
from __future__ import annotations

import math
from datetime import timedelta

from .. import replies
from ..util import fmt_iso
from .charm import effective_charm


def _gift_amount(ctx, charm: float) -> int:
    """彩礼 = 对象魅力 × 基数 × 随机系数，向上取整并保证最低值。"""
    factor = ctx.rng.uniform(ctx.cfg.get("marriage_gift_random_min"),
                             ctx.cfg.get("marriage_gift_random_max"))
    raw = charm * ctx.cfg.get("marriage_gift_base") * factor
    return max(ctx.cfg.get("marriage_min_gift"), math.ceil(raw))


def _chance(ctx, kind: str, actor: float, target: float) -> float:
    if actor > target:
        return ctx.cfg.get(f"marriage_{kind}_chance_win")
    if actor < target:
        return ctx.cfg.get(f"marriage_{kind}_chance_lose")
    return ctx.cfg.get(f"marriage_{kind}_chance_equal")


def _roll(ctx, chance: float) -> bool:
    return ctx.rng.uniform(0.0, 1.0) < chance


def _auto_marry(ctx) -> bool:
    return _roll(ctx, ctx.cfg.get("marriage_auto_chance"))


def _settle(ctx, group: str, payer: str, target: str, price: int,
            ts: str, prefix: str = "") -> str:
    """成婚：托管彩礼归对象、双方互设配偶、清除求婚。"""
    ctx.store.adjust_coins(group, target, price, "marriage", payer, ts)
    ctx.store.set_spouse(group, payer, target, ts)
    ctx.store.set_spouse(group, target, payer, ts)
    ctx.store.drop_proposal(group, target)
    return replies.marriage_blessing(payer, target, price,
                                     ctx.cfg.get("marriage_blessing"), prefix)


def _target_player(ctx, group: str, name: str, ts: str):
    return ctx.store.get_or_create_target(
        group, name, ts, ctx.cfg.get("initial_coins"),
        ctx.cfg.get("charm_base"), ctx.cfg.get("auto_create_target"))


def propose(ctx, group: str, sender: str, target_name: str) -> str:
    if target_name == sender:
        return "求婚失败：不能向自己求婚。"
    now = ctx.now()
    ts = fmt_iso(now)
    me = ctx.store.get_player(group, sender)
    target = _target_player(ctx, group, target_name, ts)
    if target is None:
        return replies.NOT_FOUND_REPLY.format(target=target_name)
    if me is None:
        return replies.ERROR_REPLY
    if me.spouse:
        return "求婚失败：你已经有配偶了。"
    if target.spouse:
        return f"求婚失败：{target.name} 已经有配偶了。"
    if ctx.store.get_proposal(group, target.name) is not None:
        return f"求婚失败：{target.name} 已经有一个待处理的求婚。"
    if ctx.store.proposal_by_proposer(group, sender) is not None:
        return "求婚失败：你已有待处理的求婚，请等待对方回复。"
    charm, _anchor = effective_charm(ctx, group, target, now)
    price = _gift_amount(ctx, charm)
    if me.coins < price:
        return f"求婚失败：彩礼需要 {price} 金币，当前 {me.coins} 金币。"
    ctx.store.adjust_coins(group, sender, -price, "propose", target.name, ts)
    ctx.store.create_proposal(group, target.name, sender, price, ts)
    if _auto_marry(ctx):
        return _settle(ctx, group, sender, target.name, price, ts, "天赐良缘，")
    return replies.propose_pending(sender, target.name, price)


def accept(ctx, group: str, sender: str) -> str:
    proposal = ctx.store.get_proposal(group, sender)
    if proposal is None:
        return "没有人向你求婚。"
    now = ctx.now()
    ts = fmt_iso(now)
    proposer = ctx.store.get_player(group, proposal.proposer)
    if proposer is None:
        ctx.store.drop_proposal(group, sender)
        return "求婚已作废。"
    if proposer.spouse:
        ctx.store.adjust_coins(group, proposal.proposer, proposal.bride_price,
                               "marriage_refund", sender, ts)
        ctx.store.drop_proposal(group, sender)
        return f"求婚已作废：{proposal.proposer} 已有配偶，彩礼已退回。"
    return _settle(ctx, group, proposal.proposer, sender, proposal.bride_price, ts)


def reject(ctx, group: str, sender: str) -> str:
    proposal = ctx.store.get_proposal(group, sender)
    if proposal is None:
        return "没有人向你求婚。"
    ts = fmt_iso(ctx.now())
    ctx.store.adjust_coins(group, proposal.proposer, proposal.bride_price,
                           "marriage_refund", sender, ts)
    ctx.store.mark_rejected(group, sender, ts)
    return replies.reject_ok(sender, proposal.proposer, proposal.bride_price,
                             ctx.cfg.get("marriage_force_window_minutes"))


def steal(ctx, group: str, sender: str) -> str:
    proposal = ctx.store.latest_pending(group)
    if proposal is None:
        return "抢婚失败：当前没有进行中的求婚。"
    if sender == proposal.target:
        return "抢婚失败：不能抢自己的求婚。"
    if sender == proposal.proposer:
        return "抢婚失败：这就是你自己的求婚。"
    now = ctx.now()
    ts = fmt_iso(now)
    me = ctx.store.get_player(group, sender)
    target = ctx.store.get_player(group, proposal.target)
    if me is None or target is None:
        return replies.ERROR_REPLY
    if me.spouse:
        return "抢婚失败：你已经有配偶了。"
    if target.spouse:
        return f"抢婚失败：{target.name} 已经有配偶了。"
    if ctx.store.proposal_by_proposer(group, sender) is not None:
        return "抢婚失败：你已有待处理的求婚。"
    charm_me, _a = effective_charm(ctx, group, me, now)
    charm_target, _b = effective_charm(ctx, group, target, now)
    price = _gift_amount(ctx, charm_target)
    if me.coins < price:
        return f"抢婚失败：彩礼需要 {price} 金币，当前 {me.coins} 金币。"
    if not _roll(ctx, _chance(ctx, "steal", charm_me, charm_target)):
        return replies.steal_fail(sender, target.name, proposal.proposer)
    ctx.store.adjust_coins(group, proposal.proposer, proposal.bride_price,
                           "marriage_refund", sender, ts)
    ctx.store.adjust_coins(group, sender, -price, "propose", target.name, ts)
    ctx.store.replace_proposal(group, target.name, sender, price, ts)
    if _auto_marry(ctx):
        return _settle(ctx, group, sender, target.name, price, ts, "抢婚成功，")
    return replies.steal_ok(sender, target.name, price, proposal.proposer)


def force(ctx, group: str, sender: str) -> str:
    now = ctx.now()
    ts = fmt_iso(now)
    window = ctx.cfg.get("marriage_force_window_minutes") * 60
    proposal = ctx.store.latest_forceable(
        group, fmt_iso(now - timedelta(seconds=window)))
    if proposal is None:
        return "逼婚失败：当前没有可逼婚的求婚。"
    if sender == proposal.target:
        return "逼婚失败：不能逼迫自己。"
    me = ctx.store.get_player(group, sender)
    target = ctx.store.get_player(group, proposal.target)
    if me is None or target is None:
        return replies.ERROR_REPLY
    if me.spouse:
        return "逼婚失败：你已经有配偶了。"
    if target.spouse:
        return f"逼婚失败：{target.name} 已经有配偶了。"
    if sender != proposal.proposer \
            and ctx.store.proposal_by_proposer(group, sender) is not None:
        return "逼婚失败：你已有待处理的求婚。"
    charm_me, _a = effective_charm(ctx, group, me, now)
    charm_target, _b = effective_charm(ctx, group, target, now)
    # 自己发起的待处理求婚：彩礼已在托管，直接结算，不重复扣款
    escrow_mine = proposal.status == "pending" and proposal.proposer == sender
    if escrow_mine:
        price = proposal.bride_price
    else:
        price = _gift_amount(ctx, charm_target)
        if me.coins < price:
            return f"逼婚失败：彩礼需要 {price} 金币，当前 {me.coins} 金币。"
    if not _roll(ctx, _chance(ctx, "force", charm_me, charm_target)):
        return replies.force_fail(target.name, proposal.status == "rejected")
    if not escrow_mine:
        if proposal.status == "pending":
            ctx.store.adjust_coins(group, proposal.proposer, proposal.bride_price,
                                   "marriage_refund", sender, ts)
        ctx.store.adjust_coins(group, sender, -price, "propose", target.name, ts)
    return _settle(ctx, group, sender, target.name, price, ts, "逼婚成功，")


def help(ctx, group: str) -> str:
    return replies.marriage_help(ctx.cfg.get("marriage_force_window_minutes"))
