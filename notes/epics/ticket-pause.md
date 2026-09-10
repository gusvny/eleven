# 立项单：ticket-pause（工单段间暂停/恢复）

| 字段 | 值 |
| --- | --- |
| 代号 | `ticket-pause` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-09-08 |
| 备注 | 首票=t260908-01（引擎+UI+集成一票全包）；设计基准=本文档 |

## 拍板（260908 宿主，四条）

1. **粒度=段间暂停**：当前段（含在飞 agent activity）自然跑完，workflow 停在段间
   门口等待，不派下一段；恢复后接着走。不打断在飞 activity。
2. **权限=仅人门**：pause/resume 只从 client.py CLI 信号通道进（与 sign/rework
   同族），agent prompt/activities 无发送入口，代签纪律同现有。
3. **一票全包**：引擎 + UI 同票交付。
4. **通用性=base 通用层**：实现落在所有工单 workflow 共用的共享骨架
   （`server/engine/base.py` 的 `TicketPauseMixin` + `shared.py` 的
   `PauseRequest`/常量），换一个 workflow 模板同样生效；dev_lane 侧零私有改动
   是验收项（机械审计=继承+一个门调用点+snapshot 并键，diff ≤5 行接线）。

## 机制

- **信号**（`TicketPauseMixin`，base.py）：`pause(PauseRequest)` /
  `resume(PauseRequest)`。temporalio 装饰器可继承（base.py 头注已证 1.18.2），
  子类零重定义。
- **段间门** `_pause_gate()`：主循环每次相位/段切换前调用；未暂停零开销返回；
  已暂停→`_paused_at_gate` 置位 + `wait_condition` 等 resume。门本身是 await 点，
  事件循环让出，暂停期 snapshot 查询照常（KI-008 相邻面天然覆盖）。
- **回放安全**：`PAUSE_PATCH_ID="ticket-pause-v1"`（shared.py）。老 RUNNING 实例
  （功能上线前开出的票）事件历史无 marker → 门重放 no-op（KI-003 _breathe 同款
  纪律）；且 pause 信号内有 patched 前置拒收分支——老实例收 pause 得 refused
  「该工单启动于暂停功能上线前，不支持暂停」，杜绝「徽标说暂停、workflow 照跑」
  的误导信号（KI-018 同族；review_plan R4）。resume 不需同款分支：老实例
  `_paused` 恒 False，自然落空态拒绝。
  （更正记录：temporalio 对无 handler 的信号是**投递成功、worker 侧丢弃告警**，
  不是投递被拒——老部署（无该 handler 代码）不受影响。）
- **反馈可辨（幂等）**：重复 pause / 空态 resume / 畸形 payload（who 空·纯空白、
  note 超 `PAUSE_NOTE_INPUT_LIMIT=20000`，host_ruling 同源值独立常量）均落
  `refused`（文案点名原因、不进事件历史，intake gate 双形态）；成功 pause/resume
  落 `_log`+timeline（`paused`/`paused-waiting`/`resumed`）。
- **快照二态**：`paused`（bool）+ `paused_phase`（`pending`=已受理待段间生效——
  当前段还在跑/在人门/blocked 等位；`at_gate`=已停在段间门口）。UI 徽标按此
  二态文案，防「已暂停却还在跑」误读为 bug。

## 显式语义声明

- **暂停是正交维度**：不碰 status/stage_state 状态机。blocked 票可暂停（语义=
  retry_qc 重跑完本段即停门口）；awaiting-human（merge 人门）票可暂停（人门等
  签字与暂停等 resume 互不干扰）。
- **pause×rework**：门插在 rework 分支之前——暂停期间到达的 rework 压在门口，
  resume 后循环先走 rework 分支（打回先于下一段派发）。场景 L3.5/L3.6 断言。
- **末段边界**：暂停发生在最后一段执行中时，循环自然结束、工单收口（无下一段
  可停）——非故障形态，paused 位随 resume/终结清理。

## 通道与 UI

