# t260924-04 票1 验收走查报告（integration，acceptance_walkthrough gen5＝最终）

结论：**通过（status=ok）**——票1 全部七项验收口径在真舞台与离线契约面双实证
通过；场景② journey **14/14 全绿**（A1 全链、A1 续跑、A3/A7 建票拒收与归属边界），
场景① 33/33 绿，收窄守卫 35/35 绿。本走查轮零代码缺陷；残余红全部归因为
**测试资产观测面选点**，已在本轮以写集内最小修正收敛并复跑实证。

## 逐场景结论（最终）

| 场景 | 结论 | 证据 |
|---|---|---|
| ①登记即加载＋逐模板隔离拒收（离线契约面，33 断言） | **过** | 本轮机械闸 exit 0；上轮走查独立探针四态复核（好模板四表同现／缺 STAGES 点名／撞名双方／加载失败隔离） |
| ②journey 真舞台（14 断言） | **过** | 本轮隔离台实跑：A1 外置模板票 worker 拉起→受理→j_one/j_two 段序推进→closed；A1 续跑（段在飞停 worker→重起→同票走完）；未知模板文案分项目可见（A 见 dev-lane+journey-two-step、B 不见他项目登记）；A3 被拒模板建票 fail-closed 且点名检查＋来件；A7 坏项目 dev-lane 照常建票可查 |
| t260904-08 收窄守卫（35 断言） | **过** | 移交命令实证 exit 0（C/E/F 全段；F 段经 gen2 资产时序修正后绿） |
| UI/泳道图渲染 | 不适用 | 本票无 UI 改动 |
| ⑥安全面 | 不降级 | 外置模板走 TicketWorkflowBase 同一基类；client.py USAGE 无 set-stage/force_stage 入口（工具面白名单零变动） |

## 本轮做了什么（含残余红归因）

上轮移交的 journey 复跑仍 FAIL，本轮逐层剥洋葱，确认 D7 修复本身有效（worker
日志：`j_one` 活动已注册、段序推进、`j_two/closed workflow 完成`、专属 worker
收口自退），残余两处均为**场景观测面选点**问题：

1. **观测面（既有引擎面，非本票缺陷）**：场景 poll 用的裸入口
   `client ticket op=query`，其跨项目闸前置读走活工作流 query——专属 worker 收口
   自退后对已收口票恒报 `RPCError: no poller seen for task queue recently`。
   **判别实验**：同流程跑内置 fixture-two-step（模板无关）同样复现 → 引擎既有面；
   而 `ticket-query` 子命令（describe/result 路径，client.py COMPLETED 分支专为此
   而设，KI-025 注释在案）在 worker 自退后正常返回全量快照。→ KI 候选（见下）。
2. **观测解包**：`ticket-query` 面形状为 `{exec_status, snapshot:{status,stage,…}}`，
   场景 cond 按票面顶层字段判——query() 增加解包到票形 snapshot（观测语义与
   原意图完全同源，非弱化：断言面一字未松，A1 closed/续跑/A3/A7 全部照原判据过）。

修正后 journey 全量复跑 **14/14 PASS**（约 272s，可复现）。

## 测试资产变更审查（对照打回轮）

- developer 侧（D7）：`workflows_v2.PROJECT_TEMPLATE_STAGE_IDS`（agent 段过滤与
  `Stage.kind` 语义一致：exit=human→human 门、agent=False→script 闸，均正确不收）
  ＋ worker activities 装配补注册（同一 `make_stage_activity` 工厂，agent_
  termination guard 同款）＋ `test_d7_external_stage_ids_for_worker_activities`
  回归（agent/human/闸混合＋被拒模板零残留）——契约精确化，UT 74 passed。
- 仲裁侧：poll 超时消息带末回执全文（可诊断化）。
- 走查侧（本轮）：journey `query()` 两处——观测子命令切换（ticket-query）＋
  snapshot 解包。逐条核为「让断言面真正到达原判据」的取数修正；14 条断言判据
  与设计登记逐字一致，无绿灯捷径（closed/续跑/归属边界的判据全部真跑到达）。

## 附带发现（上报登记，非本票范围）

- **KI 候选 #A**：裸入口 `client ticket op=query` 对「已收口票＋专属 worker 已退」
  恒报 `RPCError: no poller seen…`（kind=internal）——闸前置读用活工作流 query，
  未走 COMPLETED 分支的 describe/result 路径。模板无关（内置夹具同判复现，判别
  探针留档 `/tmp/probe_fixture_query.py` 逻辑，报告归档）。修复方向：该入口前置读
  先 describe、COMPLETED 走 result（与 cmd_ticket_query 同款）。
- **KI 候选 #B**（implement 同轮已上报，本岗附议）：段 activity 重试窗口内票面
  `stage=None/timeline=[]` 的可观测缺口——内置模板同样形态。

## 收口两问（留痕）

- **doc_sediment**：`want=true`——加载口文档 §五「sandbox 兼容双层防线」已由
  implement 落实（D3/D6 事实在册，含受限 importer KeyError 机理）；剩余两条建议：
  ① §五补一句「passthrough 符号实名＝`temporalio.worker.workflow_sandbox.
  SandboxRestrictions`（1.18.2 无 WorkflowSandboxRestrictions 别名，写错＝worker
  启动即崩，D4 实录）」；② §二/§六补「外置模板段驱动 activity 由引擎按 STAGES
  自动接线（D7），项目侧不写 activity 函数」。另：KI 候选 #A/#B 若成立，登记时
  挂工单号（加载口票外）。
- **doc_conflicts**：实际读 docs/README.md、加载口文档 v1（§五/§六）——文档主张
  （双层防线、passthrough 全集、演进纪律、安全面原文）与实现/行为面一致，无推翻；
  历史全部 pending-doc-sync 条目已闭环。

## 遗留与风险（移交人审）

- KI 候选 #A（query 裸入口 no-poller）建议随专门票处置；在它修复前，一切「收口后
  查票」的观测面请走 `ticket-query` 子命令或 ticket.py show（工作台 API 面另计）。
- t260921-06 批契约守卫的基线欠账维持不归属（与前几轮口径一致）。
- 本轮我（走查）改动仅 journey 观测面一处；工单其余交付物清单与上轮一致。
