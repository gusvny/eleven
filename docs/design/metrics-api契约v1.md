---
title: metrics 口径与 API 契约 v1
category: design
tags:
  - metrics
  - 契约
  - API
status: active
updated: 2026-09-04
---

# metrics 口径与 API 契约 v1

> **本文是契约文档，字段级冻结即本文目的，豁免《设计文档写作指南》自查清单中
> 「Proposal 无 API 名/字段名」一项；其余自查项照常适用。**
>
> 本文冻结 metrics 立项（notes/epics/metrics.md）M0 的三维数据口径、`/metrics`
> API 请求/响应、缓存记录 schema 与降级行为。v1 冻结后，M1a/M2/M3 各工单的实现
> 与验收以本文为唯一真源；任何字段增删须开新工单 bump 版本（见块 6），不得就地
> 改写。`docs/design/metrics面板ui规划.md` §6 保留示意并已回指本文。

## Problem（问题）

### 现状哪里不好

metrics 立项的 M1a（读侧聚合后端）、M2 系列（面板四视图）、M3（对账验收）是多张
并行工单，都要消费同一套数字。目前契约内容只有《metrics 面板 UI 规划》§6 的 12 行
示意：参数一行、ChartSpec 一行、缓存 schema 一行——字段语义、默认值、非法值行为、
降级路径均未定义。并行实现必然各说各话；M3 的「图表数字 vs 人工核算」「双前门
字节级一致」两条硬验收没有可依据的口径成文，对账无从判红绿。

### 背景知识

- **三真源**（立项单关键决策 1）：时间=Temporal timeline（`state==='running'`
  终态条目的时间戳）；交付=git（lane 分支 diff/commit）；token=`~/.dsh` 会话
  落盘文件（t260828-07 已落地的解析通路）。
- **t260828-07 usage 通路**（机制文档「usage 聚合数据通路」节）：工单台已有的
  token 统计实现（`workbench/src/host/agent-usage.ts`），含窗口切分、事件提炼、
  一组已处理的故障模式——本文大量沿用其口径与降级先例。
- **双前门**：聚合唯一实现服务两个入口——workbench host 的 HTTP `GET /metrics`
  （服务 UI）与 node CLI（服务 agent/脚本/CI）；同请求同响应字节级一致是
  M3 基线锁的验收硬项。
- **多模板**：聚合键=（模板， stage），stage 轴=所选模板 STAGES 链序，跨模板
  永不混排（立项单关键决策 5）。

### 证据

- UI 规划 §6 全部契约内容仅 12 行，无字段语义与错误行为；
- 立项单 M0 明确要求「成文冻结，防止后续 M1a/M2 工单各说各话」；
- M3 要求「抽 3 张已结票对账」「LOC 对 `git diff --stat`」「双前门字节级一致」，
  三者均需口径先行。

## Requirement（需求）

每条可验证：

1. **三维口径每条有唯一真源、明确计算式、已知近似声明**：M1a 实现者读完本文后
   无需再做任何口径决策；
2. **`/metrics` 请求参数枚举 + 默认值 + 非法值行为逐项定义；响应 JSON 逐字段
   （含类型）定义**，可逐字实现；
3. **缓存记录 schema 逐字段（含类型）+ 失效规则成文**，与立项单关键决策 2
   （source_version/engine_version/updated_ts 版本化失效）一致；
4. **双前门字节级一致的比较面成文**：M3 基线比对脚本按本文规则实现后不会因
   时钟字段天然红；
5. **错误与降级路径成文**：非法参数 4xx 防穿、无凭据 SKIP、缓存弃置重建不报错，
   且含畸形/缺失/迟到三态用例表，每条有预期行为；
6. **声称沿用既有实现的，须附故障模式取舍清单**（agent-usage.ts 八项逐项声明
   带过来/不带+理由）；
