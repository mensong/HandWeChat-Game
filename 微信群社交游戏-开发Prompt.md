# 微信群社交游戏开发 Prompt
## 「奴隶系统 × 魅力系统 × 礼物系统 × 金币系统」

> 版本：v1.0（2026-11-14）
> 依赖：`接口方案.md` 中定义的 HandWeChat HTTP API
> 用途：把本文完整交给编码 AI / 工程师，作为实现该游戏服务的唯一需求规格。
> 编码要求：先按本文实现，不要自行增加未定义的玩法；所有可调参数放入配置文件。

---

# 一、你的角色与交付目标

你是一名资深 Python 后端工程师。请实现一个独立运行的「微信群社交游戏服务」：

1. 它不直接操作微信，只通过 `接口方案.md` 中的 HTTP API 读取当前聊天消息、发送纯文本回复。
2. 它维护一套持久化的游戏状态（玩家、金币、魅力、奴隶关系、礼物记录、冷却与流水）。
3. 它只响应用户明确发送的游戏指令；群里的普通聊天消息一律静默忽略。
4. 它必须能够在 OCR 识别存在噪声、消息重复、微信重启、API 重启的情况下稳定运行。

交付物：

- 可运行的 Python 服务（建议 Python 3.11+）。
- SQLite 数据库及建表逻辑。
- 完整的 `game_config.json` 配置文件。
- 单元测试 + 接口联调测试。
- 一份 README，说明启动方式、配置项、已知限制。

---

# 二、外部接口能力与硬约束

## 2.1 可用的 HandWeChat API

基础地址：`http://127.0.0.1:8000`（可配置）。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/health` | 查询微信在线、OCR 监听、当前聊天标题、队列状态 |
| POST | `/api/v1/attach` | 微信重启后重新附加 |
| POST | `/api/v1/listener/start` | 启动 OCR 监听 |
| POST | `/api/v1/listener/stop` | 停止 OCR 监听 |
| GET | `/api/v1/messages?cursor=0&limit=100&timeout=0` | 拉取当前聊天的新消息 |
| POST | `/api/v1/send` | 发送纯文本，返回 `task_id` |
| GET | `/api/v1/send/{task_id}` | 查询发送任务结果 |

消息结构：

```json
{
  "id": "42",
  "cursor": 42,
  "sender": "张三",
  "content": "收到",
  "received_at": "2026-11-13T12:01:02+08:00"
}
```

## 2.2 必须遵守的硬约束

1. **只处理当前打开的聊天。** API 不具备切换聊天的能力，也不维护聊天列表。
2. **不读取微信控件树，不使用 UIA。** 只依赖 HTTP API。
3. **只支持纯文本。** 不处理图片、文件、语音、引用、小程序、表情包。
4. **发送必须限速。** API 自身限制 20 条/分钟；本服务出站上限设为 15 条/分钟，且两条之间至少间隔 1.5 秒。
5. **不能假成功。** 发送失败、任务失败、微信离线都要记录日志，不能当作已发送。
6. **不做聊天切换、不做群成员枚举、不读取历史消息。**
7. **不修改 HandWeChat API 服务本身。** 本程序是它的外部调用方。
8. **所有游戏数据落库。** 不允许只放内存，进程重启后金币、魅力、奴隶关系不能丢。

## 2.3 OCR 噪声的现实约束

- `sender` 可能是 `我`（自己发送）、`对方`（无法识别昵称）、空字符串。
- 同一条消息可能被 OCR 重复输出。
- 昵称可能被识别出多余空格、全角字符、尾部标点。
- 聊天标题可能带成员数量，例如 `888 种田大队(32)`，人数变化会影响标题。
- 消息内容可能带换行、全角 `＠`、全角数字。

实现时必须针对以上情况做规范化、去重和容错；不能假设输入是干净的。

---

# 三、总体架构

```text
微信客户端
   ↕ 截屏 / OCR / 粘贴发送
HandWeChat HTTP API
   ↕ HTTP（本服务的唯一外部依赖）
游戏服务（本程序）
   ├─ 消息轮询器 Poller
   ├─ 命令解析器 Parser
   ├─ 指令分发器 Dispatcher
   ├─ 领域处理器 Handlers（金币 / 魅力 / 礼物 / 奴隶）
   ├─ 持久化 Store（SQLite）
   └─ 回复发送器 Sender（队列 + 限速 + 任务校验）
```

建议目录：

```text
game/
  __init__.py
  main.py               # 启动、轮询循环、优雅退出
  config.py             # 配置加载与校验
  wechat_client.py      # 封装 HandWeChat API
  parser.py             # 消息规范化与命令解析
  dispatcher.py         # 指令路由
  store.py              # SQLite 访问、事务、建表
  models.py             # 数据类
  rng.py                # 可注入的随机源（便于测试）
  replies.py            # 所有回复模板
  send_queue.py         # 出站队列与限速
  handlers/
    coins.py
    charm.py
    gifts.py
    slaves.py
  tests/
```

进程模型：单进程 `asyncio`。消息按到达顺序串行处理；数据库写入串行；发送由独立协程消费队列。

---

# 四、全局消息处理规则

> 本节规则先于所有子系统执行。子系统只负责“命中指令之后做什么”。

## 4.1 消息观察与玩家注册

每收到一条消息：

1. 规范化 `sender`。若 `sender` 属于忽略集合（默认 `["我", "对方", "未知", ""]`），直接丢弃。
2. 在**当前群**的玩家表中 upsert 该 `sender`：
   - 首次出现时创建玩家，初始金币 `initial_coins`（默认 200），初始魅力 `charm_base`（默认 10）。
   - 每次出现更新 `last_seen_at`。
   - 只要玩家本人发过任何消息，就把 `is_phantom` 置为 0（真实玩家）。
3. 然后再判断是否为游戏指令。**普通聊天只注册玩家，不回复、不改数值。**

这样做的目的：让“被购买/被送礼”的目标尽可能已经存在于玩家表中；目标不存在时再按 4.6 的规则处理。

## 4.2 文本规范化

解析前对 `content` 依次执行：

1. Unicode NFKC 规范化（全角 `＠` → `@`，全角数字 → 半角数字，全角字母 → 半角字母）。
2. 将换行、制表符、连续空白折叠为单个半角空格。
3. 去掉首尾空白。
4. 若配置 `allow_hash_prefix=true` 且文本以 `#` 开头，去掉 `#` 及其后的前导空格。
5. 去掉整条消息尾部的标点：`。！？!?，,、~～…`（仅用于“无参数指令”的整句匹配）。
6. 结果为空则丢弃。

注意：第 5 步只去掉整条消息末尾的标点；参数中的昵称要单独清洗（见 4.4）。

## 4.3 指令匹配原则

1. **必须从消息开头匹配。** 例如 `我想购买奴隶@张三` 不是指令，必须忽略。
2. **无参数指令必须整句匹配。** 例如 `奴隶打工` 命中；`奴隶打工好累`、`奴隶打工 谢谢` 不命中。
3. **带参数指令按正则解析。** 指令关键字后面必须紧跟 `@`（允许中间有空格）。
4. **不在指令表里的消息一律静默忽略。** 不回复“未知指令”，避免刷屏。
5. **指令大小写：** 中文关键字精确匹配；英文礼物名/别名不区分大小写。
6. **可选 `#` 前缀：** `#签到` 与 `签到` 等价（可配置关闭）。

## 4.4 参数解析

### 目标昵称

所有 `@用户名` 形式的参数按以下规则解析：

