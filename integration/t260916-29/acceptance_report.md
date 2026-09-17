# t260916-29 验收走查报告（acceptance_walkthrough，integration）

走查对象：引擎 P1「票专属 worker 的优雅停实为立即取消」修复（implement 提交 2b3df43，16 文件 +1770/-60）。
走查方式：integration 灰盒独立实跑（不复述 developer 自测），对当前 worktree 全量取证。

## 结论：status=ok（验收四项全过，机械轮 9 败全数归因为非本票）

## 做了什么（逐验收项结论）

| # | 工单验收项 | 结论 | 证据 |
|---|---|---|---|
| ① | UT/场景：worker 停机时在飞活动 → grace 生效或失败原因点名「worker 终止」 | **过** | 引擎 selfcheck 场景 A/B/C 实跑 PASS=12 FAIL=0：A=宽限期内在飞 stub 收尾（grace 3s 生效+停机日志逐票点名「停机点名：在飞 agent 活动 票 t-selfcheck-a 段 slow_stage_a gen 0 attempt 1」+注册表终态 completed）；B=grace=0 复现事故形态→取消被分类为 worker_terminated、票面文案点名「worker 被外部终止（停机/重载），活动已取消（票 t-selfcheck-b 段 slow_stage_b）」；C=停机取消自动重跑一次成功（calls=2，不落 blocked）。集成场景①（grace 旋钮契约，真实 worker.py 进程面）PASS：缺省 1800s/显式 0 逃生门/畸形三值回缺省/显式 2 透传 SDK（will wait 0:00:02 实锚） |
| ② | 票面文案断言（不再出现无信息的「活动故障」） | **过** | selfcheck B 场景级断言「不再出现无信息旧文案」在文；developer UT 42 过（含 blocked_reason 端到端、KI-093 兄弟边负例=普通失败不被洗成停机）；全族 grep `agent 活动故障` 确认 dev_lane 12 位+base 2 位 catch 全部改走 `format_agent_stage_failure` 唯一出口，代码面无漏网直拼（余量命中均为注释/UT 断言/旧文案出口本身，属设计内） |
| ③ | 既有 worker/信号面场景（t260913-01）零回归 | **过** | t260913-01-authz-signal-delivery 实跑 pass=37 fail=0，拆台零残留、审计账本 0 条（未触碰生产 7233/8233/3099）；worker.py 信号处理原样抽出为 `install_stop_signal_handlers()`（行为等价重构），verify_signal_transport 未动 |
| ④ | 文档更新（运维口径落 server/engine/README.md） | **过** | README §8.3.1 新增：核心事实（重启/重载 console 会波及全部在飞 agent 阶段）+SIGTERM 后语义（宽限旋钮/点名/终态清单/票面点名文案/自动重跑一次）+三路停机口径表（dispose 路/崩溃收养路/断电 SIGKILL 路）+生效窗口（按 worker 进程生效，存量票 worker 重启前仍是旧码）+已知边界（merge_check 等不在册、SIGKILL 无宽限）+故障模式取舍清单（C5 纪律）。未写 notes/，符合写集 |

### 集成场景②（console 崩溃收养路）实跑 PASS
腿A 收养路（console 崩溃→票 worker 被 launchd 收养 ppid=1→watch 发现自退）缺省 grace 实得 1800s+自退语义日志在文；腿B 旋钮=2 贯通崩溃路；腿C 直接信号对照恒判（防全腿 N/A）。收养观测 ps+pgrep 双通道，被测子进程零生产连接（审计钩子自证）。

## 测试资产变更审查（对照打回轮次）

本票期间被改动的既有测试 2 处，逐处核实为**契约精确化，非绿灯捷径**：

