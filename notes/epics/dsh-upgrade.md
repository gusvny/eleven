# 立项单：dsh-upgrade（dsh 0.1.1-rc.2 → 0.1.5-rc.2，流程化升级）

| 字段 | 值 |
| --- | --- |
| 代号 | `dsh-upgrade` |
| 状态 | 已立项（宿主 260916 当面令：「搞个 epic，做 dsh 升级」） |
| 起草日期 | 2026-09-16 |
| 起草人 | integration（sandbar 项目会话） |
| 来源 | dsh 0.1.5-rc.2 升级评估（260916，tarball 解包核对完成）＋宿主原则：「升级要有一个流程的，核心是不能影响现有的生产的使用，而且是可以回退的」 |
| 流程文档 | `notes/discussions/260916-dsh-upgrade-runbook.md`（7 步 checklist + 回退章节；本 epic 的执行细则以它为准） |

## ⓪ 说人话版（一分钟）

**dsh 是什么**：每张工单里「干活的那个 AI」背后的工具，装在这台机器的全局 npm 里，当前版本 0.1.5 之前的 0.1.1-rc.2。

**升级是什么**：把它换成 0.1.5-rc.2（会话持久化更可靠等增益，评估已做完：接口面兼容、CLI/插件都核对过）。

**为什么要有 epic 而不是直接装**：因为换版本有一个**硬坑**——新版写会话文件的**名字变了**（`session.jsonl` → `session.v3.jsonl.zstd`），而引擎里有 4 处代码按旧名字找文件，不先改，升级完引擎就「找不到会话」。所以顺序必须是：

1. **先写代码**（T1 票）：让引擎新名字旧名字都认——这步不改任何行为，纯兼容，独立可回退；
2. **再执行换版本**（按 runbook 操作，不是写代码）：停 worker → 装新版 → 冒烟 → 重启 → 开一张真工单全链验证；
3. 换坏了**随时退回**：npm 装回旧版 + 镜像 tag 切回即可；新旧会话文件都保留，双向不丢数据。

## 子票结构

| # | 内容 | 形态 | 状态 |
| --- | --- | --- | --- |
| T1 | 引擎读侧双名兼容（4 处字面名消费点，见下）＋解析不到必须响亮（不许静默零） | dev-lane 代码票 | **已交付**（t260916-23 双名兼容 + t260917-05 零静默降级，均已关；同族 t260922-02 记录类型面适配亦已关。runbook §1-T1 已勾，260923） |
| T5 | **UI 兼容面 + stage 控制台**（独立端口 3199/独立 DSH_HOME，供宿主人工测试；UI 接缝清单化） | dev-lane 代码票 | **已交付**（`t260916-25` 已关；integration 已手工搭出可用环境，票内固化为一键脚本） |
| T4 | **兼容矩阵 + 探针对账 + dsh 二进制钉路径**（见 §接缝矩阵；升级前把「会 break 的地方」逐条变成可判定判据） | dev-lane 代码票 | **已交付**（`t260916-24` 已关；门槛文本已并入 runbook §1，260923。**剩 live 双版对照实测未完成**——含 0.1.5-rc.2 复评，见 runbook §1-T4 与 §6） |
| T6 | **两插件适配新版会话视图扩展面**（`conversationViews` → `uiConversation.views`；要求双版本容错 + 显式降级） | dev-lane 代码票 | **已交付**（`t260916-26` 已关；stage 人工测试实测报障后新增） |
| T2 | 升级执行（runbook §2 七步：停 worker → npm 安装 → 冒烟 → 镜像 → 重启 → 生产冒烟票 → 观察一个巡检周期） | **操作流程，非代码票**；执行时按 runbook 打勾并记时间 | **未开工**（代码面前置已落仓 + 三问见 runbook §4；当前阻塞：队列非空＝在飞 t260922-10/-18、Q2 npm 前缀未拍板、T4 双版对照未绿、0.1.5 镜像未建——见 runbook §6 快照） |
| T3 | 容器镜像 `sandbar-agent:dsh-0.1.5-rc.2-s1`（Q3＝同升；含三处版本同步，有测试锁定） | dev-lane 代码票（小） | **已交付**（`t260921-14` 已关：三处同步锁已翻新、旧 tag 保留为回退面、回退剧本 `integration/t260921-14/ROLLBACK.md` 与机械验证在册。**但镜像本体尚未构建**，属 T2 执行前必办：见 runbook §6 第 3 条） |

## 接缝矩阵（引擎 ↔ dsh，宿主 260916 问「集成会不会 break」的答案面）