1. `@` 后面的**第一个非空 token** 作为目标昵称。
2. 目标昵称首尾的标点去掉：`。！？!?，,、~～…`。
3. 目标昵称长度必须在 1~20 个字符之间，不能包含 `@`、`#`、换行。
4. 目标昵称**不支持包含空格**。这是明确限制：微信昵称中如果有空格，当前无法被 `@` 指令准确定位。README 中要写明。
5. 目标昵称后面的多余文字：按各指令规则处理；无法识别的多余参数不报错，忽略。
6. 目标查找先做精确匹配；若目标是纯 ASCII 且未找到，再做一次不区分大小写匹配。

示例：

| 输入 | 解析结果 |
| --- | --- |
| `购买奴隶@张三` | target=`张三` |
| `购买奴隶 @ 张三` | target=`张三` |
| `购买奴隶@张三。` | target=`张三` |
| `购买奴隶@张三 谢谢` | target=`张三`，多余文字忽略 |
| `购买奴隶@张 三` | target=`张`（不支持带空格昵称） |
| `购买奴隶 张三` | 不命中，回复用法提示 |
| `我想购买奴隶@张三` | 不命中，静默忽略 |

### 数量参数

- 只接受纯数字（NFKC 后）。
- 范围必须校验；越界时按各指令规则回复失败。
- 多余的非数字文字忽略。

## 4.5 指令总表

> 下表是唯一权威的指令清单。实现时正则和关键字必须与此一致。

| 系统 | 指令 | 参数 | 匹配正则（规范化后） |
| --- | --- | --- | --- |
| 金币 | `我的金币` | 无 | `^我的金币$` |
| 金币 | `签到` | 无 | `^签到$` |
| 金币 | `转账@用户名 数量` | target, amount | `^转账\s*@\s*(?P<target>\S+)\s+(?P<amount>\d+)(?:\s+.*)?$` |
| 金币 | `金币榜` | 无 | `^金币榜$` |
| 金币 | `金币系统` | 无 | `^金币系统$` |
| 魅力 | `我的魅力` / `魅力值` | 无 | `^(?:我的魅力\|魅力值)$` |
| 魅力 | `魅力榜` | 无 | `^魅力榜$` |
| 魅力 | `魅力系统` | 无 | `^魅力系统$` |
| 礼物 | `礼物列表` | 无 | `^礼物列表$` |
| 礼物 | `送礼@用户名 礼物名 [数量]` | target, gift, count | `^送礼\s*@\s*(?P<target>\S+)\s+(?P<gift>\S+?)(?:\s+(?P<count>\d+))?(?:\s+.*)?$` |
| 礼物 | `礼物榜` | 无 | `^礼物榜$` |
| 礼物 | `礼物系统` | 无 | `^礼物系统$` |
| 奴隶 | `购买奴隶@用户名` | target | `^购买奴隶\s*@\s*(?P<target>\S+)(?:\s+.*)?$` |
| 奴隶 | `给他自由@用户名` / `给她自由@用户名` | target | `^给(?:他\|她)自由\s*@\s*(?P<target>\S+)(?:\s+.*)?$` |
| 奴隶 | `奴隶打工` | 无 | `^奴隶打工$` |
| 奴隶 | `我的奴隶` | 无 | `^我的奴隶$` |
| 奴隶 | `我要自由` | 无 | `^我要自由$` |
| 奴隶 | `奴隶系统` | 无 | `^奴隶系统$` |

## 4.6 目标玩家不存在时的处理

配置 `auto_create_target`（默认 `true`）：

- 目标在当前群不存在时，创建一个“影子玩家”：
  - `coins = initial_coins`
  - `charm = charm_base`
  - `is_phantom = 1`
  - `last_seen_at = now`
- 影子玩家可以被购买、被送礼、被转账。
- 影子玩家本人一旦发言，自动转为真实玩家（`is_phantom = 0`）。
- 排行榜默认只统计真实玩家，避免影子玩家污染榜单。
- 若 `auto_create_target=false`，目标不存在时回复：
  `未找到玩家「{target}」，请确认昵称是否正确。`

## 4.7 去重与幂等

1. **按消息 ID 去重。** 维护最近 10,000 个已处理消息 ID 的集合；同 ID 只处理一次。
2. **按内容去重。** 同一 `sender` + 同一规范化 `content` 在 `dedupe_window_seconds`（默认 5 秒）内重复出现，只处理一次。用于抵消 OCR 重复输出。
3. **一条消息最多处理一个指令。** 不解析“一句话里多个指令”。
4. **一次指令一个数据库事务。** 事务内完成所有读写；发送回复在事务提交之后。
5. **发送失败不回滚业务数据。** 金币、魅力、奴隶关系已经发生，就保持发生；只记录发送失败日志。

## 4.8 限流与冷却

| 限制 | 默认值 | 作用范围 | 超限行为 |
| --- | --- | --- | --- |
| 单用户指令间隔 | 2 秒 | 每个玩家 | 静默丢弃并记日志 |
| 帮助类指令冷却 | 60 秒 | 每个玩家 | 静默丢弃 |
| 用法提示冷却 | 60 秒 | 每个玩家 | 静默丢弃 |
| 出站发送 | 15 条/分钟、间隔 ≥1.5 秒 | 全局 | 排队等待 |
| 打工冷却 | 30 分钟 | 每个主人 | 回复冷却剩余时间 |
| 打工每日次数 | 8 次 | 每个主人 | 回复“今日次数已用完” |
| 反抗冷却 | 180 分钟 | 每个奴隶 | 回复冷却剩余时间 |
| 反抗每日次数 | 3 次 | 每个奴隶 | 回复“今日反抗次数已用完” |
| 送礼每日花费 | 20,000 金币 | 每个送礼者 | 回复失败 |
| 转账每日转出 | 5,000 金币 | 每个转出者 | 回复失败 |

## 4.9 群识别与数据隔离

API 只返回当前聊天标题，没有稳定的群 ID。为支持多群并防止串数据：

1. 每次轮询同时读取 `/api/v1/health` 的 `chat_title`。
2. 规范化群标题：
   - 去掉首尾空白；
   - 去掉尾部成员数，如 `(32)`、`（32）`、`(32人)`；
   - 折叠连续空格。
3. `group_key = 规范化后的标题`。
4. 群标题变化需要**稳定 10 秒**才切换 `group_key`，避免 OCR 抖动导致频繁切群。
5. 所有玩家、奴隶关系、礼物、流水、日计数器都按 `group_key` 隔离。
6. 配置 `allowed_groups`：
   - 空数组表示允许所有群；
   - 非空时，只有 `group_key` 在列表中的群才处理指令，否则暂停并记录一次告警。
7. `chat_title` 为空时沿用上一次的 `group_key`；从未识别到标题时，暂停处理并记录日志。

## 4.10 启动、恢复与游标

1. 服务启动后读取配置、初始化数据库。
2. 调用 `/api/v1/health`：
   - 若微信不在线（`online=false`），记录错误并每 10 秒重试。
   - `listener_running` 仅用于状态展示，OCR 监听的启动/重启由使用端负责，本服务不调用 `/api/v1/listener/start`。
3. **丢弃积压消息。** 启动时用 `cursor=0&limit=100` 循环拉取直到 `has_more=false`，把本地 `cursor` 设为最后的 `next_cursor`，不处理这些历史消息。原因：避免服务重启后重放购买、送礼等扣费指令。
4. 正常运行使用长轮询：`GET /api/v1/messages?cursor={local}&limit=100&timeout=25`。
5. **API 重启检测：** 如果响应中的 `next_cursor` 小于本地 `cursor`，说明 API 进程重启、游标已重置。此时：
   - 记 `API_CURSOR_RESET` 日志；
   - 把本地 `cursor` 设为响应中的 `next_cursor`；
   - 丢弃本批消息（视为积压），继续轮询。