7. 交付维（delivery）真源存活期问题（lane 分支 merge 后清理 vs M3 对账已结票）
   有明确解法且写入 schema 语义。

## Nongoal（不做什么）

- **不做 v2 精确 stage 时长的设计**（只登记存在：v2=08 终态精确，触发条件留未来工单）；
- **不做交付维从 main 历史 dig 反推**：跨 epic 合并的 commit 不可分票，选固化方案
  （见块 3）；
- **健康视图不进缓存**：直查 Temporal（立项单关键决策 6）；
- **不冻结图表视觉样式**：版式归 UI 规划与效果图；
- **不做 stage 类别归一**（plan/review/implement/... 六类视图列 M3+ 可选项）；
- **不改工单引擎行为**（epic 红线，交付固化挂载点归 M1a 的桥接侧）；
- **不做计费/金额**：只做 token 数。

## Proposal（方案）

### 块 1：三维口径定义

#### 时间维

- **stage 时长 v1 = handoff 近似**：从 Temporal timeline 取 `state==='running'`
  条目的 ISO 时间戳，第 i 窗 = [from_i, from_{i+1})，末窗开放式；同角色跨 stage
  靠窗口切分，rework 重入=多窗加总。切窗实现复用 agent-usage.ts 的窗口派生逻辑。
- **末窗封口规则**：末窗右端 = min(下一窗 from, closed_ts)——closed 终态条目
  迟到时以 closed 时刻封口，开放式末窗不无限延伸。
- **human_wait** = 人门 stage（exit:human 的 stage）窗口时长合计，单独计列，
  是饼图「人审等待」橙色块与副图「人等 vs 机器」的数据源。
- **单票交付时长** = closed 终态时刻 − 创建时刻。
- **v2 = 08 终态精确**：仅登记为后续版本方向，不在 v1 冻结范围。
- 已知近似（悬停文案）：v1 时长含 agent 排队/等待间隙，非纯执行时间；口径ⓘ
  悬停声明「时长 v1=handoff 近似 / v2=08 终态精确」。

#### 交付维

- **LOC** = lane 分支 diff vs base 的 additions/deletions，**分列不合并净值**；
  M3 对账基准命令：`git diff <base>...<lane> --shortstat`。
- **base 钉死**：base = lane 创建点的主干 commit（等价于 lane 首个 commit 的
  parent）。**中途「主干合并进泳道」不改变 base**——diff 始终对创建点，口径不随
  计算时点漂移。base 的 commit hash 固化进缓存记录 `delivery.base`，重算/对账
  均取该字段，不现场再求 merge-base。
- **commits** = `git rev-list --count <base>..<lane>`，含 worker 代落盘 commit。
- 真源存活期（Requirement 7）：见块 3 固化语义。

#### token 维

沿用 t260828-07 口径：

- 只加总 `assistant/message` 事件里的 `data.usage{inputTokens, outputTokens,
  cacheReadTokens}`；`assistant/chunk`（`data.chunk.type==='usage'`）的同名
  usage 是同一份的流式镜像，**不计入**（两处都加会翻倍）；
- **cacheRead 单列**，不并入 `tokens_total`；`tokens_total` = in + out 合计；
- 模型归因：usage 事件不带模型，顺序扫描维护「当前模型」（`request/context`
  的 `data.{provider,model}` 主，`request/header` 的
  `data.header.config.{provider,model}` 兜底），每条 usage 归到当时的模型。

### 块 2：/metrics API 请求/响应契约（冻结）

```
GET /metrics?window=7d|30d|all&epic=<code|all|none>&project=<key>&template=<id>&view=time|delivery|token|health&mode=full|fast
```

