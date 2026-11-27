"""game.main 的 Web 控制台：玩家数据、动作日志、运行状态、游戏配置。

挂在健康端口上（默认 8001），`/health` 接口保留；
页面入口 `http://<host>:8001/`。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config, ConfigError, read_config_file, write_config_file
from .engine import Engine
from .util import fmt_iso

CONSOLE_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>游戏控制台</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Microsoft YaHei", system-ui, sans-serif;
       background: #111418; color: #d8dde3; }
header { padding: 10px 16px; background: #1a1f26; border-bottom: 1px solid #2a313a; }
header h1 { font-size: 16px; margin: 0 0 6px; color: #7fb2ff; }
.statusbar { display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; }
.statusbar .k { color: #6a737d; margin-right: 4px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 5px;
       margin-right: 4px; vertical-align: middle; }
.dot.ok { background: #7fd18b; }
.dot.bad { background: #ff8a80; }
nav { display: flex; gap: 4px; padding: 0 16px; background: #1a1f26;
      border-bottom: 1px solid #2a313a; }
nav button { background: transparent; color: #9aa3ad; border: none;
             border-bottom: 2px solid transparent; padding: 8px 16px;
             cursor: pointer; font-size: 14px; }
nav button.active { color: #7fb2ff; border-bottom-color: #7fb2ff; }
main { padding: 14px; max-width: 1200px; margin: 0 auto; }
.page { display: none; }
.page.active { display: block; }
section { background: #1a1f26; border: 1px solid #2a313a; border-radius: 8px;
          padding: 14px; margin-bottom: 14px; }
section h2 { font-size: 14px; margin: 0 0 10px; color: #7fb2ff; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: #9aa3ad; font-weight: normal; padding: 5px 8px;
     border-bottom: 1px solid #2a313a; }
td { padding: 5px 8px; border-bottom: 1px solid #232a32; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.master { color: #f0c674; }
.phantom { color: #6a737d; }
input[type=text], input[type=number], select { background: #0f1216; color: #d8dde3;
        border: 1px solid #3a434e; border-radius: 4px; padding: 6px 8px; font-size: 13px; }
button.act { background: #2f6fdb; color: #fff; border: 1px solid #2f6fdb;
             border-radius: 4px; padding: 5px 14px; cursor: pointer; font-size: 13px; }
button.act:hover { background: #3d7de8; }
button.ghost { background: #2a313a; color: #d8dde3; border: 1px solid #3a434e;
               border-radius: 4px; padding: 5px 12px; cursor: pointer; font-size: 13px; }
.row { display: grid; grid-template-columns: 260px 1fr; gap: 10px;
       align-items: center; margin-bottom: 8px; }
.row label { font-size: 13px; color: #c3cad2; }
.row .desc { font-size: 11px; color: #6a737d; }
.formline { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
.formline input, .formline select { width: auto; }
#msg, #pmsg { font-size: 13px; margin-left: 10px; }
#msg.ok, #pmsg.ok { color: #7fd18b; }
#msg.err, #pmsg.err { color: #ff8a80; }
.result { color: #cdb8ff; }
.hint { font-size: 12px; color: #6a737d; line-height: 1.7; }
.kv { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; }
.kv .item { background: #0f1216; border: 1px solid #232a32; border-radius: 6px; padding: 8px 10px; }
.kv .k { font-size: 12px; color: #6a737d; }
.kv .v { font-size: 14px; margin-top: 2px; }
</style>
</head>
<body>
<header>
  <h1>微信群游戏控制台</h1>
  <div class="statusbar" id="statusbar">加载中…</div>
</header>
<nav>
  <button id="tabbtn_players" onclick="showTab('players')">玩家数据</button>
  <button id="tabbtn_logs" onclick="showTab('logs')">动作日志</button>
  <button id="tabbtn_config" onclick="showTab('config')">游戏配置</button>
</nav>
<main>
  <div class="page" id="page_players">
    <section>
      <h2>玩家列表</h2>
      <div class="formline">
        <span>群：</span>
        <select id="groupsel" onchange="loadPlayers()"></select>
        <span id="pmsg"></span>
      </div>
      <table>
        <thead><tr><th>玩家</th><th>金币</th><th>魅力</th><th>主人</th>
                     <th>连签</th><th>最近活跃</th><th>操作</th></tr></thead>
        <tbody id="pbody"></tbody>
      </table>
    </section>
    <section>
      <h2>管理员操作（写流水，reason=admin）</h2>
      <div class="formline">
        玩家 <input type="text" id="pname" list="pnames" style="width:140px">
        <datalist id="pnames"></datalist>
        动作 <select id="paction">
          <option value="add_coins">加/扣金币</option>
          <option value="set_charm">设置魅力</option>
          <option value="release_slave">解除奴隶（无奖励）</option>
        </select>
        数值 <input type="text" id="pamount" style="width:110px" placeholder="金币增减 / 魅力值">
        <button class="act" onclick="editPlayer()">执行</button>
      </div>
      <p class="hint">加金币填正负整数（负数扣除，余额不能为负）；设置魅力填非负数；
解除奴隶立即生效且不发放释放奖励。玩家不存在会报错，先让对方发一条消息注册。</p>
    </section>
    <section>
      <h2>危险操作</h2>
      <div class="formline">
        <label style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" id="purgechk"> 连同流水 / 礼物记录一起删除
        </label>
      </div>
      <div class="formline">
        <button class="ghost" onclick="cleanPhantoms()">清理本群影子玩家</button>
        <span style="color:#6a737d" id="phantomcount"></span>
      </div>
      <div class="formline">
        清空整群数据（输入群标题确认）：
        <input type="text" id="cleargroup" style="width:220px">
        <button class="ghost" style="background:#5a2a2a;color:#ff8a80;border-color:#7a3a3a"
                onclick="clearGroup()">清空该群全部玩家</button>
      </div>
      <p class="hint">删除玩家时，其名下奴隶自动恢复自由身，每日计数器一并删除；
金币流水与礼物记录默认保留（近 30 天榜单仍会出现已删玩家），勾选后才会一并删除。
影子玩家是 OCR 噪声误识别产生的未发言玩家，不参与排行榜，可放心清理。</p>
    </section>
  </div>
  <div class="page" id="page_logs">
    <section>
      <h2>指令与事件（内存最近 500 条，更早的查 data/logs/game.log）</h2>
      <div class="formline"><button class="ghost" onclick="loadLogs()">刷新</button></div>
      <table>
        <thead><tr><th>时间</th><th>类型</th><th>群</th><th>发信人</th><th>指令</th>
                   <th>结果</th><th>耗时</th><th>摘要</th></tr></thead>
        <tbody id="lbody"></tbody>
      </table>
    </section>
  </div>
  <div class="page" id="page_config">
    <section>
      <h2>游戏配置 <span id="cfgpath" style="font-size:12px;color:#6a737d"></span></h2>
      <div class="formline">
        <button class="act" onclick="saveConfig()">保存到配置文件</button>
        <button class="ghost" onclick="loadConfig()">放弃修改并重新加载</button>
        <span id="msg"></span>
      </div>
      <p class="hint">保存前会用游戏校验器检查，非法配置不会被写入。
保存后自动热加载、立即生效（改动会写入动作日志）；
仅 gateway_url、gateway_app_id、gateway_token、gateway_rules、web_host、health_port、timezone 需重启 game.main 生效。</p>
      <div id="form"></div>
    </section>
  </div>
</main>
<script>
const META = [
  {group: "服务与接口", items: [
    ["gateway_url", "网关地址", "text", ""],
    ["gateway_app_id", "网关应用 ID", "text", "需与网关配置 apps[].id 一致"],
    ["gateway_token", "网关 token", "text", "网关配置 apps[].token；留空表示不校验"],
    ["gateway_rules", "网关规则（JSON）", "json", "null = 自动生成；非空数组则手写覆盖"],
    ["health_port", "控制台/健康检查端口", "num", ""],
    ["web_host", "控制台绑定地址", "text", "0.0.0.0=局域网可访问；127.0.0.1=仅本机"],
    ["timezone", "时区", "text", ""],
  ]},
  {group: "消息处理与限流", items: [
    ["allow_hash_prefix", "允许 # 前缀", "bool", ""],
    ["ignore_senders", "忽略的发送者", "json", ""],
    ["dedupe_window_seconds", "同内容去重窗口（秒）", "num", ""],
    ["command_rate_limit_seconds", "单用户指令间隔（秒）", "num", ""],
    ["help_cooldown_seconds", "帮助指令冷却（秒）", "num", ""],
    ["usage_hint_cooldown_seconds", "用法提示冷却（秒）", "num", ""],
    ["command_aliases", "指令别名", "json", '如 {"购买奴隶":["购买","买下"]}，键为规范指令名，未知键忽略'],
    ["reply_max_chars", "单条回复上限（字符）", "num", ""],
  ]},
  {group: "自动回复", items: [
    ["bot_name", "机器人昵称", "text", "配置中所有字符串可用 {bot} 引用；pattern 内自动转义"],
    ["bot_name_aliases", "机器人提及别名", "json", "数组，供 @机器人 指令识别；填群昵称或 OCR 误读的写法，机器人昵称本身始终生效"],
    ["auto_replies", "回复规则（JSON 数组）", "json_text", '每项：name 名称、pattern 正则、replies 文案（字符串或数组）、cooldown_seconds 冷却、cooldown_key 冷却键（默认 {sender}）、enabled 启用、allow_ignored_senders 允许系统行；文案支持 {sender} {bot} 与 {msg1}..{msgN}'],
  ]},
  {group: "发送限速", items: [
    ["send_max_per_minute", "每分钟最多发送（≤20）", "num", ""],
    ["send_min_interval_ms", "两条发送最小间隔（毫秒）", "num", ""],
    ["send_queue_max", "发送队列上限", "num", ""],
  ]},
  {group: "群识别", items: [
    ["allowed_groups", "允许的群标题（白名单）", "json", "空数组 = 允许所有群"],
    ["group_title_stable_seconds", "群标题稳定窗口（秒）", "num", ""],
  ]},
  {group: "玩家与金币", items: [
    ["initial_coins", "新玩家初始金币", "num", ""],
    ["auto_create_target", "目标不存在时自动创建影子玩家", "bool", ""],
    ["signin_base_reward", "签到基础奖励", "num", ""],
    ["signin_streak_step", "连签每日加成", "num", ""],
    ["signin_max_reward", "签到奖励上限", "num", ""],
    ["chat_coins_per_message", "每条消息金币奖励", "num", "0=关闭聊天收入"],
    ["chat_coins_daily_cap", "聊天收入每日上限", "num", "0=不设上限"],
    ["transfer_tax_rate", "转账手续费率（0~1）", "num", ""],
    ["transfer_daily_limit", "每日转账转出上限", "num", ""],
  ]},
  {group: "魅力", items: [
    ["charm_base", "基础魅力值", "num", ""],
    ["charm_decay_period_days", "衰减周期（天）", "num", ""],
    ["charm_decay_rate", "每周期衰减比例（0~1）", "num", ""],
  ]},
  {group: "奴隶", items: [
    ["max_slaves", "每主人奴隶上限", "num", ""],
    ["slave_price_coeff", "购买价格系数", "num", ""],
    ["slave_price_random_min", "随机系数下限", "num", ""],
    ["slave_price_random_max", "随机系数上限", "num", ""],
    ["min_slave_price", "最低购买/释放价格", "num", ""],
    ["release_reward_coeff", "释放奖励系数", "num", ""],
    ["slave_work_cooldown_minutes", "打工冷却（分钟）", "num", ""],
    ["slave_work_max_per_day", "打工每日次数", "num", ""],
    ["rebel_cooldown_minutes", "反抗冷却（分钟）", "num", ""],
    ["rebel_max_per_day", "反抗每日次数", "num", ""],
    ["rebel_master_coeff", "主人战力系数", "num", ""],
    ["rebel_slave_coeff", "奴隶战力系数", "num", ""],
    ["rebel_master_multipliers", "主人随机倍率", "json", ""],
    ["rebel_slave_multipliers", "奴隶随机倍率", "json", ""],
    ["rebel_loot_max", "抢走上限", "num", ""],
    ["rebel_ransom_max", "赎金/上缴上限", "num", ""],
    ["rebel_compensation_max", "补贴上限", "num", ""],
    ["interaction_coins_min", "调教金币变化下限（绝对值）", "num", ""],
    ["interaction_coins_max", "调教金币变化上限（绝对值）", "num", ""],
    ["interaction_charm_min", "调教魅力变化下限（绝对值）", "num", ""],
    ["interaction_charm_max", "调教魅力变化上限（绝对值）", "num", ""],
    ["interaction_weight_coins", "只变金币的权重", "num", ""],
    ["interaction_weight_charm", "只变魅力的权重", "num", ""],
    ["interaction_weight_both", "金币和魅力都变的权重", "num", ""],
    ["interaction_cooldown_minutes", "调教冷却（分钟）", "num", ""],
    ["interaction_max_per_day", "调教每日次数", "num", ""],
    ["ransom_price_coeff", "赎身价格系数（0~1）", "num", "价格 = 魅力 × 系数 × 随机[0,3]"],
    ["ransom_cooldown_minutes", "赎身冷却（分钟）", "num", ""],
    ["ransom_max_per_day", "赎身每日次数", "num", ""],
  ]},
  {group: "礼物", items: [
    ["gift_max_quantity", "单次送礼数量上限", "num", ""],
    ["gift_daily_spend_limit", "每日送礼花费上限", "num", ""],
    ["gift_rank_days", "礼物榜统计天数", "num", ""],
  ]},
];
const GIFT_COLS = [["id", "ID"], ["name", "名称"], ["aliases", "别名（逗号分隔）"],
                   ["price", "价格"], ["charm", "魅力"]];
const EVENT_COLS = [["text", "事件文本"], ["coins_min", "金币下限"],
                    ["coins_max", "金币上限"], ["weight", "权重"]];
const INTERACTION_COLS = [["text", "互动文案"], ["tone", "语气（褒/贬/中性）"]];
const TONES = ["褒", "贬", "中性"];
let CFG = null;
let curTab = "players";
let logTimer = null;

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function getJSON(url) { return (await fetch(url)).json(); }
async function postJSON(url, body) {
  const r = await fetch(url, {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})});
  return {status: r.status, data: await r.json()};
}

function show(msg, isErr, id) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = isErr ? "err" : "ok";
}

function showTab(tab) {
  curTab = tab;
  for (const t of ["players", "logs", "config"]) {
    document.getElementById("page_" + t).classList.toggle("active", t === tab);
    document.getElementById("tabbtn_" + t).classList.toggle("active", t === tab);
  }
  if (tab === "players") loadPlayers();
  if (tab === "logs") loadLogs();
  if (tab === "config" && CFG === null) loadConfig();
}

async function refreshStatus() {
  try {
    const s = await getJSON("/api/status");
    const g = s.game, u = s.upstream || {}, gw = g.gateway || {}, ctx = gw.context || {};
    const dot = v => `<span class="dot ${v ? "ok" : "bad"}"></span>`;
    document.getElementById("statusbar").innerHTML = `
      <span>${dot(gw.connected)}网关</span>
      <span><span class="k">应用</span>${esc(gw.app_id || "-")}</span>
      <span><span class="k">offer</span>${gw.offers ?? 0}</span>
      <span>${dot(g.online)}微信在线</span>
      <span>${dot(g.listener_running)}OCR监听</span>
      <span>${dot(u.upstream_connected)}上游连接</span>
      <span><span class="k">群</span>${esc(g.group_key || "-")}</span>
      <span><span class="k">最新消息</span>${g.cursor}</span>
      <span><span class="k">队列</span>${g.queue_size}</span>
      <span><span class="k">已处理</span>${g.processed_total}</span>
      <span><span class="k">游戏侧错误</span>${esc(g.last_error || "无")}</span>
      <span><span class="k">网关错误</span>${esc(gw.last_error || "无")}</span>
      <span><span class="k">发送失败</span>${gw.sends_failed ?? 0}</span>`;
  } catch (e) { /* 服务未就绪时忽略 */ }
}

async function loadPlayers() {
  const sel = document.getElementById("groupsel");
  const wanted = sel.value;
  const s = await getJSON("/api/players" + (wanted ? "?group=" + encodeURIComponent(wanted) : ""));
  sel.innerHTML = "";
  for (const g of s.groups) {
    const o = document.createElement("option");
    o.value = o.textContent = g;
    if (g === s.group) o.selected = true;
    sel.appendChild(o);
  }
  const dl = document.getElementById("pnames");
  dl.innerHTML = "";
  const tb = document.getElementById("pbody");
  tb.innerHTML = "";
  let phantoms = 0;
  for (const p of s.players) {
    if (p.is_phantom) phantoms++;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="${p.is_phantom ? "phantom" : ""}">${esc(p.name)}${p.is_phantom ? "（影子）" : ""}</td>
      <td class="num">${p.coins}</td>
      <td class="num">${Number(p.charm).toFixed(1)}</td>
      <td class="${p.master ? "master" : ""}">${esc(p.master || "—")}</td>
      <td class="num">${p.signin_streak || 0}</td>
      <td>${esc((p.last_seen_at || "").replace("T", " ").slice(0, 19))}</td>
      <td><button class="ghost" data-name="${esc(p.name)}"
                  onclick="deletePlayer(this.dataset.name)">删除</button></td>`;
    tr.onclick = (ev) => {
      if (ev.target.tagName === "BUTTON") return;
      document.getElementById("pname").value = p.name;
    };
    tb.appendChild(tr);
    const o = document.createElement("option");
    o.value = p.name;
    dl.appendChild(o);
  }
  document.getElementById("phantomcount").textContent =
    "当前群影子玩家 " + phantoms + " 个";
}

function purgeChecked() {
  return document.getElementById("purgechk").checked;
}

async function deletePlayer(name) {
  const group = document.getElementById("groupsel").value;
  if (!confirm("确认删除玩家「" + name + "」？\\n其名下奴隶将自动恢复自由身" +
               (purgeChecked() ? "，且相关流水/礼物记录一并删除" : "") + "。")) return;
  const r = await postJSON("/api/players/delete",
    {group, name, purge_history: purgeChecked()});
  if (r.status !== 200) { show(r.data.error || "删除失败", true, "pmsg"); return; }
  const freed = r.data.released_slaves || 0;
  show(`已删除「${esc(name)}」` + (freed ? `，释放了 ${freed} 名奴隶` : ""), false, "pmsg");
  loadPlayers();
}

async function cleanPhantoms() {
  const group = document.getElementById("groupsel").value;
  const n = parseInt((document.getElementById("phantomcount").textContent.match(/\d+/) || [0])[0], 10);
  if (!n) { show("当前群没有影子玩家", false, "pmsg"); return; }
  if (!confirm("确认删除 " + n + " 个影子玩家？" +
               (purgeChecked() ? "\\n相关流水/礼物记录将一并删除。" : ""))) return;
  const r = await postJSON("/api/players/delete_phantoms",
    {group, purge_history: purgeChecked()});
  if (r.status !== 200) { show(r.data.error || "清理失败", true, "pmsg"); return; }
  show("已清理 " + r.data.deleted + " 个影子玩家", false, "pmsg");
  loadPlayers();
}

async function clearGroup() {
  const group = document.getElementById("groupsel").value;
  const typed = document.getElementById("cleargroup").value.trim();
  if (typed !== group) {
    show("确认文字与群标题不一致", true, "pmsg");
    return;
  }
  if (!confirm("确认清空群「" + group + "」的全部玩家数据？" +
               (purgeChecked() ? "\\n该群流水/礼物记录将一并删除。" : ""))) return;
  const r = await postJSON("/api/players/clear_group",
    {group, confirm: typed, purge_history: purgeChecked()});
  if (r.status !== 200) { show(r.data.error || "清空失败", true, "pmsg"); return; }
  show("已清空 " + r.data.players + " 个玩家", false, "pmsg");
  loadPlayers();
}

async function editPlayer() {
  const body = {group: document.getElementById("groupsel").value || undefined,
                name: document.getElementById("pname").value.trim(),
                action: document.getElementById("paction").value,
                amount: document.getElementById("pamount").value.trim()};
  if (!body.name) { show("请填写玩家名", true, "pmsg"); return; }
  const r = await postJSON("/api/players/edit", body);
  if (r.status !== 200) { show(r.data.error || "操作失败", true, "pmsg"); return; }
  const d = r.data;
  show(`已执行：${esc(d.name)} 当前金币 ${d.coins}，魅力 ${Number(d.charm).toFixed(1)}`, false, "pmsg");
  loadPlayers();
}

async function loadLogs() {
  const s = await getJSON("/api/logs?limit=300");
  const tb = document.getElementById("lbody");
  tb.innerHTML = [...s.events].reverse().map(e => {
    const detail = e.kind === "command" ? (e.detail || "") : (e.message || "");
    return `<tr>
      <td>${esc((e.ts || "").slice(0, 19))}</td>
      <td>${esc(e.kind)}</td>
      <td>${esc(e.group || "")}</td>
      <td>${esc(e.sender || "")}</td>
      <td>${esc(e.cmd || "")}</td>
      <td class="result">${esc(e.result || "")}</td>
      <td class="num">${e.cost_ms != null ? e.cost_ms : ""}</td>
      <td>${esc(detail)}</td></tr>`;
  }).join("");
}

async function loadConfig() {
  const r = await getJSON("/api/config");
  if (r.error) { show(r.error, true, "msg"); return; }
  CFG = r.data;
  document.getElementById("cfgpath").textContent = "｜ " + r.path;
  renderConfig();
}

function renderConfig() {
  const form = document.getElementById("form");
  form.innerHTML = "";
  for (const g of META) {
    const div = document.createElement("div");
    div.className = "group";
    div.style.cssText = "background:#141920;border:1px solid #2a313a;border-radius:8px;padding:14px;margin-bottom:14px";
    div.innerHTML = `<h2>${esc(g.group)}</h2>`;
    for (const [key, label, type, desc] of g.items) {
      const row = document.createElement("div");
      row.className = "row";
      let input;
      if (type === "bool") {
        input = `<input type="checkbox" id="f_${esc(key)}" ${CFG[key] ? "checked" : ""}>`;
      } else if (type === "json_text") {
        input = `<textarea id="f_${esc(key)}" rows="14"
                  style="width:100%;font-family:monospace">${esc(JSON.stringify(CFG[key], null, 2))}</textarea>`;
      } else if (type === "json") {
        input = `<input type="text" id="f_${esc(key)}" value='${esc(JSON.stringify(CFG[key]))}'>`;
      } else {
        input = `<input type="${type === "num" ? "number" : "text"}" step="any"
                  id="f_${esc(key)}" value="${esc(CFG[key])}">`;
      }
      row.innerHTML = `<label>${esc(label)}<div class="desc">${esc(desc)}</div></label>
                       <div>${input}</div>`;
      div.appendChild(row);
    }
    form.appendChild(div);
  }
  renderTable("gifts", "礼物目录（gifts）", GIFT_COLS);
  renderTable("work_events", "打工事件表（work_events）", EVENT_COLS);
  renderTable("slave_interactions", "调教互动表（slave_interactions）", INTERACTION_COLS);
}

function renderTable(key, title, cols) {
  const form = document.getElementById("form");
  const div = document.createElement("div");
  div.style.cssText = "background:#141920;border:1px solid #2a313a;border-radius:8px;padding:14px;margin-bottom:14px";
  const ths = cols.map(c => `<th>${esc(c[1])}</th>`).join("") + "<th></th>";
  div.innerHTML = `<h2>${esc(title)}</h2>
    <table><thead><tr>${ths}</tr></thead><tbody id="tb_${esc(key)}"></tbody></table>
    <button class="ghost" onclick="addRow('${key}')">+ 添加一行</button>`;
  form.appendChild(div);
  (CFG[key] || []).forEach(item => addRow(key, item));
}

function addRow(key, item) {
  const cols = key === "gifts" ? GIFT_COLS
             : key === "work_events" ? EVENT_COLS : INTERACTION_COLS;
  item = item || {};
  const tb = document.getElementById("tb_" + key);
  const tr = document.createElement("tr");
  tr.innerHTML = cols.map(([field, _]) => {
    if (key === "slave_interactions" && field === "tone") {
      const opts = TONES.map(t =>
        `<option value="${t}"${item.tone === t ? " selected" : ""}>${t}</option>`).join("");
      return `<td><select data-f="tone">${opts}</select></td>`;
    }
    let v = item[field];
    if (field === "aliases") v = (v || []).join(",");
    return `<td><input type="text" data-f="${esc(field)}"
             value="${esc(v == null ? "" : v)}"></td>`;
  }).join("") + `<td><button class="ghost" onclick="this.closest('tr').remove()">删除</button></td>`;
  tb.appendChild(tr);
}

function collect() {
  const data = JSON.parse(JSON.stringify(CFG));
  for (const g of META) {
    for (const [key, _label, type] of g.items) {
      const el = document.getElementById("f_" + key);
      if (type === "bool") { data[key] = el.checked; continue; }
      const v = el.value.trim();
      if (type === "json" || type === "json_text") {
        try { data[key] = JSON.parse(v); }
        catch (e) { throw new Error(key + " 不是合法 JSON：" + v); }
        continue;
      }
      if (type === "num") {
        if (v === "" || isNaN(Number(v))) throw new Error(key + " 必须是数字");
        data[key] = Number(v);
        continue;
      }
      data[key] = v;
    }
  }
  const collectTable = (key, convert) => {
    const out = [];
    document.getElementById("tb_" + key).querySelectorAll("tr").forEach(tr => {
      const obj = {};
      tr.querySelectorAll("input,select").forEach(inp => { obj[inp.dataset.f] = inp.value.trim(); });
      out.push(convert(obj));
    });
    return out;
  };
  data.gifts = collectTable("gifts", o => ({
    id: o.id, name: o.name,
    aliases: o.aliases.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    price: Number(o.price), charm: Number(o.charm)}));
  data.work_events = collectTable("work_events", o => ({
    text: o.text, coins_min: Number(o.coins_min),
    coins_max: Number(o.coins_max), weight: Number(o.weight)}));
  data.slave_interactions = collectTable("slave_interactions", o => ({
    text: o.text, tone: o.tone}));
  return data;
}

async function saveConfig() {
  let data;
  try { data = collect(); }
  catch (e) { show("保存失败：" + e.message, true, "msg"); return; }
  const r = await postJSON("/api/config/save", {data});
  if (r.status !== 200) { show("保存失败：" + (r.data.error || ""), true, "msg"); return; }
  if (r.data.hot_reload_error) {
    show("已保存到文件，但热加载失败：" + r.data.hot_reload_error +
         "。重启 game.main 后生效。", true, "msg");
    return;
  }
  const rr = r.data.restart_required || [];
  if (rr.length) {
    show("已保存并热加载生效；以下参数需重启：" + rr.join("、"), false, "msg");
  } else {
    show("已保存并热加载生效（改动 " + (r.data.changed || []).length + " 项）",
         false, "msg");
  }
}

showTab("players");
refreshStatus();
setInterval(refreshStatus, 3000);
setInterval(() => { if (curTab === "logs") loadLogs(); }, 5000);
</script>
</body>
</html>
"""