6. API 错误处理：
   - `WECHAT_OFFLINE` / `ATTACH_FAILED`：指数退避（1s、2s、5s、10s、30s 封顶）重连，微信窗口的重新附加由使用端负责，本服务不调用 `/api/v1/attach`。
   - `OCR_CHANNEL_NOT_RUNNING`：指数退避重连，等待使用端恢复监听，本服务不调用 `/api/v1/listener/start`。
   - HTTP 5xx / 连接失败：指数退避，不丢业务数据。
   - `INVALID_REQUEST`：记录请求参数，不重试。

## 4.11 回复发送

1. 每个指令产生一个回复文本；多行用 `\n` 连接。
2. 回复进入发送队列，由单独的发送协程按顺序消费。
3. 发送流程：
   - `POST /api/v1/send`，拿到 `task_id`；
   - 每秒轮询 `GET /api/v1/send/{task_id}`，最多 30 秒；
   - `success`：完成；
   - `failed` 且 `error_code=SEND_FAILED`：5 秒后重试一次；
   - `failed` 且 `error_code=SEND_VERIFY_FAILED`：只记录日志，**不重试**，避免重复发送。
4. 回复长度上限 `reply_max_chars`（默认 500 字符）：
   - 超过上限时按行拆分，每段加 `(1/2)`、`(2/2)` 前缀；
   - 单行仍然超长时截断并加 `…`。
5. 发送队列上限 100 条；队列满时记录 `SEND_QUEUE_FULL` 并丢弃该回复（业务数据不回滚）。
6. 所有出站文本必须是纯文本，不使用 Markdown、HTML、表情图片。

## 4.12 静默、用法提示与内部错误

1. 与游戏无关的消息：**静默忽略**。
2. 消息以某个指令关键字开头，且关键字后紧跟 `@`、空白或消息结束，但整体格式不合法：
   - 回复一次用法提示；
   - 同一用户 60 秒内最多一次。
3. 用法提示模板：
   `指令格式不对。用法：{正确用法}`
4. 处理器内部异常：
   - 回滚事务；
   - 记录完整堆栈；
   - 同一用户 60 秒内最多回复一次：`系统开小差了，请稍后再试。`

---

# 五、数据模型

使用 SQLite，开启 WAL。所有时间存 ISO 8601 本地时间字符串（带 `+08:00`）。所有金额为整数金币；魅力值存 2 位小数。

## 5.1 players

```sql
CREATE TABLE IF NOT EXISTS players (
  group_key        TEXT    NOT NULL,
  name             TEXT    NOT NULL,
  coins            INTEGER NOT NULL DEFAULT 200 CHECK (coins >= 0),
  charm            REAL    NOT NULL DEFAULT 10,
  charm_anchor     TEXT    NOT NULL,          -- 上次魅力衰减基准时间
  master           TEXT,                      -- 奴隶主昵称，NULL 表示自由身
  enslaved_at      TEXT,
  is_phantom       INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT    NOT NULL,
  last_seen_at     TEXT    NOT NULL,
  last_signin_date TEXT,                      -- YYYY-MM-DD
  signin_streak    INTEGER NOT NULL DEFAULT 0,
  last_work_at     TEXT,
  last_rebel_at    TEXT,
  total_charm_gained REAL  NOT NULL DEFAULT 0,
  total_gift_spent   INTEGER NOT NULL DEFAULT 0,
  total_gift_charm   REAL  NOT NULL DEFAULT 0,
  PRIMARY KEY (group_key, name)
);

CREATE INDEX IF NOT EXISTS idx_players_master
  ON players(group_key, master);
```

约束由应用层保证：

- `master` 必须指向同群玩家。
- 一个玩家最多只有一个 `master`。
- 一个主人最多 `max_slaves` 个奴隶。
- 不允许自己成为自己的奴隶。
- 不允许形成环（A 是 B 的主人，B 又是 A 的主人）。

## 5.2 gift_events

```sql
CREATE TABLE IF NOT EXISTS gift_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_key  TEXT    NOT NULL,
  ts         TEXT    NOT NULL,
  sender     TEXT    NOT NULL,
  receiver   TEXT    NOT NULL,
  gift_id    TEXT    NOT NULL,
  gift_name  TEXT    NOT NULL,
  count      INTEGER NOT NULL,
  cost       INTEGER NOT NULL,
  charm_gain REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gift_events_group_ts
  ON gift_events(group_key, ts);
```

## 5.3 coin_ledger

每次账户余额变化写一行；转账、送礼等双边变化写两行。

```sql
CREATE TABLE IF NOT EXISTS coin_ledger (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  group_key      TEXT    NOT NULL,
  ts             TEXT    NOT NULL,
  actor          TEXT    NOT NULL,
  counterparty   TEXT,
  amount         INTEGER NOT NULL,            -- 有符号：+收入 / -支出
  reason         TEXT    NOT NULL,            -- signin/gift/transfer/purchase/release/work/rebel
  balance_after  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coin_ledger_group_ts
  ON coin_ledger(group_key, ts);
```

## 5.4 daily_counters

```sql
CREATE TABLE IF NOT EXISTS daily_counters (
  group_key TEXT    NOT NULL,
  date      TEXT    NOT NULL,                 -- YYYY-MM-DD
  name      TEXT    NOT NULL,
  action    TEXT    NOT NULL,                 -- work/gift_spend/transfer_out/rebel
  count     INTEGER NOT NULL DEFAULT 0,
  amount    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (group_key, date, name, action)
);
```

## 5.5 事务与并发

- 单进程、单写入协程；每条指令使用 `BEGIN IMMEDIATE`。
- 所有“先读后写”的数值变更必须在同一事务内完成。
- 魅力衰减也在事务内落库，保证只衰减一次。
- 迁移：启动时执行 `CREATE TABLE IF NOT EXISTS` 与索引创建；后续字段变更用简单的版本号迁移。

---

# 六、全局配置

配置文件：`config/game_config.json`。启动时校验类型与范围，非法配置直接拒绝启动并打印原因。