**破法三类**：硬崩（进程/命令失败，显眼）／**静默降级**（最危险：统计归零、隔离失效、模型钉错但不报错）／行为漂移（agent 行为变而系统不报）。

| # | 接缝 | 引擎侧位置 | 破法 | 探测手段 | 状态（260916 探针实测） |
| --- | --- | --- | --- | --- | --- |
| 1 | 会话文件名 | `agent_activities.py:205`（坏会话隔离 glob）、`:2826`（token 统计 glob）、`workbench/src/host/agent-usage.ts:140`、报错文案 | 静默降级：v3 文件名不匹配 glob → 隔离与统计**静默失效**（不报错、只是永远 0） | 夹具双名（v0/v3）UT + 真样本对账 | ✅ **真样本证实**：0.1.5 产出 `session.v3.jsonl.zstd`（0.1.1 产出 `session.jsonl.zstd`）；另有新伴生文件 `session.lock`。→ T1 |
| 2 | 会话**记录 schema** | token 统计解析 `request/context`、`request/header`、`assistant/message.usage.{inputTokens,outputTokens,cacheReadTokens}` | 静默降级：字段改名 → 统计静默归零/少算 | **真样本对账**（隔离前缀跑一次性会话，逐字段比对引擎解析面） | ✅ **实测通过**：三个记录类型在两代都存在，`request/context.provider|model`、`request/header.header.config.model|provider`、`assistant/message.usage.inputTokens|outputTokens` 均取到真实值。⚠️ 单轮样本 `cacheReadTokens` 缺失（0.1.5 该字段为可选）→ 需**多轮（有缓存命中）样本**验证缓存读计数是否仍上报，否则缓存读会静默少算 |
| 3 | settings/profile 钉模型面 | 泳道 `.dsh/settings.yaml`（role preset patch + `agent-default-model` 钉路由） | 静默降级：schema 变 → 钉不上 → agent 悄悄跑错模型 | 探针跑一票，断言 agent 实际使用模型 == model-routes 路由值 | ✅ **实测通过**：探针会话记录里 `request/context = {provider: zai-coding-cn, model: glm-5.3-flash}`，与 model-routes 路由值一致（旧 profile 直接跑新二进制也生效） |
| 4 | **沙箱/权限不变量** | 「worker 代落盘」设计的前提=agent 沙箱**写不了**主库 `.git` | 若新版默认策略变化 → 要么 agent 能提交（settle 语义变），要么写入被更严拦死 | 探针核策略记录 + **越界写实测**（试着往沙箱外写） | ✅ **声明面实测相同**：两代会话记录里 `permission/preset=workspace-write`、`sandbox/mode=workspace-write`、`approval/policy=ask` **逐字一致**；⬜ 越界写「实际执法」待 T4 补断言 |
| 5 | 自研 headless-resume 插件 | 项目侧插件对接 dsh 插件 API | 硬崩或静默不生效（resume 失效但流程照跑） | 探针：resume 路径实跑；对账导出面 | 🟡 部分：**旧 profile（0.1.1 装的 plugin bundle）在 0.1.5 二进制下直接跑通一票**（未报 API 错）= 插件面向前兼容；⬜ resume 专项待 T4 |
| 6 | env/`DSH_*` 面 | `DSH_HOME` 等引擎注入的隔离变量 | 硬崩或**隔离失效**（agent 写错 home） | 探针对账 + 落盘位置核对 | ✅ **实测通过**：`DSH_HOME` 指向隔离目录即落在该目录（会话/锁文件都进 `$DSH_HOME/sessions`），无外溢 |
| 7 | CLI 面（spawn 参数/退出码/结果通道） | `DSH_CMD`（`SANDBAR_AGENT_CMD`，默认 `dsh --profile sandbar-headless`）；阶段结果走**文件** | 硬崩为主 | 探针跑一票全链 | ✅ **实测通过**：同一 argv（`--profile sandbar-headless "<prompt>"`）+ 旧 profile 哈希，0.1.5 正常回包 exit 0 |
| 8 | 容器镜像面 | `Dockerfile.agent` ARG / `build_agent_image.sh` / `DEFAULT_AGENT_IMAGE` | 行为漂移：宿主 0.1.5 + 容器 0.1.1 → 同票两段行为分叉 | 版本自检点名 | ⬜ 待 Q3 |
| 9 | **console（3099，宿主操作面）** | 全局 npm 安装 = console 也用它；红线=不得重启 console | **混版**：运行中的 console 已加载旧模块不受影响，但它新 spawn 的子进程会拿到新版 | **钉路径**：引擎 spawn 的 dsh 走显式二进制路径（配置），升级只切引擎侧路径 | ⬜ T4 设计 |
| 10 | **workbench 会话日志/实时视图**（A/B 新发现！） | `host/agent-logs.ts:228`（`assistant/chunk`）、`host/agent-live.ts:198`（`assistant/chunk`/`text-chunks`/`reasoning-chunks`） | **静默降级**：0.1.5 不再写 `assistant/chunk`/`reasoning-chunks`（改为 `assistant/attempt`/`system/message`）→ 日志查看器与实时流式视图的**部分内容静默消失**（不报错） | A/B 真样本记录类型 diff + 场景断言（新代会话在日志/实时视图仍可读，缺的内容显式标注而非空白） | ⚠️ **实测确认类型差异**：仅 0.1.5 有 `assistant/attempt`、`system/message`；仅 0.1.1 有 `assistant/chunk`、`reasoning-chunks`（`assistant/message` 两代都有，故正文仍可见）。→ 需 T4/T5 |
| 11 | 回归面 | 288 条集成场景 + 巡检套件（本身就是最全的兼容测试） | — | 升级后**在隔离副本上先跑全集**，再上生产 | ⬜ T2 步骤 |
| 12 | **UI 插件扩展面（会话视图页签注册）**（stage 人工测试发现） | `server/plugins/knowledge/src/client/index.tsx:37`、`server/plugins/providers/src/client/index.tsx:34`（`inject=['slots','conversationViews']`） | **硬 break（显式报错）**：0.1.1 的 `conversationViews` 服务由 `dsh-client-runtime` 提供（`super(ctx,"conversationViews")`，该包 lib/client.js:10206）；**0.1.5 已无 `dsh-client-runtime` 包**，扩展面改为 `uiConversation.views.register(...)`（`dsh-client-ui-conversation/lib/client.js:2461`）→ 两插件 pending → UI 顶部「Failed to load plugins」 | stage 控制台起一次即可发现（脚本断言「零 pending 零 failed」） | ✅ **实测已复现并定位**：仅 knowledge/providers 受影响；workbench、admin-ui 在 0.1.5 下正常激活（宿主 API 200 实测）。→ **T6** |