def make_reload_callback(engine: Engine, queue, loop, log):
    """返回热加载回调：写入配置文件后调用，把新配置原子替换进运行时对象。

    在事件循环线程内执行替换（经 call_soon_threadsafe 调度），
    保证热加载发生在两条指令之间；回调阻塞至替换完成（最多 5 秒）。
    """
    from .config import RESTART_KEYS

    def reload(data: dict) -> dict:
        from .config import Config
        new_cfg = Config(data)
        old = engine.cfg
        changed = sorted(k for k in new_cfg.as_dict() if old.get(k) != new_cfg.get(k))
        restart_required = sorted(k for k in RESTART_KEYS if old.get(k) != new_cfg.get(k))
        done = threading.Event()
        errors: list[str] = []

        def apply() -> None:
            try:
                engine.apply_config(new_cfg)
                queue.cfg = new_cfg
                engine.add_event(kind="config_reloaded", changed=len(changed),
                                 restart_required=restart_required)
                log.info("config hot-reloaded: changed=%s restart_required=%s",
                         changed, restart_required)
            except Exception as e:  # pragma: no cover
                errors.append(str(e))
            finally:
                done.set()

        loop.call_soon_threadsafe(apply)
        if not done.wait(5):
            raise RuntimeError("热加载超时")
        if errors:
            raise RuntimeError(errors[0])
        return {"changed": changed, "restart_required": restart_required}

    return reload


