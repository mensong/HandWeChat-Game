"""奴隶系统处理器。"""
from __future__ import annotations

import math
from datetime import timedelta

from .. import replies
from ..util import fmt_iso, parse_iso, round2
from .charm import effective_charm


def _price(ctx, charm: float, coeff_key: str) -> int:
    r = ctx.rng.uniform(ctx.cfg.get("slave_price_random_min"),
                        ctx.cfg.get("slave_price_random_max"))
    raw = charm * ctx.cfg.get(coeff_key) * r
    return max(ctx.cfg.get("min_slave_price"), math.ceil(raw))


def purchase(ctx, group: str, sender: str, target_name: str) -> str:
    if target_name == sender:
        return "购买失败：不能购买自己。"
    now = ctx.now()
    ts = fmt_iso(now)
    player = ctx.store.get_player(group, sender)
    target = ctx.store.get_or_create_target(
        group, target_name, ts, ctx.cfg.get("initial_coins"),
        ctx.cfg.get("charm_base"), ctx.cfg.get("auto_create_target"))
    if target is None:
        return replies.NOT_FOUND_REPLY.format(target=target_name)
    if target.master == sender:
        return f"购买失败：{target.name} 已经是你的奴隶。"
    if target.master is not None:
        return f"购买失败：{target.name} 已经是 {target.master} 的奴隶。"
    if player.master is not None and player.master == target.name:
        return "购买失败：不能购买自己的主人。"
    max_slaves = ctx.cfg.get("max_slaves")
    if ctx.store.slave_count(group, sender) >= max_slaves:
        return f"购买失败：你的奴隶已达上限（{max_slaves} 个）。"
    charm, _anchor = effective_charm(ctx, group, target, now)
    price = _price(ctx, charm, "slave_price_coeff")
    if player.coins < price:
        return f"购买失败：金币不足（需要 {price} 金币，当前 {player.coins} 金币）。"
    ctx.store.adjust_coins(group, sender, -price, "purchase", target.name, ts)
    ctx.store.set_master(group, target.name, sender, ts)
    slaves = [p.name for p in ctx.store.slaves(group, sender)]
    return replies.purchase_ok(sender, price, slaves)


def release(ctx, group: str, sender: str, target_name: str) -> str:
    now = ctx.now()
    ts = fmt_iso(now)
    target = ctx.store.resolve_player(group, target_name)
    if target is None or target.master != sender:
        return f"{sender} 的奴隶列表中没有 {target_name}。"
    charm, _anchor = effective_charm(ctx, group, target, now)
    reward = _price(ctx, charm, "release_reward_coeff")
    ctx.store.set_master(group, target.name, None, ts)
    balance = ctx.store.adjust_coins(group, sender, reward, "release", target.name, ts)
    return (f"恭喜{target.name}恢复自由身。\n"
            f"{sender} 获得 {reward} 金币。")


def work(ctx, group: str, sender: str) -> str:
    now = ctx.now()
    ts = fmt_iso(now)
    today = now.date().isoformat()
    player = ctx.store.get_player(group, sender)
    slaves = ctx.store.slaves(group, sender)
    if not slaves:
        return "你还没有奴隶，先去购买一个吧。"
    cooldown = ctx.cfg.get("slave_work_cooldown_minutes") * 60
    if player.last_work_at:
        elapsed = (now - parse_iso(player.last_work_at)).total_seconds()
        if elapsed < cooldown:
            remaining = math.ceil((cooldown - elapsed) / 60)
            return f"奴隶们还在休息，{remaining} 分钟后再试。"
    count, _ = ctx.store.get_daily(group, today, sender, "work")
    if count >= ctx.cfg.get("slave_work_max_per_day"):
        return f"今天的打工次数已用完（{ctx.cfg.get('slave_work_max_per_day')} 次）。"
    events = ctx.cfg.work_events
    weights = [e.weight for e in events]
    lines = []
    total = 0
    for slave in slaves:
        ev = ctx.rng.weighted_choice(events, weights)
        if ev.coins_min == ev.coins_max:
            coins = ev.coins_min
        else:
            coins = ctx.rng.randint(ev.coins_min, ev.coins_max)
        actual = coins
        if coins < 0:
            current = ctx.store.get_player(group, sender)
            actual = max(coins, -current.coins)
        if actual != 0:
            ctx.store.adjust_coins(group, sender, actual, "work", slave.name, ts)
        total += actual
        lines.append(replies.work_line(slave.name, ev.text, actual))
    balance = ctx.store.get_player(group, sender).coins
    ctx.store.set_player_field(group, sender, "last_work_at", ts)
    ctx.store.incr_daily(group, today, sender, "work", 1, 0)
    return replies.work_report(sender, lines, total, balance)


