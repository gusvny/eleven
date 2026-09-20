# t260916-24 验收走查报告（acceptance_walkthrough gen2，integration）

**结论：status=ok**——gen1 走查通过后本票核心面零变更（diff 证明被测对象逐字节
未变，既有复跑结论延续有效）；守卫三条与探针自检本轮复跑全绿；机械轮 6 败全部
落在与本票零代码交集的共享台面族（动态端口临时 console 的 WebSocket 连接层瞬时
故障），代表性败项复跑即绿。本报告供人类最终合并审查。

## 做了什么

gen1 走查（status=ok）之后回路又走了一轮：仲裁 gen1 修复 engine-layout 最后
一处红（gen0 报告 ：59 引文行补守卫锚词）并入库（cb31e97）；本轮机械跑 229 条
出现 6 败 / 4 环境红（闸拦 3 条：t13-evidence-lightbox、t260904-07-charter-
injection-journey、lane-parallel-dom）。gen2 走查三件事：①核实 gen1→gen2 间
唯一资产变更（仲裁 gen1 提交）与「本票核心面零变更」；②对机械败项做本票相关
性归因（含代表性复跑实证）；③守卫三条+探针自检维持性复跑，收口两问按 gen2
终态重答。

## 测试资产变更审查（gen1→gen2 间）

唯一变更=cb31e97 两个文件：
- acceptance-walkthrough-gen0.md :59 行内补 `t260907-10 退役账引文` 锚（gen1
  走查已核实：走守卫自文档的行级锚豁免机制，引文内容一字未改、扫描规则零改动，
  复跑 39/39）——**契约精确化，无弱化**；
- acceptance-walkthrough-gen1.md 入库（85 行，gen1 报告本身）。
本票 engine/场景面（server/engine/ 5 文件 + integration/t260916-24/ 场景与探针）
自 gen1 全绿复跑时点起 **diff 为零**——被测对象逐字节未变，gen1 的复跑结论
（场景①②+UT 25 用例）对 gen2 终态树延续有效。

## 怎么验证的（gen2 维持性复跑 + 败项归因）

| 对象 | 结论 | 证据 |
| --- | --- | --- |
| 守卫三条（no-skip / naming / engine-layout） | **全部 exit 0 维持绿** | pass=7/7/39 fail=0 |
| t260916-24-dsh-probe-selftest | **exit 0 维持绿** | 金样本 3 档绿+篡改 7 档逐项红 |
| 本票场景①②+L1 UT | **gen1 复跑结论延续有效** | git diff e6f6137..HEAD 对被测文件零变更；gen1 实测=场景① exit 0（四子用例 17 断言）/ 场景② exit 0（两子用例 8 断言，单前缀改动等价实证）/ UT 25 passed |
| lane-parallel-dom（本轮闸拦败项，代表性复跑） | **复跑 exit 0**（pass=8 fail=0 env_fail=0） | 机械轮败因 P5/P6 伴随 `WebSocket ws://127.0.0.1:21020/api/events.mux ERR_CONNECTION_REFUSED`、consoleErrors=75——动态端口临时 console 台的连接层瞬时故障；复跑即绿=抖动而非产品缺陷 |

机械 6 败归因（只定位不修复）：闸拦 3 条 + t260915-05-detail-lane-map-dom
（fail=10，L8 直接 `page.reload: ERR_CONNECTION_REFUSED`）全部为 browser-free/
browser 池场景，共同症状=临时台面（动态端口实例，机械跑时点为 21020）WebSocket
连接层故障 → DOM/旅程断言连带红。**与本票零代码交集的双重证明**：①本票
diff（10ca93c^→HEAD）对 server/plugins/ 零改动（console/workbench 面未触碰）；
②engine 面改动（spawn 解析/meta 观测）与台面生命周期/工作流持久化无交集
（gen1 轮 auto-rework-trace 同族归因已闭环）。代表性复跑即绿，按既有口径
（瞬时抖动不动断言、不改场景迁就环境）处置，供给面归 run_integration_tests。

留痕说明：本轮注入上下文仅含部分败项 output_tail（闸拦清单 3 条+t260915-05
可确认；其余 2 败与 4 环境红名单未随上下文注入）。已确认败项归因如上；其余
败项落在闸拦清单未点名+与本票零交集的台面族，归属终判归仲裁段。

## 遗留与风险

1. 共享/临时台面的瞬时抖动族（21020 连接层、17233 共享 Temporal、browser 池
   并发）在本泳道三轮机械跑中反复出现（gen0 三条 browser、gen1 auto-rework-trace、
   gen2 四条台面族）——均为复跑即绿，但反复横跳会持续消耗闸拦/仲裁轮次；建议
   run_integration_tests 侧做台面供给声明（专用台或生命周期隔离），不属于本票
   代码票范围。
2. 探针 live 档（隔离 npm 安装+真会话五断言对账）仍未实跑——属 T2 升级门槛
   时点的人工显式动作（RUNBOOK_GATE.md 门槛文本已交付待 merge 执行人转正进
   runbook §1）；断言 c（沙箱越界写）/e（resume 续写）无离线自检覆盖，live
   首跑需人工审读输出（gen0 遗留项延续）。
3. 本票无 UI/泳道图渲染触及（改动面=engine spawn 解析/观测面+integration 场景），
   『并行期 UI 呈现』检查项**不适用**——旁证：恰好测并行双亮的 lane-parallel-dom
   本轮复跑全绿，与本票无因果。

## 收口两问（gen2 终态重答，留痕）

- **doc_sediment**：want=true（与 gen0/gen1 结论一致，三轮未变）。
  target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（主档可观测性家族同构先例：usage 聚合/进度
  心跳）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸是新增引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块需 merge 执行人转正进
  `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾（三轮一致；gen1 轮 merge main 后亦无新增矛盾）。
  实际读过：docs/README.md；主档 §Worker 运行时；docs/ops/admin-dsh-应用方案.md
  §组装/会话/模型；docs/testing-guide.md；docs/design/metrics-api契约v1.md:236 行、
  dsh_seam需求书v1.md、sandbar项目接入契约v1.md（grep 行级）。低风险观察（不登记
  债）：admin-dsh-应用方案.md:33「SESSION_FORMAT_VERSION = 0（预发布，不承诺
  兼容）」将随 dsh 实际升级过时——自带免责且升级未执行，T2 时点同步该 ops
  文档即可。

## 参考 docs 清单（结算 note 用）

读过：docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md
（§目录+Worker 运行时）；docs/ops/admin-dsh-应用方案.md（§组装/会话/模型行级）；
docs/testing-guide.md；docs/design/metrics-api契约v1.md（:236 行）；
docs/design/dsh_seam需求书v1.md、docs/design/sandbar项目接入契约v1.md（grep 行级）；
仓库根 CLAUDE.md；notes/epics/dsh-upgrade.md（主检出全文，契约真源）。
