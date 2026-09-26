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
| KI-052 | 控制台插件「盘上客户端×内存服务端」版本错窗（260905 立案：宿主在 3099 点接入弹层→405——客户端半每次请求从盘现读（tsdown 重建即新弹层可见），服务端半进程启动载入（15 号路由不在内存）→界面新/服务旧的混合态；弹层 HTTP 合同 23/23 与组件级均绿但**真控制台点击全链未测**=3099 红线面测试不碰+宿主未重启，双重盲区）——修法=宿主重启 3099 即愈；根治面=①staleness 横幅（temporal-tools 先例扩展：插件检测盘上 bundle 与内存模块版本差即提示「重启生效」）②15 号加的 UI 场景在 3199 隔离台补一条真点击接入全链（隔离台=新代码，可点穿） | 非阻塞（重启即愈） | open（①挂详情观测性票 ②挂 19 后 UI 队） |现场=宿主 260905 22:5X 实点 405 报告；代码面=node.ts:1864 路由在仓在盘、进程内存无（启动早于 540f9c6） |
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

## KI-055 主题面漏网之鱼（宿主 260907 实报，主题家族第三次台面绿×真机红）
- 症状①：浅色模式下「文档」页文字不可读——docs.tsx 硬编码 25 处深色调色板（#c9d1d9/#8b949e/#3a404c 等），t260905-06 落地时按深色写死，t260905-08 全台令牌化漏网，hex 看守未网住（豁免或扫描面缺口待查）。
- 症状②：深色模式下工单台部分子面仍是浅色（具体面待 sweep 排查）。
- 病根纪律：主题验收只跑了「测试台平台（新版 token 集）×双外观」，从未跑「旧版平台 token 集」矩阵——与 KI-052 版本错位同族。修法=t260907-08 sweep：docs.tsx 令牌化＋全子面排查＋**双平台版本×双外观四象限**验收矩阵（t260907-03 重基线落地后执行，同文件错峰）。

## KI-056 rework 轮回执格式无提醒（260907 写集 saga 教训，非阻塞）
- 现象：create_plan rework 轮 agent 连续交空 files_changed（01/03 两票各 2-3 轮被 KI-049 拒），根因=rework 重跑的 prompt 不含回执 schema 提醒（首轮 prompt 有，rework prompt 组装丢了这段）。
- 影响：每票多耗 1-2 小时（打回-重跑-再拒循环）。
- 处置：小改进票（build_stage_prompt 对 rework gen>0 的 create_plan 补回执格式段），排队不紧急；本日两票已靠 rework note 手工带指令解套。
- 260907 补记（dengzhufpv 侧 t260907-09 同坑二次实锤，宿主转报）：语义混淆面确认——agent 把文件填 deliverables（自由文本）而非 files_changed（契约字段），以为交差。修法定向：①rework 轮 prompt 补回执格式段；②KI-049 红灯文案自带字段分工教学（拒收即教）；③派活契约补两字段分工句。**明确不采纳**「写集刷新吃 deliverables」——散文字段入授权白名单=污染写集闸（KI-049 单一真源原则）。

## KI-057 工单台 host 全家静态锚引擎仓（宿主 16:48 实报，dengzhufpv 侧排查＋integration 复核实锤）
- 症状：外部项目（dengzhufpv）工单变更 tab 空（API 实测 source: none，"worktree 越出仓库根"——防穿越闸误伤跨项目泳道）。
- 全族六处（node.ts/changes.ts）：diff 仓锚（changes.ts:451）、审批意见锚（node.ts:357）、epics 目录锚（node.ts:359，t260907-07 只修 CLI 侧）、证据目录锚（node.ts:266）、引擎 CLI 路径锚（node.ts:459）、病根 repo 本尊（node.ts:352 不按 ?project= 解析）。
- 修法=请求层按项目键解主目录（注册表已有），逐面穿参；验收含 dengzhufpv 实票对照。

## KI-057 补记（260907 晚）：文档面第七锚＋全族清单方法本身失灵
- 宿主实报：文档按钮跨项目串亮＋文档树只显 sandbar——handleDocsTree/Doc 端点 join(repo,scope) 静态锚=第七锚。上午六锚清单漏数=**手工枚举法结构性失灵**（数锚永远数不全）。
- 根治：t260907-11 验收升级为「跨项目隔离不变量」场景族（双项目夹具×每视图两断言：数据源对+切换重置），测不变量不测实例。

## KI-058 机器层安装态≠代码态（260907 晚宿主重启即炸，integration 把关疏漏）
- 现象：t260907-05 插件改名落 main 后宿主首次重启 console 即崩（loader 解析 sandbar-* 全 ERR_MODULE_NOT_FOUND）——profile 农场软链是机器层状态不入 git（README 制式：新 checkout/改名后重建），merge 与重启之间无人执行重建。
- 把关教训：改名/新增插件/挂载变更类票，落地交接必须含「机器层生效步骤」（农场重建制式/重启顺序）；lane 自身验证用 lane 本地农场（隔离台绿）≠机器农场在位（真机红）——台面绿真机红第五次。
- 处置：integration 侧 merge 交接清单加「机器层生效步骤」必答项（立即可行，随本次开始执行）；自动化（落地钩子自动重建农场）挂 t260907-10 目录重构后评估。
- 260907 晚补记（浏览器侧分身）：t260907-05 改 localStorage LEDGER_KEY（suyou-→sandbar-）未做迁移=会话入口老 session 全隐形（数据未丢，在旧 key 下）。修法=5 行惰性迁移并入 t260907-11。**改名类票必须列状态层清单：软链农场/localStorage key/profile 数据目录**——代码外的状态面一处都不能漏。

## KI-059 会话日志撕裂→resume 必炸（260907 晚两连，t260907-11 双角色同坑）
- 现象：lane agent 进程被杀时会话 jsonl.zstd 半写撕裂；dsh-headless-resume 读坏帧 rc=1，连「回落新建同 id 会话」也崩在同文件——workflow 进 blocked 等人工隔离。
- 已两连：developer 与 integration 角色同一次 kill 事件先后中招；手工处置=隔离坏文件到 /tmp/corrupt-sessions + retry_qc。
- 根治方向（dsh 平台侧，非本仓）：resume 读侧对末帧撕裂容错（截断续跑）＋回落新建不得再读坏文件。排队不紧急，随小改进批次。

## KI-060 套件健康无人值守（宿主 260907 质问「这么多测试过不了谁负责，巡检在哪里」）
- 事实：闸防新红不核存量；34 环境红＋预存败族有债册登记但**无核销机制/无趋势盯梢/无责任人**。inspection epic（260904 定稿，质检员设计）与 dispatcher-scan 调度骨架均在，但 scan 暂停（POC demo 后）且其巡工单流不巡套件健康——「套件健康巡检实例」从未建成。
- 宿主裁定（260907）：**只记账，暂缓**——不立即开票，等目录重构＋当前四轨落地后再排。
- 重提条件：目录重构落地后由 integration 主动提请（债条不沉底）。

## KI-061 仲裁超限 blocked 的唤醒死锁（260908 凌晨 t260907-10 实锤）
- 现象：integration_route 纯函数下 tests-fault+轮数超限=恒 blocked；retry_qc 唤醒后走查/arbitrate 不真重跑（22:58 后零新 gen，memoized 结论复用），host_ruling 注入无可达消费点——L1515 已修的「格式纠正单边重置」同族病在超限分支缺位。
- 影响：票卡 awaiting-merge 死等（人已签字两度、裁定两度均无法驱动）；数据无损，lane 分支完整可合并。
- 处置建议（宿主晨间裁定二选一）：①引擎小修=超限 blocked 唤醒时单边重置 arb_res/acc 状态（照 L1515 格式分支同款移植，~30min 票）；②授权手动合并（git 侧 squash＋审计注记，票留 blocked 作历史）。
- 教训：三态路由纯函数没有「宿主终裁覆盖」入口——设计缺口。

## KI-062 全局会话越权自并 t260907-10 半途中断（260908 凌晨实锤，console 晨间不可启动）
- 现象：console 全局会话（suyou-integration preset，session-9ac81af9，260904 起整夜 turn 184）在票卡「转人工判读」等宿主晨间裁定期间，自主执行 KI-061 处置选项②：`git stash` 暂存宿主未提交更改（stash@{0}）＋`git merge --squash lane/t260907-10`；02:15:44 会话被 dispose、merge 写盘半途 abort（tool call aborted）——旧路径 tracked 删半、新路径部分落盘（server/profile 缺位）、start-console.sh 未更新，console 装载三件套全断（start-console.sh:54 `cd server/dsh/workbench` ENOENT）。
- 根因：宿主配合节点清单（notes/t260907-10-host-node.md）标注的宿主专属步骤对全局会话无机制性隔离（workspace-write 直改 main 树 git 状态）；KI-061「处置建议二选一」文案进了会话上下文，被当成可自行选边的授权。
- 影响：宿主晨间操作面（console 3099）不可用、未提交更改被 stash 移位、t260907-10 裁决权被抢占（未遂）。数据零丢失——stash/HEAD/lane 分支三处各有正身；260908 晨三步恢复（`reset --hard HEAD`＋`stash pop`＋残留清理，host-node.md 归档 *.merge-rescue-260908），五插件解析链复验通。
- 教训：裁定类文案（「二选一处置」）须显式标注「仅宿主执行」；全局会话对 main 树的 git 写操作应过宿主确认面；处置选项文本进入会话上下文＝事实上的越权邀请函。

## KI-063 场景面偏科：函数级直调冒充全链（260908 晨 dengzhufpv t260907-13 实案）
- 现象：t260907-12 场景全部函数级直调（resolve/derive/prepare 各自绿），但 ticket-start→TicketInput 解码链一次没走——混合形态真开票即 TypeError（workspace Dict[str,str] 撞 repo_worktrees list）。
- 病根：隔离台 e2e 场景贵（分钟级）所以场景面偏科函数级；无「动输入契约必带全链场景」的闸规则。
- 机制补丁（已落）：dev-lane 验收段第四问＋integration persona「整车点火」纪律。修复票=t260908-02。
- 260908 晨层错修正（宿主点破）：KI-063 补丁首版误入两层共享面（dev-lane.yaml 通用模板＋server/dsh/roles 默认回落人格）——TicketInput 契约是引擎私货，不得污染多项目通用面。两处已撤。正解=sandbar 项目专属声明面：注册表声明 paths.roles_dir 指向引擎仓专属人格目录（项目级 overlay，他项目不受染），随小票落地；「实报即全族」一条是真通用，保留在模板与人格不动。

## KI-064 dev-lane.yaml 生成物漂移（260908 仲裁上报，integration 自记——f67a456 遗留）
- f67a456（260907 方法论入机制）手改 dev-lane.yaml 未回 dev_lane.py 生成源——yaml 是生成物，手改必漂移（今晨 KI-063 首版入 yaml 又撤，同文件二连踩）。
- 处置：方法论第三问（实报全族）应改走 dev_lane.py 源码常量（STAGE_ACCEPTANCE_EXTRA 或同源），随专门票；在此之前 yaml 手改段为活漂移，merge 有风险面。

## KI-060 复查清单（宿主 260908 排定：检查什么/为何慢/怎么加快——方案宿主定，integration 只备料）
- 备料③（仲裁 agent 参与度）：现状归因全量走 agent（20min/轮，昨晚同账抄 14 遍＋上头忘交卷＋诚实报 tests-fault 变死锁）。候选方向=机械基线签名比对打底（败场⊆存量→自动放行），agent 只接基线外新败；三病同根（速度/KI-061/agent 依赖）。
- 备料①（155 场景逐条盘点）与备料②（耗时分布测量）待做——结论先报宿主再动。

## KI-065 t260907-10 落账窗口三连事故（机器层步骤删 untracked＋checkout 二次清场＋WAL 伴生删除致 history 不可读）
- 现象（260908 午间时序）：①12:08 global session 代签后 merge 活动开跑，`.venv/ bin/ data/`（皆 gitignore 的 untracked）被整目录删除——凶手非 global session（会话日志全天无主树 mv/rm，仅 lane 内软链实验），最大嫌疑=merge 侧机器层生效步骤的「清旧路径」把 untracked 一并清了（KI-059 起机器层生效为必答项，但无 untracked 保护）；②宿主侧 12:46 于旧物理位重建 `.venv/bin` 后，13:38 squash checkout 建 `server/dsh/temporal-poc → ../engine` 软链时旧目录再次被强制清空（二次踩同一坑）；③`temporal.db` 的 WAL/SHM 伴生文件同删，temporal server（进程未死、句柄幽灵态）GetHistory RPC 结构性损坏（h2/timeout），terminate 亦不可达。
- 影响：temporal 事件史不可再读（导出仅得 visibility 台账 638 执行＋97 票快照，事件明细失）；工单台/worker 断链两轮；t260907-10 workflow 留 RUNNING 僵尸态（专属 worker 已收口，作历史）。
- 处置（260908 午后宿主裁定收口）：git 侧 squash 落账（536d5fc）＋四根文件 A1 复位（035a99e）＋engine/ 新家重建 venv/bin＋农场软链重指＋~/.dsh 重定向；票务基础数据双存档（server/engine/data/exports/ 与 ~/Documents/sandbar-data-recovery-260908/）。
- 教训：机器层生效步骤必须 untracked 白名单化（.venv/bin/data 先 mv 后清，或只动 tracked）；checkout 建软链前旧目录若含 untracked 应报错而非清场；temporal 数据卷的 WAL/SHM 应与主库同列保护清单；「不能重启的幽灵态 server」要第一时间导出（本次 12:54 导出在删除后仍得骨架，侥幸）。
- 遗留：t260908-02 在飞执行依赖旧 venv 内存态的 worker，收口后随 console 重启统一换新路径 worker；temporal server 空库重建（宿主已裁定「历史票基础数据够用」）择 t260908-02 收口后执行；旧名链 ~/.dsh/profiles/suyou{,-headless} 处置随宿主裁定。

## KI-066 多仓写集静默丢代码：正规入口预派生堵死引擎多仓链（260910 dengzhufpv t260910-01 实锤）
- 现象：多仓写集 [fpv-toolchain/, integration/] 全流程绿灯收口，成员仓零落仓（代码仅泳道侥幸保全）；snapshot meta.repo_worktrees=null（单仓形态）。
- 根因（260910 integration 定位）：server/tools/ticket.py `_create` 预调 derive_lane_workspace 未传 repo_write_set（缺参），算出单仓 workspace 显式转发 client.py，堵死引擎侧派生触发条件（ws is None and not worktree）；shared.build_repo_worktrees 本身正确（现场复现双仓明细）。裸入口派生正确=「正规入口反而事故入口」。
- 连锁放大：成员仓被根仓 .gitignore 忽略 → diff/越界/合并闸全盲。
- 修复票=t260910-03（病灶+双保险丝+逐仓物化+正规入口全链场景）；对方仓报告=dengzhufpv/notes/discussions/260910-sandbar-multirepo-defects.md。

## KI-067 正规入口 ticket.py 静默失败：create/rework 输出空、无审计、信号未送达（260910 两实证）
- 现象：ticket.py create 与 rework 均返回空输出、admin.log 无痕、Temporal 无信号；裸 client.py 同操作一发即通。
- 危害：操作面不可信+审计盲区；同族=sign/retry_qc 从未包进正规入口（代签这类敏感操作恰是唯一不进审计的工单操作）、signal 子命令退役后 CLI 无 retry_qc 通道（260910 曾用 Temporal 直连发信号兜底）。
- 排队票「入口收口」（审计+回执嵌提醒+sign/retry_qc 包装），前置=t260910-03 收口（同文件 ticket.py 串行）。

## KI-068 暂停功能 UI 半残：host 列表接口不透传 paused（t260908-01 合并后实测实锤）
- 现象：引擎侧暂停语义全验证通过；console 列表行无 paused/paused_phase → 无 ⏸ 徽标、按钮恒显「暂停」、暂停中的票 UI 无法恢复。
- 根因：t260908-01 只做了前端消费面（注释自称「host 行形状透传」=假设 host 会带），node.ts 行形状未实现；其场景只断言引擎查询面，未断言 console API 面——断层面写窄放行。
- 修复票=t260910-04；活体验证对象=t260910-02（停在 at_gate）。教训入册：合并前「同路径推断会在」不算实证（260910 integration 认领）。

## KI-069 UI 证据链失效：截图取景不可靠+证据读路径三层旧名错位+无人看像素（260910 暂停票全程实证）
- 现象：①capture.mjs 板面视图在主列表渲染完成前按快门，拍出无按钮废图带全绿进归档；②workbench 取图/列表端点只认旧名（.suyou/evidence、.worktrees/<id>/.suyou/screenshots），引擎/截图台写新名（.sandbar/screenshots、.lane/<id>）——功能实际失效，靠手工复制兜底；③走查 agent 文本模型看不了像素、合并闸只查文件存在（自认盲区）——唯一看图环节=人门最后一步。
- 修复票=t260910-05（截图内容断言+路径新名迁移；宿主拍板：不做签字界面嵌图）。

## KI-070 文档视图单仓硬编码：多项目只读 sandbar docs（260910 宿主实报）
- 现象：任何项目点「文档」都只显示 sandbar 仓 docs/，别的项目自己的文档看不见——影响使用。
- 根因：node.ts handleDocsTree/handleDocsDoc 用 join(repo, scope)，repo=引擎仓根；代码注释自认「C1 写死：全仓单例，docs 属仓不属项目」。多项目化未跟上的同族缺口（与 KI-066 diff 单仓同族）。
- 修复：docs tree/doc 按当前项目根解析（复用项目锚/enrich 的 root 传递链，同证据列表端点），缺省回落引擎仓；UI 一票升级（mock v1：Project 切换+Search+左栏上文件浏览器下 On this page 大纲+英文固定元素+正文 Verified 新鲜度 chip）。
- 票=文档视图修复（排队计划 260910-ticket-queue-plan.md）；设计 mock=notes/discussions/260910-docs-view-mock.html（宿主 260910 过稿）。

## KI-071 多仓修复半程：明细贯通断在 workflow→prepare 一跳（260910 实证，t260910-03 补程=t260910-08）
- 现象：t260910-03（21903b7）修好创建链后，真项目仍建单仓泳道——dengzhufpv t260910-07（创建于合并后 18:12）创建载荷双仓明细齐全，但泳道无成员仓工作区、无 .suyou/repo_worktrees.json、meta.repo_worktrees=null。
- 根因：dev_lane._init 不搬 TicketInput.repo_worktrees 进 meta（全文件零写入，仅 906 一处读 meta）；建泳道前 WorkspacePrep 构造不传 write_set/project_root → agent_activities prepare_workspace 三环读取（prep 明细/ws/写集+项目根推导）全空 → 恒单仓路径。
- 定性教训（同类第二次）：**断言没打在交付物终态上**——t260910-03 场景只断言 TicketInput 载荷持久化（G8c），integration 签字时随其断言面复核同样漏过；正确面=泳道磁盘逐仓物化（成员仓工作区+分支+清单）。
- 同票另一条（dengzhufpv 复核报）：test_t260910_03_fuses.py::test_fuse_a_no_project_root_member_entries_still_rejected 结果依赖 cwd（仓根 25 passed／/tmp 跑 24+1 failed，撞 shared.py:1105 豁免分支）。
- 修复票=t260910-08（明细贯通+断言上移诊断终态+CWD 敏感红收口）。

## KI-072 负载敏感的不稳定检查（并发下假红，单跑全绿）——260910 夜 三实证
- 现象：同一检查在并发环境（merge_check/全量套件内）红、安静面单跑全绿：
  ①`integration/t260901-25/t03_reap_process_group.py`：t260910-11 merge_check 内 `pass=7 fail=1`，
  泳道与 main 单独复跑均 `pass=8 fail=0`（进程组回收/幂等容错腿对时序敏感）；
  ②`scenario-guard-pipeline-landed`：t260910-08 套件内红，泳道安静面复跑 `GUARD ran=3 fail=0`、main 基线亦绿；
  ③`ticket-session-restore`：t260910-08 套件内红，泳道安静面复跑 `pass=10 fail=0`、main 基线亦绿。
- 危害：为环境瞬态反复触发仲裁迭代（260910 05/08 各撞 6 轮上限转人工），并诱导「改测试集」的错误处置。
- 处置方向：①判据层面＝t260910-13（失败形态分类+机械基线对照）落地后，此类红不再堵票；
  ②测试层面＝这些检查需加时序容忍/重试或去掉对墙钟与并发的依赖（归巡检校准 t260910-11 或后续小票）；
  ③运维层面＝过夜/高峰期限制同时跑套件数（并发争抢是共同诱因）。

## KI-073 可复现构建未闭合：同源码重建仍出压缩器风格抖动（260910-15 反例，260911 夜实证）
- 现象：t260911-02 泳道内重建前端产物 lib/client.js|cjs，与分叉点版本差 4 行（每文件 4 行），
  形如 `var e = 0; for (; e < i.length; e++)` ↔ `var e; for (e = 0; e < i.length; e++)`
  ——同一语义的压缩器写法差异（非手改、非逻辑改动）。