| 参数 | 枚举/类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| window | `7d` \| `30d` \| `all` | `7d` | 时间窗 |
| epic | 立项代号 \| `all` \| `none` | `all` | `none`=历史无代号票兜底桶（本文档对 UI 规划 §6 的唯一枚举扩展，理由：归属依赖生成路径注入的代号，存量票无此 attribute） |
| project | 项目 key | 当前注册项目 | 越界/不存在 → 4xx |
| template | 模板 id | `dev-lane` | 决定 stage 轴链序 |
| view | `time` \| `delivery` \| `token` \| `health` | 必填 | 缺省 → 4xx |
| mode | `full` \| `fast` | `full` | `fast`=只读缓存聚合（cache-first 先吐快照，缺票不现算，`cache.status='stale'`）；`full`=全量惰性计算（t260903-09 bump） |

**错误行为**：非法值、缺必填、同名重复参数一律 `4xx {error, reason}`（重复参数
无「取首个」容错，与非法值同款防穿）。

**响应**（200）：

```json
{
  "kpis": { "tickets": 0, "closed": 0, "avg_delivery_min": 0.0, "tokens_total": 0 },
  "charts": { "primary": ChartSpec, "secondaries": [ChartSpec, ChartSpec] },
  "generated_at": "ISO8601",
  "cache": { "status": "hit|miss|computed|stale", "computed_at": "ISO8601", "source_version": "v1" }
}
```

```
ChartSpec = { kind: 'bar'|'stackBar'|'hBar'|'donut', title, categories, series[{name,data}], drill: true }
```

- `cache.status`：`hit`=命中缓存；`miss`→`computed`=本次惰性生成后回包；
  `stale`=fast 模式缓存快照（可能缺票：未算过/引擎版本失配的票不入快照；存量旧版记录按缓存计算时刻近似归窗计入，
  缺票走 reason 显式；客户端随后台 full 请求替换。t260903-09 bump）；
- **KPI 归窗单一口径（t260903-09 收口）**：tickets/closed/charts/tokens 四者同
  一 anchor——closed 票按闭单终态时刻、未结票按创建时刻归窗（gen2 成文本就如此，
  实现曾分裂出 tickets=创建归窗的第四套人口，出现「关闭数>工单数」悖论，已收口）；
- **donut 人审扇区契约字面（t260903-09 钉死）**：后端 donut 分类名「人审等待」
  是冻结字面，前端 human 扇区着色据此判定（metrics-charts.isHumanSliceName）；
  后端改名必须同票改前端 UT（tests/donut-render-dispatch.mjs），不得静默掉色；
- **度量宇宙补全（t260903-09；验收 F2/F3 修订）**：直并/收口终态票从工单列表
  消失后，度量侧从缓存存量并入聚合（template 筛选尊重；存量票 epic 不入缓存=未知，
  仅 epic=all 可见，none 桶排除——未知≠无代号），reason 显式计数「度量宇宙补全：
  N 票…」且该 notice 排 reason 首、不受 20 条 cap 截断。**锚点回落**：存量旧版缓存
  记录（无 created_ms/closed_ms）按 rec.computed_at 近似归窗计入，reason 声明近似
  计数；近似锚点只进响应、**绝不回写缓存**（防近似值永久化成真实闭单时刻）。
  列表内票的旧版记录在 full 门命中后按行内 timeline 补真实锚点并**回写升级**（一次
  性迁移），此后 fast 直接受益。无缓存记录的收口票度量侧无从补全（registry 根修
  另立工单）。**ticket list API 响应集合不因此扩大**（dispatch 流不被 archived 票
  污染）；
- 健康 view 直查 Temporal，不读缓存；
- CLI 前门：`metrics '<json 参数>'` → stdout 同一份 JSON，同实现同缓存。

**字节级一致比较面（M3 基线锁依据）**：双前门同请求的响应，比较面 = 序列化 JSON
**剔除 `generated_at` 与 `cache.computed_at` 后的全部其余字段**（键按序列化序、
UTF-8 字节全量比对）。两时间戳语义是「本次响应生成时刻 / 缓存计算时刻」，允许
双前门各自取时钟；M3 比对脚本按此剔除后比对，任何其余字段差异即红。

