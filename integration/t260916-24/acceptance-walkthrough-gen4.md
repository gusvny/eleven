# t260916-24 验收走查报告（acceptance_walkthrough gen4，integration）

**结论：status=ok**——本票核心面在第二次 main merge 后接线完好（UT 25/25 含源码
锚）、守卫维持面无本票引入回归；本轮全部机械败项与本票零交集且逐条归因定位。
**两项显著上报**：①仲裁 gen3 声称的测试资产修复**未落库**（空过断言与假确保
原样在场，机械绿≠修复生效）；②守卫两条红系第二次 main merge 带入的他票资产
（t260917-02）踩守卫，非本票引入。本报告供人类最终合并审查。

## 做了什么

gen3 之后回路又走了两步：第二次 main merge（444137d，conflicts keep both，带入
t260916-19/t260917-01/t260917-02 等，机械场景数 229→232）+ 仲裁 gen3 对
auto-rework-trace 做根因级定位（namespace suyou-test 缺失 + ensureTestTemporal（naming-compat 勘误引文）
假确保 + :290 空过断言，verdict=tests-fault）。gen4 走查：①核实 merge 对本票
契约面的影响；②逐处核实仲裁 gen3 声称的测试资产修复是否落地；③对本轮 4 败
逐条归因（含实跑复现）；④守卫/探针/UT 维持性复跑；⑤收口两问重答。

## 测试资产变更审查（gen3→gen4 间，逐处）

1. **第二次 main merge（444137d）**：本票核心四文件（dsh_pin.py / worker.py /
   场景①② / 探针与夹具）**零触碰**；main 侧带入的 agent_activities.py 变更
   （85 行，inspection 族）未伤本票接线——dsh_pin 引用 15 处在位、
   _prepare_agent_spawn@1388 在位、**UT 25 passed**（含 ⑨源码锚防接线漂移子用例）。
2. **仲裁 gen3 声称的两处测试修复未落库（显著上报）**：HEAD 提交 44956b5 仅含
   gen3 走查报告入库；`ticket-lifecycle-scenes.mjs` ensureTestTemporal 仍为
   `portOpen → return true` 单验端口（:130，报告所述 namespace describe 验真+
   幂等创建+SA 注册+双验**不在场**）；`sc_auto_rework_trace.mjs:290` 仍为空过
   断言 `started.ok !== false`（报告所述实读 body 改造**不在场**）；工作区干净
   无未提交改动。**本轮机械跑 auto-rework-trace 绿不能归因于该修复**（我同日
   空载单跑同命令红，见 §归因）——修复缺口仍在，间歇红预期继续。
3. 修正我方 gen3 报告的归因表述：auto-rework-trace 非「共享台重启后稳定坏态」
   ——gen4 实证红绿交替（gen1 单跑绿→gen2/gen3 机械红+空载双红→gen4 机械绿+
   我单跑红），真实机制=**间歇性 namespace 缺失窗口**（详见下节三环根因）。

## 怎么验证的（gen4 逐项）

| 对象 | 结论 | 证据 |
| --- | --- | --- |
| L1 UT test_t260916_24_dsh_pin.py | **25 passed**（merge 后） | 接线在位+源码锚过 |
| sc_dsh_probe_selftest / engine-layout | **exit 0 维持绿** | 探针金样本+篡改档、守卫 39/39 |
| no-skip-guard / naming-grep-assert | **实跑 exit 1 红**（新状态） | 命中全是第二次 merge 带入的他票资产，见下节归因 |
| t260905-06-doc-read-through（本轮唯一闸拦） | **复跑 exit 0 绿**（pass=17 fail=0） | ro 池文档走查场景，与本票零代码交集；环境类瞬时 |
| auto-rework-trace | **我单跑红**（mu56kzne，pass=4 fail=1 同症状）；本轮机械跑绿 | 红绿交替=间歇性，非稳定态（修正 gen3 表述） |

### 败项归因（只定位不修复）