1. `integration/t260901-21/i02_spawn_wiring.py`：spawn 接线锁的三个宿主函数（_run_agent_stage_impl/arbitrate/acceptance_walkthrough）因包 `worker_termination_guard` 薄壳、本体移名 `_<host>_body`，检查新增 `resolve()` 跟随薄壳找本体。实证：三薄壳函数体均无 spawn/reap 面（grep 验证 False），本体接线/reap 全部在场，锁语义未弱化；实跑 pass=11 fail=0。
2. `integration/t260901-25/t02_source_locks.py`：同型 `resolve_body()` 跟随逻辑（KI-009 finally reap 锁）。实跑 pass=15 fail=0，reap 接入+finally 兜底断言仍在。

既有测试新增集成场景 2 条（sc_worker_stop_grace_knob/sc_console_crash_graceful_stop）登记 run_scenarios.py SCENARIOS（pool=engine），intent 查重声明完整，lint_tests.py 0 error/0 warn。

## 机械集成测试结果归因（9 败逐条，全部非本票）

机械轮（integration-report-260917-074707：227 跑/218 过/9 败/0 环境红，跳过池=engine+exclusive）9 败逐条实跑或形态归因：

| 失败场景 | 机械轮形态 | 本轮归因 |
|---|---|---|
| t11-arbitrate-log-renders（0.1s） | 秒败 | **实跑绿**（rendered=1 logging_error=no） |
| t11-log-faultsurface（0.1s） | 秒败 | **实跑绿**（cases=4 全过） |
| t260907-04-naming-grep-assert（0.2s） | 秒败 | **实跑绿**（pass=7） |
| t260907-10-engine-layout（0.5s） | 秒败 | **实跑绿**（pass=39） |
| lane-parallel-dom（12.2s） | P6 console.error 洁癖 | **实跑绿 8/8（含红过的 P6）** |
| t260904-05-session-lifecycle-ui / t260904-07-charter-injection-journey / t13-evidence-lightbox / t260911-05-ki048-status-card-dom | ERR_CONNECTION_REFUSED(21010)/ERR_INCOMPLETE_CHUNKED_ENCODING，且 t260911-05 业务断言 T1-T3 全过仅 T4 洁癖红 | 台面资源瞬态形态（与已证绿的 lane-parallel-dom 同型：并行 227 条时的端口/SSE 流竞争），写集与本票零交集（workbench UI 面 vs server/engine worker 面），不属本票回归 |

四条秒败场景机械轮红而单跑绿，指向机械轮并发执行的环境瞬态；闸拦机制（t260910-13 决策表，baseline_unavailable）拦下待归属，本轮实跑即归属证据。

## 并行期 UI 呈现检查项

**不适用**：本票写集（server/engine/ + integration/）纯引擎停机面与测试，不涉 UI/泳道图渲染。顺带实跑 lane-parallel-dom 8/8 绿，供参考。

## 怎么验证的

- `python3 integration/lint_tests.py` → 0 error / 0 warn（SCENARIOS 292 条）。
- developer UT：`.venv/bin/python -m pytest tests/test_t260916_29_worker_graceful_stop.py -q` → 42 passed。
- 引擎 selfcheck：`selfcheck_worker_graceful_stop.py` → PASS=12 FAIL=0（场景 A 宽限收尾/B 归因文案/C 重跑兜底，本地测试 server 随机端口，零碰 3099/7233）。
- 集成场景：`sc_worker_stop_grace_knob.py` PASS、`sc_console_crash_graceful_stop.py` PASS（隔离 docker 台，拆台零残留、审计零记录）。
- 回归：t260913-01 pass=37 fail=0；四条源码锁+lane-parallel-dom 实跑全绿（归因机械轮 9 败）。
- 源码走查：worker.py（旋钮容错矩阵/单一真源 kwargs/停机点名/终态清单）、agent_activities.py（guard 四态/取消细节 fail-closed/KI-009 reap 原样）、shared.py（classify 沿 cause 链+环/深>8 fail-closed、文案函数、重跑兜底 CancelledError 不吞）、dev_lane/base（12+2 处 catch 统一出口、patched 门防 replay 歧变）、ticket_worker.py（reap 只 SIGTERM 不 SIGKILL，宽限不被回收侧砍断）、README §8.3.1。

