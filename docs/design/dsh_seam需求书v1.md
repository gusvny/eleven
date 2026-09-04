# dsh seam 需求书 v1 —— A3 运行时模型覆盖 + A4 headless 会话延续钩子

> 供向 dsh（DeepSeek Harness）上游提 issue 或自适配引用的需求书。
> 消费对象：`notes/debts/sandbar-m0-dsh-touchpoints.md`（sandbar M0 债务盘点①）
> 定性的消解-上游两条：A3（settings 层叠 workaround）、A4（headless runner
> 内部装配 patch，立项单点名历史债务）。立项依据 = sandbar 关键决策 4
> 「dsh 零 patch、跟版升级」。
> 方案与取舍过程见 `notes/discussions/260901-dsh-seam-需求书v1-方案.md`。

## Problem（两案共用背景与事实基线）

sandbar 作为 dsh 的编排方（Temporal 工单流按 (workflow, stage) 派活给 headless
agent），对 dsh 有两个正当需求——每次 spawn 钉运行时模型、跨 spawn 延续会话
——但 dsh 0.1.1-rc.2 均无公开入口，sandbar 只能用「接触 dsh 内部实现细节」的
workaround 硬扛，dsh 任意相关变更即静默失效。事实基线（全部在本机 dsh
0.1.1-rc.2 安装树实测指认，非臆测）：

1. **A3 层叠顺序**：`@deepseek-ai/dsh-settings` 的 resolve =
   `mergeLayers(base, section)`（`dsh-settings/lib/types/index.js:175` 起，
   plain object 递归合并、`over` 后盖）——settings.yaml 用户层后盖 cordis
   patch 合成层。后果：编排方经 `--patch` 钉 `agent-default-model` 会被
   用户 GUI 写下的同段盖掉。sandbar 260826 事故即此：路由表切
   kimi-coding/zai 全部落空，agent 实跑 scnet，配额一尽全灭。现行
   workaround = 双写（patch 声明层 + 文本行摘段重写 settings.yaml 用户层，
   `server/dsh/temporal-poc/agent_activities.py:226-248`，调用点 :641）。
2. **A4 headless 无 resume**：stock runner（cordis id=`headless-runner`，
   `@deepseek-ai/dsh-headless/lib/index.js`，inject=`[agentDefaultModel,
   agents, sessions]`）固定 `sessionId: SessionId(\`session-${randomUUID()}\`)`
   （同文件 :71），无任何 create-or-resume 入口。sandbar 现行 workaround =
   每次 spawn 生成一次性 patch：disable stock runner + insert 自研
   create-or-resume runner（`server/dsh/headless-resume/node.ts`），依赖
   stock runner 的 cordis id、`headlessStartup` 注入点、
   `!!js ctx.headlessStartup.task` 求值上下文三个内部细节
   （`agent_activities.py:644-665`），任一变更 patch 即失效——会话延续
   静默丢失（回退 stock 不硬失败，最难发现的一种坏法）。
3. `DSH_HEADLESS_SESSION` 环境变量在 dsh 安装树内零命中（grep 实测）——
   系 sandbar 自定约定，仅自研 runner 消费，非 dsh 能力。

## Requirement 第一章（A3）：运行时模型覆盖须压过 GUI 用户层

### 用例

编排系统按路由表（model-routes.yaml）为每次 spawn 决定 (provider, model)；
同一台机器上用户可能在 console GUI 的 settings.yaml 写过
`agent-default-model`。期望：编排方的运行时决定优先于用户 GUI 默认值，
且不改写用户文件。

### 期望 API（两个候选，写明倾向）

1. **spawn 级显式覆盖参数（倾向）**：`dsh --profile headless --model
   <provider>/<model>`（env 形态 `DSH_AGENT_MODEL` 亦可接受）。语义 =
   最高优先级的一次性 model selection：不落盘、不改 settings.yaml、
   不影响后续进程。
2. **层叠声明**：cordis patch 条目支持 `precedence: above-user` 类标记，
   使该段 resolve 时后盖用户层。保留双文件机制，且「编排覆盖」与「用户
   手改」的优先级仍隐式依赖层叠顺序，不如方案 1 直白——故倾向方案 1。