def build_console_handler(engine: Engine, cfg: Config, cfg_path: str,
                          reload_callback=None):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _page(self, text: str) -> None:
            raw = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return {}

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if path == "/":
                self._page(CONSOLE_PAGE)
            elif path == "/health":
                self._json(200, engine.stats())
            elif path == "/api/status":
                self._json(200, {"game": engine.stats(),
                                 "upstream": engine.last_upstream_context,
                                 "cfg_path": str(Path(cfg_path).resolve())})
            elif path == "/api/players":
                group = query.get("group") or engine.tracker.key
                groups = engine.store.list_groups()
                players = engine.store.list_players(group) if group else []
                self._json(200, {"groups": groups, "group": group,
                                 "players": players})
            elif path == "/api/logs":
                try:
                    limit = int(query.get("limit", 200))
                except ValueError:
                    limit = 200
                self._json(200, {"events": engine.get_recent_events(limit)})
            elif path == "/api/config":
                try:
                    resolved, data = read_config_file(cfg_path)
                    self._json(200, {"path": resolved, "data": data})
                except Exception as e:
                    self._json(500, {"error": str(e)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            body = self._body()
            if self.path == "/api/players/edit":
                self._player_edit(body)
            elif self.path == "/api/players/delete":
                self._player_delete(body)
            elif self.path == "/api/players/delete_phantoms":
                self._phantom_delete(body)
            elif self.path == "/api/players/clear_group":
                self._clear_group(body)
            elif self.path == "/api/config/save":
                data = body.get("data")
                if not isinstance(data, dict):
                    self._json(400, {"error": "data must be an object"})
                    return
                try:
                    write_config_file(cfg_path, data)
                except ConfigError as e:
                    self._json(400, {"error": f"配置校验失败：{e}"})
                except Exception as e:
                    self._json(400, {"error": str(e)})
                else:
                    if reload_callback is not None:
                        try:
                            info = reload_callback(data)
                        except Exception as e:
                            self._json(200, {"status": "saved",
                                             "hot_reload_error": str(e)})
                            return
                        self._json(200, {"status": "saved", **info})
                    else:
                        self._json(200, {"status": "saved"})
            else:
                self._json(404, {"error": "not found"})

        def _player_edit(self, body: dict) -> None:
            group = (body.get("group") or engine.tracker.key or "").strip()
            name = (body.get("name") or "").strip()
            action = body.get("action")
            if not group or not name:
                self._json(400, {"error": "group and name required"})
                return
            try:
                ts = fmt_iso(engine.clock())
                if action == "add_coins":
                    amount = int(body.get("amount"))
                    coins = engine.store.admin_add_coins(group, name, amount, ts)
                    p = engine.store.admin_get_player(group, name)
                    engine.add_event(kind="admin", group=group, name=name,
                                     action=action, amount=amount, result="ok")
                    self._json(200, p | {"added": amount})
                elif action == "set_charm":
                    value = float(body.get("amount"))
                    engine.store.admin_set_charm(group, name, value)
                    p = engine.store.admin_get_player(group, name)
                    engine.add_event(kind="admin", group=group, name=name,
                                     action=action, amount=value, result="ok")
                    self._json(200, p)
                elif action == "release_slave":
                    engine.store.admin_clear_master(group, name)
                    p = engine.store.admin_get_player(group, name)
                    engine.add_event(kind="admin", group=group, name=name,
                                     action=action, result="ok")
                    self._json(200, p)
                else:
                    self._json(400, {"error": f"unknown action: {action}"})
            except (LookupError, ValueError) as e:
                self._json(400, {"error": str(e)})

        def _player_delete(self, body: dict) -> None:
            group = (body.get("group") or engine.tracker.key or "").strip()
            name = (body.get("name") or "").strip()
            purge = bool(body.get("purge_history"))
            if not group or not name:
                self._json(400, {"error": "group and name required"})
                return
            try:
                result = engine.store.delete_player(group, name, purge)
            except (LookupError, ValueError) as e:
                self._json(400, {"error": str(e)})
                return
            engine.add_event(kind="admin", group=group, name=name,
                             action="delete_player", result="ok",
                             released_slaves=result["released_slaves"],
                             purged_history=purge)
            self._json(200, {"status": "deleted"} | result)

        def _phantom_delete(self, body: dict) -> None:
            group = (body.get("group") or engine.tracker.key or "").strip()
            purge = bool(body.get("purge_history"))
            if not group:
                self._json(400, {"error": "group required"})
                return
            deleted = engine.store.delete_phantom_players(group, purge)
            engine.add_event(kind="admin", group=group, action="delete_phantoms",
                             result="ok", deleted=deleted, purged_history=purge)
            self._json(200, {"status": "deleted", "deleted": deleted})

        def _clear_group(self, body: dict) -> None:
            group = (body.get("group") or engine.tracker.key or "").strip()
            purge = bool(body.get("purge_history"))
            confirm = (body.get("confirm") or "").strip()
            if not group:
                self._json(400, {"error": "group required"})
                return
            if confirm != group:
                self._json(400, {"error": "确认文字与群标题不一致"})
                return
            result = engine.store.clear_group_data(group, purge)
            engine.add_event(kind="admin", group=group, action="clear_group",
                             result="ok", players=result["players"],
                             purged_history=purge)
            self._json(200, {"status": "cleared"} | result)

        def log_message(self, fmt, *args):
            pass

    return Handler


def build_console_server(engine: Engine, cfg: Config, cfg_path: str,
                         reload_callback=None) -> ThreadingHTTPServer:
    handler = build_console_handler(engine, cfg, cfg_path, reload_callback)
    server = ThreadingHTTPServer((cfg.get("web_host"), cfg.get("health_port")), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
