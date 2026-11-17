"""指令路由。"""
from __future__ import annotations

from .context import Ctx
from .handlers import charm, coins, gifts, slaves
from .models import Command


class Dispatcher:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def dispatch(self, cmd: Command, group: str, sender: str) -> str | None:
        ctx = self.ctx
        if cmd.name == "my_coins":
            return coins.my_coins(ctx, group, sender, subject=cmd.mention)
        if cmd.name == "sign_in":
            return coins.sign_in(ctx, group, sender)
        if cmd.name == "transfer":
            return coins.transfer(ctx, group, sender, cmd.target, cmd.amount)
        if cmd.name == "coin_rank":
            return coins.coin_rank(ctx, group)
        if cmd.name == "coins_help":
            return coins.help(ctx, group)
        if cmd.name == "my_charm":
            return charm.my_charm(ctx, group, sender, subject=cmd.mention)
        if cmd.name == "charm_rank":
            return charm.charm_rank(ctx, group)
        if cmd.name == "charm_help":
            return charm.help(ctx, group)
        if cmd.name == "send_gift":
            return gifts.send_gift(ctx, group, sender, cmd.target, cmd.gift, cmd.count)
        if cmd.name == "gift_list":
            return gifts.gift_list(ctx, group)
        if cmd.name == "gift_rank":
            return gifts.gift_rank(ctx, group)
        if cmd.name == "gifts_help":
            return gifts.help(ctx, group)
        if cmd.name == "purchase_slave":
            return slaves.purchase(ctx, group, sender, cmd.target)
        if cmd.name == "release_slave":
            return slaves.release(ctx, group, sender, cmd.target)
        if cmd.name == "slave_work":
            return slaves.work(ctx, group, sender)
        if cmd.name == "my_slaves":
            return slaves.my_slaves(ctx, group, sender, subject=cmd.mention)
        if cmd.name == "train_slave":
            return slaves.train(ctx, group, sender, cmd.target)
        if cmd.name == "train_all_slaves":
            return slaves.train_all(ctx, group, sender)
        if cmd.name == "ransom_slave":
            return slaves.ransom(ctx, group, sender, cmd.target)
        if cmd.name == "rebel":
            return slaves.rebel(ctx, group, sender)
        if cmd.name == "slaves_help":
            return slaves.help(ctx, group)
        return None
