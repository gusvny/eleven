# t260916-24 验收走查报告（acceptance_walkthrough gen0，integration）

**结论：status=failed（打回）**——本票四件核心交付（探针自检 / 钉路径 UT / 两条
engine 场景）实跑全绿且质量达标，但**本票新增文件踩红两条既有守卫场景**
（t260904-12-no-skip-guard、t260907-04-naming-grep-assert，已实跑复现并定位到
文件行级），工单验收④「既有场景零回归」不满足。两处均为小改可修（修法建议见
§归因定位），修复后复跑归零即可收口。

## 做了什么

以用户视角独立走查本票全部交付物（HEAD=10ca93c，24 文件 +2025 行），不预设
机械测试结论：逐场景实跑复验（3 条场景族 + L1 UT + lint）、审读 engine 侧
diff（dsh_pin.py/worker.py/agent_activities.py/shared.py/run_worker.sh）、
对照 epic 接缝矩阵（notes/epics/dsh-upgrade.md 主检出 §接缝矩阵 12 条）核对
T4 应兑的面（#1 文件名 / #2 schema / #3 钉模型 / #4 沙箱 / #5 resume /
#9 钉路径 / #11 回归门槛）、对机械测试 6 败逐条归因定位。

## 怎么验证的（逐场景结论）

| # | 对象 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | sc_t260916_24_dsh_face_meta（engine 池，真 docker 台+真 worker 起跑链） | **PASS exit 0**，17 断言全绿 | 四腿实证：缺省腿（来源=default、cmd 与文档化缺省逐元素等值、version=宿主 `dsh --version` 实测 0.1.1-rc.2=探测非抄配置）；钉路径腿（SANDBAR_AGENT_CMD 指版本桩→来源=env、version=桩自报 9.9.9-stub、二进制解析到桩本体）；预期不符可查腿（expected_state=mismatch 在案且不拦）；探测失败腿（version_state=error 附 detail 点名、不挡启动）。红线：审计账本 0 条（被测子进程零连生产端口） |
| 2 | sc_t260916_24_dsh_expected_loud（engine 池，真工单链） | **PASS exit 0**，8 断言全绿 | 缺省腿=mismatch 时 spawn 照走+create_plan 出结果+日志响亮行同点 actual(9.9.9-stub)/expected(0.1.1-rc.2)；STRICT 硬闸腿=桩 agent 形态调用恒 0（2→2）+硬闸红点名两版本。组合语义「带病跑但喊得出来 / 宁停不悄悄跑错」双向钉死。红线：审计账本 0 条 |
| 3 | t260916-24-dsh-probe-selftest（ro 池） | **PASS exit 0** | 金样本 3 档全绿（v0 全键 / vN 全键+压缩 / vN 无 cacheReadTokens 恰出 WARN=可选键「缺席告警不拦停」语义自锁）；篡改 7 档逐项红且红必命中预期断言名（bad-filename→断言 a / missing-required、cacheread-nonint→断言 b / model-mispin→断言 d / bad-json-line、truncated-half-line、zstd-bad-frame→完整性，KI-059 撕裂族） |
| 4 | L1 UT server/engine/tests/test_t260916_24_dsh_pin.py | **25 passed**（引擎 venv pytest） | 显式路径生效 / 缺省不破现状（与 agent_activities 旧常量逐元素等值）/ 期望三态 / STRICT 硬闸 / 探测失败四态全终态回收 / meta 增列读侧兼容 / 畸形 env 点名 / docker tag 提取 / face 形状+源码锚 |
| 5 | integration/lint_tests.py | **0 error / 0 warn** | 终态复跑 |

验收清单对照：①探针可重跑+正负自检 **满足**；②钉路径 UT（显式生效+缺省不破）
**满足**；③版本自检落票面/日志可查 **满足**（真启动链 meta `dsh` 键四腿 + 真票链
日志响亮行实证；票面 `dsh_pin_<tag>.json` 由 UT 源码锚防接线漂移，见遗留 3）；
④既有场景零回归 **不满足**（§归因定位）。探针 live 档不入默认跑分面 **满足**
（registry 仅登记 3 条，live 探针无 sc_ 前缀不入册，diff 核实 run_scenarios.py
增量=纯登记零执行逻辑）。

## 测试资产变更审查

- 本段=acceptance_walkthrough **gen0（首进）**，无打回轮次可对照；
- 本票测试资产（场景①②、共享夹具 lib_t26091624.py、探针、UT）与前段
  design_integration_tests gen1 交接一致：实跑断言数 17/8 与交接记录吻合，
  场景关键结构（agent_rows 形态过滤、审计账本终局断言、STRICT 腿「不设
  snapshot 不可达观测」闸挂点注记）逐项在位，无 implement 收尾写入冲掉、
  无绿灯捷径式弱化；
- 场景断言全部锚公开产物（meta JSON / 进程终态 / 桩调用账本 / 日志字面量同现），
  字段拼写不锁（KI-051 语义锚），符合灰盒纪律——契约不变的重构不会误伤。

## 归因定位（机械测试 6 败逐条，只定位不修复）

1. **t260904-12-no-skip-guard：本票引入**。实跑复现 exit 1（fail=1）。残留 5 处
   全在 `integration/t260916-24/probe_dsh_seam.py`（行 435/448/462/666/671 的
   `skip_install` / `--skip-install` 字面），踩「integration/ 树 SKIP/skip 零残留」
   守卫。修法建议：参数改名 `--reuse-install`（语义更精确——该参数实为「复用已装
   前缀」，安装核验照跑，"skip" 名不副实），连带 selftest/live 调用点与 README 段。
