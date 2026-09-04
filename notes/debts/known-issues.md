# 已知问题登记表（rolling）

> 工单 t260901-07 建立。rolling 约定：后续任何工单发现非阻塞问题追加本表
> （新编号顺延），**不删旧条目**；修复后状态流转 open → fixed（注明修复工单），
> 淘汰条目标 wontfix/obsolete 留痕。严重度口径：阻塞 = 阻断流程/造成错误
> 交付；非阻塞 = 不影响正确性、观测性或体验有缺口。本表首批三条均非阻塞，
> 对应工单正文要求；只登记，不在本工单修复。
>
> **2026-09-04 仓际迁移**：控制台安家 sandbar 后，引擎与工单台代码真源均在
> 本仓（按文件位置推导 repo），本表自 suyou 仓 `notes/debts/known-issues.md`
> 整体迁入——suyou 侧同名档案自此冻结只读（CLAUDE.md 硬规则），**新条目只
> 在本仓追加**；条目内引用的仓库相对路径（engine/workbench/docs）以本仓为准。

| 编号 | 标题 | 严重度 | 状态 | 定位 |
| --- | --- | --- | --- | --- |
| KI-001 | review_plan 审读打回不上工单台横幅 | 非阻塞 | open | dev_lane.py:727-748（打回分支）；base.py:375（rework 时间线写入点）；workbench/src/client/index.tsx:1132-1145（ReworkBanner） |
| KI-002 | agent 步 max_polls 恒 0，轮询超时保护不生效 | 非阻塞 | open | shared.py:1083；agent_activities.py:553/813/1752/1813 |
| KI-003 | snapshot 查询端点偶发超时 | 非阻塞 | fixed | t260903-06 收口（重试面）：client.py `QUERY_RETRY_*` 常量 + `_query_snapshot_with_retry` 指数退避 0.5/1/2s±20% 三尝试、`_describe_with_retry` describe 瞬时重试；根因面（事件循环让路）见下方机制结论（base._breathe，t260901-23 已落地）。回归：integration/t260901-23/t01/t02/t03 + integration/t260903-06/sc_query_kind_no_lie.py |
| KI-004 | 泳道并入主干 squash 成单提交（改进提案） | 非阻塞 | open | worker 代落盘每项变更一 commit；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md L84（不以 rebase 替换 merge 策略） |
| KI-005 | 人审 approve 签字无人工备注输入框 | 非阻塞 | fixed（suyou 时代 t260901-22「approve 弹层自由备注」已修，随 v0.1.0 搬迁快照 415e582 在位——260904 宿主走查指认后核对翻转：index.tsx L3651 自由备注 textarea（≤2000 字随签字进不可变历史）+ L2975 buildApproveNote(summary, remark) 接线在案；本行自迁移起滞后未翻，登记失误非回归） | workbench/src/client/index.tsx L3651（自由备注 textarea）/L2975（buildApproveNote 接线）、approve-note.ts（suyou 史 t260901-22 落地；原锚 1651/2556 已随重构漂移） |
| KI-006 | 打回注记不落工作空间，接力只走内存与台面 | 非阻塞 | open | dev_lane.py:656-658（rework → prev_ctx）、723-737（agent 审读打回分支）；base.py:375（rework 时间线唯一写入点） |
| KI-007 | 写集 refresh 静默跳过，回执缺 files_changed 零生效零告警 | 非阻塞 | open | dev_lane.py:701-704（无清单跳过分支）；shared.py:1231（refresh_write_set 纯函数） |
| KI-008 | RUNNING snapshot 查询失败无重试无显式降级（用户已拍板方向） | 非阻塞 | fixed | t260903-06 兑现：client.py 指数退避重试（`QUERY_RETRY_ATTEMPTS=3`，0.5/1/2s±20%）+ kind 分级显式降级（详情 transient 文案、列表 degraded 行保留）；UI 侧 poll-health 静默重试+快照保留+滞后角标。回归：t260901-23 t01/t02、t260903-06 sc_query_kind_no_lie |
| KI-009 | 幂等重读不代落盘迟写文件 | 非阻塞 | open | agent_activities.py:477-492（幂等重读）、528-545（就绪即 settle 返回）、552-560（finally terminate）、312（settle 幂等口径） |
| KI-010 | 审计日志读操作通胀：每次工具调用无条件 audit | 非阻塞 | open | tools_registry.py:95-110（call→audit）；admin.py:90-127（chat_loop 逐工具放大） |
| KI-011 | 建票写集提示缺失：建单方三连犯 dev-lane 缺 integration/（改进提案） | 非阻塞 | open | workbench/src/client/epics.tsx:739-747（写集输入区） |
| KI-012 | agent 结果文件非法 JSON → 基础设施故障重试死循环，幂等锚点使 retry_qc 无法自愈 | 阻塞 | open | agent_activities.py:285-289（_read_result 吞解析异常返 None）、674-688（幂等分支读不到合法结果就 re-spawn）、749-754（进程已退出即抛 RuntimeError） |
| KI-013 | arbitrate spawn 日志占位符 3 传 2，每次仲裁派单都打 logging traceback | 非阻塞 | fixed | agent_activities.py:2427（fmt 含 cwd=%s 但 args 只有 ticket_id、gen） 。t260902-11 修复落地（补 cwd=str(cwd) 第三实参，同批 3 支 L2 用例锁行为） |
| KI-014 | manifest 共享可变尾文件是并行泳道的结构性冲突热点，LLM 消解 JSON 追加属教义不自洽（改进提案） | 非阻塞 | fixed | integration/manifest.json（全仓共享追加）；dev_lane.py design_integration_tests 契约（写 manifest）；agent_activities.py run_integration_tests/_settle（manifest 加载与合并闸） |
| KI-015 | _sh 输出裁剪至末 2000 字节，白名单 diff 大时首行截成假路径：假越界误阻断 + 前段文件静默漏检 | 阻塞 | fixed | server/tools/verify_lane.py:86（`(p.stdout+p.stderr)[-2000:]`）、:363-376（_diff_names 逐行判写集，吃进半截路径即假红；裁点前文件静默不检）。t260902-05 实证：diff 2650 字节 → 假路径「ial/token-30d.json」假红 blocked。t260902-10 已 UT 永久化（server/dsh/temporal-poc/tests/test_ki015_crop.py：crop=None 实参断言 + ~2300 字节大 diff 全链路无假红无漏检） |
| KI-016 | 泳道暂存凭据快照永不刷新：`_copy_creds` 目标已存在即跳过，新登记 provider 对老泳道永久不可见（MISSING_CREDENTIAL） | 阻塞 | open | agent_activities.py:601（`local_dsh = cwd/".dsh"` 每代理暂存 DSH_HOME）、:174-186（`_copy_creds` `if dst.exists(): return`）。t260902-05 实证：泳道快照 2026-08-22 13:04 仅 4 key，zai-coding-cn（0902 上线）不在内 → arbitrate spawn 必报 MISSING_CREDENTIAL |
| KI-017 | metrics 交付/token 维随泳道蒸发 + 口径污染：①交付=git 三点区间 三点 diff，泳道中途并 main 后把吸收的 main 进度（含兄弟票 lib 重建，单文件 50,889 行）算成本票交付——t260902-02 界面显示 8 万，squash 实测真实交付仅 +2,557；②泳道清理后缓存数字继续展示、无归档标注；③token 唯一数据源=泳道/.dsh/sessions，合入即陪葬——7 天 200 万严重低计（k3 配额打爆周的真实消耗全埋在已删泳道）。**t260903-09 收口观测侧**：①主仓归档口径（票 id grep 提交集，不含 main 吸收进度，绕开 base_ref/worktree 早退——直并票可补账）+reason 显式标注；②delivery_frozen 死字段激活（主仓回落/降维保留置 true）+「归档口径」reason；③缓存降维保留（engine_version 失配不再整条作废）+项目级账本探测缝（SUYOU_USAGE_LEDGER_DIR）。**引擎侧欠账保留 open**：merge 时刻冻结 usage/numstat 出仓快照（agent_activities.py，观测票写集外），per-commit 归属归档根治多票 id 双算/引用性提及多算（W4 实测：grep 会把「他票 message 引教训提及本票 id」的提交也算入，双算面+多算面均在契约块 3 增补段登记） | 非阻塞（观测层误导，不卡执行） | fixed（观测侧=t260903-09；引擎侧出仓快照=t260904-09 settle 冻结真源——SANDBAR_SETTLE_SNAPSHOT_DIR 机制已在 main（agent_activities L1910+），读写两侧 journey 场景在册；260904 收口后核对翻转） | 原病灶 metrics.ts:397-417、agent-usage.ts:118 已重写；现实现=metrics.ts computeDelivery（泳道活口径+主仓归档回落）、ticketRecord（降维保留）、agent-usage.resolveLedgerSessionFiles（账本缝）；契约=metrics-api契约v1.md 块 3 增补段；回归=server/dsh/workbench/tests/delivery-recovery.mjs（含 KI-017① 注入用例：中途并 main 不计回落口径） |
| KI-018 | workflow 回路期间可观测性缺陷（信号存在但误导）：①查询饿死时占位符文案「查询超时，刷新重试」被当作数据写进 title 字段并在侧栏展示——t260902-10 实证（真实标题被顶掉）；②心跳显示已存在，但机械 suite 阶段本无代理心跳、无相位说明，读作「久无心跳=卡死」（tests-fault 自愈中被误判）；③回路轮次/上限/预计剩余仍不可见 | 非阻塞（误导操作判断，曾差点人工干预正常回路） | open | client.py ticket-list 查询饿死路径（占位符进数据字段=泄漏模式）；dev_lane.py 回路分支无进度 emit；工单台心跳组件无相位语境。修复方向：占位符严禁写入数据字段（错误渲染为 UI 状态，保留 last-known-good）；根治 KI-003 查询与 worker 忙碌解耦；心跳/进度带相位语境（机械步/代理步/回路第 N 轮）。故障模式：错误文案当数据写；回归用例：随 observability 票补 |
| KI-019 | 工单详情页泳道图并行与重跑呈现失真：①数据模型缺维度——TimelineEntry 仅 {at,stage,state,reason} 扁平四元组，无轮次（gen）、无并行分支标识，且事件可乱序到达（metrics 注释实证「乱序按 from 排序」），前端只能从扁平序列猜测轮次切窗；②呈现模型是单行步骤条——并行分叉期仅多个节点同时 ▶（t260901-05 活跃步数组语义），画不出真正的并行双道；重跑多轮聚合为 Σ 总时长，轮次明细藏在 tooltip，多返工后视觉混乱（05 七轮仲裁实证） | 非阻塞（观测失真，不卡执行） | open | index.tsx:832（TimelineEntry 结构）、:1149（步骤条一字排开+活跃步数组）、lane-durations.ts deriveStageDurations（扁平序列猜轮次切窗）、base.py _mark（事件源无结构维度）。修复方向：引擎 _mark 增加轮次/分支标识与因果序号，保证追加有序；前端步骤条升级真泳道呈现（并行分叉画双道、重跑逐轮分格）；依赖 KI-018 查询解饿死保证数据完整。故障模式：扁平事件流承载结构性信息；回归用例：随 observability 票补 |
| KI-020 | t260902-10 test 道三缺口（落盘时刻实况，闭环后删对应项；原拟 KI-017，与 main metrics 债务撞号重编）：①契约 ②a 字段级真源未同步 checks.test 行（docs/design/sandbar项目接入契约v1.md 键表 closed set，docs/ 不在该票写集）；②根 verify.yaml 的 test 声明暂缓（.gitignore 无 `**/.venv/` 规则，先建 venv 会被 settle `git add -A` 吞库，待 dispatcher 批写集扩入 .gitignore 并同批 settle）；③泳道 venv 引导缺口（LANE_DEP_SYMLINKS 未加 server/dsh/temporal-poc/.venv，待重开 260825「泳道内没有消费方」拍板；主树 venv 一次性创建待安排归属）。引擎侧 test 道与 48 条 UT 已落地（verify_lane.py checks.test），不阻塞本票 merge | 非阻塞 | open | server/tools/verify_lane.py（test 道已落地）；verify.yaml（声明暂缓中）；agent_activities.py LANE_DEP_SYMLINKS；:567（settle add -A） |
| KI-021 | workflow 重启不能续段：写集等启动参数冻结且无扩写集机制，任何参数修正或中断恢复都只能取消重开、重付全段链成本（agent 段+全量 suite），宿主被迫两票直并（t260902-10/11 实证） | 非阻塞（流程经济性/人审体验） | open | dev_lane.py 段链主循环（无 resume-at-stage 语义）、client.py ticket-start（write_set 启动冻结）、ticket.py（无写集修订指令）。修复方向：①ticket 写集修订指令（dispatcher 裁决+审计）；②流程续段语义（段链快照+resume-at-stage）；③合并闸就地重试读取最新票据写集。故障模式：参数化冻结导致恢复成本等于重来；回归用例：随引擎改造票补 |
| KI-022 | 测试占位符检测无边界省略号误伤技术记法（KI 标题含 git 三点区间记法即假红） | 非阻塞 | obsolete | integration/t260901-17/t02_numbering_no_placeholder.py:37（占位正则含无边界省略号模式）；t260902-12 全量套件 144 跑唯一失败实例；回归用例：精化后同测试（KI-017 git 三点区间 实案放行、行首点串纯占位行仍拦） |
| KI-023 | integration 测试分层归位欠账：32 支 src 级 mjs（import workbench src/*.ts）暂留场景层，收编 workbench/tests/ 需连带 fixtures/兄弟导入路径手术（t260902 直改尝试 20/32 红即回滚） | 非阻塞 | fixed | integration/run_scenarios.py:SCENARIOS（js_ut 候选清单 /tmp/js-ut-candidates.txt 已盘点）；收编时同步建 run_tests.mjs 源级执行器 |
| KI-024 | 工单详情观测性盲区（宿主令登记 20260903，实案=t260903-01）：①并行分叉期 stage 单字段后写者赢——implement 与 design_integration_tests 同跑但详情只显示一边（dev_lane.py:463-469 `_enter` 写同一 meta["stage"]；:290 注释自认「展示链按线性近似」）；②动态流只播 agent 叙述不播工具轮——spawn→首句叙述间 7 分钟空窗（00:26:20 派活→00:33:31 首句）被误读为停摆，同期会话文件持续写入证明在干活。已致两次误诊：integration 误判 review_plan 挂起（实为办案）、宿主误判分叉停滞。修复方向：stage 改 `parallel_impl_design` + `parallel_stages` 列表供 UI 双显；动态流补工具轮事件（工作台轮询会话流出一行「🔧 调用 X」级事件） | 非阻塞（观测性；与 KI-018/019 同族） | fixed | t260903-04 收口：dev_lane.py `set_parallel_stages`（并行分叉期写 meta["parallel_stages"]，两分支 gather 前/汇合/rework 离场/等待期摘失败边四时机；**取舍：meta["stage"] 单字段保持后写者赢不改合并标记——工单正文「保留单 stage 字段向后兼容」为准，登记行旧方向「stage 改 parallel_impl_design」不再执行**）+ workbench lane-states.ts 真值优先双显（缺失/空回落既有启发式，回落路径行为逐字节保持——启发式已知误判面在旧票仍存，根治靠真源，不借机改启发式）+ agent-live.ts 补轮级新鲜度行（step/start→「第 N 轮」、llm/retry→「LLM 重试中仍在干活」；🔧 工具行 t260825-03 已在，静默窗真因是轮级事件被过滤）。回归用例：temporal-poc/tests/test_parallel_stages_meta.py、workbench/tests/lane-parallel-states.mjs P1-P6、workbench/smoke/agent-live.mjs D 段、integration/baselines/sc_lane_parallel_dom.mjs（S0） |
| KI-025 | ticket 查询层谎报「工单不存在」：查询失败（连接/超时类）被包装成 ValueError 不存在语义，实案 t260903-02 在飞推进中连环谎报 5+ 次（01:44-01:47），值守险据此走数据抢救误路径；CLI describe 同刻证实 workflow 活着且 run_integration_tests 在跑。与 KI-003 同族危害升格：超时可自愈，假不存在诱导误操作（重开票/废弃泳道）。修复方向：查询失败与不存在分级报错（errno/异常类型区分），绝不把前者文案成后者 | 非阻塞（观测性/值守安全） | fixed | t260903-06 收口：client.py 五出口 kind 分级（not_found=describe 命中 NotFoundFailure 唯一入水口 / transient / terminal / internal）→ ticket.py `QueryError(kind)` → tools_registry.call 异常口 duck-type 并入（hasattr(e,'kind')）→ 工作台 404/503/410/500 分流 + UI 只认 body.kind（kind 缺失一律按可重试降级，绝不按不存在）。回归：integration/t260903-06/sc_query_kind_no_lie.py（全链 A-G 段）、workbench/tests/ki025_show_error_split.mjs |
| KI-026 | lane merge_check 不跑 poc pytest（UT 层无闸）：t260903-02 合并后 t02_arb_ctx_tail_budget 陈锚假红穿透到主树才被 sanity 抓到（lane 内 64 场景+verify code 均不含 pytest）。修法=随 KI-020③ venv 符号链接落地后把 pytest 入 verify.yaml checks（lane 无 venv 前加进去会全 lane 假红）。回归用例=本事故 | 非阻塞（闸覆盖缺口） | open | server/dsh/temporal-poc/tests/（UT 层）；verify.yaml checks（无 pytest 项）；实案 t260903-02 合并后 20260903 02:15 |
| KI-027 | 工单关闭后动态流消失（宿主令登记 20260903）：数据无损——双角色 session.jsonl.zstd+全代 stage 报告已归档 ~/.sandbar/.../data/tickets/<id>/，但动态流的活水源（泳道内活会话）随泳道拆除而亡，UI 无回放入口，用户侧观感=「历史蒸发」。修复方向：①详情页动态流回落读归档会话（zstd 流式重放，收尾部 N 行）；②或「查档」入口跳归档清单。与 KI-024 同族（观测性） | 非阻塞（观测性） | open | workbench 动态流数据源（活会话轮询，无归档回落）；泳道拆除时序（先归档后拆，数据面安全）；实案=今晚四票全关闭后动态流齐灭 |
| KI-028 | agent 上下文随历史线性增长（宿主令登记 20260903，不急）：design 段④防 intent 重复要求读全局用例清单+KI 清单——这是唯一随工单数增长的 agent 输入（场景 80+/KI 28 条，现状几 KB 无感）；数百条后两害=提示符膨胀+「防重复」认知负载超载（清单太长反而防不住）。治理方向：①KI fixed/obsolete 条目移档案节（活账只留 open）；②场景清单按域分组或建 intent 索引（agent 查索引而非全清单） | 非阻塞（规模债，触发线=场景>300 或 KI open>60） | open | server/dsh/temporal-poc/dev_lane.py FLOW_BRIEF design_integration_tests ④；integration/run_scenarios.py SCENARIOS；notes/debts/known-issues.md |
| KI-029 | Temporal 全断连（连接失败）路径不产 transient、无退避重试：`cmd_ticket_query` 的 `await _connect()` 在分级/重试区之外，连接失败落 main() catch-all（client.py:1086）→ kind=internal（HTTP 500）而非 transient（503+retryable）；泳道无 poc venv 时（KI-020③）TEMP_PY 回退 python3 连 temporalio import 都崩，traceback 经 ticket.py `_poc`「Temporal 返回非 JSON」包装直泄用户文案。20260903 t260903-06 验收实弹探针实测：隔离台 GET /wf/tickets/<格式合法 id> → 500+kind=internal+「ValueError: Temporal 返回非 JSON: Traceback…」。降级方向安全（绝不 404、文案零「不存在」、UI 按 internal→retryable 静默重试），且 KI-003 实案形态（server 活着、查询超时）已被 describe/query 重试覆盖——故非阻塞 | 非阻塞（降级方向安全；观测性/文案精确性缺口） | open | server/dsh/temporal-poc/client.py `cmd_ticket_query`（`_connect()` 在 try 区外）+ main():1086 catch-all；server/tools/ticket.py `_poc`（TEMP_PY 回退 + 非 JSON 包装）；复现=integration/t260903-06/boot-and-run-parallel-dom.mjs 实弹探针（20260903 验收走查）；修复方向=connect 失败纳入分级（transient + 退避重试 1-2 次）或 catch-all 按异常类型分级；venv 缺失时 _poc 给可行动文案（指向 venv 引导）。回归=同探针（修复后期望升 503+transient） |
| KI-030 | 模型路由表内容损坏静默默认模型（编号史：原编 KI-027，与宿主令「工单关闭后动态流消失」撞号让号；验收轮曾重编 KI-028，又与 main 新登记「agent 上下文随历史线性增长」撞号，merge 消解终编 KI-030）：model_route_for 对读表一切异常 `except Exception: return None`（shared.py:913），表存在但 YAML 烂=无红无日志退默认模型。t260903-03 ①d「锚点 vs 内容」已明文为存量边界（声明与否同语义，不属 paths 四态对象）。修复方向=收窄 except（文件缺失 vs 解析错分态）或表内容 fail-closed，另立工单；回归用例=UT test_paths_contract i3 + 场景 doc-guard G6 钉现状语义，修复时随新语义同步改 | 非阻塞（静默降级，观测缺口） | open | server/dsh/temporal-poc/shared.py:913（model_route_for）；契约 ①d 锚点/内容段（sandbar项目接入契约v1.md v1.6）；t260903-03 review C1 发现 |
| KI-031 | terminate/直并收口票从工单列表与度量宇宙整体消失（audit 洞，t260903-09 实案=t260903-05 直并后从列表蒸发）：列表数据源只报可派工票，收口终态票无归档可见面。**度量侧已由 t260903-09 部分补全（验收 F3 后改准表述）**：聚合宇宙=list ∪ 度量缓存存量——仅对**缓存有记录**的票生效；旧版记录（无归窗锚点）按缓存计算时刻近似归窗（reason 显式声明近似），列表内票经 full 门迁移回写真实锚点。**无缓存记录的收口票（如 t260903-05）度量侧无从补全、依旧不可见**——registry 根修是唯一根治。ticket list API 响应集合不因此扩大（archived 票不进 dispatch 流——C4 裁决）。**registry 根修欠账 open**：列表侧给收口票可见终态（归档分组/终态筛选），需动 registry list 语义与 dispatch 过滤，另立工单 | 非阻塞（观测性/审计洞） | open（度量侧收口=t260903-09；registry 根修欠账） | metrics.ts collectArchivedRows（缓存存量补全）；回归=server/dsh/workbench/tests/terminate-universe.mjs（含 W3 负向断言：list 行集合不被度量补全污染）；根修面=registry ticket list（写集外） |
| KI-032 | 开票裸入口不锚项目根（宿主令登记 260904，实案=t260904-01 首开脑裂）：client.py ticket-start 直调只传 project 名、不传 project_root——derive_lane_workspace 产出**相对**泳道路径，落仓由「抢到 activity 的 worker 按自身 REPO_ROOT」决定。正规入口 ticket.py create（admin.py call ticket / 工单台 UI 同款）传 project_root=proj['dirs'][0] 生成绝对路径，与执行 worker 解耦。260904 实锤：裸入口首开 + suyou 侧遗留 worker 抢先 → worktree 建进冻结仓 suyou/.lane（create_plan 基于旧 epic 无 R1–R8 + 旧 workbench 源），review_plan 又在 sandbar 空泳道跑——跨仓脑裂，cancel 作废后正规入口重开恢复正常。修复方向=引擎侧硬闸：client.py ticket-start 收到 project 时自查注册表锚 project_root（与 ticket.py 同源），未锚定即拒收；在此之前开票纪律：**只走 ticket.py create / 工单台 UI，client.py 限读（list/query/describe）** | 非阻塞（有正规入口可绕；裸入口属误用面） | closed | server/dsh/temporal-poc/client.py cmd_ticket_start（derive_lane_workspace 未传 project_root）；server/tools/ticket.py:664-669（正规锚点参照）；实案时间线=260904 t260904-01 cancel 重开。**修复=t260904-02**：装载器上收 shared.py（单一真源）+ client.py ticket-start 硬闸（lookup_project 锚 project_root→check_paths_under_project 双查；缺 project/未知 key/路径越界三态拒收）。回归=UT test_t260904_02_registry_anchor + 场景 t260904-02-ticket-start-anchor。**t260904-02 acceptance gen1 验收过后转 closed（260904；走查实证：Temporal payload workspace 绝对锚定+三态拒收文案互辨全绿）** |
| KI-033 | 跨仓双引擎进程双 serve 工单专属队列无感知（宿主令登记 260904，与 KI-032 叠加成灾）：工单 worker 去重靠 pidfile，但 pidfile 按各仓 data/ 目录隔离——sandbar/suyou 两套引擎进程并存时，同一条 suyou-ticket-<tid> 队列被双 worker 并行领 activity，交替执行=脑裂（一仓建 worktree、另一仓跑 agent staging），且互不知晓。260904 实锤：suyou 时代遗留 headless（node，无监听端口，携带 temporal supervisor 的 15s ticketEnsure）未随迁移清场，新票被其抢先 spawn 的 worker（cwd=suyou poc）接管。处置=杀僵尸进程族（headless+其 general worker+ticket worker）、清 suyou/.lane 误建 worktree 与分支。防再犯：①迁移/切换后清点旧仓引擎进程（lsof -c node/-c Python 查 cwd 指向）；②引擎侧修法（另立工单）：worker 注册带引擎仓指纹，ensure 发现异仓 worker 服务同票即告警/拒接 | 非阻塞（单仓部署不触发；多仓并存期高危） | closed | server/dsh/temporal-tools/node.ts ensureTicketWorkers/spawnTicketWorker（pidfile=各仓 dataDir）；worker.py 专属队列 watch；实案=260904 僵尸进程族 7942/37185/53762。**修复=t260904-02**：worker 归属指纹 meta（{version,pid,repo_root,ts}，起跑早写/优雅退自清）+ node.ts ensureTicketWorkersOnce 三态（异仓 warn{repoRoot,pid,tid}+拒接不杀）+ doctor 第五面 probe-engine-zombies（--live 真扫）。回归=UT test_t260904_02_worker_meta + 场景 t260904-02-worker-fingerprint-gate / -doctor-zombie。**t260904-02 acceptance gen1 验收过后转 closed（260904；走查实证：ensure 真执行三态 decisions+异仓 warn 三要素全绿，拒接不杀）** |
| KI-034 | 知识库未随代码迁移+文档维护机制未落实（宿主令登记 260904，主体当日已修）：sandbar=引擎真源但 docs/ 只有契约 1 份——WORKFLOW_CONTEXT dev-lane 必读的引擎机制主档（deepseek_harness...multi-agent_mechanism.md）缺档，在飞泳道 agent 开工必读为空只能靠票面 spec；notes/ 机制载体（README 分工/毕业规则/交付文档钩子）未迁。当日处置：迁引擎/插件/基建域文档 12 篇（design 9+ops 1+根级 2）+build_index 脚本、docs/README 重写为 sandbar 版、index.json 重跑、notes/README 落地（commit 7fd087d 及后续）。**残余欠账 open**：①terminology 整表迁入含项目域条目待清理；②content-pipeline 必读指向项目域文档（平台架构设计.md 留 suyou）——WORKFLOW_CONTEXT 按引擎根解析 docs/，跨项目票上下文应按 project 解析 docsDir（knowledge 插件已声明化，引擎侧未），与 KI-032 同属「引擎↔项目根解耦」族——**260904 已消解**（t260904-03 两表退役，派活头不再指向任何具体文档，引擎侧最后一个按引擎根解析 docs 的消费点消失，见 KI-035）；③4 篇迁入文档缺 frontmatter（dsh_seam/metrics面板/契约/杂务工单，存量旧账，build_index 已告警）——**260904 当日已补齐（d63a8bf），索引告警清零**；④docs 与代码漂移的持续维护机制（merge 关卡核对 epic 交付文档清单）靠 integration 执行，尚无机械护栏 | 非阻塞（主体已修；残余为欠账面） | partial（迁移=260904 当日；③②已闭；残余①④另排） | docs/（迁移清单=commit 7fd087d）；shared.py WORKFLOW_CONTEXT（dev-lane 必读主档已就位）；notes/README.md（机制载体） |
| KI-035 | 派活必读清单制浪费 agent 上下文+映射表与 docs 实况手工耦合（宿主令登记并拍板修法 260904）：WORKFLOW_CONTEXT/TITLE_CONTEXT_RULES（shared.py:839-852）把设计文档以「必读、按序先读」塞进每段派活——agent 每会话全文读 413 行机制主档（≈60-80k token/票重复消耗，与票面相关性无关），标题二级推导再叠加（temporal/工单引擎命中加 405 行工单台设计）；表与 docs 实况手工耦合，260904 迁移即断链（掌握模型/营造建造留守 suyou 仍被指向）。**宿主拍板=索引化**：派活头③改恒定知识库规约（目录=docs/README.md 每篇一句话用途；agent 对照标题/写集按需读；结算 note 列参考 docs 清单作审计），两张表退役；CLAUDE.md+岗位说明书保底两项不变。前置=4 篇缺 frontmatter 补齐（260904 当日 integration 完成 d63a8bf，告警清零）。落地=engine-hardening 票② | 非阻塞（效率+解耦债） | closed（t260904-03 落地 260904：两表退役+两路派活头恒定知识库规约+结算 note/交付契约审计句+UT 回归锁；**设计×实现漂移登记**：知识库设计.md §4/§7/§8-M4 派活传文档机制句已被索引化拍板取代，修订待人审另票） | shared.py:839-852（两表）+:989-994（派活头③）+:1651（dispatch-next 同款）；docs/README.md+index.json（索引基建）；修复票=t260904-03 |
| KI-036 | ui_evidence 机械关卡失效（t260904-01 实锤 260904）：capture.mjs 依赖 playwright-core 未随迁移恢复（sandbar ui-check/ 无 node_modules；suyou 侧曾装过——M2 迁 gitignore 不带依赖；沙箱内 npm install EPERM 不可用）→ capture-lane 隔离台 boot 成功但截图通道红，ui_evidence 段 status=failed。implement 段以自写 bench-shot.mjs（domcontentloaded+语义锚+DOM 断言）绕过产出真证据（before/after/closeup 落泳道 .suyou/screenshots/，DOM 断言含 24×24 方块几何与洞号 1/3 不回收可视化）——证据在但关卡红。**附带纪律问题**：ui_evidence fallback 有「capture.mjs 直连 http://127.0.0.1:3099」路（只读导航未遂，但违反测试隔离铁律精神，应删）。修复面：①宿主侧（沙箱外）在 server/dsh/ui-check/ 恢复依赖安装；②agent_activities LANE_DEP_SYMLINKS 补 ui-check 依赖软链（泳道同病）；③引擎 ui_evidence fallback 删直连 3099 分支。与 engine-hardening 票①隔离台 (D) 相邻不同票（那是场景基建，这是截图通道）。260904 回迁的 gate-interlock 场景已加环境守卫（双缺 playwright-core 干净 SKIP 注明 KI-036，依赖恢复自动生效，断言面不变） | 非阻塞（有 bench-shot 绕过通道；merge_check 机械查截图在场可过） | open | server/dsh/ui-check/capture.mjs（playwright-core import）；agent_activities.py LANE_DEP_SYMLINKS+ui_evidence 段；实锤=t260904-01 ui_evidence failed（run_tests capture-stale-banner 同族） |
| KI-037 | 主树三个存量红灯未登记（迁移测试债，t260904-01 run_tests 实锤 ran=36 pass=33 fail=3）：①tests/capture-stale-banner——profile 软链缺（start-console.sh 注释「headless 软链待建」同源，~/.dsh/profiles/sandbar-headless 未建）；②tests/epic-status-enum——census 期望 9 张（suyou 口径）sandbar 现 2 张（session-entry/engine-hardening）未适配；③tests/verify-lane-config F9——app/ 白名单 suyou 形态未随迁移改口径。t260904-01 的 integration agent 三分「本票未触碰、预存」判断正确**但未登记 KI**——对抗发现的问题被免单蒸发，本条补账（对抗性欠账也在此记录：review/design 两段对抗实质到位——C1 溢出裁剪链/C3 并发同号/C4 backfill 竞态/13 FAIL 实弹+P1 方案-实现签名分歧上报，非橡皮章）。修复面：①建 profile 软链；②③改测试口径适配 sandbar 现状。**260904 更新**：①capture-stale-banner 已绿（t260904-01 merge 后实测，横幅三态实拍通过）。②③按宿主裁定（「怎么可以用真实数据自测」）重构为 fixture/性质分层而非改口径追现实——epic-status-enum B 段删写死 9 张清单+逐张点名，改 B1 真数据性质断言（全枚举合法+无残留）+B2 fixture roster 独立性（数量刻意≠真实仓，新 charter 出现不红）；verify-lane-config F9 由 suyou 快照（write_allow 含 app/）改 sandbar 性质断言（声明 server/+integration/ 真源面+无 app/ 残留）。run_tests 36/36 全绿；原则沉淀 docs/testing-guide.md「测试数据纪律」。三红全清 | 非阻塞 | **fixed**（260904） | server/dsh/workbench/tests/capture-stale-banner.mjs / epic-status-enum.mjs / verify-lane-config.mjs；start-console.sh 软链注释；实锤=t260904-01 implement 段 run_tests 输出 |
| KI-038 | 集成场景迁移过度裁剪 89→10（与 KI-034 同族：迁移按时间线裁非按真源裁，宿主问询触发 260904 登记）：M2 干净基线只带回 sandbar 项目期出生的三张票场景（t260903-10/12/13=10 条），suyou 时代 79 条整体留冻结仓——但其中**引擎行为族 ~30 条**（ticket 生命周期/auto-rework/settle-lane-anchoring/mergecheck×3/t260902-02 归档族×9/fork-contract×3/paths×3/t260903-06 query-kind-no-lie×3=KI-029 实弹探针/t260903-09×4/并行段×3）与 **workbench UI 捕获族 ~15 条**（capture-chat-e2e/redline-gate/lane-preset/lane-parallel-dom/approve-modal/session-top-entry/multi-tab/metrics-donut）的被测代码真源已迁入 sandbar。下游症状=UI 层场景缺口、引擎行为零覆盖、截图通道失效（KI-036）全为此刀。真该留 suyou 的~40 条（content/阅读/项目域/manifest 已退役族）判定正确。附带：handoff 点名的 doc-guard（sc_sandbar_dsh_compat）也遗留在 suyou baselines/。修复面=场景回迁（带回/留/退役三判+适配）。**260904 已执行**：triage 89→带回 73/退役 14/暂缓 1（notes/discussions/260904-integration-scenarios-triage.md）；宿主裁定不开票直迁——P1+P2 56 条已落地 main（套件 66 条全绿），P3 browser 16+e2e 2 待隔离台（票①(D)）+KI-036 playwright 恢复。**UT 面实锤形态（t260904-03 验收走查发现；泳道侧曾以 KI-036 补登，merge 轮撞号并归本条）**：tests/ 24 个薄包装（t260901-14/16/19/21/23/25/26、t260902-02/07/09 族）subprocess 指向未迁场景目录恒红，「红=正常」习惯化会淹真回归（与 KI-026 叠加；基线清单=t260904-03 泳道 .suyou/pytest_baseline_failed.txt）——目录回迁后解封 2 条，余 22 条=脚本在场但环境依赖红，归「主树 UT 测试网复绿」票三分处置 | 非阻塞 | **closed（260904）**：P3+e2e 第二批落地（票①(D) 隔离台先行），套件 88/88；唯 retention（Docker 路线）暂缓随隔离台重估 | suyou/integration/run_scenarios.py（89 条清单）；sandbar integration/run_scenarios.py（10 条）；manifest 无场景级判定（仅计数一句） |
| KI-039 | 引擎 venv 依赖不齐（260904 回迁 spawn-seam 实锤）：sandbar temporal-poc/.venv 有 temporalio 但缺 PyYAML → model_route_for 容错返回 None → **迁仓以来每次 spawn 的模型路由 patch 静默空转**（声明表/回落常量全读不到，agent 一律用 profile 默认模型，无红无痕无人察觉——容错设计把依赖缺失吞成了「无路由」语义）。场景侧症状=A3/B1 模型半红而角色半绿（A1 证明 registry paths 声明链本身是好的）。已装 PyYAML 6.0.3 即时修复（spawn-seam 11/11；t260902-09 F 组 11 例解封全过）；残留=venv 是 gitignore 的，重建即丢——需 requirements 固化（建议并入 engine-hardening 面：temporal-poc 依赖清单+venv 体检并票① doctor 项）。教训=容错分支必须区分「表确实无路由」与「读表失败」，静默等价吞依赖缺失 | 非阻塞（已装包修复；默认模型兜底在） | **fixed-fragile**（即时修复在，重建即复发） | server/dsh/temporal-poc/.venv（pip list 无 PyYAML）；agent_activities.py model_route_for 容错路径；实锤=integration/t260903-03/sc_paths_spawn_seam.py A3/B1 + t260902-09 skip 行 |
| KI-040 | metrics 缓存命中对失败维/陈旧维永不自愈（260904 宿主「数据令人失望」问询触发，审计=notes/discussions/260904-metrics-data-audit.md）：ticketRecord 缓存命中即早退，delivery=null 的记录永不重算——t260903-11/12/13 缓存算于 merge 前（09-03T15:34Z），此后 squash 落 main（06ef0b2/91327b9/7e2b475）仍永久报「主仓无引用本票的提交」（git 实测 6/6 票全有引用提交），交付视图 6 票 5 空；连带 open 标志陈旧（t260904-02 缓存算于闭单前 5 秒，open=true 永久化）→ 跨视图自相矛盾：time/delivery/token 视图 closed=4 vs health 直查 closed=5（suyou 同病 48 vs 50）；唯一有数的 t260904-01 归档口径还超算（grep 6 提交含预解/记账 add 2436 vs squash 真值 2135，虚高 14%=KI-017① 多提交双算面的 sandbar 实证） | 非阻塞（观测层数字失真，不卡执行） | fixed（t260904-04 收口 0aa8a96：stale-cache-heal journey 在册「实现已随本票落地全绿」，回退则 J1-J6 红） | metrics.ts ticketRecord 缓存早退 + computeDelivery 主仓回落；证据=缓存原文 ~/.sandbar/projects/sandbar/data/metrics/*.json + 审计报告真值表 |
| KI-041 | computeDelivery 泳道活口径死于 join 毒路径：worktree 字段存绝对路径（KI-032 修复后恒锚根），path.join(repo, 绝对路径) 拼出 /…/sandbar/Users/user/… 不存在的路径 → git fatal: cannot change to → 活泳道三点 diff 100% 失效，在制票交付恒回落主仓口径（merge 前主仓无引用 → 恒「不可算」）。实证 t260904-03：活泳道真值 +671/−43/6 commits 全丢 | 非阻塞（观测层，活口径失效） | fixed（t260904-04 收口：metrics.ts L546 isAbsolute 归一在位实证——毒路径 join 修复落地） | metrics.ts computeDelivery join(deps.repo, worktree)；实证=毒路径 git -C fatal vs .lane/t260904-03 真值 diff |
| KI-042 | metrics 面板选择器失效族：①立项下拉取 `${API}/wf/epics` 恒 404（正确路由 /api/epics，实测 engine-hardening/session-entry 两条在）→ 立项筛选从上线起只有「全部/无」空壳，fetch 失败静默吞；②项目下拉 UI 硬禁用（title「随契约 bump」过时——冻结契约块 2 本就有 project=<key> 且后端 parseMetricsQuery/checkProject 已实现），多项目宇宙锁死缺省 sandbar。宿主令 260904：泳道（模板）与立项选择器退役、项目下拉启用 | 非阻塞（UI 面） | fixed（t260904-04 收口：项目下拉启用+泳道/立项选择器退役，metrics.tsx L96 注释与 L224-228 双 select 实证） | metrics.tsx epics fetch（L116-131）与筛选行三个 select（L215-231）；后端 project 支撑=metrics.ts parseMetricsQuery |
| KI-043 | metrics 聚合宇宙双洞：①跨项目 repo 错位——node.ts 前门 repo 恒按本文件位置推导（=sandbar），传 project=suyou 时 git/会话解析仍指 sandbar 仓，suyou 50 张票历史（缓存 50 条记录俱在）不可见或按错仓回落数字，多项目引擎实际只聚合得出 sandbar 6 票；②模板过滤静默吞票——t260903-10（workflow=''）被 template 过滤丢弃，reason 无任何记载，宇宙缩水（list 7→聚合 6）对用户不可见 | 非阻塞（观测层） | fixed（t260904-04 收口：per-project repo seam + 吞票显式 notice 场景在册全绿；token 出仓欠账由 t260904-09 settle 快照承接） | metrics.ts template 过滤（L678）；node.ts repo 推导（config.repo→SUYOU_REPO→本文件上三级）；token 维账本缝 SUYOU_USAGE_LEDGER_DIR 未设=KI-017③ 引擎侧欠账延续（token 出仓快照另立票） |
| KI-044 | UI 截图证据闸可被粗粒度写集声明绕过（260904 实证=t260904-05）：merge_check 的 UI 票判定 shared.is_ui_write_set 按**声明条目**前缀匹配 UI_WRITE_PREFIXES（src/client/、lib/、app/src/…）——t260904-04 逐文件声明（含 src/client/metrics.tsx）命中→闸生效被卡；t260904-05 声明整个 server/dsh/workbench/ 父目录（实际改的就是会话区 UI，写集甚至含 ui-check/ 截图工具本身）→不满足 startswith→判「非 UI 票」，五项检查里根本没有截图项，全绿直过 merge。声明口径≠实际写面，粒度越粗关卡越弱；迁移以来无任何票真正产过截图（05 绕过、04 卡 KI-036 playwright-core 缺失）。根治方向=按泳道分支**实际 diff 路径**判定 UI 票（260904 与宿主对齐定稿：共享谓词 ui_changed_paths=diff --name-only base...branch × UI 前缀表，两处调用同一源——ui_evidence 段算一次定拍不拍、merge_check 再算一次定要不要证据，结果各自落闸记录；「目录条目展开」备选废弃——对工作区展开误伤、对 diff 展开多余、冻结声明追不上票内新增文件；两时点 diff 变化由 fail-closed 补拍循环兜住，证据必须覆盖最终 diff），属引擎写集需另开票 | 非阻塞（关卡完整性漏洞：不产生错误交付，但削弱 UI 验收面） | open（环境侧 playwright-core 已装 260904；闸判定根修另开票） | shared.py UI_WRITE_PREFIXES/is_ui_write_set（L1207-1241）；agent_activities.py merge_check 3.6 UI 证据闸（L1722-1741）；实证=t260904-05 gate_runs（无截图项全绿）vs t260904-04（截图项红 blocked） |
| KI-045 | capture 视图清单缺 metrics 面板专属视图（260904 补拍 t260904-04 证据时发现）：capture.mjs 的 VIEWS 停在 t260829-07 六视图+立项单（t260901-24 仅 fixture 态 +2），metrics 面板（M2 四视图）上线以来的 UI 改动只有间接覆盖（default/board 里见侧栏入口），筛选行/图表本体无直拍证据。宿主令 260904：**后面做 metrics 票时再加**。补法建议：新增 console-metrics.png——锚=下栏「📊 度量」按钮 → 面板开态，断言=筛选行收敛后形态（时间窗+项目两下拉，泳道/立项选择器不在场）+ 主图容器非空；随票更新 capture.mjs 契约注释与视图计数 | 非阻塞（证据覆盖缺口） | open（挂下一张 metrics 票） | server/dsh/ui-check/capture.mjs VIEWS 数组（L636-652）+文件头视图清单注释；关联=t260904-04 补拍实况（6/7 视图，无 metrics 直拍） |
| KI-046 | t260904-07 会话开局注入上线即坏（宿主 260904 报障：新建会话报 `invalid payload for session prompt`）：客户端 `session.prompt(charter, 'queue')` 传**裸字符串**，平台 wire 契约要求 `content: PromptContentPart[]`（`[{type:'text',text}]`），apiproxy zod 拒收；放大器=平台 prompt 失败**不抛错**只回 RpcResult（写 snapshot.promptError→toast），票内 R3「就地 catch 兜底」从未触发，无 console.error 无 notify，会话保持 blank。为何闸没拦：唯一能抓住它的注入旅程场景在合并闸**干净 SKIP**（lane 无 playwright-core=KI-036 族、无 3199 隔离台），闸按 exit 0 计过，arbitrate 注记「干净 SKIP」放行；反事实验证=journey 真跑必红（30s 无 charter+零 console error→FAIL）。缺口三层：lane 环境缺 browser 依赖（browser 池 16+ 条同类退化）／核心旅程 SKIP 无人工复判阻断门（KI-044 同族）／SessionsFace any 面+tsc 无从校验签名。定位报告=notes/discussions/260904-charter-injection-invalid-payload.md | 阻塞（已造成错误交付：07 票核心功能 100% 失效） | open（待开修复票：分片数组+result.ok 检查+any 面收窄；验收=隔离台真跑 journey 三腿） | session-entry.tsx L313（违规调用）/L155-164（any 面）；dsh-host-apiproxy lib/index.js L614-620 schema+L4824-4831 文案；dsh-client-runtime lib/client.js L7196-7240（透传+不抛错）；闸实证=worker-t260904-07.log L54/L61/L85/L93-94；失败现场=~/.dsh/sessions/…sandbar--/session-c5ea997f-*（4 行转录零注入） |
| KI-047 | merge_check mixed-red 排序缺口（t260904-11 实证，260904 登记；**260904 晚归因修正**：当时 verify red=2 实为两个 integration/ 文件越界——票面写集精确枚举缺 integration/，非「写集外过时守卫」；smoke 守卫红只在 agent 手跑面，verify.yaml 无 smoke 引用不进引擎闸——见 KI-049）：冲突自动消解回路触发条件 `conflict = (not green) and (not other_red) and …`（agent_activities.py:1821，注释「基础问题先交人，不带病消解」）——当「基础问题」（verify 红等）**恰是 merge 本身才能治愈的**，构成设计性死锁：verify 红→压制消解回路→无法并 main→verify 红永存。当日处置=main 侧代行引擎消解（git merge main 进泳道+机械冲突并集 4f46eff+rework 回 run_integration_tests 重验，宿主令「11走A吧」，全程留痕）。属 KI-021（写集冻结无修订通道）+KI-044（声明口径执法）家族；根治面=写集改革（notes/discussions/260904-write-set-reform.md） | 非阻塞（有代行解法，但每次需人肉介入） | open（挂写集改革讨论档，随其立项） | agent_activities.py:1821（conflict 判定压制）；dev_lane.py:1554（not mc.conflict→blocked 分支）；死锁现场=worker-t260904-11.log 19:16/20:16 两轮同象；解法现场=lane/t260904-11 4f46eff（并 main） |
| KI-048 | merge squash 被 main 脏工作区拒绝后：①误归类为「merge 失败（conflict）」回卷重验（实为 git 本地改动保护，非冲突）；②重架人门但**无任何原因展示**——首签被静默消费、票看似原地不动，真相只在 worker log WARNING 一行（t260904-14 实证：宿主未提交的契约 v1.8 编辑挡 squash，20:39 首签蒸发；处置=v1.8 确认代提交 26f174c+main 预并泳道 d1c933f+重签，3f99dce 落账）。运营面 root cause=「main 侧随时可能有无主未提交编辑」（当前即常态：notes/ 批次、宿主草稿），引擎 squash 在 main 工作区执行=每次落账都暴露于此 | 非阻塞（可恢复但费一轮人肉+签名浪费） | open（观测面：squash 拒绝分类修正+人门上下文带失败原因；预防面=merge 前 main 脏检查提示） | dev_lane.py merge 失败分支（「merge 失败（conflict）自动打回重验」文案）；worker-t260904-14.log 20:39:18.412 WARNING（squash 失败原文） |
| KI-049 | dev-lane 写集与流水线自身产出结构性错位（t260904-11 实证 red=3，260904 登记；**260904 深夜加重：写集跟随方案机制实践性死亡**——`refresh_write_set` 依赖 create_plan 结果 JSON 的 `files_changed` 字段，而 11 号两代方案该字段均为**空数组 []**（叙述里写了补列、结构化字段没填）→ 并集静默 no-op（只记 None 的「跳过」，空数组零日志）；grep 全工单史「授权扩展」日志=**0 条**，t260829-07 立的机制从未生效过，agent prompt 返回形状（agent_activities.py:18）虽列了 files_changed 但无强制）——修复面：①create_plan 段 prompt/校验强制 files_changed 非空（或从 plan 文本机械抽取）；②refresh 对空数组记告警日志（空≠None 的观测缺口，KI-048 同族）；③**缝上契约场景**：run_tests 增测——以真实 agent 回执形状（files_changed 空数组）喂 refresh 链路，断言「空回执=可见红/告警」（本条实践性死亡单测为何全绿：mock 恰当填字段，生产 agent 不填——引擎函数测试无法覆盖缝契约，KI-046 干净 SKIP 同族：测试在场≠测试生效）；④**机制活性断言**（dead-man's switch）：巡检项 grep 工单史「授权扩展」日志非零——机制的 liveness 至今无人监测，本条死了 N 天靠人肉盯两轮同象红灯才发现；本票当日第二輪 rework 用外科手术式指令强制填写验证通路（留档））：design_integration_tests 段**必然**写 integration/（场景文件+run_scenarios.py 登记+守卫修正），但写集刷新只有一个时点——review_plan 放行后 `refresh_write_set(plan_files)`（dev_lane.py:566/876）——集成段产出不在刷新面；票面写集若建票时未列 integration/（t260904-11 精确枚举五项漏列），merge_check verify_lane 判越界红，且**无 band 内通道**事后扩写集（update op 无 write_set 面；rework 只能回 create_plan 让方案重declare 再走一次 refresh——当日晚即用此路：rework→create_plan 补列三文件）。同日三连击：11 号先后撞 KI-047（压制消解）→软链环境债→本条（越界红），全是写集家族。结构性根治=写集改革「验证资产默认开」柱（integration/ 场景/smoke/tests 属验证资产，默认放行+守卫改动进必审项）——本条即其 P0 活证据；次选=引擎在 design_integration_tests settle 后追加一次 refresh | 非阻塞（rework→create_plan 可解但整链重跑约 1h；机制死亡使每次都要人肉盯 files_changed） | open（挂写集改革讨论档；①②为引擎小修票） | dev_lane.py:566（refresh 单时点）/876（调用位）/571-573（files_changed 读取与 None-only 日志）；shared.py:1312（refresh_write_set 纯并集语义）；agent_activities.py:18（返回形状列了字段无强制）/469（解析）；现场=worker-t260904-11.log 21:00:42 与 21:38:19 两轮 red=3 同象+两代 stage_create_plan_gen*.json files_changed=[]；对照=同日 t260904-10/14/15 建票均带 integration/ 无此象 |
| KI-051 | 守卫锚字面量×实现改名脱钩（260904 立案：05 号票重构 capture.mjs 把锚措辞「隔离台『+ 新建会话』」改「隔离台项目行『+ 钮』」，两个 capture-chat 守卫仍断言旧字面=永红；**被环境红捂住数日**——浏览器缺依赖使两场景 env_fail 根本没跑到断言，12 号理顺环境供身后首跑即现形，主跑 fail=3 的两席；修复=锚措辞兼容正则（锚语义不锚字面），4e79108 双绿16/0 与 8/0）——**环境红捂真红的 KI-038/046 同族第三案，也是 12 号三态制的正面论证**；根治面=code-quality 巡检 epic 测试面扫描（守卫锚 vs 实现措辞漂移检测：反向索引「守卫断言的字面锚 → 生产方在场性」静态核验） | 非阻塞（已修） | open（挂 inspection epic 票①扫描项；另：断言写死字面的写法规范=锚语义优先，入写作面） | 现场=4e79108 修复 diff＋/tmp/suite_full.log（122/98/3/21 主跑实录）；生产方=capture.mjs L342 模板拼接（字面搜索搜不到=巡检需模板感知） |
| KI-050 | UI 证据闸的引擎侧路径硬编码=多项目通用性缺口（260904 宿主质询登记）：shared.py:1212 `UI_WRITE_PREFIXES` 写死 sandbar 布局五条——①布局假设：他项目 UI 在 web/、frontend/、packages/ui/ 下→**闸盲**（改 UI 不触发证据要求）；②存在假设：无 UI 项目（纯后端/CLI/库）仍出现「UI 截图证据=绿」检查项=trivially green 噪声（看着像验过，实无面可验）；③供给假设：截图依赖 browser 供给（KI-036 家族=当晚 25 环境红中 18 条大头），未走 t260904-12 立的 supply 声明制。修复方向=声明制（先例双在：merge-checks.yaml「无文件=无扩展检查、别的项目不受影响」＋契约①d paths 节）：`ui_evidence {dirs, supply}` 项目自报，**无声明=闸拓扑级缺席**（非 SKIP[环境缺=红]、非 trivially green[假验过]），引擎只留机制（diff×声明目录判定+截图执行），sandbar 声明=现硬编码五行迁移即数据。统一原则：机制在引擎，面在项目 | 非阻塞（单项目期无害；多项目接入即现形） | open（挂「闸面通用化」票：与 12 号乙段 supply+引擎窗口 env_fail 盲区同票或相邻） | shared.py:1212（硬编码表）/1232（match_ui_paths 单点，迁移只改数据源）；agent_activities.py:1488（_ui_diff_paths diff 源）/1782（检查项拼接处）；供给面=契约②a supply（v2.0 行） |

---

## KI-001 review_plan 审读打回不上工单台横幅

**现象**：review_plan 段 integration agent 审读不通过（打回方案）时，工单台
详情页看不到「被打回过 N 次」横幅；只有人工点「打回」按钮（rework signal）
产生的打回才上横幅。

**机制**（读码定性，2026-09-01）：dev-lane 的 review_plan 打回走主循环内部
`continue` 回 create_plan（dev_lane.py:727-748），该分支只调 `_handoff` +
`_log`，**没有 `_mark(..., "rework", ...)`**——而工单台 ReworkBanner
（index.tsx:1135）只渲染 `timeline.filter(t => t.state === 'rework')`，
时间线 rework 记录的唯一写入点是 base.py:375（rework signal → `_apply_rework`）。
所以 agent 审读打回在观测面上隐形：用户不知道方案被打回过几轮、理由是什么，
得去 handoff/日志里翻。

**影响**：非阻塞——流程本身正确（打回-返工回路正常轮转，MAX_REVIEW_ROUNDS
超限也走 blocked 留痕）；缺的是可观测性。

**修复方向（登记，不在本工单做）**：review_plan 打回分支补
`_mark("create_plan", "rework", "<理由>")`（与 rework signal 同一写入点），
横幅即可复用。注意创建 `_finish("create_plan")` 的下一轮会再落 running 记录，
时间线语义需一并核对。

## KI-002 agent 步 max_polls 恒 0，轮询超时保护不生效

**现象**：`AgentStageArgs.max_polls` 缺省 0（shared.py:1083，注释
「0=缺省（activity 侧常量）」），全仓没有任何构造点传非 0（grep `max_polls`
全仓 5 处：定义 1 + 消费 4）。四个消费点均为
`if args.max_polls and polls >= args.max_polls`（agent_activities.py:553
通用步、813 suggest_next、1752/1813 另两处轮询循环），恒 0 → 分支恒不进入，
**等结果文件的轮询上限保护从未生效**。

**定性**：字段与消费点像是为了「卡死的 agent 进程留一道主动超时」预留的防呆，
但 activity 侧常量从未接线（「0=缺省」注释暗示预期由 activity 常量兜底，
实际无此常量）。当前实际兜底链：Temporal activity 超时/重试 +
observability 脉搏行的心跳停滞红提示（只显示不动作，判读留人）。属防呆缺口
而非功能 bug：没有它系统也能收敛，只是卡死时等的是平台超时而不是主动报错。

**影响**：非阻塞。

**修复方向（登记）**：二选一——接线 activity 常量（按 stage 类型给
max_polls 实值，超时抛错带轮询数便于诊断），或删除字段与四处死分支
（承认平台超时兜底即可）。读码倾向后者更诚实，但接线成本低，修复工单定夺。

## KI-003 snapshot 查询端点偶发超时

**现象**：工单台工单详情/列表偶发出现 snapshot 查询超时——详情接口报
「snapshot 查询失败（worker 在线？）」（client.py:536 的 8s
`asyncio.wait_for` 到期），列表接口静默降级为匿名最小行（client.py:636
`_meta_of` 吞异常返回 `{}`，行内标题/角色/epic 缺失）。重试（刷新）通常
恢复。

**机制**（读码定性）：RUNNING workflow 的 `snapshot` query 在 workflow task
队列上排队执行，workflow 正在长 activity（如 merge_check 内跑 verify_lane）
或专属 worker 繁忙时 query 等待超 8s。8s 超时与「非 RUNNING 不发 query」
的口径是 260824 收口工单拖慢列表的实证修复（client.py:627-631 注释），
方向正确；残留缺口是 RUNNING 侧的排队没有区分「worker 死了」与「worker 忙」，
也没有重试/退避，偶发表现为上面的两种降级。

**影响**：非阻塞——两种降级都可恢复且不产生错误数据（详情显式报错、列表
匿名行），但体验上有「工单台偶发抖动」。

**修复方向（登记）**：query 失败路径加一次短退避重试（如对 RUNNING 重试
1 次、间隔 2s），或把列表 `_meta_of` 的吞异常降级显式化（行内标注「查询
超时，刷新重试」）。修复工单顺带复核 8s 阈值。

**机制结论（2026-09-01 下午，用户观察 + 五次活体佐证）**：主因不是上面
机制段猜的「长 activity 排队 / worker 忙」，而是 **stage 转换 inline 突变
噎住查询事件循环**——RUNNING workflow 的 `snapshot` query handler
（base.py:568）与主协程共用同一个 workflow 事件循环；stage 转换时主协程
同步做 inline 突变（`_log`/`_mark`，base.py:112-119；rework `_mark`
唯一写入点 base.py:375；`refresh_write_set` 与 results 记账），期间 query
只能排队，排队超 client.py:536 的 8s 即触发本条两种降级。**多页签轮询
风暴为负载共犯**：工单台每个页签的列表对全部 RUNNING 票并发发 query
（client.py:650 `asyncio.gather`），页签开多时 query 流量成倍放大，叠加
排队延迟。原机制段描述的「长 activity 排队」降为次要因素，原文保留不删。
修复方向归口：事件循环让路（stage 转换重活移出主协程或异步化）在本条做；
失败重试与显式降级归 KI-008（用户已拍板方向），两条互引、不重复修复。
状态维持 open 不变，本结论为登记，不在本工单修复。

**落地注记（2026-09-03，t260903-06，本条 fixed）**：重试面由 t260903-06 兑现——
`_query_snapshot_with_retry` 升级为指数退避（3 尝试，0.5/1/2s ±20% 抖动，参数
`QUERY_RETRY_*` 模块级可注入），describe 瞬时失败亦有 `_describe_with_retry`
一次退避重试；错误出口全量分级（kind 字段，见 KI-025）。根因面（事件循环让路）
已由 t260901-23 的 base._breathe 落地，机制结论保留不改。回归用例：
integration/t260901-23/t01（30 案，含退避序列与分级断言）/t02/t03、
integration/t260903-06/sc_query_kind_no_lie.py。

## KI-004 泳道并入主干 squash 成单提交（改进提案）

**提案**：工单在人审签字放行后、泳道并入主干前，把泳道上的多个小提交
squash 成单个提交再合并，降低主干提交噪音。

**现状口径**（读码确认，2026-09-01）：当前是「agent 写、worker 代落盘」
（server/dsh/temporal-poc/dev_lane.py 的 worker 代落盘路径），每项变更一个
commit（仓库根 `CLAUDE.md` 硬规则 4、工单交付契约第 8 条），泳道并入
主干保留全部小提交。设计文档明示**「不以 rebase 替换 merge 策略」**——
见 `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
L84，冲突消解在泳道内以合并提交落账、不改写泳道历史。

**注意**：本提案与上述既定 merge 口径存在方向性张力（squash 改写泳道历史，
与「不改写泳道历史」相抵触）。是否采纳**需用户拍板**，本表只登记提案本身，
不代表 squash 是当前行为、也不预设要改。

**动机**：worker 代落盘的中间态 commit（同一工单多轮 gen）进入主干后，
主干 log 噪音大，回溯一段功能要跨多个中间提交。

**定级**：非阻塞（流程改进提案，不影响正确性）。

**建议（若拍板采纳）**：只动 merge 落账脚本——人审签字后合并时用
squash merge 生成单提交（提交信息引用工单号），泳道内小提交保留不动，
这样不与「冲突消解在泳道内不改写历史」冲突；需顺带定义 squash 后的
提交信息规范与冲突消解回合的落账口径。

## KI-005 人审 approve 签字无人工备注输入框

**现象**：工单台人审签字的 **approve（放行）** 路径没有人工备注输入框：
note 由前端自动生成的审批摘要填充（buildApproveSummary，index.tsx:1651、
调用点 2556），签字人无法补充自由备注（如放行前提条件、口头交代事项），
留痕断在台面上。**打回（reject/rework）路径已有必填理由框**
（doRework，index.tsx:2587-2590，「需要填写返工理由」），不受本条影响。

**影响**：非阻塞——打回侧理由留痕完整，缺口收窄为 approve 单侧的
自由备注；放行上下文目前只能去会话记录里翻。

**修复方向（登记，不在本工单做）**：签字确认弹层加可选备注输入框，
人工输入非空时覆盖/追加到 note（保留自动摘要做前缀），时间线与详情页
照现有 note 通道透传即可。

## KI-006 打回注记不落工作空间，接力只走内存与台面

**现象**：打回（rework）理由传给下一棒 agent 的通道是内存变量
`prev_ctx`（dev_lane.py:656-658，rework signal → `last_rework_note`）和
agent 审读打回的内联拼装（dev_lane.py:723-726），**不落任何写集内文件**。
next agent 能在 prompt 里拿到注记，但换 agent 接力、或下一棒要回溯「上一轮
为什么被打回」时，工作空间里没有可读的留痕，只能去工单台详情/时间线翻；
而时间线侧 rework 记录又有 KI-001 的盲区（agent 审读打回不写
`_mark("rework")`，base.py:375 是唯一写入点），两条缝叠加后 agent 打回的
理由在台面和工作空间都不完整。

**影响**：非阻塞——打回-返工回路本身正确（prev_ctx 注入不丢注记），
缺的是跨轮次/跨 agent 的可追溯留痕。

**修复方向（登记，不在本工单做）**：打回时把理由同步落一份进工作空间
固定接力文件（如 `.suyou/` 或写集约定位置），或统一 `_handoff` 摘要携带
完整理由；顺带修 KI-001 的 `_mark` 缺失，让时间线注记对齐。与 KI-007
（写集 refresh 静默跳过）互为表里，见 KI-007 互引段。

## KI-007 写集 refresh 静默跳过，回执缺 files_changed 零生效零告警

**现象**：create_plan 回执的 `files_changed` 为空或缺失时，写集刷新
`refresh_write_set` 走「无清单 → 保留初始写集」的跳过路径——只落一行
日志、时间线无任何条目。方案明明要扩写集（如 rework 注记要求补列文件），
结果零生效零告警：写入提示生效了，写入约束没跟上。

**机制**（读码定性，2026-09-01）：review_plan 通过分支读
`self.results["create_plan"]["files_changed"]`（dev_lane.py:701）；字段为
`None` 时仅一行 `_log("写集刷新跳过…初始写集保留")` 就过（dev_lane.py:702-704）；
字段为 `[]` 时走 `refresh_write_set` 并集后写集原样不变、added/dropped
均为空，同样零告警。时间线/横幅/`_mark` 全程无条目，跳过的存在只有日志
可查。纯函数本体在 shared.py:1231。

**实锤案例**：t260901-08 第 4 轮——打回注记明确要求扩写集 4 个路径，方案
回执 `files_changed=[]`，写集维持原样 5 条，4 个越界文件照常通过合并闸。

**影响**：非阻塞——正确性不受影响（只是不扩，不是误扩）；缺的是「方案与
写集脱节」这一防呆断点在台面零观测。

**处置**：待批次（只登记，不在本工单修复）。

**修复方向（登记，不在本工单做）**：两路可选，可并用——
a) rework 注记含路径但回执清单为空、或不覆盖注记所列路径时，review_plan
审读段强制打回（三态都覆盖：`None` 缺字段、`[]` 空清单、清单缺注记路径）；
b) refresh 跳过升级为时间线可见条目（`_mark` 或等价留痕），跳过不再是
只见日志的黑洞。

**互引**：与 KI-006（打回注记不落工作空间/不扩写集）互为表里——KI-006
说注记的传递留痕断，本条说注记的约束兑现断；修复工单建议合并处理。

## KI-008 RUNNING snapshot 查询失败无重试无显式降级（用户已拍板方向）

**现象**：inline 突变噎循环的主因（见 KI-003 机制结论）下，本条缺口
再被负载放大：详情接口 8s `wait_for` 到期即 `_err("snapshot 查询失败
（worker 在线？）")` 一字返回，无重试也无「这是瞬时抖动」的显式降级
口径（client.py:536/538）；列表接口 `_meta_of` 吞异常静默回 `{}`，行
退化为匿名行，用户看不出「超时了，刷新可恢复」（client.py:632）。

**机制**（读码定性，2026-09-01）：失败根因见 KI-003 机制结论（stage 转换
inline 突变噎住查询事件循环 + 多页签轮询风暴为负载共犯——工单台每个
页签对全部 RUNNING 票并发发 query，client.py:650 `asyncio.gather`）；本条
是失败**处理面**的缺口——既无重试也无显式降级，瞬时抖动被呈现为持续故障。

**影响**：非阻塞——不产生错误数据，但瞬时抖动被放大成「工单台坏了」的观感。

**修复方向（用户已拍板，登记，不在本工单修复）**：对 RUNNING 的 snapshot
查询失败**重试 1 次、间隔 2s**；重试仍败走**显式降级**——列表行标注
「查询超时，刷新重试」而非静默匿名行。与 KI-003 互引：KI-003 修事件循环
让路（根因），本条修失败处理面（兜底），不重复修复。

**落地注记（2026-09-03，t260903-06，本条 fixed）**：按拍板方向兑现并升级——
重试从「1 次间隔 2s」升为指数退避 3 尝试（阶段切换突变窗 1-2s 即恢复的实测
口径，KI-003 机制结论）；显式降级两层落地：引擎层 kind 分级回执（列表 degraded
行「查询超时，刷新重试」保留，KI-008 语义不变）+ UI 层 poll-health（连续失败
静默重试、保留上次成功快照、滞后角标，连续 3 次才错误态；in-flight 守卫防
轮询堆叠——不放大本条登记的并发 query 风暴面）。详情/列表最坏查询窗
3×8s+3.5s≈27.5s，由 UI 守卫兜住不叠加。

## KI-025 ticket 查询层谎报「工单不存在」

**现象**：见登记表行（实案 t260903-02，2026-09-03 01:44-01:47 连环 5+ 次，
值守险走数据抢救误路径；CLI describe 同刻证实 workflow 活着）。

**机制**（读码定性，t260903-06）：`ticket.py _v2_query` 对 `ticket-query` 的
**任何** `ok:false`（超时/连接失败/取消）一律 `return None` → `_show` 据此抛
「工单不存在」；工作台各只读路由把 ok!==true 一律映射 404。瞬时故障与真不存在
在唯一一条返回路径上不可区分——谎报面。review_plan 对抗核查补出两处结构洞：
①tools_registry.call 异常出口只留 message，分级字段若只在异常属性上必然湮灭；
②终态票（TERMINATED/CANCELED/FAILED）若落「瞬时请重试」文案=反向谎报（对死票
无限重试）。

**修复（t260903-06，fixed）**：kind 四级全链贯通——client.py 五出口穷举分级
（not_found 只能由 describe 命中 NotFoundFailure 触发；transient=超时/连接/取消；
terminal=终态永久，文案明说刷新无效；internal=畸形兜底）→ ticket.py
`QueryError(kind)` → tools_registry.call 异常口 duck-type 并入 kind（识别面
`hasattr(e,'kind')`，2026-09-03 对抗核查全仓零撞型）→ node.ts 统一分流
（404/503+retryable/410/500，kind 缺失一律 500 非 404）→ UI 只认 body.kind，
缺失/未知值一律按可重试降级。红线：「工单不存在」文案只能随 kind=not_found
产出，其余任何路径零「不存在」子串（场景按子串守卫）。

**回归用例**：integration/t260903-06/sc_query_kind_no_lie.py（A 瞬时/B 真不
存在/C 终态/D 畸形/E 缺 kind 上游/F 空 id/G 普通异常不带 kind，全链灰盒）；
integration/t260901-23/t01（分级+退避单元面 30 案）；workbench/tests/
ki025_show_error_split.mjs（node 消费端分流裁定）。

## KI-009 幂等重读不代落盘迟写文件

**现象**：agent 段的代落盘（`_settle_worktree_lane`）在「读到结果文件」
那一刻就执行并返回（agent_activities.py:528-545），agent 进程在结果文件
之后迟写的文件不在这次 settle 内；幂等重读分支（:477-492）也只 settle
重读当下看到的脏区，无法区分迟写归属——迟写文件要等下一次 settle 才被
代落盘，且可能与下一 stage 的改动混进同一笔 commit（错账）；末段票的
迟写则直接表现为 merge_check 见脏区或产物缺失。finally 的 terminate
（:552-560）会在返回路径上截断仍在写的 agent 进程，是迟写的直接来源之一。

**机制**（候选锚点，读码定夺，2026-09-01）：三个候选锚点——
a) 轮询循环读到合法结果文件立即 settle 返回，settle 早于 agent 进程退出
   （agent_activities.py:528-545 + finally :552-560）；
b) `skip_settle` 分叉期票：幂等重读跳过 settle（:486-489 注释「由汇合点的
   settle_lane 统一承担」），若汇合点已过则迟写无人兜底；
c) `_settle_worktree_lane`「工作区已干净则不动」的幂等口径（:312）在迟写
   场景可能恰好掩盖问题（迟写前重读 → 误判干净）。

**影响**：非阻塞——主路径交付不受影响；缺的是迟写文件的代落盘归属与
兜底，属收口账面精度问题。

**修复方向（登记，不在本工单做）**：候选锚点读码定夺后二选一——在
settle 前等 agent 进程退出（带超时），或把迟写检测接进幂等重读（对比
结果文件落定时间与最后写入时间）。具体方案由修复工单定夺。

## KI-010 审计日志读操作通胀：每次工具调用无条件 audit

**现象**：`tools_registry.call` 对每一次工具调用（含 params_get、
data_stat 等纯读工具）无条件向 server/admin.log 追加一条 JSONL 审计记录
（含完整 args 与 summary，tools_registry.py:95-110）；admin agent loop
一跑就是 ≤8 轮 × 每轮多个工具调用（admin.py:90-127），admin.log 被读
操作记录通胀，写操作的审计信噪比被稀释。

**机制**（读码定性，2026-09-01）：audit 无读写分类（tools_registry.py:
`def call` 单一路径 → `def audit` append），读与写享受同一记录粒度。

**影响**：非阻塞——审计不丢，丢的是信噪比与检索效率。

**修复方向（登记，不在本工单做）**：读类工具打标（工具 meta 声明
read_only），读操作精简审计（如只记 name+run_id 不记 args/summary）或
分流到独立日志；取舍需用户拍板（全量审计的诉求未做过确认）。

## KI-011 建票写集提示缺失：建单方三连犯 dev-lane 缺 integration/（改进提案）

**现象**：建单方连续三张（三连犯）dev-lane 工单的写集漏 `integration/`
（集成测试/收口物无处落，收口时才补扩写集）。

**提案**：建票表单的写集输入区加**非阻断提示**：模板选 dev-lane 且写集
不含 `integration/` 路径时提示「dev-lane 工单通常需要 integration/
（集成测试落点），确认不需要？」。

**现状口径**（读码确认，2026-09-01）：写集输入区在
`server/dsh/workbench/src/client/epics.tsx:739-747`，目前无任何按模板
类型的路径提示；建票口校验只查路径形状（不越界、不绝对路径），不查
「该模板该有的目录」。

**影响**：非阻塞——收口时能补扩写集（KI-007 修复后还有强制打回兜底），
缺的是建票时的前置提醒。

**注意**：提示必须非阻断、不强制——有的票确实只动 notes/（如本工单），
强制拦截会造成「为过提示而填假路径」的反效果。

**定级**：非阻塞（体验/防呆提案，不影响正确性）。登记提案，不在本工单做。

**建议（若拍板采纳）**：前端提示即可（epics.tsx 写集 textarea 下方一行
灰字或提交时 confirm），不动建票口校验语义；提示文案与模板清单的映射
写进表单常量，不散落。

## KI-012 agent 结果文件非法 JSON → 基础设施故障重试死循环，幂等锚点使 retry_qc 无法自愈

**现象**（t260902-07 实证，2026-09-02）：implement 段 agent 把结果文件
`.suyou/stage_implement_gen0.json` 写坏——evidence 字段里一个手滑的
`\-`（非法 JSON 转义，字节 2617 处）。agent 本体工作全部完成且正确
（交付物齐全、自测全绿、status=ok 写在文件里），但 activity 侧
`_read_result` 对解析异常**静默返 None**（agent_activities.py:285-289）
→ 轮询循环发现「文件不在但进程已退出」→ 抛
`RuntimeError("headless agent 退出（rc=0）但未写结果文件")`（:749-754，
错误信息与事实相反：文件在，是解析不了）→ Temporal 按基础设施故障重试
3 次全灭 → 工单 blocked。与模型配额无关（该段跑在 zai/glm-5.3-flash，
全程健康）。

**机制**（读码定性）：重试时幂等分支（:674-688）先 `_read_result`，
坏文件返 None → 不走缓存 → **re-spawn agent**；agent resume 后命中
「结果文件已存在即本段视为完成」的幂等锚点，**不会重写文件** → 退出 →
再抛 → 死循环。retry_qc 重跑同样穿过这条路径，**永远无法自愈**，只能
人工修文件（t260902-07 由 integration 纯格式修复 `\-`→`-` 后 retry_qc
解锁，agent 零重跑、零模型调用）。注意与 KI-009 相邻但不同：KI-009 是
「读到了但没 settle 全」，本条是「根本读不出来」。

**影响**：阻塞级——实际阻断 t260902-07 推进约 12 分钟（12:14:58 blocked →
12:26 人工修复），需人工介入才恢复；且 blocked 文案（「未写结果文件」）
误导排障方向（会先去查模型/配额，实际文件在、是解析不了）。

**修复方向（登记，不在本工单做）**：activity 侧二选一——a) 解析失败
且进程已退出时改报**业务失败**（StageResult failed，summary 带明文
JSON 解析错误与字节偏移，不再走基础设施重试）；b) 解析失败时把坏文件
改名挪开（如 `.bad` 后缀）再重试一次，让 agent 重写。另建议 agent 侧
契约补一句：结果文件必须 json.dumps 产出，禁止手拼字符串。

## KI-013 arbitrate spawn 日志占位符 3 传 2，每次仲裁派单都打 logging traceback

**现象**（t260902-07 实证，2026-09-02）：每次 arbitrate 派单，worker 日志
出现一段 `--- Logging error ---` 风格的 traceback，最后跟
`Message: "[t260902-07/arbitrate] spawn integration 仲裁（gen0，cwd=%s）…"`。

**机制**（读码定性）：agent_activities.py:2427 的格式串有 3 个占位符
（`%s…gen%d…cwd=%s`），实参只传了 2 个（ticket_id、gen）——cwd 漏传，
logging 格式化抛「not enough arguments」，traceback 进 worker 日志。

**影响**：非阻塞——logging 自吞异常，activity 照常跑；纯观测噪音 +
spawn 行里 cwd 永远记不上。

**修复方向（登记，不在本工单做）**：2427 行补第三个实参 `str(cwd)`；
顺带扫一遍同文件其他 `logger.info` 的占位符/实参配对（同模式手误可能
不止一处）。

## KI-014 manifest 共享可变尾文件是并行泳道的结构性冲突热点（改进提案）

**现象**（t260902-07/03/04 三连实证，2026-09-02）：每张 dev-lane 票的
design_integration_tests 按契约往 `integration/manifest.json` 尾部追加
条目。多张泳道并行时，先后合并进 main 会在同一尾部区域互相顶撞：
04 靠追加位置相距超过上下文行侥幸自动并过，03 撞实冲突，触发
「打回 implement 消解（agent）→ settle → merge_check 重验 → merge」
一轮完整回路——代价是一个 LLM spawn + 一次 verify_lane，换来的是
JSON 数组追加合并这种**确定性可算**的结果。

**机制**（读码定性）：worktree 隔离了代码写入面，但 manifest 是全仓
共享、每票必写的可变尾文件——测试注册表把并行隔离开了个共享口子。
两个衍生问题：a) 冲突结构性必然，并行度越高越频发；b) 任何泳道的
agent 理论上可改到别票的 manifest 条目（爆炸半径不受写集隔离）。
用 LLM 消解「按 name 去重追加」这类确定性合并，与引擎「杜绝幻觉、
确定性优先」教义不自洽——LLM 消解应留给语义性冲突。

**影响**：非阻塞——兜底路径能收敛（本轮一轮完成、无需重签），正确性
无损；损耗是并行批次的重复成本 + 消解结果的非确定性风险。

**修复方向（提案，采纳需用户拍板）**：
A) **manifest 分片（推荐）**：每票写 `integration/manifest.d/t<id>.json`，
   run_integration_tests 加载器 glob 目录按名排序拼接；存量 manifest
   迁移一次或保留为只读遗留段。冲突类从构造上消失，跨票篡改面同时
   收敛。动点：加载器一处 + design_integration_tests 契约文案 +
   manifest 相关测试口径。
B) 引擎合并预检：冲突文件清单仅含 manifest.json 时，worker 做结构性
   union-by-name（零 LLM）后重入 merge_check；其余冲突照旧走 agent。
   不动 schema，但给引擎开单文件特例，hotspot 本身保留。
C) 操作纪律：并行票串行合并。无成本也不解决问题，仅作过渡。

**拍板结论（2026-09-02，用户）**：三案均弃，直接**约定发现**——索引文件
整个退役，每票一个 `integration/t<id>/run.sh` 标准入口，加载器 glob 发现
（用户质询「为什么还需要 manifest 索引」驱动，论证见
notes/discussions/20260902-integration-约定发现-runsh.md）。状态维持
open，待修复工单落地后转 fixed。

## KI-015 _sh 输出裁剪至末 2000 字节，白名单 diff 大时假红 + 静默漏检

**现象**（t260902-05 实证，2026-09-02）：merge_check 白名单红
`越界写: ial/token-30d.json`——仓里不存在叫 `ial/` 的路径；该票 diff
56 文件，`--name-only` 全量 2650 字节，**没有任何真越界文件**
（integration/ 全部在写集内）。

**机制**（读码定性 + 逐字复现）：verify_lane.py:86 `_sh` 把 stdout+stderr
裁到最后 2000 字节；:363 `_diff_names` 用它取变更清单；:373 逐行判写集。
2650 > 2000，裁点落在行中间 → 返回文本首「行」= 半截路径
`ial/token-30d.json`（`integration/t260902-05/golden_serial/token-30d.json`
的尾巴）→ 前缀匹配必败 → 假越界 → merge_check 假 blocked。
`[-2000:]` 模拟逐字复现该假路径。

**影响**：阻塞级，双向——①假红误阻断（05 被卡）；②更危险的是裁点**之前**
的文件（约前 12 条，含 manifest.json）被静默丢弃、从未进白名单校验：
大 diff 票的合并闸写集覆盖是不完整的，越界文件若排在清单前段可漏网。
verify_lane 是合并闸守门组件，此为守门精度缺陷。07/03/04 未触发纯因
diff 小于 2000 字节，非逻辑免疫。

**修复方向（登记，不在本工单做）**：解析用途的输出不许裁剪——_diff_names
绕开 _sh 的裁剪（或 _sh 提供 line-boundary 安全裁剪 + 显式 truncated
标记，truncated 时白名单 fail-closed 报「清单不完整」而非照常逐行判）；
_sh 的 2000 字节裁剪仅保留给人类可读 detail 字段。修复工单建议与
KI-012（同为引擎重试/守门面）同批。

**修复记录（2026-09-02）**：用户拍板由 integration 直修（未走工单——
合并闸守门工具属 integration 职责面，改动仅 3 处）。`_sh` 加 `crop`
参数（默认 2000 保持人类可读 detail 行为不变），`_diff_names` 与
`_auto_scopes` 两处逐行解析调用传 `crop=None`。验证：①合成回归——
2349 字节 diff、越界文件排首行（旧代码裁掉即假绿），修后正确报
`越界写: evil.txt` 且 60 个集合内文件零误报；②t260902-05 真实场景
用主仓修后工具重验四项全绿。**注意**：merge_check 跑的是泳道副本，
存量泳道（t260902-05）需对齐 main 后才吃到修复。

---

## KI-028 模型路由表内容损坏静默默认模型

> 20260903 验收重编：原编 KI-027，与宿主令「工单关闭后动态流消失」条目撞号
> （登记权归 integration，宿主令编号不动）。

**现象**：model-routes.yaml（回落表或 ①d 声明表同）存在但内容不可解析（YAML
语法错、编码坏）时，spawn 静默退 profile 默认模型——无红、无日志、工单正常走。

**机制**（读码定性，2026-09-03，t260903-03 review C1 发现）：shared.py:913
`except Exception: return None`——文件缺失、解析错、权限错一律吞成 None，消费点
视同「查不到路由」不打 model patch。该语义先于路径契约化存在（t260903-03 只增
routes_file 参不动容错面，零回归要求使然）；契约 ①d「锚点 vs 内容」段已把边界
明文：paths 四态只覆盖声明值与锚点，表内容损坏继承查表容错，声明与否同语义、
不分叉（v1.6）。

**影响**：非阻塞——改错表/写坏表的用户得不到任何信号，错把「默认模型」当「表
生效」；排障时模型不对应先查表内容能否解析，而非只查路由键。

**修复方向（登记，不在本工单做）**：model_route_for 收窄容错——文件缺失维持
None 软语义、解析错改 fail-closed 红并点名表路径；或维持 None 但加 warn 日志。
取舍需拍板，另立工单。注意与 ①d 联动：改语义须同步改 ①d「锚点 vs 内容」句与
UT i3（test_paths_contract.py）/ 场景 G6（sc_paths_contract_doc_guard.py）两个
钉子——它们钉的是现状语义，修复必须让契约更准而非让红灯变绿。

---

## 变更记录

- 2026-09-01（t260901-07）：建表，首批 KI-001/002/003 入表，均非阻塞、open。
- 2026-09-01（t260901-10）：回填 KI-004/005/006（均非阻塞，KI-004 为改进提案）。
  存量三条复核：定位引用逐条对照当前代码核验（dev_lane.py 打回分支、base.py:375、
  shared.py:1083、agent_activities.py 四处 max_polls、client.py:536/636），
  全部成立无漂移，状态维持 open 不变。
- 2026-09-01（t260901-10 gen1）：修集成测试两红（KI-004 状态枚举收敛为 open、
  小节补全出处路径），按总管拍板回填 KI-007（写集 refresh 静默跳过，待批次）。
  **挂起**：用户下午另攒 3 条已知问题/提案未送达原始清单，本工单不占编号、
  不代拟内容；待用户补充后按顺延编号从 KI-008 起回填（KI-007 已被拍板占用）。
- 2026-09-01（t260901-17）：回填 KI-008、KI-009、KI-010、KI-011（均非阻塞、
  open；KI-008 为用户拍板方向条目，KI-011 为改进提案）；KI-003 条目内追加
  「机制结论」小节（用户观察 + 五次活体佐证：stage 转换 inline 突变噎住
  查询事件循环，多页签轮询风暴为负载共犯；原文逐字保留，追加式修订）。
  存量 KI-001~007 复核：定位引用逐条对照当前代码核验（client.py:536/538/
  632/650、base.py:112-119/375/568、agent_activities.py:477-492/528-560/
  312、tools_registry.py:95-110、epics.tsx:739-747），全部成立无漂移，
  状态维持 open 不变。
- 2026-09-02（integration 代记，用户指示）：回填 KI-012（阻塞级、open，
  t260902-07 实证：agent 结果文件含非法 JSON 转义 `\-` → activity
  基础设施故障重试 3 次全灭，幂等锚点致 retry_qc 无法自愈，人工修文件
  后解锁）。
- 2026-09-02（t260902-07 巡检代记）：回填 KI-013（非阻塞、open，
  arbitrate spawn 日志占位符 3 传 2，worker 日志每次仲裁派单打
  logging traceback）。
- 2026-09-02（t260902-03 冲突消解触发，integration 代记）：回填 KI-014
  （非阻塞改进提案、open：manifest 共享可变尾文件致并行泳道结构性
  冲突，附 A 分片根治 / B 引擎 union / C 串行纪律三案，采纳待拍板）。
- 2026-09-02（t260902-05 排障，integration 代记）：KI-014 追加拍板结论
  （约定发现方案，见 notes/discussions/20260902-integration-约定发现-runsh.md）；
  回填 KI-015（阻塞、open：_sh 末 2000 字节裁剪致白名单假红 + 前段
  文件静默漏检，t260902-05 逐字复现）。
- 2026-09-02（KI-015 修复）：用户拍板 integration 直修，_sh 加 crop
  参数、两处解析调用 crop=None，合成回归 + 05 真实场景双验证通过，
  状态 open → fixed。存量泳道副本需对齐 main 后生效。
- 2026-09-03（t260903-03 仲裁，integration 代记）：回填 KI-027
  （非阻塞、open：model_route_for 全吞容错致路由表内容损坏静默默认
  模型，shared.py:913；review C1 发现，契约 ①d v1.6 已明文为存量
  边界，修复另立工单并须同步改 ①d 句与两个语义钉子）。
- 2026-09-03（t260903-06 验收走查，integration 代记）：KI-027 撞号处置——
  模型路由条目重编 KI-028（原编 KI-027 与宿主令「工单关闭后动态流消失」
  条目撞号；宿主令编号不动、git 历史一致，登记表唯一号恢复）。同票走查另将
  baselines/sc_lane_parallel_dom.mjs P5 升级至轮询优雅降级新合同（静默窗
  角标→连败阈值红条→恢复清零，t260903-06 需求③；旧口径「单次失败立即
  红条」随需求③作废，P5 原始 intent「错误可感知、不崩溃」保留）。
  实弹探针另抓出 KI-029（Temporal 全断连路径不产 transient/无重试，
  venv 缺失时 traceback 直泄；降级方向安全，非本票回归面）。