```json
{
  "api_base_url": "http://127.0.0.1:8000",
  "api_timeout_seconds": 30,
  "poll_timeout_seconds": 25,
  "poll_limit": 100,
  "health_poll_seconds": 2,
  "timezone": "Asia/Shanghai",

  "allow_hash_prefix": true,
  "ignore_senders": ["我", "对方", "未知", ""],
  "dedupe_window_seconds": 5,
  "command_rate_limit_seconds": 2,
  "help_cooldown_seconds": 60,
  "usage_hint_cooldown_seconds": 60,
  "reply_max_chars": 500,

  "send_max_per_minute": 15,
  "send_min_interval_ms": 1500,
  "send_queue_max": 100,
  "send_task_timeout_seconds": 30,

  "allowed_groups": [],
  "group_title_stable_seconds": 10,

  "initial_coins": 200,
  "auto_create_target": true,

  "charm_base": 10,
  "charm_decay_period_days": 7,
  "charm_decay_rate": 0.10,

  "max_slaves": 5,
  "slave_price_coeff": 2.0,
  "slave_price_random_min": 0.0,
  "slave_price_random_max": 10.0,
  "min_slave_price": 10,
  "release_reward_coeff": 2.0,

  "slave_work_cooldown_minutes": 30,
  "slave_work_max_per_day": 8,

  "rebel_cooldown_minutes": 180,
  "rebel_max_per_day": 3,
  "rebel_master_coeff": 1.0,
  "rebel_slave_coeff": 1.0,
  "rebel_master_multipliers": [0.0, 1.0, 2.0],
  "rebel_slave_multipliers": [0.0, 0.5, 1.0],
  "rebel_loot_max": 500,
  "rebel_ransom_max": 500,
  "rebel_compensation_max": 200,

  "signin_base_reward": 10,
  "signin_streak_step": 2,
  "signin_max_reward": 24,
  "transfer_tax_rate": 0.05,
  "transfer_daily_limit": 5000,

  "gift_max_quantity": 99,
  "gift_daily_spend_limit": 20000,
  "gift_rank_days": 30,

  "gifts": [
    {"id": "rose",      "name": "玫瑰",   "aliases": ["rose", "玫瑰花"], "price": 10,   "charm": 1},
    {"id": "lollipop",  "name": "棒棒糖", "aliases": ["lollipop"],       "price": 20,   "charm": 2},
    {"id": "chocolate", "name": "巧克力", "aliases": ["chocolate"],      "price": 52,   "charm": 5},
    {"id": "cake",      "name": "蛋糕",   "aliases": ["cake"],           "price": 99,   "charm": 10},
    {"id": "perfume",   "name": "香水",   "aliases": ["perfume"],        "price": 199,  "charm": 20},
    {"id": "ring",      "name": "戒指",   "aliases": ["ring"],           "price": 520,  "charm": 52},
    {"id": "car",       "name": "跑车",   "aliases": ["car"],            "price": 1314, "charm": 131},
    {"id": "castle",    "name": "城堡",   "aliases": ["castle"],         "price": 5200, "charm": 520}
  ],

  "work_events": [
    {"text": "在奶茶店做帮工，表现优越",     "coins_min": 2,  "coins_max": 2,  "weight": 6},
    {"text": "扶老奶奶过马路",               "coins_min": 3,  "coins_max": 3,  "weight": 6},
    {"text": "在工地搬砖，汗流浃背",         "coins_min": 4,  "coins_max": 4,  "weight": 6},
    {"text": "帮邻居修电脑，收到红包",       "coins_min": 5,  "coins_max": 5,  "weight": 6},
    {"text": "在夜市摆摊，生意兴隆",         "coins_min": 6,  "coins_max": 6,  "weight": 6},
    {"text": "捡到钱包归还失主，获得酬谢",   "coins_min": 3,  "coins_max": 3,  "weight": 6},
    {"text": "替人排队买奶茶",               "coins_min": 2,  "coins_max": 2,  "weight": 6},
    {"text": "在餐厅端盘子，拿到小费",       "coins_min": 4,  "coins_max": 4,  "weight": 6},
    {"text": "帮主人跑腿送快递",             "coins_min": 3,  "coins_max": 3,  "weight": 6},
    {"text": "参加搬家公司临时工",           "coins_min": 5,  "coins_max": 5,  "weight": 6},
    {"text": "扶起摔倒老人，被讹",           "coins_min": -5, "coins_max": -5, "weight": 5},
    {"text": "打工时打碎盘子，赔偿",         "coins_min": -3, "coins_max": -3, "weight": 5},
    {"text": "上班摸鱼被扣工资",             "coins_min": -2, "coins_max": -2, "weight": 5},
    {"text": "骑车送外卖超时，被罚款",       "coins_min": -4, "coins_max": -4, "weight": 5},
    {"text": "被骗子骗走零钱",               "coins_min": -6, "coins_max": -6, "weight": 5},
    {"text": "在工地偷懒被发现，扣钱",       "coins_min": -3, "coins_max": -3, "weight": 5},
    {"text": "在公园长椅上睡了一整天",       "coins_min": 0,  "coins_max": 0,  "weight": 2.5},
    {"text": "去面试被拒，白跑一趟",         "coins_min": 0,  "coins_max": 0,  "weight": 2.5},
    {"text": "帮主人看家，无功无过",         "coins_min": 0,  "coins_max": 0,  "weight": 2.5},
    {"text": "追公交车追了两条街，没赶上",   "coins_min": 0,  "coins_max": 0,  "weight": 2.5}
  ]
}
```

配置说明：

- `send_max_per_minute` 必须 ≤ 20，建议 15。
- `gifts` 的 `charm` 必须为正数；`price` 必须为正整数。
- `work_events` 同一个事件不能跨越正负号（例如 `-2` 到 `+3` 不允许）。
- 所有权重必须大于 0。

---

# 七、金币系统

## 7.1 定位

金币是唯一通用货币，用于购买奴隶、送礼、转账。金币不能为负。

金币的创造与回收：

| 行为 | 方向 | 说明 |
| --- | --- | --- |
| 初始金币 | 创造 | 新玩家 200 |
| 每日签到 | 创造 | 10~24 |
| 奴隶打工 | 创造/回收 | 正收益由系统发放，负收益直接回收 |
| 释放奴隶 | 创造 | 奖励由系统发放 |
| 购买奴隶 | 回收 | 扣款直接销毁，不进入奴隶账户 |
| 送礼物 | 回收 | 礼物费用直接销毁 |
| 转账手续费 | 回收 | 手续费直接销毁 |
| 反抗 | 玩家间转移 | 不创造也不销毁 |

## 7.2 触发规则

- 只有整条消息等于 `我的金币`、`签到`、`金币榜`、`金币系统`，或匹配 `转账@用户名 数量` 时才处理。
- 其余消息一律不进入金币系统。
- `转账` 必须带 `@` 和正整数数量。

## 7.3 指令

### 7.3.1 我的金币

触发：`我的金币`

说明：查看自己的金币余额与群内排名。

返回：

```text
我的金币：
{sender} 当前金币 {coins}（群内第 {rank} 名）。
```

- `rank` 按当前群真实玩家的金币降序计算；同额按昵称升序。
- 玩家是影子玩家时，排名按全部真实玩家计算，若不在榜内显示 `未上榜`。

### 7.3.2 签到

触发：`签到`

说明：每天签到一次领取金币，连续签到有加成。

公式：

```text
reward = min(signin_base_reward + (streak - 1) * signin_streak_step, signin_max_reward)
```

- `streak` 规则：
  - 今天已签到：回复“今天已经签到过了”，不加金币、不改变连续天数。
  - 上次签到是昨天：`streak = streak + 1`。
  - 上次签到不是昨天或从未签到：`streak = 1`。
- 日期按 `timezone`（默认 `Asia/Shanghai`）的本地日期计算，00:00 切换。
- 默认第 1 天 10 金币，第 2 天 12，第 3 天 14……第 8 天起封顶 24。

返回（成功）：

```text
签到成功！获得 {reward} 金币（连续签到 {streak} 天）。
当前金币：{coins}。
```

返回（重复）：

```text
{sender} 今天已经签到过了，明天再来吧。
```

### 7.3.3 转账

触发：`转账@用户名 数量`

说明：把自己的金币转给另一个玩家，收取手续费。

公式：

```text
fee     = ceil(amount * transfer_tax_rate)
net     = amount - fee
```

规则：

- `amount` 必须是正整数，且 ≥ 1。
- 不能转给自己。
- `amount` 不能超过自己的余额。
- 每次转出金额计入当日 `transfer_out` 累计；超过 `transfer_daily_limit` 则失败。
- 目标不存在时按 4.6 处理。
- 转账成功后：转出方扣 `amount`，接收方加 `net`，`fee` 销毁。

返回（成功）：

```text
转账成功：{sender} → {target} {net} 金币（手续费 {fee} 金币）。
{sender} 当前金币：{coins}。
```

返回（失败示例）：

```text
转账失败：金币不足（需要 {amount} 金币，当前 {coins} 金币）。
转账失败：不能转账给自己。
转账失败：今日转账额度不足（剩余 {remaining} 金币）。
```

### 7.3.4 金币榜

触发：`金币榜`

说明：列出当前群金币最多的 10 位真实玩家。

