#!/usr/bin/env python3
"""integration 场景执行器（manifest 退役后的项目声明道）。

约定：
- SCENARIOS = (name, intent, cmd[, pool]) 三元组或四元组——intent 是该场景守护的用户可
  感知行为/合同；pool 可选："main"（缺省，串行主池）/命名池（如 "ro" 只读并行池，
  与主池并行）/"exclusive"（独占全程）。同池串行保顺序，跨池并行提吞吐
  （评审一眼可见；intent 级重复禁止，步骤级共享允许）。
- 层次：单组件函数测试归 UT（temporal-poc/tests pytest、workbench/tests node 源级）；
  本清单只收跨组件场景、对外合同冻结、用户旅程与故障面对抗。
- 命名铁律：场景案例文件一律 sc_<slug>.py/.mjs——凡 sc_ 必须登记本清单，
  凡未登记的 sc_ = 孤儿（lint L5 红）；不带 sc_ 前缀的文件 = 共享/子检查代码，
  不登记、不报警（t260902 宿主令：约定胜过推断）。
- 一次性交付验收快照不入场（交付完成使命即终，t260902 宿主令重审定案）。
- cmd 以仓库根为 cwd、/bin/sh -c 执行，单条超时 900s；只用标准库。
"""
import subprocess
import sys
import time