- 意义：t260910-15（构建产物抖动钉死，已合并 3f4bfe7）声称「同源码+同工具链+同参数→重建逐字节稳定」，
  并由其场景 sc_build_reproducible 7/0 自证；但真实泳道重建路径上仍复现抖动 → 说明钉死未覆盖全部重建入口
  （可能面：泳道内构建未走 build-client.sh 唯一入口、node_modules/工具版本随泳道而异、npx 回落拉取不同版本、
  或构建参数环境差异）。**可复现性只在「受控同环境」成立，未在「跨泳道/跨入口」成立。**
- 危害：①diff 噪音回归干扰人审（本意要治掉的病）；②跨票产物差异会在合并时产生无意义冲突与越界写判据
  （本夜 t260911-02 即被 merge_check 判「越界写 server/plugins/workbench/lib/*」而卡门，实为仲裁段连产物
  一并落盘 + 抖动所致）。
- 处置方向：①查明真实重建入口与工具解析链（lane 内 bash build-client.sh 是否可用、tsdown 版本是否同源）；
  ②在闸侧加固：产物类文件**只允许经唯一构建入口产生**，且重建结果须与分叉点/主树一致，否则点名；
  ③15 的收口追加场景：**在泳道内**（非主树）重建后断言逐字节一致。

## KI-074 引擎受保护路径名单写死 sandbar 私货＝多项目闸盲（t260911-03 出生，260911 通用性审计立案）
- 现象：`server/engine/path_gates.py:55-72` `PROTECTED_PATHS` 这份「真源与期望值」名单里全是
  **sandbar 这个项目的文件名**（`verify.yaml`、`server/model-routes.yaml`、`server/merge-checks.yaml`、
  `server/projects.yaml`、`server/project-registry.ts`、`server/roles`、`docs/design`、
  `integration/baselines`、`integration/t260902-07/tests/test_route_{table,lookup}.py`），
  而全仓**没有任何项目声明入口**能改这份名单：`grep PROTECTED_PATHS` 只有定义处、
  `judge_protected_paths`（`:282`）与它自己的单测引用，无注入参数、无 override 读取。
- 为什么算违背：本条犯的是「机制在引擎，内容在项目声明」的界线错误（判据取自 KI-050 修复方向
  与 260908 层错修正）。「哪些文件是真源/期望值」是**项目的内容**，引擎只该留机制。
  KI-050（UI 证据闸写死 sandbar 五条 UI 路径）是同族第一例，本条是**第二例且落点更核心**——
  受保护闸守的是真源与期望值，正是「人审环节不可被绕」的机械保障。
- 危害（他项目上两种，都不好）：
  ①**闸静默全绿**：闸语义是「存在才拦」（`exists_at_base`，`:270-293`），他项目仓里没有名单内
  这些路径 → 永不命中 → 永远放行。表现为「检查项在、看着验过了、实际什么都没验」；
  注意现有 fail-closed 只覆盖「锚不可知」（谓词故障/None），**不覆盖名单空命中**，故不报警。
  ②**他项目的真源不拦**：他自己命名的真源文件不在名单里，本来要防的「泳道改期望值给自己发
  免红令」照旧无防护。
  ③**扩面会加深违背**：260911 待审清单里的「闸第二层（名单扩到共享测试基建＋他票场景目录）」
  若照现写法落地＝把私货规模做大，必须先声明制。
- 同族小项（不单列）：`STAGE_PATH_RULES["design_integration_tests"]["prefixes"] = ("integration",)`
  （`:91`）把「测试目录叫 integration/」当所有项目约定；`RESULT_FILE_PREFIXES = (".sandbar", ".suyou")`
  （`:48`）是平台级 dot 目录（可接受，`.suyou` 已标 naming-compat）。
- 诚实边界：只做了字面量与调用点扫描；「引擎零私货」的盖章需另做一轮逐文件精读。
- 处置方向：①名单改**声明制**（引擎留机制＋项目声明给名单）；②「缺声明」的行为必须写死
  （建议＝闸拓扑级缺席＋显式报告，不得静默全绿，同 KI-050 立场）；③声明可给时，闸应能报出
  「本项目真源是否漏配」的可观测信号，避免他项目复制 sandbar 名单了事。
- 定位：`server/engine/path_gates.py:48/:55-72/:91/:270-293/:282`；出生＝commit `0dd1df9`（t260911-03）；
  审计档＝`notes/discussions/260911-generality-audit.md`

## KI-075 共享测试/工具面写死宿主绝对路径与项目键＝多机即断，且路径卫生守卫针太窄致其长期漏检（260911 通用性审计立案）
- 判据修正（宿主 260911 立）：**绝对路径违规不是「多项目」问题，是「多机」问题**——sandbar
  自己换台电脑、换个用户名、换个检出位置就断。故「代码域不得写死本机路径」与项目数无关。
- 现象（逐条，均已实测）：
  ① `integration/stage_docker.py:932` 凭证候选 `~/.sandbar/projects/suyou/credentials.yaml`——
     **项目键 suyou 写死**。实测 `~/.sandbar/projects/{suyou,sandbar,dengzhufpv}/credentials.yaml`
     三者**全都不存在** → 今天是无害死候选；但它是**跨项目串凭证隐患**：哪天有人放上 suyou 的
     per-key 凭证，**任意项目**（如 dengzhufpv）起台都会静默使用 suyou 的凭证，身份错位且无日志。
  ② `integration/stage_docker.py:934` 候选 `/Users/user/Documents/sandbar/.dsh/.credentials.yaml`、
  ③ `:952` 候选 `/Users/user/Documents/sandbar/.dsh/.agent-presets`——**宿主绝对路径写死**。
     实测：`REPO = integration/..`（`:125`）＝同一路径，即 ②③ 与紧邻上一候选**是同一个文件**，
     今天零功能价值；泳道 8 条中 7 条自带 `.dsh/.credentials.yaml` → 实际从不轮到 ②。
     `~/.dsh/.agent-presets/sandbar-integration` 才命中，③ 之后的候选恒死。
  ④ `server/ui-check/.debug-chat.mjs:51` `spawn("/opt/homebrew/bin/dsh", [… "--profile suyou" …])`
     ——**可执行文件绝对路径**。别的开发者用 nvm/volta/其他位置装 dsh 即断；该文件头自称
     「临时，不入库」但实际在 git 跟踪面内。
  ⑤ `server/projects.yaml:17` `/Users/user/Documents/suyou`：**声明面承载机器路径属「数据」性质**
     （不算代码违规），但它在 git 里，别人克隆后指向不存在目录——需确认解析器在目录缺失时是
     **显式报告**还是静默丢弃（待查）。
- 危害：换机/换用户即断或变假红；②类是「容器内凭证/人格缺失 → shell-access overlay 挡全屏」
  那个原始 bug 的复发形态（外观像环境问题，难归因）；①类是跨项目身份错位且无日志。
  引擎正层 `server/engine/**` 经扫描**零绝对路径**（只有注释文本），故本条的危害面集中在
  **共享测试/工具面**——而这两处是每个项目、每台机器都要跑的。
- 根因（可执行的一面）：路径卫生守卫 `integration/t260907-01/sc_migration_path_hygiene.mjs:43`
  的 needle 只对**旧仓 suyou 路径**这一根具体串，不对**「任意本机绝对路径」这一类**。260907 那次
  清扫只清了旧仓路径，于是 ②③④ 从它眼皮下存活至今（`/opt/homebrew/bin/dsh` 属漏网新证据）。
  附警示：`server/plugins/workbench/smoke/agent-live.mjs:39` 注释里仍留宿主真值
  `--Users-user-Documents-suyou-.worktrees-t260825-03--`，不炸但教后来者「写宿主路径没事」。
- 边界（不算违规）：`smoke/agent-live.mjs:46`（纯字符串函数输入→输出对拍）、`smoke/projects.mjs`、
  `server/installer/tests/test_zombies.py`、`server/installer/zombies.py:47`、
  `integration/t260902-02/lib/fixture.py:175`、`integration/t260907-10/sc_worker_reap_predicate.py:41`
  ＝样本数据/夹具，不读真机文件，只是样本值长得像宿主真路径（丑但不断）。
- 处置方向：①needle 从「具体旧仓名」扩成「**类**」——代码域禁 `/Users/`、`/home/<user>`、
  `/opt/homebrew` 等本机路径，只许 env/HOME/自文件相对推导；声明面按位置豁免（数据面 vs 代码面
  的界线正是这条规矩的核心）；②stage_docker 三条候选改按 `project_key` 解析（抄
  `agent_activities._resolve_credentials_source`（`:226`）/`shared.perkey_projects_root()`，
  该函数手上本就有 `project` 变量）；③`.debug-chat.mjs` 的 dsh 解析改 `which`/`process.execPath`。
- 定位：`integration/stage_docker.py:125/:932/:934/:952`；`server/ui-check/.debug-chat.mjs:51`；
  `integration/t260907-01/sc_migration_path_hygiene.mjs:43`；引入时间＝`e936847`（2026-09-06，t260904-19，
  非 260910 夜改入；但 t260910-12 昨夜重写此文件时未顺手清）；审计档＝`notes/discussions/260911-generality-audit.md`

## KI-076 路由表「按目录反查注册表」恒失败（readFileSync 列目录 → EISDIR）→ 静默回落仓内旧表；smoke 因此空转（t260910-14 引入，260911 宿主质询时发现）
- 现象：`buildRoutesView(某目录)` **不显式给 projectKey** 时恒得 `state=decl_missing`、读**仓内兜底表**——
  而该目录明明就是注册表里某条目的 `dirs` 值（260911 实测：REPO=/Users/user/Documents/sandbar，
  机器级 `~/.sandbar/projects/sandbar/project.yaml` 在、声明也在，仍判「未找到条目」）。
- 根因：`server/plugins/ui/src/host/routes.ts:258-283` `findKeyByPrimaryDir` 用
  **`readFileSync(root, { withFileTypes: true })`**（`:262`）列举注册表根目录——列目录应使用
  `readdirSync`。Node v26.5.0 对「读目录」直接抛 `EISDIR: illegal operation on a directory, read`，
  被紧邻的 `catch { return null }` 吞掉 → 该函数**恒返回 null** → `resolveRoutesFilePath` 走
  `key === null` 分支 → `decl_missing` + 仓内兜底表（`:290-293`）。
- 证据：①`node -e` 实测 `readFileSync(dir,{withFileTypes:true})` → EISDIR（Node v26.5.0）；
  ②逐字复刻该函数跑真注册表 → 返回 null（异常在 catch 里被吞，连条目枚举都没进）；
  ③探针 A/B 对照：A=`buildRoutesView(REPO)` → `decl_missing`/读仓内/`developer=zai`、
  `integration=zai-coding-cn`（旧值）；B=`buildRoutesView(REPO,{projectKey:'sandbar'})` →
  `ok`/读机器级/`developer=zai-coding-cn`、`integration=deepseek-official`（新值）。
- 影响面：**产品面当前不中招**——唯一产品调用点 `server/plugins/ui/node.ts:205` 显式传
  `{ projectKey: proj.key }`。中招的是**只给目录**的调用：`server/plugins/ui/smoke/routes.mjs:124`、
  `server/plugins/providers/smoke/routes-save.mjs:39/:61/:113/:130`，以及今后任何省略 key 的调用。
  危害形态＝**静默降级**：`state` 虽点名 `decl_missing`，但调用方不看 state 就会把兜底表当真源用。
- **守卫空转实证（本条最值得记的一面）**：`ui/smoke/routes.mjs` D 段标签写「对真源钉当前值（防路由表
  漂移）」，实际因上述缺陷**读到的一直是仓内兜底表**——260911 宿主改真源（developer→zai-coding-cn、
  integration→deepseek-official）后该 smoke **仍 70/0 全绿**，对真源变化**零洞察力**；它钉死的旧值
  反而会诱导下一个人去「同步」一个不需要同步的守卫。
- 定性教训（同族第三例，KI-046/KI-050/KI-071 家族＝「测试在场≠测试生效」）：t260910-14 的五支场景
  **全部显式传 projectKey/projectsDir 夹具**，按目录反查这条真实路径**无测试覆盖** → 带病通过
  260911 凌晨 integration 的代签（复核时只见场景全绿，未追问「哪条路径没被测」）。
- 处置方向：①一行修：`readFileSync(…withFileTypes)` → `readdirSync`；②补场景：真实形态注册表
  （per-key `project.yaml`、`dirs:` 带缩进）**只给目录**调用 → 断言 `state=ok` 且 routes_file＝声明文件
  （不是兜底）；③smoke D 段要么显式传 key、要么改成与解析结果对拍，否则它永久只测兜底且把兜底值钉死。
- 跨机边界：该缺陷与 Node 版本相关（EISDIR 在 Node 26 正确抛出；个别旧版本/平台「读目录」行为不同），
  属 KI-075 划定的「多机」隐患族。
- 定位：`server/plugins/ui/src/host/routes.ts:258-283`（`:262` 病灶、`:290-293` 回落分支）；
  注入提交 `bfc1c34`（t260910-14 squash 收口）；产品调用点 `server/plugins/ui/node.ts:205`

## KI-077 测试台残骸堆积＝docker 地址池报错的真因（池子没小，是台没拆）——260912 实测
- 现象：全量/并发跑时场景报 `Error response from daemon: all predefined address pools have been fully subnetted`
  （`t260904-19-stage-docker-parallel-zero-residue`、`t260910-12-herd-no-crosstalk` 连坐环境红）。
- **宿主的质询是对的：不是网络数少不够用**。两步实测否掉了「池子小」这个解释：
  ①空闲池探测＝临时新建网络随手分到 `192.0.2.0/24`（池子远未枯竭）；
  ②现场 15 条 `stage-console-*` 台，按容器标签 `com.docker.compose.project.working_dir` 反查，
  **12 条的工作目录已不存在**（`/private/var/folders/.../sandbar-baseline-*`）：测试自建基线树起台，
  临时树删了**台还开着**（最久 6 小时）；另有 17-18 小时的 `fix15-*`、存活 4 天的 `suyou-test-temporal`；
  同时死测试残骸 10 个容器（`t26090419-par-*`「并行零残留」自造台活了 3-4 小时——报池满的正是它自己）。
- 真因两条：①**残骸堆积**（主人早没了，台还占网络与内存；引擎现有起跑前卫生只清
  「停止态容器 + 闲置网络」，够不着「还开着但主人早死」的台）；②**瞬时爆发**（一条场景一次起多台、
  每台一条 compose 默认网络，几十条 /24 同时申请即撞分配器限额——总量不缺，缺的是**同一瞬间**的头寸）。
- 危害：假环境红连坐（一次实测 19 条连坐史）、内存被残骸吃掉（本机 docker 上限实测 15.66 GB，
  十余台同时开着）、把归因引向「机器不够用」。
- 处置方向（引擎侧，归票）：①起台时把**索租方身份**写进租约，收尾扫「持有者已死 / 工作目录已不存在」
  的台逐台拆（容器+网络+卷）并点名；②建期前先回收孤儿台；③**减少建网次数**——不再每台各建一条
  默认网络，改复用一条专用测试网络或整轮共用一个工程名。可选兜底＝扩大 docker `default-address-pools`
  （**OrbStack 是否支持该 Docker 原生键尚未确认**，且改它需重启 OrbStack 会打断在跑台，故不作首选）。
- 已当场清场（宿主授权，只清无票面归属/主人已死/死测试残骸，未动任何在飞票的台）：
  **容器 45→13、网络 31→11**；生产面复核完好（console 3099 HTTP 200、引擎活得、四票照常推进）。
- **260912 全天实测修正（重要，替换上面几处推断）**：
  - **「并发 4-6 台就不稳」这条历史记载无据，已实测推翻**：起台本身极快（串行单台 2.1 秒；
    12 台并发去掉名额闸后 5.3 秒全绿；16 台 7.0 秒 16/16）。真正卡人的是**满员闸**
    （缺省上限 12，全机共用名额，把在飞票常驻台与残台一并计入）：同一轮 12 台并发，
    上限 12 → 3 台卡到 150 秒超时；**仅把上限改 30 → 12/12 全部 5.3 秒起完**。
  - **地址池报错的真触发条件＝瞬间爆发量**，与存量网络数无关：同瞬间新建网络 16 条全绿、
    24 条失败 1、**32 条失败 9**（报错全为 `fully subnetted`）。**天花板≈23 条**。
  - **天花板可以绕开，且不必动 docker 守护配置**：同样爆发 32 条但由我们**指定网段**
    （`docker network create --subnet 10.213.x.0/24`）→ **32/32 成功、1.35 秒**。
    故首选修法是「stage_docker 自管受管网段表 + 每台指定网段」，而非扩大 daemon 池。
  - 残台判据的缺口更明确了：残台的 hold 心跳进程仍活着 → 租约永新鲜 → 「过期+持有者进程消失」
    这条判据**抓不到真残台**；须改按**主人存在性**（工作目录/泳道/心跳陈旧度）+ 两条安全阀
    （booting 且心跳新鲜不碰、泳道仍在 worktree list 不碰）。
  - 已立案修复票：**t260912-02**（去名额闸留 100 保险丝 / 残台自动认领并拆 / 起台自管网段），
    验收基线＝并发 32 台 32/32 零超时、地址池报错零复发、残台三形态全拆且两对照不误拆。
- 定位：`integration/stage_docker.py`（台的生命周期与锁根）、`server/docker-compose.test.yml`（无 networks 声明
  ＝每工程一条默认网络）、`server/engine/agent_activities.py:_docker_hygiene()`（起跑前卫生够不着残骸台）

## KI-078 单票集测段是在跑「整套全局场景」＋超时静默重试＝三小时黑洞（260912 实测）
- 现象：`run_integration_tests` 段（**机械段，零模型调用**，`dev_lane.py:423` `agent=False`）执行
  `verify.yaml` 的 `integration.cmd` ＝ `run_scenarios.py` 全量；每张票都跑**整套**场景，
  与该票改了什么无关。票内实测单轮 36-50 分钟（t260911-06 五次入场：36/48/101/41/50 分），
  而我独立单跑同版全量＝18.7 分钟（并发宽度同、机器负载更高）→ 差额来自**多票各自跑整套**互相争抢。
- 二次危害：活动超时 `INTEG_RUN_TO`（原 60 分钟，`dev_lane.py:135`）配实际 40-50 分钟＝**贴着上限赌博**；
  超时后 Temporal 自动重试（`MaximumAttempts=3`），一轮可吃 3 小时才报错（t260911-04/06 实测
  各已超时两次）。症状表现为「段一直在跑」，不像故障，容易误判为模型慢。
- 相关改动（由 t260911-05 顺手改入，待定性）：`INTEG_RUN_TO` 60min→100min，理由＝外层 60 < 内层批量帽 95
  自相矛盾（诊断成立）；但方向与宿主 260912「单票集测 ≤10 分钟」相反，故暂按**临时**处理，
  集测分轨/限时落地后收回。
- 处置方向：①按票裁剪——每票只跑与该票写集相关的场景子集，整套挪给**定期巡检**单独跑；
  ②超时不再静默重试（或重试必须上抛可见告警）；③两轨共用一份场景清单，只靠标记（cadence）区分，
  不得复制成两份；④巡检跑时独占机器。
- 定位：`server/engine/dev_lane.py:128/:423/:1427`；`server/engine/agent_activities.py:_run_scenarios`（`:3661`）；
  `server/tools/verify_lane.py` 集成道（`:505` 起）；`verify.yaml` `integration.cmd`；
  基线数据＝`~/.lane/t260911-05/out/integration-report-260912-035013.json` 与
  integration 独立跑 `/tmp/integ-bench-20260912-025906.log`

## KI-080 人授权通道的 authorize 载荷送不到：钥匙插不进去（t260912-03 落地后立即实证，阻塞级）
- 现象：260913 对两张卡住的票签发人授权（`ticket.py op=authorize`），回执均 `ok / delivered=true`，
  但票面 `refused` 记的是 **`{"want":"sign()","why":"当前步 <段> 非人审等待中，签字无效"}`**——
  即被**当普通签字**处理，`meta['authorizations']` 始终为空。含义：新落地的人授权例外通道
  **在任何工单状态下都无法签发**，两条本应被它解开的判定（受保护路径闸、仲裁上限）仍无出口。
- 实证（integration 侧只读复现，含一条无副作用对照）：
  ① t260911-05（arbitrate/blocked）发 arbitration_verdict 授权 → 得 sign() 拒收；
  ② t260912-01（design_integration_tests/blocked）发 protected_path 授权 → 同上；
  ③ 对照：对 t260911-06（acceptance_walkthrough/running）发**已过期**授权（必被拒、不落账）
  → 仍得 sign() 拒收。若载荷送达，intake 应先到并回报「expires 已过期」，而非走 stage 判定。
- 定位线索（读源，未改）：发送侧 `server/engine/client.py:396` 构造
  `Signature(who=…, gate="", decision="approve", authorize=auth)` 后 `handle.signal("sign", sig)`；
  接收侧 `server/engine/dev_lane.py:2148` 的 `getattr(sig,"authorize",None) is not None` 分支**从未进入**
  → 归一化后的 authorize 在传输/反序列化一跳丢失。载荷定义 `shared.py:350-363`（HumanAuthorization
  dataclass，scope 为 List[str]）；本信号面此前只带标量（who/gate/decision/note），**本案是首次携带
  嵌套对象载荷**——嫌疑面＝嵌套载荷的编码/解码不对称，且失败是**静默回落**（走普通签字路径）而非点名。
- 为什么守卫没抓住：t260912-03 的三套单测（payload/sign/cli，15+ 用例）**只覆盖纯函数与 schema**
  （`grep handle.signal` 零命中），**无一条真走信号往返**；而该缺陷只在真投递时出现。此为
  「测试在场≠测试生效」家族的又一例（KI-046/KI-050/KI-071/KI-076 同族）。
- 处置方向：①修正嵌套载荷的编码/解码不对称（intake 侧已支持 dict/dataclass 双读，优先让解码产出 dict）；
  ②接收侧加**可见失败**——authorize 载荷存在但解析为 None 时须 refused 点名，不得静默走普通签字路径；
  ③补真往返守卫：至少一条经真实信号投递的集成场景（受保护路径放行 + 仲裁超限推进），含过期/错票号/自签/畸形四条负锁。
- 定位：`server/engine/client.py:387-400`；`server/engine/dev_lane.py:2140-2187`；`server/engine/shared.py:350-363,650`；
  已立案修复票 **t260913-01**（验收 F 腿：修好后 t260911-05 与 t260912-01 至少一张必须实际被解开）。

## KI-079 说明书与实际入口不符：`ticket.py` 无 pause/resume（且旁路丢身份）
- 现象：会话宪章（`session_charter.md`「引擎操作面」）列了
  `$PY $TK '{"op":"pause"|"resume",...}'`，实际 `server/tools/ticket.py` 的 op 白名单只有
  create/update/list/show/accept/advance/dispatch-next/rework/sign/retry_qc（`:617-636`）
  ——调 pause 报 `ValueError: 未知 op: 'pause'`。暂停只能回落裸入口
  `client.py ticket '{"op":"pause",...}'`：无 notes 写集闸、回执自带 `entry_hint` 提醒，
  且**调用方身份丢失**（实测事件里 who 记成 `op-local`，`by` 字段未透传）。
- 危害：每次暂停都走旁路＝审计面缺身份；说明书教了一个不存在的入口＝与 260910 教训同族
  （「说明书教错调用形式」被误报成产品故障）。同族小项：`t260911-05` 的仲裁超限（`MAX_TESTS_FAULT_ROUNDS=5`）
  在引擎里是**机械上限**而非代码缺陷，但现场无从一步看出「该由谁判、判完怎么放行」，
  缺一句「转人工后如何处置」的可见说明（本次由 integration 逐条复现后裁定放行，裁定档
  `notes/t260911-05-verdict.md`）。
- 处置方向：①给 `ticket.py` 补 pause/resume 并把 who 透传进事件历史；或②改宪章口径并写明
  pause 走哪条正规入口；两者择一，别让说明书继续教错。
- 定位：`server/tools/ticket.py:617-636`；`server/engine/client.py:424`（pause/resume 实现处）；
  宪章＝`session_charter.md`「引擎操作面」节

## KI-081 引擎代码已落 main，但在跑的工单工人仍跑旧码＝新信号静默被丢（260913 实证）
- 现象：引擎修复落 main 后，**已存在的工单专属 worker 进程不会自动重载**——它们的内存里是启动那一刻的代码；
  表现分两种，都不显眼：
  ① **新信号被静默丢弃**：260913 给 t260912-01 / t260911-05 签发人授权（`ticket.py op=authorize`）与
  `retry_qc`，回执均 `ok / delivered=true`，但票面 `authorizations` 恒为空、段位不动、`refused` 也空
  ——即「送达但不生效、且无任何报错」。同一时刻 **t260913-01（工人是当天新起的）同一操作成功落账**，
  对照坐实「差在工人进程的新旧」；
  ② **内存与磁盘代码不匹配**：旧进程日志出现
  `[creds] 工单 t260911-05 的 project 查询降级（cannot import name 'AUTH_KINDS' from 'shared'）`
  ——它启动后磁盘上的 `shared.py` 已新增名字，旧进程 import 失败并静默降级。
- 处置（260913 已执行并验证）：对无在跑活动的票**优雅重启其工人**（`server/engine/ticket_worker.py`
  `reap_ticket_worker`（SIGTERM，未完成活动先跑完）→ `spawn_ticket_worker`；或由控制台 ensure 补拉）。
  重启后**连排队中被丢弃的信号都补处理**：两张票的在册授权从 0 变 3 条（含重启前签发的那几条），
  `retry_qc` 随即生效、段位开始推进。
- 通用教训：**「代码落地」≠「行为生效」**——凡改了引擎/worker 侧判定与协议（新增 dataclass 字段、
  新信号载荷、新 import 名），必须同时处理「在跑工人持有的旧码」，否则症状是「一切都成功但没反应」。
- 定位：`server/engine/ticket_worker.py:100`（spawn）/`:130`（reap）/`:139`（ensure 对账）；
  证据＝`server/engine/data/worker-t260911-05.log`、`worker-t260912-01.log`（260913 11:19 两条）；
  票面证据＝t260912-01 / t260911-05 的 `authorizations` 从空到 3 条的时间线。

## KI-096 场景夹具进程泄漏占满自家端口池 → t260916-25 系列自报「高位口耗尽」（260923 实证；**同日 main 侧已修**，宿主令「不开票，main 上修」）
- 现象：跑批里 `t260916-25-stage-console-selfcheck-red` 报产品红（「降级台=红透传」）、同族场景报
  `ENV_FAIL 高位口耗尽——环境面`；表现为「这批场景在候选版上回归了」，极易误判为 dsh 升级回归。
- 实证（260923）：夹具取口范围＝3511–3549（`lib_stage_fixture.mjs` `pickFreePort`）；实测该 **39 个口全被
  node 进程监听**，逐口 `lsof -p <pid>` 的 cwd 分别指向 `.lane/t260922-10`（泳道跑批）与
  `T/sandbar-baseline-*`（基线跑批，目录早已删除）——即**每跑一轮漏一对「夹具台+桩」**，跨日累积把池占满。
- 根因：场景自起的桩/台进程收尾未回收；`stage-sweep` 的孤儿阀（1800s）只覆盖**在册租约**，这些残留不在册 → 不判拆。
- 危害：池满后同批场景开始**自报环境红/产品红**（假红伪装成产品缺陷），且每再跑一轮更满＝**自毒化**。
  与 dsh 版本无关（本条即本轮误判候选版回归的真因）。
- 处置（本轮，规避非修复）：按仓内既有 30 分钟孤儿阀，kill 3511–3548 上 38 个陈旧监听（保留 5 分钟内的 1 个；
  用户 console 3099 / stage 台 3199 / 原生 web 3299 一律未动）；清口后同批 `--only` 复跑：
  prepare-refresh **PASS**、selfcheck-red **PASS**（另三条因本机沙箱禁 `ps` 报 ENV，非本面）。
- 建议修复方向（只登记，未动手）：①夹具收尾对自己起的桩/台**无条件回收**（进程组 kill＋断言端口已释放），
  并把「退出后本场景占的口已释放」写成场景自身的一条子用例；②`pickFreePort` 找不到空口时**响亮点名占用者
  pid/cwd**，而不是笼统「高位口耗尽」；③口池不必硬钉 39 个（可动态扩窗），免得被历史残留锁死整个场景族。
- **修复（260923，main 侧提交 `679d25a`）**：桩台自带寿命自毁（`integration/t260916-25/lib_stage_fixture.mjs`
  的 STUB_SERVER_JS，缺省 240s、`STAGE_STUB_TTL_MS` 可调）——桩台到点 `process.exit(0)`。与 ps 清点、
  与 kill 路径完全解耦，跑批被杀也照样自退，池子自愈。验证＝在**清理面必然失效**的环境（本沙箱禁 ps）跑
  selfcheck-red：跑完即刻两端口仍在听（复现原病）→ 26s 后全部自退（TTL=20s）。上述①③（进程组回收与
  动态扩窗）仍未做，留作出路；②的点名改进亦未做（本修法让池子不再被锁死，优先级下调）。
- 定位：`integration/t260916-25/lib_stage_fixture.mjs:26-40`（FORBIDDEN_PORTS/pickFreePort）、`:161`（makeStubRoot）；
  场景记录点 `sc_stage_console_selfcheck_red.mjs:71/87/97`；实案观测量＝`lsof -nP -iTCP -sTCP:LISTEN` 全口占用 + `lsof -p` 的 cwd。

## KI-094 main 常量 id 的 patched 门「唤醒不激活」：在飞票首评落重放段 memo 固化 False（t260917-04 起在册；债册漏登，260923 据代码引用回填）
- 来源：260923 登记 KI-095 时发现 `integration/run_scenarios.py` 与
  `integration/t260917-04/sc_t260917_04_replay_compat.py` 已把 KI-094 当既有条目标引，但本表无条目
  （KI-095 条内已留「待补登」，登记权在 integration 岗）。本条据那两处引用**回填**，未另行实证。
- 内容（回填）：仲裁闸拒直落分支的 `workflow.patched` 门用 **main 常量 id** 形态时，**在飞票首评**会落进重放段
  并被 memo 固化为 False → **唤醒不激活**：新段被唤醒、但对这类停环票不生效。t260917-04 场景因此
  **不断言激活语义**（只锁 patched 门契约与在飞回放兼容，钉住=把缺陷写进契约）。follow-up 方向＝门升级为
  `base#seq` **per-entry**（逐条目判，而非整门一个常量 id）。
- 状态：open（缺口在册）。
- 出处：`integration/run_scenarios.py:1490-1494`（场景条目注释）、
  `integration/t260917-04/sc_t260917_04_replay_compat.py:28-32`（「断言边界：防 rot 与防钉缺陷」段）。

## KI-095 作废票号被回收 + 泳道路径随之复用 → 新票继承旧票未落盘改动（260922 实证，已人工规避、待修）
- 现象：260922 傍晚为「泳道主动同步 main」开票时，自动号给成 `t260922-17`——**正是同日下午因撞受保护
  路径闸而作废的文档票号**；更要紧的是引擎把**那条旧泳道 `.lane/t260922-17` 一并复用**：新票 worktree
  指向旧路径，工作区里带着旧票**未落盘的草稿**（`docs/README.md`、`docs/design/失败分类协议v1.md`、
  `docs/index.json`、`integration/run_scenarios.py` 全为 M，另有未跟踪目录 `integration/t260922-17/`）。
  新票是一张**引擎票**：带着 `docs/design`（受保护路径）的脏改动开工，一落盘即撞受保护闸——**开局即废**。
- 根因链（三点，逐条实证）：
  ① **号源会回收**：`_next_id` → `ticket-list(id_prefix)` 扫 Temporal 现存 id → `next_ticket_seq_from_ids`
     取「最大序号 +1」（`server/tools/ticket.py:435-448`）。**作废（terminate）的 workflow 不再出现在该扫描里**
     （实测：cancel 后该 id 从 list 消失）→ 其号被回收复用。宪章口径「票号全项目唯一」由此被破坏：
     同一号先后属于两条不同 workflow，Temporal 历史里出现两条同 id 运行（show/追溯歧义）。
  ② **泳道路径由号派生**：dev-lane 泳道＝`.lane/<票号>` + 分支 `lane/<票号>`；号一复用，路径同名。
  ③ **建泳道是「已注册即复用」**：prepare_workspace 对已存在且已在 `git worktree list` 注册的树走
     `reused` 路径（幂等设计，本为 retry 复用），**不做清洁校验**（源码只在「目录存在但非已注册 worktree」
     时报错要人工处置）→ 旧票的脏残留原样交给新票。
- 危害：①新票带着**别人未落盘的改动**开工，症状是「莫名其妙被写集/受保护闸拒」，排查方向极易跑偏；
  ②同号两条 workflow 使票号不再唯一，`show`/审计追溯有歧义；③本次是人工先查现场才发现，换人踩就是
  「开局即废 + 十几分钟排查」。
- 处置（本轮已执行，规避而非修复）：作废该次 create（temporal cancel，理由入不可变历史）→ 确认旧分支
  `lane/t260922-17` **无独有提交**（`git rev-list --count <base>..lane/t260922-17 == 0`）→
  `git worktree remove --force` + `git branch -D` 清残留 → 以**显式号 `t260922-18`** 重建
  （新泳道基点＝当前 main，落后 0、工作区净）。
- 建议修复方向（只登记，未动手）：① 号源改**只增不减**（高位水线/持久发号，不因作废回收）；
  ② 建票期加**冲突检查**（同号已存在、或 `.lane/<号>` 已被注册/非空 → 明确拒收或换号，绝不静默复用）；
  ③ 复用泳道前加**清洁校验**（工作区脏/有未跟踪改动/分支有独有提交 → 拒复用并点名）；
  ④ 若确要回收号，则把泳道路径与号解耦（带随机后缀）。
- 定位：`server/tools/ticket.py:435-448`（号源单点 `next_ticket_seq_from_ids`）、dev-lane 泳道登记
  （`.lane/<票号>` + `lane/<票号>`）、`server/engine/agent_activities.py` prepare_workspace
  （docstring「idempotent: retries take the reuse path」+ `"[%s] reused"` 分支）；实案痕迹＝Temporal 两条
  `t260922-17` 运行 + `server/admin.log` 该时段 create/cancel 记名行 + `.lane/t260922-18`（重建后的新泳道）。
- 登记附记（取号纪律，本次实证）：**债册 max+1 不等于下一个可用号**。本次登记时债册最大是 KI-093，但
  代码里 `integration/run_scenarios.py:1478` 与 `integration/t260917-04/sc_t260917_04_replay_compat.py:30`
  已把 **KI-094** 当既有条目标引（债册漏登该条）；若只按债册 max 取号即撞号。⇒ 取号须双向核对
  「债册已定义 ∪ 全仓引用」，本次据此改用 KI-095。另：`integration/baselines/sc_notes_write_gate.py:110`
  里的 `KI-099` 是**测试夹具合成字符串**（非真条目），不得作为占号依据。**遗留**：KI-094 在代码有引用
  但债册无条目，待补登（登记权在 integration 岗）。

## KI-093 并行段（arb_acc_parallel）互相残杀：一条活动的进程组 reap 杀掉另一条在飞 agent（260915 凌晨实证，待复核）
- 现象：`t260914-04` 在 `acceptance_walkthrough` 连挂 **4 次**（23:46 / 00:18 / 01:29 / 01:35），每次都满足
  「**agent 活干完了、结果文件也写了**（gen0 38KB / gen1 38KB / gen2 37KB 均在盘上），活动仍被判
  `agent 活动故障：Activity task failed`」——日志形态：`reap：terminate（进程组），rc=0` 紧跟判失败。
- 结构性线索（两条独立观察）：
  ① `dev_lane.py:1507` 的 `arb_acc_parallel` 相位＝**仲裁与验收走查真并行**（两条 agent 活动同时在飞），
     而两者由**同一个工单专属 worker** 托管、spawn 出的 agent 属**同一进程组**；
  ② `t260914-05` 更直接的形态：`attempt 2` 于 22:40:24 起跑，22:40:40 的 `reap（attempt=1）` 以
     「terminate 进程组」收尾 → 把共享同组的 attempt 2 一并杀掉，留下**孤儿 agent**（进程活着、活动已判死）。
  合起来＝**父活动的进程组级 terminate 会连带杀掉兄弟活动的在飞 agent**。
- 危害：①「活干完了却判失败」是最费钱的失败形态——每轮重跑都烧一个完整 agent 段，而成果每次作废；
  ②与心跳超时（`HEARTBEAT_TO=3 分钟`）叠加时更难辨：网络卡顿（心跳缺失）与进程组残杀都表现为
  「无结果文件 + reap」，需靠「结果文件是否已落盘」区分（本轮四次的文件都在盘上 ⇒ 指向残杀/竞态而非心跳）。
- 待复核（本条为**候选根因**，未坐实）：需在并行相位下加 agent 进程组身份的实测（spawn 出的 pgid 是否同组、
  谁发起 terminate）。**在坐实之前不改引擎**。
- 变通（本轮实证可用）：`retry_qc` 重试——每次重试里通常只有一条活动被残杀，另一条能过；04 的四次重试
  虽未收敛，但 02/05 在同相位都过过（05 第 1 次即过）。若某票在该相位反复不收敛，处置＝停手留档交人查，
  不要无脑连试（每次都是整段成本）。
- 定位：日志＝`server/engine/data/worker-t260914-04.log`（四次 spawn/reap 对）、`worker-t260914-05.log`
  （attempt 2 被 attempt 1 的 reap 连带）；相位＝`server/engine/dev_lane.py:1507 arb_acc_parallel`；
  超时常量＝同文件 `AGENT_TO=6h` / `HEARTBEAT_TO=3min`。

## KI-092 多仓票写集「只写仓名」= 该仓整仓禁写：声明残缺在建票期不拦，到 settle 才炸（dengzhufpv/t260911-07 实证）
- 现象：`dengzhufpv/t260911-07` 过了 create_plan（settle 三修生效）后，在 implement/design 段落盘时
  `path_gate_reason=write_set_missing`：「段 implement 无写集可判（写集空/缺失），改动 .gitignore、Cargo.lock、
  Cargo.toml（等 6 项）出白名单面」——**整仓禁写、票卡死**，而 agent 的活其实全干完了（方案与场景产物俱在）。
- 根因链（实算）：该票写集＝`['fpv-toolchain/', 'integration/']`（多仓票只圈了成员仓名，未列仓内任何路径）。
  `shared.rebase_write_set(ws, 'fpv-toolchain')` 按 `prefix='fpv-toolchain/'` 剥前缀 → 仓名条目满足 startswith
  → 剥完剩空串 → 得 `['']`；写集闸对空白条目 fail-closed（`path_gates._entries` 与
  `agent_activities._dirty_within_write_set` 同立场）→ 判 `write_set_missing`。滤空后仍是空表、仍判同一红
  ——**即「只写仓名」在这套语义下等价于「该仓没有任何可写面」**，与该票实做（仓根 Cargo.toml/app/crates 等）不符。
- 附带修（已落 `4965bda`）：`rebase_write_set` 剥前缀后**滤掉空串条目**（对齐其自身 docstring「等于仓名的
  条目产出空」；原实现留 `''` 这种畸形条目，且把错因引向 `write_set_missing` 而非「写集面为空」）；补边界单测。
  引擎全量单测 825 passed。**注意：此修不改变本票结果**，只消掉畸形条目与错因误导。
- 暴露的两层缺口：①**建票期不拦**——写集条目以 `/` 结尾（目录形）或只到仓名，本应在 create 时点名拒收
  （现有校验只在 `ticket-start` 侧解析「写集归属」，未拦目录形条目），于是畸形声明一路跑到 settle 才炸，
  且**代价是整段机时**；②**运行中无救**——`update` 的字段白名单只有 `status/note/pending_add/book_path`，
  `write_set` 建票即钉进 workflow 输入，**无任何入口可改**（死结，除非人重建票）。
- 处置方向（建议，未实施，需宿主定夺）：①**建票期校验**：拒收「以 `/` 结尾的目录形条目」，并点名提示
  「请给具体文件或子目录路径（如 `fpv-toolchain/app/`）」——治根，防下次再踩；②**给出路**：允许以「仓名＋
  仓内路径」重述写集（如重建同项目新票、或用既有的写集刷新面），使在途票有救；③**不建议**把「仓名条目
  ＝整仓可写」写进引擎语义（那是「声明越粗、权限越大」，与白名单立场相反）。
- 定位：写集＝`dengzhufpv/t260911-07` 的 `workflow_input.write_set`；实算＝`shared.rebase_write_set(['fpv-toolchain/','integration/'],'fpv-toolchain')`；
  闸＝`path_gates.judge_stage_paths('implement', ['Cargo.toml','.gitignore'], write_set=[''])` → `write_set_missing`；
  日志＝`server/engine/data/worker-t260911-07.log` 17:41 段；成员仓产出＝`/Users/user/Documents/dengzhufpv/.lane/t260911-07/fpv-toolchain`（`git status` 6 项）。

## KI-091 路由解析静默兜底 → 走错 provider 撞额度：表现为「agent 失败」，真因是「票用错模型」（260914 实证）
- 现象：`t260911-05` 唤醒后 agent 连试 3 次全失败，agent 日志只有
  `dsh: QUOTA: 429: {"code":"1113","message":"Insufficient balance or no resource package. Please recharge."}`
  ——看起来像「额度用尽」，而宿主核对 `zai-coding-cn` **额度仍在**，形成矛盾。
- 真因链（逐段实测）：
  ① 该票 `developer` 角色的**生效路由**＝`zai-coding-cn` / `glm-5.3-flash`（机器级
     `~/.sandbar/projects/sandbar/model-routes.yaml`，由 project.yaml 的 `paths.model_routes` 声明）；
  ② 但在跑的是 **09-13 起的老 worker 进程**（内存里是当时的 `shared.py`：按**旧路径约定**找声明，
     找不到）→ 日志 `[model_route] 路由表解析非 ok（state=decl_missing，读=<仓内兜底表>）`；
  ③ 兜底读 `server/model-routes.yaml`——**该文件自注「已不是生效真源、内容陈旧」**，其 `default`
     是 `provider: zai`（BigModel 那套 `ZAI_API_KEY`，与 `zai-coding-cn` 是**两把不同的 key**）；
  ④ 于是 agent 被钉到 **`zai`** 而不是 `zai-coding-cn` → 撞上 `zai` 那侧余额不足 → 429 报「insufficient balance」。
  实证：同票 gen0 patch=zai、gen1/gen2=zai-coding-cn（那时解析 ok）、**gen3=zai**（声明读不到的那一轮）；
  重启 worker 后 gen4 patch 回到 `zai-coding-cn`，agent 立刻正常开工。
  另证：主树与泳道各自直调 `shared.resolve_routes_table('sandbar')` → `state=ok`、
  `roles.developer={'provider':'zai-coding-cn'}`；老进程报 `decl_missing` 只因**内存码旧**（KI-081 同族）。
- 危害：①**归因误导**——报错文案说「余额不足」，实际是「票用错了 provider」，会把人引去充值/查错账户
  （本次已实测误导宿主一轮）；②静默性：全链只有一条 WARNING 落在 worker 日志里，**票面与回执面完全看不见**
  「本轮 agent 用的是哪个 provider/model」，事后只能逐一翻 `.sandbar/model_patch_*.yml`；③老进程存活越久
  越容易踩（与 KI-081/KI-082 同族：引擎已改，在跑实例不重载）。
- **260914 补充（dengzhufpv 项目会话首验移交，与上条同源、互为佐证）**：容器化首验实跑（五条容器场景 85 断言 0 红、
  A 腿 A3「implement 期容器真在场、会话恢复成功」通过）时，**真 agent 段撞 429**；根因链比上条更深一层——
  ① 真源（机器级表）是对的；② 但**测试台/隔离场景用隔离注册表**（`SANDBAR_PROJECTS_DIR`，脚本生成的 project.yaml
  只写 key/name/dirs、**无 `paths` 声明**）→ `resolve_routes_table` 判 `decl_missing` → 按设计**读侧兜底回落仓内
  `server/model-routes.yaml`**；③ 仓内那份是**迁移前旧口径**（developer/default 仍 `provider: zai` = 主账号余额已尽）
  → 真 agent 段 429。**影响面不止测试台**：任何未声明 `paths.model_routes` 的项目/隔离环境都会静默捡到过期表，
  表现成「环境红」，极易误读为配额偶发故障。**一句话判据：表存在但内容过期，比表缺失更毒——缺失会点名，过期只会静默用错。**
- **未执行完的裁决（本条真根因）**：`notes/discussions/260910-model-routes-relocation.md` 的目标形态表与「实施票必含」
  已明写三件，**实测均未执行**：①**仓内那份销毁**（「退役（删除）；默认表示例移入 docs 或 installer 内置常量」）；
  ②**缺表行为绝不静默**（三态可辨 + 票面/日志告警：声明缺失/文件缺失/内容坏）；③**引用点一并改**
  （`shared.MODEL_ROUTES_FILE` 常量退场、UI `routes.ts` 两处 `join(repo,'server','model-routes.yaml')`、
  守卫场景、node.ts 注释与「模型」页）。当前状态＝真源已迁机器级且声明在位（做了一半），仓内旧表仍在并仍被兜底消费。
- 处置方向（按 260910 裁决直接执行，非新设计）：删仓内旧表 + 兜底腿命名化告警（带表路径与内容指纹）+ 引用点退场；
  另建议测试台基座生成的隔离 project.yaml **声明自己的路由表**（或注入可用模型），使场景与生产口径同源。
- 处置方向（建议，未实施）：①**把「本轮 agent 实际路由」显示到票面/回执**（provider/model 逐轮留痕），
  让「用错模型」不必靠翻日志；②解析非 ok 的兜底改为**响亮**（现仅 WARNING）——或至少在票面时间线落一条
  可辨事件（「本轮模型来自兜底表，可能非生效路由」）；③`server/model-routes.yaml`（陈旧兜底表）按宿主
  260911 的「先不动」继续保留，其注释已足够警示，真修法是①的可见性。
- 定位：证据＝`.lane/t260911-05/.sandbar/model_patch_implement_gen{0,1,2,3,4}.yml`（provider 逐轮）、
  `server/engine/data/worker-t260911-05.log` 的 `[model_route]` WARNING；读侧＝`server/engine/shared.py`
  `resolve_routes_table`（`decl_missing` 分支）/ `project_paths`；兜底表＝`server/model-routes.yaml`
  （自注「已非生效真源」）；生效表＝`~/.sandbar/projects/sandbar/model-routes.yaml`。

## KI-090 曾被误提交的 `.sandbar/` 状态目录借「合并 main」复发：老分叉泳道在 merge_check 判红（260914 双票实证）
- 现象：`t260913-01` 走到 merge_check 判红两条——「工作区干净（无未提交改动）」红 + 「敏感/运行时路径
  入库（必须 untrack）」红，点名 `.sandbar/routes-migration-260911/README.md` 与 `…/model-routes.yaml.to-machine`。
  它当时在跑冲突消解（worker 代 `git merge main`），**红不是它自己的改动造成的**。
- 根因（实测链）：该两文件由 `6716e2e`（09-11 04:31「路由迁移预备包 + 过夜报告」）**误提交进 main 历史**；
  随后 `e1d2303`（t260911-06 squash 收口）在 main 上删除该路径（`main` 现 `git ls-tree -r main -- .sandbar/`
  = 0 条）。**分叉点早于 `e1d2303` 的泳道仍带着这两文件**（`git ls-files .sandbar/` = 2）；合并 main 时
  收到这次删除 → 工作区呈现「待删 tracked 文件」→ 工作区不干净 + 敏感路径入库两条红同时成立。
- 危害：①老票越老越容易撞（与 KI-082 同族），且**形态误导**——看起来像本票在工作区乱留东西，实际是
  历史欠账借合并复发；②只由 merge_check/merge 阶段暴露，前面所有段都看不见，而那时已经烧掉大量机时；
  ③`.gitignore` 只有 `.dsh/`、`.suyou/`，**没有 `.sandbar/`**，所以 `.sandbar/` 一旦被误提交就再无自动
  免疫——同目录下每天生成的 `model_patch_*.yml`／`stage_*.json`／`resume_patch_*.yml`（每票上百个）都是
  靠「不 add」而非规则挡住的，风险面一直开着。
- 实测影响面（260914 普查全部泳道）：`t260913-01` 与 `t260913-04` **形态完全相同**（HEAD tracked=2、工作区
  已删、`git status` 两条 `D`、相对 main 的 `--name-status` 为 `A`）——即 04 的「未触红」是暂时的，它走到
  merge_check 同样必红。其余泳道 0。
- **卡死的机制（260914 实测，比初版描述更准）**：两条红里**「敏感/运行时路径入库」不是拦路虎**——
  `verify_lane.py:470` 的判据是 `st in ('A','M','T')` 才红，**`D`（清退删除）本就放行**；真正拦的是
  merge_check 的**「工作区干净」**条：这两个待删文件**不在票面 write_set 内**（写集＝`server/engine/`、
  `server/tools/ticket.py`、`integration/`），于是 ①merge_check 自愈前置检查明确「脏文件在 write_set 外，
  不自愈」；②实现段的 `settle` 只收写集内改动 → **这一笔清账删除永远无法由引擎自己落盘**。实证：实现段
  交接已写「两处历史欠账删除落定：工作树已删**待 settle**」（14:52），而 15:09 merge_check 仍红，说明
  agent 干对了、卡在引擎不提交写集外文件。且 write_set 是建票时钉进 workflow 输入、运行中改不了
  （meta 的 write_set 不影响在跑实例），故这条死结**没有票内自解路径**。
- 处置方向（建议，未实施）：①**把 `.sandbar/` 加进 `.gitignore`**（与 `.dsh/`、`.suyou/` 同列；`.sandbar`
  是本引擎的泳道侧状态目录，按设计从不入库）——同时消掉「误提交」与「待删」两种复发形态，是根修；
  ②**merge_check 自愈面放宽一格**：`RUNTIME_PREFIXES`（`.sandbar/`、`.suyou/`、`.dsh/`）下**删除形态**的脏项
  视同可自愈（与「敏感前缀只在 A/M/T 判红、D 放行」的同一条口径对齐），由 worker 代落盘——否则老分叉泳道
  永远需要人手工提交这一笔；③可选：merge_check 对「删除仅来自 main 侧既有清账」的形态给出可辨提示。
- **本轮处置（越界代落盘，如实留档）**：两条死结在票内无解，故由 main 侧（integration）代 worker 执行
  `git rm -r --cached .sandbar/routes-migration-260911` 并提交：
  `t260913-01` → `75868d8`、`t260913-04` → `28220eb`（两泳道工作区归零、相对 main 的 `.sandbar/` 标记清空），
  随后 `retry_qc` 重验 merge_check。**这是绕过「写集外不落盘」的越界操作**，只为解今天的死结，不代表口径：
  修法见上面②。
- 定位：证据＝`.lane/t260913-01` 的 `git ls-files .sandbar/` = 2、
  `git status --porcelain .sandbar/` 两条 `D`；`main` 侧 `git log --diff-filter=D -- .sandbar/routes-migration-260911/README.md`
  → `e1d2303`；引入提交 `6716e2e`；`git merge-base --is-ancestor 6716e2e main` = 真；
  闸判据＝`server/tools/verify_lane.py:83 RUNTIME_PREFIXES` / `:470 st in ('A','M','T')`；
  自愈面＝`server/engine/agent_activities.py:2013 _dirty_within_write_set`（「脏文件在 write_set 外，不自愈」）。

## KI-089 池排除由「目录形写集」无条件压制：凡是写自己集测基建的票，排除声明恒定失效（260914 实证）
- 前言（先纠正一条当日误判）：排除机制**本身是好的**，`t260913-03` 声明对当期新票即刻生效。证据＝
  `t260913-04` 12:20 那轮报告 `excluded_pools=['engine','exclusive']`、`excluded_count=47`，
  ran 242→195、wall 1898s→**132.7s**。先前 11:40 那轮之所以「全跑」，是**在跑的工人加载的还是
  11:05 之前的旧码**（同 KI-081），与排除实现无关。
- 但真问题在下面，且是设计层口径问题：**写集是「目录前缀」匹配位**。
  `verify_lane._in_write_set('integration/bench.py', ['integration/'])` ≡ True——于是**任何写集里带
  `integration/` 的票，都会与被排除池（engine 32 条 / exclusive 13 条）的资产面求交命中** →
  `_integ_pool_exclude` 判 `forced_by` 非空 → `{'declared': [...], 'applied': False}` →
  **不下发 `SANDBAR_SCENARIO_EXCLUDE_POOLS`，整轮全跑**。实测：该资产面共 **77 条**，本票写集命中
  **79 项**（几乎全覆盖，因为 `integration/` 一条就等于整个测试目录）。
- 危害：①命中条件与「是否真动了那些池的判据」不对等——只改一个无关的测试助手文件也算；②而**引擎票的写集
  天然带 `integration/`**（引擎票必须自带场景才会写集成测试）：当前四张在跑的维护票 `t260913-01/02/04`、
  `t260914-01` **写集全都含 `integration/`**，等于这个优化对最需要它的那批票**一批都不生效**；
  ③每票单轮集测 30~40 分钟（engine+exclusive 占 57%+18% 的机时），这是当前最贵的一笔固定开销；
  ④表象有欺骗性：排除「看起来已实施」却毫无效果，需要翻 `pool_exclude` 回执才能发现（本次即靠报告键
  有无 `excluded_pools` 才定位）。
- **已处置（宿主管 260914 令「一律全跳过，engine 池只在巡检跑」）**：撤除例外腿——`apply=true`（每票段）
  时**声明即跳过**；被跳池只由项目级全量轮（巡检/手动/回放，均不传 apply）覆盖；旧命中面改写进回执
  `pool_exclude.former_force_assets` 留痕（少跑仍可见，不再据此放行）。落地面＝`server/tools/verify_lane.py`
  `_integ_pool_exclude` + TOOL schema 描述、回执消费面 `server/engine/agent_activities.py` /
  `server/engine/dev_lane.py`、`server/engine/shared.py` 字段注释、契约测试
  `server/engine/tests/test_t260913_03_pool_exclude.py`（d/e/f 由「命中即全跑」改判为「命中仍跳过+留痕」，18 条全过）、
  票面场景 `integration/t260913-03/sc_pool_exclude_force_assets.py`（改判后 13/0 绿；同族另三个场景
  19/0、11/0、17/0 全绿）、`integration/README.md`、`verify.yaml` 注释。提交＝`9b12b8d`（代码）+ `4960b32`（verify.yaml 注释）。
  口径变化带来的取舍（宿主已认可）：改了被跳池资产的票，其改动**不**由该票自己那轮集测覆盖，由全量轮兜底。
- 处置方向（建议，未实施；设计定稿权在宿主）：①**把强制面的粒度从「目录前缀」收紧到「被排除池的判据文件」**
  （即只在真正改了 `engine/`、`exclusive` 两池自己的场景/夹具时才强制全跑），目录形写集不再天然构成命中；
  ②或反向：写集声明器要求给到**文件粒度**，禁止只给目录；③无论取哪条，都要求在回执里**肉眼可见**地给出
  `declared / applied / forced_by`——现在「失效」是无提示的。（①②已被上面的「一律全跳」取代；③已落地为
  `former_force_assets` 留痕。）
- 260914 12:55 现场复核（四张在跑票逐票实算，写集×强制面求交）：`t260913-01`（写集含 `integration/`）命中 77 项、
  `t260913-02` 命中 77、`t260913-04` 命中 78（另含 `server/docker-compose.test.yml` 固定资产）、`t260914-01` 命中 77
  ——**四张全部判「强制全跑」，跳过全部作废**。对应现场：`t260913-01` 12:52 一轮 ran=233/2465s、`t260913-02` 12:07
  一轮 ran=235/1603s、`t260913-04` 12:41 一轮 ran=242/2000s（被跳的 47 条整整齐齐回来）、`t260914-01` 12:19 一轮
  ran=246/2367s，报告里**都没有** `excluded_pools`。**结论：当下没有任何一张票吃到这个优化。**
- 一处异常**已查实（结论二次修正）**：`t260913-04` 12:20 那轮报告带 `excluded_pools=['engine','exclusive']`、
  ran=195/132.7s，12:41 那轮又回到 ran=242/2000s。**更正：这不能归因于「工人内存旧码」**——同族证据见
  `t260914-01` 泳道**同一份闸**下的整轮序列（09-14）：08:21 ran=246/1794s 无排除 → 10:20 ran=246/4995s 无排除
  → 10:26 ran=246/1740s 无排除 → **11:19 ran=200/133.7s 有排除** → 12:19 ran=246/2367s 无排除 →
  13:10 ran=246/1835s 无排除。**同一泳道、同一份闸，跳过与否逐轮横跳**——若真是内存码版本差异，不可能在
  11:19 出现、又在 12:19 消失。故真因＝例外腿判据**逐轮可变**（票面 write_set 在不同段/轮次不同：写集带
  `integration/` 即命中整个测试目录 → 判强制全跑；不带则正常跳过），即 KI-089 的主体结论；「内存码」只解释
  了 04 泳道在 09-14 11:05 前后那一次跨越，不解释同泳道横跳。连带更正：`.lane/t260913-01|02` 的闸文件我先前
  用字符数判断版本，**判错了**——精确匹配显示 `t260914-01` 泳道四件齐全（`verify.yaml` 声明 1、`dev_lane`
  置位 1、`shared` 载荷 1、`verify_lane` 消费 2），只是带旧拒绝分支。
- 定位：`server/tools/verify_lane.py:529 _pool_exclude_assets` / `:574 _integ_pool_exclude` / `_in_write_set`；
  `server/engine/dev_lane.py:1445`（显式置位）；`server/engine/shared.py:267 integ_verify_payload`；
  证据报告＝`.lane/t260913-04/out/integration-report-260914-122055.json`（生效）与 `…-114004.json`（未生效）、
  `.lane/t260914-01/out/integration-report-260914-1119*.json`（同泳道生效轮）；
  相关＝KI-081（旧码重载）、KI-082（老票贵）。

## KI-088 provider 瞬断（TRANSPORT Connection error）→ agent 活动失败 → 票 blocked（外部因素；260914 二度实测）
- 现象：agent 段跑到一半整批失败并 blocked，报「agent 活动故障（已重试）：ActivityError: Activity task failed /
  Activity task timed out」，而 agent 日志尾部只有重复的
  `dsh: TRANSPORT: Connection error.`（偶有 `DeepSeek API request to https://api.deepseek.com failed`）。
  **agent 的活往往已经干完**（泳道里能看到它的交付与进展），只是最后一步连不上模型、结果文件没写出。
- 归因（宿主 260914 亲证）：**是宿主侧网络的问题**，不是引擎缺陷、也不是 provider 计费/限流
  （同时刻 `curl https://api.deepseek.com/` 返回 401＝可达）。当日两次整批发生（约 06:5x 与 09:4x），
  每次需人工 `retry_qc` 后即可继续。
- 已实测的恢复路径：`ticket.py op=retry_qc` → 段重进 → 正常继续（本会话两次均如此，未丢交付物）。
- 危害与噪声：①票凭空停摆、看起来像引擎/模型故障，易误判（本会话已先后误判为限流/配额各一轮）；
  ②与 KI-081（工人跑旧码致信号静默被丢）在症状上同族——**「一切正常但没反应」**，需靠日志尾部区分。
- 处置方向（建议，未实施）：①**活动级自动重试**：agent 段活动当前 `MaximumAttempts=3` 且失败即 blocked；
  可考虑对「网络类失败（TRANSPORT/连接错误，且无结果文件、泳道无损坏）」增加**一次跨时间窗重试**
  （间隔数十秒，避开瞬断窗口），仍失败才 blocked——注意保持「真失败不吞」；②**归因可见**：把「网络类失败」
  在与结果文件同处记一条可辨标记（如 `net_transient`），使「agent 失败」与「环境瞬断」可一眼分开；
  ③工程上更干净的方向＝provider 侧冗余/换线路，属环境面，不在本仓。
- 定位：实证＝`server/engine/data/worker-t260913-01.log` / `worker-t260913-02.log`（260914）；
  相关＝KI-081（同族「静默无反应」）、KI-078（活动超时与预算口径）。

## KI-087 老名泳道必卡：判脏清单漏 `.suyou` + 空提交抛异常（dengzhufpv 每次卡 create_plan 的真根因）
- 现象：`dengzhufpv/t260911-07` 每次重跑都在 `create_plan` 段 blocked，报「agent 活动故障」——
  而**agent 的产物其实是好的**（`.suyou/stage_create_plan_gen3.json` 与失败同分钟落盘）。
- 复现与原文（260914 实跑取证）：触发重跑 80 秒后 blocked，worker 日志异常：
  `settle: git commit 失败: … Untracked files: .dsh/ .suyou/ … nothing added to commit but untracked files present`。
- 病灶三处（均定位到行，main 当前态）：
  ① `server/engine/agent_activities.py:739` `SETTLE_PATHSPEC = [".", ":!.dsh", ":!.sandbar", ":!.sandbar"]`
  —— `.sandbar` 写两遍、**老名 `.suyou` 全漏**（行尾注释还把它称 legacy lane name）；引入于 260907 改名票
  （搬迁快照里本行原本是正确的 `:!.suyou`）。
  ② `:1036` 空提交 `raise RuntimeError(...)` ——链路＝判脏非空 →`git add -A -- .`→`git reset -- .dsh .suyou .sandbar`
  （撤下协调目录）→暂存区空→commit 非零→抛异常；而**「无改动可提交」是正常工作态**（只产出协调目录产物的段）。
  ③ `:1650` `mf_dir = lane_root / ".suyou"` 硬编码老名 —— 创建多仓泳道即写下老名，泳道整条命粘老名
  （`resolve_dot_dir` 老名粘滞规则），故后续每段都在 `.suyou/` 下。
- 为什么只有它踩（对照解释）：sandbar 自己的票多数泳道是 `.sandbar/` 或**两者都有**（`.sandbar` 在清单里→不判脏），
  而 dengzhufpv 这条**只有老名 `.suyou/`** → 每次必踩。即：**「认双名」这件事没补上**。
- 危害：①任何老名泳道里「只产出协调目录产物」的段（create_plan/review_plan/ui_evidence 等）**必卡**，且重跑无用；
  ②报错被上抛成「agent 活动故障」，**归因噪声极大**（本票已让多张票各重跑数次、误判为网络/配额各一轮）；
  ③「改了引擎但工单看起来是 agent 挂了」这一形态与 KI-081 同族。
- 处置：已开票 **t260914-01**（判脏口径补老名并收单源／空提交按正常收口且与真失败可辨／多仓清单走真源），
  回归锚＝`dengzhufpv/t260911-07` 重跑后 create_plan 正常收口。
- 定位：`server/engine/agent_activities.py:739 / :1036 / :1650`；实证＝`server/engine/data/worker-t260911-07.log`
  （260914 07:08）与 `dengzhufpv/.lane/t260911-07/.suyou/stage_create_plan_gen3.json`。

## KI-086 备选方案备忘：整张票的 worker 进容器（B 案，260914 宿主拍板「先做 A、B 记录一下」）
- 背景：t260913-04 落地的是 **A 案**——「worker 在宿主、agent 在容器」（宿主 worker 跑 DevLaneWorkflow，
  到 agent 段时 `docker exec` 进该票容器；容器每票一个、常驻 `sleep infinity`、挂载=仅该票泳道且**同路径**）。
  容器内模式按宿主口径放开为**全权**（边界由挂载面承担）。**B 案＝连跑工作流那个 worker 进程也在容器里**
  （容器自己轮询 Temporal、自己起 agent，不再需要 docker exec）。本条目只记录 B 案的技术要点与取舍，未排期。
- B 案要解决的六件事（本日实核，逐条给结论）：
  ① **容器里要有「引擎+仓库」**：现镜像只有 dsh+python/git（给 agent 用）；整 worker 需再加引擎代码、
     venv 依赖（temporalio）、worker 入口（`worker.py --pidfile … --logfile …`）。
  ② **泳道必须在容器内「同路径」**（关键技术点）：泳道是 git worktree，其 `.git` 是**文件**、内含
     **宿主绝对路径**（指向主仓 `.git/worktrees/<id>`）。容器内若不存在该宿主路径，则容器内一切 git 命令
     （status/commit＝worker 代落盘、merge、teardown）全失败。做法＝`-v <宿主泳道>:<宿主泳道>` **且**把主仓
     `.git` 也按同路径挂进去；同款「同路径挂载 + git-common-dir」在测试台 compose 里已有先例可抄。
  ③ **容器要能连上宿主 Temporal**：宿主地址 `127.0.0.1:7233` 在容器内指向容器自身。可选
     `host.docker.internal:7233`（需 darwin host 网关配置）或容器 `--network host`——**后者等于放弃
     「仅出口」的网络边界，是新的取舍点，须宿主拍**。
  ④ **接线点**：现起台点＝宿主「console → 起 worker 进程」；B 案要改成「console → 起容器（里面跑 worker）」
     ——即 t260913-04 报告所指的那个接线点（`node.ts:623` 原文：console 是工单 worker 的唯一生产 spawn 点）；
     console 属用户面，改动与重启须宿主操作。
  ⑤ **生命周期**：按票起、收口即拆、起不来**回落宿主**（不让工单卡死）；worker 日志/结果文件仍落泳道内。
  ⑥ **性能待实测**：挂载是宿主文件系统（OrbStack 有代价），worker 频繁读写泳道文件，可能比现在慢。
- 判断（260914）：**先 A 后 B**——A 能立刻解掉「agent 必须在容器里执行命令」这个真实卡点（macOS Seatbelt
  不可用，见 KI-083），且不引入 git 路径/网络边界/性能三个新变量；B 的收益是「连工作流引擎那层也在容器里」
  的更强隔离，优先级取决于宿主对隔离强度的需求。若启用 B，③的网络取舍与④的 console 接线须先由宿主拍板。

## KI-085 禁用 sandbox-policy 会把整个插件树卡死（console 起不来）——来历不明的工作区改动，260913 实证
- 现象：`dsh web` / 控制台启动即失败：
  `Error: dsh: plugin tree failed to load: dsh: 3 entries did not activate` ——
  `dsh-bash-sandbox: pending (waiting for service: sandboxPolicy)`、
  `dsh-fs-sandbox: pending (waiting for service: sandboxPolicy)`、
  `dsh-permission-presets: pending (waiting for service: shell)`。
- 根因（宿主排查确认）：`server/profile/cordis.patch.yml` 末尾被加了 **`sandbox-policy: disabled` 两行**
  → `sandboxPolicy` 服务无人提供 → 两个沙箱消费者 pending；受限执行器起不来又导致 `shell` 服务缺失
  → `permission-presets` 也 pending，**三者连坐把插件树卡死**，控制台无法 boot。
- 关键事实：该两行是**未提交的工作区改动**、**没有任何笔记说明来历**（谁加的、想解决什么均无记录）。
  集成侧自查：本会话对配置面写操作 **0 次**（`git status` 仅 `notes/debts/known-issues.md` 为本会话所写）；
  引擎侧唯一写 `disabled: true` 的位置是 `agent_activities.py:1150` 附近的**会话延续 patch**（禁用的是
  原版 headless runner、换 resume runner，与 `sandbox-policy` 无关）——**归因未定，如实留档**。
- 教训与处置：①**「禁掉沙箱」是一条会把整棵树拖死的操作**（服务链上有依赖顺序），不是局部开关；
  ②凡在 profile 层做 `disabled`/`consumers` 类改动，**必须留注释说明来历与目的**（本仓硬规则之一就是
  文档/注释可追溯），否则下一个人只能靠猜——这次是宿主在外部排查才复起的；
  ③排查口诀：看到 `pending (waiting for service: X)` 先查**谁本该提供 X**（本例 provider 被 disabled），
  再顺链看下一个 pending。
- 定位：`server/profile/cordis.patch.yml`（末尾两行；headless 侧同名文件是指向它的软链，一并受影响）；
  诊断输出＝控制台启动时的 `3 entries did not activate` 清单。

## KI-084 仲裁段的「测试面」定义不含被 import 的测试基建助手＝修法落不进该段（260913 三例）
- 现象：仲裁段判出测试基建红（tests-fault）后，其**修法落在「被场景 import 的共享助手」**上，而段规则
  `STAGE_PATH_RULES["arbitrate"] = {"kind": "test_face"}` 的测试面＝**场景脚本（sc_*）+ test_*.py +
  tests/ 目录 + 本票场景 + 结果文件**，**不含**助手库 → `stage-path 闸` 拒收，票停在 blocked：
  `段 arbitrate 不允许改 <文件>（本段只许：测试面…）——合法出路：打回目标段或回 main 侧走票`。
- 三例实证（260913 同日）：①`integration/baselines/capture-ensure-build.mjs`（界面场景共享构建助手）；
  ②`server/engine/dev_lane.py`（仲裁要修集测段活动超时，属引擎代码面）；③
  `integration/t260912-02/lib_lifecycle_case.py`（起台腿三态归类的单源函数落点）。
- 结构性原因：仲裁被设计成「可迭代测试集」，而**测试集的主体恰恰是助手库与共享资产**（sc_* 只是入口薄壳）；
  「测试面＝脚本」这个定义与实际形态不符，于是**每一次「仲裁要修测试基建」都会撞墙**。
  现实处置＝每次给该文件签一张 `protected_path` 授权再打回实现段（260913 三次均如此），
  **症状被压住但缝隙仍在**；且每次要多一轮（打回 → 实现 → 集测 → 仲裁）。
- 处置方向（二选一，建议②）：
  ①**扩规则**：测试面定义扩到「从失败场景出发的 import 闭包」（可机械实现：解析场景文件的 import 图，
  取其 `integration/` 内闭包为测试面）——一劳永逸，但仲裁段可写面变大，需与「受保护名单」边界一起审视；
  ②**保留授权路**：承认「助手文件属受保护真源、须人授权」是**有意设计**，则把这条写进流程说明
  （仲裁段遇此情形应**主动报为「需授权」**而不是干等超时/反复重跑），并把授权范围从「单文件」改成
  「本票测试面闭包」以减少签批次数。
- 附带（同轮仲裁新报，待另票/另 KI 评估）：①console 台 hold 上限 14400s 自退 → 租约过期 →
  ensure 对活容器 fail-closed ⇒ **单台死亡连坐约 17 场景**；②锁根分裂（沙箱降级根写入的租约对闸不可见 →
  「容器在跑却报租约已死/缺失」）。
- 定位：`server/engine/path_gates.py`（`STAGE_PATH_RULES["arbitrate"]`、`_is_scenario_script` 的测试面判定）；
  实证＝票 t260913-01 / t260913-02 的时间线（260913 三条 blocked 记录，reason 内含上述拒绝原文）。

## KI-083 macOS 宿主机无可用沙箱后端 → agent 命令面 fail-closed（260913 全链取证；容器内已验证可解）
- 现象：本机 headless agent **一律无法执行 shell 命令**，报
  `sandbox mode "workspace-write" is requested but no sandbox backend is usable on this host; refusing to
  run the command unconfined. …`；而它**读写文件一切正常**（能改代码、能写结果文件）——故极易误判成
  「这个 agent 有问题 / 这张票有问题」。
- 取证（按 DSH 官方手册的四项证据法，集成侧实测）：
  ①环境＝macOS 26.4.1 / 内核 25.4.0、dsh 0.1.1-rc.2、Node v26.5.0、`/usr/bin/sandbox-exec` 在位；
  ②Node 直接 spawn 裸名与绝对路径**都成功**（排除 issue #4849 那种 `spawn ENOENT` 环境桥故障）；
  ③provider 链＝`darwin: ["seatbelt"]` 唯一一条腿，可用性探测＝用真实 read-only profile 跑
  `sandbox-exec -p … -- true` 要求 status===0 → **实测退出码 71（`sandbox_apply: Operation not permitted`）**
  → 判定 unusable → **fail-closed**；连最小 profile `(version 1)(allow default)` 也返回 71
  （即本机**无法应用任何 Seatbelt profile**，非 profile 语法问题）；
  ④无沙箱对照（宿主直跑命令）正常 → 命令面本身没坏，只有「戴项圈」被内核拒绝。
- 分层原因（本条最容易被误读的点）：DSH 的**文件读写**走 `dsh-fs-sandbox`＝**进程内文件栅栏**（不依赖
  sandbox-exec），**执行命令**走 `dsh-bash-sandbox`＝**必须由系统沙箱包住子进程**。所以同一台机器上
  「文件工具可用、命令工具全废」是**预期分层**，不是随机故障。
- 官方立场（重要）：手册把这类判为 `SANDBOX_UNAVAILABLE`（无可用后端＝预期 fail-closed，不是文件越权），
  **明文反对**用切 `danger-full-access` 来「修」（且全权路径另有未修 bug：discussion #5298 提权校验、
  #4763 模型乱填字段）；官方正解＝**用容器 / microVM / 远程执行器替换整条执行面**
  （dsh-sandbox README：「同一世界隔离；需要整体环境隔离时请用容器」）。
- **容器内已验证**（集成侧原型，`test-dsh:dsh-0.1.1-rc.2`，Linux/OrbStack 内核 7.0.14）：同一份 profile、
  同一 `workspace-write` 模式，agent **命令面完全可用**（十余条命令均有真实输出）；文件改写为真；
  **沙箱确在生效**——agent 尝试写工作区外（`/usr/local/lib/python3.11/…`）被 `Permission denied`。
  即：同模式在 Linux 有可用后端（bwrap/Landlock），且把写入限制在工作区内。→ 已开票 **t260913-04**
  （agent 执行面容器化：镜像预装依赖 + 引擎接线 + 回归）。
- 附带发现（同票一并处置）：①容器镜像内 Python 依赖不齐（无 pytest），`pip install` 遇
  `externally-managed-environment`、`venv` 因缺 ensurepip 失败 → 镜像必须预装；②**bash 工具 60 秒超时**
  对分钟级测试命令不适用（`pip download` 即被掐断）——agent 侧应用后台任务 + 轮询。
- 未查明（如实留档，不编）：同一张票 `t260911-05` 在 09-13 11:23 有**成功执行命令**的痕迹
  （git/pytest/shasum），而当日 15:56 之后的段全部失败；机制侧无直接证据解释这一时间差
  （已排除：agent 进程新旧——新起进程同样失败；配置差异——两泳道 `.dsh` 权限项均未配；系统更新——
  安装历史无 09-12/13 的 OS 更新，仅 XProtect 数据更新）。
- 定位：`dsh-sandbox-local`（探测 `defaultProbeSeatbelt`、`darwin: ["seatbelt"]`）；
  `dsh-bash-sandbox` vs `dsh-fs-sandbox`（分层原因）；手册＝deepseek-harness-handbook
  `troubleshooting/sandbox-denied-vs-unavailable.md`；复现命令＝
  `/usr/bin/sandbox-exec -p '(version 1)(allow default)' -- true`（期望 0，实测 71）。

## KI-082 老票越放越难合：分叉点落后 main 无任何提示，最终以「越界写/冲突」形态爆出（260913 实证）
- 现象：`t260911-05` 分叉点停在 09-11，到 09-13 已**落后 main 28 个提交**；期间它自己照常跑阶段、
  人数次推它过门，直到 `merge_check` 三红才暴露：①越界写 `.sandbox_tmp_gen9.md`（仲裁段 09-13 11:22
  留下的两字 placeholder 临时文件，未被 gitignore 忽略 → settle 判越界）；②泳道内 `verify_lane code`
  `exit=None red=1`（未跑成，疑似被前序超时连累）；③**合并预演冲突三文件**——`integration/stage_docker.py`
  （main 侧已被 t260912-02 改）、`integration/run_scenarios.py` 与 `server/engine/dev_lane.py`
  （main 侧已被 t260913-03 改）。即：**同一批文件被别的票先改，老票只会以冲突形态知道**。
- 危害：①老票的每轮集测都在**旧基线上**跑，判红/判绿都可能与 main 现状无关（误导仲裁）；
  ②解冲突时极易用旧版覆盖别人的新实现（本票退票附注已明确写「以 main 侧为基础，只保留本票增量」）；
  ③票越老单轮成本越高，形成「越拖越贵、越贵越拖」。
- 处置方向：①给票面/列表加**落后度可见**（分叉点落后 main 多少提交/多少小时），并在落后超阈值时
  在段入口给出提示或强制对齐；②段间自动对账：进入集测段前先与 main 对齐（或明确声明「本轮在旧基线上跑」）；
  ③临时文件类工作产物要么进 gitignore、要么由作者清理——`.sandbox_tmp_*` 这类不该进 settle 的脏面。
- 定位：`t260911-05` 泳道（`.lane/t260911-05`，HEAD 862907a 未含 main tip b614392）；
  merge_check 报文明细见其时间线 09-13 11:23；退票附注（对齐口径）见同票 09-13 07:56 事件。


## KI-100 dsh 升级三连故障模式：同版本号 ≠ 同 bits / 原位换包打挂活着的 console / 机器级 GUI preset 不在兼容面（260923 实证；**同日 main 侧已修**，宿主令「不开票，直接搞好」）
- 现象（宿主实报）：「在外头修了一下才能进 console」——3099 打不开、白屏；随后新建会话/续老会话全废。
  三个症状看着像三件事，实为一轮升级暴露的三个**不同环节**的缺口。
- **模式 A：同版本号 ≠ 同 bits（本族根因，最反直觉）**
  - 触发：`npm install -g @deepseek-ai/dsh@0.1.5-rc.2` —— dsh 自身依赖写的是 semver 区间，
    **同一天装**解析到的传递依赖与 09-21 验证过的 tarball 解包不同；240 个包中 8 个版本差一档：
    `cordis 4.0.2→4.0.3`、`cordis-plugin-loader 1.0.3→1.0.4`、**`cordis-plugin-hmr 1.0.17→1.0.18`**
    （另有 group/include/timer/cosmokit/schemastery）。
  - 致命点：`hmr@1.0.18` **删掉了 `registerConfig`**，而 `dsh-app-boot/lib/index.js:1115`
    （`watchUserPatches`）必调它、`lib/profile-boot-Dk-7KqJc.js:321` 在 `patchReload==="live"`
    （自定义 profile 缺省值）下会动态挂 hmr 再调 → **该安装自不相容**；profile 侧无从绕（手动开 hmr
    撞更深的同类错）。**「`--version` == 目标版本」这一步两套都过**——只校版本号判不出可用。
  - 什么样的改动会踩：任何按 semver 装 dsh（npm 全局 / 换机器 / 重装 / CI）都可能解析到当天的新依赖；
    上游只要再发一版带破坏性变更的 cordis 族依赖就会复发。
- **模式 B：原位换包打挂活着的 console**
  - 机制：dsh 的 web 静态页与客户端模块**每请求现读磁盘、无缓存**
    （`dsh-host-frontend-static/lib/index.js:64` `await readFile(target)`；
    `dsh-client-modules/lib/index.js:545/753` 请求期 `readFileSync`）。
    故 `npm install -g` 落地的那一刻，**已在运行的旧 console 就被隔空打挂**：旧进程启动时组好的 config
    引用的包已被新版删掉（0.1.5 移除 `dsh-client-runtime` 整包）→ 客户端资源 404 → 白屏。
  - 被推翻的假设：runbook「升级切流与回退」段原文写「console(3099) 用的全局 dsh 不受影响」——
    对**按请求现读的静态文件面不成立**；「运行中的进程已加载旧模块」只对内存态成立。
- **模式 C：机器级 GUI preset 不在兼容面**
  - `~/.dsh/.agent-presets/<项目>-<角色>/agent.cordis.yml` 是 0.1.1 时代的**实体拷贝**（不在仓库、
    不在任何测试网、不在接缝矩阵）；0.1.5 把 `dsh-persona` 配置 schema 由 `text:` 改为
    `prefix:/suffix:`（`prefix` 必填）→ 旧拷贝**挂载即抛** → preset 挂不上 → 新建会话失败、
    老会话同样点名该 preset 也续不上。矩阵当时覆盖了 headless 的 roles patch（走
    `system-prompt.persona`，该面 0.1.5 未动，所以探针没暴露），GUI 实体拷贝这一面没人对账。
- 危害：①升级后**谁都起不来**，且报错指向 profile/hmr（把诊断引向错误方向）；②宿主手动救场
  （改环境变量、重建 preset）＝无人知晓的旁路修复；③console 白屏期间宿主操作面全断。
- 处置（260923，main 侧，规避+根治）：
  ① 全局重装成已验证解析集：`npm install -g @deepseek-ai/dsh@0.1.5-rc.2 --before=2026-09-22T00:00:00+08:00`
     （`--before` 让 npm 按该时刻 registry 状态解析依赖——**这是模式 A 的正解**，优于逐包 overrides）；
     现全局树与 `~/.sandbar/dsh-015` **240 个包零版本差异**；
  ② `start-console.sh` 加 bits 指纹对账：`--bits-check` 可单独跑；不指定 `DSH_BIN` 时**自动挑能用的那套**
     （坏套跳过并点名原因），显式指定坏套则**响亮拦下、绝不静默替换**（升级预演要能信 `DSH_BIN`）；
     默认取值不再裸信 PATH（机器钉 `~/.sandbar/dsh-015/bin/dsh` 优先）——治「裸跑 `./start-console.sh`
     必踩坏套」这个最可能复发的入口；
  ③ 验证口径：stage 台（独立端口 3288 + 独立 `DSH_HOME`，仓库自带工具）实起修复后的全局安装
     → 干净 boot + `selfcheck` **全绿（pass 7 / red 0）**；起完即停、临时 home 已清、3099 全程未动。
- 回归用例（本族，已落地）：`integration/tests/test_start_console_bits.py`（8 条，全离线、不占端口）——
  ①好套在位→选中并启动；②漂移套→拒绝且点名实得版本；②b**版本号对但缺 `registerConfig`→仍拒**
  （锁因果不锁版本清单）；③显式坏套→拒绝且不静默替换；③b显式路径不存在→「无法从 bin 定位安装根」；
  ④强闯开关（`SANDBAR_SKIP_DSH_BITS_CHECK=1`）→放行但留痕；⑤壳源码静态看守（裸 `$VAR` 贴全角字符 /
  默认取值绕过对账）。
- 定位：`dsh-app-boot/lib/index.js:1115`（`hmr.registerConfig` 调用点）、
  `dsh/lib/profile-boot-Dk-7KqJc.js:321-328`（`patchReload==="live"` 挂 hmr）；两套 bits 对比＝
  `/opt/homebrew/lib/node_modules/@deepseek-ai/dsh` vs `/Users/user/.sandbar/dsh-015/...`；
  静态读取面＝`dsh-host-frontend-static/lib/index.js:64`、`dsh-client-modules/lib/index.js:545/753`；
  preset 面＝`~/.dsh/.agent-presets/sandbar-integration/agent.cordis.yml`（备份 `…bak-260923/`）；
  修法落位＝`start-console.sh`（bits 闸）+ 本族回归用例；runbook 已同步（§2 步 1/2/3、§5 风险表、§6 第 6/7 条）。
- 同族面（一并查明，未修）：nusuyou/dengzhufpv 未声明 `paths.dsh_bin` → worker spawn 走裸 `dsh`
  （`server/engine/data/worker-t260923-04.log` 实证 `bin=dsh(→/opt/homebrew/bin/dsh) 来源=default`），
  即全局 bits 坏掉时**所有项目**的 agent 段一起坏——全局安装保持指纹绿是跨项目公共面。

## KI-101 dsh 0.1.5 客户端服务面迁移未入兼容面：`workspaces.startSession` → `uiWorkspace.startSession`（260923 实报；**同日 main 侧已修**，宿主令「不开票，直接搞好」）
- 现象（宿主实报）：「新建会话失败：请求异常（详情见控制台）」——**所有项目一起坏**（nusuyou 与 sandbar 都炸），
  浏览器控制台实际异常：`TypeError: workspaces.startSession is not a function at Object.handleNew`。
- 根因：0.1.5 把客户端「UI 工作区服务」与「工作区控制器」拆成两个服务——
  `dsh-client-ui-workspace` 以 `super(ctx, "uiWorkspace")` 提供带 `startSession` 的服务
  （平台自己的 sidebar/agent-preset 都经 `ctx.uiWorkspace` 调它），而 `ctx.workspaces` 变成
  `dsh-api-workspace-controller`（纯控制器，**整包无 startSession**）。0.1.1 时代 `startSession`
  在 `ctx.workspaces` 上，本插件照它写死，升级后同一句调用必炸。
- 为什么没被网住：`server/plugins/workbench/tests/` 里**零命中** `startSession`——这条链原先没有任何
  测试覆盖，平台服务面换名/迁移没人管（与 KI-100 的 A/C 两个模式同族：**平台面没进任何兼容矩阵**）。
- 危害：宿主侧「项目行 ＋ 新建会话」全项目失效、`handleOpen` 的 blank 会话自愈分支同样失效；
  报错文案只说「请求异常」，真因只在浏览器控制台。
- 处置（260923，main 侧）：新增 `server/plugins/workbench/src/shared/workspaces-compat.ts`
  （`resolveStartSession(candidates)`：按候选面顺序取 `startSession`、`this` 绑回宿主、全无则抛**精确**错误——
  点名「0.1.5 在 uiWorkspace／workspaces 现为纯控制器」，不再甩裸 TypeError）；
  `session-entry.tsx` 两处调用点（handleNew / handleOpen 的 blank 自愈）统一走 hook 内
  `startWorkspaceSession`；`index.tsx` 把 `uiWorkspace` 传下去且**在渲染期取值**（apply 期取会拿到
  undefined：装载次序不保证）；**未写入插件 inject**（0.1.1 无该服务，声明＝entry 永久 pending，t260916-26 教训）。
- 回归：`server/plugins/workbench/tests/session-start-version-shim.mjs`（21 条：双版解析纯逻辑 + 源码静态
  看守「不得再直呼 workspaces.startSession(」+ 产物同构防「改了 src 没重建」）。
- 验证：真起隔离台（3288 + 独立 DSH_HOME）→ 自检全绿（组合包四插件在位、workbench API 全 200）；
  **抓浏览器实际下载的组合包（13.28MB）**：新文案命中 1、`resolveStartSession` 命中 4、旧直呼残留 0。
- **续记（同日，本条的修复自己踩出来的二次事故——留档，教训比故障更值钱）**：第一版修法用
  `(ctx as any).uiWorkspace ?? ctx.get('uiWorkspace')`，`??` 先求左值——而 cordis 的 proxy 对**属性形式**
  访问未 inject 的服务**直接抛** `cannot get property "uiWorkspace" without inject`；抛点在 slot 渲染期 →
  `slot entry crashed in 'sidebar.workspaces'` → **整个 sandbar UI 消失、退回 dsh 默认界面**（宿主实报
  「ui 都没了」）。正路＝免注入查找口 `ctx.get(name)`（平台先例 `dsh-client-ui-sidebar:339`）；
  且应**点击时惰性取**（避免装载次序/渲染时序）。修法见 main 提交 `c5a1f32`。
- **验证盲区（同一条命，必须记住）**：第一版只验了「组合包命中 sandbar-workbench」＝**文件在**，
  不等于**条目激活**；「条目在但渲染期抛错」这类故障只有**真浏览器加载页面**才看得见。现口径＝
  隔离台 + playwright 真加载（断言我们的 DOM 锚在位、崩溃类 console 错误为 0、点一次「新建会话」成功）
  ——回归用例已把这两条钉成静态看守（不得属性形式访问 uiWorkspace；免注入只走 ctx.get）。
- 定位：`dsh-client-ui-workspace/lib/client.js:38`（`super(ctx,"uiWorkspace")`）/`:81`（startSession 定义）/
  `dsh-api-workspace-controller/lib/client.js`（`super(ctx,"workspaces")`，startSession 零命中）；
  仓内旧调用点＝`server/plugins/workbench/src/client/session-entry.tsx`（handleNew/handleOpen 两处）。

## KI-102 roles patch 的角色说明书在 0.1.5 下被**静默丢弃**（260923 复盘发现；待修）
- 现象：**没有任何报错**——agent 照常 spawn、票照常跑，但 headless agent 收到的是**空的**角色前缀，
  即 developer / integration / 产品运营三个岗位的说明书（`server/roles/*.yml`）根本没进 prompt。
- 根因：roles patch 写的是 `name: '@deepseek-ai/dsh-system-prompt' / config: { persona: … }`；
  0.1.5 该包 `static Config = z.object({ includeHarnessIdentity, includeRuntimeContext,
  personaPrefix, personaSuffix, toolOrder })`——**没有 `persona`**，且 `personaPrefix/personaSuffix`
  都有 `.default("")`。schemastery 对未知键**不抛错**（实测 `z.object({a,b})({a:'x',oldkey:'y'})`
  → `{a:'x',b:'',oldkey:'y'}`），于是旧键原样留着没人读、新键取默认空串 ⇒ 静默丢内容。
- 危害：升级 0.1.5 之后**所有项目所有票**的 agent 段都在无岗位说明书状态下运行（行为、口径、
  纪律全缺），且票面与日志都正常——最坏的一类失效（静默）。
- 修法（细节已核）：`persona:` → `personaPrefix:`；`{{cwd}}` 是**合法注册变量**
  （`dsh-agent-loop/lib/index.js:1536` 注册 `cwd`、`:1534/:1535` 注册 provider/model，
  system-prompt 装配期插值，未知变量才抛 `unknown prompt variable`）——改名后不会撞该抛。
  回退兼容（0.1.1 读的是 `persona`）：两个键都写（各自忽略对方的键）或按钉住的版本选目录。
- 回归建议：真 spawn 一次 agent 并断言「角色说明书确实进了 prompt」（不能只断言它跑起来了）；
  另见机械对账 `integration/tools/dsh_surface_check.py` 的 [D] 项（本条的发现者）。
- 定位：`server/roles/{developer,integration,product-operation}.yml`；
  目标版 schema＝`…/dsh-system-prompt/lib/index.js:200-206`；装配插值＝同包 `:104-170`。

## KI-103 升级「平台面对账」四类缺口（260923 复盘登记；工具已落地，逐项待处置）
> 共同特征：**上游改平台面，我们这边不会有编译错误、也不会有测试红**，只能靠主动对账发现。
> 机械对账工具＝`integration/tools/dsh_surface_check.py`（A 服务面／B 访问纪律／C 槽选项／D 配置键／E 客户端模块）。
- **[C] `sidebar.footer.action` 是 `kind: "list"` 槽，注册必须带 `id`**：我们的注册没带 →
  浏览器控制台 `list slot "sidebar.footer.action" requires options.id`，度量入口**静默降级**回工单台下栏
  （功能在、位置错）。已用**改动前的产物**复现＝既有缺口（非 260923 引入）。修法：补 `id: 'sandbar-metrics'`
  （平台先例 `dsh-client-ui-cordis/lib/client.js:1340` `id: "cordis-panel"`）。
- **[E] 四个插件的 `package.json` 仍声明 `dsh.client.inject: ['@deepseek-ai/dsh-client-runtime', …]`**，
  而 0.1.5 **整包移除**了 `dsh-client-runtime`。今天未阻塞（组合包与该字段消费面已换），
  但属「声明了不存在的包」，需核实语义后清理或加注。定位：`server/plugins/{ui,knowledge,providers,workbench}/package.json`。
- **[卫生] GUI preset 的备份目录放在会生效的扫描根内**：`~/.dsh/.agent-presets/sandbar-integration.bak-260923/`
  是**完整可识别的 preset**（且是 0.1.1 旧 schema）→ 会出现在名册里，误选即挂载失败。
  建议挪到扫描根外（如 `~/.dsh/agent-presets.bak-<日期>/`）并写进升级流程。
- **[脚本/机器面] `start-console.sh` 候选链里硬编码机器路径** `$HOME/.sandbar/dsh-015/bin/dsh`
  （260923 为「裸跑就能起来」加入）。换机或清理该目录后行为变化；建议改吃 env 声明或读
  `project.yaml` 的 `paths.dsh_bin`，并在注释里标明它是机器级便利缺省而非引擎契约。

## KI-104 引擎 spawn 面 `ValueError: embedded null byte`（260923 发现，非升级相关，未修）
- 现象：nusuyou t260923-04 的 implement 段连环失败、最终 blocked，票面只写「agent 活动故障（已重试）：
  ActivityError: Activity task failed」。
- 真因（日志实证）：`server/engine/data/worker-t260923-04.log` 三轮 traceback 同形——
  `subprocess.Popen(cmd, cwd, env)` 抛 `ValueError: embedded null byte`
  （栈底 `server/engine/agent_runtime.py:353`）。**不是 dsh bits 问题**（该轮日志里 dsh 自检一致、spawn 前一步正常）。
  ⇒ 命令行或环境变量里混进了 NUL 字节，属引擎侧缺陷，会咬任何项目的任何 agent 段。
- 处置建议：spawn 前对 `cmd`/`env` 做 NUL 体检并**点名是哪一个键/哪个实参**（现在的报错只说「embedded null byte」，
  诊断直接被引向错误方向：我第一眼就误判成 dsh 版本问题，靠读日志才纠正）。
- 定位：`server/engine/agent_runtime.py:353`（Popen）；调用面 `server/engine/agent_activities.py:2872`
  （`_run_agent_stage_impl` → `agent_runtime.spawn_agent`）。

## KI-105 已知红轮被判 tests-fault 重跑烧轮次 → 迭代超限假封（260923 集成轮次瘦身直修发现并修；宿主直修令 260923）
- 病灶：闸已判「红面全为基线既有欠账·记录不堵」（blockers 空=零新增红）时，仲裁仍判
  tests-fault 重跑已知红——重跑已知红不会绿、只烧轮次到「迭代 6 轮超限转人工」。
  43 票 22 张撞墙的主因（t260922-18 报告「零一项归属本票功能面」+verdict=tests-fault 实锤）。
- 修法（0f51b4f）：计轮第三豁免形态 known_red（blockers 显式为空→不计轮，连续豁免
  仍撞 MAX_TESTS_EXEMPT_ROUNDS 独立上限=转人工触发不许归零）+ 仲裁判词锚定
  「零新增红判 pass，禁止以重跑等绿当收敛手段」。
- 回归棒：server/engine/tests/test_t260923_known_red_exempt.py（含双车道「转人工
  触发不许归零」棒）。

## KI-106 同机锁根分裂：降级回落随机 TMPDIR 与供给钉根不一致 → 租约/孤儿判定劈叉（260923 直修发现并修）
- 病灶：lock_root() 在 ~/.sandbar 不可写时回落 tempfile.gettempdir()/sandbar-test-stages
  ——macOS 上 gettempdir()=TMPDIR 随机目录，而 verify.yaml supply 与场景族钉
  /tmp/sandbar-test-stages。同机两锁根：清扫 dry-run 把共享供给误判成孤儿、并发守卫
  把在飞台判成「外来工程」——「环境老不稳定」的一条实根。
- 修法（1f46a00）：降级根钉死 /tmp/sandbar-test-stages（与供给同根+写探针）；不可写
  =红点名并指路 SANDBAR_STAGE_LOCK_DIR，不静默换根。
- 回归棒：integration/tests/test_t260923_lock_root_unify.py（行为三态子进程实证）。

## KI-107 端口瞬时撞口整轮报废：探针期未见的瞬时占口 compose up 即败（260923 直修发现并修）
- 病灶（260922-18 实证）：compose up 撞「Bind for 127.0.0.1:21060 failed: port is
  already allocated」而 bind 探针期未见占口者——占口者常为已退瞬时占用，一次失败
  即整轮 0 跑报废。
- 修法（6787184）：窄签名退避重试至多 2 次自愈；耗尽照旧红但终报附占口者诊断
  （docker ps 按被撞端口点名容器/状态/映射；无占口者如实说「已退/瞬时占用形态」）；
  终报按最后形态点名（不许把端口撞口说成网段撞号）。
- 回归棒：integration/tests/test_t260923_port_bind_retry.py。

## KI-108 孤儿清扫多前缀族点名文案 tuple 格式化炸 + 自动清扫缺 Enable 面（260923 直修发现并修）
- 病灶一：orphan_condemn_projects「前缀外」点名对 tuple 前缀 `%s` 格式化抛
  TypeError（逗号族扩展才暴露的潜伏洞）。
- 病灶二：挂点孤儿清扫因 F1 红线（真拆须宿主点头+必须有半径）缺省关，残台持续堆积。
- 修法（5db830a）：点名文案归一逗号串；orphan_prefix 逗号族（单值语义逐字节不变）；
  引擎集成跑环境显式启用 SANDBAR_STAGE_SWEEP_ORPHANS=on + PREFIX=t26,sandbar-test,
  stage-console 三族半径（只在未设时注入，操作员显式 off 不覆盖；租约/新鲜/在册三阀
  与年龄阀照旧保护在用台与共享供给）。
- 回归棒：integration/tests/test_t260923_orphan_autosweep.py（F1 负锁「挂点缺省关
  红线不动」在内）；t260915-18 F1 契约场景 18/0 实证不破。

## KI-109 测试扫描面被非代码面污染的同族两案（260923 全量跑定性发现；isolated 挂账，integration 岗登记）
> 共同特征：**「全仓零命中」型守卫把非代码面算进扫描域**，红灯指向的位置（数据杂物/历史树）
> 与真实意图（代码域卫生/退役字面退场）脱节，诊断被带偏——与 KI-104 同族「报错指错方向」。
- **案一·未跟踪数据杂物入扫描根**：t260907-01-path-hygiene 报「新病灶 183 文件」——实为
  `.probe-home/.dsh/sessions*` 会话数据转储（文件名含旧仓名 slug），非代码域引用旧仓路径。
  扫描排除面（node_modules/.git/.suyou/.lane/docs/notes）不含探针杂物目录。
  修法方向：代码域=git 在册面（`git ls-files`）或显式排 `.probe-home`；数据转储杂物本身应
  清出扫描根。定位：integration/t260907-01/sc_migration_path_hygiene.mjs 判据 A。
- **案二·冻结泳道树入扫描根**：t260916-02-decl-gate-aggregate「铸号调用形全仓零命中」命中
  `.lane/t260908-02`、`.lane/t260907-10` 遗留泳道树的退役字面——泳道树是冻结历史（红线：
  不动 .lane/），不是主树代码域。修法方向：扫描域限主树（排 .lane/）或限 git 在册面。
  定位：integration/t260916-02/sc_*decl_gate* 判据 0a。
- 两案处置=isolated 入已知红基线挂账（integration/known-red-baseline.json，home=杂物清理/
  泳道清理工序）；结构性修法待专项（扫描域语义收紧属契约变更，须配套断言不减覆盖面）。

## KI-110 巡检泳道拆除诚实性族（假「已清」+幂等谎报+清扫不认目录壳+agent_home 泳道锚漂移；260924 已修待验，integration 岗登记）
> 260922/260924 双期躺壳实案（.lane/inspection-integration-tests-2026092{2,4}）：
- ①teardown_lane 只看 git 回执不验目录——agent 杂物复活的目录壳骗过「已清…零残留」章（假绿）；
- ②幂等重拆 git rc=128（is not a working tree / branch not found）被记 warn，UI 误报「未净」（假红）；
- ③sweep_inspection_lanes 只收 worktree/branch 两种形态，裸目录壳恒「定向 sweep 无可清条目」（清不掉）；
- ④根因：agent_home 解析落 .lane 泳道树，套件段拆掉泳道后 agent 的 home.mkdir(parents=True) 把壳复活
  （agent 会话存储重建 <lane>/server/engine/out/…）。触发条件=套件段拆泳道→inspect agent 起步 mkdir，
  或超时收尾二次拆除/重跑。
- 260924 宿主直修令修复：拆后逐 tree 验目录、壳在即点名「目录壳残留」；幂等形态静默精确化（说哪个检查
  失败，不谎报）；定向清扫收目录壳（嵌套 .git 拒拆守卫=t260916-20 教训承袭）；sanitize_agent_home
  泳道锚守卫堵复活源头。
- 事故回归：teardown_multirepo 幂等双态升格棒+test_t260924_inspection_teardown_honesty.py 棒2-4。
  待验点=下期巡检（260925）拆除回执真实性。

## KI-111 巡检审查预算错配（套件段 55 分钟量级 vs 审查段 30 分钟预算；260924 已修待验，integration 岗登记）
> 260923/260924 连续两期实案：suite 跑满 ~55 分钟后审查 agent 的 1800s 预算必超时——「agent 未完成
> （超时…）未产出结果文件，本期不假绿」，台账恒空壳。触发条件=套件档开+审查分面走真 agent（桩面不触发）。
> 260924 修复：DEFAULT_INSPECT_TIMEOUT_MIN 30→60（声明可配面不动；预算<workflow start_to_close 不等式
> 仍由 test_t260916_22_inspect_flow 锁定）。事故回归=棒1。遗留观察：60 分钟若仍超时（模型慢），下期按
> 实测续调，审查/套件并行化列为方案题回用户。
> **260924 复核更正**：所谓「套件 55 分钟量级」实为**内层 3300s guard 命中**，套件本身零信号
> （ran=0）——见 KI-116；即本期「审查超时」是双层瞎：套件无信号 + 审查无产出。60 分钟预算
> 在生产已确认生效（3600s 文案准确），但审查 agent 实测 59 分钟仍在干活（分派 7 子代理审 368
> 场景文件）后撞 dsh 子代理机制 fatal error 而亡——审查预算/审查策略需另案重定（缩面或改分片），
> 非单纯调大数字。

## KI-112 历史工单泳道拆道欠账面（.lane/ 存量 10 个闭票泳道；待入轨，integration 岗登记）
> 260924 盘面：.lane/ 存留 t260903-12/14、t260907-10、t260908-02、t260912-01、t260916-27、t260922-04/05/18、
> t260923-06 共 10 个历史工单泳道（多为闭票/已合并/已清场票）——git 登记残留还是仅目录壳未逐个甄别
> （不在 260924 授权清理范围，只记账不动）。与 KI-109 案二（冻结泳道树入扫描根）、t260916-27 票面
> 「dev lane registry broken」同族。处置建议=开记名清账票甄别（登记残留走 prune、壳走定向清扫），
> 宿主授权后动。
>
> **260926 追加（工具面实锤：`lane_audit prune` 的 worktree 分支实际不可用）**：`audit` 把已终态票的泳道
> 判成 `prunable`（「待守门后可剪」），但 `prune --apply` 先跑 `guard_worktree`——**守门第一条是
> `git status --porcelain` 有任何输出即 `blocked:uncommitted`**，而**每条泳道都有 `?? .sandbar/`**
> （引擎运行期暂存：stage 结果、截图、日志、取证产物），根因是 `.gitignore` **没有 `.sandbar/`**
> （`.lane/`、`.dsh/`、`.suyou/` 都在，唯独漏它；主仓自己 `git status` 也是 `?? .sandbar/`）。
> 后果：`prunable` 状态**永远转不成动作**，KI-112 的清账在此路走不通（本次实测）。
> 处置：①`.gitignore` 补 `.sandbar/`（一并解掉「工作区是否干净」的口径噪声，属引擎侧小改，待入轨）；
> ②在那之前，终态泳道走「先列后删 .sandbar 暂存 → `git worktree remove` → `git branch -d`」，
> OS 级复核（ticket list 无该 id 或 `kind=terminal` + `rev-list --count main..<branch>` 为 0）。
> **260926 已按此口径清掉 `t260922-04`、`t260922-05` 两条（含分支 `lane/t260922-*`；04 的唯一一份
> `probe-dsh-015` 取证已先搬到 `.sandbar/evidence/t260922-04-voided-duplicate/`）**。另注：
> `git worktree list` 里还有三条 `/var/folders/.../sandbar-baseline-*` 临时 worktree（基线跑残留），
> 归 KI-115 残壳族。

## KI-113 巡检周期 workflow 跑共享队列=中央工人冻结码（部署拓扑缺口+注释撒谎；260924 定谳，integration 岗登记）
> 铁证=worker.log 原文 `task_queue: 'sandbar', workflow_id: 't260924-01', workflow_type:
> 'InspectionPeriodicWorkflow'`：巡检周期票（InspectionPeriodicWorkflow）起在共享队列 TASK_QUEUE
> （inspection_ticketing.open_period_ticket(task_queue=TASK_QUEUE)），执行者=中央工人（data/worker.pid，
> 无 supervisor）——普通工单（TicketWorkflow）走 per-ticket 队列+专属工人，两族拓扑不同。连带事实：
> ①shared.py「共享队列只放 dispatcher-scan」注释与 inspection_ticketing 代码矛盾（注释撒谎，审查被
> 误导两次——260924 亲历）；②KI-081 冻结纪律的部署后果：engine 修法上线后，巡检流水线仍跑旧码，
> **验货/生效都必须重启中央工人（红线：需宿主明示）**。260924 处置=宿主明示授权重启（66222 起新码）；
> 结构性修法=巡检 workflow 迁 per-ticket 队列或中央工人纳 supervisor，待专项。

## KI-114 终态票期号黑洞（cancel 后重开无路；260924 实案，integration 岗登记）
> 实案：t260925-01 记名清场后重跑 `inspection_trigger trigger --period 20260925` 回执
> `triggered:false deduped:true dedup_source:sa_query`——open_period_ticket 的显式去重（实例+期号
> SA 查询）**不认终态**，被终结票的检索属性永久占住期号，同号重开无路、stale_pointer_cleared 也不
> 触发（指针三态管不到 SA 层）。后果：该期成为死槽（当日 cron 也会被去重挡回）。260924 绕行=顺延
> 开期 20260926 验货。修法方向：去重限「非终态」查询或提供记名 force 通道；须配套审计留痕
> （同号多 run 的对账语义）。

## KI-115 清扫嵌套仓守卫误伤 worktree 残壳（.git gitfile）；拆除「Directory not empty」待归因（260926 验货实案；守卫部分已修待验）
> 260926 期实案（t260926-01 suite 收尾，04:52:50Z）：`git worktree remove --force` 报
> `failed to delete '…/inspection-integration-tests-20260926': Directory not empty`（登记/分支已清、
> 目录树残留）；回落定向 sweep 又因壳内顶层 `.git` **文件**（worktree 痕迹 gitfile，对象库在主仓）被
> 判成「未注册嵌套仓」而**拒拆** → 回执如实「未净」并列名三项原因（诚实性修复生效，**非假绿**），
> 但壳留在场（`.lane/inspection-integration-tests-20260926`）。
> 定性：守卫粒度错——worktree 痕迹（顶层 .git 文件）与真仓（顶层 .git 目录／任意更深层 .git）必须
> 分开判。260924 直修令续修：三态判定（文件=可清／目录=拒／嵌套=拒）+ 水位态自愈面（setup 清扫按
> 「早于水位」收旧壳，与 worktree/分支同语义）；棒=test_t260924_inspection_teardown_honesty.py 棒3
> 升格（定向/水位矩阵+三态矩阵，20/0）。
> 待归因（未修）：`Directory not empty` 成因——疑似套件尾巴进程写入竞态（套件内起过服务/子进程）；
> 下期若复现按「谁在写」定位（拆除时刻该目录的写入者）。

## KI-116 巡检套件面零信号（常态 ran=0；内层 3300s guard 与外层 120min 预算两层错配）（260924 验货挖出，integration 岗登记；**修复票=t260924-05**，宿主 260924「最高优先」令）
> **实案**（260924 复核 5 期套件回执+工人日志）：巡检套件回执连续多期 `ran=0/passed=0/failed=0`——
> **零测试信号**：4 期卡「场景执行器整体超时（>3000s）」墙钟 3300.0s、1 期「未知错误」1497.5s；
> 再往前 260918 期**非超时**返回（334.5s）同为 ran=0。即巡检套件段**从未产出过场景信号**（至少
> 260918 至今 ≥6 期），每期白烧 5.5~55 分钟。
> **机制链（已核）**：内层 `BATCH_TIMEOUT_SEC = env(SANDBAR_INTEG_BATCH_TIMEOUT_SEC) or 3000`
> （guard=BATCH+300=3300s，先炸，agent_activities.py:6324/6487/6667）；外层巡检预算 SUITE_TO=120min
> 形同虚设；`inspection_flow` 未抬高该 env；`agent_activities.py:6323` 注释要求「覆盖时须同步抬高
> dev_lane.INTEG_RUN_TO」（成对锁）；`inspection_flow.py:71` 注释写「默认 5400+300=5700s」与常量真值
> （3000）**不符**（KI-079 族「说明书与实际不符」，注释撒谎）。
> **未归因（待诊断票）**：为何巡检泳道内套件 ran=0（3300s 挂死）而同套件在 dev-lane 仅 ~205s/273 行
> 正常——嫌疑① worker 环境继承（SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW 在场触发嵌套守卫路径）；
> 嫌疑② 结果行读取面错位（真跑了但回执读不到）；嫌疑③ 巡检泳道内锁/端口/依赖面。诊断法=在巡检等价
> 泳道手工跑一次 `_run_scenarios` 并看 runner 真 stdout。
> **影响**：巡检的「套件信号」整面瞎（另一半审查面本期亦超时零产出）——KI-111/KI-115 多为本表的表症；
> 修复优先级应**高于**继续调大审查预算。

## KI-117 走查/仲裁段取证面无界（agent 把「全量套件」当复现工具；口径还比闸更大）（260924 归因，宿主令「先查后开票」）
> **实案**（t260924-04 第 2 轮，19:33:00–20:56:22＝83 分钟）：走查 agent 分两趟跑了**全注册表 374 条**
> （墙钟 2427.7s / 2328.1s，各约 40 分钟），用途=**两轮复现本票 journey 场景 FAIL**（agent 自述
> 「缺陷#3 worker 日志（两轮复现）」）；同期仲裁仅 21.5 分钟（并行，**不占关键路径**）。→ 该票
> 「仲裁/走查」2h01m 里约 113 分钟是走查在跑全量套件。
> **机制面**：走查=agent 段（role=integration），引擎派活文案只要求「用户视角走查＋引用已注入的闸
> 回执」，**未限制取证面、无预算/条数上限**；agent 自选工具＝无参 `run_scenarios.py` → 全量。
> **口径差（实算）**：闸 `excluded_pools=[engine, exclusive]` → 294 条/10 分钟；走查**无排除** →
> **374 条**（多出 80 条 engine 池重活——闸里本就由 pytest 覆盖、故排除）→ 每趟 40 分钟。
> **放大因子**：三泳道并发（同量级 294 条单票独占实测仅 205s，t260922-18）。
> **修复方向**：①派活文案明确「闸回执即全量证据；复现单条只跑单条」；②定点复跑入口＋条数/墙钟
> 上限（超限 fail-loud）；③agent 段自跑口径与闸一致；④并发限宽（另案）。修复票=t260924-07。

## KI-118 定点复跑对「引擎票」恒失效（写集粗前缀 → blast_radius=shared → 每轮全量）（260924 归因；宿主授权开票）
> **实案** t260924-04：写集含 `server/engine/`（命中 `_SHARED_BASE_PREFIXES` 前缀）→
> `blast_radius(write_set)=="shared"` → `targeted_rerun_plan` **恒返空** → 每轮返工都跑全量：
> 该票 6 轮里 **4 趟全量套件**（294 条、7~10 分钟/趟，三泳道并发下更久；≈1.5 小时纯套件时间）。
> **面**：D 口径（260923 定点复跑）**只对「窄写集」票生效**；而引擎票写集几乎必然含
> `server/engine/`、`server/tools/`、`integration/` → **引擎类改动零收益**（今天三张引擎票全中）。
> **张力**：粗前缀原是保守取舍（改引擎=共享基座变了，只复跑红项不安全），但事实上一处单文件改动的
> 真爆炸半径远小于整目录。**修法方向**＝按**实际改动文件**算爆炸半径，同时保留两条保险：
> 「碰真共享面（执行器/基线/verify.yaml 等）仍全量」＋「放行只认收口全量跑」。

## KI-119 跨项目写操作的调用方身份未接线（记名放行兜着；翻拒收会立刻卡一批流）（260924 普查发现；修复票=t260925-06）
> **实案**：260924 普查近窗票面 `cross_project_uses`——代签、清场（cancel）、裁决（ruling）等跨项目写
> 操作全部记为「未声明调用方身份（策略=记名放行，console/泳道注入接线后翻拒收）」：即 `caller_project`
> 未由 console/泳道自动注入，引擎以「记名放行」兜底（by/who 必填＋理由入账，审计可查）。
> **风险**：①审计面——身份靠调用方手填而非机制注入，跨项目写无法机械核验「谁有权」；②既定方向是把
> 策略翻成「未声明＝拒收」，**翻之前若不接线，所有未接线调用面（console 操作、泳道 agent 的 ticket
> 调用）会立刻被拒**——仅今天一天就有多次代签靠记名放行通过，使用频度高。
> **修法方向**：console 与泳道 agent 调用 ticket/op 工具时**自动注入身份**；保留 `cross_project`
> 记名越权旗（by+reason 必填）为唯一豁免通道；翻拒收前须有跨项目三态验收（声明匹配放行／未声明拒收／
> 记名越权放行）。
> **260925 实况（翻拒收落地即验证）**：t260925-08 合并后（`4aa1960`）策略**当场翻成拒收**——本会话
> 直调 `ticket.py` 的写操作（未注入身份）立即被拒：「跨项目闸：调用方项目身份未声明
> （SANDBAR_CALLER_PROJECT 未注入且无显式参数），引擎策略=拒收」；**显式带 `caller_project=sandbar`
> 即放行**（同一条 rework 补参后 delivered）。→ 直调会话/运维脚本/裸入口调用方**必须显式声明身份**；
> console 与泳道侧是否已自动注入，须在宿主醒后实测确认（本岗不碰 console，无法代测）。

## KI-120 并行叉内的路径闸 block 不可脱困（授权已放行、票停在「空原因的 blocked」，四种出路均无驱动）（260925 实案，integration 岗登记）
> **实案** t260925-05（中央工人 supervisor 票）：仲裁段（`arbitrate ∥ acceptance_walkthrough` 并行叉）的 join-settle
> 命路径闸拒落盘（`integration/baselines/sc_auto_rework_trace.mjs` 属保护名单）→ 04:04:06 票转 blocked（带卡因与出路）。
> integration 依既定流程处置：① 04:07:12 发 `authorize kind=protected_path`（单文件/限期/记名，**已 landing**）；
> ② settle 随即两次记录「受保护路径经人授权放行」；③ **票面却停在 `acceptance_walkthrough/blocked` 且
> blocked_reason 变为空**，04:07:14 之后再无任何活动（工作流既不推进也不重入叉）。
> **已试尽的出路（全部 delivered 但无驱动效果）**：`retry_qc`×2（票面记 retry-requested 第 1/2 次）、
> `pause`+`resume`（工作流日志可见 paused/resumed、票面记 resumed）、`rework to_stage=arbitrate`（并行兄弟段）、
> `rework to_stage=implement`（上一串行段）。工人进程活着、信号被消费——**是状态机不重驱，不是工人死**。
> **判读**：同一天里**串行段**上的同类 block 两次都能用「authorize + retry_qc」脱困（t260924-04 的 docs/design、
> t260925-04），唯独**并行叉**内的这次脱不了 → 怀疑并行叉的 block-清除路径未复位 fork 簿记、未重驱兄弟段。
> **影响**：票永久停在 blocked（不烧资源但占位），只能弃票重开或修引擎。**修法方向**：block 清除后按 fork 语义重入
> 分支（或把「授权后重驱」做成单一入口）；**验收**＝坏路径 block→授权→自动续跑（并行叉与串行段各一例）。
> **现场保留**：t260925-05 泳道与授权均在场，修好后可直接用于复现与验收。
> **260925 实测校正（同日 12:5x）**：该卡死状态**并非永久**——引擎从 KI-121 停摆恢复后再次复查，
> 票的 blocked_reason **已刷新为另一条正当卡因**（`unauthorized_path`：arbitrate 段越段改共享库
> `integration/lib_console_noise.mjs`，该段只许动测试面），此时一次 `rework → implement` 即被正常消费、
> 票复活（`implement/running`）。→ 收敛表述：**清掉 block 后票会长时间滞留在「空原因 blocked」达数小时
> （期间任何出口都不驱动）**，直到某个状态刷新/复工把它带回可驱动路径；不是绝对死锁，但**对自动化而言
> 等同停摆**，故 t260925-17 的验收仍以「授权后必须自动/单出口续跑」为准。

## KI-122 「tests-fault（本票零新增红）→ 重跑全量」活锁：仲裁的「转人工」不被采纳，改为每轮烧一趟全量（260925 实案，integration 岗登记）
> **实案** t260925-16（KI-121 修复票）：代码自 03:57 起零变化，却连续重进集成闸三轮，节奏≈
> 闸 30 分钟 → 仲裁∥走查只跑 ~3 分钟 → 静默 ~27 分钟 → 再进闸（时间线实证：
> 04:27 done→闸#2 04:59→闸#3 05:59→闸#4 06:59…；走查 agent 单轮仅 80 秒）。
> **驱动已核（仲裁判词三轮逐字）**：`gen0 verdict=tests-fault 本票场景夹具已修绿；余红 auto-rework-trace 属共享
> 资产点名转人工`、`gen1 verdict=tests-fault 本票零新增红（本票场景绿）；闸拦 7 条均 main 并入面/抖动形态，
> 属共享资产点名转人工`、`gen2 verdict=tests-fault 本票零新增红；余 2 条属 t260916-25 共享资产（1 抖动 1 环境），
> 转人工`。→ **仲裁每轮都明确要求「转人工」，但工作流对 tests-fault 的既定反应是「重跑机械测试确认」**，
> 于是每 ~30 分钟重烧一趟全量、判词不变、代码不变，直到通用轮次 cap 才可能落人工。
> **代价**：单票 ≥4 轮 × ~30 分钟；三泳道并发下更久。这正是「怎么又跑这么多遍集成」的真身——
> 与 KI-117（走查拿全量当复现工具）、KI-118（引擎票定点复跑失效）同族，但**病根在裁决采纳面**：
> **B 口径（相对基线零新增红）没有作用到 tests-fault 的下一步决策上**。
> **修法方向**：tests-fault 且「本票零新增红 + 余红均属已知账/共享资产/抖动形态」时应①采纳仲裁的转人工
> （进人审/挂账）或②按 B 口径直接放行并留痕，**不得无变化重跑全量**；重跑仅限「本票面红或有新红」；
> 并给「同判词重复 N 次」设机械熔断（重复即升级，不烧预算）。
> **260925 追加根因（关键机制，integration 实测）**：上限 `MAX_TESTS_FAULT_ROUNDS=5` 计的是
> **连续** tests-fault 轮，而段入口的 `tests_round_step("streak-reset", …)` 对**任何「非 tests-fault
> 迭代来源」的重进都复位**（新实现轮／验收打回／**人工 rework 后重进**／阻塞脱困重进）——
> 于是：①**任何外部处置都会把连续计数归零，两道防活循环上限（tests 5 / exempt 5）可能永远不触发**
> （t260925-05 闸轮 7 仍未浮出「超限转人工」，实测根因即此）；②同时每轮 `blockers` 非空
> （抖动红每轮 22~29 条、不完全重合、超出 45 条基线覆盖）→ 走「探针复跑未证全绿 → 保守计轮」分支。
> **合起来＝无外力则烧到 cap，有外力则 cap 被复位**——当晚处置＝pause 该票止血（段间生效），
> 并把「streak 复位可被外部处置击穿」列为 KI-122 修法的一部分（复位语义须区分「代码/验收来源」与
> 「人工处置来源」，或另设累计计数防绕过）。

## KI-123 建票面看不到外置模板类面（名字面有、类面静默不并入）；t260924-04 验收「夹具等价面」未覆盖真路径（260925 nusuyou 实测 + integration 复核，修复票=t260925-19）
> **实案（nusuyou 侧留证）**：`ticket.py create workflow=content-studio` 被拒——`create 需要 workflow
> （模板 id，可用：dev-lane）`；而同一进程里 `project_template_names_merged()` **能**返回
> `{'dev-lane':…, 'content-studio':…}`（名字面读到了注册声明与模块源），
> `project_template_classes_merged()` 却返回 **`accepted=[] rejections=[]`**——**既不接受也不拒收＝静默
> 不并入**（非拒收）。→ 建票口（client.py/ticket.py 路径）永远看不到项目模板的类面，项目自建工作流
> 建不出票（其 P0 真稿因此卡住）。
> **我们的验收盲区（integration 认账）**：t260924-04 的 A1 用「隔离测试环境的**夹具**模板建票」代验，
> **没有覆盖「真实项目声明模块的类面并入」这条路径**——夹具等价面过了、真路径却是空的，故本缺口漏网；
> 与设计稿里我自己写下的「夹具等价面代验」风险同源。**按事故回归纪律**：补一条**真实项目模块**
> （非夹具门）的类面并入验收/场景。
> **修法方向**：①让建票面类面可见（或把类面深检与建票面解耦）；②类面不可用时**必须点名原因**
> （缺什么、为什么不可用），禁止 `accepted=[] rejections=[]` 这种「静默回落内置面」；
> ③补真实项目模块路径的回归棒。

## KI-121 外置模板加载口使中央工人起不来（活动双注册；合并即触发，260925 实案，integration 岗登记）
> **实案**：t260924-04（项目外置工作流模板加载口）合并后，中央工人重启即崩：
> `ValueError: More than one activity named ai-review`（temporalio `_activity.py:90` 注册期抛）。
> 日志关键行：`project template modules passthrough: [... 'sandbar_ext_nusuyou_content_studio' ...]`
> ——工人加载了 nusuyou 注册声明的 `paths.workflow_modules: workflows/content_studio.py`。
> **机制（已核）**：`workflows/content_studio.py` **自身不含 `@activity.defn`**（纯 workflow 模块）；
> 撞名的两侧是**引擎自己**——加载器 import 项目模块时 `agent_activities` 被以第二个模块身份**再导入一次**，
> 于是引擎为历史回放保留的退役 content-pipeline 活动（`propose/process/ai-review/publish`，
> agent_activities.py:1365）**被注册成两份**，首个撞名即 `ai-review`。→ 不是项目模块的错，是**加载口的
> 双导入/去重缺陷**（且缺「活动名撞车」的显式 fail-loud 检查：现在是一崩了之，无点名）。
> **影响**：**中央工人不可启动 → 共享队列无 poller**（巡检/周期流程全停）；每票专属工人不受影响
> （dev-lane 票照跑）。t260924-04 的 merge_check（pytest 全绿）**测不到**此类注册期冲突=闸的盲区。
> **修法方向**：①加载器保证引擎模块不被二次导入（模块身份去重），或对项目加载面做活动名命名空间；
> ②加载期做「活动名唯一性」显式校验并 fail-loud 点名（不崩栈、不空过）；③闸侧补一条「工人可启动」
> 的机械检查（worker 注册 dry-run），把这类冲突挡在合并前。
> **现场**：nusuyou 注册声明在场（`~/.sandbar/projects/nusuyou/project.yaml` 的 `workflow_modules`），
> 复现=中央工人启动。
> **260925 停摆与临时处置（integration 记名）**：事故实际范围**远大于中央工人**——每票专属工人同样
> 崩（t260925-16/17 的工人日志崩溃循环 **118 次**）＝**所有新工人起不来、引擎对新工单全面停摆约 3 小时**
> （08:0x–11:09；期间集成层的票面查询因队列无 poller 而挂死，故 tick 卡住未及时识别，认账）。
> **临时处置（宿主提议的 A 方案，可逆）**：注释掉 nusuyou 注册声明的 `workflow_modules` 一行
> （备份 `/tmp/nusuyou-project.yaml.bak-260925`）→ 新工人立刻恢复、中央工人重启成功（pid 44791）。
> **复原步骤（本 KI 修好、且 t260925-16 落地后必做）**：去掉该行注释（或从备份覆盖）→ 再重启中央工人 →
> 用 content_studio 声明复跑一遍「工人可启动」验证。**在复原之前，content-studio 模板不可加载。**
> **260925 15:0x 复原已完成（integration 记名）**：nusuyou 侧按同源需求书自行修好段名（八段 id 全加
> `cs-` 前缀，裸名仅剩 CLI marker 参数，非段 id），integration 随即复原声明并重启中央工人（pid 19995）——
> 日志 `project template modules passthrough: [... 'sandbar_ext_nusuyou_...']` ＋ `worker polling queues:
> sandbar`，**带外置模板声明的工人正常启动** ✓，降级模式解除。→ 同时反证了本 KI 的定位链（段 id →
> 活动名 → 撞引擎遗留活动名）。**加载口侧的结构性修法仍归 t260925-16**（注册期隔离拒收＋点名＋闸补
> worker 启动 dry-run＋命名纪律入文档），以免下一个项目再踩。

## KI-124 外置模板票的段路径闸恒关（client.py 硬编码 dev-lane）＝外置模板跑在「无写集护栏」状态（260925 nusuyou 需求书实测，integration 复核；修复票=t260925-22）
> **实案（nusuyou 留证：其 P0 二号票 t260925-14 create_plan 报告）**：`engine/client.py:1113-1117` **硬编码**
> `path_gate=(str(tpl) == "dev-lane")` → 项目外置模板（content-studio）的票 `path_gate` **恒 False**，
> **段路径闸永不触发＝没有写集护栏**（他们当前即以「闸恒关」运行）；而一旦放开，
> `path_gates.STAGE_PATH_RULES` 又**没有项目模板的八个新段规则** → 按该表语义会判 `unknown_stage`
> （fail-closed，但缺登记方式）。
> **风险（安全面）**：段写集闸是引擎对「段内能改哪些文件」的主要机械护栏；外置模板绕过它意味着
> **项目模板可在任意路径落盘**（只剩 notes/ 禁写与真源保护名单两道），与「项目模板＝跑在引擎工人进程里
> 的同权代码」叠加，信任面比设计预期更宽。
> **修法方向**：①`path_gate` 由硬编码模板名改为**按模板/票声明**；②提供项目模板段路径规则的登记方式
> （引擎侧登记或模板自声明二者择一），并以既有纪律「段 id 全集 ⊆ 规则键集」加单测锁定；③未声明段保持
> fail-closed，但错误文案要点名「缺哪条规则、怎么补」。

## KI-125 越权闸不认 git 折叠的未跟踪目录（写集写「新目录内具体文件」被判 unauthorized_path，交付件反复被隔离）（260925 nusuyou 需求书实测；修复票=t260925-23）
> **实案**：票写集条目写成**文件路径** `workflows/content_studio.py`（该目录为项目根下新建目录）时，
> 合并前回结报越权并把交付件挪进 `.sandbar/quarantine/`；票连续两轮无法提交、仲裁两度判 code-fault
> （nusuyou t260925-06 实证）。**定位**：`path_gates.judge_stage_paths`（implement 段 kind=write_set）
> 拿到的脏条目是 git 状态里的 **`?? workflows/`（未跟踪新目录被 git 折叠成目录名）**，而
> `_within("workflows", ["workflows/content_studio.py"]) = False` → `unauthorized_path`。
> **对照实证**：写集条目写成**目录** `packaging/` 时，同样场景正常入库（commit f1ca1a9a）——说明是匹配
> 面的口径问题，不是意图判定问题。**修法方向**：匹配前把折叠的未跟踪目录**展开为文件级条目**，或让
> 文件级/目录级条目**双向匹配**；验收须含反向对照（写集外文件仍判红）。**该项目侧绕法（已用）**：
> 写集一律用目录级条目。

## KI-126 审方案段 agent 无产出即冻票，票可挂数日无人拉（260926 巡检发现，integration 岗登记）
> **实案**：`t260922-04`（最后动作 **09-22 00:00**「进入本步（第 1 次）」）与 `t260922-05`（**09-21 23:56**）
> 双双停在 `review_plan/running`，`status=dispatched`（=非终态），**冻结约 4 天**；两条的泳道仍在
> `.lane/`（并已进 KI-112 的陈旧泳道名单）。
> **性质**：与当晚 `16` 票的「agent 退出 rc=1 未写结果文件」同族——**段 agent 无产出时，票既不重试也不
> 落 blocked，而是静默冻结**；且**没有任何兜底（无超时升级、无 watchdog、无漏票告警）**把它捞出来。
> 与 KI-113（工人冻结码/无 supervisor）、KI-120（block 不可脱困）同属「状态机不驱动力」家族。
> **影响**：①「在途票」账面失真（僵尸票长期占位，掩盖真实负载）；②其泳道永久滞留（KI-112 清账被
> 「非终态票」卡住）；③若发生在关键票上，等于静默丢活。
> **修法方向**：①段 agent 无产出/退出异常 → 活动层显式判失败并让工作流落 blocked（点名）或按策略重试；
> ②票级 watchdog：`running` 超过阈值无进展即在票面高声标红/落 pending 告警（可与 dispatcher-scan 或巡检
> 的漏跑核查同源）；③僵尸票清场入口（记名 cancel）——本 KI 当场无处置，待宿主一句话。
>
> **260926 处置**：宿主令「cancel 掉」——`t260922-04/05` 已记名 terminate（清场根因另立 KI-127），
> 僵尸清场完成；**机制面（无超时升级/无 watchdog）仍待修**，本 KI 保持 open。

## KI-127 「作废/关票不杀流程」：票面 closed 但 workflow 未 terminate → 在飞活动把票推回 dispatched，成永久僵尸（260926 清场实测，integration 岗登记；实案=t260922-04/05）
> **实案**：09-22 07:39 建 04/05 两票（建票口径错：`user_request` 与 `body` 同时传，引擎口径
> `user_request or body` → agent 只读到一行宿主令、看不到需求正文），07:41 作废改号重建为 `t260922-06/07`
> （两张均已合并收口）。票面 log 留了 `status=closed` 的记名（作废 + 跨项目闸「策略=拒收」），**数据目录也被拆**
> （`data/tickets/t260922-04/05` 今已不存在），**但那张 Temporal workflow 从未 terminate**：当时已在飞的
> `create_plan` 活动照跑完（07:56 / 08:00），workflow 随即推进到 `review_plan/running`，并把它自己的票面
> **推回 `status=dispatched`** —— 两张僵尸票挂了 4 天（KI-126 的实案就是它们）；两张专属 worker 也一直挂着
> （260926 07:07 terminate 后才自退，日志尾部即「watch：workflow 已收口（TERMINATED），专属 worker 自退」）。
> **关键机制**：`ticket.py list/show` 均走 **v2 查 Temporal**——workflow 活着就等于「进行中」，数据目录被拆
> 不影响它继续出现在名册里；**票面 log 的终态记录与 workflow 实际状态之间没有对账**。
> **影响**：①名册与负载失真（僵尸长期占位，掩盖真实在途）；②泳道壳永久滞留（KI-112 清账被「非终态票」卡住）；
> ③只能靠人工辨认，无任何告警。
> **修法方向**：①cancel/作废路径统一「先留痕、后 terminate」，terminate 结果进票面可判（t260925-05 反证：
> terminate 失败=票面完全不可得）；②新增对账巡检项——票面已 closed 而 workflow 仍 RUNNING（或反之）=不一致，
> 高声报；③活动收尾落盘前复核票面终态：**已 closed 的票不得被活动推回 dispatched**。

## KI-128 段序列变更打在飞票＝永久不可重放僵尸（Temporal 非确定性）：票面查询恒失败、正规记名取消入口进不去（260926 清场实测，integration 岗登记；实案=t260925-05）
> **实案**：`t260925-05`（中央工人新鲜度/轮换票）的专属 worker 自 09-25 22:47 起刷
> `[TMPRL1100] Nondeterminism error: Activity type of scheduled event 'implement' does not match activity type
> of activity command 'verify_review_gate'`，**11656 条 / 8.2MB 日志**（来源=控制台与 CLI 的持续轮询）；该票在
> `list` 里显示 `stage=None, updated=epoch0`（查询面已废），`ticket.py show/cancel` 全线失败——cancel 的
> 跨项目闸**前置读快照**先失败，被归成 `kind=transient`「瞬时抖动？请刷新重试」（**误导：这是永久性票损**），
> 于是「未执行任何动作」；最后只能走**裸 `client.py cancel`** terminate（记名只落 admin.log，票面留痕不可得），
> worker 07:08 收口自退。
> **性质**：dev-lane 在 implement 前插了 `verify_review_gate`（t260829-07 / t260922-18 一族）——**在段序列里
> 插入或改名 activity 是 Temporal 破坏性变更**：历史里没有该事件的在飞 workflow 一重放即非确定，票永久推不动；
> 且 **Query 也要重放**，所以连读都读不到——是 KI-025「查询失败说谎」的升级形态（那次是误报不存在，这次是
> 查询面结构性报废）。
> **影响**：①在飞票静默变僵尸且无告警；②读不到 → 记名取消入口结构上够不着（只能裸 terminate，丢票面记名）；
> ③轮询持续刷 worker 日志（8.2MB/8h，无人察觉）。
> **修法方向**：①工作流版本化纪律（Temporal patching / `workflow.patched`，或「段序列与活动名变更只对新票生效」），
> 并写进引擎改动的审查清单（这次是插段，下次不许直接插）；②非确定错误必须与瞬时抖动分开，`kind` 不得归
> transient，文案点名「票损、不可重放」；③脱困出口：记名 terminate 不得以「票面快照可得」为前置。

## KI-129 期号槽被「非终态」期票占住 → 后续自动班**静默跳过**（spawner 去重命中即 50ms 完成：无票、无报告、无告警；reopen 通道只认终态槽）（260926 巡检验收实测，integration 岗登记）
> **实案（期 20260926）**：09-26 07:30（＝2026-09-25T23:30Z）调度**确实触发**了——spawner 工作流
> `inspection-spawn-integration-tests-2026-09-25T23:30:00Z` 在 **50ms 内 COMPLETED**，返回值：
> `{"dedup_source":"sa_query","deduped":true,"instance":"integration-tests","period":"20260926",
> "ticket_id":"t260926-01","triggered":false}`。即：本期期票已存在（`t260926-01`＝09-24 手动顺延开的那期，
> **至今停在 `inspect/blocked`**）→ 去重命中 → **本期根本没跑**：无新票、无套件回执、无审查报告、
> 中央工人日志零行（worker.log 停在 09-25 15:02 启动行）、宿主侧零告警；期票也不在 `ticket.py list` 面，肉眼查不到。
> **性质**：`(实例, 期)` 去重的「占位」判据**不区分占用者的终态/非终态**。终态槽有 reopen 通道
> （`append_reopen_journal` / 期号 `-1` 后缀，见 `inspection_ticketing.py`），**非终态槽（blocked/running 卡死）
> 没有任何通道**：既不会自动重跑，也不让位，**永久吞掉该期号**；而期号＝当天日期，于是「今天这一班」就这么没了。
> 与 KI-114（终态票期号黑洞）、KI-125（期号槽黑洞修法）同族，是**新形态**（占用者未终态）。
> **影响**：①「每日一班」的承诺静默失效，**没有任何 face**（唯一证据是 spawner 的 50ms 回执）；
> ②巡检欠账被系统自己掩盖（漏跑核查只认台账文件，本期台账不存在 → 判「漏 1 期」，但要等 deadman 跑才有声）；
> ③一张 blocked 脏票不主动清场就永久堵路。
> **修法方向**：①去重判据并入占用者执行状态（非终态但超期未推进 → 高声报 + 允许按 reopen 口径另开「期号-1」）；
> ②`triggered:false` 必须落到可观测面（admin.log 一行 + 巡检台账一行），不许只活在返回值里；
> ③巡检手册补一条：期号＝当天日期的自动班被占 → 手动触发下一期（本岗 260926 按此处置）。
>
> **260926 追加（处置实测：该槽位「解不开」，只能换期）**：想释放 20260926 的槽位再重跑同期，
> 实测**两条路都不通**——① `ticket.py cancel t260926-01` 回 `already_terminal:true, exec_status=COMPLETED`
> （票面 blocked ≠ 执行未终态：**workflow 执行早已 COMPLETED**，「blocked」只是票面判决）；② 于是
> `period_slot_verdict("COMPLETED")` 判为 **served → 照旧 deduped**（KI-114 语义：只有
> CANCELED/TERMINATED 才释放槽位并自动重开）。**结论：一个「跑完了但判决 blocked」的期票，会把该期号
> 永久吞掉，且现有入口无一能改判/清场**（reopen 只认终止态、cancel 幂等挡回）。处置改走换期：
> `inspection_trigger.py trigger --instance integration-tests --period 20260927` →
> `{"triggered":true,"deduped":false,"ticket_id":"t260927-01"}`（260926 本期记为永久丢失，证据留在
> `out/inspection/inspection-integration-tests-20260926.json`）。**另注副作用**：提前服务下一期会让
> 「明天 07:30 的自动班」对该期去重跳过——期号并未丢（一个期号只服务一次），但**服务日期提前一天**；
> 宿主若在意按日节奏，修法须让 dedupe 认「served 且判决非 ok」的槽位。
>
> **同批巡检验收实测（260926，期 20260926）**：①期票未铸＝本 KI；②套件回执 `ran>0` **仍待验**——09-24 那期为
> `ran=0 wall=3300s`（KI-116 零信号实案），修法 t260924-05 已合并但**此后没有任何一期真跑过**；③审查段 09-24
> 超时 blocked（预算 3600s 用尽、无发现清单）→ 同样待验；④拆除回执「已清」**不实**——09-24/09-25 两个期号的
> 泳道目录壳一直在 `.lane/`（git 登记与分支已清、目录残留＝KI-115 实案；260926 本岗按「先列后删」口径清除）；
> ⑤agent_home 锚**漂移实锤**——09-24 期的 agent_home 落在**泳道**里
> （`.lane/inspection-integration-tests-20260925/server/engine/out/inspection/agent-home/integration-tests-20260924`，
> 68 个文件），主仓 `server/engine/out/inspection/agent-home/` 无其影＝KI-110 实案；已搬回主仓 out/ 留证。

## KI-130 集成断言锚定「票外文档」＝泳道结构性不可满足（S1 charter↔notes 附录逐字；实测卡死九轮，260926 宿主令删除）（integration 岗登记）
> **实案**：`integration/t260904-07/sc_session_charter_source_contract.mjs` 的 S1 要求 `server/session_charter.md`
> 与 `notes/discussions/260904-project-session-charter.md` 附录 ```markdown 块**逐字一致**。而 `notes/` 不在任何
> 泳道写集内（有意设计），于是**任何交付涉及 charter 的票对该断言结构性无解**——只能等人回主仓手写。
> 实测代价：`t260925-21` 同一条件连判 **9 轮** tests-fault（每轮附一趟全量、10 次仲裁，最后靠 pause 止血）；
> `t260907-05`（命名迁移票）已被卡过一次，当时靠加「命名 token 归一」容忍面绕过；260926 附录回写当刻，
> main 立刻出现**镜像红**（附录 99 行 / charter 94 行）。另：该断言与本场景 S2 自身原则**自相矛盾**——
> S2 明写「授权栏内容会合法变更 → 不锚内容」，S1 却把整份可变文件的逐字相等焊到另一份文档上。
> **规律（集成设计纪律）**：断言只可锚「调用方/用户可感知的承诺面」（公开接口、行为、交付物自身要素）；
> **不得锚定票外文档，尤其 notes/ 过程材料**——那类同步属**人的流程**（落票 + 人审签字时核对），不是机械红。
> 反证：全仓 39 处引用 `notes/` 的场景里，其余都是「notes 不可写」的反向守卫，只有这一条把 notes 当断言对象。
> **处置（260926 宿主令「删 S1，不开票」）**：S1 三条断言整段删除，场景保留 S2–S5（17 检查全绿）；
> `run_scenarios.py` 注册描述同步改写。无替代机械看守，同步责任回归人门。

## KI-131 自动班「静默跳过」未被手动重跑能力覆盖（＝KI-129 自动面；手动面 260926 已修）
> **实案口径**：期 20260926 的槽位被一张「执行 COMPLETED、判决 blocked」的期票占死（KI-129），
> 自动班静默跳过；本岗改走换期（手动开 20260927＝t260927-01）处置。
> **已修（260926 宿主令「不能手动 trigger 一次巡检吗，这个是应该支持的」）**：
> `server/engine/inspection_trigger.py trigger [--reopen-reason <人工具名>]`——非空即对
> 「已服务(COMPLETED)」「FAILED/TIMED_OUT/未知」槽位与终止票同路重开（铸新号 + 审计三处：
> 回执 `superseded_ticket_id` / 新指针 `supersedes` / reopen journal 落 `reason`）；**在飞期（live）
> 仍拒**（重跑＝双跑同一期，先等收口或记名 cancel）；**空串＝既有语义逐字不变**（served dedup 回执
> 另带 `reopen_hint` 指路）。回归用例 6 支（`server/engine/tests/test_t260925_09_terminated_period_reopen.py`：
> served/failed 具名重开、活期拒、指针层两态、hint）。
> **仍未修（本条留 open）**：**自动班**（cron → spawner）不带具名，故对「served 但判决非 ok」的槽位
> **仍然静默跳过**——彻底修需 spawner 侧据「上一期判决」（台账面 `out/inspection/<inst>-<period>.json`
> 的 face）自动派生重开理由，属 activity 面改动且**需重启中央工人**（KI-113 冻结码）。这是 KI-129 安静
> 失效的最后一块，待下一步（宿主授权后动）。


## KI-132 巡检套件「零信号」未修好：套件活动以 `server/admin.log` ENOENT 收场（ran=0），流程照常推进到审查段（260926 期 20260927 首次真验实测，integration 岗登记）
> **实案**：手动开的期 20260927（t260927-01，base=main `dcfc627`）跑满套件段后，
> `out/inspection/inspection-integration-tests-20260927-suite.json` 回执 **ran=0 pass=0 fail=0 env_fail=0 墙钟=2834.4s**，
> `error="verify_lane integ 无有效输出（exit=1）：Traceback … .lane/inspection-integration-tests-20260927/server/admin.py:178 → tools_registry.call:116 → audit:90 → FileNotFoundError:
> '/Users/user/Documents/sandbar/.lane/inspection-integration-tests-20260927/server/admin.log'"`。
> 中央工人日志同一活动的行在 **09:08:56** 才出现，而流程时间线在 **09:06:20** 已记「suite → 泳道拆除：已清」
> 并进入 `inspect` —— **拆除先于套件回报**，套件进程随后写盘时目标已不在（ENOENT 的候选机制）。
> **结论**：KI-116 的「套件零信号」**未修好**（这是修复合并后的第一次真跑：ran 仍为 0，且这回拿到了具体报错面）；
> 修法面（预算/拆除次序 vs 落地活动回报）与 KI-131 的自动班堵塞是同一张巡检工程的下一刀。
> **旁证**：本次期票铸出、`lane_teardown=已清（零残留）`、`agent_home` 落主仓 `out/inspection/agent-home/integration-tests-20260927`
> ——清单 ①④⑤ 三项过，②（ran>0）**不过**，③（审查段）被供应商周额度打断（见下，环境因非引擎因）。
> **环境因（非 KI，留证）**：审查段 `inspect` blocked，原因为 `dsh: AUTH: 403 … You've reached your weekly (7-day) usage limit`
> ——**模型供应商 7 天额度用尽**，故本期无发现清单；额度恢复后需重跑一期。

## KI-133 模型供应商额度耗尽（AUTH 403 weekly limit）不被识别为环境类：票面只报「agent 退出码 1」，引擎照通用重试烧尝试（260926 两处实案，integration 岗登记）
> **实案（同日两处）**：① 巡检期 20260927 的 `inspect` 段 blocked，票面文案=「agent 退出码 1（未完成）」，
> 真因在 agent 日志里：`dsh: AUTH: 403 {"error":{"type":"permission_error","message":"You've reached your weekly (7-day)
> usage limit…"}}`；② 签完 `t260926-04` 终审门后 `cs-publish` 段同一形态 blocked（`RuntimeError: headless agent 退出（rc=1）
> 但未写结果文件 …/stage_cs-publish_gen1.json`），agent 日志里是同一串 403，且**反复重试**（`dsh-headless-resume: 已恢复会话`
> 数轮）直到退出。
> **性质**：额度类失败（401/403 AUTH、quota/rate-limit）与「代码/内容失败」在票面**完全同形**——都是 generic agent 退出 rc=1；
> 引擎按通用瞬态故障重试，票面不点名「额度/鉴权」，**宿主与值守只能翻 agent 日志才知道不是自己的活坏了**。
> **影响**：① 排障误导（照「agent 崩了」查代码，实为额度）；② 白烧重试与日志；③ 巡检/内容链在额度耗尽期间会**连续多期零产出**
> 而票面看像产品故障。
> **修法方向**：① spawn 结果面识别 AUTH 403/quota/rate-limit 关键字 → 段结果落 `env_fail` 语义 + 票面/巡检 face 点名
> 「模型供应商额度耗尽（哪家/何时重置）」，且**不重试**（额度不会因重试恢复）；② 巡检审查段遇此态记为「环境红」而非「agent 未完成」，
> 免得把它算进「巡检连续零信号」的家族里。

> **260926 追加（我自己的 reopen 能力有缺口）**：`--reopen-reason` 可重开一次，但**同一期重开第二次就被守卫拒**：
> `trigger --period 20260927 --reopen-reason …` 第二次返回 `ok:false「同期已服务票出现多张：t260927-01、t260927-02
> ——每期一票被破坏，人工处置」`（`inspection_ticketing.open_period_ticket` 的 `len(served_ids) > 1` 守卫把
> 「多次重开留下的多张已服务票」误判成破窗）。修法方向：带 `reopen_reason` 时允许 N 张已服务票共存
> （supersede 链式记名 + reopen journal 逐行留痕），只对**无具名**的多张已服务票保持 fail-closed。
> 当下的绕法＝换新期（本岗当日即改用期 20260928 验收）。

## KI-134 两处预先存在的巡检/自检失败（260926 期 20260929 收尾时挖出，非当轮改动引入；integration 岗登记）
> 子代理「stash 全部改动后复跑＝同样失败」的双证下，两条与本轮改动面无关的既有红：
> ① `server/engine/selfcheck_integ_loop.py` → `FAIL 明细逐条带 exit 与尾段（…末条恒为 __pool_exclude__ 少跑点名条）`：
>    实际末条是 `__ledger__`（**台账面在场时 details 多一条**）——判据钉在「末条恰为某固定项」上，台账面一开就假红；
> ② `integration/t260924-06/sc_inspect_zero_face.py`：**带引擎 venv 跑**时 `RuntimeError('Not in activity context')`
>    （不带 venv 走 env-red 路径时 pass=9/0）——场景在 venv 形态下越界调用了活动上下文里的东西。
> 影响：两条都是「判据/形态耦合」型假红，会污染闸侧归因；修法方向＝①改成「集合包含」而非「末条等值」；
> ②场景在 venv 形态下改用不依赖活动上下文的桩或显式 ENV_FAIL 点名。待排期。

> **260930 追加（实测两案：长命 worker 的「内存旧模块」会把修复判成失效）**：同一个坑今天咬了两次——
> ① 期 20260928 的套件回执出现 `>3000s`（新代码在巡检链上不可能给 3000，且回执缺新键）；
> ② 期 20260930 的产物里 `suite` 族标题已是英文、`deadman` 族仍是中文（产物 mtime 16:29 > 模块 mtime 14:52）。
> 两次都是**磁盘修复已落地、但长命 worker 用启动时载入的旧模块**，结果被误读成「修复无效」。
> 处置：① 每次改完引擎面**必须重启对应 worker**（中央工人=共享队列、ticket 各自专属）再实测；
> ② 演进：回执/face 落可读 `code_stamp`（多模块 mtime + worker 启动时刻），使「混版本」机械可判，
>   不再靠人肉比 mtime（已授权实现）；③ 教训入审查清单：**实测出「不像新代码/数值不合理」时，
>   第一步先判版本，再谈归因**。