返回：

```text
金币榜 TOP10：
1. 张三 1234
2. 李四 987
...
```

- 不足 10 人时按实际人数列出。
- 无数据时：`金币榜暂无数据。`

### 7.3.5 金币系统

触发：`金币系统`

返回：

```text
金币系统指令：
1. 我的金币 —— 查看余额与排名
2. 签到 —— 每日签到领金币
3. 转账@用户名 数量 —— 转账（手续费 5%）
4. 金币榜 —— 金币排行
```

## 7.4 边界与失败处理

- 所有扣款先校验余额，余额不足不产生任何状态变化。
- 所有金额变更写 `coin_ledger`。
- 同一指令内多次变更（如转账双边）必须在同一事务内完成。
- 金币下限 0；任何会导致负数的操作直接失败，不做“扣到 0 为止”的静默截断（奴隶打工的亏损事件除外，见 10.5）。

---

# 八、魅力系统

## 8.1 定位

魅力值是玩家的社交资产，决定：

1. 被购买为奴隶时的价格；
2. 反抗奴隶主时的战力；
3. 魅力榜排名；
4. 被送礼后的成长反馈。

魅力值不是货币，不能直接消费，不能转账。

## 8.2 触发规则

- 只有整条消息等于 `我的魅力`、`魅力值`、`魅力榜`、`魅力系统` 时才处理。
- 魅力值本身不能通过指令直接增加；唯一来源是收到礼物。
- 其他系统读写魅力值时，必须先执行“魅力衰减结算”。

## 8.3 指令

### 8.3.1 我的魅力

触发：`我的魅力` 或 `魅力值`

返回：

```text
{sender} 当前魅力值 {charm}，群内第 {rank} 名。
累计收到礼物魅力 +{total_charm_gained}。
```

- 魅力显示保留 1 位小数，四舍五入。
- `rank` 按当前群真实玩家的有效魅力降序；同值按昵称升序。
- 影子玩家不参与排名；若自己是影子玩家，显示 `未上榜`。

### 8.3.2 魅力榜

触发：`魅力榜`

返回：

```text
魅力榜 TOP10：
1. 张三 88.5
2. 李四 52.0
...
```

- 只统计真实玩家（`is_phantom=0`）。
- 无数据时：`魅力榜暂无数据。`

### 8.3.3 魅力系统

触发：`魅力系统`

返回：

```text
魅力系统指令：
1. 我的魅力 —— 查看魅力值与排名
2. 魅力榜 —— 魅力排行
说明：收到礼物可增加魅力；魅力每 7 天衰减 10%，最低不低于基础值 10。
```

## 8.4 魅力公式

### 8.4.1 初始值

- 新玩家 `charm = charm_base`（默认 10.0）。
- `charm_anchor = 创建时间`。

### 8.4.2 获得魅力

- 收到礼物时：
  ```text
  charm = effective_charm(receiver) + gift.charm * count
  ```
- 同时累加 `total_charm_gained += gift.charm * count`。
- 魅力值存储保留 2 位小数。

### 8.4.3 衰减

每满 `charm_decay_period_days`（默认 7 天）衰减一次，只衰减超出基础值的部分：

```text
periods = floor((now - charm_anchor) / charm_decay_period_days)
if periods > 0 and charm > charm_base:
    charm = charm_base + (charm - charm_base) * (1 - charm_decay_rate) ** periods
    charm_anchor = charm_anchor + periods * charm_decay_period_days
    round(charm, 2) 并落库
```

规则：

- 衰减是惰性结算：任何读取或修改魅力之前调用 `effective_charm(player)`。
- 幂等：同一时间点多次调用不会重复衰减。
- 衰减后不得低于 `charm_base`。
- 衰减不产生日志刷屏，只在 debug 级别记录。

### 8.4.4 显示

- 存储 2 位小数，展示 1 位小数。
- 排名使用未四舍五入的存储值。

## 8.5 边界

- 魅力值不能为负。
- 礼物带来的魅力可以无限累加，但会随时间衰减。
- 魅力值变化必须写日志（debug 级别即可），但不写金币流水。
- 影子玩家的魅力同样可以增长；转为真实玩家后直接参与排名。

---

# 九、礼物系统

## 9.1 定位

礼物是金币的主要消耗途径，也是魅力值的唯一来源。送礼是公开行为，回复会展示在群里。

## 9.2 礼物目录

| id | 名称 | 别名 | 价格（金币） | 魅力 |
| --- | --- | --- | --- | --- |
| rose | 玫瑰 | rose、玫瑰花 | 10 | 1 |
| lollipop | 棒棒糖 | lollipop | 20 | 2 |
| chocolate | 巧克力 | chocolate | 52 | 5 |
| cake | 蛋糕 | cake | 99 | 10 |
| perfume | 香水 | perfume | 199 | 20 |
| ring | 戒指 | ring | 520 | 52 |
| car | 跑车 | car | 1314 | 131 |
| castle | 城堡 | castle | 5200 | 520 |

- 礼物目录完全由配置驱动，不在代码里硬编码。
- 名称和别名匹配不区分 ASCII 大小写。
- 展示时按价格升序。

## 9.3 触发规则

- `送礼@用户名 礼物名 [数量]` 必须同时包含目标、礼物名；数量可省略，默认 1。
- 礼物名必须是目录中的名称或别名。
- 数量必须是 1~99 的整数。
- `礼物列表`、`礼物榜`、`礼物系统` 为整句指令。
- 其他消息不进入礼物系统。

## 9.4 指令

### 9.4.1 送礼

触发：`送礼@用户名 礼物名 [数量]`

公式：

```text
cost       = gift.price * count
charm_gain = gift.charm * count
```

规则：

1. 不能送给自己。
2. 目标不存在时按 4.6 处理。
3. `count` 默认 1，范围 1~99；越界回复失败。
4. 校验余额：`coins >= cost`，否则失败，不产生任何变化。
5. 校验当日送礼花费：`已花费 + cost <= gift_daily_spend_limit`，否则失败。
6. 扣款 `cost`（销毁）。
7. 目标先做魅力衰减结算，再加 `charm_gain`。
8. 写 `gift_events`、`coin_ledger`，累加双方的礼物统计。
9. 礼物是公开行为，回复中展示送礼者、收礼者、礼物、数量、花费、魅力变化。

返回（成功）：

```text
{sender} 送给 {target} ×{count} {gift_name}，花费 {cost} 金币。
{target} 魅力 +{charm_gain}，当前魅力 {target_charm}。
```

返回（失败示例）：

```text
送礼失败：金币不足（需要 {cost} 金币，当前 {coins} 金币）。
送礼失败：不能送给自己。
送礼失败：没有找到礼物「{gift_name}」，发送「礼物列表」查看可送礼物。
送礼失败：数量必须在 1~99 之间。
送礼失败：今日送礼额度不足（剩余 {remaining} 金币）。
```

### 9.4.2 礼物列表

触发：`礼物列表`

返回：

```text
礼物列表（价格 / 魅力）：
玫瑰 10 金币 +1 魅力
棒棒糖 20 金币 +2 魅力
巧克力 52 金币 +5 魅力
蛋糕 99 金币 +10 魅力
香水 199 金币 +20 魅力
戒指 520 金币 +52 魅力
跑车 1314 金币 +131 魅力
城堡 5200 金币 +520 魅力
用法：送礼@用户名 礼物名 [数量]
```

### 9.4.3 礼物榜

触发：`礼物榜`

说明：统计最近 `gift_rank_days`（默认 30）天的送礼与收礼情况。

返回：