def my_slaves(ctx, group: str, sender: str) -> str:
    slaves = [p.name for p in ctx.store.slaves(group, sender)]
    return replies.slave_list(sender, slaves, ctx.cfg.get("max_slaves"))


def _render_interaction(text: str, master: str, slave: str) -> str:
    return (text.replace("{sender}", master)
            .replace("{奴隶}", slave)
            .replace("{target}", slave))


def _interaction_limit_error(ctx, group: str, sender: str, player, now):
    cooldown = ctx.cfg.get("interaction_cooldown_minutes") * 60
    if player.last_interact_at:
        elapsed = (now - parse_iso(player.last_interact_at)).total_seconds()
        if elapsed < cooldown:
            remaining = math.ceil((cooldown - elapsed) / 60)
            return f"调教冷却中，还需 {remaining} 分钟。"
    today = now.date().isoformat()
    count, _ = ctx.store.get_daily(group, today, sender, "interaction")
    if count >= ctx.cfg.get("interaction_max_per_day"):
        return f"今天的调教次数已用完（{ctx.cfg.get('interaction_max_per_day')} 次）。"
    return None


def _interact_once(ctx, group: str, master: str, slave, now) -> str:
    cfg = ctx.cfg
    item = ctx.rng.choice(cfg.interactions)
    numbers = [
        cfg.get("interaction_weight_coins"),
        cfg.get("interaction_weight_charm"),
        cfg.get("interaction_weight_both"),
    ]
    # 内部键：比特_，避免与中文语气标签混用
    mode = ctx.rng.weighted_choice(["coins", "charm", "both"], numbers)
    changes = []
    if mode in ("coins", "both"):
        magnitude = ctx.rng.randint(cfg.get("interaction_coins_min"),
                                    cfg.get("interaction_coins_max"))
        delta = magnitude * ctx.rng.choice([1, -1])
        current = ctx.store.get_player(group, slave.name).coins
        actual = max(delta, -current)
        if actual:
            ctx.store.adjust_coins(group, slave.name, actual, "interaction", master,
                                   fmt_iso(now))
        changes.append(("coins", actual))
    if mode in ("charm", "both"):
        magnitude = ctx.rng.randint(cfg.get("interaction_charm_min"),
                                    cfg.get("interaction_charm_max"))
        delta = magnitude * ctx.rng.choice([1, -1])
        charm, anchor = effective_charm(ctx, group, slave, now)
        new_charm = round2(max(0, charm + delta))
        actual = round2(new_charm - charm)
        if actual:
            ctx.store.update_charm(group, slave.name, new_charm, anchor)
        changes.append(("charm", actual))
    narrative = _render_interaction(item.text, master, slave.name)
    effect = replies.interaction_effect(slave.name, item.tone, changes)
    return f"{narrative}\n{effect}"