### 块 3：缓存记录 schema（per-ticket，冻结）

```json
{
  "ticket_id": "string",
  "template": "string",
  "durations": { "by_stage": {}, "by_round": {}, "human_wait": 0.0 },
  "delivery": { "base": "commit hash", "add": 0, "del": 0, "commits": 0 },
  "tokens": { "by_stage": {}, "by_model": {}, "in": 0, "out": 0, "cacheRead": 0 },
  "open": false,
  "delivery_frozen": false,
  "source_version": "v1",
  "engine_version": "string",
  "updated_ts": "ISO8601",
  "computed_at": "ISO8601",
  "created_ms": 0,
  "closed_ms": 0
}
```

- 正典字段串（与 UI 规划 §6 schema 行逐字一致，双文档对照用）：
  `{ ticket_id, template, durations: {by_stage,by_round,human_wait},
  delivery: {base,add,del,commits}, tokens: {by_stage,by_model,in,out,cacheRead}, open: bool, delivery_frozen: bool,
  source_version, engine_version, updated_ts, computed_at, created_ms, closed_ms }`
- **归窗锚点 created_ms/closed_ms（t260903-09 bump）**：派生字段入缓存、不入
  响应——缓存命中路径与 fast 路径据此免逐票 show 补锚点；读侧向后兼容（旧版
  记录无此两键 → 走「list 行 timeline / show 取 timeline」补齐，命中路径不重写）。
- **失效规则（t260903-09 修订）**：`source_version`（本文档版本）不一致 → 记录
  作废重算（立项单关键决策 2）；`engine_version`（模板 STAGES 链变更）不一致 →
  **只作废时间维**（durations 按现行链重算），delivery/tokens 两维与 stage 链
  无关 → **降维保留**不陪葬（KI-017②③ 收口：旧实现整条作废是 token/交付蒸发
  的缓存侧共因）。缓存整体可弃置重建，目录 `~/.sandbar/data/<project>/`，不进
  git（sandbar 关键决策 3 随迁方向）。
- **唯一例外——交付维固化（可弃 ≠ 可重算）**：delivery 维真源是 lane 分支，
  merge 落账后 lane 分支清理，已结票惰性重算无源可算，而 M3 对账恰指向已结票。
  因此 **delivery 数据在 merge_check 全绿后、落账前由确定性脚本固化进缓存**
  （挂载点归 M1a 桥接侧，引擎零触碰红线不变）；固化后 `delivery_frozen=true`，
  失效重算**跳过 delivery 维**只刷新其余维度。选项对比：从 main merge commit
  历史反推（跨 epic 合并不可分票）、只统计 lane 存活票（砍掉 M3 抽样面）均不采。
  机制上线前结的历史票无 delivery 数据（同 usage 先例：统计从功能上线算起），
  **M3 抽样须在固化机制上线后结的票中抽**。
- **主仓归档口径（t260903-09 增补，KI-017①② 收口）**：固化机制上线前的补账
  路径——泳道拆了/base_ref·worktree 缺失（直并收口票）/泳道 git 失败时，
  computeDelivery 回落主仓 `git log --grep <票id>` 提交集（merge/squash commit
  message 均带票 id；提交集口径天然不含中途并 main 吸收的进度——区间 diff 的
  8 万假交付病灶正面收口）。成功即 `delivery_frozen=true`，reason 显式标注
  「主仓归档口径」，与泳道活口径不静默混用。已知边界（W4 实测 20260903）：一
  commit 引用多票 id 时提交集口径双算；他票 commit message **引用性提及**本票 id
  （如教训引用「t260903-05 教训」）同样被 grep 命中计入本票——两类多算面均登记
  tests/delivery-recovery.mjs④，根治需 per-commit 归属归档（引擎侧 KI-017③ 同批）。