```text
送礼榜 TOP5（近 30 天）：
1. 张三 5200 金币
2. 李四 1314 金币

收礼榜 TOP5（近 30 天）：
1. 王五 520 魅力
2. 赵六 131 魅力
```

- 两个榜都只统计真实玩家。
- 某个榜无数据时显示 `暂无数据`。
- 并列按昵称升序。

### 9.4.4 礼物系统

触发：`礼物系统`

返回：

```text
礼物系统指令：
1. 礼物列表 —— 查看可送礼物
2. 送礼@用户名 礼物名 [数量] —— 赠送礼物
3. 礼物榜 —— 近 30 天送礼 / 收礼排行
说明：送礼消耗金币，收礼增加魅力。
```

## 9.5 边界

- 礼物一旦送出，不可撤回、不可退款。
- 礼物费用不进入收礼者账户。
- 送礼者不增加魅力。
- 礼物记录用于榜单和审计，不删除。
- 大量礼物可能导致魅力快速上涨，这是设计内的；衰减机制负责长期平衡。

---

# 十、奴隶系统

## 10.1 定位

奴隶系统是本游戏的核心玩法：

- 用金币购买他人为奴隶；
- 奴隶可以被主人驱使打工，产生随机收益或亏损；
- 主人可以释放奴隶，获得重新计算的金币奖励；
- 奴隶可以反抗，成功则恢复自由，失败则可能被镇压或得到补偿。

## 10.2 触发规则

- 只有以下消息进入奴隶系统：
  - `购买奴隶@用户名`
  - `给他自由@用户名` / `给她自由@用户名`
  - `奴隶打工`
  - `我的奴隶`
  - `我要自由`
  - `奴隶系统`
- `购买奴隶`、`给他自由`、`给她自由` 必须带 `@`；缺少 `@` 回复用法提示。
- 其余消息一律忽略。

## 10.3 购买奴隶

触发：`购买奴隶@用户名`

说明：把指定玩家购买为自己的奴隶，按公式扣除金币。

价格公式：

```text
charm  = effective_charm(target)
r      = uniform(slave_price_random_min, slave_price_random_max)
raw    = charm * slave_price_coeff * r
price  = max(min_slave_price, ceil(raw))
```

默认：

- `slave_price_coeff = 2.0`
- `slave_price_random_min = 0.0`
- `slave_price_random_max = 10.0`
- `min_slave_price = 10`

规则：

1. 不能购买自己。
2. 目标已经是自己的奴隶：失败，`{target} 已经是你的奴隶。`
3. 目标已经是别人的奴隶：失败，`{target} 已经是 {master} 的奴隶。`
4. 目标是自己当前的主人：失败，`不能购买自己的主人。`
5. 自己的奴隶数量已达到 `max_slaves`：失败。
6. 金币不足：失败，不产生任何变化。
7. 成功后：
   - 扣除 `price` 金币（销毁，不进入目标账户）；
   - 设置 `target.master = sender`，`target.enslaved_at = now`；
   - 写 `coin_ledger`；
   - 回复购买结果和最新奴隶列表。

返回（成功）：

```text
购买成功，花费 {price} 金币。
{sender}的奴隶：
1. {slave1}
2. {slave2}
...
```

返回（失败示例）：

```text
购买失败：金币不足（需要 {price} 金币，当前 {coins} 金币）。
购买失败：不能购买自己。
购买失败：{target} 已经是你的奴隶。
购买失败：{target} 已经是 {master} 的奴隶。
购买失败：不能购买自己的主人。
购买失败：你的奴隶已达上限（{max_slaves} 个）。
```

## 10.4 释放奴隶

触发：`给他自由@用户名` 或 `给她自由@用户名`

说明：把指定奴隶从自己的奴隶列表中释放，并获得重新计算的金币奖励。

奖励公式（重新随机一次）：

```text
charm   = effective_charm(target)
r       = uniform(slave_price_random_min, slave_price_random_max)
reward  = max(min_slave_price, ceil(charm * release_reward_coeff * r))
```

默认 `release_reward_coeff = 2.0`。

规则：

1. 目标必须是自己的奴隶；否则回复无效，不改任何状态。
2. 成功后：
   - 清除 `target.master` 与 `target.enslaved_at`；
   - 主人获得 `reward` 金币（由系统发放）；
   - 写 `coin_ledger`；
   - 回复释放结果。

返回（成功）：

```text
恭喜{target}恢复自由身。
{sender} 获得 {reward} 金币。
```

返回（无效）：

```text
{sender} 的奴隶列表中没有 {target}。
```

## 10.5 奴隶打工

触发：`奴隶打工`

说明：驱使名下所有奴隶各打工一次，每个奴隶随机触发一个事件。

规则：

1. 没有奴隶：`你还没有奴隶，先去购买一个吧。`
2. 冷却中：`奴隶们还在休息，{minutes} 分钟后再试。`
3. 当日次数已用完：`今天的打工次数已用完（{max_per_day} 次）。`
4. 每个奴隶独立抽取一个事件，按权重随机。
5. 事件金币为负且主人余额不足时：本次最多扣到 0，按实际扣除金额展示。
6. 所有事件在同一事务内结算。
7. 更新 `last_work_at` 与当日 `work` 计数。

返回：

```text
{sender}的奴隶打工：
1. {slave1} 在奶茶店做帮工，表现优越，为主人赚得 2 金币。
2. {slave2} 扶老奶奶过马路，为主人赚得 3 金币。
3. {slave3} 扶起摔倒老人，被讹，让主人损失 5 金币。
...
本次合计：+{total} 金币，当前金币 {coins}。
```

渲染规则：

- `coins > 0`：`{slave} {event.text}，为主人赚得 {coins} 金币。`
- `coins < 0`：`{slave} {event.text}，让主人损失 {abs(coins)} 金币。`
- `coins == 0`：`{slave} {event.text}，没有收获。`
- 合计为正：`本次合计：+{total} 金币，当前金币 {coins}。`
- 合计为负：`本次合计：-{abs(total)} 金币，当前金币 {coins}。`
- 合计为 0：`本次合计：0 金币，当前金币 {coins}。`

## 10.6 我的奴隶

触发：`我的奴隶`

返回（有奴隶）：

```text
{sender}的奴隶（{count}/{max_slaves}）：
1. {slave1}
2. {slave2}
...
```

返回（无奴隶）：

```text
{sender} 目前没有奴隶。
```

- 按 `enslaved_at` 升序展示。
- 超过 20 个时只展示前 20 个，并追加 `…（共 {count} 个）`。

## 10.7 我要自由（奴隶反抗）

触发：`我要自由`

说明：奴隶尝试摆脱主人。先比较双方战力，再根据成功/失败抽取具体结局。

战力公式：

```text
master_mult = choice(rebel_master_multipliers)   # 默认 {0.0, 1.0, 2.0}，等概率
slave_mult  = choice(rebel_slave_multipliers)    # 默认 {0.0, 0.5, 1.0}，等概率

master_score = effective_charm(master) * rebel_master_coeff * master_mult
slave_score  = effective_charm(slave)  * rebel_slave_coeff  * slave_mult
```

判定：

```text
success = slave_score >= master_score
```

- 平局视为奴隶反抗成功（险胜）。
- 双方战力都保留 2 位小数比较。

前置校验：

1. 不是奴隶：`你现在是自由身，不需要反抗。`
2. 冷却中：`你刚反抗过，还需 {minutes} 分钟。`
3. 当日次数已用完：`今天的反抗次数已用完（{max_per_day} 次）。`

成功结局（三选一，等概率）：

1. 普通恢复自由：
   `恭喜{sender}恢复自由身。`