## 遗留与风险（观察项，不阻塞验收）

1. **冲突消解轮前缀信息损失**：dev_lane 冲突消解轮旧文案「冲突消解轮 agent 活动故障（已重试）：…」换统一出口后丢失「冲突消解轮」前缀（段名仍在 blocked 字段，票号段号仍点名）。归因能力不降，但历史日志对照时少一个上下文词。可接受。
2. **SIGKILL/断电路无宽限**（本质局限，README 已声明已知边界）：靠心跳 3min+重试兜底，票面呈 timeout 形文案，不属本票修复面。
3. **merge_check（20min）等非 agent 长活动不在册**：停机取消仍走旧文案（README 已声明，通用化留专门票）。
4. **生效窗口**：存量在跑票 worker 仍是旧码（grace=0、无归因），随各自重启才受益（README §8.3.1 已写明，KI-081 教训对照）。本票上线后仍需一次 console 重启/票 worker 轮换才全量生效——重启本身的破坏力已由本票变可控（宽限+归因+重跑）。
5. **grace 缺省 1800s 的运维体感**：console 正常退出会等票 worker 宽限收尾（worker 收 SIGTERM 后最多滞留 30min）；README 已写「设多大=接受滞留多久」，运维需知情。
6. 机械轮 engine 池整池被跳过（excluded_pools），本票两条集成场景机械轮未跑——本轮验收已实跑补证；后续机械轮应恢复 engine 池。

## doc_sediment（沉淀一问）

**want=true**。建议：target=`docs/testing-guide.md`（及/或引擎机制主档 worker 生命周期节），reason=docs/testing-guide.md 的 3099 铁律只写禁令（「不允许重启/停止」）不写破坏力；本票把「重启/重载 console 会 SIGTERM 全部票 worker→在飞 agent 段进宽限（缺省 1800s）/超宽限取消且票面点名 worker 终止」的运维事实落在 server/engine/README.md §8.3.1，但 docs/ 知识库读者（新 agent 首读面）读不到该破坏面，属知识库与引擎 README 的覆盖缺口。本票写集（server/engine/+integration/）不含 docs/，故仅预填建议，不代改。

## doc_conflicts（反向同步闸）

只报实读文档：docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md（grep worker/优雅停/SIGTERM/停机相关主张，仅「不需要零停机重启——worker 跟着工单同生共死」一条，与本票修复不冲突：票 worker 同生共死语义未变，改的是停机时在飞活动处置）、docs/testing-guide.md（3099 禁令，与本票运维口径互补不冲突）、docs/design/失败分类协议v1.md 与 docs/design/工单工作流台设计.md（grep 活动故障/blocked 文案面均无命中，无被推翻主张）。**结论：零矛盾，无 pending-doc-sync 条目。**

---

# gen1 走查附录（仲裁 gen0 判 tests-fault、回路收敛后重走查）

gen0 走查因仲裁判定 tests-fault 而作废；本轮（gen1）对当前盘面（implement 2b3df43 + arbitrate 24fa155 + 仲裁 gen1 在途修改）重新走查。**结论：status=ok**——gen0 全部验收结论在本盘面复验成立，仲裁期间测试资产变更 4 处逐一核实为契约精确化/测试纠错，非绿灯捷径。

## 测试资产变更审查（仲裁期间 4 处，逐处核实）