- **token 维项目级账本（t260903-09 前向契约，KI-017③）**：泳道 `.dsh/sessions`
  随泳道拆除陪葬，usage 出仓归档（merge 时刻冻结快照）落项目级账本
  `$SUYOU_USAGE_LEDGER_DIR/<工单id>/*.jsonl.zstd`（与 session.jsonl.zstd 同构，
  引擎侧 agent_activities.py 落盘，本票只留探测缝）；两处皆无 → tokens=null +
  人话 reason，不做静默 0。

### 块 4：错误与降级（三态用例表，冻结）

每条用例的预期行为（值 / 状态码 / 是否计数）：

**畸形**

| 输入 | 预期 |
| --- | --- |
| `window=abc` | 4xx `{error, reason}` |
| `view` 缺省或非法值 | 4xx |
| 同名重复参数 | 4xx（无「取首个」容错） |
| `epic` 超长或含非法字符 | 4xx |
| `project` 不存在 | 4xx |

**缺失**

| 输入 | 预期 |
| --- | --- |
| timeline 无 running 条目 | 该 stage 时长计 0 + reason 计数（不静默丢） |
| 会话文件不存在 | 软降级：200 + 空数据 + reason 人话（SKIP），UI 显「—」不报错 |
| 无凭据环境 | 200 + SKIP 提示（SKIP 属正确行为，数据恢复自动填充） |
| lane 分支无 diff | 全 0，合法数据非错误 |
| 缓存目录不可写 | 本次直算回包 + reason，不 5xx |

**迟到 / 乱序**

| 输入 | 预期 |
| --- | --- |
| rework 后 timeline 时间戳非单调 | 按 from 排序后再切窗 |
| 事件时间戳越出本票窗口 | 丢弃 + reason 计数 |
| 末窗开放式时 closed 条目迟到 | 按末窗封口规则：右端 = min(下一窗 from, closed_ts) |

### 块 5：沿用实现的故障模式取舍

声明的参考实现：`workbench/src/host/agent-usage.ts`（t260828-07，窗口派生 + 聚合）。
八项故障模式逐项取舍（**全部带过来**）：

| # | 故障模式 | 取舍 | 说明 |
| --- | --- | --- | --- |
| ① | chunk 镜像 usage 防翻倍 | 带过来 | metrics 同源数据，必须同款 |
| ② | 首窗前事件只进 total 不落 stage | 带过来 | 同窗口派生逻辑，total ≥ ΣbyStage 口径不变 |
| ③ | 会话目录/文件不存在→软降级 | 带过来 | metrics 同款：200 + 空数据 + reason 人话（SKIP） |
| ④ | zstd 不可用/解压失败→软降级 | 带过来 | 同款软降级；解压输出封顶也带过来 |
| ⑤ | 无 usage 事件→软降级 | 带过来 | 空集 200，非报错 |
| ⑥ | usage 无模型的顺序归因兜底（request/context 主、request/header 兜） | 带过来 | token 按模型分序列依赖此归因，实现共用同一函数 |
| ⑦ | 工单 id 非法/字段越界→4xx 防穿 | 带过来 | /metrics 所有 query 参数同款 4xx 防穿 |
| ⑧ | 多角色多会话文件加总 | 带过来 | per-ticket token 记录按角色会话全加总 |

**agent-usage 不覆盖的新增故障模式**（独立列出，不复用上表序号）：

- git 命令失败（分支不存在 / 非 worktree 环境）→ 该票 delivery 置 null + reason，
  软降级不阻塞整响应；
- timeline 条目缺 from 时间戳 → 该 stage 计 0 + reason 计数，不静默丢弃。

### 块 6：版本与变更纪律

- v1 冻结后任何字段增删须开新工单 bump 到 v1.x / v2，双前门基线同步更新；
- 缓存记录 `source_version` 随本文版本走；
- 与《metrics 面板 UI 规划》§6 的一致性：本文档对 §6 共**三处 delta**——
  ①契约指针行（指向本文）；②epic 枚举补 `none`；③schema 行逐字同步（含
  `delivery.base` 与 `delivery_frozen`）。无其他差异。