2. 恢复自由并拿走主人金币：
   ```text
   恭喜{sender}恢复自由身，并拿走{master}的{loot}金币。
   ```
   `loot = random_int(1, min(master.coins, rebel_loot_max))`；若主人余额为 0，则退化为结局 1。
3. 恢复自由并支付主人赎金：
   ```text
   恭喜{sender}恢复自由身，并支付{master}赎金{ransom}金币。
   ```
   `ransom = random_int(1, min(slave.coins, rebel_ransom_max))`；若奴隶余额为 0，则退化为结局 1。

失败结局（三选一，等概率）：

4. 普通失败：
   `{sender}反抗失败。`
5. 被镇压并上缴金币：
   ```text
   {sender}反抗失败，遭到{master}镇压，上缴主人{penalty}金币。
   ```
   `penalty = random_int(1, min(slave.coins, rebel_ransom_max))`；若奴隶余额为 0，则退化为结局 4。
6. 主人良心发现补贴：
   ```text
   {sender}反抗失败，但{master}良心发现，补贴{compensation}金币。
   ```
   `compensation = random_int(1, min(master.coins, rebel_compensation_max))`；若主人余额为 0，则退化为结局 4。

状态变更：

- 成功：清除 `slave.master` 与 `slave.enslaved_at`；按结局转移金币。
- 失败：保持奴隶关系；按结局转移金币。
- 更新 `last_rebel_at` 与当日 `rebel` 计数。
- 所有金币变化写 `coin_ledger`。

## 10.8 奴隶系统帮助

触发：`奴隶系统`

返回：

```text
奴隶系统指令：
1. 购买奴隶@用户名 —— 购买奴隶
2. 给他自由@用户名 / 给她自由@用户名 —— 释放奴隶
3. 奴隶打工 —— 让所有奴隶打工
4. 我的奴隶 —— 查看我的奴隶
5. 我要自由 —— 反抗奴隶主
说明：购买价格 = 目标魅力值 × 系数 × 随机系数；每个主人最多 5 个奴隶。
```

## 10.9 打工事件表

事件表完全由配置 `work_events` 驱动，默认 20 条：

| 类型 | 事件 | 金币 | 权重 |
| --- | --- | --- | --- |
| 正 | 在奶茶店做帮工，表现优越 | +2 | 6 |
| 正 | 扶老奶奶过马路 | +3 | 6 |
| 正 | 在工地搬砖，汗流浃背 | +4 | 6 |
| 正 | 帮邻居修电脑，收到红包 | +5 | 6 |
| 正 | 在夜市摆摊，生意兴隆 | +6 | 6 |
| 正 | 捡到钱包归还失主，获得酬谢 | +3 | 6 |
| 正 | 替人排队买奶茶 | +2 | 6 |
| 正 | 在餐厅端盘子，拿到小费 | +4 | 6 |
| 正 | 帮主人跑腿送快递 | +3 | 6 |
| 正 | 参加搬家公司临时工 | +5 | 6 |
| 负 | 扶起摔倒老人，被讹 | -5 | 5 |
| 负 | 打工时打碎盘子，赔偿 | -3 | 5 |
| 负 | 上班摸鱼被扣工资 | -2 | 5 |
| 负 | 骑车送外卖超时，被罚款 | -4 | 5 |
| 负 | 被骗子骗走零钱 | -6 | 5 |
| 负 | 在工地偷懒被发现，扣钱 | -3 | 5 |
| 零 | 在公园长椅上睡了一整天 | 0 | 2.5 |
| 零 | 去面试被拒，白跑一趟 | 0 | 2.5 |
| 零 | 帮主人看家，无功无过 | 0 | 2.5 |
| 零 | 追公交车追了两条街，没赶上 | 0 | 2.5 |

正/负/零的权重合计为 60 / 30 / 10，期望收益略为正，保证养奴隶有动力但不会失控。

## 10.10 边界与防刷

- 一个玩家同时只能有一个主人。
- 一个主人最多 `max_slaves` 个奴隶。
- 不允许自己买自己、买自己的主人、形成主奴环。
- 购买、释放、打工、反抗都必须在一个事务内完成。
- 打工、反抗有冷却与每日次数限制。
- 释放奖励由系统发放，购买扣款由系统销毁；两者使用同一套价格公式，长期期望接近平衡。
- 奴隶关系不因玩家离线、改名（新昵称视为新玩家）而自动解除。

---

# 十一、跨系统规则

## 11.1 数值结算顺序

一条指令内涉及多个系统时，按以下顺序执行：

1. 校验发送者是否存在、是否被限流、是否重复消息。
2. 校验目标是否存在（必要时创建影子玩家）。
3. 校验参数与业务前置条件。
4. 对涉及的角色执行魅力衰减结算。
5. 校验金币余额与每日额度。
6. 变更金币、魅力、奴隶关系。
7. 写礼物记录、金币流水、每日计数器。
8. 提交事务。
9. 生成回复并进入发送队列。

## 11.2 经济闭环

- 金币来源：初始金币、签到、打工正收益、释放奖励。
- 金币回收：购买奴隶、送礼、转账手续费、打工负收益。
- 魅力来源：收礼。
- 魅力回收：每 7 天衰减 10%（只衰减超出基础值部分）。
- 设计目标：让“送礼 → 魅力上升 → 奴隶价格上升 → 购买/释放/反抗更有博弈”形成闭环。

## 11.3 数值边界

- 金币：整数，范围 `[0, 2^31-1]`。
- 魅力：浮点，范围 `[charm_base, 1e9]`，存储 2 位小数。
- 所有随机金额至少为 1；退化为 0 时按对应规则降级。
- 所有除零、负数、越界参数在入口处拦截。

## 11.4 防刷与公平

- 单用户指令间隔、帮助冷却、用法提示冷却。
- 打工、反抗冷却与每日次数。
- 送礼每日花费上限、转账每日转出上限。
- 回复发送全局限速。
- 所有异常与限流都记日志，便于事后审计。
- 不提供任何“管理员加钱/改魅力”的群内指令；需要调整时直接改数据库或配置文件。

## 11.5 身份与昵称

- 玩家身份以“群 + 昵称”为准。
- 微信昵称改名后视为新玩家，旧数据不会自动迁移；README 中注明。
- 影子玩家用于处理“目标尚未发言”的情况；本人首次发言后转正。
- 不支持昵称中包含空格的玩家作为 `@` 目标。

---

# 十二、非功能要求

## 12.1 可靠性

- 进程崩溃后重启，金币、魅力、奴隶关系、礼物记录、流水不丢。
- 消息处理幂等：同一条消息不会重复扣费。
- 发送失败不回滚业务数据。
- 微信离线、OCR 停止、API 重启都能自动恢复。
- 优雅退出：停止轮询、等待发送队列清空（最多 10 秒）。

## 12.2 日志

- 日志目录：`data/logs/`。
- 文件：`game.log`，按 10MB 轮转，保留 5 份。
- 每条指令一行结构化日志：
  ```text
  2026-11-14T15:30:00+08:00 | group=888种田大队 | sender=张三 | cmd=purchase_slave | target=李四 | result=ok | price=120 | cost_ms=3
  ```
- 错误日志包含堆栈。
- 不记录与游戏无关的聊天内容。
- 发送任务失败记录 `task_id`、`error_code`、`error_message`。

## 12.3 监控

提供 `GET /health`（本服务自己的端口，默认 8001）：

```json
{
  "status": "ok",
  "api_online": true,
  "listener_running": true,
  "chat_title": "888 种田大队(32)",
  "group_key": "888 种田大队",
  "cursor": 1234,
  "queue_size": 0,
  "processed_total": 567,
  "last_error": null
}
```

## 12.4 部署

