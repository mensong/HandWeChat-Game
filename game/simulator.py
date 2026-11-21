"""本地测试模拟器：不经微信收发服务，直接向游戏引擎投喂消息。

启动：
    python -m game.simulator --config config/game_config.json --port 8002
页面：
    http://127.0.0.1:8002/
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import (Config, ConfigError, load_config, read_config_file,
                     write_config_file)
from .engine import Engine
from .rng import Rng
from .store import Store
from .util import fmt_iso, make_clock, normalize_title


class SimClock:
    def __init__(self, tz_name: str):
        self.tz = make_clock(tz_name).tz
        self.t = make_clock(tz_name)()

    def __call__(self):
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)

log = logging.getLogger("game.sim")

# 模拟器默认放开指令间隔/去重/帮助冷却，方便连续测试；
# 打工/反抗冷却、每日额度保持真实，可用页面上的时间推进来测。
RELAXED = {
    "command_rate_limit_seconds": 0,
    "help_cooldown_seconds": 0,
    "usage_hint_cooldown_seconds": 0,
    "dedupe_window_seconds": 0.001,
}

SIM_GROUP_TITLE = "模拟群(10)"

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>微信群游戏模拟器</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Microsoft YaHei", system-ui, sans-serif;
       background: #111418; color: #d8dde3; }
header { padding: 10px 16px; background: #1a1f26; border-bottom: 1px solid #2a313a;
         display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
header h1 { font-size: 16px; margin: 0; color: #7fb2ff; }
header .t { font-variant-numeric: tabular-nums; color: #f0c674; }
header button, main button { background: #2a313a; color: #d8dde3; border: 1px solid #3a434e;
         border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 13px; }
header button:hover, main button:hover { background: #3a434e; }
header input { width: 70px; background: #0f1216; color: #d8dde3; border: 1px solid #3a434e;
               border-radius: 4px; padding: 4px 6px; font-size: 13px; }
main { display: grid; grid-template-columns: 340px 1fr 340px; gap: 12px; padding: 12px;
       height: calc(100vh - 58px); }
section { background: #1a1f26; border: 1px solid #2a313a; border-radius: 8px;
          padding: 12px; overflow-y: auto; }
section h2 { font-size: 14px; margin: 0 0 10px; color: #7fb2ff; }
label { font-size: 13px; color: #9aa3ad; display: block; margin: 8px 0 4px; }
input[type=text], textarea { width: 100%; background: #0f1216; color: #d8dde3;
        border: 1px solid #3a434e; border-radius: 4px; padding: 6px 8px; font-size: 14px; }
textarea { height: 60px; resize: vertical; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.chips button { font-size: 12px; padding: 3px 8px; }
#sendbtn { width: 100%; margin-top: 10px; padding: 8px; font-size: 15px;
           background: #2f6fdb; border-color: #2f6fdb; color: #fff; }
#sendbtn:hover { background: #3d7de8; }
.dbgrow { margin-top: 16px; border-top: 1px dashed #3a434e; padding-top: 10px;
          display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dbgrow input { width: 90px; background: #0f1216; color: #d8dde3; border: 1px solid #3a434e;
                border-radius: 4px; padding: 4px 6px; font-size: 13px; }
.entry { margin-bottom: 14px; border-bottom: 1px solid #232a32; padding-bottom: 10px; }
.entry .who { font-size: 13px; color: #7fd18b; }
.entry .content { background: #243040; border-radius: 6px; padding: 6px 10px;
                  margin: 4px 0; font-size: 14px; white-space: pre-wrap; }
.entry .reply { background: #2b2440; border-radius: 6px; padding: 6px 10px;
                margin: 4px 0 0 24px; font-size: 14px; white-space: pre-wrap; color: #cdb8ff; }
.entry .reply.none { color: #6a737d; background: transparent; margin-left: 24px; font-size: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid #232a32; }
th { color: #9aa3ad; font-weight: normal; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.master { color: #f0c674; }
.phantom { color: #6a737d; }
.hint { font-size: 12px; color: #6a737d; margin-top: 10px; line-height: 1.6; }
</style>
</head>
<body>
<header>
  <h1>微信群游戏模拟器</h1>
  <span class="t" id="simtime"></span>
  <span>
    <button onclick="advance(60)">+1分</button>
    <button onclick="advance(600)">+10分</button>
    <button onclick="advance(1800)">+30分</button>
    <button onclick="advance(3600)">+1小时</button>
    <button onclick="advance(86400)">+1天</button>
  </span>
  <span>
    <input id="advmin" placeholder="分钟" type="text">
    <button onclick="advanceCustom()">推进</button>
  </span>
  <button onclick="resetAll()">重置全部数据</button>
  <a href="/config" style="background:#2a313a;color:#7fb2ff;border:1px solid #3a434e;border-radius:4px;padding:4px 10px;text-decoration:none;font-size:13px;">配置可视化</a>
</header>
<main>
  <section>
    <h2>发消息</h2>
    <label>发信人昵称</label>
    <input type="text" id="sender" list="senders" placeholder="例如：张三">
    <datalist id="senders"></datalist>
    <label>消息内容（支持 # 前缀、全角＠）</label>
    <textarea id="content" placeholder="例如：购买奴隶@李四"></textarea>
    <div class="chips" id="chips"></div>
    <button id="sendbtn" onclick="sendMsg()">发 送</button>
    <div class="dbgrow">
      <b>调试：</b>给
      <input id="dbgname" placeholder="玩家">
      加
      <input id="dbgamt" placeholder="金币数">
      <button onclick="debugCoins()">发放</button>
    </div>
    <p class="hint">模拟器已放开指令间隔/去重/帮助冷却，方便连续点击；
打工/反抗/调教的冷却与每日额度仍真实生效，可用上方时间推进来测。
数据保存在独立的模拟数据库，不影响正式数据。</p>
  </section>
  <section id="log">
    <h2>消息记录</h2>
    <div id="loglist"></div>
  </section>
  <section id="state">
    <h2>玩家状态</h2>
    <table>
      <thead><tr><th>玩家</th><th>金币</th><th>魅力</th><th>主人</th><th>连签</th></tr></thead>
      <tbody id="pbody"></tbody>
    </table>
    <p class="hint" id="groupinfo"></p>
  </section>
</main>
<script>
const CHIPS = ["签到","我的金币","金币榜","我的魅力","魅力榜","礼物列表","礼物榜",
               "我的奴隶","奴隶打工","调教所有奴隶","我要自由","奴隶系统",
               "金币系统","魅力系统","礼物系统"];
const chips = document.getElementById("chips");
CHIPS.forEach(c => {
  const b = document.createElement("button");
  b.textContent = c;
  b.onclick = () => { document.getElementById("content").value = c; };
  chips.appendChild(b);
});

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function post(url, body) {
  const r = await fetch(url, {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})});
  return r.json();
}

async function refresh() {
  const s = await (await fetch("/api/state")).json();
  document.getElementById("simtime").textContent = "⏱ " + s.now;
  document.getElementById("groupinfo").textContent =
    "群: " + s.group_key + " ｜ 数据库: " + s.db_path;
  const dl = document.getElementById("senders");
  dl.innerHTML = "";
  s.players.forEach(p => {
    const o = document.createElement("option");
    o.value = p.name;
    dl.appendChild(o);
  });
  const tb = document.getElementById("pbody");
  tb.innerHTML = "";
  s.players.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="${p.is_phantom ? "phantom" : ""}">${esc(p.name)}${p.is_phantom ? "（影子）" : ""}</td>
      <td class="num">${p.coins}</td>
      <td class="num">${Number(p.charm).toFixed(1)}</td>
      <td class="${p.master ? "master" : ""}">${esc(p.master || "—")}</td>
      <td class="num">${p.signin_streak || 0}</td>`;
    tb.appendChild(tr);
  });
  const ll = document.getElementById("loglist");
  ll.innerHTML = s.log.map(e => `
    <div class="entry">
      <div class="who">${esc(e.sender)} <span style="color:#6a737d">${esc(e.ts)}</span></div>
      <div class="content">${esc(e.content)}</div>
      ${e.replies.length
        ? e.replies.map(r => `<div class="reply">${esc(r)}</div>`).join("")
        : `<div class="reply none">（无回复：非指令或被忽略）</div>`}
    </div>`).reverse().join("");
}

async function sendMsg() {
  const sender = document.getElementById("sender").value.trim();
  const content = document.getElementById("content").value.trim();
  if (!sender || !content) { alert("请填写发信人和消息内容"); return; }
  await post("/api/send", {sender, content});
  document.getElementById("content").value = "";
  refresh();
}

async function advance(seconds) {
  await post("/api/time", {seconds});
  refresh();
}

async function advanceCustom() {
  const m = parseFloat(document.getElementById("advmin").value);
  if (!m || m <= 0) { alert("请输入大于 0 的分钟数"); return; }
  await post("/api/time", {seconds: Math.round(m * 60)});
  refresh();
}

async function debugCoins() {
  const name = document.getElementById("dbgname").value.trim();
  const amt = parseInt(document.getElementById("dbgamt").value, 10);
  if (!name || !amt) { alert("请填写玩家和金币数"); return; }
  const r = await post("/api/debug/coins", {name, amount: amt});
  alert("发放完成，" + name + " 当前金币 " + r.coins);
  refresh();
}

async function resetAll() {
  if (!confirm("确认清空全部模拟数据（玩家、金币、奴隶关系、记录）？")) return;
  await post("/api/reset", {});
  refresh();
}

document.getElementById("content").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); }
});
refresh();
</script>
</body>
</html>
"""


