---
title: metrics 面板 UI 规划
category: design
tags:
  - metrics
  - workbench
status: active
updated: 2026-09-04
---

# metrics 面板 UI 规划

> 本文是 metrics 立项（notes/epics/metrics.md）的 UI 落地规划：面板骨架、四视图逐图定义、
> 工程结构与 API 契约、分期工单映射。效果图见同目录 `metrics-mockops/`（5 张，示意数据，
> 版式为准）。改动本文档视同变更契约，需随 metrics 立项走工单。

## 1. 已拍板前提（地基，评审五轮结论）

- 四视图：时间分布 / 交付量 / Token 消耗 / 系统健康；入口在下栏 settings 旁；
- 图表库 **ECharts**，经 adapter 隔离（唯一 import echarts 的文件是 metrics-charts.ts）；
- 存储三层：真源只读（Temporal timeline / git / ~/.dsh 会话文件）→ 可弃聚合缓存（运行时
  数据目录，记录带 source_version/engine_version/updated_ts 版本化失效，不进 git）→
  聚合服务（host /metrics + node CLI 双前门，字节级一致，基线锁死）；
- 多模板：聚合键=（模板, stage）；跨模板不混排；
- 饼图纪律：占比类用环形，趋势/排名类用柱/条；
- Temporal 原生 Prometheus/Grafana 归 sandbar M2，本规划不做。

## 2. 入口与导航

- 下栏重构：左「📊 度量」按钮 + 右 ⚙ settings 图标（原 sandbar 驻留内联输入收进 ⚙ 弹层，
  弹层同时容纳「静默在制阈值（分钟）」等健康 tab 参数）；下栏高度不变；
- 点击「度量」= 全幅覆盖面板（类 epics 全页视图，不用右侧抽屉——图表要宽度），Esc/✕ 关闭；
- 面板状态（tab/筛选器/时间窗/项目）存 localStorage，重开恢复。

## 3. 面板骨架（四视图共用）

> **t260904-04 修订（KI-042 宿主令）**：筛选行收敛为 `[时间窗▾][项目▾]` 两下拉——
> 「立项▾」「模板▾」退役（模板恒后端缺省 `dev-lane`、立项恒 `all`，由 loadPanelState
> 归一常量透传，localStorage 残留值读时弃用，防旧存值锁死非 dev-lane 模板导致空面板）；
> 项目下拉启用（数据源 GET /wf/projects 注册表，`项目：默认`=后端缺省 + 各项目 key）。
> 下图骨架行以修订后为准。

```
┌────────────────────────────────────────────┐
│ 度量  [时间窗▾][项目▾]  口径ⓘ ✕              │
│ KPI 条：工单数│关闭数│均交付时长│Token 总量    │  ← 任何 tab 常驻
│ [时间] [交付] [Token] [系统健康]             │
│ ┌────────── 主图（每 tab 一张） ───────────┐ │
│ └──────────────────────────────────────────┘ │
│ ┌─副图1──┐ ┌─副图2──┐                        │
└────────────────────────────────────────────┘
```

- 「口径ⓘ」悬停声明：时长 v1=handoff 近似 / v2=08 终态精确、token 不含 cacheRead（悬停可见）、
  缓存时间与 source_version；
- **下钻全局规则（第一红线）**：任何柱子/扇区可点 → 侧滑构成清单（票 id/标题/数值）→
  点票跳既有详情抽屉。

## 4. 四视图逐图定义

### Tab 时间
- 主图：**stage 时长分布**，柱↔饼双形态。柱：X=stage（所选模板链序）、Y=耗时，均值切换
  （平均/P50/P90）；饼「时间去哪了」：单票平均占比环形，**人审等待独立一块橙色**，
  中心大字「N 分钟 · 其中人等 X%」。下钻=该 stage 慢的票清单；
- 副 1：单票耗时排行（横条 Top N，点击跳详情）；
- 副 2：人审等待 vs 机器时间（每票 100% 堆叠条，橙=人等）。

### Tab 交付
- 主图：按周分组柱，序列=additions/deletions 双序列（不合净值）；计量切换器
  （LOC/commits/工单数三模式共用图）；
- 副 1：按 epic 份额环形；副 2：按角色柱；
- 图下脚注钉死口径：LOC=diff vs base 分列；commits=lane 分支计数（含 worker 代落盘）；
  tooltip 逐票列明。

### Tab Token（沿用 t260828-07 口径：cacheRead 收悬停）
- 顶切换：**工单视角 / 全机会话**；
- 主图：按日堆叠柱（X=日，序列=模型，值=in+out 合计），下钻=当日按票清单；
- 副 1：per-stage 均耗柱；副 2：单票 Top N 表；
- 空态：无凭据环境「SKIP 属正确行为」黄条（数据恢复自动填充）。