### 回扣

本方案逐字段冻结口径与降级 → 解决 Problem 里「并行实现各说各话、对账无据」→
满足 Requirement 1–7 → 避开 Nongoal（v2/历史反推/健康缓存/视觉样式/引擎行为
均明确划出）。

### 增补段（t260904-04，KI-040~043 收口；schema 冻结不破，本段声明语义增补）

1. **缓存命中自愈（KI-040）**：per-ticket 缓存命中不再无条件早退。两类陈旧记录
   放行全量重算路径（存量降维保留机制不变）：
   - 条件 A（失败维固化 + TTL 节流）：`delivery===null` 且记录 `updated_ts` 距今超
     TTL（env `SUYOU_METRICS_REPROBE_TTL_MIN`，缺省 60 分钟；0=每次必探仅测试；
     负值按 0）。`updated_ts` 缺失/坏值视为过期必探（NaN 比较方向已定：向「重探」
     倾斜，不给脏记录留永久静默）。重探写回恒刷 `updated_ts`=「上次尝试时刻」，
     节流锚点自洽——真不可算票每票每 TTL 周期最多付费一轮 showTicket+git。
     `delivery===null && delivery_frozen===true` 脏态同属条件 A（不看 frozen 位，
     重算门同步只看 `delivery===null`）；该态原不可达，登记防 schema 演化残留。
   - 条件 B（open 陈旧）：`rec.open` 与工单 list 行 `status` 比对不一致即刷新。
     比对是零 spawn 纯内存且不受 TTL 门；**刷新走既有全量重算路径**（closed_ms/
     timeline 从 ticket show 取——不内存改 flag 了事，否则闭单票归窗锚点退化为
     created_ms 污染 KPI 归窗）。time/delivery/token 视图（closed 派生自 rec.open）
     与 health 视图（直查 list）的 closed 计数分叉（KI-040 实证 4 vs 5）由此收敛。
     **computed_at 语义细化 + 归档近似锚点基线（验收 F1 修复，20260904）**：重算无真
     锚点（timeline 不可得，created_ms=null）时 computed_at 保留基线值（该票首次计算
     时刻，不随重探覆写为本次时刻）；本请求内重算的归档票 F3 近似归窗用重算前存量
     computed_at 作基线（响应内存面，不回写缓存）——否则治愈票近似锚点漂到窗口上界
     之外，首拍被 inWindow 静默丢弃（人口塌缩一拍，真机实证 sandbar 6→1、suyou 50→2）。
     有真锚点时 computed_at 恒为本次计算时刻；updated_ts 不受影响、恒刷（TTL 节流锚点）。
     **归档票 open 无外部真源（验收 F2 处置，20260904）**：show 不可达（返回 null）时
     open 沿用存量 flag 不漂白；归档票 open=true 在 notices 显式计数「closed 计数可能
     低计」（命中/重算/fast 三拍一致）——收口终态真源缺失是 registry 根修欠账
     （KI-031 家族，写集外），本票以显式化收口不静默；health 视图人口=工单列表直查
     为契约成文口径，「time 与 health closed 一致」判据仅在票尚在 list 的世界可测。
2. **模板过滤 reason 显式化（KI-043②）**：list 行 workflow 为空/不匹配被模板过滤
   排除的票，计数进响应 reason notices（与宇宙补全 notice 同位，不受 20 条 cap
   截断），文案=`N 票模板不匹配（workflow 为空或非 <template>）被过滤出聚合宇宙`。