CONFIG_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>游戏配置可视化</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Microsoft YaHei", system-ui, sans-serif;
       background: #111418; color: #d8dde3; }
header { padding: 10px 16px; background: #1a1f26; border-bottom: 1px solid #2a313a;
         display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
         position: sticky; top: 0; z-index: 5; }
header h1 { font-size: 16px; margin: 0; color: #7fb2ff; }
header .path { color: #6a737d; font-size: 12px; }
header button, header a { background: #2f6fdb; color: #fff; border: 1px solid #2f6fdb;
         border-radius: 4px; padding: 5px 14px; cursor: pointer; font-size: 13px;
         text-decoration: none; }
header button:hover { background: #3d7de8; }
header button.ghost, header a.ghost { background: #2a313a; border-color: #3a434e; color: #d8dde3; }
#msg { font-size: 13px; }
#msg.ok { color: #7fd18b; }
#msg.err { color: #ff8a80; }
main { max-width: 1100px; margin: 0 auto; padding: 14px; }
.group { background: #1a1f26; border: 1px solid #2a313a; border-radius: 8px;
         padding: 14px; margin-bottom: 14px; }
.group h2 { font-size: 15px; margin: 0 0 12px; color: #7fb2ff; }
.row { display: grid; grid-template-columns: 260px 1fr; gap: 10px;
       align-items: center; margin-bottom: 8px; }
.row label { font-size: 13px; color: #c3cad2; }
.row .desc { font-size: 11px; color: #6a737d; }
input[type=text], input[type=number] { width: 100%; background: #0f1216; color: #d8dde3;
        border: 1px solid #3a434e; border-radius: 4px; padding: 6px 8px; font-size: 13px; }
input[type=checkbox] { transform: scale(1.3); }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
th { text-align: left; color: #9aa3ad; font-weight: normal; padding: 4px 6px; }
td { padding: 3px 6px; border-top: 1px solid #232a32; }
td input { padding: 4px 6px; }
td button { background: #5a2a2a; color: #ff8a80; border: 1px solid #7a3a3a; border-radius: 4px;
            padding: 3px 8px; cursor: pointer; font-size: 12px; }
.addbtn { margin-top: 8px; background: #2a313a; color: #d8dde3; border: 1px solid #3a434e;
          border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 13px; }
.hint { font-size: 12px; color: #6a737d; line-height: 1.7; }
</style>
</head>
<body>
<header>
  <h1>游戏配置可视化</h1>
  <span class="path" id="cfgpath"></span>
  <button onclick="saveAll()">保存到配置文件</button>
  <button class="ghost" onclick="location.reload()">重新加载</button>
  <a class="ghost" href="/">返回模拟器</a>
  <span id="msg"></span>
</header>
<main>
  <p class="hint">保存前会使用游戏校验器检查全部取值，非法配置不会被写入。
修改配置文件后，正式服务需重启生效；正在运行的模拟器沿用启动时的值
（其中指令间隔/去重/帮助冷却四项在模拟器内始终被放宽）。</p>
  <div id="form"></div>
</main>
<script>
const META = [
  {group: "服务与接口", items: [
    ["gateway_url", "网关地址", "text", "正式服务连接网关使用"],
    ["gateway_app_id", "网关应用 ID", "text", "需与网关配置 apps[].id 一致"],
    ["gateway_token", "网关 token", "text", "网关配置 apps[].token；留空表示不校验"],
    ["gateway_rules", "网关规则（JSON）", "json", "null = 按指令表、别名和自动回复自动生成；非空数组则手写覆盖"],
    ["health_port", "本服务健康检查端口", "num", ""],
    ["timezone", "时区", "text", "本机缺时区数据时按 UTC+8 处理"],
  ]},
  {group: "消息处理与限流", items: [
    ["allow_hash_prefix", "允许 # 前缀", "bool", "#签到 等价于 签到"],
    ["ignore_senders", "忽略的发送者", "json", "这些昵称的消息一律丢弃"],
    ["dedupe_window_seconds", "同内容去重窗口（秒）", "num", ""],
    ["command_rate_limit_seconds", "单用户指令间隔（秒）", "num", ""],
    ["help_cooldown_seconds", "帮助指令冷却（秒）", "num", "四个 ×系统 指令"],
    ["usage_hint_cooldown_seconds", "用法提示冷却（秒）", "num", ""],
    ["command_aliases", "指令别名", "json", '如 {"购买奴隶":["购买","买下"]}'],
    ["reply_max_chars", "单条回复上限（字符）", "num", "超长自动拆条"],
  ]},
  {group: "自动回复", items: [
    ["bot_name", "机器人昵称", "text", "配置中所有字符串可用 {bot} 引用；pattern 内自动转义"],
    ["auto_replies", "回复规则（JSON 数组）", "json_text", '每项：name 名称、pattern 正则、replies 文案（字符串或数组）、cooldown_seconds 冷却、cooldown_key 冷却键（默认 {sender}）、enabled 启用、allow_ignored_senders 允许系统行；文案支持 {sender} {bot} 与 {msg1}..{msgN}'],
  ]},
  {group: "发送限速", items: [
    ["send_max_per_minute", "每分钟最多发送（≤20）", "num", ""],
    ["send_min_interval_ms", "两条发送最小间隔（毫秒）", "num", ""],
    ["send_queue_max", "发送队列上限", "num", "满时丢弃回复并记日志"],
  ]},
  {group: "群识别", items: [
    ["allowed_groups", "允许的群标题（白名单）", "json", "空数组 = 允许所有群"],
    ["group_title_stable_seconds", "群标题稳定窗口（秒）", "num", ""],
  ]},
  {group: "玩家与金币", items: [
    ["initial_coins", "新玩家初始金币", "num", ""],
    ["auto_create_target", "目标不存在时自动创建影子玩家", "bool", "关闭则回复未找到玩家"],
    ["signin_base_reward", "签到基础奖励", "num", ""],
    ["signin_streak_step", "连签每日加成", "num", ""],
    ["signin_max_reward", "签到奖励上限", "num", ""],
    ["chat_coins_per_message", "每条消息金币奖励", "num", "0=关闭聊天收入"],
    ["chat_coins_daily_cap", "聊天收入每日上限", "num", "0=不设上限"],
    ["transfer_tax_rate", "转账手续费率（0~1）", "num", "向上取整"],
    ["transfer_daily_limit", "每日转账转出上限（金币）", "num", ""],
  ]},
  {group: "魅力", items: [
    ["charm_base", "基础魅力值", "num", "衰减下限"],
    ["charm_decay_period_days", "衰减周期（天）", "num", ""],
    ["charm_decay_rate", "每周期衰减比例（0~1）", "num", "只衰减超出基础值部分"],
  ]},
  {group: "奴隶", items: [
    ["max_slaves", "每主人奴隶上限", "num", ""],
    ["slave_price_coeff", "购买价格系数", "num", "价格 = 魅力 × 系数 × 随机系数"],
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
    ["rebel_master_multipliers", "主人随机倍率列表", "json", "等概率抽取"],
    ["rebel_slave_multipliers", "奴隶随机倍率列表", "json", "等概率抽取"],
    ["rebel_loot_max", "反抗成功抢走上限（金币）", "num", ""],
    ["rebel_ransom_max", "赎金/上缴上限（金币）", "num", ""],
    ["rebel_compensation_max", "良心发现补贴上限（金币）", "num", ""],
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
    ["gift_daily_spend_limit", "每日送礼花费上限（金币）", "num", ""],
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

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function load() {
  const r = await fetch("/api/config").then(x => x.json());
  if (r.error) { show(r.error, true); return; }
  CFG = r.data;
  document.getElementById("cfgpath").textContent = "文件：" + r.path;
  render();
}

function render() {
  const form = document.getElementById("form");
  form.innerHTML = "";
  for (const g of META) {
    const div = document.createElement("div");
    div.className = "group";
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
  renderTable("gifts", "礼物目录", GIFT_COLS);
  renderTable("work_events", "打工事件表", EVENT_COLS);
  renderTable("slave_interactions", "调教互动表", INTERACTION_COLS);
}

function renderTable(key, title, cols) {
  const form = document.getElementById("form");
  const div = document.createElement("div");
  div.className = "group";
  const ths = cols.map(c => `<th>${esc(c[1])}</th>`).join("") + "<th></th>";
  div.innerHTML = `<h2>${esc(title)}（${key}）</h2>
    <table><thead><tr>${ths}</tr></thead><tbody id="tb_${esc(key)}"></tbody></table>
    <button class="addbtn" onclick="addRow('${key}')">+ 添加一行</button>`;
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
      return `<td><select data-k="${esc(key)}" data-f="tone">${opts}</select></td>`;
    }
    let v = item[field];
    if (field === "aliases") v = (v || []).join(",");
    return `<td><input type="text" data-k="${esc(key)}" data-f="${esc(field)}"
             value="${esc(v == null ? "" : v)}"></td>`;
  }).join("") + `<td><button onclick="this.closest('tr').remove()">删除</button></td>`;
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
        data[key] = Number.isInteger(CFG[key]) ? Number(v) : Number(v);
        continue;
      }
      data[key] = v;
    }
  }
  data.gifts = collectTable("gifts", GIFT_COLS, row => {
    return { id: row.id, name: row.name,
             aliases: row.aliases.split(/[,，]/).map(s => s.trim()).filter(Boolean),
             price: Number(row.price), charm: Number(row.charm) };
  });
  data.work_events = collectTable("work_events", EVENT_COLS, row => {
    return { text: row.text, coins_min: Number(row.coins_min),
             coins_max: Number(row.coins_max), weight: Number(row.weight) };
  });
  data.slave_interactions = collectTable("slave_interactions", INTERACTION_COLS, row => {
    return { text: row.text, tone: row.tone };
  });
  return data;
}

function collectTable(key, cols, convert) {
  const out = [];
  const rows = document.getElementById("tb_" + key).querySelectorAll("tr");
  rows.forEach(tr => {
    const obj = {};
    tr.querySelectorAll("input,select").forEach(inp => { obj[inp.dataset.f] = inp.value.trim(); });
    out.push(convert(obj));
  });
  return out;
}

function show(text, isErr) {
  const el = document.getElementById("msg");
  el.textContent = text;
  el.className = isErr ? "err" : "ok";
}

async function saveAll() {
  let data;
  try { data = collect(); }
  catch (e) { show("保存失败：" + e.message, true); return; }
  const r = await fetch("/api/config/save", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({data})}).then(x => x.json());
  if (r.error) { show("保存失败：" + r.error, true); return; }
  show("已保存到配置文件（正式服务重启后生效）", false);
}

load();
</script>
</body>
</html>
"""


class ReplyCollector:
    def __init__(self):
        self.replies: list[str] = []

    def enqueue(self, text: str) -> bool:
        self.replies.append(text)
        return True


class Simulator:
    def __init__(self, cfg: Config, db_path: str, cfg_path: str = ""):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.db_path = db_path
        self.lock = threading.Lock()
        self.log_entries: list[dict] = []
        self._rebuild(wipe=False)

    def _rebuild(self, wipe: bool = False) -> None:
        if getattr(self, "store", None) is not None:
            self.store.close()
        if wipe and self.db_path != ":memory:" and os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.store = Store(self.db_path)
        clock = SimClock(self.cfg.get("timezone"))
        self.clock = clock
        self.rng = Rng()
        self.collector = ReplyCollector()
        self.engine = Engine(self.cfg, self.store, clock, self.rng, log)
        self.engine.attach_sender(self.collector)
        self.engine.handle_health({"chat_title": SIM_GROUP_TITLE,
                                   "online": True, "listener_running": True})
        self.counter = itertools.count(1)
        self.log_entries = []

    @property
    def group(self) -> str:
        return normalize_title(SIM_GROUP_TITLE)

    def send(self, sender: str, content: str) -> list[str]:
        with self.lock:
            self.clock.advance(1)  # 每条消息推进 1 秒，模拟自然间隔
            now = self.clock()
            self.collector.replies = []
            n = next(self.counter)
            self.engine.handle_message({
                "id": str(n), "cursor": n, "sender": sender,
                "content": content, "received_at": fmt_iso(now),
            })
            replies = list(self.collector.replies)
            self.log_entries.append({
                "ts": fmt_iso(now), "sender": sender,
                "content": content, "replies": replies,
            })
            self.log_entries = self.log_entries[-200:]
            return replies

    def advance(self, seconds: float) -> str:
        with self.lock:
            self.clock.advance(seconds)
            return fmt_iso(self.clock())

    def debug_coins(self, name: str, amount: int) -> int:
        with self.lock:
            ts = fmt_iso(self.clock())
            with self.store.transaction():
                p = self.store.get_or_create_target(
                    self.group, name, ts, self.cfg.get("initial_coins"),
                    self.cfg.get("charm_base"), True)
                p = self.store.get_player(self.group, name)
                return self.store.adjust_coins(self.group, name, amount, "debug", None, ts)

    def reset(self) -> None:
        with self.lock:
            self._rebuild(wipe=True)

    def state(self) -> dict:
        with self.lock:
            return {
                "now": fmt_iso(self.clock()),
                "group_key": self.engine.tracker.key,
                "db_path": str(Path(self.db_path).resolve()),
                "players": self.store.list_players(self.group),
                "log": list(self.log_entries),
            }


def build_handler(sim: Simulator):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
            if self.path == "/":
                raw = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif self.path == "/config":
                raw = CONFIG_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif self.path == "/api/state":
                self._json(200, sim.state())
            elif self.path == "/api/config":
                try:
                    path, data = read_config_file(sim.cfg_path)
                    self._json(200, {"path": path, "data": data})
                except Exception as e:
                    self._json(500, {"error": str(e)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            body = self._body()
            if self.path == "/api/send":
                sender = (body.get("sender") or "").strip()
                content = (body.get("content") or "").strip()
                if not sender or not content:
                    self._json(400, {"error": "sender and content required"})
                    return
                self._json(200, {"replies": sim.send(sender, content)})
            elif self.path == "/api/time":
                seconds = float(body.get("seconds") or 0)
                if seconds <= 0:
                    self._json(400, {"error": "seconds must be > 0"})
                    return
                self._json(200, {"now": sim.advance(seconds)})
            elif self.path == "/api/reset":
                sim.reset()
                self._json(200, {"status": "reset"})
            elif self.path == "/api/debug/coins":
                name = (body.get("name") or "").strip()
                try:
                    amount = int(body.get("amount"))
                except (TypeError, ValueError):
                    amount = 0
                if not name or amount == 0:
                    self._json(400, {"error": "name and amount required"})
                    return
                self._json(200, {"coins": sim.debug_coins(name, amount)})
            elif self.path == "/api/config/save":
                data = body.get("data")
                if not isinstance(data, dict):
                    self._json(400, {"error": "data must be an object"})
                    return
                try:
                    write_config_file(sim.cfg_path, data)
                    self._json(200, {"status": "saved"})
                except ConfigError as e:
                    self._json(400, {"error": f"配置校验失败：{e}"})
                except Exception as e:
                    self._json(400, {"error": str(e)})
            else:
                self._json(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            pass

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="游戏本地模拟器")
    parser.add_argument("--config", default="config/game_config.json")
    parser.add_argument("--db", default="data/sim_game.db")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--log-dir", default="data/logs")
    args = parser.parse_args(argv)

    Path(args.log_dir).mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(Path(args.log_dir) / "simulator.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    log.addHandler(console)

    cfg = load_config(args.config)
    data = cfg.as_dict()
    data.update(RELAXED)
    sim = Simulator(Config(data), args.db, cfg_path=args.config)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(sim))
    log.info("simulator listening on http://127.0.0.1:%d/ (db=%s)", args.port, args.db)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        sim.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
