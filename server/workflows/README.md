# 工作任务模版 —— 真源=代码（M11 v2 模版即代码）+ 版本治理与确定性编码规约

**2026-08-22 架构转向（用户两轮纠偏定稿，工单 t260822-m11-template-as-code）**：
模版真源从本目录 yaml 改为 **每模版一个 workflow 类**（`server/engine/`
下 `base.py` 的 `TicketWorkflowBase` + 各子类一文件——260824 起 code-lane /
build-workbench 已删；**260904 宿主令 content-pipeline / proofread / regression /
cleanup 四模版退役，现仅存 dev-lane**，本文与旧档中的「六模版/五模版」为删前措辞）。本目录的 `<id>.yaml`
降为**从类定义生成的人类可读参考快照**——由 `engine/gen_workflows_doc.py`
生成，头注「真源=代码，勿手改」，重跑即覆盖；改模版 = 改子类 STAGES + 重跑生成器
（`.venv/bin/python gen_workflows_doc.py`，`--check` 可验漂移）。

出处：设计文档 `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
「工作单与角色间协作」节的架构转向段 + 实施波次 M11 v2 行。

## 1. 架构速览（v2：模版即代码 + stage 即 activity + 状态只在 workflow）

- **每模版一个 workflow 类**：stage 链/脚本门/人门写死在子类的 `STAGES` 类属性
  （`Stage` 元组：id/name/role/desc/acceptance/next/exit/fanout/revision_to/gate/parts——
  parts=执行主体组合声明（agent/script/human 可组合，t260828-01），静态展示元数据，
  动态真源仍是 Temporal history；任一 stage 缺 parts 生成器硬失败）。
  共享机制（主循环/签字/打回/记账/快照）全在 `base.py` 的 `TicketWorkflowBase`。
- **stage 即 activity**：agent 段 = activity（名=stage 名）spawn headless agent
  （`dsh --profile suyou-headless "<派活指令>"`，工作目录=工单工作空间），
  轮询结果文件 `.suyou/stage_<段>_gen<N>.json` + 心跳；**幂等**=结果文件已存在则
  直接读文件返回（Temporal 重试/worker 重启安全）；rework 重跑靠 gen+1 换新文件。
  脚本门段 = `script_gate` activity（现状复用，绿才推进，红则 blocked 等
  `retry_qc`/`rework` signal）。人门段 = `prepare_human_gate` activity 做机械准备
  （提案摘录/工作空间清单/diff stat）→ workflow 级 `wait_condition` 等 `sign` signal。
- **状态只在 workflow**：`tickets/*.json` 投影取消——v2 工单全程不落 JSON；
  读走 query（`snapshot` 含 meta 全文，JSON 兼容形态）；工单台/`ticket.py` 经
  `client.py ticket-list / ticket-query` 读 Temporal；`ticket.py` 退化为薄壳
  （create→`ticket-start`，update/rework 转发，accept/advance/dispatch-next 对
  v2 工单结构化报错「已取消」）。有 JSON 的存量工单一律走旧路径。
- **自动推进**：dispatch-next 与逐项 accept 取消——workflow 过门自动进下一段；
  验收=事后看产物（snapshot 的 results/handoffs）；rework=signal 回目标段重跑
  （payload 带 target_stage 与返工指令；修订回路机制随 content-pipeline 模板于
  260904 一并退役，机制数据仍留存 shared.py）。
- **老类已退场（260823）**：老 `TicketWorkflow` 类与 tickets/ JSON 投影目录一并删除
  （存量工单全部 closed，历史查 git）；新工单由 `ticket.py create` 按
  `shared.TEMPLATE_CLASS_NAMES` 映射走模版子类（dev-lane 为 activity 直编排），create 必传 project。

## 2. 确定性编码规约（写/改 workflow 代码的硬约束，review 工单照此核）

以下为用户 2026-08-21 明令，原文照录设计文档（v2 全程适用）：

> - workflow 函数体里**只允许确定性逻辑**：禁止 wall-clock 时间（用 `workflow.now()`）、
>   禁止 random、禁止网络/文件/子进程 IO、禁止读外部可变状态（环境变量、全局单例、
>   工单 JSON 文件等）——一切副作用与不确定输入都进 **activity**，workflow 只消费
>   activity 的返回值。
> - 跨调用的可变状态只放 workflow 实例字段；外部输入一律走 input / signal / update /
>   query 载荷。
> - 「绿才推进」的判据只看 activity 返回的**结构化字段**（如 qc_run 的 `green`），不在
>   workflow 里重新解析文本输出。
> - 改流程代码必须 `workflow.patched()` 开版本分支：workflow 会被 Temporal 从头 replay，
>   非确定性改动会让 running 老实例直接卡死（这是引擎级的确定性强制，也是规约存在的原因）。

v2 补充（同样硬性）：

- **派活指令组装是纯函数**（`shared.build_stage_prompt`）：从 workflow 上下文
  （handoffs/前段产物/工作空间路径）拼 prompt，零 IO，workflow 内确定性调用。
- **agent 段交付契约**：结果文件 `{status, summary, deliverables, files_changed,
  evidence}`——workflow 只看结构化字段判成败；agent 进程退出却没写结果文件 =
  基础设施故障（activity 重试），不是业务失败。

## 3. 版本治理规矩（v2）

| 层 | 是什么 | 怎么改才安全 |
|---|---|---|
| 模版定义 | 五个子类的 `STAGES` 类属性（真源） | 直接改代码+重跑 `gen_workflows_doc.py`；对**在跑工单不生效**（启动时钉死），新工单自动用新版 |
| 流程代码 | `base.py` 主循环/信号/update 处理 | **每个子类独立 patched id**（`<模版>-v3` 起）：改执行逻辑必须新增/bump 本类 PATCH_ID 并在变更点 `workflow.patched()` 分支，老实例 replay 走旧分支 |
| yaml 快照 | 本目录五套（生成物） | 不手改；漂移检测 `gen_workflows_doc.py --check` |
| 在跑工单实例 | workflow 历史 | 改不了；要么 patched 兼容，要么 terminate 重跑（轻任务判据见 §3.3）/ 老类工单 re-adopt（§3.2） |

### 3.1 何时用 patched（改流程代码）

- 改 `TicketWorkflowBase._main`/信号/update 处理，或改某子类 STAGES 且**希望本类在跑
  实例不破**：bump 该子类 PATCH_ID，变更点 `workflow.patched()` 分支。五类 patched id
  各自独立（一类 bump 不影响他类 replay）。
- 只给 `Stage` 加带默认值的**元数据字段**（不改已执行路径，如 t260828-01 加 parts）
  不触确定性，无需 bump；用 `engine/replay_check.py` 对存量 RUNNING 工单做
  replay 实测兜底（只读拉历史 + temporalio Replayer 逐条回放）。
- 拿不准就 patched——成本极低，漏一次代价是整批 running 实例卡死。

### 3.2 换流程 = terminate + 新建

260823 起无 re-adopt 通道（adopt.py 随投影目录删除，v2 工单状态只在 workflow）。
要换流程：terminate 旧实例 + 按 §3.3 判据新建。

### 3.3 轻任务直接 terminate 重跑新版的判据

设计文档原文口径：「如果多版本兼容的难度很大，大多数情况下，只要这个任务不是很重量级，
那完全可以不要过去的任务，重新用新版本跑一遍即可。」落地判据——**同时满足**即可直接
terminate + 新建工单跑新版：

- 工单还在早期段（如 develop 未交付、未产生合并进主树的成果），重跑成本低；
- 没有不可再生的中间产物（审批签字、人工验收结论、跨会话泳道成果）会随 terminate 丢失；
- 兼容（patched 多叠一层）的成本明显高于重跑一遍。

### 3.4 多版本并存是过渡态，非常态

- 新老引擎并存只为「存量工单跑到自然 close」；**老 TicketWorkflow 在存量全 close 后
  从 worker 注册表退役**（届时本节目档可删）。
- 不要把「多版本长期并存」当成能力建设方向；并存期间的管理成本由改动方承担。

## 4. 模版一页索引（真源=类；STAGES 摘要）

**260904 宿主令：仅存 dev-lane**；content-pipeline / proofread / regression / cleanup
四模版已退役（类文件与 yaml 快照删除，票收口后独立回归能力由 integration main 侧
直跑或开 dev-lane 承担；历史 workflow 终态快照零触碰）。

| 模版 id | workflow 类（文件） | 用途 | lane | 脚本门（Stage.gate） | 人门 |
|---|---|---|---|---|---|
| dev-lane | `DevLaneWorkflow`（dev_lane.py） | 开发泳道（developer 系唯一流程，260824 起） | worktree | merge_check（程序化四项，activity 内直跑） | merge（合并签字） |

> 类名说明（历史注记）：步1 的 `ContentPipelineWorkflow` 类名已被在跑实例占用（workflow type 名进
> 历史不可改），content-pipeline 的 v2 类曾用新名 `ContentPipelineTicketWorkflow`（260904 随模板退役）。
> M10 五角色归一：approve/final-review 等旧 dispatcher 段在 v2 类里直写 integration。
> 260824：code-lane / build-workbench 两模版删除，developer 系统一走 dev-lane
> （activity 直编排，不走 base.py stage 机；STAGES 仅展示/推导元数据）。

- **dev-lane 步链**（activity 直编排，步名=activity 名）：prepare_workspace（代码）
  → create_plan(developer) ⇄ review_plan(integration，打回循环≤5)
  → implement(developer) ∥ design_integration_tests(integration)（并行分叉，asyncio.gather；
    汇合点统一代落盘 settle_lane，两边齐活才前进）
  → ui_evidence（仅 UI 票：汇合落盘后 worker 代跑 capture-lane 隔离台截图；非 UI 票跳过直达
    run_integration_tests，软失败不拦主链，merge_check 证据闸兜底）
  → run_integration_tests（程序化：按 integration/manifest.json 逐条跑，0 commit 闸前置，
    结果 JSON 交仲裁）
  → arbitrate（integration 三态判定：pass/tests-fault/code-fault，tests-fault 自行迭代重跑、
    code-fault 打回 implement，轮次上限见类内常量）
  → acceptance_walkthrough（integration 以用户视角走查新功能写验收报告，发现代码问题打回
    implement）
  → merge_check（程序化：泳道有 commit / 工作区干净 / 泳道内 verify_lane code 绿 /
    merge-tree 预演无冲突——红灯即 blocked）
  → **merge（人门）**：签字通过 → merge activity 真合并进 main + 泳道清理 → closed。

（content-pipeline / proofread / regression / cleanup 四模版的 STAGES 段链与执行
主体组合已随 260904 退役删除，历史段链查 git 或 docs/design 设计档。）

各段验收清单（acceptance）以类定义为准，快照 yaml 逐字同构（生成器回读校验）。

各段执行主体（parts，t260828-01；🤖 agent / ⚙️ 脚本 / 👤 人，组合态直接拼接）：

- **dev-lane**: create_plan🤖 → review_plan🤖 → implement🤖⚙️（worker settle 代落盘 +
  自测/verify 脚本门）∥ design_integration_tests🤖（并行分叉）→ ui_evidence⚙️（UI 票
  capture-lane 隔离台截图，非 UI 票无此步）→ run_integration_tests⚙️ → arbitrate🤖⚙️
  （三态判定）→ acceptance_walkthrough🤖⚙️（验收走查）→ merge_check⚙️ → merge👤⚙️
  （人签字 + merge 落账 + 泳道清理）。

口径：引擎管道件（结果文件轮询/幂等缓存、prepare_human_gate 机械准备、非 worktree
泳道 no-op 的 settle）不计入；业务产物落账必需的脚本计入。