def train(ctx, group: str, sender: str, target_name: str) -> str:
    if target_name == sender:
        return "调教失败：不能调教自己。"
    target = ctx.store.resolve_player(group, target_name)
    if target is None or target.master != sender:
        return f"调教失败：{target_name} 不是你的奴隶。"
    if not ctx.cfg.interactions:
        return "暂无可用的互动内容。"
    now = ctx.now()
    player = ctx.store.get_player(group, sender)
    err = _interaction_limit_error(ctx, group, sender, player, now)
    if err:
        return err
    text = _interact_once(ctx, group, sender, target, now)
    ts = fmt_iso(now)
    ctx.store.set_player_field(group, sender, "last_interact_at", ts)
    ctx.store.incr_daily(group, now.date().isoformat(), sender, "interaction", 1, 0)
    return text


def train_all(ctx, group: str, sender: str) -> str:
    slaves = ctx.store.slaves(group, sender)
    if not slaves:
        return "你还没有奴隶，先去购买一个吧。"
    if not ctx.cfg.interactions:
        return "暂无可用的互动内容。"
    now = ctx.now()
    player = ctx.store.get_player(group, sender)
    err = _interaction_limit_error(ctx, group, sender, player, now)
    if err:
        return err
    shown = 20
    lines = []
    for i, slave in enumerate(slaves, 1):
        text = _interact_once(ctx, group, sender, slave, now)
        if i <= shown:
            lines.append(f"{i}. {text.replace(chr(10), ' ')}")
    if len(slaves) > shown:
        lines.append(f"…（共 {len(slaves)} 个）")
    ts = fmt_iso(now)
    ctx.store.set_player_field(group, sender, "last_interact_at", ts)
    ctx.store.incr_daily(group, now.date().isoformat(), sender, "interaction", 1, 0)
    return f"{sender} 调教奴隶：\n" + "\n".join(lines)


def _ransom_limit_error(ctx, group: str, sender: str, player, now):
    cooldown = ctx.cfg.get("ransom_cooldown_minutes") * 60
    if player.last_ransom_at:
        elapsed = (now - parse_iso(player.last_ransom_at)).total_seconds()
        if elapsed < cooldown:
            remaining = math.ceil((cooldown - elapsed) / 60)
            return f"赎身冷却中，还需 {remaining} 分钟。"
    today = now.date().isoformat()
    count, _ = ctx.store.get_daily(group, today, sender, "ransom")
    if count >= ctx.cfg.get("ransom_max_per_day"):
        return f"今天的赎身次数已用完（{ctx.cfg.get('ransom_max_per_day')} 次）。"
    return None


def ransom(ctx, group: str, sender: str, target_name: str) -> str:
    if target_name == sender:
        return "赎身失败：不能给自己赎身。"
    target = ctx.store.resolve_player(group, target_name)
    if target is None or target.master is None:
        return f"赎身失败：{target_name} 不是奴隶。"
    if target.master == sender:
        return "赎身失败：不能赎自己的奴隶，请使用「给他自由」。"
    now = ctx.now()
    player = ctx.store.get_player(group, sender)
    err = _ransom_limit_error(ctx, group, sender, player, now)
    if err:
        return err
    charm, _anchor = effective_charm(ctx, group, target, now)
    price = math.ceil(charm * ctx.cfg.get("ransom_price_coeff")
                      * ctx.rng.uniform(0.0, 3.0))
    price = max(0, price)
    if player.coins < price:
        return f"赎身失败：金币不足（需要 {price} 金币，当前 {player.coins} 金币）。"
    master = target.master
    ts = fmt_iso(now)
    if price:
        ctx.store.adjust_coins(group, sender, -price, "ransom", master, ts)
        ctx.store.adjust_coins(group, master, price, "ransom", sender, ts)
    ctx.store.set_master(group, target.name, None, ts)
    ctx.store.set_player_field(group, sender, "last_ransom_at", ts)
    ctx.store.incr_daily(group, now.date().isoformat(), sender, "ransom", 1, 0)
    return replies.ransom_ok(sender, target.name, price, master)