**方法要点（解决「不知道会不会 break」的标准动作）**：
1. **先探针，后升级**：隔离前缀装新版（`npm i --prefix /tmp/dshprobe`，不碰全局），跑一次性真会话 → 用**真样本**对账引擎实际解析的每个字段（#2/#3/#6/#4），把「猜」变成「测得」；
2. **接缝即契约测试**：能离线造夹具的（文件名/schema）进 UT；不能的（沙箱不变量/settings 钉模型）进探针 checklist，每期升级可重跑；
3. **零静默降级**：凡解析不到的面对必须点名（T1 已含：统计/隔离看不到本版本文件要报「版本/格式不匹配」，不许静默 0）；
4. **版本钉路径 + 增量切流**：引擎只认自己路径下的 dsh（与 console 解耦）；先单票试跑 → 观察一个巡检周期 → 再全量；回退=装回旧版 + 钉回旧路径。


**T1 的 4 处消费点**（升级评估已定位）：
- `server/engine/agent_activities.py:205`（坏会话隔离 rglob）
- `server/engine/agent_activities.py:2826`（token 统计 glob）
- `server/plugins/workbench/src/host/agent-usage.ts:140`
- 相关报错文案里的字面文件名

## 三问（执行 T2 前答即可，T1 不依赖）

- **Q1 窗口**：建议=队列空的任意时点（全程 30~60 分钟）；挑你不用 dsh 的时段更稳。
- **Q2 npm 前缀**：A=sudo 装回 `/opt/homebrew` 原位（现状不变）；B=改用户级前缀（以后免 sudo，需迁移现有全局包）。二选一。
- **Q3 镜像**：容器镜像同升（推荐，版本一致）or 宿主先升、镜像留 0.1.1。

## 验收口径（epic 级）

1. `dsh --version` = 0.1.5-rc.2；会话文件落 `session.v3.jsonl.zstd`，引擎四处消费点对新旧两代文件名都工作（T1 的 UT/场景）；
2. 生产冒烟：真工单 create_plan→…→closed 全链绿，token 统计与 workbench 会话用量页正常；
3. 观察一个完整巡检周期（次日 07:30 调度触发正常）后宣布完成；
4. 回退演练（可选但推荐）：T2 完成后空跑一遍 runbook §3 回退步骤确认可逆，再宣布收官。