- **CLI**：`client.py ticket op=pause|resume`（payload 兼容 input 包装与顶层直给
  两形）；USAGE 同步。agent 面无发送入口（selfcheck 源码锁看住）。
- **host**：workbench `node.ts` OPS 白名单 + `pause`/`resume` 分支——照
  sign/retry-qc 先例 runPocCli 直调 engine client.py，**不经** server/tools/
  ticket.py（该文件不在票写集），不造旁路；通道失败（非零退出/120s 超时/非
  JSON）由调用点 try/catch 转 502 结构化，前端走既有 apiPost 错误通路。
- **列表入口**：ticket-list 行携带 `paused`/`paused_phase`（client.py
  `_meta_of` 把 snapshot 顶层键并入行形状）；行卡徽标二态 + 暂停/恢复操作位
  （busy 禁用+stopPropagation 同族纪律）；`availableOps` 任何进行态给键
  （blocked 含，取舍见上），closed 无。推导住纯函数层（ticket-list-model.ts
  `pauseOpOf`/`pausedBadgeText`），index.tsx/行卡只消费。

## 夹具模板与通用性验收

- `server/engine/fixtures/fixture_two_step.py`：TicketWorkflowBase 最小两段子类
  （fx_step_one→fx_step_two），零私有逻辑，clean-module（temporalio sandbox 重
  执行定义模块，零模块级 IO——fixture_ticket_fake 头注同款约束）。
- 注册走 `SANDBAR_FIXTURE_TEMPLATES=1` 环境门（workflows_v2 TEMPLATE_CLASSES/
  ALL_WORKFLOWS_V2 + shared.TEMPLATE_CLASS_NAMES/TEMPLATE_DISPLAY_NAMES 同门同款）：
  默认面恰 {dev-lane}，收窄守卫（sc_template_face_narrowing）与生产板不受影响。
- 通用性验收两层表述：①dev_lane diff 审计=暂停语义零行、接线 ≤5 行（「零私有
  逻辑」）；②夹具模板行为断言=新模板接线 ≤N 行即暂停生效（非「零改动即生效」）。

## 验收（integration/t260908-01/sc_ticket_pause_gate.py）

主旅程（dev-lane 真链路，SANDBAR_AGENT_STUB=1 桩脑+真 activities+真
DevLaneWorkflow）：开票→在飞段 pause→段自然跑完→停段间门口（paused+at_gate+
paused-waiting）→观察窗不派下一段→重复 pause refused→列表行 paused→暂停中
rework 压门口→resume→先打回再推进→走完全链（预置仲裁 verdict=pass→merge 人门
sign）→closed。反馈腿：空态 resume/who 空白/note 超限三笔拒收可辨不置位。
通用性腿：fixture-two-step 同款暂停/恢复/走完 + env 门关开票拒收「未知模板」。
拓扑过嵌套护栏（review R3 核准形态）：子进程 env 剥泳道标记三件套
（SANDBAR_TASK_QUEUE/SANDBAR_TASK_QUEUES/SANDBAR_WATCH_WORKFLOW）+钉
sandbar-ticket-<票id> 专属队列+只连 stage_docker 一次性测试台+L0 自证腿——
ticket-lifecycle 移出闸教训的收窄声明（护栏原文与其处置不动）。
docker/舞台缺件=ENV_FAIL exit 2（环境缺失口径，非拓扑性永红）。

## 故障模式取舍清单（review_plan R1 纪律产物）

