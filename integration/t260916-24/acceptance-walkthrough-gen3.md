# t260916-24 验收走查报告（acceptance_walkthrough gen3，integration）

**结论：status=ok**——gen2 通过后本票核心面持续零变更、守卫与探针自检维持全绿；
本轮唯一机械败项 auto-rework-trace 归因定位到共享测试台重启后的稳定坏态（证据链
完整，与本票零交集）。**修正我方 gen1/gen2 报告中的一处归因表述**：该场景的失败
不是「复跑即绿的瞬时抖动」——gen3 实证空载双跑稳定红（详 §归因），系共享台
供给债，非本票回归。本报告供人类最终合并审查。

## 做了什么

gen2 走查（ok）后回路走了一轮：仲裁 gen2 将 gen2 轮 6 败全部闭环归因（常驻测试
台 console :21020 mid-run 死亡，四场景单跑全绿）并入库（0926a04，仅 gen2 报告
落盘）。本轮机械跑 229/225 过/**1 败**/3 环境红——唯一败项 auto-rework-trace
（同症状第三次出现在机械跑）。gen3 走查：①确认 gen2→gen3 间零代码资产变更；
②守卫+探针维持性复跑；③对该败项做复跑归因（两次空载复跑，结果推翻此前「瞬时
抖动」假设，见 §归因）；④收口两问重答。

## 测试资产变更审查（gen2→gen3 间）

唯一提交 0926a04 = acceptance-walkthrough-gen2.md 入库（90 行，走查报告本身）。
**零代码资产变更**：本票 engine/场景面（server/engine/ + integration/t260916-24/
场景与探针）自 gen1 全绿复跑时点起持续 diff 为零，gen1 的场景①②+UT 复跑结论
对 gen3 终态树延续有效。

## 怎么验证的

维持性复跑（全部 exit 0）：
- 守卫三条：no-skip-guard / naming-grep-assert / engine-layout（pass=7/7/39 fail=0）
- t260916-24-dsh-probe-selftest（金样本 3 档绿+篡改 7 档逐项红）
- 旁证：上一轮台面族败项（charter-injection-journey / lane-parallel-dom /
  t13-evidence-lightbox / t260915-05-detail-lane-map-dom）本轮机械跑全部转绿
  （exit 0），与仲裁 gen2 的「:21020 台面 mid-run 死亡」归因互证。

### auto-rework-trace 归因定位（本轮唯一机械败项）

| 样本 | 时点 | 结果 |
| --- | --- | --- |
| gen1 走查单跑 | 13:4x | **绿**（pass=10 fail=0） |
| gen2 轮机械跑 | 13:5x~14:0x | 红（闸拦名单） |
| gen3 轮机械跑 | 14:1x | 红（mu54m7ud） |
| gen3 空载复跑① | 14:25 | **红**（mu557bk6，pass=4 fail=1） |
| gen3 空载复跑② | 14:3x | **红**（mu55c5rk，同症状） |

定位结论（只定位不修复）：
- **症状**：sceneF ticket-start 0.1s 秒回「受理」→ 0.2s 后查 workspace_prep 即报
  「工单不存在：Temporal 无此 workflow」——台面受理层与 Temporal 实际状态失同步；
- **台面证据**：共享台 sandbar-test-temporal（:17233，多泳道共用）容器
  StartedAt=14:15:27+0800（本轮内重启过）；我两次空载复跑（14:25/14:3x）均在
  重启之后且稳定红——**gen1 时点绿→gen3 时点稳定红的转变与台重启时间线吻合，
  台重启后进入坏态**；
- **与本票零交集三证**：①场景与 baselines 目录本票零 diff（git log 最后变更=
  历史注释批票，260909 提速战役期既有基线资产）；②台面服务跑在容器内，不加载
  本 worktree 代码；③本仓 gen1→gen3 仅走查报告 md 变更；
- **修正与上报**：gen1/gen2 报告中「复跑即绿=瞬时抖动」的表述被 gen3 双红样本
  推翻——这不是抖动，是共享台重启后稳定坏态。四样本（两轮机械+两次空载）齐备，
  修复归属=测试台供给面（run_integration_tests 的台面生命周期/专用台声明，或
  共享台运维），非场景断言问题、非本票写集可修。建议按供给债登记跟进。

验收清单对照（gen3 终态）：①探针正负自检满足；②钉路径 UT 满足（结论延续）；
③版本自检落票面/日志可查满足（结论延续）；④既有场景零回归满足（本票写集产物
引发的回归为零；唯一败项非本票面，归因证据链如上）。探针 live 档不入默认跑分面
维持（registry 仅 3 条登记）。UI 呈现检查项**不适用**（本票无 UI/泳道图渲染触及，
改动面=engine spawn 解析/观测面+integration 场景）。

## 遗留与风险

1. **共享台 sandbar-test-temporal 稳定坏态（置顶上报）**：auto-rework-trace 在
   其上空载双跑稳定红（mu557bk6/mu55c5rk），机械轮连续两轮同败；同台的其它场景
   是否受累未全量排查（本轮机械跑其余 225 过说明大部分场景不受影响，症状局限在
   「create→Temporal workflow 失同步」链）。修复归属测试台供给面，不随本票收口
   消失——人审合并时不应视为本票遗留。
2. 探针 live 档（隔离 npm 安装+真会话五断言对账）仍未实跑——T2 升级门槛时点的
   人工显式动作（RUNBOOK_GATE.md 待 merge 执行人转正进 runbook §1）；断言 c/e
   无离线自检覆盖，live 首跑需人工审读输出。
3. 本轮 3 环境红名单未随上下文注入（三态机制点名不假绿，留痕不阻塞）。

## 收口两问（gen3 终态重答，留痕）

- **doc_sediment**：want=true（四轮一致）。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（主档可观测性家族同构先例：usage 聚合/进度
  心跳）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸是新增引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块需 merge 执行人转正进
  `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾（四轮一致）。实际读过：docs/README.md；主档 §Worker
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