3. **归档口径多提交边界（KI-040 连带，口径悬停+reason 已注）**：归档口径 reason
   首句显式「含多提交（预解/记账等提交一并计入，行数可能高于 squash 真值）」。
   **收窄口径（只认 squash merge commit）议后不落**——git 对 squash merge 无可靠
   机械判别（无 merge commit 可认，message 启发式误判面大）；根治归引擎侧出仓
   快照票（KI-017③，另立）。UI 口径ⓘ 悬停同步注明。
4. **epic/template 面板参数常量化（KI-042 宿主令）**：面板筛选行泳道（模板）与
   立项选择器退役；客户端 `template` 恒 `dev-lane`、`epic` 恒 `all` 常量透传
   （parseMetricsQuery 两参必收语义不变，localStorage 残留值读时归一弃用）；
   `project` 下拉启用（数据源 GET /wf/projects，注册表），`''`=后端缺省项目。
   请求/响应 schema 零变化。
5. **立项白名单边界（C3 声明）**：`listEpicCodes` 白名单仍按引擎仓 notes/epics
   解析（不随 project 换根）。面板立项面已退役（恒 all 不走校验），仅 CLI 前门
   显式传 `epic=<code>&project=<非引擎仓 key>` 时按引擎仓白名单校验——已知边界，
   危害休眠，随立项域多项目化（如有）另票收口。
6. **per-project repo 换根（KI-043①）**：`deps.repo` 语义收紧为「该 project 的
   注册表主目录」——buildMetricsResponse 在 project 校验通过后按
   `repoForProject(project)`（defaultDeps 缺省实现=findProject→primaryDir，任何
   注册表合法 key 含默认项目均换根；未知 key/注册表异常 null 回退传入 repo）
   本请求局部换根，git/主仓回落/会话解析随之指向项目主目录。admin CLI 通路面
   不变（按 project 传参分流）。**双前门同修**：node.ts 与 metrics-cli.mjs 同吃
   defaultDeps，无前门分叉。lane worktree 内查默认项目也指向注册表主目录（非
   worktree 自身 git）——与缓存/数据目录按项目键解析同族语义。

### 增补段（t260904-09，settle 出仓快照收口；schema 冻结不破，本段声明语义增补）

1. **settle 出仓快照（KI-017 引擎侧欠账收口）**：引擎在 merge（squash 收口）落定后、
   泳道清理前，冻结单票快照出仓到 `<projects-root>/<key>/data/settle/<票号>.json`
   （与 metrics 缓存同根约定；测试缝 env `SANDBAR_SETTLE_SNAPSHOT_DIR` 替换**项目根
   整体**，与 `SUYOU_METRICS_DIR ?? SANDBAR_PROJECTS_DIR ?? ~/.sandbar/projects` 同链，
   读写两侧同一解析语义）。快照内容：`tokens`（in/out/cacheRead、by_model；by_stage
   恒空对象+`by_stage_available:false`——引擎侧无 workflow timeline 时间窗真源，不硬造）
   + `delivery`（squash 真身 numstat add/del/commits、base、squash_commit short hash、
   `zero_change`）+ `schema_version:"v1"` + settled_at。语义：
   - **本条取代块 3「token 维项目级账本（t260903-09 前向契约）」的出仓格式约定**：
     原始会话文件（`$SUYOU_USAGE_LEDGER_DIR/<id>/*.jsonl.zstd`）出仓不再实施，改
     聚合 JSON 快照。`resolveLedgerSessionFiles` 读缝保留为兼容读位（存量外部注入
     仍可读），读侧优先级在其下，不再新增引用。
   - **幂等/不可变**：重复 settle 载荷一致=跳过；不一致（重开票等）=keep-old 不回写
     ——**已知边界：重开票增量交付不可见**（快照 reason 的 squash_commit 可发现；
     需重算删旧快照文件再 settle）。
   - **失败软降级**：快照任何失败转 note 拼进 merge 告警链，绝不阻塞 merge（观测
     欠账不卡交付，与 ui_evidence 同款 catch-all→log→不阻塞语义）。票 id 形状非法
     （不过 PROJECT_KEY_RE 白名单，含 `../` 路径穿越形态）→ fail-closed 跳过快照
     +note，不落盘（W8 打回项收口）。
   - **收口零变更（zero_change）**：squash「未产新提交」分支 HEAD message 非本票
     前缀（真·无内容可收，HEAD=他票收口）→ delivery 记零且不取 numstat（防他票
     交付错记本票）；读侧 reason 显式「收口零变更（<hash> 为 main 尾提交，非本票
     交付）」。
