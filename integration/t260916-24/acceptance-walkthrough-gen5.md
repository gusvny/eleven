# t260916-24 验收走查报告（acceptance_walkthrough gen5，integration）

**结论：status=ok**——本票交付物全部后续变更均已审计（两处仲裁 gen0 修复 gen1
实跑验证等价；其余三文件零变更），UT/守卫维持面无本票回归；本轮机械 10 败全部
归因供给侧与 main 侧他票资产（台面连接层族×6、namespace SA 缺失×1、守卫两红
＝t260917-02 资产、瞬时×1）。**转人工判读项现状重申**：共享库 ensureTestTemporal
前提重落（唯一阻塞）与 :290 空过断言修复在 gen5-7 仲裁轮落过工作区后被恢复机制
吃掉，当前树态两处均缺席——人审签字前需裁决修复归属（详见 §遗留 1）。本报告
供人类最终合并审查。

## 做了什么

gen4 后回路多轮迭代（仲裁 gen5/6/7 重判 + gen8 代落盘），本轮走查四件事：①核实
gen4→gen5 间树态与代落盘内容（1e6f845 仅入库 gen4 走查报告；工作区已恢复干净——
仲裁 gen5/6/7 落在工作区的修复面被恢复机制吃掉，遗留风险成真）；②对本票交付物
自 implement 以来的全部后续变更做终局审计；③维持性复跑（守卫/探针/UT）；④本轮
机械 10 败按既有归因逐类核对。收口两问重答。

## 测试资产变更审查（gen4→gen5 间）

- **落库变更=零代码资产**：HEAD 1e6f845 唯一内容=acceptance-walkthrough-gen4.md
  入库（107 行，走查报告本身）；
- **仲裁 gen5-7 的工作区修复面已丢失**（与仲裁自述一致）：sc_auto_rework_trace.mjs
  :290 仍为空过断言 `started.ok !== false`（原形态）；ensureTestTemporal 仍
  `portOpen → return true` 单验端口（nsDescribe=0，报告所述 namespace 验真+幂等
  创建+SA 注册**不在场**）；工作区干净无未提交改动。该状态与我 gen4 上报一致，
  修复缺口持续存在；
- **本票交付物终局审计**（10ca93c implement→HEAD 全量）：probe_dsh_seam.py 12 行
  与 sc_t260916_24_dsh_expected_loud.py 5 行=仲裁 gen0 两处修复（--reuse-install
  改名、单前缀队列），gen1 已逐行核实「零行为变化/断言集不变」并实跑验证等价；
  sc_t260916_24_dsh_face_meta.py / lib_t26091624.py / sc_dsh_probe_selftest.py
  **零变更**；server/engine 四文件的后继变更为第二次 main merge 带入的 main 侧
  inspection 族（他票），gen4 已核实本票 dsh 接线在位（15 处引用+源码锚 UT 过）。
  **无未审计变更、无污染**。

## 怎么验证的（gen5 维持性复跑 + 10 败归因核对）

| 对象 | 结论 | 证据 |
| --- | --- | --- |
| L1 UT test_t260916_24_dsh_pin.py | **25 passed** | 接线+源码锚维持 |
| sc_dsh_probe_selftest / engine-layout | **exit 0 维持绿** | 探针金样本+篡改档、守卫 39/39 |
| no-skip-guard / naming-grep-assert | **exit 1 红（既有状态延续）** | 命中=第二次 main merge 带入的 t260917-02 资产（lib_t260917.py 的 Temporal 观测字段名/枚举 3 处；lib_inspection.py:103 勘误注释行内 suyou-test 字面），gen4 已归因非本票引入，树未变故延续 |
| 本票场景族①② | gen1 实跑结论延续有效 | 交付物终局审计（见上节）证明被测对象无未审计变更 |
| auto-rework-trace | 间歇红根因未变（namespace SA 缺失=场景外前提） | 仲裁 gen6 实测 FAIL 签名「Namespace sandbar-test has no mapping defined for search attribute ProjectKey」；修复点（共享库 ensureTestTemporal）转人工，树态仍缺席 |

本轮机械 10 败归因核对（全部与本票零代码交集）：
- 6 条闸拦（session-lifecycle-ui / lightbox / charter / lane-parallel-dom /
  lane-map-everblocked / detail-lane-map）＝台面连接层族，症状与 gen2 轮完全同
  签名（ERR_CONNECTION_REFUSED / ERR_INCOMPLETE_CHUNKED_ENCODING / 21020 事件流），
  gen2 仲裁已闭环归因（stage-console mid-run 死亡、ensureStageConsole 幂等自愈）
  且我 gen2 实证 lane-parallel-dom 复跑绿——供给侧间歇发作，非本票；
- auto-rework-trace＝namespace SA 缺失（转人工阻塞项，见上）；
- 其余 3 败按同基线事实＝守卫两红（他票资产）+t260905-06 瞬时（仲裁四轮单跑
  17/17 绿）的合集（留痕：名单未随本轮上下文注入）。

验收清单对照（gen5 终态）：①②③五轮维持满足；④既有场景零回归**本票侧满足**
（本票交付物引发的回归为零；现存红项全部归因供给侧/main 侧他票资产）。探针
live 档不入默认跑分面维持。UI 呈现检查项**不适用**（本票无 UI/泳道图渲染触及，
六轮一致）。

## 遗留与风险

1. **置顶（转人工判读项，唯一阻塞）**：共享库 `integration/baselines/ticket-lifecycle-scenes.mjs`
   的 ensureTestTemporal 前提重落（namespace describe 验真+缺席幂等创建+SA 族
   幂等注册+双验）——方案与实跑证据见仲裁 gen3/gen4/gen5 结果文件；仲裁按契约
   边界（共享场景库=仓库级资产）不越权，转人工。**当前树态两处修复均缺席**
   （工作区恢复机制吃掉了 gen5-7 的工作区修复面），人审签字前需裁决：由谁、在
   哪个票面重落该修复（消费该共享库的 8 个场景在台重建后都会红）。
2. 代落盘覆盖面问题建议引擎侧核查：gen3 代落盘仅收 1 文件（走查报告），同工作区
   的测试修复未收——历轮修复面反复被恢复机制吃掉，属于流程级缺口（非本票代码）。
3. 守卫两红（t260917-02 他票资产踩守卫）：归属仲裁裁定；本 lane 树上维持红，
   merge gate 若要求全绿需先处置（t260917-02 侧适配或守卫语义精确化）。
4. 探针 live 档（隔离 npm 安装+真会话五断言对账）六轮未实跑——T2 升级门槛时点
   的人工显式动作（RUNBOOK_GATE.md 待转正进 runbook §1）；断言 c/e 无离线自检
   覆盖，live 首跑需人工审读输出。

## 收口两问（gen5 终态重答，留痕）

- **doc_sediment**：want=true（六轮一致）。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（主档可观测性家族同构先例：usage 聚合/进度
  心跳）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸是新增引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块需 merge 执行人转正进
  `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾（六轮一致）。实际读过：docs/README.md；主档 §Worker
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