SCENARIOS = [
    ("ticket-validate",
     "--- empty write set / explicit declaration --- rejects([], False, '写集为空', 'empty write s",
     "node integration/baselines/sc_ticket_validate.mjs"),
    ("retention",
     "Test-env only: try to idempotently bring up the Docker test env (never do this // agains",
     "node integration/baselines/sc_retention.mjs", "ro"),
    ("ticket-session-restore",
     "ticket-session 面双半契约（t260831-08 起；browser 半被 t260903-07 反转）：服务端 POST ticket-session/open 保留 find-or-create（session_id=ticket-<id>、created 旗标、重开不重复）与畸形 id/缺 project/未知 project/不存在工单显式 4xx；浏览器半=点工单行中列详情照常开、右栏 chat 零切换（快照零注入、phase 不变、多行点击零 churn）",
     "node integration/baselines/sc_ticket_session_restore.mjs"),
    ("ticket-evidence-images",
     "(black-box, user perspective): // QA screenshots (.suyou/screenshots/*.png in the lane) ",
     "node integration/baselines/sc_ticket_evidence_images.mjs"),
    ("ticket-lifecycle",
     "The env half itself follows the triad verdict of the real (saved) env value. const guard",
     "node integration/baselines/sc_ticket_lifecycle.mjs"),
    ("session-top-entry",
     "(black-box, user perspective): // Production defect triad after t260831-02: // 1. MRU li",
     "node integration/baselines/sc_session_top_entry.mjs"),
    ("sandbar-contract-v1",
     "Strategy item must name both policy files with their roles. const strat = extractSection",
     "node integration/baselines/sc_sandbar_contract_v1.mjs", "ro"),
    ("sandbar-dsh-compat",
     "(doc-guard, t260903-08): 契约 v1.7 ⑧节 dsh 兼容区间/四条升版必查项/版本自报口径在场，"
     "交接单取舍清单覆盖 R1 关键词+V1 真孤儿优先级+3099 六词禁词表——"
     "⑧节是安装器 upgrade/doctor 探针的机器消费面，缺失=消费方展示假区间/升版复扫漏项",
     "node integration/baselines/sc_sandbar_dsh_compat.mjs", "ro"),
    ("session-tab-interactions",
     "(black-box, user perspective) — the ticket's three complaints: // 1. Clicking a tab move",
     "node integration/baselines/sc_session_tab_interactions.mjs", "browser"),
    ("capture-lane-preset",
     "capture-lane-preset.mjs —— 隔离台 preset 物化基线（t260901-02）。 // // 断言 server/dsh/ui-check/cap",
     "node integration/baselines/sc_capture_lane_preset.mjs", "browser"),
    ("ui-evidence-failure-retention",
     "显式钉死候选环境：单直连候选（假 capture.mjs 秒退 3）+ 死端口 + 临时归档目录。",
     "PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/baselines/sc_ui_evidence_failure_retention.py", "browser"),
    ("capture-chat-e2e",
     "(black-box, user perspective): // t260901-02 acceptance walk found the capture evidence ",
     "node integration/baselines/sc_capture_chat_e2e.mjs", "browser"),
    ("capture-chat-active",
     "（黑盒，用户视角）： // t260901-02 验收走查实证：隔离台端到端实跑 chat 视图 25s 内未出现 // data-phase=active，capture 退",
     "node integration/baselines/sc_capture_chat_active.mjs", "browser"),
    ("capture-redline-gate",
     "(black-box, user perspective): // The capture evidence tool may create sessions and SEND",
     "node integration/baselines/sc_capture_redline_gate.mjs", "browser"),
    ("check-auto-rework-trace",
     "从源码解析模块级常量：PHASE_MAIN_CHAIN（frozenset）→ set； PHASE_MAIN_ROLES（Dict）→ dict。解析失败返回 None。",
     "python3 integration/sc_check_auto_rework_trace.py"),
    ("auto-rework-trace",
     "---- A1: 五个自动打回场景，各产一条横幅可见记录（用户视角主契约） ---- scenarios = [ ('acceptance', 'implement', '验收",
     "node integration/baselines/sc_auto_rework_trace.mjs"),
    ("t13-evidence-lightbox",
     "(black-box, user perspective): 工单详情抽屉的截图证据缩略图网格 // (t260831-08) 现在支持看图灯箱。用户可感知契约（以 t2609",
     "node integration/t260901-13/sc_evidence_lightbox_dom.mjs", "browser"),
    ("lane-parallel-dom",
     "(black-box, user perspective): t260901-05 shipped the lane diagram's // parallel-fork re",
     "node integration/baselines/sc_lane_parallel_dom.mjs", "browser"),
    ("metrics-contract-doc-structure",
     "t260901-11 M0 集成测试：契约文档存在性与结构（黑盒文档基线） // 验收对象：docs/design/metrics-api契约v1.md // - 存在、fro",
     "node integration/baselines/sc_metrics_contract_doc_structure.mjs", "ro"),
    ("metrics-contract-schema-sync",
     "t260901-11 M0 集成测试：两文档 schema/枚举冻结同步（防各说各话） // 验收对象： // 1. 契约文档缓存 schema 行与 UI 规划 §6 sch",
     "node integration/baselines/sc_metrics_contract_schema_sync.mjs", "ro"),
    ("metrics-contract-api-freeze",
     "t260901-11 M0 集成测试：/metrics API 契约冻结面（请求/响应/错误/双前门） // 验收对象：契约文档中冻结的请求参数、响应字段、错误与降级行为、字节",
     "node integration/baselines/sc_metrics_contract_api_freeze.mjs", "ro"),
    ("metrics-contract-criteria-faultmodes",
     "t260901-11 M0 集成测试：口径钉死与故障面（review 三轮收敛成果的回归守卫） // 验收对象： // 1. 三维口径（时间/交付/token）各有真源与已知近",
     "node integration/baselines/sc_metrics_contract_criteria_faultmodes.mjs", "ro"),
    ("t19-cache-probe",
     "!/usr/bin/env python3 '''t260901-19 T4: cache_probe tool (plan v3 item 1, read-only inve",
     "python3 integration/t260901-19/sc_t04_cache_probe.py"),
    ("multi-tab-coexistence",
     "(black-box, user perspective): the ticket workbench is used with // MULTIPLE console tab",
     "node integration/baselines/sc_multi_tab_coexistence.mjs", "browser"),
    ("t16-settle-lane-anchoring",
     "!/usr/bin/env python3 '''T06 settle_lane 路径锚定修正锁（t260901-16 arbitrate 打回主修项）。 用户视角：并行分叉票",
     "python3 integration/t260901-16/sc_t06_settle_lane_anchoring.py"),
    ("t18-whitelist-caliber",
     "!/usr/bin/env bash # 工单 t260901-18 合并闸白名单口径热修（KI-010 解锁）—— 集成测试集 # 黑盒视角：用户可感知的行为变化 = 泳道并",
     "bash integration/t260901-18/sc_check.sh t01-whitelist-caliber"),
    ("t18-literal-main-hazard",
     "!/usr/bin/env bash # 工单 t260901-18 合并闸白名单口径热修（KI-010 解锁）—— 集成测试集 # 黑盒视角：用户可感知的行为变化 = 泳道并",
     "bash integration/t260901-18/sc_check.sh t02-literal-main-hazard"),
    ("t18-mergecheck-wiring",
     "!/usr/bin/env bash # 工单 t260901-18 合并闸白名单口径热修（KI-010 解锁）—— 集成测试集 # 黑盒视角：用户可感知的行为变化 = 泳道并",
     "bash integration/t260901-18/sc_check.sh t03-mergecheck-wiring"),
    ("t18-mergecheck-failclosed",
     "!/usr/bin/env bash # 工单 t260901-18 合并闸白名单口径热修（KI-010 解锁）—— 集成测试集 # 黑盒视角：用户可感知的行为变化 = 泳道并",
     "bash integration/t260901-18/sc_check.sh t04-mergecheck-failclosed"),
    ("t260901-20-metrics-m1a",
     "单元层（stub 缝，秒级，覆盖聚合口径/缓存语义/归窗口径/双前门稳定性） 't01_params_cache.mjs', 't02_aggregate.mjs', 't03",
     "node integration/t260901-20/sc_t06_all.mjs"),
    ("t23-yaml-chain-truth",
     "选定解释器能否 import temporalio（生成器导入 TEMPLATE_CLASSES 的前提）。",
     "python3 integration/t260901-23/sc_t04_yaml_chain_truth.py"),
    ("t260901-24-fixture-pack",
     "attempts 语义（lane-states 规则 4）：results 有记录则该步 attempts ≥ 1—— // 双并行步必须无 results 记录，否则 run",
     "node integration/t260901-24/sc_t01_fixture_pack.mjs"),
    ("t260901-24-load-fixtures-malformed",
     "F1 缺目录 let r = await tryLoad(join(tmp, 'no-such-dir')) ok(r.threw !== undefined, 'F1 缺目录",
     "node integration/t260901-24/sc_t02_load_fixtures_malformed.mjs"),
    ("t260901-24-route-decision",
     "路径相近但非 wf 端点不误吞 ok(!!callDecide('GET', BASE + '/suyou-workbench/other/tickets')?.passthr",
     "node integration/t260901-24/sc_t03_route_decision.mjs"),
    ("t260901-24-gate-interlock",
     "本树 ui-check 缺 playwright-core 时镜像 capture-lane 的回退：主树 ui-check // （worktree 布局 <main>/.w",
     "node integration/t260901-24/sc_t04_gate_interlock.mjs"),
    ("t21-creds-source-js",
     "!/usr/bin/env node /** * t260901-21 t03 —— creds-source.mjs（ui-check 凭据源解析）镜像用例。 * * 与 t",
     "node integration/t260901-21/sc_t03_creds_source_helper.mjs"),
    ("t21-creds-parity-py-mjs",
     "tmp env 桩：进入时 SANDBAR_PROJECTS_DIR/DSH_HOME/HOME 全指临时目录，退出恢复。",
     "python3 integration/t260901-21/sc_i01_parity_py_vs_mjs.py"),
    ("t21-creds-ui-check-wiring",
     "!/usr/bin/env node /** * i03 —— 控制台截图台链路接线 + JS helper 行为冒烟（t260901-21）。 * * 用户场景：UI 检查台",
     "node integration/t260901-21/sc_i03_ui_check_wiring.mjs"),
    ("t22-t260901-22-approve-modal-ui",
     "* * integration/t260901-22/t02_approve_modal_ui.mjs * —— KI-004「approve 弹层自由备注」用户可感知 UI ",
     "node integration/t260901-22/sc_t02_approve_modal_ui.mjs", "browser"),
    ("t22-t260901-22-approve-modal-faultmodes",
     "本 UI 家族（wb-modal）无 Esc/外点关闭处理器（rework 打回弹层同样只有「确认/取消」 // 两条真实关闭路径）——验收口径改为：每一处 setApprov",
     "node integration/t260901-22/sc_t03_approve_modal_faultmodes.mjs", "browser"),
    ("t260902-01-metrics-m2a-it",
     "* * t260902-01 i_all: integration aggregate entry (t06_all form). * * Runs i01 (API 消费面,",
     "node integration/t260902-01/sc_i_all.mjs"),
    ("t260902-05-t02-views-open",
     "---- A+B+C. 三 view 信封与数据前提 { console.log('A. delivery/token/time 三数据视图信封与一致性') const dep",
     "node integration/t260902-05/sc_t02_views_open.mjs"),
    ("t260902-05-t04-token-reconciliation",
     "票不得带非空 worktree（resolveSuyouBaseDir 优先 worktree 且 repo=/stub-repo 下不存在）； // workspace.ty",
     "node integration/t260902-05/sc_t04_token_reconciliation.mjs"),
    ("t260902-05-t05-cold-start",
     "---- A. 正确性不变 { console.log('A. 冷缓存聚合正确性（8 票）') const deps = makeDeps(eightTicketStub())",
     "node integration/t260902-05/sc_t05_cold_start.mjs"),
    ("t260902-05-t06-ui-build-gate",
     "* * t260902-05 t06 —— 用户反馈①②「入口位置 / 中 pane 化」构建产物黑盒门。 * * 用户场景：①「📊 度量」入口出现在出厂侧栏最底一排（与 ds",
     "node integration/t260902-05/sc_t06_ui_build_gate.mjs"),
    ("t02-t260902-02-archive-ticket",
     "桩下 activity 是裸函数；真 temporalio 下是 ActivityDefinition(.fn)。",
     "python3 integration/t260902-02/sc_t02_archive_ticket.py"),
    ("t02-t260902-02-merge-teardown",
     "tmp 真 git 仓库：main 一提交 + lane 分支一提交 + worktree 挂出。",
     "python3 integration/t260902-02/sc_t03_merge_teardown.py"),
    ("t02-t260902-02-prune-archive-legacy",
     "!/usr/bin/env python3 '''t04 —— ticket-prune / ticket-archive-legacy（Temporal 回归运行态的清理面）",
     "python3 integration/t260902-02/sc_t04_prune_archive_legacy.py"),
    ("t02-t260902-02-archive-layout",
     "-*- coding: utf-8 -*- '''t260902-02 t01 —— 完结工单归档落位与 archive.json manifest 契约。 用户故事：dev-",
     "python3 integration/t260902-02/sc_t01_archive_layout.py"),
    ("t02-t260902-02-fail-closed-idempotent",
     "-*- coding: utf-8 -*- '''t260902-02 t03 —— 归档 fail-closed 两态 + 坏 JSON 字节级归档 + 会话缺失软处理。 用",
     "python3 integration/t260902-02/sc_t03_fail_closed_idempotent.py"),
    ("t02-t260902-02-teardown-versioning",
     "-*- coding: utf-8 -*- '''t260902-02 t04 —— 收口三段化与 defer_teardown 版本化契约。 用户故事（升级安全）：本单把「m",
     "python3 integration/t260902-02/sc_t04_teardown_versioning.py"),
    ("t02-t260902-02-prune-e2e",
     "client.py 末行 JSON 回执；解析失败 = FAIL。",
     "python3 integration/t260902-02/sc_t05_prune_e2e.py"),
    ("t02-t260902-02-archive-legacy-e2e",
     "注入缝直调真命令逻辑（活文件系统，零 Temporal server 依赖）。",
     "python3 integration/t260902-02/sc_t06_archive_legacy_e2e.py"),
    ("t07-t260902-07-credential-probe",
     "!/usr/bin/env python3 '''t260902-07 集成测试 ③：凭据 seam 与远端探针（前置条件 + 可选外呼）。 - 前置：~/.dsh/setti",
     "python3 integration/t260902-07/tests/sc_test_credential_probe.py"),
    ("t09-t260902-09-creds-merge-blackbox",
     "子进程模式：sys.modules 塞 None 模拟 PyYAML 软依赖缺失， 断言合法 dst+src 降级 no-op（不抛错、dst 字节原样）。",
     "PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260902-09/sc_it01_creds_merge_blackbox.py"),
    ("t09-t260902-09-spawn-creds-refresh",
     "以 fixture 泳道为 cwd 跑 spawn 准备（role 空 = 不触角色 patch/会话延续）。",
     "PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260902-09/sc_it02_spawn_creds_refresh.py"),
    ("scenario-guard-spec-landed",
     "spec 四条修订与 FLOW_BRIEF 条款防悄悄回退（合并守卫）",
     "python3 integration/sc_scenarios_guard_spec.py"),
    ("scenario-guard-pipeline-landed",
     "UT 工序与 verify test 道落地防回退（合并守卫）",
     "python3 integration/sc_scenarios_guard_pipeline.py"),
    ("scenario-guard-doc-drift",
     "文档/链路与代码真源漂移检测（合并守卫）",
     "python3 integration/sc_scenarios_guard_drift.py", "ro"),
    ("t11-format-args-pairing",
     "仲裁日志渲染：格式化参数与占位配对不丢不错（KI-013 修复的行为面）",
     "python3 integration/t260902-11/sc_t01_format_args_pairing.py"),
    ("t11-arbitrate-log-renders",
     "仲裁日志端到端可渲染：三条核心链路日志结构完整",
     "python3 integration/t260902-11/sc_t02_arbitrate_log_renders.py"),
    ("t11-log-faultsurface",
     "日志故障面：异常路径日志不静默、可定位（cwd 修复的行为面）",
     "python3 integration/t260902-11/sc_t03_log_faultsurface.py"),
    ("t260903-02-fork-contract",
     "泳道提速②并行分叉契约：分叉边名必须是 STAGES id（防未知步骤卡死，t260901-04 同款）；单点 settle 先于 verdict 判定（tests-fault 测试集改动先落账再重跑）；非 pass 作废走查有留痕",
     "python3 integration/t260903-02/sc_fork_contract.py", "ro"),
    ("t260903-02-conditional-contract",
     "泳道提速③附条件放行契约：FLOW_BRIEF 三态词表与解析正则同源且带负向断言；附条件意见直通 implement 前缀在场且拼接 report；plan_rounds 计数点恰 1 处（只 reject）；打回环与超限 blocked 文案保留；纯函数真接线",
     "python3 integration/t260903-02/sc_conditional_contract.py", "ro"),
    ("t260903-02-lock-update-integrity",
     "两把已登记精确锁随 arb_acc_parallel 新键同步且不弱化：py EXPECT 恰 13 键含新键、total_calls==7；mjs len==13、findall==8、旧字面退场、键集合动态比对保留",
     "python3 integration/t260903-02/sc_lock_update_integrity.py", "ro"),
    ("contract-v11-onboarding",
     "下一个项目接入全旅程：照契约 ②a~②e 写最小 verify.yaml（列表命令制 checks 含 cwd/timeout、integration.cmd 三行协议桩），admin.py call 真入口双道绿且返回形状逐键符合 ②b-(b)；越界写红并点名；场景失败 exit 透传（t260903-01）",
     "node integration/t260903-01/sc_contract_v11_onboarding.mjs"),
    ("contract-v11-integ-protocol",
     "integ 道输出契约对抗面：畸形 FAIL 行 fallback（name=整行 exit=-1）、汇总行与明细矛盾不判红（参考行不读）、仅汇总行=零场景绿、err 态键集无 red_count/checks 泄漏（t260903-01 ②b-(a)）",
     "node integration/t260903-01/sc_contract_v11_integ_protocol.mjs", "ro"),
    ("contract-v11-checks-exec",
     "code 道 checks 列表命令制执行语义（全仓此前零覆盖：既有用例全 skip_slow）：id 命名、cwd 相对声明根、exit 码判红、timeout 到点判红且进程回收、skip_slow 跳过全部命令检查（t260903-01 ②a/②d）",
     "node integration/t260903-01/sc_contract_v11_checks_exec.mjs", "ro"),
    ("contract-v11-regression-rods",
     "本票勘误回归棒（KI-020① 同族「真源文件自身漂移」）：verify_lane.py 幻影/退役措辞零残留、契约文档 F1（integration 道无关闭态+零场景绿惯用法）与 F2（汇总行参考性）语义明文、verify.yaml 头注指向 ②a~②e；实现落地前红=预期（t260903-01）",
     "node integration/t260903-01/sc_contract_v11_regression_rods.mjs", "ro"),
    ("t260903-03-paths-spawn-seam",
     "路径契约化端到端（跨组件：注册条目×路径解析×spawn 组装×patch 产物，观测=cmd --patch 链与 patch 文件内容）：声明命中用声明值（roles patch 指声明目录、模型来自声明表，声明优先于现行约定）；未声明四回落态（无 paths 节/条目不存在/key 空/key 非法含穿越形状）与现行约定等价、模型走回落常量单源；锚点在内容缺走软语义不红（t260903-03 ①d 用户旅程）",
     "PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260903-03/sc_paths_spawn_seam.py"),
    ("t260903-03-paths-failclosed-red",
     "路径契约化故障面对抗（spawn 缝隙红传导，用户视角=红工单点名文件而非静默猜着跑）：条目 project.yaml 损坏（现行约定在位也必须红，不静默回落）、声明锚点缺失（不被 per-role 软跳过吞掉）、锚点类型错位（表↔目录/目录↔文件）、声明值畸形代表例（未知键/绝对路径/../穿越）一律红且文案点名键或解析后路径（t260903-03 ①d 三态）",
     "PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260903-03/sc_paths_failclosed_red.py", "ro"),
    ("t260903-03-paths-contract-doc-guard",
     "契约 ①d/v1.6 落地防漂移（对外合同冻结）：①d 两键声明、条目文件畸形 fail-closed 不回落、装载器放开前生效前提过渡句、锚点/内容软语义、声明表内容损坏容错边界、空白值 strip 口径（t260903-03）",
     "python3 integration/t260903-03/sc_paths_contract_doc_guard.py", "ro"),
    ("t260903-04-parallel-stages-meta",
     "并行期快照 meta.parallel_stages 生命周期契约（KI-024①引擎半）：两分叉段写入与汇合清空在案、单 stage 字段保留向后兼容；纯函数行为=词表内写入/词表外与非字符串清洗/去重/空列表删键/幂等（t260903-04）",
     "python3 integration/t260903-04/sc_t01_parallel_stages_meta.py", "ro"),
    ("t260903-04-parallel-ui-truth",
     "工单台并行双显真源优先契约（KI-024①UI 半）：meta.parallel_stages 非空即真值双显且纠 timeline 启发式误判面（fallback=false 守「并行分叉中」文案）、缺失/空/全畸形回落现口径、旧票单值指针零回归（t260903-04）",
     "node integration/t260903-04/sc_t02_parallel_ui_truth.mjs", "ro"),
    ("t260903-04-live-round-freshness",
     "动态流静默窗新鲜度契约（KI-024②）：每个 step/start 与 LLM 重试各出一行、🔧 工具行回归不破、静默窗整链（spawn→首句）不再零行、坏行与流式块不上屏、会话缺失 exists:false 人话降级（t260903-04）",
     "node integration/t260903-04/sc_t03_live_round_freshness.mjs", "ro"),
    ("t260903-04-client-bundle-sync",
     "工单台 shipped bundle 与 src/client 源码同步守卫：lib/client.js≡client.cjs 双产物一致、契约特征词（parallel_stages 等）在用户实际被服务的产物内在案——改 src 忘重建 tsdown 时源码层全绿而真台面仍旧行为的静默穿透面（t260903-04 arbitrate，t260901-22 同族事故常驻化）",
     "node integration/t260903-04/sc_t04_client_bundle_sync.mjs", "ro"),
    ("t260903-07-click-no-chat-switch",
     "点工单不切右侧会话（t260903-07①核心反转）：点工单行后中列详情照常开（.wb-d2-steps 在场）、右栏 chat 零变化——【工单上下文】快照零注入、data-phase 不变、会话顶入口不出现 ticket- 行；多行重复点击零注入零 churn（旧契约「点行→开 ticket- 会话」的显式反转守卫，防联动复活）",
     "node integration/t260903-07/sc_t01_click_no_chat_switch.mjs", "browser"),
    ("t260903-07-chat-project-tag",
     "全局 chat 用户消息项目 tag 契约（t260903-07②）：引用真实工单 id 的消息行渲染文本=注册项目 key 的 chip（颜色非空）；同项目恒同色、不同项目不同色、页面重载后同色（确定性映射的用户可感知面）；全部 chip 文本 ∈ 注册项目键不造假 key；「归属不了→不渲染」是 env 相关声明行为、不在场景层强断言（L1 DOM 桩已锁，chip 经 ::before 伪元素渲染故断言走 getComputedStyle）",
     "node integration/t260903-07/sc_t02_chat_project_tag.mjs", "browser"),
    ("t260903-05-manifest-structure",
     "M2-A 仓界盘点清单结构完整性（黑盒文档基线，用户验收口径）：四章齐备（①文件级引擎构成/②双向依赖/③仓外触点/④风险表）、关键边界文件点名、条目带 文件:行 锚点、3099 显式禁碰、历史处理三选项各写明倾向、端口 7233/8233 随迁、在跑工单过渡口径；清单缺失=FAIL 不 SKIP（t260903-05 交付物）",
     "python3 integration/t260903-05/sc_manifest_structure.py", "ro"),
    ("t260903-05-manifest-coverage",
     "盘点覆盖面无悬空（全枚举口径，review 意见 2）：find 全枚举 server/ 受控文件逐一被清单点名（无未判定遗留）、「未判定」只许否定式出现、M0 债务 H1-H12 与接触面 A/B/C/D 全部有归宿映射（t260903-05）",
     "python3 integration/t260903-05/sc_manifest_coverage.py", "ro"),
    ("t260903-05-manifest-deps",
     "②依赖图权威性对抗（实机 grep 反向核对文档，review 意见 1 口径）：引擎代码面对仓内路径/仓外触点的每处残余引用宿主文件均须在清单登记（随迁/改声明/收口三选一），白名单不由测试硬编码、以清单自身登记为准；H2/H3 回落常量宿主文件显式在册（t260903-05）",
     "python3 integration/t260903-05/sc_manifest_deps.py", "ro"),
    ("t260903-06-query-kind-no-lie",
     "查询谎报面全链回归（KI-025）：阶段切换窗查询失败时，从 Temporal 抖动经 client.py→ticket.py→tools_registry 的完整回执链路绝不把瞬时/终态/畸形故障文案成「工单不存在」；「不存在」仅由 NotFoundFailure 语义产出；终态票不诱导重试；kind 随分级异常跨层存活、缺 kind 回执绝不产 not_found（t260903-06）",
     "python3 -B integration/t260903-06/sc_query_kind_no_lie.py", "ro"),
    ("t260903-06-ui-poll-degrade",
     "台面轮询降级旅程（KI-003/需求③）：5s 轮询连败 1、2 次静默窗节拍不变、第 3 次连败才退 30s 慢轮询、成功即清零回常规、not_found/terminal 语义短路不进重试循环、成功打断后重新计数、畸形 outcome 不崩（t260903-06）",
     "node integration/t260903-06/sc_ui_poll_degrade.mjs", "ro"),
    ("t260903-06-no-lie-404-guard",
     "工作台面谎报文案静态守卫（KI-025 UI 半）：node.ts 事故文案「工单不存在或读取失败」零残留、kind 分流辅助在位——谎报 404 不得重生（t260903-06）",
     "node integration/t260903-06/sc_no_lie_404_guard.mjs", "ro"),
]