2. **读侧优先级（工单条 5）**：单票 delivery/tokens 取数序=**settle 快照 > 现算
   （泳道活口径/会话聚合）> 主仓归档 grep**。快照命中 → 数字=快照值、
   `delivery_frozen=true`、reason 标「settle 快照（squash <hash>）」。缓存记录
   `delivery` 对象增补**可选注记键** `squash_commit?: string` 与 `zero_change?: boolean`
   （仅快照口径写入；旧读方按多余 JSON 键忽略，向后兼容）。
3. **归档口径收窄（工单条 6；本条取代 t260904-04 增补段 3 的「收窄议后不落」结论
   与「含多提交」reason 文案）**：无快照存量票归档口径只认 **message 首行以票号
   开头**的 squash 收口提交，他账（引用性提及、预解/记账等）剔除。当初否决的是
   **子串启发式**（引用性提及票号不居首即误判；git 对 squash merge 无机械判别）；
   前缀锚定=消息首 token，squash 收口提交模板（引擎侧 `%s squash 收口…`）保证首
   token 恒为票号，误判面收敛到「手工伪造 message」。实证锚=t260904-05：grep 命中
   5 提交、前缀命中 1（真身 455320d 合计 5658；grep 合计 5783 含他账 125）。双算面
   （一 commit 双票 id）随收窄正面关闭——一 commit 只归唯一前缀票。
4. **重算触发器（SOURCE_VERSION bump v1→v2）**：口径语义变更（快照优先级+归档收窄）
   随 source_version 走（本文档版本口径），bump 后全量 per-ticket 缓存整条作废重算
   （=块 3 成文「缓存整体可弃置重建」，非红线）。已知副作用面：collectArchivedRows
   记忆行按 source_version 过滤，bump 后旧记忆行缺席（聚合宇宙暂缩，重算入口=既有
   list/全量门；在-list 票不受影响）。**存量 non-null frozen 记录无重算触发器**的
   结构面（t260904-04 自愈只覆盖 delivery===null）由本 bump 打通一次；同类未来口径
   变更须再次 bump，登记为通用纪律。
5. **donut「有无代码变更票占比」四桶（工单条 7）**：`['有变更', '已收口·零变更',
   '未交付（在制）', '不可算（数据缺失）']`，逐桶映射：有变更=add+del>0；已收口·
   零变更=delivery 非空且全零；未交付（在制）=delivery=null 且 open；不可算（数据
   缺失）=delivery=null 且 closed。四桶互斥且 Σ=票数；零变更已闭票不再与「不可算」
   混装。**已知边界（继承，不新造静默）**：归档票 open 无外部真源（openUnverified，
   KI-031 家族），「未交付（在制）」桶可能混入实际已闭的归档票。
6. **legacy 单文件注册表模式（SUYOU_PROJECTS_YAML）**：该模式只影响 host 侧 metrics
   缓存落盘（enabled:false）；settle 快照目录解析不受其影响——引擎照常写根链目录，
   读侧照读（快照与缓存独立性声明）。

## 相关文档

- [metrics 面板 UI 规划](metrics面板ui规划.md)——四视图逐图定义与面板骨架，§6 为本文示意入口
- [DeepSeek Harness and Temporal based multi-agent mechanism](deepseek_harness_and_temporal_based_multi-agent_mechanism.md)——usage 聚合口径与故障模式先例（块 1/5 依据）

> 来源立项：metrics
