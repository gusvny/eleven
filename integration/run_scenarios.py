#!/usr/bin/env python3
"""integration scenario runner (the project declaration surface left after the
manifest retired).

Conventions:
- SCENARIOS holds (name, intent, cmd[, pool]) tuples. intent = the
  user-perceivable behavior/contract the scenario guards; pool is optional:
  "main" (default, the serial main pool) / a named pool (e.g. "ro", the
  read-only pool running in parallel with main) / "engine" (docker-stage
  engine scenarios, concurrent in Phase 2 since campaign 3b) / "exclusive"
  (runs alone before all pools — since campaign 3b only the
  shared-temporal ticket writer; see the engine-pool block comment in the
  registry). Within a pool entries run serially to keep order; across pools
  they run in parallel for throughput. Duplicate intents are forbidden.
- Layering: single-component function tests belong to UT (pytest / node at
  source level); this registry only takes cross-component scenarios, frozen
  external contracts, user journeys, and fault-surface adversaries.
- Naming iron rule: scenario files are always sc_<slug>.py/.mjs — anything
  named sc_ must be registered here, unregistered = orphan (lint L5 red);
  without the sc_ prefix the file is shared code, neither registered nor
  warned about (t260902).
- One-shot delivery acceptance snapshots do not enter (their job ends once the
  delivery lands, t260902).
- cmd runs with the repo root as cwd via /bin/sh -c, 900s per entry; stdlib
  only.
- In-pool concurrency (260909 speedup campaign round 2): an entry may carry
  a fifth element "serial" — scenarios that must run one after another even
  inside a pool (process-shaped / fixed-port / pidfile-assumption families);
  entries not marked serial run in-pool at SANDBAR_POOL_CONC (default 4)
  lanes. SANDBAR_CONC_POOLS (default "main:3,ro:3,browser-free:3") picks which
  pools get concurrency, with an optional per-pool width override ("name" =
  SANDBAR_POOL_CONC lanes, "name:N" = N lanes). The default pins width 3, one
  below SANDBAR_POOL_CONC: final verification of campaign 3 saw a load flake
  at full width 4 (capture-chat-e2e's 11-view walk lost two best-effort
  views to element-wait timeouts under the 12-lane herd), and width 3 costs
  zero wall — the serial engine lane (~280s) is the Phase-2 pole while the
  widest other pool tops out around ~165s, so the fourth lane only bought
  shadow headroom, not wall. The engine pool deliberately
  stays OUT of the default list (width 1): its scenarios boot docker stages,
  and campaign 3b verification showed a width-2 engine already flakes (three
  runs, three different victims: a 600s stage-up timeout, a fast env fail,
  and a load product-red) once the concurrent compose-up herd exceeds ~4-6.
  The browser pool was split in speedup campaign 3:
  9 chain entries keep the shared console and stay strictly serial (registry
  order = execution order; the empty-ledger assertion depends on no
  concurrent writer); the 12 zero-coupling entries (7 self-hosted / no
  console + 5 read-only API stubs) moved to browser-free and run
  concurrently with the chain. SANDBAR_POOL_CONC=1 restores the old
  semantics (strict serial everywhere — in-pool lanes AND pool-by-pool).
- The registry only lists assets present in this repo (L4 rule: every cmd
  script must exist).
"""
import os
import subprocess
import sys
import time