2. **t260907-04-naming-grep-assert：本票引入**。实跑复现 exit 1（fail=1）。
   `integration/t260916-24/sc_t260916_24_dsh_expected_loud.py:88` 的
   `suyou-ticket-%s` 旧队列前缀缺 `# naming-compat` 行尾标记；先例
   （t260908-01/lib_ki061.py:107、t260905-02 三处）全带标记，本票漏带。修法：
   行尾补 `# naming-compat`（该双前缀队列系沿 t260905-10 既有契约，非新用旧名）。
3. **t260907-10-engine-layout：非本票**。失败点
   `integration/t260916-02/lib_relocation.py:147`（旧路径 `server/dsh/temporal-poc`，t260907-10 退役账引文）
   残留），该文件属 t260916-02 票（1adbb72 收口），本票未动；本票 fixtures 二进制
   文件仅 INFO 列出不判红。归属待仲裁裁定，非本票写集可修。
4. **ticket-session-restore / t260904-05-top-entry-retired-form /
   t260904-05-session-lifecycle-ui（3 条 browser）：与本票零代码交集**。本票
   HEAD 改动面=server/engine/ 5 文件 + integration/t260916-24/ + run_scenarios.py
   （纯登记）+ README（文档），未触碰 console/workbench/plugins 面；三条场景消费
   的服务端/浏览器面均不在本票 diff 内。归因：main 基线债或 browser 环境类，
   待仲裁归属，非本票引入（writer 型场景涉生产 console 共享面，走查未重跑复现，
   依据 diff 交集归零判定）。

## 遗留与风险

1. 探针断言 c（沙箱不变量）/ e（resume）为 live 档专属，selftest 不覆盖这两支
   断言器（已审读 live 主体：probe_live 行 494/508 真实调用，判定逻辑=文件存在性
   与会话文件集集合差，逻辑简单）；live 档首次人工调用（升级门槛）时需人工审读
   输出——本段未实跑 live（需网络+npm+真凭据，且属升级执行时点的门槛动作）。
2. 探针 live 档的五断言对账（矩阵 #2 cacheReadTokens 开放问号等）待 T2 前按
   RUNBOOK_GATE.md 显式调用，本段无法代跑。
3. 票面 `artifacts/dsh_pin_<tag>.json` 的真票链落盘未被场景直接断言（场景②真票
   链上 spawn 发生但断言锚日志行 + 桩账本；UT ⑨源码锚防接线漂移）。低风险：
   写失败本就 best-effort 不挡 spawn，观测主面（meta+日志）已场景实证。
4. 两条守卫红修复后须复跑 `sc_no_skip_guard.py` 与 `sc_naming_grep_assert.py`
   归零，并连同 3 条 browser 败项在仲裁归属后收敛——engine 池场景本段已实跑
   （机械测试轮跳过池=engine、exclusive）。
5. 本票无 UI/泳道图渲染触及（改动面=engine spawn 解析/观测面 + integration 场景），
   『并行期 UI 呈现』检查项**不适用**。

## 收口两问（留痕）

- **doc_sediment**：want=true。建议 target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  增「可观测性：dsh 版本面」小节（该主档可观测性家族已有 usage 聚合 / 进度心跳
  同构小节先例）。reason：四旋钮 env 契约（SANDBAR_AGENT_CMD / SANDBAR_AGENT_IMAGE /
  SANDBAR_DSH_EXPECTED_VERSION / SANDBAR_DSH_STRICT，缺省=现行为）+ worker meta
  `dsh` 键 + 票面 `dsh_pin_<tag>.json` + STRICT 硬闸语义，是新增的引擎公开行为契约，
  T2 升级执行直接消费；另 RUNBOOK_GATE.md 门槛块（写集外交接件）需 merge 执行人
  转正进 `notes/discussions/260916-dsh-upgrade-runbook.md` §1。
- **doc_conflicts**：无矛盾。实际读过：docs/README.md；主档 §Worker 运行时（372-408
  行，不含 spawn 命令解析细节，本票纯增量观测不推翻）；docs/ops/admin-dsh-应用方案.md
  §组装/会话/模型；docs/testing-guide.md；docs/design/metrics-api契约v1.md:236 行、
  dsh_seam需求书v1.md、sandbar项目接入契约v1.md（grep 行级核对 DSH_HOME/session
  文件名主张）。低风险观察（不构成矛盾、不登记债）：admin-dsh-应用方案.md:33
  「SESSION_FORMAT_VERSION = 0（预发布，不承诺兼容）」将随 dsh 实际升级过时——该句
  自带免责且升级未执行（T2 时点），T2 执行时同步该 ops 文档即可。

## 参考 docs 清单（结算 note 用）

读过：docs/README.md；docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md
（§目录+Worker 运行时）；docs/ops/admin-dsh-应用方案.md（§组装/会话/模型行级）；
docs/testing-guide.md；docs/design/metrics-api契约v1.md（:236 行）；docs/design/dsh_seam需求书v1.md、
docs/design/sandbar项目接入契约v1.md（grep 行级）；仓库根 CLAUDE.md；
notes/epics/dsh-upgrade.md（主检出全文，契约真源）；
notes/discussions/260916-dsh-upgrade-runbook.md 未读（交接件落点，由 merge 执行人落笔）。