### Tab 系统健康
- KPI 卡：在制 / 等人审 / blocked / 今日 closed；
- 主图：票流按日堆叠（新建/关闭/在制末态/人审末态）；
- 副 1：blocked 榜（当前 blocked 票+原因+已卡时长）；
- 副 2：**静默在制清单**——running 但 N 分钟无活动心跳的票（阈值默认 15，⚙ 弹层可调），
  红点脉动告警。

## 5. 多模板口径

> **t260904-04 修订**：「模板▾」选择器已退役，模板恒 `dev-lane`（后端缺省）——
> 主图 stage 轴即 dev-lane STAGES 链序；聚合存储键=（模板, stage）不变，跨模板
> 不混排契约不破。多模板切换 UI 待宿主重开（须随契约 bump）。

- 模板决定主图 stage 轴（该模板 STAGES 链序）；聚合存储键=（模板, stage）；
- 单票维度图（耗时排行/人等 vs 机器）与模板无关；
- 跨模板 stage 不强映射；「stage 类别」归一视图（plan/review/implement/test/gate/human
  六类）为 M3+ 可选项，不进 v1。

## 6. 工程结构与 API 契约（M0 冻结）

新代码收在三个新文件 + 一个 CLI：

- `server/plugins/workbench/src/client/metrics.tsx`——面板/视图/筛选/KPI 条（wb- 前缀 CSS 惯例）；
- `server/plugins/workbench/src/client/metrics-charts.ts`——ECharts adapter：
  暴露 `stackBar()/groupBar()/hBar()/donut()` 四工厂（入参 categories+series+onDrill），
  视图层不见 echarts 类型；
- `server/plugins/workbench/src/host/metrics.ts`——聚合唯一实现（三源读取+可弃缓存+失效）；
- `metrics-cli.mjs`（workbench 下，挂 server/tools 桥 = dsh tool「metrics」）——argv→参数→
  stdout JSON，与 HTTP 同实现同缓存。

**API 契约（v1，字段级冻结真源见《[metrics-api契约v1](metrics-api契约v1.md)》，本节为示意）**：

```
GET /metrics?window=7d|30d|all&epic=<code|all|none>&project=<key>&template=<id>&view=time|delivery|token|health&mode=full|fast
→ {
    kpis: { tickets, closed, avg_delivery_min, tokens_total },
    charts: { primary: ChartSpec, secondaries: [ChartSpec, ChartSpec] },
    generated_at, cache: { status, computed_at, source_version }
  }
CLI: metrics '{"window":"7d","view":"time",...}'  → 同一份 JSON
```

ChartSpec = { kind: 'bar'|'stackBar'|'hBar'|'donut', title, categories, series[{name,data}], drill: true }。
缓存记录 schema（per-ticket）：`{ ticket_id, template, durations: {by_stage,by_round,human_wait},
  delivery: {base,add,del,commits}, tokens: {by_stage,by_model,in,out,cacheRead}, open: bool, delivery_frozen: bool,
  source_version, engine_version, updated_ts, computed_at, created_ms, closed_ms }`。
（t260903-09 bump：mode 参数、cache.status 增 stale、缓存锚点 created_ms/closed_ms——
语义见 metrics-api契约v1.md 块 2/块 3 增补段。）

## 7. 分期→工单映射

| 单 | 内容 | 前置 |
| --- | --- | --- |
| M0 | 口径文档（docs/design/metrics-api契约v1.md）+ API 契约冻结 | 现在可开（纯 docs） |
| M1a | host /metrics + 可弃缓存 + CLI 前门（挂 tools 桥） | M0；等 t260901-08 落账（并行位纪律，写集不撞） |
| M1b | 泳道图节点耗时（drill-down 最小消费方） | 现在可开（09 已落，写集不撞） |
| M2a | 面板骨架 + KPI 条 + Tab 时间 | M1a |
| M2b | Tab 交付 + Tab Token（含全机开关） | M2a |
| M2c | Tab 系统健康（含静默在制） | M2a |
| M3 | 对账验收（3 票人工核对）+ 双前门一致基线 + 推导基线 | 全部 |

写集纪律：M1a/M2 系列=workbench src/client + lib 产物 + host/metrics.ts(+node.ts 路由) +
integration/（基线）；**引擎零触碰**写进每张单红线；M1b=workbench src/client + lib + integration/。

## 8. 全面板验收红线

数字可下钻到单票；口径悬停可见；tab 切换 <500ms（缓存命中）；echarts 不出 adapter；
每视图有空态；面板纯只读（零写操作）；CLI 无 console 环境独立出数；双前门字节级一致
（integration 基线锁）。

> 来源立项：metrics