| 参考实现 | 已处理的故障模式 | 取舍 |
| --- | --- | --- |
| host_ruling intake gate | who/note 空白拒收 | 带：双形态同款 |
| host_ruling intake gate | note 超 20000 不入事件历史 | 带：PAUSE_NOTE_INPUT_LIMIT 同值独立常量 |
| sign 的 stage-state 门 | gate 错配 refused | 不带：pause/resume 正交维度无「当前等待段」可错配；对端终结由通道侧 _err 承担 |
| retry-qc 通道（runPocCli） | 非零退出/超时/非 JSON → 502 结构化 | 带：同款 runPocCli+同款 502 |
| client.py cmd_ticket 族 | 不可达/未知 op → _err 不裸栈 | 带：同族；signal 对 completed workflow 抛错→_err 点名 |
| KI-003 _breathe patched | 老实例重放无 marker 破坏确定性 | 带：独立 PAUSE_PATCH_ID 门体 no-op + 信号内前置拒收（R4） |
| fixtures 桩族形态 | 模块级 IO 炸 sandbox 重执行 | 带：fixture_two_step 零模块级 IO |
| 行卡 busy 纪律 | busy 连点重复发操作 | 带：disabled+stopPropagation 同款 |
| KI-008 snapshot 饿死 | 长 RUNNING 窗查询饿死 | 天然覆盖（门是 await 点）+场景显式断言 |
| sc_ticket_lifecycle nestedGuard | 嵌套 worker 继承泳道 env 自递归 | 带教训不带处置：剥标记+钉队列+一次性服务端，L0 自证；护栏原文不动 |
| ticket-lifecycle writeGuard | 场景误连生产 temporal | 带：SANDBAR_TARGET_HOST 钉舞台地址+L0 禁区端口断言 |

## KI 相邻面

- KI-003：patched 回放安全（本机制第二处 patch id 消费点）。
- KI-008：暂停延长 RUNNING 窗口，门即 await 点+既有查询重试面覆盖；场景断言
  暂停中 snapshot 可查。
- KI-018：paused_phase 二态+timeline 相位语境=「信号存在且可辨」，防误导信号。

## 自我迭代记录（implement 段回填）

- 种子场景（design_integration_tests 边预置）初版照 ticket-lifecycle 先例把仲裁
  预置缓存写死 `.suyou/`——该先例已随 M2 点目录迁移过期（新道真源=.sandbar/，
  resolve_dot_dir 新名优先）。implement 修正为与引擎同规则的解析写法。
  **教训：照搬先例前先核先例是否已随迁移过期（点目录/旧布局类先例是高危族）。**
- 桩段秒过导致「段在飞」窗口不可捕捉（e2e 首跑 L2/L3.2 双红）。给
  SANDBAR_AGENT_STUB 桩加 `SANDBAR_AGENT_STUB_DELAY_SEC` 时长旋钮（缺省 0=即时，
  既有语义不变）——**「在飞粒度」类验收必须有确定性的在飞窗口，靠轮询碰运气
  的断言是慢性 flake**。
- 预置仲裁 verdict 不依赖捕捉 run_integration_tests 相位窗（verify_lane 在夹具
  仓秒红，相位以秒计，2s 轮询必错过）——**幂等缓存类预置要「早置等消费」，
  不要「等窗口再写」**。
- macOS `/var→/private/var` symlink：mkdtemp 路径与引擎 Path.resolve() 不归一，
  _ensure_lane_deps 误判「跨项目泳道」跳过依赖软链。场景 tmp 一律 realpath 归一。
- 夹具仓 `git clone --depth 1` 的默认分支名跟随源仓 HEAD（泳道分支名），不是
  main——merge_check 基线 merge-base main 会 rc=128。clone 后显式 `branch -m main`。
- **测试台线束 env 泄漏是族病**：桩旋钮（SANDBAR_AGENT_STUB/SUGGEST_STUB 等）与
  worker 路由旋钮（SANDBAR_TASK_QUEUES/WATCH_WORKFLOW/WATCH_INTERVAL_SEC）随
  worker env 漏进 merge_check 的泳道内 pytest 子进程，三个契约 UT 轮流假红。
  根治=单一真源 `shared.TEST_STUB_ENV_KNOBS / WORKER_ROUTING_ENV_KNOBS`，
  merge_check 的 verify_lane 调用点统一剥除（生产恒等）；两个已受害 UT 顺手补
  ambient 隔离。**教训：给 worker 注测试旋钮时，必须同时回答「这些旋钮会被哪些
  子进程继承」——子进程链上的契约测试默认应当 hermetic。**