SCENARIOS = [
    # Delisted (t260904-12 section 7.3: scenarios that can never actually reach
    # the gate (red-line forbidden zone / destructive) stay out of the gate
    # registry): ticket-lifecycle always trips the nested guardrail inside a
    # worker mechanical step (detected via the SANDBAR_TASK_QUEUE marker, which
    # guards against unbounded self-recursion) — a deliberate environment red,
    # it can never reach PASS inside the gate. Real coverage is carried by the
    # manual checklist in the main repo (t260903-09). The reasoning chain behind
    # the two flips of this ruling (unlisted -> listed -> delisted) is in the
    # README "known limitations" section.
    # Original cmd: node integration/baselines/sc_ticket_lifecycle.mjs

    ("t260903-10-installer-console-line",
     "3099 红线源码级静态守卫（交接单 §3 C1 全词表）：安装器入口+server/installer 全源对 kill/pkill/重启/spawn/start/launch × 3099/console 上下文零容忍、提示文案（请手动/操作面）白名单豁免区分提示与执行；扫描器自证红绿（干净样本绿+注入 pkill 副本红+含 start 的提示行豁免）；verify.yaml guard-3099-redline 为 2 词行级粗守卫，本场景为全词表+上下文窗细守卫不互替（t260903-10）",
     "python3 integration/t260903-10/sc_sandbar_installer_console_line.py", "ro", "serial"),
    ("t260903-10-installer-lifecycle",
     "安装器生命周期用户旅程（黑盒 CLI+fixture 仓注入+假 temporal 替身+临时 HOME 桩，经公共旗标 --root/--server-port/--ui-port 全程隔离，与真 7233/8233 零接触）：up 起 server（演练端口探活+状态真源 ~/.sandbar/run 落 pidfile）、status 必印「console 属用户操作面，请手动起停」、重复 up 幂等（监听者与 stub 自报 pid 恒为首发进程，不重复拉起）、down 先 worker 后 server（TERM 时间戳红线观测）且终态进程全灭+run 目录 pid 清空；所选端口被占=exit3 环境冲突不对抗（t260903-11 环境无关化重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_lifecycle.py", "serial"),
    ("t260903-10-installer-orphan-claim",
     "认领契约 V1 三态进程演练（交接单 §2-#9+V1 钦点：down supervisor 持有的 server 必须「报告+不杀+不复活」绝不能杀后被复活）：supervisor 存活→只报告归属不认领（安装器对 ppid 做真 os.kill 存活交叉核对）；父死真孤儿且命令行谓词命中（temporal server start-dev+数据卷属本安装）→认领后 down 停掉；谓词不命中→显式报错不误杀；argv/ppid 观测面经 PATH 前置 ps 桩按登记表供数（本沙箱禁真 ps），存活与信号全走真内核语义；stub 全程自建不与真环境对抗（t260903-10；t260903-11 观测缝重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_orphan_claim.py", "serial"),
    ("t260903-10-installer-fail-closed",
     "依赖故障显式红不静默（§2-#1/#8 fail-closed 家族 CLI 面，经公共旗标 --root 注入 fixture 仓驱动真实拉起路径）：temporal 可执行缺失→up 非零且报错点名 temporal；假 temporal 秒退→30s 量级超时内非零显式失败且启动超时子进程就地回收显式声明；status 空态零退出不崩不误报且必印 3099 红线提示（t260903-10；t260903-11 环境无关化重造）",
     "python3 integration/t260903-10/sc_sandbar_installer_fail_closed.py", "serial"),
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
     "bundle 新鲜度护栏配置与仓实况对齐（t260903-12）：server/merge-checks.yaml 在场（缺失=护栏未启用红）、形状可解析（引擎遇坏行 fail-closed）、恰含声明对 workbench src/client/→lib/、每对 src/out 前缀为仓内真实目录——路径写错时 3.5 节「src 前缀无改动→降噪」令护栏静默失效（t260827-02 假上线教训的复燃形态），本场景独立守护该对齐，与引擎解析逻辑不互替",
     "python3 integration/t260903-12/sc_merge_checks_pairs.py"),
    ("t260903-13-workbench-bundle-loads",
     "重建产物在 dsh 客户端模块契约下可加载（t260903-13）：lib/client.cjs 与 client.js 同体（exports ./client 指向 client.js，防 onSuccess 复制缺失的半新产物）、closure 外衣头尾完整（window.__ModuleLoader__.load({id:\"sandbar-workbench\", factory}) 头 + return module.exports 尾）、vm 沙箱按契约真实加载——工厂可执行、返回非空 exports、bare require 全部落在声明外部化面（react、@deepseek-ai/*）内，越界泄漏=台面加载失败的用户可感形态；加载器先自证红绿（合法样本绿/泄漏红/外衣破损红/未挂载红）再量真产物。锚产物形态合同不锚 bundle 内部实现，tsdown 重建不改契约则本场景不因实现重构而红",
     "node integration/t260903-13/sc_workbench_bundle_loads.mjs", "ro"),
    ("t260903-13-metrics-golden-freeze",
     "度量响应形状对串行基线冻结（t260903-13）：tests/golden_serial/ 基线（t260903-09 修复产物，剔除 generated_at/cache.computed_at）与当前 src/host/metrics.ts 实现逐字节一致；golden.mjs 被 run_tests 执行器 HELPERS 排除、此前全仓无自动跑点（t260903-13 review 实锤的孤儿入口，票面点名「基线一并过」却无执行点），本场景补上唯一自动比对点并机械守护两条纪律：比对后 golden_serial/ 零 git 脏（--record 重录换绿在此现形）、tests/ 无 stub 运行时残留；判定行为级不钉案例数（基线面随窗口枚举自然扩展）",
     "node integration/t260903-13/sc_metrics_golden_freeze.mjs"),
    ("t260904-03-dispatch-knowledge-constant",
     "派活头索引化核心承诺（KI-035 宿主拍板，t260904-03）：两条组装路径（v1 dispatch 头③ / v2 dispatch-next②）的知识段在 workflow×标题×段形态×畸形输入全电池下恒定——恰一行、逐字节同一、含目录锚 docs/README.md（不随票面相关性膨胀=「60-80k token/票、与票面相关性无关的重复消耗」根除面）；且 prompt 内提及的一切 docs/*.md|json 路径落盘存在（旧表「掌握→掌握模型设计.md、content-pipeline→平台架构设计.md」留守 suyou 断链形态的根除守护）。锚公开渲染契约不锚实现，文案重构不改契约则不红；实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-03/sc_dispatch_knowledge_constant_and_linked.py", "ro"),
    ("t260904-03-dispatch-composition-integrity",
     "恒定知识行×派活契约组合完整性（t260904-03，用户旅程=被打回重派的 agent 收到的完整指令仍自洽）：注入 previous_context 后 v2 顶层编号整体后移一位且合法（1 起/无重号/严格递增；条件节缺席跳号=既有占位契约，全节在位形态 1..N 连续——注入/交接/朴素三态实得序列直接钉在断言标签里）、知识段恰一行且缩进块 1 内；前段交接多行 report+多行 user_request+spec 共存不扰动；v1 段专项条款（content-pipeline/ai-review）/分工实例/写集在否——均不扰动知识段文本（与朴素基线逐字节同）。防插错列表位破坏编号/分支双写/条款吞噬/重派路径漏新行；实现段落地前红属预期",
     "python3 integration/t260904-03/sc_dispatch_composition_integrity.py", "ro"),
    ("t260904-03-forced-reading-retired",
     "KI-035 修复反向守护（t260904-03 验收 E 机械化，merge 关卡可跑）：server/**/*.py（引擎代码面）+活文档 docs/README.md 对 WORKFLOW_CONTEXT/TITLE_CONTEXT_RULES/context_docs 零活引用残留——防旧映射表从旧代码/旧文档抄回（照搬带回旧债的静态守护）；notes/ 历史审计行、.suyou/ 段快照、engine/tests L1 负断言源码豁免（断言面≠消费面，写明防误判）；扫描器自证红绿。实现段落地前红属预期",  # naming-compat
     "python3 integration/t260904-03/sc_forced_reading_stays_retired.py", "ro"),
    ("t260904-04-stale-cache-heal-journey",
     "度量陈旧缓存自愈用户旅程（t260904-04 KI-040，灰盒 L3）：持有算于 merge 前/闭单前的陈旧缓存（delivery=null、open=true）的用户重开度量面板——全量拍交付维出数（主仓归档口径，reason 含多提交边界=工单 B5 契约承诺）、time 与 health 两视图关闭数收敛（4vs5 分叉）、TTL 节流下数字不漂（剔除易变字段逐字节一致）、updated_ts 过期/缺失（NaN）/TTL=0 三态都自愈不自锁、自愈后 fast 第一拍快照即正确。与 workbench/tests/delivery-recovery（L1 记录内部机制/零 spawn）与 t260903-09-kpi-invariants（新鲜数据人口自洽）intent 不同面：本场景守两拍旅程与跨视图一致的响应契约。实现已随本票落地，全绿；若实现回退则 J1~J6 红、J0 夹具自检仍绿（修复面真实性的对照）",
     "node integration/t260904-04/sc_metrics_stale_cache_heal_journey.mjs", "ro"),
    ("t260904-04-universe-reason-cap",
     "聚合宇宙吞票显式化与 reason cap 共存（t260904-04 KI-043②，灰盒 L2）：workflow 为空/不匹配被模板过滤的票在 reason 首位以 notice 计数（宿主令「不静默缩宇宙」），20 条 cap 压力下 notices 保位不被挤掉（契约块 2 notices 不受 cap 截断承诺对新 notice 同样成立），被滤票不混入任何 spec categories、不进 KPI 人口（缩宇宙可以、静默不行）。与 developer L1（过滤前计数函数级）intent 不同面：本场景守响应级 reason 组装整串。实现已随本票落地，全绿；实现回退则 notice 断言红",
     "node integration/t260904-04/sc_metrics_universe_reason_cap.mjs", "ro"),
    ("t260904-04-project-repo-registry-seam",
     "per-project repo 换根的真注册表接线（t260904-04 KI-043① R1 裁决面，灰盒 L2）：repoForProject 随 defaultDeps 公开导出（HTTP/CLI 双门共享同一份→天然同修），SANDBAR_PROJECTS_DIR 注册表缝真装载——合法 key 各归各主目录、默认项目 key 同样换根（gen1 裁决语义）、未知 key 与注册表文件坏都 null 回退不抛。与 developer L1（注入桩测换根行为/双门 stub 一致性）intent 不同面：本场景补桩够不到的真 env→yaml 解析→主目录装载链；legacy 单文件注册表模式行为方案未裁决不锚。实现已随本票落地，全绿；实现回退则全红",
     "node integration/t260904-04/sc_project_repo_registry_seam.mjs", "ro"),
    ("t260904-04-panel-residue-journey",
     "面板持久化残留不锁死面板旅程（t260904-04 A1 验收，灰盒 L3）：持有旧 localStorage 残留（template=other-lane/epic=代号，两选择器均已退役）的用户重开面板——loadPanelState 读时归一（template→dev-lane、epic→all、非退役字段保留）→ 归一查询串过 /metrics 前门 200；对照组证明失败模式真实：未归一残留 template 直打门 400 且 {error,reason} 双人话（旧世界残留=永久 400 空面板）。与 developer L1（归一函数含畸形输入）intent 不同面：本场景守残留→查询串→门的旅程与对照红面",
     "node integration/t260904-04/sc_panel_residue_journey.mjs", "ro"),
    # ---- engine pool (260909 speedup campaign 3b): the Phase-1 barrier shrunk ----
    # The "exclusives first" barrier predates every entry (executor seed
    # a2065b4 fixed the semantics with zero exclusive entries registered; it
    # was never re-argued). Campaign 3 audited all 11: 10 are project-scoped
    # (dynamic port-band flock, compose-project teardown, zero fixed ports,
    # zero daemon-level ops) and overlap safely with every pool — they moved
    # to the "engine" pool, which runs alongside the other pools in Phase 2
    # but stays serial within itself (width-2 verification flaked; the
    # scenarios boot docker stages and the compose-up herd must stay small).
    # Within the lane, ticket-start-anchor is deliberately LAST (see its entry):
    # its stage boots then land in the drained window instead of the Phase-2
    # t=0 with_stage herd (run E of campaign-3 final verification).
    # Only t260905-03-period-journey stays
    # "exclusive": it writes real tickets to the shared default 7233
    # temporal, and the main-pool decl-gate triggers the same surface
    # (ticket-face pollution is the documented failure mode). Load caveats
    # (timing legs, daemon pressure) are recorded on the entries.
    ("t260904-02-worker-fingerprint-gate",
     "worker 归属指纹 ensure 闸真执行路径（epic 验收2，KI-033 修复回归；断言落公开行为输出非源级 grep——契约不变的实现重构不得打破本场景；t260904-19 起 temporal 台=docker 测试台单实例）：隔离台内真 worker 自报 meta（pid/repo_root/ts，起跑早写）；node.ts 对外契约 export readWorkerMeta/judgeTicketWorkerMeta 三态真值（same/foreign/unknown）+ensureTicketWorkersOnce 依赖注入真调——同仓照旧不重复拉、异仓拒接不 spawn+告警记录含对方仓根/pid/tid 可断言（绝不 kill 别人进程，杀进程归人）、畸形 meta 兼容跳过+reason 可辨不哑巴；TERM 后 worker 退出且自报 meta 清理（资源回收）",
     "python3 integration/t260904-02/sc_worker_fingerprint_gate.py", "engine"),  # engine: one docker stage + real worker
    ("t260904-19-stage-docker",
     "docker 测试舞台 L1（t260904-19：全仓唯一搭台方式回归锚，假 docker shim 真跑编排面零 docker 依赖）：档位 flock 原子预留（并发双起各得独立档=验收①回归锚、外部持锁滑档、锁释放复抢=崩溃自释语义）；禁区端口面（生产 3099/7233/8233+缺省台 3199/17233/18233）与内核临时区间构造性排除；畸形输入全电池（project 白名单/端口旋钮非数字越界禁区被占/目录缺失/半指定）逐条点名检查项零副作用；诚实环境红三态（docker 缺席=ENV_FAIL exit 2 点名、镜像缺席点名 build-test-temporal.sh、compose 半途死就地 down 清场零残留）；ensure 幂等（健康复用/半残拆重起）；up→down 零残留+端口释放+幂等二连；bench.py 守卫回归（槽位制退役后保留面）",
     "python3 integration/tests/test_stage_docker.py", "ro"),
    ("t260904-02-doctor-zombie",
     "doctor 引擎僵尸探测红绿自证（epic 验收3，fixture 注入档零真扫零端口）：SANDBAR_ZOMBIE_CENSUS 注入异仓引擎形态（cwd 含 server/engine 标记且引擎根≠当前，即 260904 headless 指向冻结仓实案）→exit1 红行点名 pid+异仓路径且同仓进程不误报；干净 census→exit0+兼容矩阵恰 5 行含 zombie 语义新行+重复 doctor 幂等；坏 JSON census=显式红不假绿（畸形输入三态）；文案自辨：僵尸面输出带 --live 指引（缺省 sample 档防「跑过=无僵尸」误读）+完成语不写死「四面」（数字随探针数漂移）",
     "python3 integration/t260904-02/sc_doctor_zombie.py", "ro"),
    ("t260904-01-project-sessions-journey",
     "项目会话区账册状态旅程（t260904-01 面①，灰盒 L3）：多项目用户从顶部行时代旧账册（无 seq）升级——J1 存量迁移各项目独立 1..n+幂等+serialize 往返持久化；J2 编号生命周期兑现拍板 1（关闭不回收余 tab 保号、新会话续号不填空、blank 换绑保号、关闭不回退计数器；↺ 重开已随票② R8 退役）；J3 项目行（pickProjectTabs 过滤/seq 升序/title 三级兜底/active 唯一/工单不进）——票② R8 顶部行消费面已退役，项目行是账册唯一渲染面；J4 跨键不一致对抗（计数器孤高跳号不重发、偏低/丢失按现存最大兜底防撞、账册手改撞号不崩 active 至多一、畸形 seq 剔字段不剔条目后 backfill 重补、LEDGER_CAP 淘汰后计数器不回退）。与随票 smoke（单点纯函数+源文本锚）步骤级共享、intent 级不同：旅程连续状态转移×两消费面交叉×跨键不一致。锚 shared/sessions.ts 公开导出面（方案 D1/D2 定稿：seq 字段/nextProjectSeq max 语义），不锚内部实现；确认框交互/正方形形态/折叠同隐/弹层裁剪为 node 不可测面，人工走查清单见该票结果文件",
     "node integration/t260904-01/sc_project_sessions_ledger_journey.mjs", "ro"),

    # ---- 260904 browser family + e2e return (KI-038 wrap-up) ----
    # When playwright-core is missing (KI-036) the three-state contract records
    # ENV_FAIL (exit 2) — no fake red, no fake green; it takes effect on its
    # own once the dependency is back (t260904-12: no SKIP inside the gate).
    ("ticket-session-restore",
     "ticket-session 面双半契约（t260831-08 起；browser 半被 t260903-07 反转）：服务端 POST ticket-session/open 保留 find-or-create（session_id=ticket-<id>、created 旗标、重开不重复）与畸形 id/缺 project/未知 project/不存在工单显式 4xx；浏览器半=点工单行中列详情照常开、右栏 chat 零切换（快照零注入、phase 不变、多行点击零 churn）",
     "node integration/baselines/sc_ticket_session_restore.mjs"),
    ("ticket-evidence-images",
     "(black-box, user perspective): // QA screenshots (.suyou/screenshots/*.png in the lane) ",  # naming-compat
     "node integration/baselines/sc_ticket_evidence_images.mjs"),
    # (session-top-entry / session-tab-interactions retired with ticket 2 R8
    #   (t260904-05): the tested surface SessionTopEntry/wb-sessTop family is
    #   gone with no remaining consumer; the replacement watch =
    #   smoke/hero.mjs reverse assertions + project-sessions.mjs S6.)
    # ---- browser pool split (260909 speedup campaign 3a) ----
    # Two pools touch the staging console, with different coupling:
    # - "browser": 9 chain entries driving the same page state. Strictly
    #   serial; registry order IS the contract (top-entry-retired-form
    #   asserts an empty ledger, so no concurrent writer may create a
    #   session; session-lifecycle-ui asserts seq numbers never regress).
    #   Never width-ize this pool.
    # - "browser-free": 12 zero-coupling entries running concurrently with
    #   the chain (this pool is in SANDBAR_CONC_POOLS). 7 are self-hosted
    #   (own mock server / capture lane / pure file contracts, no console at
    #   all — the capture-chat twins take kernel-assigned ports and mkdtemp
    #   homes, verified disjoint under a parallel direct run) and 5 ensure
    #   the shared console but stub every mutating route (read-only, no
    #   shared-state assertions). Line-end tags below: "# chain:" vs
    #   "# free:".
    ("capture-lane-preset",
     "capture-lane-preset.mjs —— 隔离台 preset 物化基线（t260901-02）。 // // 断言 server/ui-check/cap",
     "node integration/baselines/sc_capture_lane_preset.mjs", "browser-free"),  # free: no console — pure file contract
    ("capture-chat-e2e",
     "(black-box, user perspective): // t260901-02 acceptance walk found the capture evidence ",
     "node integration/baselines/sc_capture_chat_e2e.mjs", "browser-free"),  # free: no console — own lane (kernel port + mkdtemp home; verified disjoint from the active twin under parallel direct run)
    ("capture-chat-active",
     "（黑盒，用户视角）： // t260901-02 验收走查实证：隔离台端到端实跑 chat 视图 25s 内未出现 // data-phase=active，capture 退",
     "node integration/baselines/sc_capture_chat_active.mjs", "browser-free"),  # free: no console — own lane (same disjoint mechanics as the e2e twin)
    ("capture-redline-gate",
     "(black-box, user perspective): // The capture evidence tool may create sessions and SEND",
     "node integration/baselines/sc_capture_redline_gate.mjs", "browser-free"),  # free: no console — own mock server (240s serial pole; in-scenario parallelization = campaign 3c)
    ("t13-evidence-lightbox",
     "(black-box, user perspective): 工单详情抽屉的截图证据缩略图网格 // (t260831-08) 现在支持看图灯箱。用户可感知契约（以 t2609",
     "node integration/t260901-13/sc_evidence_lightbox_dom.mjs", "browser-free"),  # free: shared console read-only — API stubs
    ("lane-parallel-dom",
     "(black-box, user perspective): t260901-05 shipped the lane diagram's // parallel-fork re",
     "node integration/baselines/sc_lane_parallel_dom.mjs", "browser-free"),  # free: shared console read-only — API stubs
    ("metrics-donut-dom",
     "t260903-09 度量三 donut 白板修复的 DOM 级基线（黑盒） // 用户视角：有数据时三张环形图——时间去哪了/有无代码变更票占比/模型份额——真渲染非白板（canvas 有非透明像素），人审扇区独立橙色，畸形数据走人话空态不崩；cache-first 先吐 stale 快照角标后台全量替换 // 两层结构同 sc_lane_parallel_dom：S0 bundle 契约+纯逻辑 smoke（全环境跑），S1 隔离测试台真浏览器 DOM（缺环境干净 SKIP）",
     "node integration/baselines/sc_metrics_donut_dom.mjs", "browser-free"),  # free: shared console read-only — API stubs
    ("multi-tab-coexistence",
     "(black-box, user perspective): the ticket workbench is used with // MULTIPLE console tab",
     "node integration/baselines/sc_multi_tab_coexistence.mjs", "browser-free"),  # free: shared console read-only — API stubs
    ("t22-t260901-22-approve-modal-ui",
     "* * integration/t260901-22/t02_approve_modal_ui.mjs * —— KI-004「approve 弹层自由备注」用户可感知 UI ",
     "node integration/t260901-22/sc_t02_approve_modal_ui.mjs", "browser-free"),  # free: no console — pure file contract (bundle)
    ("t22-t260901-22-approve-modal-faultmodes",
     "本 UI 家族（wb-modal）无 Esc/外点关闭处理器（rework 打回弹层同样只有「确认/取消」 // 两条真实关闭路径）——验收口径改为：每一处 setApprov",
     "node integration/t260901-22/sc_t03_approve_modal_faultmodes.mjs", "browser-free"),  # free: no console — pure file contract (bundle)
    ("t260905-05-modal-dialog-semantics",
     "wb-modal 弹层族 dialog 语义契约（t260905-05，灰盒 L2）：本票 client 侧唯一行为变化=四类 wb-modal（审批推进/打回/派活指令/内容预览）补 role=dialog+aria-modal——用户可感知承诺=弹层在场时 [role=dialog] 语义通路可发现（全仓 6 个集成 helper 的 dismissOverlays 通路从恒空变可用，即本票改动要兑现的契约）、aria-modal=true 在册、可经语义通路关闭（点弹层按钮遮罩消失）；真台面行为腿（行卡「推进」→审批弹层 / 行卡「打回」→打回弹层，t260904-17 行卡契约锚+页级 API 桩零真写，native confirm 全程自动 accept）+ 服务产物完备腿（盘上 lib/client.js=台面按请求服务的真产物，每处 wb-modal 皆带 role——改 src 忘 tsdown 重建的 KI-052 同族静默穿透在此现形：client 半每次请求从盘现读，未重建=持续红 merge 闸不放行）+ 零 pageerror 卫生。与 t260901-22 approve-modal-ui（弹层出现+内容在场面）/t260903-04 bundle-sync（src≡lib 构建卫生面）/multi-tab-coexistence（跨页签族行为面）intent 不同面。实现段落地前红属预期（TDD 验收门，S0 build-contract 先例），arbitrate/merge 期必须绿",
     "node integration/t260905-05/sc_modal_dialog_semantics.mjs", "browser"),  # chain: shared-console writer — real API writes (approve/reject state changes)
    ("t260905-05-multitab-guard-assets",
     "19 号豁免体系资产守卫（t260905-05，静态读源零台面）：本票红线「不改 19 号已落资产语义」+验收条款「force 取证守卫保留」的机械面——sc_multi_tab_coexistence.mjs 内诚实红定性标签 PRE_EXISTING_TAG 仍挂 T2/T5 fail 分支与 failWith catch 路径（防「红=正常」习惯化的守卫，绿则随 fail 分支自消但资产本体必须保留）、force 取证守卫（「force 后抽屉仍不开=产品红如实落」语义注释+force:true 点击通路）在册、三态执行契约（SUMMARY 四计数+退出码 1/2 分家）未弱化、T1-T7 族腿清点零缺失（新增腿不拦、缺腿即红——族覆盖收缩须走票）；检测器红绿自证（真源逐规则绿+四份变异样本逐规则红，检测器失明在此现形）。与 multi-tab-coexistence（运行时行为面）intent 不同面：本场景守守卫资产在册",
     "node integration/t260905-05/sc_multitab_guard_assets.mjs", "ro"),
    ("t02-t260902-02-prune-e2e",
     "client.py 末行 JSON 回执；解析失败 = FAIL。",
     "sh integration/with_stage.sh t26090202-prune python3 integration/t260902-02/sc_t05_prune_e2e.py"),
    ("t02-t260902-02-archive-legacy-e2e",
     "注入缝直调真命令逻辑（活文件系统，零 Temporal server 依赖）。",
     "sh integration/with_stage.sh t26090202-arch python3 integration/t260902-02/sc_t06_archive_legacy_e2e.py"),
    ("t260903-07-click-no-chat-switch",
     "点工单不切右侧会话（t260903-07①核心反转）：点工单行后中列详情照常开（.wb-d2-steps 在场）、右栏 chat 零变化——【工单上下文】快照零注入、data-phase 不变、项目会话区 tab 全集不含 ticket- 行（票② R8 改锚：顶部行已退役，判据改 [data-wb-psess-tab] 全集）；多行重复点击零注入零 churn（旧契约「点行→开 ticket- 会话」的显式反转守卫，防联动复活）",
     "node integration/t260903-07/sc_t01_click_no_chat_switch.mjs", "browser"),  # chain: shared-console reader — real ticket rows, zero-churn assertion
    ("t260903-07-chat-project-tag",
     "全局 chat 用户消息项目 tag 契约（t260903-07②）：引用真实工单 id 的消息行渲染文本=注册项目 key 的 chip（颜色非空）；同项目恒同色、不同项目不同色、页面重载后同色（确定性映射的用户可感知面）；全部 chip 文本 ∈ 注册项目键不造假 key；「归属不了→不渲染」是 env 相关声明行为、不在场景层强断言（L1 DOM 桩已锁，chip 经 ::before 伪元素渲染故断言走 getComputedStyle）",
     "node integration/t260903-07/sc_t02_chat_project_tag.mjs", "browser"),  # chain: shared-console reader — real ticket rows (chip color mapping)
    ("notes-write-gate",
     "机械闸守卫：dev-lane 工单禁写 notes/（宿主令 260904——票据/知识库账本归 main 侧直管，t260904-01/03 的 KI 行合并冲突与 notes/epics 草案直落为动因）。三执法点：A 合并闸 verify_lane 四态真子进程（声明了 notes/ 也拦防自授权/D 删账同拦/写集内普通文件不误伤/粗判据分支同拦）；B 建单侧 ticket.create 写集含 notes/ 创建即拒（纯函数面零 Temporal，人话指路结算 note）；C 本仓 verify.yaml write_allow 无 notes/ 静态防回潮。tmp git 仓全本地",
     "python3 -B integration/baselines/sc_notes_write_gate.py", "ro"),


    ("auto-rework-trace",
     "---- A1: 五个自动打回场景，各产一条横幅可见记录（用户视角主契约） ---- scenarios = [ ('acceptance', 'implement', '验收",
     "SANDBAR_TARGET_HOST=127.0.0.1:17233 node integration/baselines/sc_auto_rework_trace.mjs"),
    # 260904 ruling reversed, entry brought back: the original verdict retired
    # it (tests/rework-banner-ui became the home of the UI half), but it is
    # also an EXPECT data dependency of lock-update-integrity
    # (sc_auto_rework_trace.mjs), and the engine-constant half
    # (PHASE_MAIN_CHAIN/ROUTES source parsing) complements the UI unit test.
    # ---- 260904 scenario return (KI-038, triage = notes/discussions/260904-integration-scenarios-triage.md) ----
    # Migrated back as a family from the frozen legacy repo (host-ordered direct
    # migration): P1 engine behavior + P2 ro faces. The browser family and the
    # two e2e entries are deferred (they need the isolated-stage infra +
    # playwright restored; see the triage doc); the 15 retired entries'
    # replacements are listed in the triage doc.
    ("sandbar-contract-v1",
     "Strategy item must name both policy files with their roles. const strat = extractSection",
     "node integration/baselines/sc_sandbar_contract_v1.mjs", "ro"),
    ("sandbar-dsh-compat",
     "(doc-guard, t260903-08): 契约 v1.7 ⑧节 dsh 兼容区间/四条升版必查项/版本自报口径在场，交接单取舍清单覆盖 R1 关键词+V1 真孤儿优先级+3099 六词禁词表——⑧节是安装器 upgrade/doctor 探针的机器消费面，缺失=消费方展示假区间/升版复扫漏项",
     "node integration/baselines/sc_sandbar_dsh_compat.mjs", "ro"),
    ("ui-evidence-failure-retention",
     "显式钉死候选环境：单直连候选（假 capture.mjs 秒退 3）+ 死端口 + 临时归档目录。",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/baselines/sc_ui_evidence_failure_retention.py", "browser-free"),  # free: no console — dead-port negative test
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
     "路径相近但非 wf 端点不误吞 ok(!!callDecide('GET', BASE + '/sandbar-workbench/other/tickets')?.passthr",
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
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260902-09/sc_it01_creds_merge_blackbox.py"),
    ("t09-t260902-09-spawn-creds-refresh",
     "以 fixture 泳道为 cwd 跑 spawn 准备（role 空 = 不触角色 patch/会话延续）。",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=../../server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260902-09/sc_it02_spawn_creds_refresh.py"),
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
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260903-03/sc_paths_spawn_seam.py"),
    ("t260903-03-paths-failclosed-red",
     "路径契约化故障面对抗（spawn 缝隙红传导，用户视角=红工单点名文件而非静默猜着跑）：条目 project.yaml 损坏（现行约定在位也必须红，不静默回落）、声明锚点缺失（不被 per-role 软跳过吞掉）、锚点类型错位（表↔目录/目录↔文件）、声明值畸形代表例（未知键/绝对路径/../穿越）一律红且文案点名键或解析后路径（t260903-03 ①d 三态）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260903-03/sc_paths_failclosed_red.py", "ro"),
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
    ("t260904-05-top-entry-retired-form",
     "顶部行退役后的入口形态契约（R8+R7 左栏，browser）：lib 产物零退役符号（SessionTopEntry/wb-sessTop/pickSwitchTargets/renameEntry/data-wb-session-*）且含新锚（projband/psess-dot/psess-color）；DOM 中 data-wb-session-{entry,new,row,reopen} 全不在场、无 wb-sessTop 类元素；出厂全局新建钮继续被压制不回显（拍板 1）；项目色三处同源（t260907-03 重基线：色点=纯色板值 ∈ 确定性色板；+钮边框/文字=同色板值经锁定派生公式 55%/45% color-mix 混平台令牌链的 computed 期望值，页面内同作用域探针精确比对；判定依据见场景头注）、刷新恒色（验收 5）；关闭确认弹层文案含「仅关闭入口/不删除」且无「↺/最近关闭」表述（拍板 2）；console 零 error",
     "node integration/t260904-05/sc_top_entry_retired_form.mjs", "browser"),  # chain: shared-console reader — empty-ledger assertion needs no concurrent writer
    ("t260904-05-chat-band-affiliation",
     "右栏 chat 项目色带归属通道（R7 核心新意=用户需求③，browser）：fresh 空账册不渲染色带（不在册声明行为）；项目行 + 新建后 [data-conversation-scroll] 本体带 data-wb-chat-projband=<该项目 key>（属性锚非包裹节点=零 childList 侵入的可感知面）；色带 3px + head 自有 style 在场且色与左栏 --wb-psess-color 同源；点工单行归属不动（t01 同契约：chat 不切换）；刷新后归属恢复（账册持久）；console 零 error",
     "node integration/t260904-05/sc_chat_band_affiliation.mjs", "browser"),  # chain: shared-console writer — real project+session creation
    ("t260904-05-session-lifecycle-ui",
     "项目行会话生命周期 UI 全链（接管随 R8 退役的 session-tab-interactions 用户路径 intent，browser）：+ 新建续号且 active 恰一；关闭确认取消不动/确认才关；序号不回收（关掉的号不填洞，拍板 1）；刷新后整组 tab 持久；关完全部再新建仍续大号（BO-1 closed 号域防撞、计数器不回退）。与 t260904-01 journey（纯函数账册状态机）intent 级不同层：本条=用户操作流×真实 UI 呈现",
     "node integration/t260904-05/sc_session_lifecycle_ui.mjs", "browser"),  # chain: shared-console writer — seq numbers never regress
    ("t260904-05-ledger-adversarial-boot",
     "账册外部输入三态的真实 boot 对抗（畸形/缺失/旧版，browser；journey J4 的 boot 路径复验，intent=boot 韧性非函数容错）：旧顶部行时代账册（无 seq+title）升级渲染且补号、ticket- 条目永不进 tab；project 字段畸形（非字符串/空串）条目不落任何项目组、色带不渲染、+钮仍可用；账册+计数器双键坏 JSON → 按丢失处理 boot 干净；各 case console 零 error",
     "node integration/t260904-05/sc_ledger_adversarial_boot.mjs", "browser"),  # chain: shared-console writer — bad localStorage ledger injection
    ("t260904-06-spec-card-dom",
     "工单详情「执行规格（spec）」卡渲染契约（t260904-06，宿主拍板 B 形态，真浏览器 S1-only 无 S0 段）：API 边界桩 fixture、浏览器/console/shipped bundle/React 渲染全真——有 spec 票抽屉正文卡正下方出蓝左条卡（恰 1 个、data-v=B、ttl 含「执行规格（spec）」、徽标=spec.length+「 字」、.txt 全文逐字保真、HTML 特殊字符纯文本零注入、border-left 4px rgb(9,105,218)、pre-wrap）；无 spec 字段老票卡不渲染且正文卡照旧零扰动；超长 spec 限高 260px 滚动收敛不撑爆抽屉、badge 仍计全文；全旅程零 pageerror。与 developer L1 spec-card-ui.mjs 三产物字符串锁 intent 分工：本场景只锁 payload→像素真渲染面（L1 锁不住 JSX 运行时错/落位/徽标算错/换行丢失）；bundle 陈旧时本场景以「卡不在 DOM」正确变红，归因归 merge-checks 闸与 t260903-04 bundle-sync；缺隔离台/playwright 干净 SKIP 注明 KI-036 依赖恢复自动生效；refusing 3099 红线（t260904-06）",
     "node integration/t260904-06/sc_spec_card_dom.mjs", "browser-free"),  # free: shared console read-only — API stubs
    ("t260904-09-settle-snapshot-write-journey",
     "收口出仓快照写路径用户旅程（t260904-09，灰盒 L3，真仓真 merge）：工单收口那一刻项目账本上有一份冻结快照（SANDBAR_SETTLE_SNAPSHOT_DIR/<票>.json，schema_version/squash_commit=merge 回执真身/tokens/delivery 键齐）——token 只加总 assistant/message usage（chunk 翻倍哨兵 999 不计、模型归因当时 provider/model）、delivery=squash 真身 numstat 不靠事后 grep；重复收口（Temporal 重试态）载荷稳定不双算、账面被篡改保留旧件不回写（不可变）；会话目录缺失/zstd 撕裂帧软降级 merge 照常 ok（观测欠账不卡交付）；真·无内容可收（HEAD=他票 squash）zero_change=true 不吸他票账；票 id 注入 ../ 不落 settle 目录之外。与 developer L1（engine/tests 纯函数电池）intent 不同层：本条守「真 git squash merge→快照文件契约」跨组件写路径。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-09/sc_settle_snapshot_write_journey.py"),
    ("t260904-09-settle-snapshot-read-journey",
     "settle 快照读侧消费用户旅程（t260904-09，灰盒 L3）：面板交付/token 数字来自 settle 冻结快照（优先级=快照>活口径>归档 grep；有快照即 frozen，不再随后读侧实现/泳道拆除抖动）；无快照存量票归档口径只认 message 以票号开头的 squash 收口提交（引用性提及他账剔除，12 非 62）；口径变更对存量缓存可达（v1 宽口径存量被重算治愈——05 锚同构，宽口径不永续）；donut 四桶（有变更/已收口·零变更/未交付（在制）/不可算（数据缺失））互斥且 Σ=票数、零变更已闭票不落不可算；快照坏 JSON 不炸面板、票走回落口径留人话 reason；SANDBAR_SETTLE_SNAPSHOT_DIR 覆盖根被消费。与 t260904-04-stale-cache-heal-journey（失败维/open 陈旧自愈）、t260903-13-metrics-golden-freeze（响应形状冻结）、workbench/tests delivery-recovery（L1 记录内部机制）intent 不同面：本条守「快照成为数字真源」消费契约与口径收窄/四桶语义。实现段落地前红属预期（R0 夹具自检除外），arbitrate/merge 期必须绿",
     "node integration/t260904-09/sc_metrics_settle_snapshot_read_journey.mjs", "ro"),
    # ---- t260904-07 project-session opening injection, session-charter (charter file + GET endpoint + injected exactly once for blank) ----
    ("t260904-07-charter-source-contract",
     "charter 交付契约冻结（t260904-07，ro 静态面）：server/session_charter.md 与宿主定稿真源（notes/discussions/260904-project-session-charter.md 附录 fenced 模板）逐字同步——该文件是「当前在案授权」授权档案第一环（git 版本化），漂移=授权声明与定稿脱钩，宿主合法定稿变更须两处同步（回真源补口径后自回绿）；结构要素在文（四占位符/两纪律语义锚：notes 落盘攒批+点名修复先告知/当前在案授权节在/sandbar、suyou 两分段）；端点注册路径与客户端请求路径两侧各自可解析到同一路径字面量（直字面量或同源常量两实现形态都过——KI-042 同族「路径漂移→恒 404 静默吞」的对症看守）；内置回落模板在位含占位符（缺文件回落不 5xx 的前提）。与随票 smoke intent 级不同层：smoke 锚实现守卫源锚（L1/L2），本条锚交付物↔宿主定稿真源一致性与跨端接线一致性。t260905-04 随迁 S5 打标同源锚：charter 机读标记在宿主侧同源定义+客户端经常量引用+端点响应 kind 字段——marker 漂移=折叠件失明静默退化回整段刷屏（KI-042 同族看守）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-07/sc_session_charter_source_contract.mjs", "ro"),
    ("t260904-07-charter-endpoint-live",
     "charter 端点活体契约（t260904-07，ro fetch 级，隔离台 3199 拒 3099）：GET session-charter?project=<key> 部署后可感知契约——命中项目 200+{ok,charter}+key 实值化+零 {{ 残留（统一渲染）+命中分段头在文；未命中项目仍 200 只回通用段+无该 key 分段+{{project_name}} 弱化=key；缺/空串 project=400 形状错误 JSON 不崩不 5xx；404 时源锚复核精确归因（源码已接线未部署=fail，pre-merge=干净 skip 部署后自动生效）。t260905-04 仲裁修正命中腿前提：命中 key 取「注册表∩session_charter.md 有专属分段」的 key（sandbar 优先），注册表在案≠有分段（泳道台 seedws 无分段假红实证），无交集时分段腿=na 点名台数据前提非产品红。与随票 smoke intent 级不同层：smoke 直测渲染纯函数（内存面），本条锚 HTTP 可达面（真宿主真文件真路由）；「文件缺失回落」「改文件即生效」需对受控文件写操作不在活体腿，回落归 smoke 纯函数直测、现读现渲染列人工走查",
     "node integration/t260904-07/sc_session_charter_endpoint_live.mjs", "ro"),
    ("t260904-07-charter-injection-journey",
     "charter 注入用户旅程（t260904-07，browser 隔离台）：项目行点 + 新建会话不输入任何内容即见 charter 为首条消息（占位符实值化无 {{ 残留——「每个 session 创建时注入我们想要的 prompt」原话验收面）+截图证据落 .suyou/screenshots/（KI-044 UI 票证据自觉）；随后切换相邻 tab 再切回、reload 重进既有会话，charter 特征串出现次数恒定+tab 集合不变（守卫：恢复/切换路径绝不注入，沿 t260831-08 ⑥ 口径）；console 卫生零 error（过滤无凭据环境已知凭据类噪音）。断言上限=注入链 UI 面，agent kick-off 回复链不在断言面（无凭据隔离台已知限制，有凭据环境人工复判）；未上屏且仅凭据类错误=干净 skip 不假红。与 t260904-05 生命周期场景（tab 形态/续号/关闭链）intent 级不同层：本条锚注入内容可感知行为。t260905-04 随迁折叠面：t1 新会话开头只见「已注入项目背景」小条+默认折叠+点击展开见全文（特征串计数断言因折叠态文本仍在 DOM 零改动兼容）；t2 切换目标会话小条在场性↔含 charter 一致（无 charter 会话不留幽灵小条——React 不移除外部节点，锚定失效须摘除）；t3 恢复路径折叠面随会话恢复不丢。折叠面断言 pre-implement 红属预期（TDD 信号）",  # naming-compat
     "node integration/t260904-07/sc_session_charter_injection_journey.mjs", "browser"),  # chain: shared-console writer — session + charter injection
    # ---- t260904-11 charter prompt wire contract freeze (KI-046 regression net, platform side) ----
    ("t260904-11-charter-prompt-wire-contract",
     "charter prompt wire 契约冻结（t260904-11，ro 供给只读面，KI-046 回归网）：07 票事故的病根是「客户端发什么形状×平台 zod 门收什么形状」这条跨组件接缝两端从未同场验证——developer 的 ki046 UT（workbench/tests）锚接缝客户端一端（真跑注入函数捕获 prompt 实参），本场景锚平台一端与镜像同步责任，intent 级不同层：①真源锚=平台供给内 dsh-host-apiproxy bundle 的 session.prompt 请求门确实是 content:array(promptContentPart) 分片数组门+text/image 判别联合（锚真实安装工件防镜像循环断言，宽松正则不锚压缩名）；②用户可感知拒收文案真源 invalid payload for ${method} 在文（toast 错误家族来源，平台改文案=漂移信号人审）；③冻结镜像语义（外部调用形状单测规范条款自范本：真 schema 不可导入则仓内冻结镜像+声明同步责任）——修复后分片载荷通过、KI-046 违规裸字符串被拒、缺 text 字段/非法 mode 同拒；平台门任一方向静默漂移本场景红，人审后两处同步。缺平台供给=显式红点名缺什么，不静默 skip（KI-046 闸穿透教训）",
     "node integration/t260904-11/sc_charter_prompt_wire_contract.mjs", "ro"),
    ("t260904-08-template-face-narrowing",
     "工单模板面收窄契约（宿主令 260904，t260904-08）：真源三表（TEMPLATE_CLASS_NAMES/TEMPLATE_CLASSES/TEMPLATE_DISPLAY_NAMES）恰存 dev-lane、四退役 .py/.yaml 物理退场、v1 幸存面（workflows.py 步1 类+DispatcherScanWorkflow）不过删；用户拒收面——create/ticket-start 传四退役模板任一被拒且报错文案恰列 dev-lane（列全=仅 dev-lane，多列/漏列都算文案失真）、dev-lane 仍过模板闸（推进到下一道必填校验而非「未知模板」）；suggest_next 推荐面收「开新 dev-lane 票 / main 侧直跑验证」两类出路且零退役模板名；client start 类型面收敛 dispatcher-scan（文案锚）。stdlib 段零依赖恒跑；ticket-start CLI 段 venv-half（解释器缺失干净 SKIP 注原因，KI-020③）。与既有模板面守卫无 intent 重复（退役收窄为本票新契约）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-08/sc_template_face_narrowing.py", "ro"),
    ("t260904-08-template-retire-no-revival",
     "模板退役防复活负扫描（宿主令 260904，t260904-08）：写集五面（引擎/tools/integration/两篇指定 docs）对四退役类名+content-pipeline 记号零无豁免活引用——防从历史抄回复活注册、防半截清除（注册删了但 USAGE/示例仍教学可用）；豁免=带退役标注的注释、v1 留存引擎样例（t260904-03 R1 裁定面+shared.py 留存数据表键）、声明保留的 v1 演示面与退役标注面（两 docs/两 README，且场景反向钉标注在位防豁免黑洞）、注册表 intent 文本与 test_t260904_03_t01 历史对照夹具（C1）；扫描器自证红绿（活引用样本红+标注样本豁免+留存键/留存文件规则命中+面完整性哨兵防空面假绿）。与 t260904-03-forced-reading-retired 分工：彼守 KI-035 旧文档映射表零活引用，本守 260904 模板族退役零活引用，对象不同不互替。实现段落地前红属预期，扫描红输出即待清残留清单，arbitrate/merge 期必须绿",
     "python3 integration/t260904-08/sc_template_retire_no_revival.py", "ro"),
    ("t260904-13-ui-diff-judgement",
     "UI 票判定源=泳道实际 diff×UI 前缀表（t260904-13 KI-044 根治面，灰盒 L2，ro 隔离临时仓）：真 git 仓 merge-base 三点 diff 驱动——粗目录声明（t260904-05 形态：只声明 server/plugins/workbench/ 父目录、实际改会话区 UI 产物）按实际命中（修复面对照：旧声明口径同形态确实漏判，证明修复的票真实存在）；纯引擎 diff 空清单不误伤；声明 UI 但实际无 UI diff 仍为空（按实际不按声明，防 or 实现）；main 侧他人改 UI 不算本票面（t260901-16 三点承诺在 UI 判定面兑现）；混合票只含 UI 前缀路径；脏输入（None/非列表/非字符串/绝对路径/含 ..）不抛按未命中（developer L1 畸形用例随实现重写，本条=持久契约面）；ui_changed_paths activity 接线结构锁（锚 _merge_base_ref 不回落 main 字面、走共享判定辅助、git 失败 err 进 detail fail-closed、进 worker 注册清单）。与 sc_ki044_merge_gate_ui_item（闸输出合同）/sc_ki044_lane_patchgate_wiring（编排接线）intent 不同面；与 developer L1（白盒纯函数、禁真 git）不同层。t260904-18 增量锁（T18 段，声明制迁移面）：谓词接受显式声明 dirs、None 回落 legacy 表=冻结/重放分支数据源、单参调用形态不碎。实现已随本票落地全绿；实现回退或契约破面则红，arbitrate/merge 期必须绿（T18 段：t260904-18 实现落地前红属预期）",
     "python3 integration/t260904-13/sc_ki044_ui_diff_judgement.py", "ro"),
    ("t260904-13-merge-gate-ui-item",
     "merge_check 3.6 UI 证据闸输出契约（t260904-13 KI-044 闸面，灰盒 L2）：判定源退役声明口径（3.6 段不再吃 is_ui_write_set(args.write_set)——粒度越粗关卡越弱的 t260904-05 直过根因）、换共享判定辅助（两处同源的闸侧兑现）、复用第 3 项已解析泳道基线 wl_base（t260901-18 假阳性教训不回潮）、命中路径落 check detail「按 diff 判定」留痕+capture.mjs 红灯处置指引不丢、git 层故障该项红不静默（KI-046 同族「验证承诺静默蒸发」堵洞面）、MergeCheckArgs.write_set 字段保留（旧实例回放不破 Args 形状）、selfcheck 旧源码锁退役+新判定源/patched 门锁在场（防改码忘改锁的假绿网）。temporalio 泳道不可用→源码契约锁（t05 同族落地形态；t05 锁 diff base 各归各位，本条锁 UI 判定源与闸文案，不同面）。实现已随本票落地全绿；实现回退或契约破面则红，arbitrate/merge 期必须绿",
     "python3 integration/t260904-13/sc_ki044_merge_gate_ui_item.py", "ro"),
    ("t260904-13-lane-patchgate-wiring",
     "dev_lane UI 判定源接线与部署兼容结构（t260904-13 KI-044 编排面，灰盒 L3）：主链判定换新 activity 必须套 workflow.patched 兼容门（新实例走 diff 判定、挂起中存量实例重放走旧布尔分支=命令序列与旧历史严格一致，部署不破存量工单）；patch id 值钉死 dev-lane-ui-diff-v1（历史标记键改名=存量重放断裂）；新命令恰 1 处（旧链尾——仅存量重放可达——冻结不引入新命令）；patch 门先于新命令（门控形状）；新路径入参取 meta 泳道三件套 worktree/branch/base_ref。与判定源/闸两场景 intent 不同面；与 developer selfcheck（锁字面随实现重写）不同深度——本条锁不可随重构漂移的部署承诺。temporalio 泳道不可用→源码契约结构锁（t05 同族）。实现已随本票落地全绿；实现回退或契约破面则红，arbitrate/merge 期必须绿",
     "python3 integration/t260904-13/sc_ki044_lane_patchgate_wiring.py", "ro"),
    # ---- t260904-10 project lifecycle ticket 1: sandbar project add/list (registry wiring face) ----
    ("t260904-10-project-add-dual-loader",
     "add 产出条目的双侧装载一致性（t260904-10，ro 隔离根）：真跑 `sandbar project add` 后 Python shared.load_projects_registry 与 TS project-registry.ts.loadRegistry 从同一隔离根（SANDBAR_PROJECTS_DIR 临时目录）装载出同一条目（key/name/dirs 全等）、零隔离；首装载×seed 自动播种真路径（tracked 种子 suyou 在案+.migrated 落盘）且 add 后种子条目字节不动（决策7 不动账）；体检报告三词汇（verify.yaml/credentials/paths）在文且 credentials 先布置/裸目录两态输出可辨——排他性锚 project.yaml 文件而非条目目录（契约①b：目录与 per-key credentials 可先于 add 布置，O_EXCL 架在目录 mkdir 上=此腿红契约对）；写入零 .tmp. 残留；--json 机器可判。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-10/sc_project_add_dual_loader.mjs", "ro"),
    ("t260904-10-project-add-rejections",
     "add 拒收面全枚举 CLI 真跑（t260904-10，ro 隔离根）：key 白名单（大写/下划线/首字符中划线/42 字符拒，41 字符上界收）；根目录形态（缺参/相对路径/是文件非目录——「不存在」腿已随 t260906-01 容器代建翻转为成功旅程，移册 t260906-01-add-creates-container/-faultlines 承接）；多目录输入语义化拒收（epic 验收2 独立拒收路径：旗标面须能表达多目录输入，且文案点名「单根模型/多目录」——裸 argparse 用法错不算语义拒收）；已注册幂等同判（两次出口码+输出全等）；隔离条目同名拒收；根交叉与互为父子嵌套（父目录/子目录/恰等三向，文案报两个 key）；SANDBAR_PROJECTS_YAML legacy 拒收指路（文案点名存量 env）；name 三态（空/含 #/含换行拒且文案点名 name，首尾空白 trim 后收并读回验证）；每拒收腿注册表根字节级零残留（快照比对+.tmp. 泄漏检查）；并发同 key 双 add 恰一成一拒且赢家条目 name/dirs 自洽不混写（TOCTOU 闸）；remove 点位稳定钉（输出点名 remove、无裸 traceback、注册表不动——票①骨架恒红/票②真实现两期皆存活）。实现落地前红属预期",
     "node integration/t260904-10/sc_project_add_rejections.mjs", "ro"),
    ("t260904-10-project-list-report",
     "list 报告契约（t260904-10，ro 隔离根）：人读与 --json 同列注册+隔离条目，隔离原因含 <dir>/project.yaml 定位字面，无 project.yaml 的保留目录不列；票计数降级三态——服务不可达（SANDBAR_TARGET_HOST 死端口注入）与 SDK 缺失（PYTHONPATH 空壳 temporalio 包注入，KI-039 教训：依赖缺失不得吞成无数据）两态均 exit 0 不红、条目照列、两态输出可辨；正常计数腿在测试台 17233 可达时真跑（不可达有声 SKIP）。全程显式 env 钉死防缺省外溢生产 7233，零 3099 接触。实现落地前红属预期",
     "node integration/t260904-10/sc_project_list_report.mjs", "ro"),
    # ---- t260904-17 ticket list v5 rework (row cards / four states / hash colors / topology lanes) ----
    ("t260904-17-ticket-list-http-contract",
     "工单列表 v5 host 契约面（t260904-17，隔离台+FIX17 桩 python3 拦截 admin.py ticket/workflow、零真 Temporal）：主列表快返回且主请求窗口零 show 调用（「主数据先行」契约——现状逐票 show 阻塞 sendJson，扩 N 倍即 KI-003/029 查询饿死加重面）；enrich 形状钉为 GET /wf/tickets?project=<key>&enrich=progress[&ids=…]（方案「实现期择一」的场景侧裁定）——每票 show 短超时（全票延迟 8s 时 enrich 有界返回、无超时实现必红）、并发峰值≤4（轨迹面观测）、单票失败/畸形 timeline=该票缺 progress 整体 200、progress 数据字段零错误文案（KI-018 根除面）；四态推导字段逐行齐备（验收①数据面）；响应 workflows 恰两模板 stages.length 互异（验收③站道点数消费源）；epic 独立字段透传（验收②数据面）；路由壳回归（缺/未知 project=400 点名、PUT=405）。与 workbench UT（四态真值表/哈希色/守卫）intent 不同面；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台依赖缺失=干净 SKIP",
     "node integration/t260904-17/sc_ticket_list_http_contract.mjs", "ro"),
    ("t260904-17-ticket-list-rowcard-ui",
     "工单列表 v5 行卡用户可感知面（t260904-17，隔离台浏览器走查=验收①的机械 repeatable 面）：四态一眼可辨（等你1/受阻1/在飞3/收口1 chips 带计数——在飞 3 含未知 stage_state 票=四态缺省分支 UI 交叉验证、收口折叠计数行、行卡 data-ticket-id 可测性契约）；「去签字」=纯导航零写 API（点击后写端点 POST=0——R3 钉死：绑 advance=静默签字必红）；「看原因」达阻塞原因原文；站道点数=模板阶段数（5 段模板 5 点/3 段模板 3 点，计算样式计数）；同 epic 行卡彩条同色非灰、异 epic 异色（验收②可感知面）；搜索=过滤非分组。playwright-core 缺失=干净 SKIP（KI-036 守卫）；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260904-17/sc_ticket_list_rowcard_ui.mjs", "ro"),
    # ---- t260905-08 workbench light/dark dual mode + contrast watch (host ruling 260906 22:1X, five rulings) ----
    ("t260905-08-wb-contrast-guard",
     "工单台全台面对比度看守（t260905-08，隔离台浏览器走查=KI-052「场景绿真台盲区」回归用例）：全文档可见文字元素实算 WCAG 对比度（computed color vs 沿祖先链合成到不透明的有效底色；色解析收 rgb()/rgba() 与 color(srgb …)——后者= color-mix 派生色的 computed 形态，epic chip/muted/meta 全在此列），在平台浅档/深档令牌注入与零注入（fallback-only）与旧平台腿（t260907-03：knockout bg-primary 模拟 0.1.1-rc.2 无此名、bg-base=近白代表值，断言 --dsw-derive-canvas 精确等值=兜底链接得住旧平台令牌名）各腿下正文级均须 ≥4.5（收口卡按「至少可分辨」3.0 卡——终态降权设计意图，红线不动；口径随 96c699c 热修正：板面 done 卡=muted 静音色、侧栏 done 卡仍 opacity:.72）；未知 computed 色形态=fail-closed 点名该腿红，绝不静默计入达标（gen0 验收探针实锤旧解析只认 rgb 曾静默漏检 73% 表面，「绿≠全台面真查」KI-052 同构在看守自身复发的根治）；epic 色板 10 档经 fnv1a 槽位确定性挑码全播入（防采样盲区）；详情面（受阻横幅）/侧栏/metrics 文字面入扫（宿主裁定④全台面，不可达=na 条件腿）；变异腿故意注入低对比正文色断言看守必咬（变异测试守测试本身，改造前经侧栏 alias 消费面咬合）。病灶本质=改造前主区写死浅色自洽、三腿全绿（KI-052 同构，如实预期）；两档令牌代表值来源=裁定④「模拟两档令牌」授权，真值待宿主确认；playwright-core/隔离台依赖缺失=env_fail（exit 2）不写 SKIP（三态契约，KI-046 第三层）；arbitrate/merge 期必须绿",
     "node integration/t260905-08/sc_wb_contrast_guard.mjs", "ro"),
    ("t260905-08-hex-clean",
     "工单台写死色清零静态断言（t260905-08，宿主令裁定②「#fff8c5/#ffebe9 等 hex 现场清零（grep 断言）」机械化）：server/plugins/workbench/src/client/ 全目录 .ts/.tsx/.css 样式消费位零裸 hex，颜色一律经 token 声明位（自定义属性定义值/var() fallback）供出；allowlist 三类零特例——EPIC_PALETTE+兜底灰按值级豁免（确定性哈希色，17 号断言守着）、metrics-charts.ts 整文件（echarts 数据编码色，非文本对比度语义）、token 声明位行级判定（var() 跨行写法不在保证面）；零外部依赖 CI 恒真跑（无 env_fail 路径）；实现落地前红属预期（TDD 信号，存量 ~351 处），arbitrate/merge 期必须绿",
     "node integration/t260905-08/sc_hex_clean.mjs", "ro"),
    # ---- t260907-08 theme sweep 2: docs page tokenization + full sub-surface sweep + two-platform x two-appearance quadrants (KI-055 root fix) ----
    ("t260907-08-wb-contrast-quadrant",
     "工单台对比度四象限矩阵看守（t260907-08，KI-055 根治面=主题家族第三次「台面绿真机红」的病根是验收矩阵缺平台版本维度）：验收升为 {新版全令牌集, 旧版 bg-base-only（0.1.1-rc.2 无 bg-primary 名，knockout 模拟）}×{深, 浅} 四象限，每格六张用户台面全扫（工单列表→详情抽屉→文档视图→立项单视图→新建工单弹层→metrics——文档/立项单/弹层为本票新扩走查面，宿主实报两症状的落点：症状①=浅色文档页、症状②=深色部分子面）；正文级 4.5:1、收口行卡 3.0:1，色解析收 rgb()/rgba()/color(srgb …) 未知形态 fail-closed 点名红（沿袭 t260905-08 口径）；legacy 浅格带 canvas 精确等值探针（兜底链接住旧令牌名=t260907-03 先例）；legacy 深格=诊断腿：0.1.1-rc.2 深底 bg-base 代表值未经宿主确认前全扫照跑、比值全打印、na 注记入账不计入判定、不选方便假值造绿，宿主确认后填场景内 LEGACY_DARK_BG_BASE 常量自动升硬腿（机械升级路径）；fallback-only 零注入腿=硬腿（兜底链自洽可读）；变异腿低对比注入必咬（守测试本身）；coverage 反空转守卫：三张新走查面全程至少一格真实入扫（扫描区域计数>0，点击成功≠入扫），否则 fail-closed——防「导航 na 空转绿」（KI-052「绿≠真查」同构防御）；不另立 hex 清零场景（t260905-08-hex-clean 即该 intent 唯一看守，本票实现使其红→绿）。夹具跨票 import t260905-08 lib（bootConsole/teardownOnExit/loadPlaywright/TOKEN_SETS/cssVarsBlock），扫描器复制自该看守场景（漂移责任=两侧头注对齐）；文档/立项单内容=仓树真源（docs/ 定稿库＋notes/epics/*.md）。playwright-core/隔离台依赖缺失=env_fail（exit 2，KI-036/KI-046 家族，不写 SKIP）；实现落地前红属预期（TDD 信号），arbitrate/merge 期硬腿必须绿",
     "node integration/t260907-08/sc_wb_contrast_quadrant.mjs", "ro"),
    # ---- t260905-07 ticket-detail drill-down panel + plugin staleness banner (KI-052 root fix) ----
    ("t260905-07-ticket-detail-panel",
     "工单详情下钻面板用户可感知面（t260905-07，隔离台浏览器真点=验收①②）：行点击开详情抽屉且四观测区块在场（data-wb-digest=timeline/handoffs/signatures/workflow——本场景钉的可测性契约，data-wb-* 先例）；乱序 timeline（KI-019 触及面）按 at 升序归位渲染（data-wb-tl-at 升序）+缺 at 条目沉底带时间缺失标注（呈现口径钉死，不声称修复 KI-019 数据模型）；最近交接/门与签字/工作流要点（workflow_id+worktree）内容可达；无标题老票（t260903-10 现场）列表行显正文首句不裸编号（data-wb-row-title=首句截断：含首句不含第二句）、有题票标题原文不动；enrich=progress 通道 title_or_first 字段值=正文首句（零新路由零新请求；主请求窗口零 show 由 17 号契约场景看守不重复）；行导航零写 API（写端点请求=0，「没看过就签了」危害同 17 号 R3）。playwright-core/隔离台依赖缺失=ENV_FAIL（exit 2，KI-036 家族，不写 SKIP）；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-07/sc_ticket_detail_panel.mjs", "ro"),
    ("t260905-07-stale-handshake-banner",
     "插件 staleness 握手横幅注入实验（t260905-07，fixture 真拷贝隔离台=验收③+KI-052 根治面，gen2 判定矩阵五分支双向断言）：M5 新鲜态（boot==disk==注入）等满一个 30s 轮询窗横幅不在场；M1 盘新内存旧（改 fixture node.ts→新开页注入新指纹≠boot）「重启控制台生效」横幅在场且刷新文案不在场（文案与消除动作绑定）；M2 看守自身内存旧（拦截 build-info 应答 405=KI-052 立案现场，旧看守 405 静默）重启横幅在场；M4 跨重启存活页面（同端口重起台 boot==disk 一致而同页注入=旧盘态）出「刷新页面生效」支且重启文案不在场（重启对该态无效=gen1 打回①序列，场景时序必须同页跨重启）、刷新后横幅消失（消除动作可达）；M5 复验（盘码未动+重起台→新开页→不在场=重启不制造假横幅）；文案断言锚=源码常量 banner-text.ts（KI-051 锚纪律，缺失=FAIL 点名不回退字面量蒙混）。fixture 真拷贝 server、临时端口、临时 DSH_HOME 退出即删、零 3099/7233 接触；playwright-core/preset 源缺失=ENV_FAIL（exit 2）；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260905-07/sc_stale_handshake_banner.mjs", "ro"),
    # ---- t260904-14 project lifecycle ticket 2: sandbar project remove (reversible detachment) ----
    ("t260904-14-project-remove-lifecycle",
     "默认摘除生命周期（t260904-14，桩 poc_dir 全程零真 Temporal，全腿不可 SKIP）：默认（无 purge 旗）可逆摘除——project.yaml 退役移位（project.yaml.retired-* 在位）、data/（归档+metrics）与 credentials.yaml 字节不动、.lane/ 泳道残骸只报不删且报告含票号与数据处置词汇；双侧装载器（Python shared/TS project-registry.ts）不再列该项目且其余项目条目字节不动、零隔离；re-add 同 key 成功且 data/tickets 归档链连续；closed 未归档差集黄牌列票号（C1：目录在/manifest 缺=未归档）；--dry-run 注册表根字节级零变更；RUNNING 非空=拒摘报票号且零现场变更。台别=桩 poc_dir（--root 指桩树，假 client.py 经 FIX14_CTRL 注入票号级清单），零 3099/7233 接触。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-14/sc_project_remove_lifecycle.mjs", "ro"),
    ("t260904-14-project-remove-gates",
     "remove 闸语义面（t260904-14，台别按 C3 表逐腿钉死）：真票腿=隔离台自举 temporalite 起真 running 票→拒摘报票号→cancel 收口→重跑 remove 成功（验收5 全段含 M3 续步；唯一有声 SKIP 豁免腿，依赖缺席打印原因）；其余腿全部桩 poc_dir 不可 SKIP——Temporal 不可达=拒摘含 sandbar up 诊断指路（验收7）、sdk-missing 与不可达两态输出可辨（KI-039）、通道坏 JSON=拒；purge 双旗（差集非空拒列票号[C1 缺失态 manifest 缺=未归档、畸形态红点名 <id>/archive.json]、过闸真删 data/ 不动 credentials、--purge-credentials 独立、双旗组合）、dry-run+purge 旗只出将删清单注册表根字节级零变更（验收8）、最后项目无 --confirm-last 拒/带旗零条目警告+装载器空表抛错可辨（验收9）、legacy env 拒收点名存量 env（模式闸）、key 未注册拒零现场变更、隔离条目同名区分报含 project.yaml 定位。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-14/sc_project_remove_gates.mjs", "ro"),
    ("t260904-12-executor-three-state",
     "执行器三态退出码与输出契约（t260904-12，定稿 §7.3 闸内无 SKIP）：注入假场景表——全过 exit 0；有 FAIL exit 1；fail=0 且 env_fail>0 exit 2 且 ENV_FAIL [名] exit=2 行+缩进尾段点名缺什么；FAIL 与 ENV_FAIL 并存产品红优先 exit 1（C7）；未定义退出码落 FAIL 不放行不归环境（退出码封闭性）；全腿 N/A 经 lib_env 折算产品红（C9）；SUMMARY 五计数 ran=pass+fail+env_fail 双向净不变式+汇总与明细一致（不谎报）；lib_env 助手契约（env_fail→2、fail_if_all_na→1、部分 N/A 不红）",
     "python3 integration/t260904-12/sc_executor_three_state.py", "ro"),
    ("t260904-12-no-skip-guard",
     "SKIP 语义清零防复辟守卫（t260904-12，KI-036/046 族回归）：integration/ 树（基建白名单：执行器/共享助手/lint 三件外）SKIP 与 skip 状态值零残留（覆盖运行时模板串形态）；README 执行契约段无「干净 SKIP（exit 0）」残留且三态/ENV_FAIL 明文；lint_tests.py 全绿（迁移后树不被误伤）且防回潮规则在位（锚真实形态）",
     "python3 integration/t260904-12/sc_no_skip_guard.py", "ro"),
    ("t260904-12-gate-failsafe-envfail",
     "闸 fail-closed 对 ENV_FAIL 执行器输出（t260904-12 甲段核心承诺，KI-046 反面）：fixture verify.yaml+执行器桩输出 ENV_FAIL 行+SUMMARY env_fail=1+rc2 → verify_lane lane=integ green=false 恒真（ENV_FAIL 不可穿闸）；两态分支断言（同 R4 修法①）——甲段态 err 在场且文案点名 exit=2，乙段态 ran=1+scenarios[].exit=2+缺什么尾段在案；对照组 exit0 PASS 桩=绿（夹具有效性自证）",
     "python3 integration/t260904-12/sc_gate_failsafe_envfail.py", "ro"),
    ("t260904-12-gate-supply-ethred",
     "乙段闸 supply 供给面+ENV_FAIL 行解析契约（②a supply 承诺+②b-2 env_fail 必含）：supply 先于 cmd 执行（标记探针先行序）→绿；supply 失败=红点名 need 不静默；supply 声明畸形（缺 cmd）=fail-closed 红给原因；ENV_FAIL 行畸形沿 FAIL 惯例 fallback（name=整行/exit=-1 仍计入）；env_fail 计数入回执且>0=不绿；对照组 PASS 桩=绿。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-12/sc_supply_gate_ethred.py", "ro"),
    ("t260904-12-deregistry-honest",
     "ticket-lifecycle 移册合规守卫（定稿「真跑不进闸」通道，非 SKIP 非豁免的诚实缩围）：SCENARIOS 无该条目（在册恒过=SKIP 复辟变体）；README 移册登记三要素（定稿条款引用/主库人工清单承接/t260831-04 逆转依据=C-c 防口径反复）；场景文件仍在树且非空（覆盖蒸发防线：移册≠删除）；文件 env_fail 护栏语义未被静默 neuter（设计性环境红标记在）；契约 v2.1 变更记录含移册依据。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-12/sc_deregistry_honest.py", "ro"),
    # ---- t260904-15 project lifecycle ticket 3: project-management UI embedded in the left rail (host route thin shell + three additions + three modals) ----
    ("t260904-15-project-ui-host-routes",
     "host 项目路由薄壳契约（t260904-15，API 面无浏览器；t260904-19 起台=docker 测试台 dsh-only 实例，fixtures 根挂 /fixtures、容器内引擎地址钉死不可达回环口=降级断言面）：写路由把请求薄壳转 spawn `sandbar project add|remove --json`——六类拒收错误体逐字透传为 4xx 就地显示数据源（key 白名单/已存在/dirs 缺失/相对路径/根交叉/畸形 JSON 体精确文案不裸抛堆栈）、dry-run 透传且注册表根字节级零变更、成功后 GET /wf/projects 即时出现新条目（左栏读回=装载器消费方，验收12）；读面扩展：quarantined 数组含 key+原因含 <dir>/project.yaml 定位（验收11 隔离行数据源）、空注册表 200 空清单不再 500（首接面）；票计数读路由 spawn list --json 单点取数，Temporal 不可达=降级字段非 500（验收11「—」数据源）；remove 在 Temporal 不可达 fail-closed（dry-run 同闸，契约①a-1）文案含 sandbar up 指路（验收7/13）且零现场变更。与 t260904-10/-14（CLI 语义）intent 不同面：本条守路由透传+读面扩展层。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台依赖缺失=ENV_FAIL 点名（KI-036，不假绿）",
     "node integration/t260904-15/sc_project_ui_host_routes.mjs", "ro"),
    ("t260904-15-project-ui-rail-add-remove",
     "左栏三处就位+图标族换装+接入/摘除旅程（t260904-15，浏览器捕获，mock v5 过稿口径；t260904-19 起 docker 测试台）：组头第五枚「项目设置」svg 图标、「＋ 接入项目」行、隔离 key 红色行（无组头图标）三处在位（验收11）；四视图图标换装 svg 非 emoji、aria-label 齐、点工单列表图标 active 联动保留、侧栏可见文本 emoji 清零（验收11b 渲染面）；接入弹层坏 key 错误就地显示点名原因、合法 key 成功后左栏即时出现新组（验收12）；摘除弹层四步：处置勾选默认全保留、dry-run 清单先行、purge 勾选需输 key 二次确认（错 key 禁确认）、Temporal 不可达 fail-closed 文案就地含 sandbar up 指路（验收13）。与 CLI 场景（t260904-10/-14）intent 不同面：守 UI 呈现与交互旅程。实现落地前红属预期；playwright-core 缺失=ENV_FAIL 点名（KI-036 守卫，不假绿）",
     "node integration/t260904-15/sc_project_ui_rail_add_remove.mjs", "ro"),
    ("t260904-15-project-ui-settings-isolation",
     "设置弹层信息面+隔离详情+空注册表首接（t260904-15，浏览器捕获，与场景② intent 不同面：守信息面/降级口径/空表面；t260904-19 起 docker 测试台双实例）：设置弹层只读 key/显示名/根目录如实呈现；票计数 Temporal 不可达降级「—」类中性提示不红不谎报（验收11 降级口径）；体检区中性提示不含「无黄牌」谎报（R2b 降档口径）；danger 摘除入口在位；隔离红行点击见原因含 project.yaml 定位+修复指路（验收11）；空注册表 GET /wf/projects 200 空清单不 500、零分组仍渲染接入行且首接走通（验收9 空表面）。实现落地前红属预期；playwright-core 缺失=ENV_FAIL 点名（KI-036 守卫，不假绿）",
     "node integration/t260904-15/sc_project_ui_settings_isolation.mjs", "ro"),

    # ---- t260906-01: onboarding a new project from zero (container-style: directory creation + container scaffolding + empty-project entry + route guidance) ----

    ("t260906-01-add-creates-container",
     "新目录容器代建一步接入旅程（t260906-01，ro 隔离注册表根+假 git PATH 桩）：根目录不存在（含父目录链）`sandbar project add --json` 一次成功=root_created+目录代建+容器脚手架全清单（CLAUDE.md 骨架、notes/epics|discussions/.gitkeep、docs/.gitkeep、server/model-routes.yaml）逐项在盘、scaffold.created 机械可判且 skipped 空、模板表与引擎仓真源 sha256 逐字节一致（同源模板不造两份）、CLAUDE.md 与 JSON warnings（container-no-git）含「容器未含 git 仓库」提示、注册条目落盘 key/dirs 可读回；文本形态报告含「生成物清单」「本次代建，含父目录」；全程零 git 调用（PATH 注入记录型 git 桩=调用日志空+项目树无 .git）。与 t260904-10-add-rejections（拒收面）intent 不同面：本条守代建成功旅程。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_add_creates_container.mjs", "ro"),
    ("t260906-01-add-scaffold-faultlines",
     "容器脚手架故障面对抗（t260906-01，ro 隔离根+--root 桩树注入源表三态）：已存在目录接入=项目根树快照逐字节一致（零新增零覆盖，自带自定义 model-routes.yaml 与 marker 不动、scaffold.created 空、root_created=false）；源表缺失与畸形（缺 default:/roles: 结构锚）两态=fail-closed 红+点名源路径+注册表与新建根零残留（回滚含整根与父链移除，绝不吞成空拷贝）；代建×防呆闸交互=新根为已注册根的「尚不存在」祖先仍被闸 d 拒（拒后祖先不被代建=闸序在 mkdir 之前的锚、注册表快照不变）。F1 并发同根异 key TOCTOU 为已登记预存洞（本票不修），不入闸防并发假红。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_add_scaffold_faultlines.mjs", "ro"),
    ("t260906-01-routes-uninitialized-init",
     "路由无表引导态+一键初始化（t260906-01，API 面无浏览器，mock webServer 手法同 ui smoke E 段、进程内 apply 零 3099 接触）：无表项目路由视图=uninitialized+template_source 引导态非 error（红错退役——运行时本就回落默认模型，无表≠故障）；畸形表=解析失败红错不降级为引导态（三态：畸形 fail-closed）；POST /sandbar-admin/api/routes/init 对无表项目=建父目录+原子写引擎真源表（写入与引擎表逐字节一致、无 tmp 泄漏）、对已有表=拒收零覆盖（放用户自有表再 init 断言内容不被冲掉）、init 后 GET 视图出表（uninitialized 消失、default 可解析）。wire 口径=project 走 ?project= 查询参（与同族 GET 一致）。与 t260904-15-host-routes（workbench 薄壳透传面）intent 不同面：本条守 ui 路由视图自身契约。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_routes_uninitialized_init.mjs", "ro"),
    ("t260906-01-session-entry-empty-labeled",
     "空项目会话入口可发现+弹层代建口径（t260906-01，workbench 客户端 src+lib 双锚灰盒，同 project-sessions.mjs S3 守卫手法）：账册空=「＋ 新建会话」带字按钮锚（wb-psess-new-labeled 变体+tabs.length===0 条件分支）在 src 在场、lib/client.js 同批在场（lib 锚=bundle 重建看守，KI-052 客户端半从盘现读——盘上 bundle 旧=改了也看不见）；data-wb-psess-new 数据锚与 24px 方块样式保留（有 tab 恢复现行形态、既有 smoke 旧断言不回归）；接入弹层预检口径退役「存在性」措辞、改「自动创建」。真 DOM 呈现归合并闸 ui_evidence 截图证据面（KI-036/044 家族），不重复 browser 腿。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_session_entry_empty_labeled.mjs", "ro"),

    # ---- t260904-18: three new gate contracts (refs ticket-creation gate / files_changed receipt shape / declared-form ui_evidence) ----

    ("t260904-18-refs-gate",
     "建工单背景文件闸（t260904-18 门①，宿主令「没提交的 note 不让建工单」+知识库设计 §1 工单引用铁律，灰盒 L2/L3）：票面 refs 引用未提交背景文件=建单即拒且报错逐个点名文件——三分类（工作区脏改/暂存未提交=已跟踪≠已提交/不存在）经真 git 夹具仓 HEAD 态驱动；畸形引用（绝对路径/含 ..、非列表字符串=逐字符假护栏形态）拒收点名不静默清洗；拒收路径零 Temporal 接触（校验接线先于 cmd_ticket_start 首个 _connect 的源码序锁；存量票无 refs 不追溯=backlog 口径）；闸回执形状不锚定（布尔/元组/dict/异常皆容错解释）只锚「拒+点名」。与 t260904-02-ticket-start-anchor（project 锚定闸 KI-032）intent 不同面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（入口装配腿），stdlib 闸行为腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260904-18/sc_t260904_18_refs_gate.py", "ro"),
    ("t260904-18-ki049-write-set-contract",
     "files_changed 回执形状×写集刷新缝上契约+机制活性巡检（t260904-18 门②，KI-049 修复面②③④，灰盒 L2）：以真实 agent 回执形状喂解析→刷新链（mock 填满字段掩盖过的缝）——字符串回执（「叙述写了补列、字段没填」姊妹形态）不得在解析层毁形成单字符列表（毁形强转三解析点退役=源码负锁，normalize 拒形 shape=malformed）；畸形与空数组在消费点=可见红 meta.write_set_refresh_fault+告警点名+不调 refresh（写集零污染）且不得再出「写集已随方案定稿刷新」中性行冒充成功（报错必须精确）；None 维持跳过语义（selfcheck 在场锁共存）；no_file_changes 在案豁免；合法非空回执→「授权扩展」日志非零（dead-man 开关：机制全史 0 次生效的死亡形态从此有断言网）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（解析缝/消费点行为腿），stdlib 链腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260904-18/sc_t260904_18_ki049_write_set_contract.py", "ro"),
    ("t260904-18-ui-evidence-declaration",
     "ui_evidence 声明制（t260904-18 门③，KI-050，灰盒 L2/L3）：UI 截图证据目录由项目声明（verify.yaml 顶层 ui_evidence）——verify_lane 白名单收该键（未知顶层键 fail-closed 雷 t260903-11 同位不触发）、dirs 畸形=红点名字段（契约②三态总纲：畸形≠缺省）、缺省=merge_check 截图项 green+可见 note「未声明」（行为可见非静默，非 SKIP 非假绿）、有声明+diff 命中=无 png 仍红（闸没松）、diff 故障=红不因缺省豁免（对照腿）、有声明+未命中=不出项（拓扑级缺席）；load_ui_evidence 三态；sandbar 五路径迁入仓根 verify.yaml（迁移等价 rod：声明集合≡legacy 表）；review_gate 接线源码锁（UI_EVIDENCE_DECL_PATCH_ID+meta 预载 ui_evidence_dirs）。与 t260904-13 三场景（判定源/闸输出/接线编排，KI-044 面）intent 不同面：本条守声明制新契约面；与 contract-v11-regression-rods（v1.1 勘误面）不同层。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（merge_check 行为腿），verify_lane/声明腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260904-18/sc_t260904_18_ui_evidence_declaration.py", "ro"),
    ("t260904-19-stage-docker-cli-contract",
     "docker 测试台唯一搭台入口的 CLI 对外契约缝（t260904-19，灰盒 L2）：up 产出场景可直接消费的 JSON（project/temporal 非空、127.0.0.1:<int> 形）、down 幂等二连且拆台后端口立即可复用（验收④）、docker 缺席=exit 2+ENV_FAIL 点名 docker（验收③三态）与 test-temporal 镜像缺席=exit 2 点名 build-test-temporal.sh 两文案可辨、畸形工程名非零拒收且输出点名 project 且零残留；生产端口 {3099,7233,8233} 绝不返回（3099 红线=CLAUDE.md 硬规则1）；bind 探测器占用/空闲两态自证防恒真。断言只锚 CLI 进程级公开行为（退出码/stdout JSON/docker ps 公开观测面/socket 可连性），契约不变的实现重构不得打破。与前层分工：helper 内部机制（档位锁/分配原子性/畸形全电池）归 developer L1 test_stage_docker.py，本场景守真进程消费缝（KI-049 同族：mock 单测覆盖不到缝契约）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-19/sc_stage_docker_cli_contract.py"),
    ("t260904-19-stage-docker-parallel-zero-residue",
     "双场景并行不互撞+拆台零残留端到端（t260904-19，灰盒 L3，工单验收①④；槽位制退役后并发隔离语义的用户级承接面）：两个 up 进程真同时发车（各自 compose 工程名，temporal-only 档）双台健康、JSON 端口互异、双双 ∉ 生产端口 {3099,7233,8233}；docker ps -a 按 com.docker.compose.project label（compose 公开语义）过滤 A/B 容器集互不相交且 temporal-only 恰 1 容器；拆 A 后 A 端口立即可 bind 且 B 台 TCP 复测仍活（down 爆炸半径恰一个工程）；full 档 console+temporal 双端口真活（helper exit 2=其判环境红不诬产品）；三工程终态零残留、全部用过端口立即 bind 成功（验收④收口）。与 developer L1（档位锁/分配原子性单测）intent 不同层：本条守进程级真并发系统行为，mock 与先后错开都替代不了该形态。资源口径：有意制造并发双台+一次 full 台（dsh 镜像烤制后起台秒级；建镜像才联网，见 build-test-dsh.sh），登记 exclusive 独占执行防与兄弟场景的台互相污染判定面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-19/sc_stage_docker_parallel_zero_residue.py", "engine"),  # engine: 3 concurrent stages on purpose — daemon-pressure canary (loud ENV_FAIL surface accepted)

    # ---- t260905-03 inspection ticket 1 (scheduled quality-check skeleton + test-surface scan) ----
    ("t260905-03-ki051-anchor-replay",
     "KI-051 守卫锚×生产方措辞漂移静态回放必抓（t260905-03 验收②主证据=KI-051 事故回归用例，灰盒 L2）：真形态夹具（生产方在位——模板拼接旧字面搜不到，即 KI-051 实录 capture.mjs L342 形态——+守卫断言旧字面）扫描必报 high 且证据双点名守卫与生产方；健康对照（字面在场）零误报 high；无法确证（生产方在位但措辞无近亲）降级 med 提示交人审，不判绿不静默；空壳守卫不崩。纯 stdlib 夹具零 env 依赖零真仓接触——环境红永远捂不住本断言面（KI-051 被 env_fail 捂数日的教训内建）。与 developer L1（扫描纯函数真值表）不同层；与 t260904-08 模板退役负扫描不同面（彼守退役类名零活引用，本守在役守卫锚×生产方措辞在场性）。扫描器 CLI 与 findings 形状为本票场景侧裁定（integration/t260905-03/lib_inspection.py 头注）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_ki051_anchor_replay.py", "ro"),
    ("t260905-03-scan-contract",
     "测试面扫描器对外契约（t260905-03，灰盒 L2 固定夹具）：findings[{id,severity,scan,evidence,suggestion}] 五键齐/severity∈{high,med,low}/id 唯一/证据非空；重复场景检测阈值两边界——intent 近逐字重复对必报 med（不混 high 混淆严重度）、不同守护面条目不误报；过时断言（引用资产缺席/已挪、行号越界）必报且证据点名缺什么（报错精确）；干净树=ok:true+findings==[]（全绿期零发现心跳的数据面，非静默）；红线判定化——扫描全程被扫树逐字节校验和不变（巡检绝不直接改码）；二进制乱码被扫输入不崩仍结构化回执。纯 stdlib 夹具零 env 依赖。与 t260905-03-ki051-anchor-replay intent 分工：彼守 KI-051 事故四面，本条守扫描器横向契约（步骤共享 lib 夹具构造器，intent 不同面不互替）；与 developer L1 不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_scan_contract.py", "ro"),
    ("t260905-03-decl-gate",
     "声明门——触发面尊重 inspection.yaml（t260905-03 验收③行为级证据，灰盒 L2/L3）：畸形声明拒绝且理由指向声明本身（报错精确：声明错不得报成连不上——KI-051 环境红捂真红的反向教训）；启用实例声明未接线 kind 拒绝并点名该 kind 与已接线清单（fail-closed 不静默不触发，M2 口径）；enabled=false 占位实例与未知实例拒绝并点名；enabled 实例放行回执带票号（改声明改行为的放行半边）；同期重复触发回执仍指同一张票（每期一票机械保证=scan_schedule 照搬取舍① overlap=SKIP 的用户级承接）。三态分级：拒绝腿=交付触发面离线校验（--decl-path，纯标准库零网络）闸内即验；放行腿缺 temporalio/共享台=ENV_FAIL 点名（不假红不假绿）。与 developer L1（decl 解析真值表）不同层：本条锁触发面的门行为；与 t260905-03-period-journey 不同面（彼守链路质量，本守谁能跑/谁被拒）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_decl_gate.py"),
    ("t260905-03-period-journey",
     "手动一期全链用户旅程（t260905-03 验收①主证据，灰盒 L3 真台真票，exclusive）：temp decl 双实例启用+--decl-path/--repo-root 注入夹具（真仓是干净的，不种漂移测不到发现落面；真树零写入红线不破）——种漂移实例：trigger→开票→发现清单落票面（high 带证据+suggested_fix_tickets 逐条 source_inspection=本巡检票号=修复票溯源面）→人门两拍（未签字观察窗内不终态=假门现形即红；运维通道 sign 后收口且发现留存票面=发现/处置审计链不断）；干净实例：零发现心跳票照开照收（全绿期=心跳证明）；两实例票号互异（实例维度不串票）。人门绑定浅：只锚公开 sign 面与终态可见，不锚 snapshot 内部门名。temporalio/共享台缺席=ENV_FAIL 点名（KI-036 家族口径）。登记 exclusive：往共享台写真票，防与兄弟场景互染判定面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_period_journey.py", "exclusive"),  # exclusive: the ONLY barrier entry — writes real tickets to the shared default 7233 temporal (mutex with main-pool decl-gate on the same surface)

    # ---- t260910-09: inspection ticket 2 (mechanism/simplify faces — dead-man generalization + patch-retirement) ----
    ("t260910-09-ms-scan-contract",
     "机制/简化面扫描器对外契约（t260910-09 主证据，灰盒 L2 固定夹具，纯 stdlib 零 env 依赖）：新两面 CLI 单行 JSON {ok,result|error} 同票①、result{face,findings,summary,heartbeat,meta} 形状齐、findings 六键/severity 三值域/id 唯一/证据非空（UI 巡检行通用消费的数据面承诺）；dead-man 正例=三重零命中（场景零引用+日志字面零命中+代码路径零调用）必报 med 且证据含 文件:行+带分母零计数（0/N 形——空集≠查过零，review C2 口径；零日志字面机制仍判，日志面空集不得当豁免）、meta 记录「全史」口径局限（方案 D2 不静默承诺）；反例三连=场景引用/被调用/注册表豁免任一命中即不报（并集破零）、在役函数零误报；影子代码=零调用+新旧命名对必报 med 且在役侧不报；补丁退役=*_patch 宿主被 v2 取代必报 med 且 suggestion 含「删了会怎样」风险注（本票硬性口径）；重复防御层 med；过长/过深点名 low（显著超阈 120 行/深 8 必点名、显著低于 40 行/深 2 不误点名——阈值精确边界 80/81 真值表归 developer L1）；零发现=findings==[]+heartbeat true（全绿期心跳票数据面，语义与票①逐字段同构）；红线判定化=两 face 扫描全程被扫树逐字节不变（巡检绝不直接改码）；畸形输入不崩（NUL 乱码模块逐项降级 meta 点名不株连、仓根缺失 ok:false+非零退出+error 点名路径 fail-closed）；真仓 smoke 两 face 只读可跑（发现量级不 pin，沿票① 腿8 口径）；face 分派缝=activities.run_inspection_scan 缺省（无 face 键）走 test 既有语义零变化、face=mechanism 走新面、未知 face ok:false 且 error 点名已知面清单（腿需 temporalio=venv 重入，缺席 ENV_FAIL 点名不假红）。与 t260905-03-scan-contract intent 不同面（彼守测试面 S1/S2/S3 契约，本守新两面）；与场景②不同面（彼守声明位与门数据面，本守扫描行为本身）；与 developer L1 不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260910-09/sc_inspection_ms_scan_contract.py", "ro"),
    ("t260910-09-ms-decl-gate",
     "新巡检实例声明门——mechanism-face/simplify-face 声明位与门数据面（t260910-09，灰盒 L2 离线腿为主）：仓内 inspection.yaml 两新实例在场（face=mechanism/simplify 原样、enabled=false 占位）且不进 schedule_specs（「enabled 按宿主节奏」+零发现心跳票语义不变的声明半边=不调度不触发；声明是引擎解析器逐期读取的机器契约，守卫合法非快照 pin）；夹具声明 enabled 新实例进 specs 且 face 原样透传、disabled 不进（改声明改行为、decl 零改动承诺的数据面）；enabled 新实例过门真触发腿（回执带票号）缺 temporalio/共享台=ENV_FAIL 点名不假红（沿票① decl-gate 三态分级）。与 t260905-03-decl-gate intent 不同面且不重测：彼守门行为本身（畸形/未接线 kind/占位/未知四类拒绝+test-face 放行——新实例同走该门不另测，防 intent 级重复），本守新实例的声明位在场与 face 透传数据面；与 developer L1（decl 纯函数真值表）不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260910-09/sc_inspection_ms_decl_gate.py", "ro"),
    # ---- t260905-02: engine-behavior scenario watch (worker lifecycle / settle self-exit / multi-console dedup; epic follow-up faces) ----

    ("t260905-02-worker-lifecycle",
     "工单专属 worker 进程生命周期（t260905-02 行为①，灰盒 L3，docker 舞台）：起=归属 meta（SANDBAR_WORKER_META 指路）限期落盘可解析且形状可辨（pid=真 pid、repo_root=realpath 引擎仓、ts 可解析、version 非空——KI-033 契约数据源面）；退=SIGTERM 限期优雅退出（退出码 0 非崩溃形态）+meta 自清+TERM 二连幂等不炸；异常输入=meta 指向不可写路径（父路径是文件）写失败不阻断启动（best-effort 契约）、起跑痕迹在文（stderr 归属指纹行）、路径上不冒出 meta、TERM 后照常干净退。与 t260904-02-worker-fingerprint-gate 分工：彼=ensure 消费侧三态判定（同仓/异仓/未知），本条=worker 进程侧自身生命周期（TERM 后 meta 被清一面两处观测不互替）；与 t260905-02-ticket-worker-watch-exit 分工：彼=watch 联动自退（自己走），本条=外部信号停（被叫走）。被测子进程零连生产（审计钩子+自证腿）；日志锚兼容正则锚语义（KI-051）",
     "python3 integration/t260905-02/sc_worker_lifecycle.py", "engine"),  # engine: one docker stage + real worker (TERM leg)
    ("t260905-02-ticket-worker-watch-exit",
     "收口自退不留尾巴（t260905-02 行为②，灰盒 L3，docker 舞台+真工单）：票收口（workflow 非 RUNNING 终态）→ watch 中的专属 worker 限期自退（退出码 0、收口语义日志在文、meta 自清）——工单收口后不留常驻 worker（260824 A 案：专属 worker 生命周期跟工单走）；孤儿收养自退=宿主死（worker 被收养 ppid=1）→ 自退不留无主 worker（85222 版本投毒教训；收养目标 ppid 随环境为系统状态条件腿，收养不到时按 N/A 折算）；查询失败不误退=watch 指向不存在 workflow → worker 持续存活 ≥ 两轮 watch 周期且留下「查询失败下一轮再试」痕迹（宁可多守一轮，不许票没守到人先走）。watch 生效前提两 env 同置（SANDBAR_WATCH_WORKFLOW 置时 watch 循环才存在，ppid 守护在循环体内）；watch 间隔旋钮 SANDBAR_WATCH_INTERVAL_SEC 提速（「≥两轮」按日志实际轮次判：旋钮生效 ~4s 收工、失效自然回落 30s 慢档 90s 窗内同判，语义不弱化）。与 t260904-02-worker-fingerprint-gate（ensure 消费侧）与 t260905-02-worker-lifecycle（外部信号停）intent 不同面",
     "python3 integration/t260905-02/sc_ticket_worker_watch_exit.py", "engine"),  # engine: one docker stage + worker + watch-timing legs (load-flake watch surface)
    ("t260905-02-console-duplicate-guard",
     "多 console 同槽防重与辨析文案（t260905-02 行为③，灰盒 L2/L3，docker 舞台+node 直跑 node.ts）：server 单例=同槽已有监听者第二 console 静默认领（不重复 spawn 不报错）；worker 单例=daemon pidfile 在册双 console 均不重复拉起且 dispose 不动在册他人 worker（资源归属）；工单 worker pidfile 抢注互斥=同 tid pidfile 位被占（'wx' 确定性必败注入：目录占位，非时序竞态）→ 辨析文案在文且点名 tid（「已被别的实例抢先注册，停掉重复 spawn」语义）、重复 child 当场 SIGTERM 回收（日志 fd 持有者归零观测）、无成功 spawn 文案（不两开花）；dispose 收口=幂等二连不抛、定时器清空（node 自然退出=事件循环空，挂死=超时红）。与 t260904-02-worker-fingerprint-gate 分工：彼=ensureTicketWorkersOnce 纯决策面三态（spawn 可注入），本条=apply 全真路径双 console 防重（纯决策面不含 'wx' 互斥分支，替代不了）。被测 python 子进程零连生产（apply 内部 cli/ensure 的 TARGET_HOST 由子进程 env 钉舞台；审计钩子+自证腿）",
     "python3 integration/t260905-02/sc_console_duplicate_guard.py", "engine"),  # engine: writes real repo server/engine/data (no pool scenario reads that dir)

    # ---- t260905-01: the two settle questions (distillation trigger + reverse-sync gate, doc-lifecycle ticket 2) ----

    ("t260905-01-doc-gate-questions",
     "收口两问防回退守卫（t260905-01，灰盒 L2/L3）：触发器/闸各带防回退——源码锁半（处处可跑）：STAGE_ACCEPTANCE_EXTRA[acceptance_walkthrough] 两问文案在位（沉淀+从 deliverables 推预填建议+矛盾反向同步+转正纪律句=债登记纪律进流程的流程落点）、agent_activities 判读纯函数三件套（parse_doc_gate/register_pending_doc_sync/apply_doc_gate）定义与 acceptance 返回路径调用位在场（触发器被整段拆除=红，防「实现与单测共谋删除」回退）、pending-doc-sync.jsonl 债册常量、dev_lane STAGES 走查块两问验收项；行为半（temporalio 面）：parse 正常两态/显式无可沉淀≠未答/两问缺席各自可辨（per-question absent）/畸形软降级不抛，register 登记→条目本体可查（验收②）/同键幂等去重/actual 演进=新条目（append-only latest-wins）/torn 行容忍/写失败降级不抛，apply 回执拼装两问小节+矛盾条目本体全量+转正句（验收①②拼装面）/未答也是一条记录（不答不阻塞有实证）/文件级畸形软降级（KI-012 面不新增爆面）/failed 轮不抛不翻 status（不阻塞双态保持）。切块器自证红绿先行（干净/注入/缺席三样本）。与 developer L1 纯函数白盒不同层：本条另守源码锁与回执契约面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（行为腿），stdlib 源码锁腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260905-01/sc_doc_gate_questions.py", "ro"),

    # ---- t260905-06 workbench "docs" entry (human-readable docs/notes view; the "knowledge base" wording is retired) ----
    ("t260905-06-doc-entry-present",
     "「文档」入口在场且键盘可达（t260905-06，隔离台浏览器走查=工单验收①）：左列项目组头图标枚原位（17 号栅格语言）存在 aria-label/title=「文档」图标、aria-label=「知识库」旧入口不在场（提法退役的入口面，字样清零由场景③专守）；图标可键盘聚焦+Enter 触发中列切视图（用户可感知面=发起 GET /api/wf/docs/tree?scope=docs 且 200 目录加载）+图标进入 active 排他高亮态。复用 lib_fix17 隔离台（临时注册表根+夹具项目；真库 docs/notes=泳道仓根 committed 内容，服务端 DEFAULT_REPO 直读，不向仓根写夹具防污染）。playwright-core 缺失=env_fail 点名（KI-036 家族，闸内无 SKIP）；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-06/sc_doc_entry_present.mjs", "ro"),
    ("t260905-06-doc-read-through",
     "目录→篇→正文真渲染+notes 观察窗+移动窄栏（t260905-06，隔离台浏览器走查=工单验收②⑤与「移动窄栏可用」）：API 契约面（真库）——tree?scope=docs 200 含锚篇目（README.md/terminology.md）且 skipped 拒收可见性字段在场（人读视图完整性可判定）、scope=notes 200 含 notes/README 与 epics/ 篇目、doc?scope=docs&path=terminology.md 200 含「项目术语表」、穿路径（../package.json）fail-closed 非 200 或 empty+reason 且不外泄内容；UI 链路——目录出真库篇目→点篇正文真渲染（「项目术语表」「测试环境隔离指南」标题文本在场）+围栏代码块 computed font-family 含 mono（代码块等宽）；notes 页签切换后 notes 篇目在场；窄栏腿=review V1①基线对照口径、容器级落地（壳在窄视口卸载本插件槽=视口级断点不可达，探针实证；宽栏量全局溢出基线→文档视图容器压 360px 触发 @container 单栏流→返回钮往返+再开篇可达→断言不新增全局溢出）。断言锚=真库 committed 稳定篇目（真库即夹具：天然覆盖 frontmatter/中文路径/嵌套形状，零夹具写入）。playwright-core 缺失=env_fail（KI-036 家族）；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260905-06/sc_doc_read_through.mjs", "ro"),
    ("t260905-06-docs-wording-retired",
     "UI 层「知识库」字样清零（t260905-06，静态 grep=工单验收③）：workbench 界面层源码 src/**+构建产物 lib/**（随仓提交、隔离台实际加载面）grep「知识库」全词 0 命中（注释含，命中=用户可见旧提法=产品红）；断言面缺席（目录不在）=env_fail（构建管线异常非产品红）；对照面自证——同一 grep 通道在写集外 knowledge 插件目录命中>0，防「grep 挂了恒 0」假绿。node.ts 宿主半与 knowledge 插件自身不在界面层断言面（写集外存量欠账另账）。实现落地前红属预期（现源码含字样，TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-06/sc_docs_wording_retired.mjs", "ro"),

    # ---- t260905-09: platform self-launched context moved into a fold (ticket 16 only folded its own injection — host-reported 260906) ----
    ("t260905-09-platform-anchor-contract",
     "平台内容锚交付契约冻结（t260905-09，ro 静态面，KI-042 同族防漂移）：平台自启上下文折叠靠「渲染面对平台恒定文本的内容锚」（注入源在宿主二进制，仓内无字符串可对），锚真源模块（platform-context-anchors.ts）↔取证夹具（fixtures 首行=锚固定样本+%%% 尾注取证来源）逐字同步——改锚不回夹具/夹具漂移无人知=折叠件对过时文本匹配静默失明；负向样本排除在真源层在文（中段提及普通消息文本不进锚清单=误折防线）；前缀粘贴声明腿（粘贴首行恰为在册锚=设计内不可分辨限制有夹具背书，平台 wire 契约 PromptContentPart 无 metadata 字段）；折叠件对锚模块的引用在文（锚定了空气=平台上下文永不折）。与 t260904-07-charter-source-contract intent 级不同层：那条冻结 charter marker 两端同源，本条冻结平台锚↔取证样本↔接线三点。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-09/sc_platform_context_anchor_contract.mjs", "ro"),
    ("t260905-09-platform-context-fold-stacked",
     "平台上下文叠台折叠用户旅程（t260905-09，browser 隔离台 3199 拒 3099，工单「怎么算好」原话可执行化）：夹具把平台启动上下文消息×N+工单台 charter 注入×1 叠进同一会话——16 号验收台只测自己注入腿、台面无平台叠加=假绿（宿主实报「还是显示了一堆，只折叠了开头一小部分」）。主断言=恰一个小条（不是 charter 一条+平台又一条，「同一折叠件」原话）+全部候选正文收折（含同气泡双锚去重样本）+点小条整组开/收；负向=中段提及普通消息全程可见零误折（普通用户消息绝不折）；孤儿守卫=夹具气泡移除后小条随摘无幽灵、reload 不复活；console 卫生=零 pageerror（外来节点×React 重渲染崩溃在此现形，证据上报归因不静默）。归因三态：锚真源不在=fail（TDD 信号）、源在而 served bundle 无锚样本=na（未重建/未部署，merge 期自动生效）、行为不符=fail 精确点名。charter 注入腿本身由 t260904-07 journey 守（intent 级不重复，此处只当前置卫兵）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-09/sc_platform_context_fold_stacked.mjs", "browser"),  # chain: shared-console writer — in-session platform context stacking

    # ---- t260905-10: engine immunity against three incidents (interpretation injection channel / torn-session quarantine / on-disk identity dependency) ----

    ("t260905-10-host-ruling-injection",
     "blocked 态宿主裁决注入→arbitrate 下轮 prompt 可见（KI-053 端到端，灰盒 L3，docker 舞台+真工单专属 worker）：SANDBAR_AGENT_CMD recorder 桩（spawn 单点全口径覆盖，含 arbitrate 直 spawn 面）把引擎递来的 prompt 原样落账本=mock 端点收到的 messages 等价观测面；桩回执恒缺 verdict= 标记→三次格式纠正 blocked(arbitrate)（引擎既有契约路径）；blocked 态 client op=ruling 注入（只入账不唤醒）+retry_qc 唤醒→arbitrate gen+1 轮 prompt 含裁决文本与裁决人、注入前各轮不带（对照）；全文兜底 meta.host_rulings 与事件历史 log 留痕经 query 可查（{ts,who,note} 形状、ts 留痕）；拒收两态=超大 note intake 闸拒收进 refused 不入账（不进 Temporal 事件历史）+纯空白 note 绕过 client 直发信号层拒收（钉 workflow 侧契约非仅 client 包装）；多条裁决累积全可见且旧→新排序（最新贴着现在）；被测子进程零连生产（审计钩子）。断言面=recorder 账本/快照，不锚 prompt 小节标题文案（实现副本）。实现段落地前红属预期（host_ruling 信号缺席=点名红），arbitrate/merge 期必须绿；与 developer L1（build_stage_prompt 纯函数单测）intent 不同面：本条守 signal→meta→prompt 全链真 Temporal 编排行为",
     "python3 integration/t260905-10/sc_host_ruling_injection.py", "engine"),  # engine: real workflow + ticket-private queue, POLL 60/180 timing legs
    ("t260905-10-torn-session-quarantine",
     "帧好内撕裂会话检疫隔离+同 id 新建走得通（t260905-10 面②，05 号 260906 两次卡死同型，灰盒 L3）：zstd 帧完整但 JSONL record 中截断→spawn 前检疫挪隔离区留档；好帧内非 JSON 行同判；健康对照组=多行合法 JSONL×多帧拼接（真实形态）不检疫（防「见档就隔离」反向事故）且同批健康会话不连坐；同 id 原路径重写合法档再检疫不动（恢复旅程）；挪不动（隔离路径不可建）不抛坏档留原位（既有兜底）；空文件/二进制既有 zstd -t 路径回归；裸空行容忍不判撕裂（合法 JSONL 容忍面，防误隔离）。断言面=文件系统结果，零网络零 docker。实现段落地前红属预期（逐行试析缺席=好帧内撕裂不挪=红），arbitrate/merge 期必须绿；与 developer L1（单函数腿）intent 不同面：本条守会话档族整批判定与恢复旅程",
     "python3 integration/t260905-10/sc_torn_session_quarantine.py", "ro"),
    ("t260905-10-lane-identity-guard",
     "泳道落盘身份依赖守卫（t260905-10 面③，260906 宿主 ~/.gitconfig 消失三轨 settle 全 FAILED，灰盒 L3）：git 身份全缺→prepare_workspace 开工前 ok=False/failed 红字点名 user.name/user.email（半缺腿钉死点名精确性，探针 GIT_CONFIG_NOSYSTEM+GLOBAL 夹具防系统级假红）；身份在位复用不受扰；repo 级 config 补救放行（探针锚泳道 worktree=共享主仓 config）；dir 型工作区无 commit 不查；created 路径缺失失败且泳道不落半成品（fail-fast 在 worktree add 之前）；LANE_DEP_SYMLINKS 含 engine/.venv：泳道自动软链解析到主仓、幂等不重复（260825「泳道无消费方」拍板被 260906 19 号闸实测推翻的陪伴断言）；点名断言解析「git 身份缺失（…）」括注为集合（处置句恒提两键名，子串断言吹不了精确性）。实现段落地前红属预期（守卫缺席=缺失腿照旧放行=红），arbitrate/merge 期必须绿；与 developer L1 intent 不同面：本条守 prepare_workspace 两分支×身份矩阵×deps 软链的回执契约",
     "python3 integration/t260905-10/sc_lane_identity_guard.py", "ro"),
    ("t260907-04-naming-grep-assert",
     "命名清理① grep 断言守卫（t260907-04 验收①，宿主令「名字的清理要搞干净」）：写集（engine+server/tools+integration）内 suyou 旧字面量只许在已声明兼容面——LEGACY 标识行 / naming-compat 显式标记行（目录回落/镜像/场景 fixture 造旧目录）/ README 退役账行 / L1 负断言源码与守卫自身（断言面≠消费面）/ 插件面文件名引用（出界不动册，另一票面）；并断言 README 退役账 ≥7 行在册（防撤了半截，退役必连守卫带账一起动，锚退役语义不锚措辞——KI-051 写作纪律）；扫描器自证红绿。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260907-04/sc_naming_grep_assert.py", "ro"),
    ("t260907-04-env-compat-bridge",
     "SANDBAR_*/SANDBAR_* 环境变量过渡契约（t260907-04 正文①，灰盒 L3 锚 env 契约不锚实现）：仅旧名环境引擎解析到值（存量脚本/文档/用户 shell 不炸）、仅新名生效、冲突新名优先、新名空串回落旧名（falsy 语义不静默改义=畸形输入腿）、apply_env_compat 桥幂等（import 时序外的显式重跑通路两次调用不改写环境）。与 developer L1（shim 单函数 UT）intent 不同面：本条守子进程级引擎解析行为（import 时序即被测面）。实现段落地前腿 2/3/5 红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-04/sc_env_compat_bridge.py", "ro"),
    ("t260907-04-lane-dot-dir-sticky",
     "泳道目录 .suyou/→.sandbar/ 过渡契约（t260907-04 正文③「既有在飞泳道不炸」）：纯 .suyou 在飞泳道恒旧名且不造新名目录（粘滞+读侧回落）、全新 base 落 .sandbar（创建侧换新名）、两名并存恒新名（镜像目录不参与解析）、R-1 全链钉=新 base 首写后镜像造出 .suyou 解析仍新名（防权威目录中途翻转、非镜像产物静默缺损——t260907-04 review 实锤缺陷 R-1 的回归钉）、十次解析稳定无隐状态漂移。与 developer L1（resolve 函数 UT）intent 不同面：本条守跨进程解析语义与翻转注入。实现段落地前红属预期，arbitrate/merge 期必须绿",  # naming-compat
     "python3 integration/t260907-04/sc_lane_dot_dir_sticky.py", "ro"),
    ("t260907-04-dispatcher-lock-fallback",
     "总管单例锁改名过渡（t260907-04 server/tools 引用面）：接管写锁/他人持新锁只读不派不续写/过期接管三态 + 旧锁（suyou-dispatcher.lock）TTL 内视为 held（防新旧 dispatcher 实例并行双派——过渡回落半边）+ 旧锁过期接管写新锁且旧锁只读不写不删（只回落不续命）。锁路径常量动态发现替换 temp 副本——不碰真 /tmp 锁（真 dispatcher 可能在跑，写它=干扰生产面）。实现段落地前腿 4/5 红属预期（旧锁回落未落地），arbitrate/merge 期必须绿",  # naming-compat
     "python3 integration/t260907-04/sc_dispatcher_lock_fallback.py", "ro"),
    ("t260907-04-queue-dual-registration",
     "worker 队列注册契约（t260907-04 验收②，260908 终切翻面——空库重建窗口零兼容负担）：缺省启动单名 poll 新队列 sandbar、suyou-poc 不双 poll（撤双 poll 的负向守卫，复活即红）；显式列表 env 声明的队列名照单全收；显式旧名单值 env 仍服务旧前缀队列（显式声明面≠默认推导面）。docker 舞台 stage_docker 单点（docker 缺席/镜像缺席/起台不健康=ENV_FAIL 点名缺什么），SDK 走 poc venv。腿1 红=双 poll 复活",  # naming-compat
     "python3 integration/t260907-04/sc_queue_dual_registration.py"),
    ("t260907-04-schedule-legacy-retire",
     "dispatcher-scan schedule 服务端持久标识改名退役（t260907-04）：Temporal schedule 改 ID 旧对象不会自己消失——种子旧 ID 在台→跑引擎创建走廊（仓内唯一在树创建点 demo_schedule.demo_schedule）后新 ID 在旧 ID 亡（防新旧双份调度——review gen0 缺口2）→再跑一次幂等（旧 ID 仍亡、不炸）。docker 舞台 stage_docker 单点，缺台/缺 SDK=ENV_FAIL。实现段落地前腿 2/3 红属预期（删旧未接线），arbitrate/merge 期必须绿",
     "python3 integration/t260907-04/sc_schedule_legacy_retire.py"),
    ("t260907-05-naming-residue-fulltext",
     "命名迁移②收口：旧命名 token 全量残留清点（t260907-05 验收①独立机器重演，灰盒 L3）：七 token（六插件包名 suyou 前缀族＋tools 文件名旧形）在 server/+integration/ 全后缀零残留（无 include 白名单——方案 v1 白名单漏 tsx/py/cjs 的教训收编为本条设计依据；豁免列名仅历史验收记录 t260903-12/acceptance-walkthrough-gen0.md 与本票守卫场景族自身——针脚字面量写在断言里非产品面，活文档不豁免）；docs/ 命中封口在已声明遗留票清单内（工单工作流台设计/知识库设计/docs README/build_index.py——本票不改 docs 但清单外新命中=替换面外溢即红）；正名在位（六插件 package.json name 全 sandbar-*、五份 lock 双处 name 同步）；不动面原样在位（/sandbar-admin/ 前缀、project-registry.ts、dsh-profile-suyou 包名——机械替换「顺手多改」的对抗腿，doc-guard G6 先例钉现状语义，后续票落地随其语义同步改）。与 sc_profile_farm_sandbar_links intent 不同面：本条守文本面收口，彼条守装载链结构一致性。Hermetic 纯文件读秒级；实现段落地前红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-05/sc_naming_residue_fulltext.py", "ro"),
    ("t260907-05-profile-farm-sandbar-links",
     "profile 软链农场重指一致性（t260907-05 验收③＋正文③④，灰盒 L3）：装载链每环同指新名——cordis.patch.yml id/name（装载声明）==node_modules 裸包名解析锚（软链名）==插件 package.json name（包真源），任一环留旧名=宿主重启边界上插件消失/重复/import 炸给用户看；tools 文件名旧形→新形四环同步（真身在位+内部注册名+两 profile 软链 realpath 命中+三处 import）；两 profile 农场五链（sandbar-{admin-ui,workbench,knowledge,providers,temporal-tools}）realpath 指对实际目录、旧 suyou-* 链零残留；headless/cordis.patch.yml 必须仍是指向 profile 真身的软链（被换独立文件=两 profile 声明可静默漂移，「两 profile 都改」机制保障被掏空）。对抗面=链指错层/拼写差一字/漏 headless/漏删旧链/mv 漏改 import——逐环独立断言不信任单点自检。与 developer L1（单插件行为）与 sc_naming_residue_fulltext（文本收口）intent 不同面：本条守软链结构三方一致。Hermetic 纯文件系统读秒级；实现段落地前（农场未建/软链未重建）红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-05/sc_profile_farm_sandbar_links.py", "ro"),
    ("t260907-05-route-renamed-serves",
     "工单台路由前缀迁移契约（t260907-05 正文②＋「怎么算好：工单台面板/路由全通」的机器化，灰盒 L3）：黑盒 import workbench/node.ts＋mock ctx（webServer.register 收集）自起 127.0.0.1 ephemeral server 按 exact/prefix 语义分发——新前缀真 handler 应答（/sandbar-workbench/api/wf/temporal-health→200，零引擎 spawn，生产 Temporal 只读红线允许面）；旧前缀死透（旧前缀通配→404，非 301/308/410/200——「直接换不留旧」策略的机器化）；注册面收口（全部路由注册 path 零旧前缀残留、全新前缀，含 src/host 常量挂载的 session-charter 路由——KI-042 同源防漂移面）；bundle 双产物（lib/client.js+cjs）含新前缀零旧前缀（src 改了产物没重建=浏览器半仍打旧名）。3099 全程零接触；不 fetch 新 tickets（spawn 真 admin CLI 面，业务旅程归既有场景族与隔离台）。与 t260903-13/sc_workbench_bundle_loads（bundle 可加载）intent 不同面：加载成功≠名字改对。实现段已迁 node.ts/import/主文件——T1~T5 应绿，bundle 未随票重建则 T5 红（该红正是本条存在意义）",
     "node integration/t260907-05/sc_workbench_route_renamed_serves.mjs", "ro"),

    # ---- t260907-06: multi-repo project lane carrying sub-repos (ticket B: one ticket, several worktrees cohabiting one lane) ----

    ("t260907-06-multirepo-journey",
     "多仓票全链旅程（t260907-06 验收①前半+复用幂等，灰盒 L2/L3，用户手册多 repo 模型=项目父目录作根、多树同居一 lane）：写集路径落两子仓→每仓各得路径子集（最近 .git 祖先归属，不串仓不丢路径）、单仓口径透传；lane 容器（<项目根>/.lane/<泳道>，普通目录不入仓）下每仓一棵树且=所属子仓已注册 worktree（git worktree list 绝对路径可验）、基线文件随仓；分支命名 lane/<泳道>-<仓相对路径压平> 逐仓独立；prepare 二次两树 reused（树内标记文件幸存=未重建、分支引用不漂=转移接力 M4 面）；settle 各归其仓（两树改动各落各自树分支、落账不含他仓文件=错仓落账红线）。单仓零回归不另起用例——存量 integration 场景族即单仓回归面（intent 相同不重复造）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（prepare/settle 行为腿），stdlib 归属契约腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260907-06/sc_t260907_06_multirepo_journey.py", "ro"),
    ("t260907-06-multirepo-merge-gate",
     "合并闸逐树判定+merge 逐仓收口+重入幂等（t260907-06 验收①后半，灰盒 L2/L3）：白名单门重基两向——合法分仓改动整体绿（重基漏剥前缀=假红）、树内写集外注入整体红且 detail 点名（重基不放空=假绿防线）；merge 逐仓收口两仓 main 各恰多一个 squash 提交（一单一提交逐仓独立）、内容各归所属仓（错仓落账红线）；重入幂等（Temporal 重试面）——一仓冲突整体 failed、已成功仓已落账、冲突仓不落账，解堵重试后已成功仓提交数不变（不重复落账）、失败仓补齐（不漏账）、整体 ok。与场景①旅程/场景③拒收面 intent 分界；白名单工具语义另有专测族，本条只守多仓重基后调用侧组装两向行为。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（本场全靠真链路无 stdlib 替代腿）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260907-06/sc_t260907_06_multirepo_merge_gate.py", "ro"),
    ("t260907-06-multirepo-failclosed",
     "多仓 fail-closed 注入面（t260907-06，灰盒 L2/L3，畸形/边界/异常路径）：路径逃逸项目根（../）拒收点名不给静默归仓；集合外嵌套仓（仓中仓）路径创建即拒收且红字点名嵌套仓（不静默归外层仓=错仓落账前奏）；合法路径对照腿不误伤（拒收不扩大化）；删仓后 prepare→failed 回执点名缺失仓、树原样幸存不静默重建（meta.repo_worktrees 唯一真源一致性校验面，真源漂移=交人不是自愈）；树位置被来历不明普通目录占位→failed 不覆盖不删除（与现行单仓「目录已在但非本仓 worktree→人工处置」同语义逐树保住，防覆盖 agent 工作现场）。写集条目畸形形态属建票写集契约既有面（存量已守，intent 重复不另起）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（prepare 异常路径腿），stdlib 拒收腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260907-06/sc_t260907_06_multirepo_failclosed.py", "ro"),
    ("t260907-12-mixed-root-multirepo",
     "根亦 git 仓的混合多仓项目全链（t260907-12，灰盒 L2/L3，dengzhufpv 形态=项目根知识库 git 仓+repos/* 子仓并存）：仓集合=[根]+一层子仓（repos_under 短路退位）；写集归属三态——根仓路径票归根树（repo 相对路径=空）、子仓路径票归子仓（最长前缀）、双命中票两树同居一 lane 不串不丢；根树=泳道容器本身（prepare created、分支 lane/<泳道>-root、基线随根仓、清单落盘含 repo=\"\" 条目）；workflow 闸对 repo=\"\" 合法条目放行、缺 branch/分支碰撞真畸形照旧拒（fail-closed 不弱化）；复用幂等（prepare 二次两树 reused、标记幸存、引用不漂=M4 转移接力）；settle 逐树各归其仓（根树落账只含根仓写集文件、清单 repo=\"\" 条目读侧不断链=四消费方间接覆盖）、根仓 status 不受子仓树/清单污染（advisory④ .gitignore 兜底）；单仓零变化对照腿（根 .git 无子仓：derive 不激活、prepare 走旧单仓路径无清单、谓词 False）；真嵌套仓（已登记仓内部套仓）路径拒收点名；引擎自留 .lane/<id> 泳道 worktree 不入仓集合（单仓零变化红线）。与 t260907-06 三场景 intent 分界：彼=父目录作根形态（根无 .git），本=根亦 git 仓混合形态；通用路径逃逸/写集条目畸形形态属既有契约面不另起。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（prepare/settle 行为腿），stdlib 仓集合/归属/闸契约腿照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260912/sc_t260912_mixed_root.py", "ro"),
    ("t260910-03-formal-entry-fuses",
     "正规入口多仓票全链+双保险丝（t260910-03，dengzhufpv 260910 缺陷回归面，灰盒 L2/L3）：正规入口创建链补传——ticket.py 同款 derive（repo_write_set=写集）多仓项目产出双仓 repo_worktrees（复现形态修复后必须双仓）、明细经 ticket-start 二跳 dict workspace 转发不丢（缺陷根因=此通道被堵）、漏传=单仓明细缺失（旧病灶形状对照腿）、单仓项目透传零回归不激活；保险丝A（开票拒收）——ticket-start 显式 worktree+成员仓写集创建即拒收且红字点名条目（连接前拒收零 Temporal 依赖；只锚拒+点名不锚措辞）、对照腿不误伤（纯根仓写集放行、多仓写集合法派生放行=显式 worktree 不是绕闸通道）；逐仓物化落成硬断言——prepare_workspace 双仓树均=所属仓已注册 worktree（git worktree list 绝对路径可验）+清单落盘两仓条目；保险丝B（合并红灯，混合形态=缺陷现场）——清单缺失（_lane_scopes 单仓回落=缺陷形态）×成员仓写集：merge_check 红灯且物化检查项红点名缺失仓、非冲突类（conflict=False 不进自动消解回路，KI-047 同族防线）、merge 同源保险丝 ok=False 不落账（成员仓 main 零新提交、泳道保留交人工）、物化齐全对照腿同检查项绿（不误伤）；隔离台持久化契约（docker 台，真建票只发生在一次性 namespace 跑完即拆）——正规入口 ticket.py create 真建票与裸入口 client.py ticket-start（无显式 worktree，勿回归红线）的 Temporal payload TicketInput.repo_worktrees 均含双仓（probe_wf_input 读起始事件 input=对外数据契约），create 返回体为辅证。与 t260907-06/-12/-07 intent 分界：彼守多仓泳道本体/混合形态归属/epic 锚定，本守「正规入口补传+双保险丝+裸入口不回归」缺陷回归面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（行为腿），stdlib 形状腿照跑；docker/隔离台库缺席=ENV_FAIL 点名（台面腿）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260910-03/sc_t260910_03_formal_entry_fuses.py", "engine"),
    ("t260910-06-ki067-entry-audit",
     "KI-067 工单操作入口收口（t260910-06，260910 两实证缺陷回归面，灰盒 L2/L3）：静默失败根治——正规入口 ticket.py 任何 op 失败=非零退出+stdout 结构化 {ok:false,error}（绝不空输出：260910 实证病灶=空输出+退出 0+admin.log 无痕；A 段 stdlib 直调现形状，create 缺参/无参/畸形 argsJSON/-h 全非零）；无差别自审计——client.py 每次调用无论来源记 admin.log（含未知子命令拒收/连接失败/-h，拒收不记=盲区），source 记 env SANDBAR_CLIENT_ENTRY 原值（缺省 bare；审计落 SANDBAR_ADMIN_LOG 覆盖 tmp，不污染真账）；回执嵌提醒——裸入口回执（含失败回执）附 entry_hint、env 精确等值 'ticket' 才安静、任意值（'ticket.py'）不获静默且 source 记原值（claimed-source 非身份鉴别，宿主 260910 裁非安全语义）、参数面注入 source 字段不污染标记；双行审计契约——ticket.py 直调一次=admin.log 两行（ticket.py-direct+ticket）call_id 一致（有意双行非重复记 bug，关联键=SANDBAR_CLIENT_CALL_ID）；sign/retry_qc 包进正规入口（who 调用方注入，包装层只加审计不加权力）——retry_qc 贴 workflow 裸串契约（隔离台真票 timeline reason 以 who 开头且无 dict 乱码={who,note} 误转发现形特征）、note 非空 CLI 层显式拒收点名 note、sign 通道 delivered=true 且 Signature payload 形状落 workflow 可观测面（fresh 票非人门→refused 条目 want 含 sign、who 原样，同 pause KI-061 族文档化回执面；人门签字接受面属 workflow 门逻辑 L1 不重复）。与 t260910-03 intent 分界：彼守多仓派生+双保险丝（create 链），本守入口收口面（退出码/审计/entry_hint/sign/retry_qc 包装）；与 t260908-01 分界：彼守 workflow 侧 pause/retry_qc 幂等唤醒语义，本守 CLI 包装与审计/提醒面。实现落地前红属预期（TDD 信号：A 段红即 KI-067 病灶形状复现），arbitrate/merge 期必须绿；三态契约无 SKIP——stdlib A 段恒跑，temporalio 缺失=ENV_FAIL 点名（B/C 段），docker/bench/隔离台库缺席=ENV_FAIL 点名（C 段）；红线：一切被测子进程 Temporal 地址指不可达桩 127.0.0.1:9 或一次性隔离台，真票只发生在一次性 namespace 跑完即拆",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260910-06/sc_ki067_entry_audit.py", "engine"),
    ("t260908-02-mixed-payload",
     "混合形态工单的多仓明细以一等字段穿越 Temporal 编解码两跳（t260908-02，t260907-13 实锤 bug 的缝守卫）：TicketInput/WorkspacePrep 均有 repo_worktrees 显形字段（default_factory=list 保存量回放）；编解码往返全等（workflow 启动面不再 TypeError=dengzhufpv T2 停摆修复）；畸形分层拒绝精确——类型毁形在编解码层拒、语义非法在闸层拒互不冒充；新旧闸位同拒；单仓对照零回归。stdlib 腿恒跑，temporalio 缺失=ENV_FAIL",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260908-02/sc_t260908_02_mixed_payload.py", "ro"),
    ("t260907-07-epic-anchor-two-projects",
     "立项目录锚项目感知×env 自测语义（t260907-07，GAP-B 修复回归，验收①②校验面）：双项目夹具（engine/external 桶同名 gap-b+各自异名，tmp per-key 注册表）下 resolve_epics_dir×validate_epic_code 各取各的项目主目录 notes/epics——同名各自通过（改造前 external 误报「立项代号不存在」的面）、异名自桶通过、异名跨桶拒绝且文案带该项目实际查询目录（诊断信息，不误指引擎仓）；未知项目 key fail-closed 不静默兜底；SANDBAR_EPICS_DIR 自测语义不变（两项目同指 env 目录优先于项目锚）、env 空串回落项目锚、env 指不存在目录报错「目录为空或不存在」可辨不崩。shared stdlib 直驱秒级零 docker；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；与 developer L1（畸形输入细目单测）intent 不同面",
     "python3 integration/t260907-07/sc_epic_anchor_two_projects.py", "ro"),
    ("t260907-07-epic-anchor-same-source",
     "UI×CLI 立项目录同源同规（t260907-07 验收③）：同一 per-key 注册表夹具下 Py resolve_epics_dir(key) 与 TS resolveEpicsDir(primaryDir(findProject(key))) 两项目各自全等且等于各自主目录 notes/epics（非引擎仓锚）、不串桶；SANDBAR_EPICS_DIR 覆盖两侧同款（Py==TS==env 目录）。同规口径边界：断言经同一注册源+同一拼装规则同源，不覆盖「工单台起在非项目注册主目录」部署形态（repo=config.repo 时 UI 仍锚其 repo——方案 C4）。node type-stripping 直跑+python3 子进程，子进程不可得=ENV_FAIL exit 2；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260907-07/sc_epic_anchor_same_source.mjs", "ro"),
    ("t260907-07-epic-cli-ticket-start",
     "开票入口 epic 校验项目感知用户路径（t260907-07 验收①②端到端，docker 测试台单实例）：外部项目 ticket-start 关联其主目录立项单成功（同名 gap-b+异名各自通过）、engine 桶行为不变（同名+异名照常）；负路径连接前拒收零 Temporal 依赖真跑——epic 确缺文案带该项目实际目录、跨桶异名不误指 engine 目录、未知 project 硬闸拒收（KI-032 面回归）。被测 env 显式清 SANDBAR_EPICS_DIR 防宿主泄漏改判锚，显式 SANDBAR_TARGET_HOST 指台（绝不连生产红线）；docker/镜像/SDK/隔离台库缺席=ENV_FAIL exit 2；实现落地前红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-07/sc_epic_cli_ticket_start.py", "engine"),  # engine: one docker stage
    ("t260907-07-epic-next-prepare-project",
     "立项预跑读档案项目感知接线（t260907-07 同票接线面=merge 收口预跑不再对外部项目静默跳过）：prepare_epic_next 带 project 读到该项目主目录立项全文（exists+全文匹配+state_key 可算）；不串桶（engine 异名对 external 档案缺失）；project 空=引擎锚兜底（真仓只读缺档软失败）且 env SANDBAR_EPICS_DIR 优先于兜底命中（自测语义）；档案缺失/代号形状非法 exists=False 防穿。_epic_ticket_rows 桩替 workflow 边界（selfcheck E 先例）；temporalio SDK 缺席=ENV_FAIL exit 2；实现落地前红属预期，arbitrate/merge 期必须绿；与 selfcheck E 段（env 夹具单点自测）intent 不同面",
     "python3 integration/t260907-07/sc_epic_next_prepare_project.py", "ro"),

    # ---- t260907-01: repo-move wrap-up (sweeping old repo paths) — acceptance regression anchor ----

    ("t260907-01-path-hygiene",
     "移仓收尾路径卫生守卫（工单验收①②，KI 移仓炸路径族沉淀回归）：宿主已物理移走旧仓，任何仍按旧仓绝对路径（/Users/user/Documents/ 下的 suyou 目录）解析的代码一用即炸且多为静默炸——代码域零旧仓字面量（排 node_modules/.git/.suyou/.lane/docs/notes；三个另开票残留文件显式豁免降 warn，清单外新病灶即红）＋清扫面五文件 node --check 语法健康（boot 类文件不直跑：chrome/dsh/凭据重依赖，不涉 3099 红线）。灰盒锚验收合同不锚内部推导写法；needle 串接构造自引用免疫。与 developer L1（各 smoke 自身函数断言）intent 不同面：本条守全仓卫生合同",
     "node integration/t260907-01/sc_migration_path_hygiene.mjs", "ro"),
    ("t260907-01-smoke-lane-green",
     "移仓后 smoke 资产面泳道直跑全绿（工单验收③执行面锚，KI-038「脚本在场环境红」习惯化防线）：从泳道 worktree 直跑三支零依赖纯函数冒烟（projects/sessions/agent-live，cwd=workbench）各 exit 0 且 passed>0 failed=0（agent-live 的 C/D 段在 zstd 缺席时自降级、退出码语义不变）。守的是「下次任何人直跑必须绿」的环境合同，与 smoke 自身 L1 函数断言不同层不重复；零端口零 3099 零网络",
     "node integration/t260907-01/sc_smoke_suite_lane_green.mjs", "ro"),

    # ---- t260907-10: naming cleanup 3, finale (directory restructure v6 flattening) — acceptance-rule guard ----

    ("t260907-10-engine-layout",
     "宿主令 v6 五层结构守卫＋全仓旧路径残留清零（t260907-10 验收①③，灰盒 L3）：引擎住 server/engine（宿主裁定不叫 temporal）、旧包装层退场、插件/装配配方两变体/角色声明五层上移齐整——读者按交接文档指的路径必须命中真身；残留旧路径（连写＋段式杂糅两型，段式=机械替换打进旧串的嵌合体，实测漏网型）=代码指向不存在位置，一用即炸或静默造错数据目录；五层断言锚目标树清单不锚数字（review gen1 条件①）；豁免列名制逐处归类（审计流水/宿主 merge 债/历史票快照/回落 marker/退役账行）。与 t260907-05 农场链守卫（软链结构）、t260907-04 naming grep（suyou token）intent 不同面。Hermetic 纯文件读秒级；落地前红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-10/sc_engine_layout.py", "ro"),
    ("t260907-10-engine-venv-compat",
     "引擎 venv 定位兼容契约（t260907-10 工单⑤「.venv 位置变更须保 worker 兼容（旧路径回落期一轮）」，灰盒 L3）：安装器单一装载面（root/home 注入全隔离）上断言解释器解析序——新路径 server/engine/.venv/bin/python 优先；新路径缺位窗口（主树 .venv 未物理迁移）回落旧路径；两缺不静默落系统解释器（错 python=炸在 spawn 处语义错位，报错必须精确）；畸形形态（断链软链/不可执行）视同缺位；verify.yaml test 道（接入契约 ②a 声明面）锚新路径真源。回落机制宿主裁切法二（env 注入）时本条随语义同步改读 env 锚。Hermetic 全 fixture 秒级；落地前红属预期",
     "python3 integration/t260907-10/sc_engine_venv_compat.py", "ro"),
    ("t260907-10-worker-reap-predicate",
     "迁移后 worker 收尸谓词完备性（t260907-10 资源回收面，灰盒 L3）：目录重构改了 worker 落盘路径，stop 脚本 pgrep 谓词若仍只认旧路径 cmdline，迁移后停不掉 worker——僵尸进程占 Temporal 任务槽，「停了控制台机器还在响」；断言谓词命中 server/engine/worker.py 起的进程样本＋temporal dev server 收尸线在场＋特异性（无关进程/console 3099 操作面样本不误命中、点号元字符反例不误命中）。本条同时是仓根扩权债（review gen0 A1）的监督信号：扩权未落地则本条红。Hermetic 纯文本正则秒级；落地前红属预期",
     "python3 integration/t260907-10/sc_worker_reap_predicate.py", "ro"),

    # ---- t260907-11: workbench host project awareness (KI-057, six anchors threaded through) — cross-project comparison family ----

    ("t260907-11-wb-anchor-faces",
     "跨项目三面取数对照＋撞码不互串＋防穿越闸随项目根判界（t260907-11，KI-057 宿主实报「dengzhufpv 变更 tab 空」的 fixture 化=验收腿①）：fpv 视图 epics 列表/详情读 fpv 仓、审批 POST 落 fpv 仓 server/dsh/reviews/ 且 sandbar 视图同 id 读空（写读两面均按项目键）、precache nextHintCached 与 dismiss 随项目根（同代号 demo-x 两项目缓存互不牵连=撞码面，epic 代号无跨项目唯一约束已实核）；diff 判界面=fpv 根内泳道可见（实报反面）而同一 worktree 换 sandbar 锚仍拒「越出」＋根外路径仍拒（红线：闸语义不弱化、判界基准随项目走）。进程内 apply+mock req/res（零端口零 Temporal 零 3099/7233），SANDBAR_PROJECTS_DIR 临时注册表（.migrated 跳种子迁移）；git 缺席=ENV_FAIL exit 2 点名；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。与 developer L1（resolver/纯函数真值表）与 smoke/changes.mjs（单仓单项目）intent 不同面：本条锁双项目对照组装行为",
     "node integration/t260907-11/sc_wb_anchor_cross_project_faces.mjs"),
    ("t260907-11-wb-anchor-keys",
     "项目键解析契约面：零回归＋报错精确＋隔离语义＋env 收窄（t260907-11，KI-057，验收腿②的 fixture 化）：无参回落默认仓且响应带 resolved 来源标记（方案承诺）；?project=<sandbar key> 注册表路径解析根与无参回落根逐字节一致（生产 UI 恒带 ?project=，钉住注册表条目不漂移=零回归闸）；未知 key 显式 400 且 error 点名项目键不伪装「越出仓库根」（报错必须精确）；隔离条目显式 502 透传注册表文案（不回落=不违隔离语义）；SANDBAR_EPICS_DIR 仅无参回落生效、per-project 不被 env 串味（红线「旧 env 覆盖链保留」×方案收窄声明双兑现）。进程内驱动零端口零 Temporal；实现落地前红属预期。与 developer L1（resolver 四边角单测）intent 不同层：本条锁路由组装后的响应契约；票面 t.project 与 query 优先级需引擎 ticket show，归 S5 实票不重复",
     "node integration/t260907-11/sc_wb_anchor_key_resolution.mjs"),
    ("t260907-11-wb-anchor-evidence",
     "证据目录锚项目化＋env 收窄（t260907-11，KI-057 第四面，含取图端点同族核销）：fpv 视图证据列表=归档 .suyou/evidence＋泳道 .worktrees 两候选三件、取图端点按 ?project= 读 fpv 根字节一致、sandbar 视图同 id 列表空/取图 404（不串项目）；SANDBAR_EVIDENCE_DIR 仅无参回落生效、per-project 不被串（红线 env 链保留×收窄声明）。进程内驱动零端口零 Temporal；证据防穿（文件名白名单/TICKET_ID_RE containment）归既有覆盖不重复；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260907-11/sc_wb_anchor_evidence_family.mjs"),
    ("t260908-01-ki061-wake-revive",
     "仲裁超限 blocked 两相复活旅程（t260908-01，KI-061 验收①②的用户可感知面，真 docker 台双 worker 切换）：相一 SANDBAR_TEST_DISABLE_KI061=1（create_plan v2 S3 契约开关=模拟修复前 worker）＋tests-fault 桩驱动 6 轮超限 blocked→宿主注入裁决（host_ruling）→retry_qc 唤醒→断言吃 memoized 仲裁结论立即再 blocked 且 arbitrate 零 respawn（t260907-10 02:12 症状留证）；相二换修复 worker 再唤醒→断言 arbitrate 真 respawn（账本新 spawn、gen 递增）、prompt 含宿主终裁（host_rulings 注入消费面）、verdict=pass 后票离开 arbitrate blocked。与 t260905-10 sc_host_ruling_injection（KI-053 格式纠正路径、单 worker、畸形 ruling 拒收）intent 不同面；与 developer selfcheck（L2 time-skipping 两相闸）不同层不互替；实票复活归宿主发 retry（红线），本条隔离台等价复刻。断言面=stub 账本（agent 实收 prompt）/snapshot，不锚 prompt 文案；docker/舞台缺件=ENV_FAIL exit 2；merge_check 及其后不在范围。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260908-01/sc_ki061_overlimit_wake_revive.py", "engine"),  # engine: docker stage + two-generation worker switch, timing-sensitive legs
    ("t260908-01-ki061-replay-compat",
     "在飞 workflow 重放兼容契约（t260908-01，KI-061 验收②机械面，044c692 裸改重放炸 99809 的同族回归闸，真 docker 台）：先制造修复前形态在飞 history（DISABLE=1 worker 6 轮超限 blocked＋retry_qc 唤醒一次 settle→再 blocked＝t260907-10 现形态），replay_check 只读回放两腿——腿一 pre-fix 形态 history（含唤醒穿越点 patched 求值）用修复后代码回放 ok=true（命令序列零分歧）；腿二修复 worker 复活（arbitrate respawn、KI-061 marker 入 history）后再回放 ok=true（marker notify 先行→同位 True 的消费路径确定性）。与场景①分工：彼锁 live 复活旅程、本条锁重放确定性；与 developer selfcheck（L2 环境内两相）不同层。replay_check 零写（list/fetch only）；docker/舞台缺件=ENV_FAIL exit 2。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260908-01/sc_ki061_inflight_replay_compat.py", "engine"),  # engine: docker stage + worker replay (read-only replay legs)
    ("t260908-01-ticket-pause-gate",
     "工单段间暂停/恢复全旅程（t260908-01，宿主拍板①-④验收面，灰盒 L3，真 docker 台+夹具仓桩脑链=真 DevLaneWorkflow/真 activities/SANDBAR_AGENT_STUB=1）：在飞段发 pause→当前段自然跑完→停段间门口（snapshot.paused+paused_phase=at_gate+timeline paused-waiting）→观察窗不派下一段→resume→走完全链到 closed；反馈可辨三笔（重复 pause/空态 resume/畸形 who 空白与 note 超限）refused 语义锚互辨且拒收不置位；暂停中 snapshot 照常可查（KI-008 面）+ticket-list 行带 paused（列表徽标数据源契约）；pause×rework 显式语义（暂停中压门口、恢复后先打回再推进）；通用性=非 dev-lane 模板（fixture_two_step，SANDBAR_FIXTURE_TEMPLATES 环境门）同款暂停生效+门关时开票拒收点名「未知模板」。拓扑过嵌套护栏（review R3 核准形态）：子进程 env 剥泳道标记三件套+钉 sandbar-ticket-<票id> 专属队列+只连一次性舞台 Temporal，递归按构造不可能，ticket-lifecycle 移出闸教训的收窄声明落场景头注。断言锚 CLI 回执/snapshot/timeline/refused/list 行公开契约，不锚实现内部；文案锚语义词不锚字面（KI-051）。与 ki061 两条（仲裁复活/重放兼容）intent 不同面；与 developer selfcheck_pause（常量/refused 文案/老实例拒收纯函数腿）不同层不互替。docker/舞台缺件=ENV_FAIL exit 2 点名。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260908-01/sc_ticket_pause_gate.py", "engine"),  # engine: one docker stage + fixture-clone stub workers, two tickets sequential
    # ③ final-verification run E (260909): anchor boots two docker stages and is
    # the most stage-boot-sensitive entry (≈3/8 history regardless of engine
    # width; run E burned the whole 600s ensure budget when its boot coincided
    # with the main-pool with_stage herd at Phase-2 t=0, wall 924s). It runs
    # LAST in the engine lane: by then the other pools have drained, so its
    # stage boots land in a near-empty compose herd. Zero wall cost (engine
    # serial sum unchanged). The ticket-start concurrency under test is
    # internal to the scenario (barrier), unaffected by pool position.
    ("t260904-02-ticket-start-anchor",
     "裸入口开票硬闸+隔离台并发隔离端到端（t260904-19 起 docker 测试台双实例，epic 验收1/4/5，KI-032 修复回归）：裸 client.py ticket-start 带 project→Temporal 内 payload workspace.path 绝对路径且锚注册项目主目录/.lane/（worktree 同锚，落仓与执行 worker 解耦）；缺 project/未知 key=创建即拒收且两红因文案互辨；双槽并发开票时间重叠互不见对方工单（ticket-list 双向+跨槽 describe not_found）；审计钩子证被测子进程零连生产 7233/8233（含自证拦截腿）+双台端口面核验（互异/不在禁区 3099/3199/7233/8233/17233/18233）+SANDBAR_TARGET_HOST 指生产构造即拒（红绿自证）；teardown 零残留（down 后 docker ps 无本工程容器）、端口释放、down 幂等二连、同工程名立即 re-up（t260904-19 docker 台语义，容器由 daemon 持有无锁可崩，取舍见 stage_docker 头注）；docker 缺席/镜像缺席=ENV_FAIL exit 2 点名",
     "python3 integration/t260904-02/sc_ticket_start_anchor.py", "engine"),  # engine-LAST (run E): stage boots land in the drained window; concurrency under test is internal
]

CMD_TIMEOUT = 900


def _run_entry(entry):
    """Run one scenario (cmd via /bin/sh -c, cwd = repo root). Returns
    (name, exit_code, tail, dur_s). dur_s = that scenario's wall time
    (KI-060 prep 2: timing distribution — the summary line only gives the
    total; finding the slow scenarios relies on these per-entry marks)."""
    name, cmd = entry[0], entry[2]
    t_start = time.time()
    try:
        proc = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True,
                              text=True, timeout=CMD_TIMEOUT)
        return (name, proc.returncode,
                ((proc.stdout or "") + (proc.stderr or ""))[-1500:],
                time.time() - t_start)
    except subprocess.TimeoutExpired:
        return name, -9, "超时（>%ds）" % CMD_TIMEOUT, time.time() - t_start


def main() -> int:
    """Run the registry as pools (host-ordered t260902 pool split): an entry
    may carry an optional fourth element — None/absent = the "main" pool;
    "ro"/any other string = a named pool; "exclusive" = runs alone before all
    pools (since campaign 3b only the shared-temporal ticket writer stays
    there; the other 10 former exclusives are the concurrent "engine" pool).
    Pools run in parallel; within a pool it is strictly serial (order and
    reproducibility). Cross-pool ordering may interleave —
    the engine/tools parse line by line and do not care about order.

    Three-state exit-code contract (t260904-12, final ruling section 7.3: no
    SKIP inside the gate): scenario exit 0=PASS / 1=FAIL (product red) /
    2=ENV_FAIL (environment red — nothing got verified, the cause belongs to
    the environment). The old "missing environment = clean SKIP (exit 0)"
    semantics is retired. Summary line and detail lines must be **clean in
    both directions to be green**: the runner self-checks, and any mismatch
    exits product red 1 (a lying summary never passes). Scenarios whose legs
    are all N/A record product red themselves via lib_env.fail_if_all_na.

    In-pool concurrency (260909 speedup campaign round 2): entries marked
    "serial" in a pool run first (relative order preserved), then the rest run
    at SANDBAR_POOL_CONC lanes; SANDBAR_CONC_POOLS picks the pools that get
    concurrency, "name:N" pins a per-pool width (default main,ro,browser-free
    — engine stays serial-by-default: its scenarios boot docker stages and a
    width-2 herd already flaked under load, see the module docstring; the
    browser chain pool shares one console and stays strictly serial —
    registry order is its contract); SANDBAR_POOL_CONC=1 restores the old
    semantics (strict serial everywhere, pools included — see Phase 2)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ran = passed = failed = env_failed = 0
    t0 = time.time()
    lock = threading.Lock()
    pools, exclusives = {}, []
    for e in SCENARIOS:
        opt = e[3] if len(e) > 3 else None
        if opt == "exclusive":
            exclusives.append(e)
            continue
        fifth = e[4] if len(e) > 4 else None
        pool = opt if (opt and opt != "serial") else "main"
        serial = opt == "serial" or fifth == "serial"
        pools.setdefault(pool, []).append((e, serial))

    try:
        conc_width = max(1, int(os.environ.get("SANDBAR_POOL_CONC", "4")))
    except ValueError:
        conc_width = 4
    # "name" -> SANDBAR_POOL_CONC lanes; "name:N" -> N lanes; absent -> 1.
    conc_pools = {}
    for x in os.environ.get(
            "SANDBAR_CONC_POOLS",
            "main:3,ro:3,browser-free:3").split(","):
        name, _, w = x.strip().partition(":")
        if not name:
            continue
        try:
            conc_pools[name] = max(1, int(w)) if w else conc_width
        except ValueError:
            conc_pools[name] = conc_width

    def _drain(entries, pool_name):
        """Run one pool: serial entries strictly one after another (relative
        order preserved), the rest fan out at the concurrency width."""
        nonlocal ran, passed, failed, env_failed
        serials = [e for e, s in entries if s]
        concs = [e for e, s in entries if not s]
        for e in serials:
            _emit(e, pool_name)
        if not concs:
            return
        width = conc_pools.get(pool_name, 1)
        if width <= 1:
            for e in concs:
                _emit(e, pool_name)
            return
        with ThreadPoolExecutor(max_workers=min(width, len(concs))) as tex:
            futs = [tex.submit(_emit, e, pool_name) for e in concs]
            for f in futs:
                f.result()   # re-raise scenario exceptions = product-red attribution, never swallowed

    def _emit(e, pool_name):
        nonlocal ran, passed, failed, env_failed
        name, exit_code, tail_out, dur = _run_entry(e)
        dur_tag = " (%.1fs)" % dur
        # Three-state line: 0=PASS / 2=ENV_FAIL (environment red — the indented
        # tail says what is missing) / anything else = FAIL product red.
        if exit_code == 0:
            block = ["PASS [%s]%s" % (name, dur_tag)]
        elif exit_code == 2:
            block = (["ENV_FAIL [%s] exit=2%s" % (name, dur_tag)]
                     + ["    " + ln for ln in tail_out.splitlines()[-6:]])
        else:
            block = (["FAIL [%s] exit=%d%s" % (name, exit_code, dur_tag)]
                     + ["    " + ln for ln in tail_out.splitlines()[-6:]])
        with lock:
            ran += 1
            passed += (exit_code == 0)
            env_failed += (exit_code == 2)
            failed += (exit_code not in (0, 2))
            timings.append({"pool": pool_name, "name": name,
                            "status": ("PASS" if exit_code == 0
                                       else "ENV_FAIL" if exit_code == 2 else "FAIL"),
                            "dur_s": round(dur, 1)})
            print("\n".join(block), flush=True)

    timings = []   # KI-060 prep 2: timing distribution (one row per scenario, with pool attribution)
    for e in exclusives:      # exclusives go first, overlapping no pool (always serial)
        _drain([(e, True)], "exclusive")
    if conc_width <= 1:
        # SANDBAR_POOL_CONC=1 = 全串行回退语义（提速战役③步骤0 计划验收②）：
        # 不光池内宽度收 1，池间也顺次排开——否则六个池各一路并发，负载
        # 敏感场景（起台族/capture 全视图走查）在「回退」里仍要扛六路并发，
        # 回退形同虚设（260910 实锤：只设池内宽度时 wall=467s 与缺省无差）。
        for fname, pv in pools.items():
            _drain(pv, fname or "main")
    else:
        with ThreadPoolExecutor(max_workers=max(1, len(pools))) as ex:
            for fname, pv in pools.items():
                ex.submit(_drain, pv, fname or "main")
            ex.shutdown(wait=True)
    # Summary five counters (t260904-12): na=N/A is a leg-level state, already
    # folded into pass/fail inside the scenario (all legs N/A = scenario red),
    # so at runner level it is always 0 — kept as a placeholder for the shape.
    # ran=pass+fail+env_fail is the "clean in both directions" invariant;
    # violating it = the summary is lying, exit product red (runner self-check).
    consistent = (ran == passed + failed + env_failed)
    wall = time.time() - t0
    print("SCENARIOS ran=%d pass=%d fail=%d env_fail=%d na=0 (%.0fs)"
          % (ran, passed, failed, env_failed, wall), flush=True)

    # ---- KI-060 prep 2: timing distribution report (stdout summary + JSON archive for comparison) ----
    import collections as _c
    import datetime as _dt
    import json as _json
    import pathlib as _pl
    by_pool = _c.defaultdict(float)
    for t in timings:
        by_pool[t["pool"]] += t["dur_s"]
    print("耗时分解（池内串行合计 / 池间并行，wall=%.0fs）：" % wall)
    for p, s in sorted(by_pool.items(), key=lambda kv: -kv[1]):
        n = sum(1 for t in timings if t["pool"] == p)
        print("  %-13s %6.0fs  (%d 个场景，串行合计——并行关键路径=%s)"
              % (p, s, n, "是" if s == max(by_pool.values()) else "否"))
    top = sorted(timings, key=lambda t: -t["dur_s"])[:15]
    print("最慢 Top15：")
    for t in top:
        print("  %6.1fs  %-8s %s" % (t["dur_s"], t["pool"], t["name"]))
    try:
        rp = _pl.Path("out") / ("integration-report-%s.json"
                                % _dt.datetime.now().strftime("%y%m%d-%H%M%S"))
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(_json.dumps(
            {"ran": ran, "pass": passed, "fail": failed, "env_fail": env_failed,
             "wall_s": round(wall, 1), "generated": _dt.datetime.now().isoformat(),
             "conc_width": conc_width,
             "conc_pools": sorted("%s:%s" % kv for kv in conc_pools.items()),
             "timings": timings}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("报告落档：%s" % rp, flush=True)
    except OSError:
        pass   # a failed report write does not change the exit code (the report is an observation surface)

    if not consistent:
        print("FAIL [__summary__] 汇总与明细不一致（双向净校验红）", flush=True)
        return 1
    if failed > 0:            # product red first (C7): with FAILs present, environment reds do not dilute the product red
        return 1
    if env_failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