### 行为契约

- 优先级全序写死：**CLI/env 覆盖 > cordis patch 合成层 > settings.yaml
  用户层 > 内置默认**；
- 覆盖生效路径可观测：实际生效的 selection（provider/model 及来源层级）
  在启动时打一行 stderr/日志；
- 用户文件零改动：任何情况下不写 settings.yaml；
- 向后兼容：未提供覆盖参数时，行为与现状逐字节一致。

### 对标 workaround 的故障模式取舍（参考实现 = `_pin_default_model`）

| 现状故障模式 | seam 落地后 | 理由 |
| --- | --- | --- |
| settings.yaml 不存在 → 静默跳过、路由落空（无声失败） | **消除** | spawn 参数不依赖用户文件，settings 缺失不影响覆盖生效 |
| 文本行摘段重写、dsh 改段格式即静默失配（债务清单 A3 复审触发条件的根源） | **消除** | sandbar 删除 `_pin_default_model` 双写，不再解析 settings.yaml——这正是本 seam 要消解的债务本体 |
| 用户 GUI 手改默认模型后、下次 spawn 前的重拷覆盖窗口 | **消除** | spawn 参数不落盘，窗口不复存在 |
| 覆盖值非法（provider 拼错等）→ 现状静默用错模型 | **消除** | 契约要求非法值大声报错拒绝 spawn（见验收样例 2-4） |

### 验收样例（期望行为写死，不留白给上游）

1. **happy path**：settings.yaml 带用户层 `agent-default-model` 的
   DSH_HOME 上，`dsh --profile headless --model foo/bar "say hi"` 实跑后，
   会话事件 `request/context`、`request/header` 的 provider/model 归因 =
   foo/bar，且 settings.yaml 的 mtime 与内容均不变；
2. **畸形（无 `/`）**：`--model bar` → 启动即报错、退出码非 0，stderr
   人话提示（写明须为 `<provider>/<model>` 形态），不静默忽略；
3. **畸形（未知 provider）**：`--model nosuch/bar` → 同样大声报错拒绝
   spawn，**不回落默认模型继续跑**——静默回落正是 260826 事故形态，
   契约不许它回来；
4. **畸形（空值）**：`--model ""` → 报用法错误、退出码非 0（显式传空 =
   调用方 bug，不吞、不当作未提供）。

## Requirement 第二章（A4）：headless runner 公开的会话延续钩子

### 用例

编排系统对「同工单同角色」的多次派活复用同一 dsh 会话（写方案的人就是
实现的人，打回意见在原会话里收到接着改，不再每次 spawn 从零重建上下文），
会话 id 由编排方确定性给定（如 `<ticket>-<role>`）。

### 期望 API（倾向 CLI/env 转正，不要求暴露内部服务）

`dsh --profile headless --session <id>`（或 `DSH_HEADLESS_SESSION=<id>` 被
dsh 官方认领为约定），stock `headless-runner` 的语义由「固定随机新会话」
改为 **create-or-resume**。不要求 dsh 暴露 agents/sessions 内部服务给
外部插件。

### 行为契约（6 条）

1. id 存在且可解 → resume 该会话；
2. resume 失败（会话不存在/不可解）→ 回落**同 id 新建**，stderr 一行
   人话说明；
3. 同 id 新建仍失败（典型：撕裂会话文件）→ 回落**全新随机 id**，stderr
   大声报「上下文不可恢复」，不静默、不硬失败（流程不死，但丢失必须
   可见）；
4. 未提供 id → 现行为不变（随机新会话，一次性）；
5. 任务跑完 `sessions.flush` 之后才 exit（SIGTERM 下先刷完会话文件的
   语义不变——关联债务清单 D1 复审条件）；
6. 退出码按 turn 结局：completed → 0，其余（含 error）→ 非 0
   （编排侧靠 rc 判活，关联债务清单 D2）。

### 对标实现的故障模式取舍（参考实现 = 自研 runner `server/dsh/headless-resume/node.ts`）