1. **no-skip-guard / naming-grep-assert 红＝main 侧他票资产踩守卫（非本票引入）**：
   - no-skip 命中 `integration/t260917-02/lib_t260917.py` 3 处（:17/:211/:227）——
     `num_actions_skipped_overlap`（Temporal ScheduleInfo 观测字段名）、
     `OverlapPolicy=SKIP`（Temporal API 枚举）——调度观测面字面，非「跳过测试」
     语义，守卫字面 grep 误伤面；
   - naming 命中 `integration/t260905-03/lib_inspection.py:103` 单行——该行是
     t260917-02 的**勘误注释**（描述「台命名空间漏改残留 suyou-test」的勘误账），（naming-compat 勘误引文）
     行内 suyou-test 字面为勘误语境引用；（naming-compat 勘误引文）
   - 两文件最后变更=72f0849（t260917-02 squash，main 侧），随第二次 merge 进入
     本 lane 树。归属=main 侧 t260917-02 资产×守卫机制的适配（勘误行补豁免标记/
     守卫语义精确化），非本票写集可修，待仲裁归属。
2. **auto-rework-trace 间歇红三环根因**（仲裁 gen3 定位成立，但修复未落库）：
   namespace suyou-test 缺失窗口（台容器重建即丢）× ensureTestTemporal 假确保（naming-compat 勘误引文）
   （只验端口）× :290 空过断言（真实错误印在绿行里）。样本链：gen1 绿→gen2/3
   机械红+空载双红（mu54m7ud/mu557bk6/mu55c5rk）→gen4 机械绿+我单跑红
   （mu56kzne）。
3. t260905-06：环境类瞬时（复跑绿）。其余 3 败与 0 环境红口径下的名单未随上下文
   注入（留痕，归属归仲裁）。

验收清单对照（gen4 终态）：①②③维持满足（结论四轮延续，本轮 UT 复跑再加证）；
④既有场景零回归**本票侧满足**——本票交付物引发的回归为零；现存守卫两红与
auto-rework-trace 间歇红均归因 main 侧 merge 资产/既有测试资产缺陷，非本票引入。
探针 live 档不入默认跑分面维持。UI 呈现检查项**不适用**（本票无 UI/泳道图渲染
触及，五轮一致）。

## 遗留与风险

1. **置顶：仲裁 gen3 声称的测试修复未落库**——merge 前建议由仲裁/developer 补齐
   （ensureTestTemporal 命名空间验真+幂等创建+SA 注册、:290 实读断言），或最低
   限度把 suyou-test namespace 重建纳入台面供给流程；否则 auto-rework-trace 类（naming-compat 勘误引文）
   间歇红会继续消耗闸拦轮次。**人审不应依据仲裁 gen3 报告认为该缺陷已修**。
2. 守卫两红（main merge 他票资产）：归属仲裁裁定；在裁决前本 lane 树上这两条
   守卫场景保持红——若 merge gate 要求全绿，需先处置 t260917-02 侧适配。
3. 探针 live 档（隔离 npm 安装+真会话五断言对账）五轮未实跑——T2 升级门槛时点
   的人工显式动作（RUNBOOK_GATE.md 待转正进 runbook §1）；断言 c/e 无离线自检
   覆盖，live 首跑需人工审读输出。
4. 本轮其余 3 败名单未随上下文注入（留痕）。

## 收口两问（gen4 终态重答，留痕）

- **doc_sediment**：want=true（五轮一致）。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（主档可观测性家族同构先例：usage 聚合/进度
  心跳）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸是新增引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块需 merge 执行人转正进
  `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾（五轮一致）。实际读过：docs/README.md；主档 §Worker
  运行时；docs/ops/admin-dsh-应用方案.md §组装/会话/模型；docs/testing-guide.md；
  docs/design/metrics-api契约v1.md:236 行、dsh_seam需求书v1.md、sandbar项目接入
  契约v1.md（grep 行级）。低风险观察（不登记债）：admin-dsh-应用方案.md:33
  「SESSION_FORMAT_VERSION = 0（预发布，不承诺兼容）」将随 dsh 实际升级过时——
  自带免责且升级未执行，T2 时点同步该 ops 文档即可。

## 参考 docs 清单（结算 note 用）

读过：docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md
（§目录+Worker 运行时）；docs/ops/admin-dsh-应用方案.md（§组装/会话/模型行级）；
docs/testing-guide.md；docs/design/metrics-api契约v1.md（:236 行）；
docs/design/dsh_seam需求书v1.md、docs/design/sandbar项目接入契约v1.md（grep 行级）；
仓库根 CLAUDE.md；notes/epics/dsh-upgrade.md（主检出全文，契约真源）。