| # | 变更 | 意图核实 | 复跑 |
|---|---|---|---|
| 1 | 本票两场景空队列名「旧名前缀票队列标识」→`sandbar-ticket-t26091629-*`（已落盘 24fa155） | 契约精确化：CLAUDE.md 硬规则5（旧名退役，新命名不携旧名；字面旧名不写入报告免触命名守卫）；空队列标识零行为变化 | 场景①② PASS |
| 2 | integration/t260916-02/lib_relocation.py:147 旧路径回落行补 `# engine-venv-compat` marker（仲裁 gen1 重施，当前在途未提交） | 测试资产纠错：该行是合法回落链行（新路径优先、旧布局路径兜底），t260907-10 守卫的豁免机制经核实真实存在（sc_engine_layout.py:101 行级 marker 判定），补 marker=既认惯例的声明，非放水 | engine-layout 39/0 PASS |
| 3 | integration/t260902-11/sc_t02_arbitrate_log_renders.py 的 find_arbitrate_call 锚从「函数名==arbitrate」放宽为「全模块扫+恰 1 处+args 空守卫」（仲裁 gen1 重施，在途未提交） | 测试纠错：本票薄壳化把 spawn 打点行随本体移入 _arbitrate_body，公开契约（恰 1 处打点/实参≥3/渲染含 cwd/无 Logging error）未变而测试破=测试写错（灰盒铁律：契约不变的实现重构不得打破集成测试）；恰 1 处断言保留=防重复打点意图不弱化 | t02/t03 PASS |
| 4 | t03 复用 t02 的 find_arbitrate_call，随 #3 一并治好 | 同上 | PASS |

**过程事故留痕**：仲裁 gen0 的同款修复曾被并行 agent 的树操作冲掉（t02 修正注释自述）；gen0 走查段实跑时曾读到在途修复版（绿），代落盘只收 3 项后盘面回红——这解释了重跑机械轮 3 败（t11×2+engine-layout）与仲裁「复跑 PASS」声称的矛盾：**声称的修正一度不在盘上，gen1 重施后以当前盘面复跑为准，全绿**。

## 机械重跑 3 败归因（227 跑/224 过/3 败/0 环境红）

3 败（t11-arbitrate-log-renders / t11-log-faultsurface / t260907-10-engine-layout）=上表 #2、#3 修正未落盘所致，**tests-fault 族，非产品缺陷**；仲裁 gen1 重施后本轮复跑三条全绿。gen0 轮 9 败中 5 条 UI 场景本轮全过（224 过佐证 KI-072 族负载敏感假红归因成立）。

## gen1 全量复验（当前盘面）

- lint_tests.py：0 error / 0 warn
- developer UT：42 passed
- selfcheck_worker_graceful_stop：PASS=12 FAIL=0（场景 A/B/C）
- 本票集成场景①②：PASS（队列名改动后复跑）
- t260913-01-authz-signal-delivery：pass=37 fail=0（零回归）
- 源码锁四条+lane-parallel-dom：PASS（gen0 已验，本轮三红场景复跑绿）

## doc_sediment / doc_conflicts（gen1 沿用）

docs/ 本轮零改动，gen0 结论沿用：doc_sediment want=true（target=docs/testing-guide.md，3099 红线补破坏力口径，本票写集不含 docs/ 故仅预填）；doc_conflicts 零矛盾。

## 参考 docs 清单

docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md（检索）；docs/testing-guide.md（检索）；docs/design/失败分类协议v1.md（检索）；docs/design/工单工作流台设计.md（检索）。

---

# gen2 走查附录（仲裁 gen1 期间 main 合并进泳道，重走查）

仲裁 gen1 后盘面又前进：aa29725 把 main 合入泳道（baa9d5d=t260916-20 收口，触及本票写集文件 server/engine/agent_activities.py +326 行；t260916-27 收口自带 lib_relocation.py 回落行 marker——engine-layout 因此恢复绿，非本票修复之功）；ca9190e 代落盘只收了 gen1 报告附录（+34 行），仲裁 gen1 重施的 t02 修复**再度被代落盘窗口冲掉**（工作树回旧锚）。本轮（gen2）对当前盘面走查，**结论：status=ok**。

## 做了什么