| 故障模式 | node.ts 现行为（行号） | 带进 seam？ | 理由 |
| --- | --- | --- | --- |
| id 空白（空串/纯空白） | trim 后按未置处理（:99） | **不带**——改为报用法错误退出非 0（契约第 4 条仅指「未提供参数」） | 空白 id 多为调用方 bug；「空白=未置」把 bug 吞成一次性会话，延续静默丢失。与验收样例 3 呼应。**这是有意收紧而非疏漏**：sandbar 侧生成 id 恒为 `<ticket>-<role>`，非空白，实际无影响 |
| launcher 未提供 ctx.appExit | 硬 throw 拒绝挂载（:157-160） | 不适用（dsh 内部装配语义） | seam 转正后走 stock runner 装配，appExit 由 dsh 自身保证，此防御留给上游实现时按其纪律自定 |
| 全部错误统一 `dsh: ` 前缀走 stderr（resume 失败/回落/退出原因） | :82、:106-107、:120-123 | **带**——契约第 2/3 条的 stderr 说明照此口径 | 可观测性：延续是否生效必须能从进程输出读出，不许静默 |
| 撕裂会话（zstd 坏帧）resume 与同 id create 双撞死 | 换全新随机 id 大声报（:118-124） | **带**（=契约第 3 条） | 基础设施故障不该杀流程，但上下文丢失必须大声说 |
| turn 结局非 completed → 退出码非 0 | :150-153 | **带**（=契约第 6 条） | 编排侧靠 rc 判活（债务 D2） |

### 验收样例（同一 DSH_HOME 下执行；含缺失态与畸形 id 态）

1. **happy path**：两次 spawn 同 `--session <id>`，第二次的会话事件流
   包含第一轮事件（seq 连续）；
2. **畸形磁盘输入**：预置截断 zstd 帧的坏会话文件后 spawn → 不 crash、
   stderr 有检疫提示、退出码按 turn 结局（契约第 3/6 条）；
3. **畸形 id（空/空白）**：`--session ""` 或 `--session "  "` → 报用法
   错误、退出码非 0（不按未置处理——取舍见表首行）；
4. **畸形 id（路径分隔符/超长/非 ASCII）**：`--session "../x"`、65+ 字符、
   含非 ASCII → 报用法错误、退出码非 0。会话 id 白名单语义须写死，
   本需求书建议 `[A-Za-z0-9_-]{1,64}`——兼防 id 被拼进会话文件路径
   （路径穿越面）；
5. **缺失态**：不传 `--session` → 现行为不变（随机新会话，一次性）。

## Nongoal（两案共用）

- 不要求 dsh 改会话落盘格式/路径（债务清单 C1 跟踪面不在此消解）；
- 不要求 dsh 感知「项目/工单」概念——seam 只收裸 id 与 model 字符串，
  编排语义留在调用方；
- 不承诺 sandbar 侧立即切换：上游发版前双写 workaround 照旧。弃用条件 =
  对应 dsh 版本落地后，sandbar 另开工单删除 `_pin_default_model` 双写与
  resume_patch 生成段（本需求书即该工单的需求输入）；
- **同 id 并发 spawn 竞态不做契约**：sandbar 编排侧保证同工单同角色串行
  spawn（Temporal activity 单飞），seam 不承诺并发 resume 同一会话的
  语义（并发 resume 视为未定义，调用方自行串行化），不要求上游加锁。

## Proposal（sandbar 侧迁移路径，供上游评估影响面）

- 上游两案可独立交付，互不依赖；A4 落地后 sandbar 删除 resume_patch
  生成段与 `server/dsh/headless-resume/`（自研 runner 退役），A3 落地后
  删除 `_pin_default_model` 与 model_patch 生成段——`--patch` 通路仅剩
  角色 preset（A1，合法消费）；
- 迁移完成即达成决策 4 对 A3/A4 的「dsh 零 patch」口径：sandbar 对 dsh
  内部实现细节（settings 层叠顺序、runner 装配、headlessStartup 求值
  上下文）的全部依赖归零，升级只看公开 CLI/env 契约；
- 本需求书事实基线锚定 dsh 0.1.1-rc.2；dsh 升版后按债务清单「dsh 升版
  必查项」复扫复核。