CMD_TIMEOUT = 900


def _run_entry(entry):
    """跑单条场景（cmd=/bin/sh -c，cwd=仓库根）。返回 (name, exit_code, tail)。"""
    name, cmd = entry[0], entry[2]
    try:
        proc = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True,
                              text=True, timeout=CMD_TIMEOUT)
        return name, proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
    except subprocess.TimeoutExpired:
        return name, -9, "超时（>%ds）" % CMD_TIMEOUT


def main() -> int:
    """分池执行（宿主令 t260902 并发分池）：条目可带可选第四元素——
    None/缺省 = "main" 池；"ro"/其他字符串 = 命名池；"exclusive" = 独占（先单独跑）。
    池间并行、池内严格串行（保顺序与可复现）；输出契约不变（PASS/FAIL 行+缩进尾段+
    末行汇总），跨池顺序可交错——引擎/工具逐行解析，不在乎顺序。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ran = passed = failed = 0
    t0 = time.time()
    lock = threading.Lock()
    pools, exclusives = {}, []
    for e in SCENARIOS:
        opt = e[3] if len(e) > 3 else None
        if opt == "exclusive":
            exclusives.append(e)
        else:
            pools.setdefault(opt or "main", []).append(e)

    def _drain(entries):
        nonlocal ran, passed, failed
        for e in entries:
            name, exit_code, tail_out = _run_entry(e)
            block = (["PASS [%s]" % name] if exit_code == 0
                     else ["FAIL [%s] exit=%d" % (name, exit_code)]
                     + ["    " + ln for ln in tail_out.splitlines()[-6:]])
            with lock:
                ran += 1
                passed += (exit_code == 0)
                failed += (exit_code != 0)
                print("\n".join(block), flush=True)

    for e in exclusives:      # 独占项先行，不与任何池重叠
        _drain([e])
    with ThreadPoolExecutor(max_workers=max(1, len(pools))) as ex:
        for f in [ex.submit(_drain, v) for v in pools.values()]:
            f.result()
    print("SCENARIOS ran=%d pass=%d fail=%d (%.0fs)" % (ran, passed, failed, time.time() - t0),
          flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