def rebel(ctx, group: str, sender: str) -> str:
    now = ctx.now()
    ts = fmt_iso(now)
    today = now.date().isoformat()
    player = ctx.store.get_player(group, sender)
    if not player.master:
        return "你现在是自由身，不需要反抗。"
    master = ctx.store.get_player(group, player.master)
    if master is None:
        master = ctx.store.find_player_ci(group, player.master)
    if master is None:
        return "系统开小差了，请稍后再试。"
    cooldown = ctx.cfg.get("rebel_cooldown_minutes") * 60
    if player.last_rebel_at:
        elapsed = (now - parse_iso(player.last_rebel_at)).total_seconds()
        if elapsed < cooldown:
            remaining = math.ceil((cooldown - elapsed) / 60)
            return f"你刚反抗过，还需 {remaining} 分钟。"
    count, _ = ctx.store.get_daily(group, today, sender, "rebel")
    if count >= ctx.cfg.get("rebel_max_per_day"):
        return f"今天的反抗次数已用完（{ctx.cfg.get('rebel_max_per_day')} 次）。"

    master_mult = ctx.rng.choice(ctx.cfg.get("rebel_master_multipliers"))
    slave_mult = ctx.rng.choice(ctx.cfg.get("rebel_slave_multipliers"))
    master_charm, _ = effective_charm(ctx, group, master, now)
    slave_charm, _ = effective_charm(ctx, group, player, now)
    master_score = round2(master_charm * ctx.cfg.get("rebel_master_coeff") * master_mult)
    slave_score = round2(slave_charm * ctx.cfg.get("rebel_slave_coeff") * slave_mult)
    success = slave_score >= master_score

    branch = ctx.rng.choice([1, 2, 3])
    master_coins = ctx.store.get_player(group, master.name).coins
    slave_coins = ctx.store.get_player(group, sender).coins
    reply = None

    if success:
        ctx.store.set_master(group, sender, None, ts)
        if branch == 2 and master_coins > 0:
            loot = ctx.rng.randint(1, min(master_coins, ctx.cfg.get("rebel_loot_max")))
            ctx.store.adjust_coins(group, master.name, -loot, "rebel", sender, ts)
            ctx.store.adjust_coins(group, sender, loot, "rebel", master.name, ts)
            reply = f"恭喜{sender}恢复自由身，并拿走{master.name}的{loot}金币。"
        elif branch == 3 and slave_coins > 0:
            ransom = ctx.rng.randint(1, min(slave_coins, ctx.cfg.get("rebel_ransom_max")))
            ctx.store.adjust_coins(group, sender, -ransom, "rebel", master.name, ts)
            ctx.store.adjust_coins(group, master.name, ransom, "rebel", sender, ts)
            reply = f"恭喜{sender}恢复自由身，并支付{master.name}赎金{ransom}金币。"
        else:
            reply = f"恭喜{sender}恢复自由身。"
    else:
        if branch == 2 and slave_coins > 0:
            penalty = ctx.rng.randint(1, min(slave_coins, ctx.cfg.get("rebel_ransom_max")))
            ctx.store.adjust_coins(group, sender, -penalty, "rebel", master.name, ts)
            ctx.store.adjust_coins(group, master.name, penalty, "rebel", sender, ts)
            reply = f"{sender}反抗失败，遭到{master.name}镇压，上缴主人{penalty}金币。"
        elif branch == 3 and master_coins > 0:
            comp = ctx.rng.randint(1, min(master_coins, ctx.cfg.get("rebel_compensation_max")))
            ctx.store.adjust_coins(group, master.name, -comp, "rebel", sender, ts)
            ctx.store.adjust_coins(group, sender, comp, "rebel", master.name, ts)
            reply = f"{sender}反抗失败，但{master.name}良心发现，补贴{comp}金币。"
        else:
            reply = f"{sender}反抗失败。"

    ctx.store.set_player_field(group, sender, "last_rebel_at", ts)
    ctx.store.incr_daily(group, today, sender, "rebel", 1, 0)
    return reply


def help(ctx, group: str) -> str:
    return replies.slaves_help()
