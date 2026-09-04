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
- 清单只收本仓在位资产（L4 口径：cmd 引用脚本必须存在）。迁移种子中指向未迁移
  资产的 84 条悬空引用已移除；suyou 全量场景集与其资产留在 suyou 仓原位。
"""
import subprocess
import sys
import time

SCENARIOS = [
    ("t260903-10-installer-console-line",
     "3099 红线源码级静态守卫（交接单 §3 C1 全词表）：安装器入口+server/installer 全源对 kill/pkill/重启/spawn/start/launch × 3099/console 上下文零容忍、提示文案（请手动/操作面）白名单豁免区分提示与执行；扫描器自证红绿（干净样本绿+注入 pkill 副本红+含 start 的提示行豁免）；verify.yaml guard-3099-redline 为 2 词行级粗守卫，本场景为全词表+上下文窗细守卫不互替（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_installer_console_line.py", "ro"),
    ("t260903-10-installer-lifecycle",
     "安装器生命周期用户旅程（黑盒 CLI+fixture 仓注入+假 temporal 替身+临时 HOME 桩，经公共旗标 --root/--server-port/--ui-port 全程隔离，与真 7233/8233 零接触）：up 起 server（演练端口探活+状态真源 ~/.sandbar/run 落 pidfile）、status 必印「console 属用户操作面，请手动起停」、重复 up 幂等（监听者与 stub 自报 pid 恒为首发进程，不重复拉起）、down 先 worker 后 server（TERM 时间戳红线观测）且终态进程全灭+run 目录 pid 清空；所选端口被占=exit3 环境冲突不对抗（t260903-11 环境无关化重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_lifecycle.py"),
    ("t260903-10-installer-orphan-claim",
     "认领契约 V1 三态进程演练（交接单 §2-#9+V1 钦点：down supervisor 持有的 server 必须「报告+不杀+不复活」绝不能杀后被复活）：supervisor 存活→只报告归属不认领（安装器对 ppid 做真 os.kill 存活交叉核对）；父死真孤儿且命令行谓词命中（temporal server start-dev+数据卷属本安装）→认领后 down 停掉；谓词不命中→显式报错不误杀；argv/ppid 观测面经 PATH 前置 ps 桩按登记表供数（本沙箱禁真 ps），存活与信号全走真内核语义；stub 全程自建不与真环境对抗（t260903-10；t260903-11 观测缝重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_orphan_claim.py"),
    ("t260903-10-installer-fail-closed",
     "依赖故障显式红不静默（§2-#1/#8 fail-closed 家族 CLI 面，经公共旗标 --root 注入 fixture 仓驱动真实拉起路径）：temporal 可执行缺失→up 非零且报错点名 temporal；假 temporal 秒退→30s 量级超时内非零显式失败且启动超时子进程就地回收显式声明；status 空态零退出不崩不误报且必印 3099 红线提示（t260903-10；t260903-11 环境无关化重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_fail_closed.py"),
    ("t260903-10-doctor-compat-matrix",
     "doctor 一条命令全量探针→兼容矩阵落盘契约（契约⑧-3 三轴）：缺省 fixture 档（不起真 dsh、HOME 桩隔离）doctor 零退出、~/.sandbar/compat-matrix.json 恰 5 行（五面全绿=绿一行 append 一行；第五面 probe-engine-zombies 缺省 census 档绿，t260904-02 落地）、行含 sandbar 版本（单源仓根 VERSION，字面量锚退役 t260903-12）与 dsh 已验证点 0.1.1-rc.2、重复 doctor 幂等行集合不变、坏 JSON 矩阵不静默（读侧 schema 校验：非零报错或恢复合法）（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_doctor_compat_matrix.py"),
    ("t260903-10-upgrade-contract",
     "upgrade 消费契约⑧展示契约（副本在场/缺失两态各判，断言锚全取⑧节承诺面）：副本在→--dry-run 零退出且输出含当前版本（单源仓根 VERSION，字面量锚退役 t260903-12）、已验证点 0.1.1-rc.2、必查项四条可辨（A3/A4/B1/D1 编号或语义词）；副本缺→非零 fail-closed 点名契约文件不展示假区间（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_upgrade_contract.py", "ro"),
    ("t260903-12-ver-semver-rc",
     "VERSION 单源 semver 校验 fail-closed 守护（t260903-12）：仓根 VERSION 读回自证（read_version==文件内容 strip、version_tuple==核心三段、通过现行正则——零字面量锚，升版不触红）；semver 行为契约正例回归（纯三段/-rc/-rc.N）+ 负例 12 例全拒不松（核心段与 prerelease 段前导零、rc.x、rc1 无点、-RC 大写、v 前缀、rc.1.2 双段、空串、多行、全角、缺段、四段）——version.py 校验放宽后仓内唯一负例守护点（installer/tests 无自动跑点，写集外）",
     "python3 integration/t260903-12/sc_ver_semver_rc.py"),
    ("t260903-12-merge-checks-pairs",
     "bundle 新鲜度护栏配置与仓实况对齐（t260903-12）：server/dsh/merge-checks.yaml 在场（缺失=护栏未启用红）、形状可解析（引擎遇坏行 fail-closed）、恰含声明对 workbench src/client/→lib/、每对 src/out 前缀为仓内真实目录——路径写错时 3.5 节「src 前缀无改动→降噪」令护栏静默失效（t260827-02 假上线教训的复燃形态），本场景独立守护该对齐，与引擎解析逻辑不互替",
     "python3 integration/t260903-12/sc_merge_checks_pairs.py"),
    ("t260903-13-workbench-bundle-loads",
     "重建产物在 dsh 客户端模块契约下可加载（t260903-13）：lib/client.cjs 与 client.js 同体（exports ./client 指向 client.js，防 onSuccess 复制缺失的半新产物）、closure 外衣头尾完整（window.__ModuleLoader__.load({id:\"suyou-workbench\", factory}) 头 + return module.exports 尾）、vm 沙箱按契约真实加载——工厂可执行、返回非空 exports、bare require 全部落在声明外部化面（react、@deepseek-ai/*）内，越界泄漏=台面加载失败的用户可感形态；加载器先自证红绿（合法样本绿/泄漏红/外衣破损红/未挂载红）再量真产物。锚产物形态合同不锚 bundle 内部实现，tsdown 重建不改契约则本场景不因实现重构而红",
     "node integration/t260903-13/sc_workbench_bundle_loads.mjs", "ro"),
    ("t260903-13-metrics-golden-freeze",
     "度量响应形状对串行基线冻结（t260903-13）：tests/golden_serial/ 基线（t260903-09 修复产物，剔除 generated_at/cache.computed_at）与当前 src/host/metrics.ts 实现逐字节一致；golden.mjs 被 run_tests 执行器 HELPERS 排除、此前全仓无自动跑点（t260903-13 review 实锤的孤儿入口，票面点名「基线一并过」却无执行点），本场景补上唯一自动比对点并机械守护两条纪律：比对后 golden_serial/ 零 git 脏（--record 重录换绿在此现形）、tests/ 无 stub 运行时残留；判定行为级不钉案例数（基线面随窗口枚举自然扩展）",
     "node integration/t260903-13/sc_metrics_golden_freeze.mjs"),
    ("t260904-02-ticket-start-anchor",
     "裸入口开票硬闸+隔离台并发隔离端到端（真 temporalite 槽位台，epic 验收1/4/5，KI-032 修复回归）：裸 client.py ticket-start 带 project→Temporal 内 payload workspace.path 绝对路径且锚注册项目主目录/.lane/（worktree 同锚，落仓与执行 worker 解耦）；缺 project/未知 key=创建即拒收且两红因文案互辨；双槽并发开票时间重叠互不见对方工单（ticket-list 双向+跨槽 describe not_found）；审计钩子证被测子进程零连生产 7233/8233（含自证拦截腿）+temporalite 三端口显式断言（UI 默认=--port+1000 暗雷）+SUYOU_TARGET_HOST 指生产构造即拒（红绿自证）；teardown 槽 db/日志全清、lock 槽锚保留、stop 幂等二连、kill -9 后 flock 崩溃自释同槽可复抢",
     "python3 integration/t260904-02/sc_ticket_start_anchor.py", "exclusive"),
    ("t260904-02-worker-fingerprint-gate",
     "worker 归属指纹 ensure 闸真执行路径（epic 验收2，KI-033 修复回归；断言落公开行为输出非源级 grep——契约不变的实现重构不得打破本场景）：隔离台内真 worker 自报 meta（pid/repo_root/ts，起跑早写）；node.ts 对外契约 export readWorkerMeta/judgeTicketWorkerMeta 三态真值（same/foreign/unknown）+ensureTicketWorkersOnce 依赖注入真调——同仓照旧不重复拉、异仓拒接不 spawn+告警记录含对方仓根/pid/tid 可断言（绝不 kill 别人进程，杀进程归人）、畸形 meta 兼容跳过+reason 可辨不哑巴；TERM 后 worker 退出且自报 meta 清理（资源回收）",
     "python3 integration/t260904-02/sc_worker_fingerprint_gate.py", "exclusive"),
    ("t260904-02-doctor-zombie",
     "doctor 引擎僵尸探测红绿自证（epic 验收3，fixture 注入档零真扫零端口）：SANDBAR_ZOMBIE_CENSUS 注入异仓引擎形态（cwd 含 server/dsh/temporal-poc 标记且引擎根≠当前，即 260904 headless 指向冻结仓实案）→exit1 红行点名 pid+异仓路径且同仓进程不误报；干净 census→exit0+兼容矩阵恰 5 行含 zombie 语义新行+重复 doctor 幂等；坏 JSON census=显式红不假绿（畸形输入三态）；文案自辨：僵尸面输出带 --live 指引（缺省 sample 档防「跑过=无僵尸」误读）+完成语不写死「四面」（数字随探针数漂移）",
     "python3 integration/t260904-02/sc_doctor_zombie.py", "ro"),
    ("t260904-01-project-sessions-journey",
     "项目会话区账册状态旅程（t260904-01 面①，灰盒 L3）：多项目用户从顶部行时代旧账册（无 seq）升级——J1 存量迁移各项目独立 1..n+幂等+serialize 往返持久化；J2 编号生命周期兑现拍板 1（关闭不回收余 tab 保号、新会话续号不填空、重开保号带 title、关闭不回退计数器）；J3 项目行（pickProjectTabs 过滤/seq 升序/title 三级兜底/active 唯一/工单不进）与顶部行（pickSwitchTargets 260904 混排 ≤5/current 保底）两消费面同账册交叉共存；J4 跨键不一致对抗（计数器孤高跳号不重发、偏低/丢失按现存最大兜底防撞、账册手改撞号不崩 active 至多一、畸形 seq 剔字段不剔条目后 backfill 重补、LEDGER_CAP 淘汰后计数器不回退）。与随票 smoke（单点纯函数+源文本锚）步骤级共享、intent 级不同：旅程连续状态转移×两消费面交叉×跨键不一致。锚 shared/sessions.ts 公开导出面（方案 D1/D2 定稿：seq 字段/nextProjectSeq max 语义），不锚内部实现；确认框交互/正方形形态/折叠同隐/弹层裁剪为 node 不可测面，人工走查清单见该票结果文件",
     "node integration/t260904-01/sc_project_sessions_ledger_journey.mjs", "ro"),


    ("auto-rework-trace",
     "---- A1: 五个自动打回场景，各产一条横幅可见记录（用户视角主契约） ---- scenarios = [ ('acceptance', 'implement', '验收",
     "node integration/baselines/sc_auto_rework_trace.mjs"),
    # 260904 转正：原判退役（tests/rework-banner-ui 已安家 UI 半），但它同时是
    # lock-update-integrity 的 EXPECT 数据依赖（sc_auto_rework_trace.mjs），且引擎常量
    # 半（PHASE_MAIN_CHAIN/ROUTES 源解析）与 UI 单测互补——改判带回。
    # ---- 260904 场景回迁（KI-038，triage=notes/discussions/260904-integration-scenarios-triage.md）----
    # 自 suyou 冻结仓整族迁回（宿主令直迁）：P1 引擎行为 + P2 ro 面。P3 browser 族与 t260902-02 e2e
    # 两条暂缓（依赖隔离台基建+playwright 恢复，见 triage）；退役 15 条替代者在 triage 文档。
    ("ticket-lifecycle",
     "The env half itself follows the triad verdict of the real (saved) env value. const guard",
     "node integration/baselines/sc_ticket_lifecycle.mjs"),
    ("sandbar-contract-v1",
     "Strategy item must name both policy files with their roles. const strat = extractSection",
     "node integration/baselines/sc_sandbar_contract_v1.mjs", "ro"),
    ("sandbar-dsh-compat",
     "(doc-guard, t260903-08): 契约 v1.7 ⑧节 dsh 兼容区间/四条升版必查项/版本自报口径在场，交接单取舍清单覆盖 R1 关键词+V1 真孤儿优先级+3099 六词禁词表——⑧节是安装器 upgrade/doctor 探针的机器消费面，缺失=消费方展示假区间/升版复扫漏项",
     "node integration/baselines/sc_sandbar_dsh_compat.mjs", "ro"),
    ("ui-evidence-failure-retention",
     "显式钉死候选环境：单直连候选（假 capture.mjs 秒退 3）+ 死端口 + 临时归档目录。",
     "PY=server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/dsh/temporal-poc/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/baselines/sc_ui_evidence_failure_retention.py", "browser"),
    ("check-auto-rework-trace",
     "从源码解析模块级常量：PHASE_MAIN_CHAIN（frozenset）→ set； PHASE_MAIN_ROLES（Dict）→ dict。解析失败返回 None。",
     "python3 integration/sc_check_auto_rework_trace.py"),
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
    ("t260903-06-query-kind-no-lie",
     "查询谎报面全链回归（KI-025）：阶段切换窗查询失败时，从 Temporal 抖动经 client.py→ticket.py→tools_registry 的完整回执链路绝不把瞬时/终态/畸形故障文案成「工单不存在」；「不存在」仅由 NotFoundFailure 语义产出；终态票不诱导重试；kind 随分级异常跨层存活、缺 kind 回执绝不产 not_found（t260903-06）",
     "python3 -B integration/t260903-06/sc_query_kind_no_lie.py", "ro"),
    ("t260903-09-kpi-invariants",
     "度量面板四张 KPI 卡与三视图图人口自洽（需求③）：任意窗口/视图 closed≤tickets 不再悖论、窗前创建窗内关闭票按锚点计入 tickets（人口桩 7d=3/2、30d=4/2、all=5/3）、「有无代码变更票占比」环形图两片之和恰等于卡上票数、tokens_total 跨视图恒等、「人审等待」分类名字面在场（t260903-09）",
     "node integration/t260903-09/sc_metrics_kpi_invariants.mjs", "ro"),
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