1. **归因 08:48 机械轮全部 13 个非 PASS**（228 跑/215 过/9 败/4 环境红）——逐条当前盘面单跑，**13/13 全绿**：FAIL×9（ticket-session-restore、top-entry-retired-form 11/0、t11×2、naming-grep 7/0、evidence-lightbox 13/0、lane-parallel-dom 8/8、auto-rework-trace、charter-injection-journey 12/0）+ ENV_FAIL×4（project-list-report 20/0、decl-gate、deadman、ms-decl-gate）。无一是产品缺陷。
2. **重施 t02 walker 修复（第 3 次）**：gen1 重施被 ca9190e 代落盘窗口冲掉，同款修复再次落盘（全模块扫+恰 1 处+args 空守卫，注释自述三次史）；复跑 t02/t03 绿。
3. **修正走查段自己引入的 naming 红**：gen1 报告附录写入字面旧名队列标识，被命名守卫扫出（integration/t260916-29/acceptance_report.md:84）——改措辞为「旧名前缀票队列标识」不留字面；复跑 naming 7/0 绿。走查段产物同样受守卫约束，如实留痕。
4. **main 合并后的本票面全量复验**：合并虽触及 agent_activities.py（+326 行，t260916-20 域），本票修复面（worker_termination_guard/旋钮/归因链 12+6+13 处锚点）完整在场；lint 0/0、developer UT 42 过、selfcheck PASS=12 FAIL=0、集成场景①② PASS、t260913-01 37/0——零回归。

## 测试资产变更审查（gen2 期）

| # | 变更 | 意图核实 | 复跑 |
|---|---|---|---|
| 1 | t02 find_arbitrate_call 第 3 次重施全模块扫（本段，在途未提交） | 与 gen1 同一处同一内容（打点行随薄壳本体在 agent_activities.py:5128，公开契约未变）；非新变更，是被冲修复的恢复 | t02/t03 绿 |
| 2 | 走查报告去字面旧名（本段，在途未提交） | 走查段自查自纠：报告文档受命名守卫约束，措辞合规化 | naming 7/0 绿 |
| 3 | main 合并带入 t260916-20/27（非本票改动） | 归因说明：agent_activities +326 行属 nested-repo 域，与本票 guard 面无交集（grep 复核）；lib_relocation marker 属 t260916-27 交付 | 本票面零回归（上） |

## 结构性风险（给 merge 执行人与引擎的硬提示，第三轮留痕）

**走查段与仲裁段并行跑同一工作树 + worker 代落盘逐段选择性收文件 = 未提交修复反复被冲**：gen0 修复被 24fa155 窗口冲掉、gen1 重施被 ca9190e 窗口冲掉（各只收部分文件）。gen2 交付时在途改动恰两处：integration/t260902-11/sc_t02_arbitrate_log_renders.py、integration/t260916-29/acceptance_report.md——**代落盘请同批收齐**；若 merge 时 t02 仍为旧锚（函数名==arbitrate），机械轮 t11×2 必红，按本报告 gen2 附录 #1 重施即可（内容三度验证）。

## 怎么验证的（gen2 增量）

- 13 个非 PASS 逐条单跑命令与结果见 evidence；四条秒败源码锁（t02/t03/naming/engine-layout）修后全绿。
- 本票面合并后全量复验：lint_tests.py 0 error/0 warn；UT 42 passed；selfcheck PASS=12 FAIL=0；场景①② PASS（docker 台拆台零残留）；t260913-01 pass=37 fail=0。
- 盘面状态：git log -3 = ca9190e（arbitrate gen1，仅报告）/ aa29725（merge main）/ baa9d5d；三处历史修复在场性复核（队列名 sandbar✓ 由 24fa155 持有、lib_relocation marker✓ 由 main 合并带入、t02 全模块扫=本段在途）。

## doc_sediment / doc_conflicts（gen2 沿用）

docs/ 本轮零改动：doc_sediment want=true（同 gen1）；doc_conflicts 零矛盾。

## 参考 docs 清单

docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md（检索）；docs/testing-guide.md（检索）；docs/design/失败分类协议v1.md（检索）；docs/design/工单工作流台设计.md（检索）。

---

# gen3 走查附录（收口：机械轮 228/228 全绿，走查独立复验全绿）

盘面收敛确认：44d12fe（arbitrate gen2 代落盘，2 项）把 gen2 走查段的全部在途改动（t02 walker 重施+报告脱敏）完整收齐——三轮竞态循环终止；最新机械轮 integration-report-260917-093955.json：**228 跑/228 过/0 败/0 环境红，零闸拦**。本轮（gen3）为收口走查，结论 **status=ok**。

## 做了什么

无新增改动（纯复验收口）。对当前盘面（44d12fe）独立复验四层：

| 层 | 复验项 | 结果 |
|---|---|---|
| 机械面 | 最新机械轮全名单 | 228/228/0/0，无 FAIL 无 ENV_FAIL 无闸拦 |
| 源码锁面 | t02/t03/naming-grep/engine-layout | 四条全绿（rendered=1 / cases=4 / 7-0 / 39-0） |
| 引擎面 | developer UT 42 + selfcheck A/B/C | 42 passed；PASS=12 FAIL=0 |
| 用户面 | 集成场景①（grace 旋钮契约）②（崩溃收养路）+ t260913-01 回归 | ①② PASS；t260913-01 pass=37 fail=0 |

## 逐验收项最终结论（四轮走查累计，当前盘面均复验成立）

①worker 停机宽限旋钮（缺省 1800s/显式 0 逃生门/畸形回缺省/透传 SDK）+停机逐票点名+终态清单——selfcheck 场景 A+集成场景①实证；②票面失败可辨「worker 被外部终止（停机/重载），活动已取消（票 X 段 Y 第 N 次）」，不再出现无信息「活动故障」——selfcheck 场景 B+UT+全族 grep 实证；③t260913-01 信号面零回归——四轮实跑 37/0；④运维口径 README §8.3.1 落地；④+（可选增强已做）停机取消自动重跑一次——selfcheck 场景 C 实证。

## 怎么验证的

见上表四层复验（全部本机实跑，非转述）；机械全绿证据=out/integration-report-260917-093955.json。

## 遗留与风险（收口后交人审）

1. 结构性竞态教训（gen2 附录详述：并行段共用工作树+代落盘选择性收文件）已在 44d12fe 收敛，但机制未改——建议引擎侧把「代落盘收全当前工作树全部写集改动」固化为确定性纪律（引擎改进建议，非本票范围）。
2. gen0 五条观察项沿用：冲突消解轮前缀信息损失/ SIGKILL 无宽限（心跳兜底）/merge_check 不在册/存量票 worker 生效窗口（本票上线后需一次票 worker 轮换才全量生效）/grace 1800s 运维体感（README §8.3.1 已声明）。
3. 机械轮 engine 池持续被跳过：本票两条集成场景（pool=engine）从未进机械轮，四轮验收均实跑补证——后续机械执行器恢复 engine 池调度时无需额外动作，场景已登记入册。
4. 4 条 ENV_FAIL 秒红曾在 08:48 轮同窗出现（共享前置瞬态），093955 轮已自愈；如复发建议机械执行器对 ENV_FAIL 做单跑重试再定局。
5. doc_sediment 预填未落地（本票写集不含 docs/）：docs/testing-guide.md 的 3099 铁律补破坏力口径，待专门票/岗位转正。

## doc_sediment / doc_conflicts（gen3 沿用）

docs/ 本轮零改动：doc_sediment want=true（同 gen1，target=docs/testing-guide.md）；doc_conflicts 零矛盾，无 pending-doc-sync 条目。

## 参考 docs 清单

docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md（检索）；docs/testing-guide.md（检索）；docs/design/失败分类协议v1.md（检索）；docs/design/工单工作流台设计.md（检索）。