- Windows 10/11，与微信、HandWeChat API 同机运行。
- 通过命令行或 NSSM 注册为服务。
- 配置文件路径通过命令行参数指定：
  ```bash
  python -m game.main --config config/game_config.json
  ```
- 依赖尽量少：`httpx`、`aiosqlite`（或标准库 `sqlite3` + 线程池）、`pydantic`（可选）。
- 不引入 Redis、MySQL、消息队列等外部组件。

## 12.5 测试

必须提供：

1. **解析器单测**：正常指令、全角字符、多余空格、尾部标点、错误格式、非指令消息。
2. **公式单测**：购买价格、释放奖励、魅力衰减、签到奖励、反抗判定、打工事件权重。
3. **处理器单测**：使用内存 SQLite + 可注入随机源，覆盖成功、余额不足、冷却、上限、无效目标。
4. **集成测试**：用假 HTTP 服务模拟 HandWeChat API，验证轮询、去重、发送、游标重置。
5. **回归测试**：覆盖第十三章全部验收用例。

随机源必须可注入，测试中使用固定序列，禁止依赖真实随机。

---

# 十三、验收用例

> 以下用例中的初始值按默认配置。测试时固定随机源。

| # | 场景 | 操作 | 预期 |
| --- | --- | --- | --- |
| 1 | 新玩家注册 | 张三发送 `我的金币` | 创建张三，金币 200，回复余额与排名 |
| 2 | 首次签到 | 张三发送 `签到` | 金币 +10，streak=1 |
| 3 | 重复签到 | 张三再次发送 `签到` | 回复“今天已经签到过了”，金币不变 |
| 4 | 连续签到 | 次日张三发送 `签到` | 金币 +12，streak=2 |
| 5 | 购买成功 | 张三 `购买奴隶@李四`，李四魅力 10，随机系数 1.0 | 价格 `max(10, ceil(10*2*1))=20`，张三 -20，李四 master=张三 |
| 6 | 购买余额不足 | 张三金币 5，`购买奴隶@李四` | 失败，双方状态不变 |
| 7 | 购买自己的主人 | 李四是张三的主人，张三 `购买奴隶@李四` | 失败，提示不能购买自己的主人 |
| 8 | 奴隶上限 | 张三已有 5 个奴隶，再买第 6 个 | 失败，提示已达上限 |
| 9 | 释放成功 | 张三 `给他自由@李四` | 李四 master 清空，张三获得奖励，提示恢复自由 |
| 10 | 释放无效 | 张三 `给她自由@王五`，王五不是其奴隶 | 回复“奴隶列表中没有王五”，状态不变 |
| 11 | 无奴隶打工 | 张三 `奴隶打工` | 提示先购买奴隶 |
| 12 | 打工结算 | 张三有 2 个奴隶，固定事件 +2、-5 | 分别结算，合计 -3，金币同步减少 |
| 13 | 打工冷却 | 立即再次 `奴隶打工` | 提示冷却剩余时间 |
| 14 | 反抗成功 | 奴隶战力 >= 主人战力 | 清除 master，按结局转移金币 |
| 15 | 反抗失败 | 奴隶战力 < 主人战力 | 保持 master，按结局转移金币 |
| 16 | 非奴隶反抗 | 自由身发送 `我要自由` | 提示不需要反抗 |
| 17 | 送礼成功 | 张三 `送礼@李四 玫瑰 2` | 张三 -20，李四魅力 +2，写礼物记录 |
| 18 | 送礼余额不足 | 张三金币 5，`送礼@李四 玫瑰` | 失败，双方状态不变 |
| 19 | 送礼给自己 | 张三 `送礼@张三 玫瑰` | 失败，提示不能送给自己 |
| 20 | 魅力衰减 | 李四魅力 110，距上次结算 7 天 | 魅力变为 `10 + 100*0.9 = 100` |
| 21 | 无关消息 | 发送 `今天天气不错` | 不回复，不改数值，只更新 last_seen |
| 22 | 非开头指令 | 发送 `我想购买奴隶@张三` | 忽略 |
| 23 | 格式错误 | 发送 `购买奴隶 张三` | 回复一次用法提示，不改数值 |
| 24 | 重复消息 | 同一消息 ID 重复投递 | 只处理一次 |
| 25 | OCR 重复 | 同一 sender+content 5 秒内出现两次 | 只处理一次 |
| 26 | 自己发送 | sender=`我` | 忽略 |
| 27 | 无法识别昵称 | sender=`对方` | 忽略 |
| 28 | API 游标重置 | 本地 cursor=500，API 返回 next_cursor=10 | 重置本地游标，丢弃该批消息，继续轮询 |
| 29 | 多群隔离 | 切换到另一个群，同名玩家 | 两个群的金币、奴隶关系互不影响 |
| 30 | 发送失败 | `/send` 返回 `SEND_VERIFY_FAILED` | 记日志，不重试，业务数据保持 |

---

# 十四、明确不做

以下内容不在本次范围内，不要实现：

1. 不做 Web 管理后台。
2. 不做群内管理员加钱、改魅力、强制解除奴隶等指令。
3. 不做图片、语音、文件、引用、表情包处理。
4. 不做自然语言理解；只做固定指令。
5. 不做聊天切换、群成员列表、历史消息回溯。
6. 不做多进程、多实例部署。
7. 不做账号体系、登录、权限。
8. 不做外部数据库、缓存、消息队列。
9. 不修改 HandWeChat API 服务。
10. 不自行增加未在本文定义的玩法（例如抢劫、赌场、结婚、宠物等）。

---

# 十五、待确认点与默认假设

以下参数和规则是我按“可直接落地、经济闭环、防刷”原则给出的默认值。**如果与你的预期不同，请指出，我会先改这份 Prompt，再开始写代码。**

| # | 待确认点 | 默认假设 |
| --- | --- | --- |
| 1 | 新玩家初始金币 | 200 |
| 2 | 购买价格系数 | 2.0；随机范围 [0,10]；最低价 10 |
| 3 | 释放奖励系数 | 与购买相同，2.0，重新随机 |
| 4 | 购买扣款去向 | 系统销毁，不进入奴隶账户 |
| 5 | 释放奖励来源 | 系统发放 |
| 6 | 魅力初始值 | 10 |
| 7 | 魅力来源 | 仅收礼 |
| 8 | 魅力衰减 | 每 7 天衰减 10%，只衰减超出基础值的部分 |
| 9 | 每个主人奴隶上限 | 5 |
| 10 | 打工冷却 / 每日次数 | 30 分钟 / 8 次 |
| 11 | 反抗冷却 / 每日次数 | 180 分钟 / 3 次 |
| 12 | 反抗平局 | 奴隶胜 |
| 13 | 反抗随机倍率 | 主人从 {0,1,2} 等概率；奴隶从 {0,0.5,1} 等概率 |
| 14 | 礼物目录 | 8 种，10~5200 金币，魅力 = 价格/10 |
| 15 | 转账手续费 | 5%，每日转出上限 5000 |
| 16 | 签到奖励 | 10 起，每天 +2，封顶 24 |
| 17 | 目标昵称 | 不支持空格；`@` 必填 |
| 18 | `#` 前缀 | 允许，可配置关闭 |
| 19 | 目标不存在 | 自动创建影子玩家；排行榜不显示影子玩家 |
| 20 | 多群数据 | 按规范化后的群标题隔离 |
| 21 | 指令速率 | 单用户 2 秒一条；出站 15 条/分钟 |
| 22 | 回复长度 | 500 字符，超出拆条 |
| 23 | 服务端口 | 游戏服务自身健康检查 8001 |

如果以上默认值都确认，请直接说“开始写代码”；我会按这份 Prompt 实现，并在实现完成后给出启动方式、配置说明和测试结果。
