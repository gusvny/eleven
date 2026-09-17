# t260916-24 验收走查报告（acceptance_walkthrough gen6，integration）

**结论：status=ok**——gen5 后本票面零变更（唯一新提交=gen5 走查报告入库），
维持性快验全绿（layout/探针自检/UT 25）；本轮机械跑 activity 超时（0 跑）属引擎
侧基础设施故障，不构成对本票的新证据；既有归因链延续。转人工判读项（共享库
ensureTestTemporal 前提重落）树态上仍缺席，维持上报。本报告供人类最终合并审查。

## 做了什么

gen5 后回路走了一轮仲裁（gen5 代落盘 343ee29）+ 一轮机械跑故障（ActivityError:
Activity task timed out，0 跑 0 败 0 环境红——**本轮无机械证据**）。gen6 走查
三件事：①核实 gen5→gen6 间树态（零代码资产变更）；②修复缺口现状复核（转人工
项维持缺席）；③维持性快验（layout/探针自检/UT）。收口两问重答。

## 测试资产变更审查（gen5→gen6 间）

唯一提交 343ee29 = acceptance-walkthrough-gen5.md 入库（99 行，走查报告本身），
**零代码资产变更**。测试修复缺口现状复核（与 gen5 一致，无变化）：
- `ticket-lifecycle-scenes.mjs` ensureTestTemporal 仍无 namespace 验真
  （nsDescribe/describeNamespace grep=0）——转人工唯一阻塞项维持缺席；
- `sc_auto_rework_trace.mjs:290` 仍为空过断言 `started.ok !== false`（原形态）。
本票交付物（探针/两场景/夹具/selftest）自 gen5 终局审计后 diff 为零，gen1 实跑
+gen5 审计结论延续有效。

## 怎么验证的（gen6）

| 对象 | 结论 | 证据 |
| --- | --- | --- |
| sc_engine_layout / sc_dsh_probe_selftest | **exit 0 维持绿** | 守卫 39/39；金样本 3 档绿+篡改 7 档逐项红 |
| L1 UT test_t260916_24_dsh_pin.py | **25 passed** | merge 后接线+源码锚维持 |
| 树态 | gen5 后零代码变更 | git diff 1e6f845..HEAD = gen5 报告 99 行唯一；工作区干净 |
| 修复缺口 | 维持缺席（无变化） | grep nsDescribe=0；:290 原形态在树 |
| 本轮机械跑 | **activity 超时（0 跑）** | 「ActivityError: Activity task timed out」——引擎侧 activity 执行层故障，非场景红、非本票面；本轮无机械证据，既有归因链（gen2 仲裁闭环+gen2 实证复跑绿、gen5 归因核对）延续 |

既有归因链快照（六轮累积，均与本票零代码交集）：
- 台面连接层族（console 间歇死亡/21020 事件流）：gen2 仲裁闭环归因 + 我 gen2
  实证 lane-parallel-dom 复跑绿 + 仲裁 gen5 轮本地复跑 lane-parallel-dom 8/8、
  session 族 10/10、charter 产品断言 7 绿后浏览器被关——供给侧间歇，非产品；
- auto-rework-trace：namespace/SA 缺失（场景外前提）+ 空过断言遮蔽（场景内已
  判定、修复未持久落地）——转人工唯一阻塞项；
- 守卫两红（no-skip/naming）：第二次 main merge 带入的 t260917-02 他票资产踩
  守卫（gen4 归因），树未变故延续。

验收清单对照（gen6 终态）：①②③六轮维持满足；④既有场景零回归**本票侧满足**
（本票交付物引发的回归为零）。探针 live 档不入默认跑分面维持。UI 呈现检查项
**不适用**（本票无 UI/泳道图渲染触及，七轮一致）。

## 遗留与风险

1. **置顶（转人工判读项，唯一阻塞，维持）**：共享库 ensureTestTemporal 前提重落
   （namespace 验真+缺席幂等创建+SA 族幂等注册+双验）——仲裁按契约边界不越权，
   交人工；机制结论已实锤：**跨轮只能存活 integration/t260916-24/（本票目录）
   内的改动**，baselines 共享库与他票 sc_* 守卫的修复在机制上不可能由本泳道持久
   落地，必须人工/引擎在共享资产面执行。人审签字前需裁决。
2. **机械跑 activity 超时（本轮新见）**：run_integration_tests 的 activity 执行层
   超时（0 跑）——引擎侧基础设施问题，建议引擎侧核查 activity 超时配置/台面供给
   （与代落盘覆盖面问题同属流程级缺口）。
3. 代落盘覆盖面（维持上报）：历轮测试修复面反复被工作区恢复机制吃掉（gen8 仅带
   walkthrough 1 文件），机制成因建议引擎侧核查。
4. 守卫两红（t260917-02 他票资产）：归属仲裁裁定，merge gate 全绿前需处置。
5. 探针 live 档七轮未实跑——T2 升级门槛时点的人工显式动作；断言 c/e 无离线自检
   覆盖，live 首跑需人工审读输出。

## 收口两问（gen6 终态重答，留痕）

- **doc_sediment**：want=true（七轮一致）。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（主档可观测性家族同构先例：usage 聚合/进度
  心跳）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸是新增引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块需 merge 执行人转正进
  `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾（七轮一致）。实际读过：docs/README.md；主档 §Worker
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
