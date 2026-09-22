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
- Pool exclusion (t260913-03, host order: pull the slow pools out of the
  per-ticket segment): SANDBAR_SCENARIO_EXCLUDE_POOLS="engine,exclusive" (or
  --exclude-pools) drops entries whose registry-declared pool is in the set.
  Dropped entries are NOT part of this round's register — expected =
  len(SCENARIOS) - excluded, and they are neither run nor counted as passed —
  and the excluded face is named twice in the output ("本轮跳过池=…（少 N 条）")
  so a shorter round can never masquerade as a full one. Unknown/illegal pool
  names are only loudly warned on this path (rc semantics unchanged — the
  injected fake-table batteries keep working); the single point that fails
  closed on them is --print-pool-assets, which reads the real registry in a
  fresh process and also derives the excluded pools' asset face (cmd tokens +
  their import/require closure + the integration/ root shared-infra files)
  for the gate's forced-full-run exception leg. Default (no env, no flag) =
  every entry runs, byte-identical to before.
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
import ast
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
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
    # Delisted (t260904-12 §7.3, same ruling as ticket-lifecycle): the t260917-01 scene
    # self-guards nested runs (nestedGuard -> ENV_FAIL exit 2 inside any lane's
    # mechanical step), so a registered entry could never reach PASS in-gate — a
    # deliberate environment red must stay out of the gate registry. The file stays in
    # the tree (coverage-evaporation guard) for top-level/manual runs against the docker
    # test Temporal; lint DEREGISTERED whitelists it (L5).
    # Original cmd: node integration/t260917-01/sc_t260917_01_arb_gate_refusal.mjs
    ("t260904-19-stage-docker",
     "docker 测试舞台 L1（t260904-19：全仓唯一搭台方式回归锚，假 docker shim 真跑编排面零 docker 依赖）：档位 flock 原子预留（并发双起各得独立档=验收①回归锚、外部持锁滑档、锁释放复抢=崩溃自释语义）；禁区端口面（生产 3099/7233/8233+缺省台 3199/17233/18233）与内核临时区间构造性排除；畸形输入全电池（project 白名单/端口旋钮非数字越界禁区被占/目录缺失/半指定）逐条点名检查项零副作用；诚实环境红三态（docker 缺席=ENV_FAIL exit 2 点名、镜像缺席点名 build-test-temporal.sh、compose 半途死就地 down 清场零残留）；ensure 幂等（健康复用/半残拆重起）；up→down 零残留+端口释放+幂等二连；bench.py 守卫回归（槽位制退役后保留面）",
     "python3 integration/tests/test_stage_docker.py", "exclusive"),  # engine 池仍不够：电池含 flock/端口禁区/up-down 零残留，任何并发起台都扰动（套件 573s 挂 1，隔离三连绿 121/125s）——独占先跑=搭台 L1 先验台面（t260910-05 仲裁 gen2）
     # exclusive（t260910-08 arbitrate）：三连机械波内各 1 败、单跑恒绿（17/17×2）——
     # 真 docker 全栈+console 就绪探针与同波浏览器族重负载争用；断言零改动只挪排程。
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
     "(black-box, user perspective) 工单抽屉 QA 截图证据可见（t260831-08 建；t260910-05 读侧新名迁移扩子用例）：候选目录新名优先（.sandbar）旧名只读回落（naming-compat）——新名摆渡可读可列、仅旧名回落命中、新旧并存同名去重不双计；png 字节原样 image/png 回传；穿路径/怪名/非法 id 恒 4xx；未知 id 空列表软降级；抽屉逐文件渲染 <img>。旧名 canary 兼作环境判别：canary 可见而新名不可见=产品红（TDD/回归），全不可见=ENV_FAIL",
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
    ("capture-board-assert",
     "(black-box, user perspective) t260910-05 板面截图内容断言：板面图仅在板面就绪锚在场时产出——就绪放行、未就绪（无行卡且无空态锚）run 必拒=无图且进程沿 run→failures→exitCode 链全链红；三条板面条目（board/dark/light）逐一行为锁接线（零 DOM 桩满足导航面仍拒绝=断言在位，resolve=接线断=废图全绿复活）；空态锚在场放行；DOM 探测抛异常 loud 拒绝；预算 env 畸形回落缺省不崩。锚选择器从导出 BOARD_ANCHORS 按角色取（KI-051 锚语义不锚字面）",
     "node integration/baselines/sc_capture_board_assert.mjs", "browser-free"),  # free: no console — stub page drives the exported capture surface (t260910-05)
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
     "node integration/baselines/sc_multi_tab_coexistence.mjs", "browser-free", "serial"),  # free: shared console read-only — API stubs；260915 仲裁挂 serial：T3 的 33s 隐藏零轮询时序窗要求安静机器，池内并发（真浏览器兄弟同抢 CPU）下事件循环排队迟到两次伪红（同签名 4 req/3 list poll）
    ("t22-t260901-22-approve-modal-ui",
     "* * integration/t260901-22/t02_approve_modal_ui.mjs * —— KI-004「approve 弹层自由备注」用户可感知 UI ",
     "node integration/t260901-22/sc_t02_approve_modal_ui.mjs", "browser-free"),  # free: no console — pure file contract (bundle)
    ("t22-t260901-22-approve-modal-faultmodes",
     "本 UI 家族（wb-modal）无 Esc/外点关闭处理器（rework 打回弹层同样只有「确认/取消」 // 两条真实关闭路径）——验收口径改为：每一处 setApprov",
     "node integration/t260901-22/sc_t03_approve_modal_faultmodes.mjs", "browser-free"),  # free: no console — pure file contract (bundle)
    ("t260905-05-modal-dialog-semantics",
     "wb-modal 弹层族 dialog 语义契约（t260905-05，灰盒 L2）：本票 client 侧唯一行为变化=四类 wb-modal（审批推进/打回/派活指令/内容预览）补 role=dialog+aria-modal——用户可感知承诺=弹层在场时 [role=dialog] 语义通路可发现（全仓 6 个集成 helper 的 dismissOverlays 通路从恒空变可用，即本票改动要兑现的契约）、aria-modal=true 在册、可经语义通路关闭（点弹层按钮遮罩消失）；真台面行为子用例（行卡「推进」→审批弹层 / 行卡「打回」→打回弹层，t260904-17 行卡契约锚+页级 API 桩零真写，native confirm 全程自动 accept）+ 服务产物完备子用例（盘上 lib/client.js=台面按请求服务的真产物，每处 wb-modal 皆带 role——改 src 忘 tsdown 重建的 KI-052 同族静默穿透在此现形：client 半每次请求从盘现读，未重建=持续红 merge 闸不放行）+ 零 pageerror 卫生。与 t260901-22 approve-modal-ui（弹层出现+内容在场面）/t260903-04 bundle-sync（src≡lib 构建卫生面）/multi-tab-coexistence（跨页签族行为面）intent 不同面。实现段落地前红属预期（TDD 验收门，S0 build-contract 先例），arbitrate/merge 期必须绿",
     "node integration/t260905-05/sc_modal_dialog_semantics.mjs", "browser"),  # chain: shared-console writer — real API writes (approve/reject state changes)
    ("t260905-05-multitab-guard-assets",
     "19 号豁免体系资产守卫（t260905-05，静态读源零台面）：本票红线「不改 19 号已落资产语义」+验收条款「force 取证守卫保留」的机械面——sc_multi_tab_coexistence.mjs 内诚实红定性标签 PRE_EXISTING_TAG 仍挂 T2/T5 fail 分支与 failWith catch 路径（防「红=正常」习惯化的守卫，绿则随 fail 分支自消但资产本体必须保留）、force 取证守卫（「force 后抽屉仍不开=产品红如实落」语义注释+force:true 点击通路）在册、三态执行契约（SUMMARY 四计数+退出码 1/2 分家）未弱化、T1-T7 族子用例清点零缺失（新增子用例不拦、缺子用例即红——族覆盖收缩须走票）；检测器红绿自证（真源逐规则绿+四份变异样本逐规则红，检测器失明在此现形）。与 multi-tab-coexistence（运行时行为面）intent 不同面：本场景守守卫资产在册",
     "node integration/t260905-05/sc_multitab_guard_assets.mjs", "ro"),
    ("t02-t260902-02-prune-e2e",
     "client.py 末行 JSON 回执；解析失败 = FAIL。",
     "sh integration/with_stage.sh t26090202-prune python3 integration/t260902-02/sc_t05_prune_e2e.py", "engine"),  # engine: 起台族收敛（t260910-05 仲裁：宽池并发翻红、隔离 19/19 绿）
    ("t02-t260902-02-archive-legacy-e2e",
     "注入缝直调真命令逻辑（活文件系统，零 Temporal server 依赖）。",
     "sh integration/with_stage.sh t26090202-arch python3 integration/t260902-02/sc_t06_archive_legacy_e2e.py", "engine"),  # engine: 起台族收敛（t260910-05 仲裁）
    ("t260903-07-click-no-chat-switch",
     "点工单不切右侧会话（t260903-07①核心反转）：点工单行后中列详情照常开（.wb-d2-steps 在场）、右栏 chat 零变化——【工单上下文】快照零注入、data-phase 不变、项目会话区 tab 全集不含 ticket- 行（票② R8 改锚：顶部行已退役，判据改 [data-wb-psess-tab] 全集）；多行重复点击零注入零 churn（旧契约「点行→开 ticket- 会话」的显式反转守卫，防联动复活）",
     "node integration/t260903-07/sc_t01_click_no_chat_switch.mjs", "browser"),  # chain: shared-console reader — real ticket rows, zero-churn assertion
    ("t260903-07-chat-project-tag",
     "全局 chat 用户消息项目 tag 契约（t260903-07②）：引用真实工单 id 的消息行渲染文本=注册项目 key 的 chip（颜色非空）；同项目恒同色、不同项目不同色、页面重载后同色（确定性映射的用户可感知面）；全部 chip 文本 ∈ 注册项目键不造假 key；「归属不了→不渲染」是 env 相关声明行为、不在场景层强断言（L1 DOM 桩已锁，chip 经 ::before 伪元素渲染故断言走 getComputedStyle）",
     "node integration/t260903-07/sc_t02_chat_project_tag.mjs", "browser"),  # chain: shared-console reader — real ticket rows (chip color mapping)
    ("notes-write-gate",
     "机械闸守卫：dev-lane 工单禁写 notes/（宿主令 260904——票据/知识库账本归 main 侧直管，t260904-01/03 的 KI 行合并冲突与 notes/epics 草案直落为动因）。三执法点：A 合并闸 verify_lane 四态真子进程（声明了 notes/ 也拦防自授权/D 删账同拦/写集内普通文件不误伤/粗判据分支同拦）；B 建单侧 ticket.create 写集含 notes/ 创建即拒（纯函数面零 Temporal，人话指路结算 note）；C 本仓 verify.yaml write_allow 无 notes/ 静态防回潮。tmp git 仓全本地",
     "python3 -B integration/baselines/sc_notes_write_gate.py", "ro"),

    # ---- t260911-03 双闸（阶段路径闸+受保护路径闸，settle 落盘时刻执法）----
    # 260910 宿主实证回归：仲裁/走查等零代码段越权改码、泳道改共享守卫期望值给自己发免红令。
    # 实现段落地前闸子用例红属预期（TDD 验收门，先例见 t260905-05/t260904-08 族），arbitrate/merge 期必须绿；
    # sc_pathgate_legacy_compat D1 子用例（老票零干扰）现状即绿。
    ("t260911-03-walkthrough-settle-reject",
     "阶段路径闸·零代码改动段拒绝落盘（t260911-03 验收 a，灰盒 L3）：真实 settle 单点（tmp 主仓+真注册泳道 worktree 直调，零 Temporal）——acceptance_walkthrough/review_plan 注入产品代码改动→拒绝落盘终态三件套（0 新 commit+回执点名段 id 与文件+机读 path_gate_reason=unauthorized_path）、工作区原样保留（agent 产物不丢，.sandbar 结果文件伴脏不救场）；对照子用例=仅 .sandbar/ 结果文件照常落地（闸不误伤结果文件面）。与 notes-write-gate（合并闸 notes 面）/ki044 patch 门（merge 面）/t260904-18 背景文件闸（建单面）intent 不同面：本条执法点=settle 时刻阶段白名单；与 developer L1 judge 矩阵不同层（本条锁接线与回执传播）。t260916-19 B 契约修订：越权子用例改删除型（D 态）注入——??/M 态改自动处置不再终态拒绝，处置旅程归 t26091619-unauth-disposal-matrix",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260911-03/tests/sc_pathgate_walkthrough_reject.py", "ro"),
    ("t260911-03-protected-settle-reject",
     "受保护路径闸·真源与期望值文件（t260911-03 验收 b，灰盒 L3，260910 实证①回归）：共享电池（design_integration_tests 段、integration/ 阶段面内→非 unauthorized_path，双闸独立性证明）、共享守卫 test_route_table（arbitrate 段、测试面内——泳道改守卫期望值给自己发免红令的事故原样重放）均被拒+path_gate_reason=protected_path+点名+0 commit；「存在才拦」分叉点语义三子用例=闸自身出生放行、本票同泳道 rework 再改放行（base=分叉点非 HEAD，防每轮人审死锁）、落地 main 后新分叉泳道改它即拦（改共享守卫须 main 侧走票）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260911-03/tests/sc_pathgate_protected_reject.py", "ro"),
    ("t260911-03-normal-faces-land",
     "阶段路径闸·正常面不误伤（t260911-03 验收 c 反例三连，灰盒 L3）：implement 写集内两文件、design_integration_tests 只改 integration/、arbitrate 只改本票 tests/ 测试面——三子用例全部放行且回执零原因码、commit 真落地（git show 逐文件点名在 HEAD）；仲裁段碰产品代码反用例仍拒+点名（code-fault 只许打回 implement，260910 实证另一半回归）。机械闸不得堵死正常流；与 developer L1 judge 矩阵不同层（本条锁「放行=真落地」终态）。t260916-19 B 契约修订：C4 反用例改删除型（D 态）注入——??/M 态改自动处置，处置旅程归 t26091619-unauth-disposal-matrix",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260911-03/tests/sc_pathgate_normal_faces_land.py", "ro"),

    # ---- t260916-19 路径闸 blocked 死结三修（B 越权状态分流处置 / C 声明=执法 / D 证据面）----
    # 实案=dengzhufpv t260916-11：并行 join 闸拒后越权件滞留工作区每轮复判同一红、
    # 出路（打回目标段）不可达。本族守 activity 级公开回执与 git 磁盘终态（A 的
    # workflow 级 escape 旅程归 developer selfcheck_t260916_19_join_escape，不同层）。
    # 实现落地前新契约子用例红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t26091619-unauth-disposal-matrix",
     "越权处置按 porcelain 状态分流（t260916-19 修向 B＝滞留复判解除+D＝证据面，灰盒 L2 真 git 直调 settle_lane @arbitrate）：?? 未跟踪越权自动挪档（工作区消失+dot 目录 quarantine 留档含 manifest 审计+回执点名去向+二次 settle 复绿零新 commit）；M tracked 修改越权回滚+diff 留档可 git apply 还原（工作区回基线=分支零删除，agent 修改零丢失）；D 删除型/staged 暂存型 fail-closed 拒绝+人处不自动动（待删/暂存态原样保留）；protected 拒绝一律不动（文件原地=授权消费面前提）；混合批次（合法+??+M）一次处置后代落盘内容恰为合法清单（越权件与其留档件绝不入库，二次 settle 收口零循环）；拒绝回执 judged_files=本次判定脏清单全量（含合法项，实案④证据面歧义的结构化解除）。与 t260911-03 系不同面（彼守拒绝终态三件套、越权子用例=删除型，本条守处置后转绿与留档可还原）；与 t26091619-incident-replay 不同面（彼锁实案混合形态收口+C 合法化旅程，本条分态逐态终态）；与 developer L1 逐态白盒子用例不同层（本条锁 activity 级公开回执+git 磁盘终态+留档可还原性）。实现落地前新契约子用例红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-19/sc_t26091619_disposal_matrix.py", "ro"),
    ("t26091619-incident-replay",
     "dengzhufpv t260916-11 实案形态重演（t260916-19 修向 C 旅程+B/M 态解除，灰盒 L2 真 git 直调 settle_lane @arbitrate）：工作区同批=顶层 integration/sc_*.py 新建（agent 自救场景）+integration/README.md 修改（登记表）+integration/lint_tests.py tracked 修改（共享工具，实案第二轮自救件）——修复后一次收口：顶层场景与登记表合法落盘（C 的用户可感知面：仲裁改顶层场景/登记不再被拦，本职可完成）、lint_tests.py 回基线且修改以 diff 留档可 git apply 还原（B/M 态：分支零删除、自救产物零丢失）、代落盘内容恰为两个合法件、回执点名共享工具处置去向；反用例=lint_tests.py 删除型（D 态）仍拒+点名+零 commit（C 边界：共享工具面出路=rework 打回 design_integration_tests 或建票写集列名，不随顶层放宽连带放行）。与 t26091619-unauth-disposal-matrix 不同面（彼分态矩阵，本条实案混合形态+C 合法化旅程）；与 t260911-03-normal-faces-land 不同面（彼守正常面放行反例三连，本条守修复后实案形态闭环）；零源码解析全行为面（与 sc_check_auto_rework_trace 源码锁不同层）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-19/sc_t26091619_incident_replay.py", "ro"),
    ("t260911-03-legacy-compat-closed",
     "双闸兼容面（t260911-03 验收 d+R1②闭环，灰盒 L3）：老调用形状（不传闸参数=存量序列化缺字段形态）走查段改产品代码照常落盘——老在途票按 patch 门保护不追溯、行为零变化（该子用例现状即绿，兼当本套 fixture 机械证明）；显式 path_gate=False 同放行（开关语义）；path_gate=True 未知段 brand_new_stage→拒+path_gate_reason=unknown_stage+出路文案（补配规则/人审放行），新段忘配规则被堵出来而非自动免检（review_plan R1② fail-closed 裁决的链路级回归）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260911-03/tests/sc_pathgate_legacy_compat.py", "ro"),

    # ---- t260912-03 人授权例外通道（受保护路径 + 仲裁上限；唯一入口=既有 sign 面）----
    # 260912 双实证回归：受保护路径闸无「人审放行」入口（t260912-01 停 implement/blocked）、
    # 仲裁超限后的人裁定无回灌通道（t260911-05 两轮 blocked）。实现段落地前红属预期，arbitrate/merge 期必须绿。
    ("t260912-03-authz-protected-path",
     "受保护路径的人授权通道（t260912-03 验收 A/C/D 受保护子用例，灰盒 L3）：无授权改 integration/baselines/* → 照旧拒（path_gate_reason=protected_path+点名+0 commit+脏改动保留）；持覆盖该路径、未过期的授权 → 同一改动落盘成功且回执点名授权人/签发时间/路径/理由；负锁=scope 不匹配、空 scope、精确路径对照子用例一律照旧红；信号面 intake（真 handler，零 Temporal）负锁=过期授权不生效、who 为 agent 角色名（五角色全域+大小写/空白归一+-agent 家族）拒收、arbitration_verdict 别票票号拒收、不带 authorize 的 merge 签字语义不变、who/reason/scope 超上限与非法路径拒收。与 t260911-03-protected-settle-reject 同台架不同 intent（彼锁无授权面的 settle 执法终态，本条锁「有授权＝真落地+记名点名」与授权负锁）；与 developer L1（judge 纯函数/载荷矩阵/_within 相邻串）不同层不重复",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260912-03/tests/sc_authz_protected_path.py", "ro"),
    ("t260912-03-authz-overlimit-accept",
     "仲裁上限的人授权回灌（t260912-03 验收 B/C/D 仲裁子用例，灰盒 L3，真 docker 台+桩脑，单票单 worker 单舞台）：修复启用的 worker（非 SANDBAR_TEST_DISABLE_KI061=1——授权消费点=唤醒后新一轮 route 判定，需真 respawn 才可达；与 lib_ki061.drive_to_overlimit_blocked 的 DISABLE=1 驱动不兼容，本场景自建同形驱动）＋恒 tests-fault 桩驱动 6 轮超限→相一无授权仍 blocked（零回归，meta 无授权条目、uses 零）；相二经真 CLI 入口（client.py op=authorize→Signature.authorize→sign 信号面）投已过期授权→落 snapshot.refused（文案含「已过期」）、meta 不入条目、uses 全零，retry_qc 唤醒后仲裁真重跑仍 blocked（未被放行、历史无授权放行记录）；相三投未过期「接受本判决」授权（kind=arbitration_verdict、scope=[本票票号]）→meta 落条目（who/scope/reason/expires，issued 由 workflow.now() 盖写）→retry_qc 后票离开超限 blocked 推进 acceptance_walkthrough 或更后，handoff 可读「经人授权接受判决」+判决原文关键词（「测试集迭代」「超限」）+授权人，且该条目 uses≥1（消费留痕）；审计账本空+拆台零残留（后续 merge_check 段桩票转 blocked 属合法终态不判）。与 t260908-01-ki061-wake-revive 同台架不同 intent：彼两条锁「超限 blocked 的复活与重放兼容」（host_ruling 改判+retry_qc 唤醒的 arbitrate respawn＝KI-061 修复面），本条锁「人授权接受判决→超限不阻断」新通道及其无授权/过期负锁，不互替；与本票 sc_authz_protected_path 同票不同面；与 developer L1/L2（纯函数矩阵/四 handler 卫兵/归一）不同层不重复。docker/镜像/舞台缺件=ENV_FAIL exit 2 点名",
     "python3 integration/t260912-03/tests/sc_authz_overlimit_accept.py", "engine"),
    ("t260912-03-authz-cli-queryable",
     "人授权可查面（t260912-03 验收 C，灰盒 L3，真 docker 台+真用户 CLI）：走 server/tools/ticket.py 的 op=authorize/op=show/op=list 三个用户入口（不是引擎内部 snapshot、不是裸 client.py）——生效授权须在 show 读出类型/范围/授权人/到期/状态（生效中）/消费次数，并有签发事件（timeline state=authorized 点名 who+scope），工单列表行给出生效中计数 authz_active=1；负锁=过期授权经 sign 面送达（回执 ok）但 workflow 落 refused「已过期」且可查面条目数与计数不增（死授权不进历史面）、who=agent 角色名（反自签）同样拒收且可查面零变化；审计账本空+拆台零残留。与另两条同票场景不同 intent：彼二锁闸的行为（无授权红/有授权绿/超限不阻断，读引擎 snapshot meta），本条锁用户查询管道（CLI→client.py ticket-query/ticket-list→Temporal query→meta，KI-076 同族断点面）；与 developer L1（_authz_view/_list 合成 snapshot 格式化）不同层不重复",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260912-03/tests/sc_authz_cli_queryable.py", "engine"),
    # ---- t260913-01: 人授权通道传输缺陷（authorize 载荷丢失→静默回落普通签字） ----
    # 260913 integration 侧三条实锤复现（回执 delivered=true 只证送达；票面 refused 是
    # sign() 普通签字文案）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t260913-01-authz-signal-delivery",
     "人授权通道的真信号送达面+接收侧丢失可见化（t260913-01 验收 A 送达半边/C/D-A 子用例，灰盒 L3，真 docker 台+真用户 CLI+真专属 worker+真 workflow）：人授权唯一入口（server/tools/ticket.py op=authorize→Signature.authorize→sign 信号）在真实投递链上必须送达并被 intake 落账——本票事故面=载荷在传输/解码一跳静默丢失后回落普通签字；sign_face 指纹 query 在场且自述含 authorize 字段与 marker 保留值（worker 内存 signal 面可被客户端实时核验，陈旧 worker 结构性 absent=重启判据/拒发的根）；A 子用例真信号落账字段完整（who/kind/scope/reason/expires/issued/uses）+timeline 签发事件+回执 landing=landed 机读键；负锁矩阵全真信号投递且一律不落账：①过期（refused「已过期」+回执 landing=refused）②arbitration_verdict scope=别票（点名别票票号）③who=agent 角色名（反自签）④marker 保留值直发而无 authorize 载荷（=传输丢失后的解码等价形态）→refused want=sign(authorize) 点名「载荷解析失败」且与「非人审等待中」文案可辨（静默回落普通签字=事故形态）⑤畸形 decode-safe 裸 dict 缺字段→intake 语义拒收；类型不兼容毒载荷（authorize=123）故意不用=value_to_type TypeError 进 workflow task 重试循环。与 t260912-03 三场景不同面：彼锁闸的行为（protected_path）/仲裁回灌消费面（overlimit=本票验收 B 子用例与 D 的 B 半边）/用户可查面（cli_queryable），本条锁送达面+丢失可见化；与 developer L1（指纹/分类/落账纯函数单测）不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/镜像/舞台缺件=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260913-01/tests/sc_authz_signal_delivery.py", "engine"),

    # ---- t260915-12: 跨项目写操作闸（caller-project gate；260915 宿主实报立项） ----
    # 260915 虚惊复盘（dengzhufpv 票 t260915-02 合并签字）：签字合法但暴露引擎对写操作
    # 零项目边界校验。纪律层 charter 260915 已补，本票补机器层。实现段落地前红属预期
    # （TDD 信号），arbitrate/merge 期必须绿；undeclared=B 策略现状契约被场景相七钉住，
    # 跟进插件票接线后翻 A（undeclared=拒收）时由翻严票同步改写该相。
    ("t260915-12-gate-real-chain",
     "跨项目写操作闸的真链路用户契约面（t260915-12 验收①反用例/②正用例/③越权旗+对账面，灰盒 L3，真 docker 台+真用户 CLI+真专属 worker+真 workflow）：declared 身份（SANDBAR_CALLER_PROJECT/显式参数）与目标票 project 不符→fail-closed 拒收 kind=cross_project_refused+人话点名双项目与票号（ruling/sign/ticket-start 三入口同形状）+admin.log 行 override=false 且信号不出手（snapshot 零变化）；同项目写操作零影响仅回执增身份键（caller_project/identity_src 词汇 arg|env|cwd）；出处优先级显式参数>env（env 不能救显式他项目）；越权旗 cross_project{by,reason}→放行+meta['cross_project_uses'] 按笔记名（by/reason 原文在条目）+ticket.py show 用户出口可对账+admin.log override=true；畸形旗（缺 by/缺 reason/reason 空白）fail-closed 拒收不记名；undeclared=B 策略现状契约（放行+identity_class=undeclared+记名入对账面+admin.log 行）；cwd 兜底两形=仓内子目录必须 undeclared（注册表含 dirs=[引擎仓根] 探测条目，实现只排除仓根等值即行为反转红=review C1 探测器）、cwd 在注册项目 dir 内推导 declared identity_src=cwd；workflow 第二道直发 SDK 真 stamp 解码（review C5 送达面）=带头旗记名放行/不带头旗 refused[] 点名不执行/无盖章兼容不校验；retry_qc 不盖章残留诚实（client 放行+admin.log override=true 但 meta 记名不增=方案 §8 已声明残留非漏记）；读面零闸；cancel 过闸（他项目拒/同项目 terminate 放行）。与 t260912-03 三场景不同面（彼锁人授权 authorize 载荷维，本条锁调用方项目归属维）；与 t260913-01 不同面（彼锁 authorize 嵌套载荷送达，本条锁 stamp 标量字段真投递）；与 t260908-01 不同面（彼锁 pause intake 语义，本条只把 pause/ruling 当任意状态写 op 载体）；与 developer L1（纯函数矩阵/client 桩测）及其源码锁场景不同层。docker/镜像/舞台缺件=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-12/tests/sc_cross_project_gate_realchain.py", "engine"),

    # t260915-12 离线源码锁（实现段交付，方案 §4）：结构锁+真函数重放，无 docker/
    # 网络/pytest 依赖恒可跑；与 gate-real-chain 不同层（彼真链路行为面）。
    ("t260915-12-cross-project-gate",
     "跨项目写操作闸离线源码锁+微型重放（temporalio 不可导入环境既定模式，sc_check_auto_rework_trace 同款）：锁 undeclared 策略单常量（UNDECLARED_POLICY=record——C-0② 翻严锚点：翻 A 时本场景+真链路场景相七+README 三处同步改）、四个写信号载荷盖章字段带默认值（重放安全形状）、判定矩阵单点实现（shared.cross_project_judge 唯一真源，client/workflow 两侧零复制）并直接 import 真函数重放正/负/越权/畸形四子用例（畸形子用例：旗非对象/缺 by/缺 reason/超上限/身份形状非法/路径前缀混淆/空白声明=视同未声明）、client 八写 op 全接闸+retry_qc/update 不盖章但回执 notice 分档（C3 诚实残留）、cancel 前置快照三态（transient 不判越权 KI-025/not_found/先闸后 terminate）、workflow 第二道落点（base 混入四 handler+dev_lane 三 handler+旧模板 sign 统一接闸不留分叉）、ticket.py 包装层（仓树排除的 cwd 推导=C1、越权旗本层 fail-fast、对账白名单 cross_project_uses、schema caller_project+cross_project+op enum authorize|ruling=M2）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-12/tests/sc_check_cross_project_gate.py", "engine"),

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
     "UT 工序与 verify test 道落地防回退（合并守卫）；arbitrate t260910-14 移入 exclusive：其 test 道子进程=整条 engine pytest 走廊，与各池并发跑时受 docker 起台/端口窗负载挤撞两期实红、单跑恒绿——排他先行串行隔离（供给隔离，断言不变）",
     "python3 integration/sc_scenarios_guard_pipeline.py", "exclusive"),
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
     "路径契约化端到端（跨组件：注册条目×路径解析×spawn 组装×patch 产物，观测=cmd --patch 链与 patch 文件内容）：声明命中用声明值（roles patch 指声明目录、模型来自声明表，声明优先于现行约定）；未声明多态（无 paths 节/条目不存在/key 空/key 非法含穿越形状）角色 patch 走现行约定（roles 语义不变）而模型面无表=不打 model patch+引擎面点名 state=decl_missing（t260914-05 兜底分支退役，禁静默回落仓内表）；锚点在内容缺走软语义不红（t260903-03 ①d 用户旅程）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260903-03/sc_paths_spawn_seam.py"),
    ("t260903-03-paths-failclosed-red",
     "路径契约化故障面对抗（spawn 缝隙红传导，用户视角=红工单点名文件而非静默猜着跑）：条目 project.yaml 损坏（现行约定在位也必须红，不静默回落）、无表三态（t260914-05：指向缺失文件/未声明/目录当表=spawn 不红+无模型 patch+引擎面点名 state+指纹，三态互异不静默回落仓内表）、roles_dir 锚点缺失与类型错位仍红（roles 契约未放宽）、声明值畸形代表例（未知键/绝对路径/../穿越）一律红且文案点名键或解析后路径（t260903-03 ①d 三态）",
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
     "工单台 shipped bundle 与 src/client 源码同步守卫：lib/client.js≡client.cjs 双产物一致、契约特征词（parallel_stages 等）在用户实际被服务的产物内在案——改 src 忘重建 tsdown 时源码层全绿而真台面仍旧行为的静默穿透面（t260903-04 arbitrate，t260901-22 同族事故常驻化；t260915-09 追加当票特征词 withEpicProject=epics 穿参收口的盘上锚）",
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
     "charter 端点活体契约（t260904-07，ro fetch 级，隔离台 3199 拒 3099）：GET session-charter?project=<key> 部署后可感知契约——命中项目 200+{ok,charter}+key 实值化+零 {{ 残留（统一渲染）+命中分段头在文；未命中项目仍 200 只回通用段+无该 key 分段+{{project_name}} 弱化=key；缺/空串 project=400 形状错误 JSON 不崩不 5xx；404 时源锚复核精确归因（源码已接线未部署=fail，pre-merge=干净 skip 部署后自动生效）。t260905-04 仲裁修正命中子用例前提：命中 key 取「注册表∩session_charter.md 有专属分段」的 key（sandbar 优先），注册表在案≠有分段（泳道台 seedws 无分段假红实证），无交集时分段子用例=na 点名台数据前提非产品红。与随票 smoke intent 级不同层：smoke 直测渲染纯函数（内存面），本条锚 HTTP 可达面（真宿主真文件真路由）；「文件缺失回落」「改文件即生效」需对受控文件写操作不在活体子用例，回落归 smoke 纯函数直测、现读现渲染列人工走查",
     "node integration/t260904-07/sc_session_charter_endpoint_live.mjs", "ro"),
    ("t260904-07-charter-injection-journey",
     "charter 注入用户旅程（t260904-07，browser 隔离台）：项目行点 + 新建会话不输入任何内容即见 charter 为首条消息（占位符实值化无 {{ 残留——「每个 session 创建时注入我们想要的 prompt」原话验收面）+截图证据落 .suyou/screenshots/（KI-044 UI 票证据自觉）；随后切换相邻 tab 再切回、reload 重进既有会话，charter 特征串出现次数恒定+tab 集合不变（守卫：恢复/切换路径绝不注入，沿 t260831-08 ⑥ 口径）；console 卫生零 error（过滤无凭据环境已知凭据类噪音）。断言上限=注入链 UI 面，agent kick-off 回复链不在断言面（无凭据隔离台已知限制，有凭据环境人工复判）；未上屏且仅凭据类错误=干净 skip 不假红。与 t260904-05 生命周期场景（tab 形态/续号/关闭链）intent 级不同层：本条锚注入内容可感知行为。t260905-04 随迁折叠面：t1 新会话开头只见「已注入项目背景」小条+默认折叠+点击展开见全文（特征串计数断言因折叠态文本仍在 DOM 零改动兼容）；t2 切换目标会话小条在场性↔含 charter 一致（无 charter 会话不留幽灵小条——React 不移除外部节点，锚定失效须摘除）；t3 恢复路径折叠面随会话恢复不丢。折叠面断言 pre-implement 红属预期（TDD 信号）",  # naming-compat
     "node integration/t260904-07/sc_session_charter_injection_journey.mjs", "browser"),  # chain: shared-console writer — session + charter injection
    # ---- t260904-11 charter prompt wire contract freeze (KI-046 regression net, platform side) ----
    ("t260904-11-charter-prompt-wire-contract",
     "charter prompt wire 契约冻结（t260904-11，ro 供给只读面，KI-046 回归网）：07 票事故的病根是「客户端发什么形状×平台 zod 门收什么形状」这条跨组件接缝两端从未同场验证——developer 的 ki046 UT（workbench/tests）锚接缝客户端一端（真跑注入函数捕获 prompt 实参），本场景锚平台一端与镜像同步责任，intent 级不同层：①真源锚=平台供给内 dsh-host-apiproxy bundle 的 session.prompt 请求门确实是 content:array(promptContentPart) 分片数组门+text/image 判别联合（锚真实安装工件防镜像循环断言，宽松正则不锚压缩名）；②用户可感知拒收文案真源 invalid payload for ${method} 在文（toast 错误家族来源，平台改文案=漂移信号人审）；③冻结镜像语义（外部调用形状单测规范条款自范本：真 schema 不可导入则仓内冻结镜像+声明同步责任）——修复后分片载荷通过、KI-046 违规裸字符串被拒、缺 text 字段/非法 mode 同拒；平台门任一方向静默漂移本场景红，人审后两处同步。缺平台供给=显式红点名缺什么，不静默 skip（KI-046 闸穿透教训）",
     "node integration/t260904-11/sc_charter_prompt_wire_contract.mjs", "ro"),
    ("t260904-08-template-face-narrowing",
     "工单模板面收窄契约（宿主令 260904，t260904-08）：真源三表（TEMPLATE_CLASS_NAMES/TEMPLATE_CLASSES/TEMPLATE_DISPLAY_NAMES）恰存 dev-lane、四退役 .py/.yaml 物理退场、v1 幸存面（workflows.py 步1 类+DispatcherScanWorkflow）不过删；用户拒收面——create/ticket-start 传四退役模板任一被拒且报错文案恰列 dev-lane（列全=仅 dev-lane，多列/漏列都算文案失真）、dev-lane 仍过模板闸（推进到下一道必填校验而非「未知模板」）；suggest_next 推荐面已随功能整链退役（t260910-14）；client start 类型面收敛 dispatcher-scan（文案锚）。stdlib 段零依赖恒跑；ticket-start CLI 段 venv-half（解释器缺失干净 SKIP 注原因，KI-020③）。与既有模板面守卫无 intent 重复（退役收窄为本票新契约）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
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
     "add 产出条目的双侧装载一致性（t260904-10，ro 隔离根）：真跑 `sandbar project add` 后 Python shared.load_projects_registry 与 TS project-registry.ts.loadRegistry 从同一隔离根（SANDBAR_PROJECTS_DIR 临时目录）装载出同一条目（key/name/dirs 全等）、零隔离；首装载×seed 自动播种真路径（tracked 种子 suyou 在案+.migrated 落盘）且 add 后种子条目字节不动（决策7 不动账）；体检报告三词汇（verify.yaml/credentials/paths）在文且 credentials 先布置/裸目录两态输出可辨——排他性锚 project.yaml 文件而非条目目录（契约①b：目录与 per-key credentials 可先于 add 布置，O_EXCL 架在目录 mkdir 上=此子用例红契约对）；写入零 .tmp. 残留；--json 机器可判。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-10/sc_project_add_dual_loader.mjs", "ro"),
    ("t260904-10-project-add-rejections",
     "add 拒收面全枚举 CLI 真跑（t260904-10，ro 隔离根）：key 白名单（大写/下划线/首字符中划线/42 字符拒，41 字符上界收）；根目录形态（缺参/相对路径/是文件非目录——「不存在」子用例已随 t260906-01 容器代建翻转为成功旅程，移册 t260906-01-add-creates-container/-faultlines 承接）；多目录输入语义化拒收（epic 验收2 独立拒收路径：旗标面须能表达多目录输入，且文案点名「单根模型/多目录」——裸 argparse 用法错不算语义拒收）；已注册幂等同判（两次出口码+输出全等）；隔离条目同名拒收；根交叉与互为父子嵌套（父目录/子目录/恰等三向，文案报两个 key）；SANDBAR_PROJECTS_YAML legacy 拒收指路（文案点名存量 env）；name 三态（空/含 #/含换行拒且文案点名 name，首尾空白 trim 后收并读回验证）；每拒收子用例注册表根字节级零残留（快照比对+.tmp. 泄漏检查）；并发同 key 双 add 恰一成一拒且赢家条目 name/dirs 自洽不混写（TOCTOU 闸）；remove 点位稳定钉（输出点名 remove、无裸 traceback、注册表不动——票①骨架恒红/票②真实现两期皆存活）。实现落地前红属预期",
     "node integration/t260904-10/sc_project_add_rejections.mjs", "ro"),
    ("t260904-10-project-list-report",
     "list 报告契约（t260904-10，ro 隔离根）：人读与 --json 同列注册+隔离条目，隔离原因含 <dir>/project.yaml 定位字面，无 project.yaml 的保留目录不列；票计数降级三态——服务不可达（SANDBAR_TARGET_HOST 死端口注入）与 SDK 缺失（PYTHONPATH 空壳 temporalio 包注入，KI-039 教训：依赖缺失不得吞成无数据）两态均 exit 0 不红、条目照列、两态输出可辨；正常计数子用例在测试台 17233 可达时真跑（不可达有声 SKIP）。全程显式 env 钉死防缺省外溢生产 7233，零 3099 接触。实现落地前红属预期",
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
     "工单台全台面对比度看守（t260905-08，隔离台浏览器走查=KI-052「场景绿真台盲区」回归用例）：全文档可见文字元素实算 WCAG 对比度（computed color vs 沿祖先链合成到不透明的有效底色；色解析收 rgb()/rgba() 与 color(srgb …)——后者= color-mix 派生色的 computed 形态，epic chip/muted/meta 全在此列），在平台浅档/深档令牌注入与零注入（fallback-only）与旧平台子用例（t260907-03：knockout bg-primary 模拟 0.1.1-rc.2 无此名、bg-base=近白代表值，断言 --dsw-derive-canvas 精确等值=兜底链接得住旧平台令牌名）各子用例下正文级均须 ≥4.5（收口卡按「至少可分辨」3.0 卡——终态降权设计意图，红线不动；口径随 96c699c 热修正：板面 done 卡=muted 静音色、侧栏 done 卡仍 opacity:.72）；未知 computed 色形态=fail-closed 点名该子用例红，绝不静默计入达标（gen0 验收探针实锤旧解析只认 rgb 曾静默漏检 73% 表面，「绿≠全台面真查」KI-052 同构在看守自身复发的根治）；epic 色板 10 档经 fnv1a 槽位确定性挑码全播入（防采样盲区）；详情面（受阻横幅）/侧栏/metrics 文字面入扫（宿主裁定④全台面，不可达=na 条件子用例）；变异子用例故意注入低对比正文色断言看守必咬（变异测试守测试本身，改造前经侧栏 alias 消费面咬合）。病灶本质=改造前主区写死浅色自洽、三子用例全绿（KI-052 同构，如实预期）；两档令牌代表值来源=裁定④「模拟两档令牌」授权，真值待宿主确认；playwright-core/隔离台依赖缺失=env_fail（exit 2）不写 SKIP（三态契约，KI-046 第三层）；arbitrate/merge 期必须绿",
     "node integration/t260905-08/sc_wb_contrast_guard.mjs", "ro"),
    ("t260905-08-hex-clean",
     "工单台写死色清零静态断言（t260905-08，宿主令裁定②「#fff8c5/#ffebe9 等 hex 现场清零（grep 断言）」机械化）：server/plugins/workbench/src/client/ 全目录 .ts/.tsx/.css 样式消费位零裸 hex，颜色一律经 token 声明位（自定义属性定义值/var() fallback）供出；allowlist 三类零特例——EPIC_PALETTE+兜底灰按值级豁免（确定性哈希色，17 号断言守着）、metrics-charts.ts 整文件（echarts 数据编码色，非文本对比度语义）、token 声明位行级判定（var() 跨行写法不在保证面）；零外部依赖 CI 恒真跑（无 env_fail 路径）；实现落地前红属预期（TDD 信号，存量 ~351 处），arbitrate/merge 期必须绿",
     "node integration/t260905-08/sc_hex_clean.mjs", "ro"),
    # ---- t260907-08 theme sweep 2: docs page tokenization + full sub-surface sweep + two-platform x two-appearance quadrants (KI-055 root fix) ----
    ("t260907-08-wb-contrast-quadrant",
     "工单台对比度四象限矩阵看守（t260907-08，KI-055 根治面=主题家族第三次「台面绿真机红」的病根是验收矩阵缺平台版本维度）：验收升为 {新版全令牌集, 旧版 bg-base-only（0.1.1-rc.2 无 bg-primary 名，knockout 模拟）}×{深, 浅} 四象限，每格六张用户台面全扫（工单列表→详情抽屉→文档视图→立项单视图→新建工单弹层→metrics——文档/立项单/弹层为本票新扩走查面，宿主实报两症状的落点：症状①=浅色文档页、症状②=深色部分子面）；正文级 4.5:1、收口行卡 3.0:1，色解析收 rgb()/rgba()/color(srgb …) 未知形态 fail-closed 点名红（沿袭 t260905-08 口径）；legacy 浅格带 canvas 精确等值探针（兜底链接住旧令牌名=t260907-03 先例）；legacy 深格=诊断子用例：0.1.1-rc.2 深底 bg-base 代表值未经宿主确认前全扫照跑、比值全打印、na 注记入账不计入判定、不选方便假值造绿，宿主确认后填场景内 LEGACY_DARK_BG_BASE 常量自动升硬子用例（机械升级路径）；fallback-only 零注入子用例=硬子用例（兜底链自洽可读）；变异子用例低对比注入必咬（守测试本身）；coverage 反空转守卫：三张新走查面全程至少一格真实入扫（扫描区域计数>0，点击成功≠入扫），否则 fail-closed——防「导航 na 空转绿」（KI-052「绿≠真查」同构防御）；不另立 hex 清零场景（t260905-08-hex-clean 即该 intent 唯一看守，本票实现使其红→绿）。夹具跨票 import t260905-08 lib（bootConsole/teardownOnExit/loadPlaywright/TOKEN_SETS/cssVarsBlock），扫描器复制自该看守场景（漂移责任=两侧头注对齐）；文档=仓树真源（docs/ 定稿库）；立项单=夹具根自植（t260915-09 守卫修正：client 按项目根取数后夹具根无 epics 即列表空→弹层链断→coverage 守卫 fail-closed，自植一枚不弱化守卫）。playwright-core/隔离台依赖缺失=env_fail（exit 2，KI-036/KI-046 家族，不写 SKIP）；实现落地前红属预期（TDD 信号），arbitrate/merge 期硬子用例必须绿",
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
     "默认摘除生命周期（t260904-14，桩 poc_dir 全程零真 Temporal，全部子用例不可 SKIP）：默认（无 purge 旗）可逆摘除——project.yaml 退役移位（project.yaml.retired-* 在位）、data/（归档+metrics）与 credentials.yaml 字节不动、.lane/ 泳道残骸只报不删且报告含票号与数据处置词汇；双侧装载器（Python shared/TS project-registry.ts）不再列该项目且其余项目条目字节不动、零隔离；re-add 同 key 成功且 data/tickets 归档链连续；closed 未归档差集黄牌列票号（C1：目录在/manifest 缺=未归档）；--dry-run 注册表根字节级零变更；RUNNING 非空=拒摘报票号且零现场变更。台别=桩 poc_dir（--root 指桩树，假 client.py 经 FIX14_CTRL 注入票号级清单），零 3099/7233 接触。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-14/sc_project_remove_lifecycle.mjs", "ro"),
    ("t260904-14-project-remove-gates",
     "remove 闸语义面（t260904-14，台别按 C3 表逐子用例钉死）：真票子用例=隔离台自举 temporalite 起真 running 票→拒摘报票号→cancel 收口→重跑 remove 成功（验收5 全段含 M3 续步；唯一有声 SKIP 豁免子用例，依赖缺席打印原因）；其余子用例全部桩 poc_dir 不可 SKIP——Temporal 不可达=拒摘含 sandbar up 诊断指路（验收7）、sdk-missing 与不可达两态输出可辨（KI-039）、通道坏 JSON=拒；purge 双旗（差集非空拒列票号[C1 缺失态 manifest 缺=未归档、畸形态红点名 <id>/archive.json]、过闸真删 data/ 不动 credentials、--purge-credentials 独立、双旗组合）、dry-run+purge 旗只出将删清单注册表根字节级零变更（验收8）、最后项目无 --confirm-last 拒/带旗零条目警告+装载器空表抛错可辨（验收9）、legacy env 拒收点名存量 env（模式闸）、key 未注册拒零现场变更、隔离条目同名区分报含 project.yaml 定位。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-14/sc_project_remove_gates.mjs", "ro"),
    ("t260904-12-executor-three-state",
     "执行器三态退出码与输出契约（t260904-12，定稿 §7.3 闸内无 SKIP）：注入假场景表——全过 exit 0；有 FAIL exit 1；fail=0 且 env_fail>0 exit 2 且 ENV_FAIL [名] exit=2 行+缩进尾段点名缺什么；FAIL 与 ENV_FAIL 并存产品红优先 exit 1（C7）；未定义退出码落 FAIL 不放行不归环境（退出码封闭性）；全部子用例 N/A 经 lib_env 折算产品红（C9）；SUMMARY 五计数 ran=pass+fail+env_fail 双向净不变式+汇总与明细一致（不谎报）；lib_env 助手契约（env_fail→2、fail_if_all_na→1、部分 N/A 不红）",
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
     "node integration/t260904-15/sc_project_ui_host_routes.mjs", "engine"),  # engine: docker dsh-only 起台族收敛（t260910-05 仲裁）
    ("t260904-15-project-ui-rail-add-remove",
     "左栏三处就位+图标族换装+接入/摘除旅程（t260904-15，浏览器捕获，mock v5 过稿口径；t260904-19 起 docker 测试台）：组头第五枚「项目设置」svg 图标、「＋ 接入项目」行、隔离 key 红色行（无组头图标）三处在位（验收11）；四视图图标换装 svg 非 emoji、aria-label 齐、点工单列表图标 active 联动保留、侧栏可见文本 emoji 清零（验收11b 渲染面）；接入弹层坏 key 错误就地显示点名原因、合法 key 成功后左栏即时出现新组（验收12）；摘除弹层四步：处置勾选默认全保留、dry-run 清单先行、purge 勾选需输 key 二次确认（错 key 禁确认）、Temporal 不可达 fail-closed 文案就地含 sandbar up 指路（验收13）。与 CLI 场景（t260904-10/-14）intent 不同面：守 UI 呈现与交互旅程。实现落地前红属预期；playwright-core 缺失=ENV_FAIL 点名（KI-036 守卫，不假绿）",
     "node integration/t260904-15/sc_project_ui_rail_add_remove.mjs", "engine"),  # engine: docker dsh-only 起台族收敛（t260910-05 仲裁：宽池 ENV_FAIL 面）
    ("t260904-15-project-ui-settings-isolation",
     "设置弹层信息面+隔离详情+空注册表首接（t260904-15，浏览器捕获，与场景② intent 不同面：守信息面/降级口径/空表面；t260904-19 起 docker 测试台双实例）：设置弹层只读 key/显示名/根目录如实呈现；票计数 Temporal 不可达降级「—」类中性提示不红不谎报（验收11 降级口径）；体检区中性提示不含「无黄牌」谎报（R2b 降档口径）；danger 摘除入口在位；隔离红行点击见原因含 project.yaml 定位+修复指路（验收11）；空注册表 GET /wf/projects 200 空清单不 500、零分组仍渲染接入行且首接走通（验收9 空表面）。实现落地前红属预期；playwright-core 缺失=ENV_FAIL 点名（KI-036 守卫，不假绿）",
     "node integration/t260904-15/sc_project_ui_settings_isolation.mjs", "engine"),  # engine: docker dsh-only 起台族收敛（t260910-05 仲裁）

    # ---- t260906-01: onboarding a new project from zero (container-style: directory creation + container scaffolding + empty-project entry + route guidance) ----

    ("t260906-01-add-creates-container",
     "新目录容器代建一步接入旅程（t260906-01，ro 隔离注册表根+假 git PATH 桩）：根目录不存在（含父目录链）`sandbar project add --json` 一次成功=root_created+目录代建+容器脚手架全清单（CLAUDE.md 骨架、notes/epics|discussions/.gitkeep、docs/.gitkeep、server/model-routes.yaml）逐项在盘、scaffold.created 机械可判且 skipped 空、模板表与引擎仓真源 sha256 逐字节一致（同源模板不造两份）、CLAUDE.md 与 JSON warnings（container-no-git）含「容器未含 git 仓库」提示、注册条目落盘 key/dirs 可读回；文本形态报告含「生成物清单」「本次代建，含父目录」；全程零 git 调用（PATH 注入记录型 git 桩=调用日志空+项目树无 .git）。与 t260904-10-add-rejections（拒收面）intent 不同面：本条守代建成功旅程。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_add_creates_container.mjs", "ro"),
    ("t260906-01-add-scaffold-faultlines",
     "容器脚手架故障面对抗（t260906-01，ro 隔离根+--root 桩树注入源表三态）：已存在目录接入=项目根树快照逐字节一致（零新增零覆盖，自带自定义 model-routes.yaml 与 marker 不动、scaffold.created 空、root_created=false）；源表缺失与畸形（缺 default:/roles: 结构锚）两态=fail-closed 红+点名源路径+注册表与新建根零残留（回滚含整根与父链移除，绝不吞成空拷贝）；代建×防呆闸交互=新根为已注册根的「尚不存在」祖先仍被闸 d 拒（拒后祖先不被代建=闸序在 mkdir 之前的锚、注册表快照不变）。F1 并发同根异 key TOCTOU 为已登记预存洞（本票不修），不入闸防并发假红。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_add_scaffold_faultlines.mjs", "ro"),
    ("t260906-01-routes-uninitialized-init",
     "路由无表引导态+init 退役终态（t260906-01 场景③，t260914-05 兜底分支退役重写；API 面无浏览器，mock webServer 手法同 ui smoke E 段、进程内 apply 零 3099 接触）：无声明项目=无表引导态——state=decl_missing+uninitialized=true+default=null+routes_file=\"\"（无落点），resolution_error 点名「未声明」+建表模板指引；**反毒断言**：仓内 server/model-routes.yaml 即使仍在位也不被读、内容不透出（「过期表被静默用错」=t260914-05 要杀的毒面）；init 端点退场（POST /sandbar-admin/api/routes/init 不再挂载=零写动作）；已有项目自有表但未声明→不被读也不被改（字节零变更）；声明指向畸形表→编辑视图诚实暴露解析失败并给 state=bad_content+内容指纹（与引擎 parity；运行时读面归 t260903-03/t260910-14-S1 钉）。wire 口径=project 走 ?project= 查询参（与同族 GET 一致）。与 t260904-15-host-routes（workbench 薄壳透传面）intent 不同面：本条守 ui 路由视图自身契约。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_routes_uninitialized_init.mjs", "ro"),
    ("t260906-01-session-entry-empty-labeled",
     "空项目会话入口可发现+弹层代建口径（t260906-01，workbench 客户端 src+lib 双锚灰盒，同 project-sessions.mjs S3 守卫手法）：账册空=「＋ 新建会话」带字按钮锚（wb-psess-new-labeled 变体+tabs.length===0 条件分支）在 src 在场、lib/client.js 同批在场（lib 锚=bundle 重建看守，KI-052 客户端半从盘现读——盘上 bundle 旧=改了也看不见）；data-wb-psess-new 数据锚与 24px 方块样式保留（有 tab 恢复现行形态、既有 smoke 旧断言不回归）；接入弹层预检口径退役「存在性」措辞、改「自动创建」。真 DOM 呈现归合并闸 ui_evidence 截图证据面（KI-036/044 家族），不重复 browser 子用例。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260906-01/sc_session_entry_empty_labeled.mjs", "ro"),

    # ---- t260904-18: three new gate contracts (refs ticket-creation gate / files_changed receipt shape / declared-form ui_evidence) ----

    ("t260904-18-refs-gate",
     "建工单背景文件闸（t260904-18 门①，宿主令「没提交的 note 不让建工单」+知识库设计 §1 工单引用铁律，灰盒 L2/L3）：票面 refs 引用未提交背景文件=建单即拒且报错逐个点名文件——三分类（工作区脏改/暂存未提交=已跟踪≠已提交/不存在）经真 git 夹具仓 HEAD 态驱动；畸形引用（绝对路径/含 ..、非列表字符串=逐字符假护栏形态）拒收点名不静默清洗；拒收路径零 Temporal 接触（校验接线先于 cmd_ticket_start 首个 _connect 的源码序锁；存量票无 refs 不追溯=backlog 口径）；闸回执形状不锚定（布尔/元组/dict/异常皆容错解释）只锚「拒+点名」。与 t260904-02-ticket-start-anchor（project 锚定闸 KI-032）intent 不同面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（入口装配子用例），stdlib 闸行为子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260904-18/sc_t260904_18_refs_gate.py", "ro"),
    ("t260904-18-ki049-write-set-contract",
     "files_changed 回执形状×写集刷新缝上契约+机制活性巡检（t260904-18 门②，KI-049 修复面②③④，灰盒 L2）：以真实 agent 回执形状喂解析→刷新链（mock 填满字段掩盖过的缝）——字符串回执（「叙述写了补列、字段没填」姊妹形态）不得在解析层毁形成单字符列表（毁形强转三解析点退役=源码负锁，normalize 拒形 shape=malformed）；畸形与空数组在消费点=可见红 meta.write_set_refresh_fault+告警点名+不调 refresh（写集零污染）且不得再出「写集已随方案定稿刷新」中性行冒充成功（报错必须精确）；None 维持跳过语义（selfcheck 在场锁共存）；no_file_changes 在案豁免；合法非空回执→「授权扩展」日志非零（dead-man 开关：机制全史 0 次生效的死亡形态从此有断言网）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（解析缝/消费点行为子用例），stdlib 链子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260904-18/sc_t260904_18_ki049_write_set_contract.py", "ro"),
    ("t260904-18-ui-evidence-declaration",
     "ui_evidence 声明制（t260904-18 门③，KI-050，灰盒 L2/L3）：UI 截图证据目录由项目声明（verify.yaml 顶层 ui_evidence）——verify_lane 白名单收该键（未知顶层键 fail-closed 雷 t260903-11 同位不触发）、dirs 畸形=红点名字段（契约②三态总纲：畸形≠缺省）、缺省=merge_check 截图项 green+可见 note「未声明」（行为可见非静默，非 SKIP 非假绿）、有声明+diff 命中=无 png 仍红（闸没松）、diff 故障=红不因缺省豁免（对照子用例）、有声明+未命中=不出项（拓扑级缺席）；load_ui_evidence 三态；sandbar 五路径迁入仓根 verify.yaml（迁移等价 rod：声明集合≡legacy 表）；review_gate 接线源码锁（UI_EVIDENCE_DECL_PATCH_ID+meta 预载 ui_evidence_dirs）。与 t260904-13 三场景（判定源/闸输出/接线编排，KI-044 面）intent 不同面：本条守声明制新契约面；与 contract-v11-regression-rods（v1.1 勘误面）不同层。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（merge_check 行为子用例），verify_lane/声明子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260904-18/sc_t260904_18_ui_evidence_declaration.py", "ro"),
    ("t260904-19-stage-docker-cli-contract",
     "docker 测试台唯一搭台入口的 CLI 对外契约缝（t260904-19，灰盒 L2）：up 产出场景可直接消费的 JSON（project/temporal 非空、127.0.0.1:<int> 形）、down 幂等二连且拆台后端口立即可复用（验收④）、docker 缺席=exit 2+ENV_FAIL 点名 docker（验收③三态）与 test-temporal 镜像缺席=exit 2 点名 build-test-temporal.sh 两文案可辨、畸形工程名非零拒收且输出点名 project 且零残留；生产端口 {3099,7233,8233} 绝不返回（3099 红线=CLAUDE.md 硬规则1）；bind 探测器占用/空闲两态自证防恒真。断言只锚 CLI 进程级公开行为（退出码/stdout JSON/docker ps 公开观测面/socket 可连性），契约不变的实现重构不得打破。与前层分工：helper 内部机制（档位锁/分配原子性/畸形全电池）归 developer L1 test_stage_docker.py，本场景守真进程消费缝（KI-049 同族：mock 单测覆盖不到缝契约）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-19/sc_stage_docker_cli_contract.py", "engine"),  # engine: 起台族收敛（t260910-05 仲裁）
    ("t260904-19-stage-docker-parallel-zero-residue",
     "双场景并行不互撞+拆台零残留端到端（t260904-19，灰盒 L3，工单验收①④；槽位制退役后并发隔离语义的用户级承接面）：两个 up 进程真同时发车（各自 compose 工程名，temporal-only 档）双台健康、JSON 端口互异、双双 ∉ 生产端口 {3099,7233,8233}；docker ps -a 按 com.docker.compose.project label（compose 公开语义）过滤 A/B 容器集互不相交且 temporal-only 恰 1 容器；拆 A 后 A 端口立即可 bind 且 B 台 TCP 复测仍活（down 爆炸半径恰一个工程）；full 档 console+temporal 双端口真活（helper exit 2=其判环境红不诬产品）；三工程终态零残留、全部用过端口立即 bind 成功（验收④收口）。与 developer L1（档位锁/分配原子性单测）intent 不同层：本条守进程级真并发系统行为，mock 与先后错开都替代不了该形态。资源口径：有意制造并发双台+一次 full 台（dsh 镜像烤制后起台秒级；建镜像才联网，见 build-test-dsh.sh），登记 exclusive 独占执行防与兄弟场景的台互相污染判定面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-19/sc_stage_docker_parallel_zero_residue.py", "engine"),  # engine: 3 concurrent stages on purpose — daemon-pressure canary (loud ENV_FAIL surface accepted)

    # ---- t260910-12: 起台面租约化（启发式存活判断换租约语义+幂等ensure+并发上限+瞬态重试）----
    # 消费面单一入口=stage_docker.py（with_stage.sh / stage_docker.mjs / 池内 with_stage 雷群），
    # 场景锚 CLI 进程级公开行为与 docker/进程表公开观测面，不锚租约内部文件布局。
    ("t260910-12-herd-no-crosstalk",
     "并发 N=6 套件起台零端口重叠零互相拆台（t260910-12 验收①，灰盒 L3）：六路 ensure 真同时发车（temporal-only 档）全成功、端口两两不相交且 ∉ 禁产硬集 {3099,3199,7233,8233,17233,18233}、各台端口全程 TCP 可连；持有期内二次 ensure=幂等复用（reused 且 container_ids 与首起一致）——「同 compose 项目二次起台挤掉健康台」（背景 run L/M/O 族）在 herd 风暴窗根治的用户级证据；六工程终态零残留、全部用过端口立即 bind。与 t260904-19-stage-docker-parallel-zero-residue（双台隔离/爆炸半径）intent 不同面：本条锚 herd 风暴窗规模（产品红阈值上沿 N=6）与持有期幂等稳定。资源口径：6×temporal-only 台 engine 池同窗执行（与兄弟场景互为真实负载，竞态压力就是被测面）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260910-12/sc_herd_no_crosstalk.py", "engine"),
    ("t260910-12-holder-kill-reclaim",
     "持有者被杀→TTL 后回收且不影响他人（t260910-12 验收②，灰盒 L3）：起台 A 后持有子用例进程在场（pgrep -f 匹配 CLI 子命令行，进程表公开观测面）→SIGKILL 杀持有子用例→杀后立即起台 B 成功且可服务（他人零波及）→注入小 TTL（SANDBAR_STAGE_LEASE_TTL_S 方案注入口）等租约过期→A 再 ensure=接管重起（container_ids 更替=旧台回收重建，非复活残台）→B 全程不受回收影响→双工程零残留。锚「回收判据=租约过期 AND 持有者进程不存在」的确定语义：持有者死亡是唯一触发，无 docker ps 采样/新鲜宽限参与。与 L1（假 pid 四象限 UT）不同层：本条守真进程 kill 的系统行为。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260910-12/sc_holder_kill_reclaim.py", "engine"),
    ("t260910-12-full-capacity-queue",
     "保险丝刹停点名不假红（t260910-12 验收③；原「满员诚实排队」语义随 t260912-02 ①退役——排队闸是全机共用名额，实测只制造假拥堵：上限 12 时 12 台并发 3 台卡满 150s 超时、改 30 即 12/12 共 5.3s；闸的职责收敛为防呆保险丝，本条为断言强度等价迁移非放宽）：注入 SANDBAR_STAGE_MAX_STAGES=1（env 旋钮=方案注入口，只影响本场景子进程）——先到者 A 占满唯一额度后正常起台且全程可服务（先到者不受扰）；后到者 B 在 A 持有期内发起 ensure **立即刹停退出**：rc=2、stderr 点名「起台保险丝」并附活租约清单（holder pid/票号）、期间零容器（不硬挤不假红）、红行**不含「满员」字样**（瞬态白名单不得重试失控红）；A down 释放后 C 预算内成功入位且端口可服务。锁根拓扑（arbitrate gen1 修正沿袭）：本场景用隔离锁根——保险丝计数=锁根内全部活租约，生产共享根上并行泳道活动台会被计入导致注入小额度自卡死（gen0 两次 600s 超时实锤）；隔离根上 A/B/C 判定互斥真实同根执行，跨泳道竞争不属于本条 intent（生产由缺省值 100 承担）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260910-12/sc_full_capacity_queue.py", "engine"),
    ("t260910-12-idempotent-reup",
     "同租约二次 up 幂等复用容器未被重建（t260910-12 验收④，灰盒 L2/L3）：首起记 container_ids→同项目二次 ensure：reused=true、container_ids 逐个一致（容器 id 不变=工单原文口径）、端口一致且台可服务；down 拆台零残留。与 t260904-19-stage-docker-cli-contract 的 ensure 幂等锚不同粒度（彼锚 CLI 缝 exit 0/JSON 形，本条锚本票新交付 container_ids 契约字段与「容器 id 不变」强断言——互拆根治的直接证据，mock 替代不了真容器 id 观测）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260910-12/sc_idempotent_reup.py", "engine"),
    ("t260910-12-cwd-independence",
     "全部 CLI 行为在不同 cwd 下结果一致（t260910-12 验收⑤，灰盒 L2）：cwd=仓库根起台后，cwd=/tmp 与 cwd=/ 对同项目 ensure=幂等复用（reused、container_ids 与端口和首起完全一致——cwd 不改变锁根/仓库锚/状态面解析，另起一台即红）；cwd=/ down 成功零残留；场景自身路径全 __file__ 锚。防本票新增 hold 子用例/租约文件/容量闸任一环写成 cwd 相对路径。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260910-12/sc_cwd_independence.py", "engine"),
    ("t260910-12-transient-retry-contract",
     "瞬态分类与一次重试契约（t260910-12 目标④，灰盒 L2 库契约，秒级零 docker）：三类已知瞬态（台内 502/端口拒连族/起台面繁忙族）判 transient、终态环境红（镜像缺席等）判 fatal 不重试；retry 恰一次——首试瞬态次试成功=成功且调用计数=2、两试皆瞬态=原样抛最后一次文案逐字节不变（仲裁分类器不再被迫吸收）、首试非瞬态=不重试；畸形输入（空串/非字符串/超长行）安全拒收不炸；py judge 子命令逐桩输出 transient|fatal（单源真源），mjs 薄包装 node 可加载。锚方案承诺的公开契约（库函数名/judge 子命令/薄包装存在），不锚内部布局。实现段落地前 import 红=FAIL 属预期（TDD 信号），arbitrate/merge 期必须绿；node 缺席=ENV_FAIL 点名（mjs 子用例）",
     "python3 integration/t260910-12/sc_transient_retry_contract.py", "ro"),
    ("t260910-12-lease-unit",
     "租约化起台面 developer L1 全电池（t260910-12，灰盒 L1，假 docker shim 零 docker 依赖）：回收判据四象限（新鲜+活=复用/过期+死=回收/过期+活=诚实红绝不硬拆/新鲜+死=判死回收）锚「过期 AND holder pid 不存在」唯一判据；并发写原子性（8 线程×40 写读者只见完整 JSON）；起台保险丝（t260912-02 语义迁移：计数=活租约+占位同临界区不超售、触闸红点名保险丝并附活租约清单且不含「满员」字样、非触闸负锁、锁获取有界等待保留、释放准入）；残台清扫判据矩阵（主人存在性 crit_i/ii/iii 拆、booting 新鲜/泳道在册两阀不碰、C4b 活台+目录在 fail-closed、畸形租约保守）；受管网段分配（表内/随机不序列/排除在册与 daemon/保留槽/畸形 base 拒收）；hold 子用例七路终态（正常收割 exit 0 且不补写/downing 二次校验不回写/锚死回收/起台孤儿回收/写失败非0/SIGTERM 130 不拆台/超帽 rc6）+预租约等待预算=起台者存活期；ensure 状态机（TTL 加速真翻面复用、R3 ps 空窗扛性、booting 等待零再起、孤儿 booting 接管恰一次冷起）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/tests/test_stage_lease.py", "ro"),

    # ---- t260905-03 inspection ticket 1 (scheduled quality-check skeleton + test-surface scan) ----
    ("t260905-03-ki051-anchor-replay",
     "KI-051 守卫锚×生产方措辞漂移静态回放必抓（t260905-03 验收②主证据=KI-051 事故回归用例，灰盒 L2）：真形态夹具（生产方在位——模板拼接旧字面搜不到，即 KI-051 实录 capture.mjs L342 形态——+守卫断言旧字面）扫描必报 high 且证据双点名守卫与生产方；健康对照（字面在场）零误报 high；无法确证（生产方在位但措辞无近亲）降级 med 提示交人审，不判绿不静默；空壳守卫不崩。纯 stdlib 夹具零 env 依赖零真仓接触——环境红永远捂不住本断言面（KI-051 被 env_fail 捂数日的教训内建）。与 developer L1（扫描纯函数真值表）不同层；与 t260904-08 模板退役负扫描不同面（彼守退役类名零活引用，本守在役守卫锚×生产方措辞在场性）。扫描器 CLI 与 findings 形状为本票场景侧裁定（integration/t260905-03/lib_inspection.py 头注）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_ki051_anchor_replay.py", "ro"),
    ("t260905-03-scan-contract",
     "测试面扫描器对外契约（t260905-03，灰盒 L2 固定夹具）：findings[{id,severity,scan,evidence,suggestion}] 五键齐/severity∈{high,med,low}/id 唯一/证据非空；重复场景检测阈值两边界——intent 近逐字重复对必报 med（不混 high 混淆严重度）、不同守护面条目不误报；过时断言（引用资产缺席/已挪、行号越界）必报且证据点名缺什么（报错精确）；干净树=ok:true+findings==[]（全绿期零发现心跳的数据面，非静默）；红线判定化——扫描全程被扫树逐字节校验和不变（巡检绝不直接改码）；二进制乱码被扫输入不崩仍结构化回执。纯 stdlib 夹具零 env 依赖。与 t260905-03-ki051-anchor-replay intent 分工：彼守 KI-051 事故四面，本条守扫描器横向契约（步骤共享 lib 夹具构造器，intent 不同面不互替）；与 developer L1 不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_scan_contract.py", "ro"),
    ("t260905-03-decl-gate",
     "声明门——触发面尊重 inspection.yaml（t260905-03 验收③行为级证据，灰盒 L2/L3）：畸形声明拒绝且理由指向声明本身（报错精确：声明错不得报成连不上——KI-051 环境红捂真红的反向教训）；启用实例声明未接线 kind 拒绝并点名该 kind 与已接线清单（fail-closed 不静默不触发，M2 口径）；enabled=false 占位实例与未知实例拒绝并点名；enabled 实例放行回执带票号（改声明改行为的放行半边）；同期重复触发回执仍指同一张票（每期一票机械保证=scan_schedule 照搬取舍① overlap=SKIP 的用户级承接）。三态分级：拒绝子用例=交付触发面离线校验（--decl-path，纯标准库零网络）闸内即验；放行子用例缺 temporalio/共享台=ENV_FAIL 点名（不假红不假绿）。与 developer L1（decl 解析真值表）不同层：本条锁触发面的门行为；与 t260905-03-period-journey 不同面（彼守链路质量，本守谁能跑/谁被拒）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_decl_gate.py"),
    ("t260905-03-period-journey",
     "手动一期全链用户旅程（t260905-03 验收①主证据，灰盒 L3 真台真票，exclusive）：temp decl 双实例启用+--decl-path/--repo-root 注入夹具（真仓是干净的，不种漂移测不到发现落面；真树零写入红线不破）——种漂移实例：trigger→开票→发现清单落票面（high 带证据+suggested_fix_tickets 逐条 source_inspection=本巡检票号=修复票溯源面）→人门两拍（未签字观察窗内不终态=假门现形即红；运维通道 sign 后收口且发现留存票面=发现/处置审计链不断）；干净实例：零发现心跳票照开照收（全绿期=心跳证明）；两实例票号互异（实例维度不串票）。人门绑定浅：只锚公开 sign 面与终态可见，不锚 snapshot 内部门名。temporalio/共享台缺席=ENV_FAIL 点名（KI-036 家族口径）。登记 exclusive：往共享台写真票，防与兄弟场景互染判定面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260905-03/sc_inspection_period_journey.py", "exclusive"),  # exclusive: the ONLY barrier entry — writes real tickets to the shared default 7233 temporal (mutex with main-pool decl-gate on the same surface)

    # ---- t260910-09: inspection ticket 2 (mechanism/simplify faces — dead-man generalization + patch-retirement) ----
    ("t260910-09-ms-scan-contract",
     "机制/简化面扫描器对外契约（t260910-09 主证据，灰盒 L2 固定夹具，纯 stdlib 零 env 依赖）：新两面 CLI 单行 JSON {ok,result|error} 同票①、result{face,findings,summary,heartbeat,meta} 形状齐、findings 六键/severity 三值域/id 唯一/证据非空（UI 巡检行通用消费的数据面承诺）；dead-man 正例=三重零命中（场景零引用+日志字面零命中+代码路径零调用）必报 med 且证据含 文件:行+带分母零计数（0/N 形——空集≠查过零，review C2 口径；零日志字面机制仍判，日志面空集不得当豁免）、meta 记录「全史」口径局限（方案 D2 不静默承诺）；反例三连=场景引用/被调用/注册表豁免任一命中即不报（并集破零）、在役函数零误报；影子代码=零调用+新旧命名对必报 med 且在役侧不报；补丁退役=*_patch 宿主被 v2 取代必报 med 且 suggestion 含「删了会怎样」风险注（本票硬性口径）；重复防御层 med；过长/过深点名 low（显著超阈 120 行/深 8 必点名、显著低于 40 行/深 2 不误点名——阈值精确边界 80/81 真值表归 developer L1）；零发现=findings==[]+heartbeat true（全绿期心跳票数据面，语义与票①逐字段同构）；红线判定化=两 face 扫描全程被扫树逐字节不变（巡检绝不直接改码）；畸形输入不崩（NUL 乱码模块逐项降级 meta 点名不株连、仓根缺失 ok:false+非零退出+error 点名路径 fail-closed）；真仓 smoke 两 face 只读可跑（发现量级不 pin，沿票① 子用例8 口径）；face 分派缝=activities.run_inspection_scan 缺省（无 face 键）走 test 既有语义零变化、face=mechanism 走新面、未知 face ok:false 且 error 点名已知面清单（子用例需 temporalio=venv 重入，缺席 ENV_FAIL 点名不假红）。与 t260905-03-scan-contract intent 不同面（彼守测试面 S1/S2/S3 契约，本守新两面）；与场景②不同面（彼守声明位与门数据面，本守扫描行为本身）；与 developer L1 不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260910-09/sc_inspection_ms_scan_contract.py", "ro"),
    ("t260910-09-ms-decl-gate",
     "新巡检实例声明门——mechanism-face/simplify-face 声明位与门数据面（t260910-09，灰盒 L2 离线子用例为主；t260915-10 arbitrate 起声明真值随宿主 260915 令演进=c946380：mechanism-face 仍 enabled=false 占位且不进 schedule_specs（「enabled 按宿主节奏」兑现面）；simplify-face 启用试跑=enabled:true+显式 scan_face=simplify（宿主令注记防呆：scan_face 缺省落 test 面，此断言随令新增强化）、enabled→进 specs=门数据面本征与子用例b 夹具自证同语义——旧「两占位 enabled=false」前提随宿主令退役，非本票改动面、归因见 t260915-10 仲裁报告）：两新实例在场（face 由实例 id 承载可派生）；夹具声明 enabled 新实例进 specs 且 face 原样透传、disabled 不进（改声明改行为、decl 零改动承诺的数据面）；enabled 新实例过门真触发子用例（回执带票号）缺 temporalio/共享台=ENV_FAIL 点名不假红（沿票① decl-gate 三态分级）。与 t260905-03-decl-gate intent 不同面且不重测：彼守门行为本身（畸形/未接线 kind/占位/未知四类拒绝+test-face 放行——新实例同走该门不另测，防 intent 级重复），本守新实例的声明位在场与 face 透传数据面；与 developer L1（decl 纯函数真值表）不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260910-09/sc_inspection_ms_decl_gate.py", "ro"),
    # ---- t260905-02: engine-behavior scenario watch (worker lifecycle / settle self-exit / multi-console dedup; epic follow-up faces) ----

    ("t260905-02-worker-lifecycle",
     "工单专属 worker 进程生命周期（t260905-02 行为①，灰盒 L3，docker 舞台）：起=归属 meta（SANDBAR_WORKER_META 指路）限期落盘可解析且形状可辨（pid=真 pid、repo_root=realpath 引擎仓、ts 可解析、version 非空——KI-033 契约数据源面）；退=SIGTERM 限期优雅退出（退出码 0 非崩溃形态）+meta 自清+TERM 二连幂等不炸；异常输入=meta 指向不可写路径（父路径是文件）写失败不阻断启动（best-effort 契约）、起跑痕迹在文（stderr 归属指纹行）、路径上不冒出 meta、TERM 后照常干净退。与 t260904-02-worker-fingerprint-gate 分工：彼=ensure 消费侧三态判定（同仓/异仓/未知），本条=worker 进程侧自身生命周期（TERM 后 meta 被清一面两处观测不互替）；与 t260905-02-ticket-worker-watch-exit 分工：彼=watch 联动自退（自己走），本条=外部信号停（被叫走）。被测子进程零连生产（审计钩子+自证子用例）；日志锚兼容正则锚语义（KI-051）",
     "python3 integration/t260905-02/sc_worker_lifecycle.py", "engine"),  # engine: one docker stage + real worker (TERM leg)
    ("t260905-02-ticket-worker-watch-exit",
     "收口自退不留尾巴（t260905-02 行为②，灰盒 L3，docker 舞台+真工单）：票收口（workflow 非 RUNNING 终态）→ watch 中的专属 worker 限期自退（退出码 0、收口语义日志在文、meta 自清）——工单收口后不留常驻 worker（260824 A 案：专属 worker 生命周期跟工单走）；孤儿收养自退=宿主死（worker 被收养 ppid=1）→ 自退不留无主 worker（85222 版本投毒教训；收养目标 ppid 随环境为系统状态条件子用例，收养不到时按 N/A 折算）；查询失败不误退=watch 指向不存在 workflow → worker 持续存活 ≥ 两轮 watch 周期且留下「查询失败下一轮再试」痕迹（宁可多守一轮，不许票没守到人先走）。watch 生效前提两 env 同置（SANDBAR_WATCH_WORKFLOW 置时 watch 循环才存在，ppid 守护在循环体内）；watch 间隔旋钮 SANDBAR_WATCH_INTERVAL_SEC 提速（「≥两轮」按日志实际轮次判：旋钮生效 ~4s 收工、失效自然回落 30s 慢档 90s 窗内同判，语义不弱化）。与 t260904-02-worker-fingerprint-gate（ensure 消费侧）与 t260905-02-worker-lifecycle（外部信号停）intent 不同面",
     "python3 integration/t260905-02/sc_ticket_worker_watch_exit.py", "engine"),  # engine: one docker stage + worker + watch-timing legs (load-flake watch surface)
    ("t260905-02-console-duplicate-guard",
     "多 console 同槽防重与辨析文案（t260905-02 行为③，灰盒 L2/L3，docker 舞台+node 直跑 node.ts）：server 单例=同槽已有监听者第二 console 静默认领（不重复 spawn 不报错）；worker 单例=daemon pidfile 在册双 console 均不重复拉起且 dispose 不动在册他人 worker（资源归属）；工单 worker pidfile 抢注互斥=同 tid pidfile 位被占（'wx' 确定性必败注入：目录占位，非时序竞态）→ 辨析文案在文且点名 tid（「已被别的实例抢先注册，停掉重复 spawn」语义）、重复 child 当场 SIGTERM 回收（日志 fd 持有者归零观测）、无成功 spawn 文案（不两开花）；dispose 收口=幂等二连不抛、定时器清空（node 自然退出=事件循环空，挂死=超时红）。与 t260904-02-worker-fingerprint-gate 分工：彼=ensureTicketWorkersOnce 纯决策面三态（spawn 可注入），本条=apply 全真路径双 console 防重（纯决策面不含 'wx' 互斥分支，替代不了）。被测 python 子进程零连生产（apply 内部 cli/ensure 的 TARGET_HOST 由子进程 env 钉舞台；审计钩子+自证子用例）",
     "python3 integration/t260905-02/sc_console_duplicate_guard.py", "engine"),  # engine: writes real repo server/engine/data (no pool scenario reads that dir)

    # ---- t260905-01: the two settle questions (distillation trigger + reverse-sync gate, doc-lifecycle ticket 2) ----

    ("t260905-01-doc-gate-questions",
     "收口两问防回退守卫（t260905-01，灰盒 L2/L3）：触发器/闸各带防回退——源码锁半（处处可跑）：STAGE_ACCEPTANCE_EXTRA[acceptance_walkthrough] 两问文案在位（沉淀+从 deliverables 推预填建议+矛盾反向同步+转正纪律句=债登记纪律进流程的流程落点）、agent_activities 判读纯函数三件套（parse_doc_gate/register_pending_doc_sync/apply_doc_gate）定义与 acceptance 返回路径调用位在场（触发器被整段拆除=红，防「实现与单测共谋删除」回退）、pending-doc-sync.jsonl 债册常量、dev_lane STAGES 走查块两问验收项；行为半（temporalio 面）：parse 正常两态/显式无可沉淀≠未答/两问缺席各自可辨（per-question absent）/畸形软降级不抛，register 登记→条目本体可查（验收②）/同键幂等去重/actual 演进=新条目（append-only latest-wins）/torn 行容忍/写失败降级不抛，apply 回执拼装两问小节+矛盾条目本体全量+转正句（验收①②拼装面）/未答也是一条记录（不答不阻塞有实证）/文件级畸形软降级（KI-012 面不新增爆面）/failed 轮不抛不翻 status（不阻塞双态保持）。切块器自证红绿先行（干净/注入/缺席三样本）。与 developer L1 纯函数白盒不同层：本条另守源码锁与回执契约面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（行为子用例），stdlib 源码锁子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260905-01/sc_doc_gate_questions.py", "ro"),

    # ---- t260905-06 workbench "docs" entry (human-readable docs/notes view; the "knowledge base" wording is retired) ----
    ("t260905-06-doc-entry-present",
     "「文档」入口在场且键盘可达（t260905-06，隔离台浏览器走查=工单验收①）：左列项目组头图标枚原位（17 号栅格语言）存在 aria-label/title=「文档」图标、aria-label=「知识库」旧入口不在场（提法退役的入口面，字样清零由场景③专守）；图标可键盘聚焦+Enter 触发中列切视图（用户可感知面=发起 GET /api/wf/docs/tree?scope=docs 且 200 目录加载）+图标进入 active 排他高亮态。复用 lib_fix17 隔离台（临时注册表根+夹具项目；真库 docs/notes=泳道仓根 committed 内容，服务端 DEFAULT_REPO 直读，不向仓根写夹具防污染）。playwright-core 缺失=env_fail 点名（KI-036 家族，闸内无 SKIP）；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-06/sc_doc_entry_present.mjs", "ro"),
    ("t260905-06-doc-read-through",
     "目录→篇→正文真渲染+notes 观察窗+移动窄栏（t260905-06，隔离台浏览器走查=工单验收②⑤与「移动窄栏可用」）：API 契约面（真库）——tree?scope=docs 200 含锚篇目（README.md/terminology.md）且 skipped 拒收可见性字段在场（人读视图完整性可判定）、scope=notes 200 含 notes/README 与 epics/ 篇目、doc?scope=docs&path=terminology.md 200 含「项目术语表」、穿路径（../package.json）fail-closed 非 200 或 empty+reason 且不外泄内容；UI 链路（t260915-10 语义变更留痕：文档页初值起跟随壳层项目，UI 子用例经夹具甲组图标进入=请求带 project=fixa，夹具根=引擎仓根故真库篇目经项目锚出目录——旧稿 UI 子用例靠「无 project= 缺省回落」见真库的形状退役；缺省回落子用例归 t260910-10-docs-ui-mock-v1 T1b 与 t260915-10 场景 T2 子用例一）——目录出真库篇目→点篇正文真渲染（「项目术语表」「测试环境隔离指南」标题文本在场）+围栏代码块 computed font-family 含 mono（代码块等宽）；notes 页签切换后 notes 篇目在场；窄栏子用例=review V1①基线对照口径、容器级落地（壳在窄视口卸载本插件槽=视口级断点不可达，探针实证；宽栏量全局溢出基线→文档视图容器压 360px 触发 @container 单栏流→返回钮往返+再开篇可达→断言不新增全局溢出）。断言锚=真库 committed 稳定篇目（真库即夹具：天然覆盖 frontmatter/中文路径/嵌套形状，零夹具写入）。playwright-core 缺失=env_fail（KI-036 家族）；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260905-06/sc_doc_read_through.mjs", "ro"),
    ("t260905-06-docs-wording-retired",
     "UI 层「知识库」字样清零（t260905-06，静态 grep=工单验收③）：workbench 界面层源码 src/**+构建产物 lib/**（随仓提交、隔离台实际加载面）grep「知识库」全词 0 命中（注释含，命中=用户可见旧提法=产品红）；断言面缺席（目录不在）=env_fail（构建管线异常非产品红）；对照面自证——同一 grep 通道在写集外 knowledge 插件目录命中>0，防「grep 挂了恒 0」假绿。node.ts 宿主半与 knowledge 插件自身不在界面层断言面（写集外存量欠账另账）。实现落地前红属预期（现源码含字样，TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-06/sc_docs_wording_retired.mjs", "ro"),

    # ---- t260905-09: platform self-launched context moved into a fold (ticket 16 only folded its own injection — host-reported 260906) ----
    ("t260905-09-platform-anchor-contract",
     "平台内容锚交付契约冻结（t260905-09，ro 静态面，KI-042 同族防漂移）：平台自启上下文折叠靠「渲染面对平台恒定文本的内容锚」（注入源在宿主二进制，仓内无字符串可对），锚真源模块（platform-context-anchors.ts）↔取证夹具（fixtures 首行=锚固定样本+%%% 尾注取证来源）逐字同步——改锚不回夹具/夹具漂移无人知=折叠件对过时文本匹配静默失明；负向样本排除在真源层在文（中段提及普通消息文本不进锚清单=误折防线）；前缀粘贴声明子用例（粘贴首行恰为在册锚=设计内不可分辨限制有夹具背书，平台 wire 契约 PromptContentPart 无 metadata 字段）；折叠件对锚模块的引用在文（锚定了空气=平台上下文永不折）。与 t260904-07-charter-source-contract intent 级不同层：那条冻结 charter marker 两端同源，本条冻结平台锚↔取证样本↔接线三点。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-09/sc_platform_context_anchor_contract.mjs", "ro"),
    ("t260905-09-platform-context-fold-stacked",
     "平台上下文叠台折叠用户旅程（t260905-09，browser 隔离台 3199 拒 3099，工单「怎么算好」原话可执行化）：夹具把平台启动上下文消息×N+工单台 charter 注入×1 叠进同一会话——16 号验收台只测自己注入子用例、台面无平台叠加=假绿（宿主实报「还是显示了一堆，只折叠了开头一小部分」）。主断言=恰一个小条（不是 charter 一条+平台又一条，「同一折叠件」原话）+全部候选正文收折（含同气泡双锚去重样本）+点小条整组开/收；负向=中段提及普通消息全程可见零误折（普通用户消息绝不折）；孤儿守卫=夹具气泡移除后小条随摘无幽灵、reload 不复活；console 卫生=零 pageerror（外来节点×React 重渲染崩溃在此现形，证据上报归因不静默）。归因三态：锚真源不在=fail（TDD 信号）、源在而 served bundle 无锚样本=na（未重建/未部署，merge 期自动生效）、行为不符=fail 精确点名。charter 注入子用例本身由 t260904-07 journey 守（intent 级不重复，此处只当前置卫兵）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260905-09/sc_platform_context_fold_stacked.mjs", "browser"),  # chain: shared-console writer — in-session platform context stacking

    # ---- t260905-10: engine immunity against three incidents (interpretation injection channel / torn-session quarantine / on-disk identity dependency) ----

    ("t260905-10-host-ruling-injection",
     "blocked 态宿主裁决注入→arbitrate 下轮 prompt 可见（KI-053 端到端，灰盒 L3，docker 舞台+真工单专属 worker）：SANDBAR_AGENT_CMD recorder 桩（spawn 单点全口径覆盖，含 arbitrate 直 spawn 面）把引擎递来的 prompt 原样落账本=mock 端点收到的 messages 等价观测面；桩回执恒缺 verdict= 标记→三次格式纠正 blocked(arbitrate)（引擎既有契约路径）；blocked 态 client op=ruling 注入（只入账不唤醒）+retry_qc 唤醒→arbitrate gen+1 轮 prompt 含裁决文本与裁决人、注入前各轮不带（对照）；全文兜底 meta.host_rulings 与事件历史 log 留痕经 query 可查（{ts,who,note} 形状、ts 留痕）；拒收两态=超大 note intake 闸拒收进 refused 不入账（不进 Temporal 事件历史）+纯空白 note 绕过 client 直发信号层拒收（钉 workflow 侧契约非仅 client 包装）；多条裁决累积全可见且旧→新排序（最新贴着现在）；被测子进程零连生产（审计钩子）。断言面=recorder 账本/快照，不锚 prompt 小节标题文案（实现副本）。实现段落地前红属预期（host_ruling 信号缺席=点名红），arbitrate/merge 期必须绿；与 developer L1（build_stage_prompt 纯函数单测）intent 不同面：本条守 signal→meta→prompt 全链真 Temporal 编排行为",
     "python3 integration/t260905-10/sc_host_ruling_injection.py", "engine"),  # engine: real workflow + ticket-private queue, POLL 60/180 timing legs
    ("t260905-10-torn-session-quarantine",
     "帧好内撕裂会话检疫隔离+同 id 新建走得通（t260905-10 面②，05 号 260906 两次卡死同型，灰盒 L3）：zstd 帧完整但 JSONL record 中截断→spawn 前检疫挪隔离区留档；好帧内非 JSON 行同判；健康对照组=多行合法 JSONL×多帧拼接（真实形态）不检疫（防「见档就隔离」反向事故）且同批健康会话不连坐；同 id 原路径重写合法档再检疫不动（恢复旅程）；挪不动（隔离路径不可建）不抛坏档留原位（既有兜底）；空文件/二进制既有 zstd -t 路径回归；裸空行容忍不判撕裂（合法 JSONL 容忍面，防误隔离）。断言面=文件系统结果，零网络零 docker。实现段落地前红属预期（逐行试析缺席=好帧内撕裂不挪=红），arbitrate/merge 期必须绿；与 developer L1（单函数子用例）intent 不同面：本条守会话档族整批判定与恢复旅程",
     "python3 integration/t260905-10/sc_torn_session_quarantine.py", "ro"),
    ("t260905-10-lane-identity-guard",
     "泳道落盘身份依赖守卫（t260905-10 面③，260906 宿主 ~/.gitconfig 消失三轨 settle 全 FAILED，灰盒 L3）：git 身份全缺→prepare_workspace 开工前 ok=False/failed 红字点名 user.name/user.email（半缺子用例钉死点名精确性，探针 GIT_CONFIG_NOSYSTEM+GLOBAL 夹具防系统级假红）；身份在位复用不受扰；repo 级 config 补救放行（探针锚泳道 worktree=共享主仓 config）；dir 型工作区无 commit 不查；created 路径缺失失败且泳道不落半成品（fail-fast 在 worktree add 之前）；LANE_DEP_SYMLINKS 含 engine/.venv：泳道自动软链解析到主仓、幂等不重复（260825「泳道无消费方」拍板被 260906 19 号闸实测推翻的陪伴断言）；点名断言解析「git 身份缺失（…）」括注为集合（处置句恒提两键名，子串断言吹不了精确性）。实现段落地前红属预期（守卫缺席=缺失子用例照旧放行=红），arbitrate/merge 期必须绿；与 developer L1 intent 不同面：本条守 prepare_workspace 两分支×身份矩阵×deps 软链的回执契约",
     "python3 integration/t260905-10/sc_lane_identity_guard.py", "ro"),
    ("t260907-04-naming-grep-assert",
     "命名清理① grep 断言守卫（t260907-04 验收①，宿主令「名字的清理要搞干净」）：写集（engine+server/tools+integration）内 suyou 旧字面量只许在已声明兼容面——LEGACY 标识行 / naming-compat 显式标记行（目录回落/镜像/场景 fixture 造旧目录）/ README 退役账行 / L1 负断言源码与守卫自身（断言面≠消费面）/ 插件面文件名引用（出界不动册，另一票面）；并断言 README 退役账 ≥7 行在册（防撤了半截，退役必连守卫带账一起动，锚退役语义不锚措辞——KI-051 写作纪律）；扫描器自证红绿。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260907-04/sc_naming_grep_assert.py", "ro"),
    ("t260907-04-env-compat-bridge",
     "SANDBAR_*/SANDBAR_* 环境变量过渡契约（t260907-04 正文①，灰盒 L3 锚 env 契约不锚实现）：仅旧名环境引擎解析到值（存量脚本/文档/用户 shell 不炸）、仅新名生效、冲突新名优先、新名空串回落旧名（falsy 语义不静默改义=畸形输入子用例）、apply_env_compat 桥幂等（import 时序外的显式重跑通路两次调用不改写环境）。与 developer L1（shim 单函数 UT）intent 不同面：本条守子进程级引擎解析行为（import 时序即被测面）。实现段落地前子用例 2/3/5 红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-04/sc_env_compat_bridge.py", "ro"),
    ("t260907-04-lane-dot-dir-sticky",
     "泳道目录 .suyou/→.sandbar/ 过渡契约（t260907-04 正文③「既有在飞泳道不炸」）：纯 .suyou 在飞泳道恒旧名且不造新名目录（粘滞+读侧回落）、全新 base 落 .sandbar（创建侧换新名）、两名并存恒新名（镜像目录不参与解析）、R-1 全链钉=新 base 首写后镜像造出 .suyou 解析仍新名（防权威目录中途翻转、非镜像产物静默缺损——t260907-04 review 实锤缺陷 R-1 的回归钉）、十次解析稳定无隐状态漂移。与 developer L1（resolve 函数 UT）intent 不同面：本条守跨进程解析语义与翻转注入。实现段落地前红属预期，arbitrate/merge 期必须绿",  # naming-compat
     "python3 integration/t260907-04/sc_lane_dot_dir_sticky.py", "ro"),
    ("t260907-04-dispatcher-lock-fallback",
     "总管单例锁改名过渡（t260907-04 server/tools 引用面）：接管写锁/他人持新锁只读不派不续写/过期接管三态 + 旧锁（suyou-dispatcher.lock）TTL 内视为 held（防新旧 dispatcher 实例并行双派——过渡回落半边）+ 旧锁过期接管写新锁且旧锁只读不写不删（只回落不续命）。锁路径常量动态发现替换 temp 副本——不碰真 /tmp 锁（真 dispatcher 可能在跑，写它=干扰生产面）。实现段落地前子用例 4/5 红属预期（旧锁回落未落地），arbitrate/merge 期必须绿",  # naming-compat
     "python3 integration/t260907-04/sc_dispatcher_lock_fallback.py", "ro"),
    ("t260907-04-queue-dual-registration",
     "worker 队列注册契约（t260907-04 验收②，260908 终切翻面——空库重建窗口零兼容负担）：缺省启动单名 poll 新队列 sandbar、suyou-poc 不双 poll（撤双 poll 的负向守卫，复活即红）；显式列表 env 声明的队列名照单全收；显式旧名单值 env 仍服务旧前缀队列（显式声明面≠默认推导面）。docker 舞台 stage_docker 单点（docker 缺席/镜像缺席/起台不健康=ENV_FAIL 点名缺什么），SDK 走 poc venv。子用例1 红=双 poll 复活",  # naming-compat
     "python3 integration/t260907-04/sc_queue_dual_registration.py", "engine"),  # engine: 场景内起 docker 台+temporal 走廊，宽度1道（t260910-05 仲裁：宽池翻红、隔离 3/3 绿）
    ("t260907-04-schedule-legacy-retire",
     "dispatcher-scan schedule 服务端持久标识改名退役（t260907-04）：Temporal schedule 改 ID 旧对象不会自己消失——种子旧 ID 在台→跑引擎创建走廊（仓内唯一在树创建点 demo_schedule.demo_schedule）后新 ID 在旧 ID 亡（防新旧双份调度——review gen0 缺口2）→再跑一次幂等（旧 ID 仍亡、不炸）。docker 舞台 stage_docker 单点，缺台/缺 SDK=ENV_FAIL。实现段落地前子用例 2/3 红属预期（删旧未接线），arbitrate/merge 期必须绿",
     "python3 integration/t260907-04/sc_schedule_legacy_retire.py"),
    ("t260907-05-naming-residue-fulltext",
     "命名迁移②收口：旧命名 token 全量残留清点（t260907-05 验收①独立机器重演，灰盒 L3）：七 token（六插件包名 suyou 前缀族＋tools 文件名旧形）在 server/+integration/ 全后缀零残留（无 include 白名单——方案 v1 白名单漏 tsx/py/cjs 的教训收编为本条设计依据；豁免列名仅历史验收记录 t260903-12/acceptance-walkthrough-gen0.md 与本票守卫场景族自身——针脚字面量写在断言里非产品面，活文档不豁免）；docs/ 命中封口在已声明遗留票清单内（工单工作流台设计/知识库设计/docs README/build_index.py——本票不改 docs 但清单外新命中=替换面外溢即红）；正名在位（六插件 package.json name 全 sandbar-*、五份 lock 双处 name 同步）；不动面原样在位（/sandbar-admin/ 前缀、project-registry.ts、dsh-profile-suyou 包名——机械替换「顺手多改」的对抗子用例，doc-guard G6 先例钉现状语义，后续票落地随其语义同步改）。与 sc_profile_farm_sandbar_links intent 不同面：本条守文本面收口，彼条守装载链结构一致性。Hermetic 纯文件读秒级；实现段落地前红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-05/sc_naming_residue_fulltext.py", "ro"),
    ("t260907-05-profile-farm-sandbar-links",
     "profile 软链农场重指一致性（t260907-05 验收③＋正文③④，灰盒 L3）：装载链每环同指新名——cordis.patch.yml id/name（装载声明）==node_modules 裸包名解析锚（软链名）==插件 package.json name（包真源），任一环留旧名=宿主重启边界上插件消失/重复/import 炸给用户看；tools 文件名旧形→新形四环同步（真身在位+内部注册名+两 profile 软链 realpath 命中+三处 import）；两 profile 农场五链（sandbar-{admin-ui,workbench,knowledge,providers,temporal-tools}）realpath 指对实际目录、旧 suyou-* 链零残留；headless/cordis.patch.yml 必须仍是指向 profile 真身的软链（被换独立文件=两 profile 声明可静默漂移，「两 profile 都改」机制保障被掏空）。对抗面=链指错层/拼写差一字/漏 headless/漏删旧链/mv 漏改 import——逐环独立断言不信任单点自检。与 developer L1（单插件行为）与 sc_naming_residue_fulltext（文本收口）intent 不同面：本条守软链结构三方一致。Hermetic 纯文件系统读秒级；实现段落地前（农场未建/软链未重建）红属预期，arbitrate/merge 期必须绿",
     "python3 integration/t260907-05/sc_profile_farm_sandbar_links.py", "ro"),
    ("t260907-05-route-renamed-serves",
     "工单台路由前缀迁移契约（t260907-05 正文②＋「怎么算好：工单台面板/路由全通」的机器化，灰盒 L3）：黑盒 import workbench/node.ts＋mock ctx（webServer.register 收集）自起 127.0.0.1 ephemeral server 按 exact/prefix 语义分发——新前缀真 handler 应答（/sandbar-workbench/api/wf/temporal-health→200，零引擎 spawn，生产 Temporal 只读红线允许面）；旧前缀死透（旧前缀通配→404，非 301/308/410/200——「直接换不留旧」策略的机器化）；注册面收口（全部路由注册 path 零旧前缀残留、全新前缀，含 src/host 常量挂载的 session-charter 路由——KI-042 同源防漂移面）；bundle 双产物（lib/client.js+cjs）含新前缀零旧前缀（src 改了产物没重建=浏览器半仍打旧名）。3099 全程零接触；不 fetch 新 tickets（spawn 真 admin CLI 面，业务旅程归既有场景族与隔离台）。与 t260903-13/sc_workbench_bundle_loads（bundle 可加载）intent 不同面：加载成功≠名字改对。实现段已迁 node.ts/import/主文件——T1~T5 应绿，bundle 未随票重建则 T5 红（该红正是本条存在意义）",
     "node integration/t260907-05/sc_workbench_route_renamed_serves.mjs", "ro"),

    # ---- t260907-06: multi-repo project lane carrying sub-repos (ticket B: one ticket, several worktrees cohabiting one lane) ----

    ("t260907-06-multirepo-journey",
     "多仓票全链旅程（t260907-06 验收①前半+复用幂等，灰盒 L2/L3，用户手册多 repo 模型=项目父目录作根、多树同居一 lane）：写集路径落两子仓→每仓各得路径子集（最近 .git 祖先归属，不串仓不丢路径）、单仓口径透传；lane 容器（<项目根>/.lane/<泳道>，普通目录不入仓）下每仓一棵树且=所属子仓已注册 worktree（git worktree list 绝对路径可验）、基线文件随仓；分支命名 lane/<泳道>-<仓相对路径压平> 逐仓独立；prepare 二次两树 reused（树内标记文件幸存=未重建、分支引用不漂=转移接力 M4 面）；settle 各归其仓（两树改动各落各自树分支、落账不含他仓文件=错仓落账红线）。单仓零回归不另起用例——存量 integration 场景族即单仓回归面（intent 相同不重复造）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（prepare/settle 行为子用例），stdlib 归属契约子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260907-06/sc_t260907_06_multirepo_journey.py", "ro"),
    ("t260907-06-multirepo-merge-gate",
     "合并闸逐树判定+merge 逐仓收口+重入幂等（t260907-06 验收①后半，灰盒 L2/L3）：白名单门重基两向——合法分仓改动整体绿（重基漏剥前缀=假红）、树内写集外注入整体红且 detail 点名（重基不放空=假绿防线）；merge 逐仓收口两仓 main 各恰多一个 squash 提交（一单一提交逐仓独立）、内容各归所属仓（错仓落账红线）；重入幂等（Temporal 重试面）——一仓冲突整体 failed、已成功仓已落账、冲突仓不落账，解堵重试后已成功仓提交数不变（不重复落账）、失败仓补齐（不漏账）、整体 ok。与场景①旅程/场景③拒收面 intent 分界；白名单工具语义另有专测族，本条只守多仓重基后调用侧组装两向行为。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（本场全靠真链路无 stdlib 替代子用例）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260907-06/sc_t260907_06_multirepo_merge_gate.py", "ro"),
    ("t260907-06-multirepo-failclosed",
     "多仓 fail-closed 注入面（t260907-06，灰盒 L2/L3，畸形/边界/异常路径）：路径逃逸项目根（../）拒收点名不给静默归仓；集合外嵌套仓（仓中仓）路径创建即拒收且红字点名嵌套仓（不静默归外层仓=错仓落账前奏）；合法路径对照子用例不误伤（拒收不扩大化）；删仓后 prepare→failed 回执点名缺失仓、树原样幸存不静默重建（meta.repo_worktrees 唯一真源一致性校验面，真源漂移=交人不是自愈）；树位置被来历不明普通目录占位→failed 不覆盖不删除（与现行单仓「目录已在但非本仓 worktree→人工处置」同语义逐树保住，防覆盖 agent 工作现场）。写集条目畸形形态属建票写集契约既有面（存量已守，intent 重复不另起）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（prepare 异常路径子用例），stdlib 拒收子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260907-06/sc_t260907_06_multirepo_failclosed.py", "ro"),
    ("t260907-12-mixed-root-multirepo",
     "根亦 git 仓的混合多仓项目全链（t260907-12，灰盒 L2/L3，dengzhufpv 形态=项目根知识库 git 仓+repos/* 子仓并存）：仓集合=[根]+一层子仓（repos_under 短路退位）；写集归属三态——根仓路径票归根树（repo 相对路径=空）、子仓路径票归子仓（最长前缀）、双命中票两树同居一 lane 不串不丢；根树=泳道容器本身（prepare created、分支 lane/<泳道>-root、基线随根仓、清单落盘含 repo=\"\" 条目）；workflow 闸对 repo=\"\" 合法条目放行、缺 branch/分支碰撞真畸形照旧拒（fail-closed 不弱化）；复用幂等（prepare 二次两树 reused、标记幸存、引用不漂=M4 转移接力）；settle 逐树各归其仓（根树落账只含根仓写集文件、清单 repo=\"\" 条目读侧不断链=四消费方间接覆盖）、根仓 status 不受子仓树/清单污染（advisory④ .gitignore 兜底）；单仓零变化对照子用例（根 .git 无子仓：derive 不激活、prepare 走旧单仓路径无清单、谓词 False）；真嵌套仓（已登记仓内部套仓）路径拒收点名；引擎自留 .lane/<id> 泳道 worktree 不入仓集合（单仓零变化红线）。与 t260907-06 三场景 intent 分界：彼=父目录作根形态（根无 .git），本=根亦 git 仓混合形态；通用路径逃逸/写集条目畸形形态属既有契约面不另起。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（prepare/settle 行为子用例），stdlib 仓集合/归属/闸契约子用例照跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260912/sc_t260912_mixed_root.py", "ro"),
    ("t260910-03-formal-entry-fuses",
     "正规入口多仓票全链+双保险丝（t260910-03，dengzhufpv 260910 缺陷回归面，灰盒 L2/L3）：正规入口创建链补传——ticket.py 同款 derive（repo_write_set=写集）多仓项目产出双仓 repo_worktrees（复现形态修复后必须双仓）、明细经 ticket-start 二跳 dict workspace 转发不丢（缺陷根因=此通道被堵）、漏传=单仓明细缺失（旧病灶形状对照子用例）、单仓项目透传零回归不激活；保险丝A（开票拒收）——ticket-start 显式 worktree+成员仓写集创建即拒收且红字点名条目（连接前拒收零 Temporal 依赖；只锚拒+点名不锚措辞）、对照子用例不误伤（纯根仓写集放行、多仓写集合法派生放行=显式 worktree 不是绕闸通道）；逐仓物化落成硬断言——prepare_workspace 双仓树均=所属仓已注册 worktree（git worktree list 绝对路径可验）+清单落盘两仓条目；保险丝B（合并红灯，混合形态=缺陷现场）——清单缺失（_lane_scopes 单仓回落=缺陷形态）×成员仓写集：merge_check 红灯且物化检查项红点名缺失仓、非冲突类（conflict=False 不进自动消解回路，KI-047 同族防线）、merge 同源保险丝 ok=False 不落账（成员仓 main 零新提交、泳道保留交人工）、物化齐全对照子用例同检查项绿（不误伤）；隔离台持久化契约（docker 台，真建票只发生在一次性 namespace 跑完即拆）——正规入口 ticket.py create 真建票与裸入口 client.py ticket-start（无显式 worktree，勿回归红线）的 Temporal payload TicketInput.repo_worktrees 均含双仓（probe_wf_input 读起始事件 input=对外数据契约），create 返回体为辅证。与 t260907-06/-12/-07 intent 分界：彼守多仓泳道本体/混合形态归属/epic 锚定，本守「正规入口补传+双保险丝+裸入口不回归」缺陷回归面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=ENV_FAIL 点名（行为子用例），stdlib 形状子用例照跑；docker/隔离台库缺席=ENV_FAIL 点名（台面子用例）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260910-03/sc_t260910_03_formal_entry_fuses.py", "engine"),
    ("t260910-08-lane-materialization",
     "真开票后泳道磁盘逐仓物化终态（t260910-08，dengzhufpv 形态=根仓+子仓写集，灰盒 L3，工单验收第 1 条的仪器）：正规入口 ticket.py create 真开票→真专属 worker 跑 DevLaneWorkflow→prepare_workspace 真建泳道→磁盘四件套——逐成员仓工作区目录在位（repo=\"\" 根树=泳道容器本身是根仓已注册 worktree）、分支名 lane/<票>-<seg>（根树=-root）、清单（落点＝shared.multi_manifest_path 解析位）repo/name/branch 逐条与明细一致、meta.repo_worktrees 非空（ticket show 读面=取证同面，此前恒 null 误导诊断）；Temporal 起始事件 payload 明细双仓（对外数据契约）；单仓对照同链零回归（workspace_prep=created、无清单、meta 明细空）；畸形明细两层互不冒充——类型毁形 start 受理但 worker 解码面拒收（实证注记：本仓 temporalio type-hints 校验在 decode 侧，编码面不设防；t260910-13 同款 Failed converting 签名=workflow 代码不执行、零落仓、payload 原样过线）、语义毁形（codec 可过闸必拒：条目缺 name）进 blocked 可读拒收且不落任何泳道形态（不崩 _init、绝不静默单仓）；KI-067 设计进去（create 返回体只作辅证，真值锚磁盘/Temporal 侧效果，异常/空输出/拒收回执=红灯点名）。与 t260910-03/-06/-12 intent 分界：彼等复刻 derive/直调 prepare 均不经过 dev_lane._init 第二跳（KI-063 同构盲区=t260910-07 真机单仓实证），本场景唯一守 TicketInput→_init→meta→WorkspacePrep→activity 全跳真码+磁盘终态。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/隔离台库/temporalio 缺席=ENV_FAIL exit 2（真链子用例无 stdlib 替代）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260910-08/sc_t260910_08_lane_materialization.py", "engine"),
    ("t260911-04-multirepo-fullchain-landing",
     "全链多仓旅程守卫（t260911-04，补 KI-071 传递断链的最后一跳「merge→成员仓 main 落仓」，灰盒 L3）：正规入口 ticket.py create 真开票→真专属 worker 跑 DevLaneWorkflow（桩脑自动过段零模型调用）→merge 人审签字面驱动（不旁路 workflow、零 activity 直调）→逐仓 squash 落 main 终态+泳道拆除零残留——断言全落磁盘/git 终态（testing-guide 260910 节）：成员仓 repo_a main 恰多一个该票 squash 提交（rev-list 计数=基线+1、lane/* 分支已删）、内容正确且不串仓（repo_a/src/a.py 票内内容在 main、repo_b 零新提交）、根仓 main 恰+1 且 docs/root.md 落位、worktree/分支/目录三清零残留、ticket show 非 blocked（辅证）；反向子用例=merge 人审挂起窗删泳道逐仓清单（落点＝引擎真写点 shared.multi_manifest_path；夹具级注入=缺明细形态，不改产品，注入前置带在场/已删双断言）→ 保险丝B 红灯咬合：workflow blocked 且公开读面点名「未逐仓物化/保险丝B」、三仓 main 提交数全部不变（绝不静默单仓收口）。intent 三维分界：与 t260907-06① journey 差在链形态（全链 vs 直调 activity）与落点（main vs 分支）、与② merge_gate 差在零 activity 直调（彼=KI-063 同族）、与③ failclosed 差在注入时点（merge 人审窗 vs prepare 时点）、与 t260910-08 差在终点（彼止步泳道磁盘物化）；畸形明细两层互不冒充 intent 归 t260910-08 不带。KI-067 辅证纪律（create/show 输出只作辅证，真值锚磁盘/git）、worker holder+finally 全终态回收（TERM 20s→kill 兜底计红）、env_for 剥 SANDBAR_* 防 CWD/env 泄染、两子用例共台（900s 预算）。docker/隔离台/temporalio 缺席=ENV_FAIL exit 2（真链子用例无 stdlib 替代）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260911-04/sc_t260911_04_multirepo_fullchain_landing.py", "engine"),
    ("t260913-05-teardown-scope-contract",
     "多仓拆道逐仓化的回执契约面（t260913-05，灰盒 L2，真 git 夹具+直调 teardown activity，零 docker 零 Temporal，秒级）：成员仓 worktree 清不掉（真实 git 态注入=worktree lock，非 monkeypatch）→ 回执恒 ok=True 且**逐仓点名该仓**（不得笼统一条、不得静默成功），非注入仓照清（一个仓清不掉不拖停别的仓）、注入仓残留在场（负锁非空转）；成员仓目录整仓不在盘上 → 逐仓点名、不抛 FileNotFoundError、不把可回收残留升级成卡票（_git 裸调 cwd 缺失会抛，review 实测）；三态取源=盘上清单镜像优先（与 merge 同源；两源分歧时跟盘上清单，防两套判定漂移）→ 清单缺失时用 workflow 递来的成员仓明细救源逐仓清干净；外部输入畸形/损坏（清单坏 JSON、明细缺 branch）fail-closed：ok=False+点名+**零动作**（先校验后动手，绝不在错仓上静默收口）；单仓形态（无清单）回执零告警+泳道三清（旧语义面）；幂等重试第二次调用不抛异常。intent 分界：与 t260911-04-multirepo-fullchain-landing（本票回归锚）差在成功/失败路径与层（彼真链全链守成功路径零残留；本条直调 activity 守失败路径回执文案与取源契约）；与 t260907-06（merge 门/直调 journey）零 merge 面；与 t260910-08（止步磁盘物化）无关。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；引擎 venv/temporalio 缺席=ENV_FAIL exit 2 点名（直调 activity 无 stdlib 替代）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260913-05/sc_t260913_05_teardown_scope_contract.py", "ro"),
    ("t260913-05-teardown-residue-visible",
     "多仓拆道清理失败的残留可见性（t260913-05，灰盒 L3，真 docker 隔离台+真 worker 全链）：正规入口开票→真专属 worker 跑 DevLaneWorkflow（桩脑零模型）→merge 人审挂起窗内对成员仓 repo_a 的泳道工作树 `git worktree lock`（真实 git 态注入：单次 remove --force 必失败且不删目录，非 monkeypatch 实现内部）→签字→merge 逐仓落账→归档→拆道：断言**公开读面**（ticket show 的 log 行「泳道拆除告警」）出现该行且**逐仓点名 repo_a**（验收 C：残留不得静默、不再笼统一条）、点名段带失败指示；workflow 仍走到 closed（清理失败不阻断收口的既有取舍）；一个仓清不掉不拖停其它仓（根仓三清：分支已删+注册已清+容器目录不存在）；注入仓残留在场（负锁非空转）；不串仓（repo_b main 计数不变）；同源判定组合证据（验收 D）：merge 逐仓落账的仓集合（根+repo_a main 各 +1）与拆道逐仓点名的仓集合一致。intent 分界：与 t260911-04-multirepo-fullchain-landing（本票回归锚）断言面不重叠——彼守成功路径逐仓零残留，本条故意注入一个清不掉的成员仓守失败路径可见性与逐仓粒度；与 t260913-05-teardown-scope-contract 差在层与面——彼守回执字段/取源契约（直调、秒级），本条守「回执→workflow log 行→收口终态」composition（KI-046/KI-050/KI-071/KI-076 家族：测试在场≠测试生效，故真链必跑一次）。worker holder+finally 全终态回收（TERM 20s→kill 兜底计红）、注入 finally 回收（unlock）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/隔离台/temporalio 缺席=ENV_FAIL exit 2（真链无 stdlib 替代子用例）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260913-05/sc_t260913_05_teardown_residue_visible.py", "engine"),


    # ---- t260916-20: 嵌套仓守卫四道闸（泳道内从零建成员仓的静默丢失防复发） ----
    ("t260916-20-nested-repo-fullchain",
     "泳道内从零建成员仓的四道守卫（t260916-20，nusuyou t260916-08 实案=600 文件静默丢失的防复发面，灰盒 L2，真 git 夹具+直调 activity，零 docker 零 Temporal，秒级）：主 settle 双形态拒绝——0 提交嵌套仓（untracked 目录折叠×.git 在场，防被 add -A 吞成普通文件错形入库）与暂存区 gitlink(160000)（防 squash 无处可搬）→ fail-closed 拒绝代落盘、人话点名（内嵌 path_gate_reason=gitlink_nested_repo 机器键+结构化 refusal）、现场保留（不 commit 不 reset 不删除）、重试同拒（幂等红灯）；冲突消解旁路站点（MERGE_HEAD 在场=主 settle 整体跳过时的唯一 settle 通道）同拒且 MERGE_HEAD 原样（R2 覆盖洞回归形态）；merge_check 红灯点名 gitlink（reason_code=gitlink_present）且 conflict=False（blocked 交人工不进自动消解回路，KI-047 位置契约）、位次落 checks[:-1]；squash 前置红灯 failed(gitlink_present) 主树未动（merge --squash 前判 160000）；拆道守卫——teardown 前扫出未注册嵌套仓即 blocked 点名、一物不拆、对象库完好（git -C 嵌套仓 rev-parse HEAD 前后一致）、守卫自身 IO 故障=同样 failed 点名（绝不静默放拆）；内联清理（defer_teardown=False 老票唯一拆道通道）落账后停拆、泳道保留=对象库可抢救；零回归用例=无嵌套仓的干净泳道 settle 照常代落盘、拆道照旧三清。intent 分界：与 t260911-04-multirepo-fullchain-landing（全链 L3 回归锚）差在成功/失败路径与层（彼真链全链守成功路径零残留；本条守失败路径四道闸行为）；与 t260913-05-teardown-scope-contract 差在守卫对象（彼守多仓拆道回执契约与三态取源；本条守拆道前嵌套仓扫描，单仓形态即可触发=事故现场形态）；桩级真值/畸形输入面归 UT server/engine/tests/test_t26091620_nested_repo_guards.py 不带。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；引擎 venv/temporalio 缺席=ENV_FAIL exit 2 点名（直调 activity 无 stdlib 替代）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260916-20/sc_t260916_20_nested_repo_fullchain.py", "ro"),


    # ---- t260910-11: 巡检校准五事（改名去face / 扫描误报校准 / 测试子用例隔离红线 / 票面可查询） ----
    ("t260910-11-decl-v2-rename",
     "声明 v2 演进契约（t260910-11 工单①②，灰盒 L2，纯离线）：交付 inspection.yaml 解析为新名 integration-tests/docs-sync 且 decl 回执零 face 键、yaml 文本零 face 行；含 face: 的旧形态声明被解析面拒收且报错点名 face 字段（旧声明拒收点名=工单验收原文，报错精确纪律）；兼容红线半边（InspectionPeriodicInput.face 默认值防历史重放解码报错）是数据类契约归 developer L1 重放锁，本条不复写。与 t260905-03-decl-gate intent 分工：彼守声明门「谁能跑/谁被拒」的门行为（畸形/未接线/占位/未知实例），本守字段表翻转后新旧声明的命运=schema 演进面。纯 stdlib 闸内即验；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260910-11/sc_inspection_decl_v2_rename.py", "ro"),
    ("t260910-11-temporal-isolation-guard",
     "测试子用例隔离生产 Temporal 红线守卫（t260910-11 工单④，「测试写生产 Temporal」事故回归，灰盒 L2/L3）：fail-closed 行为子用例——ambient 目标=生产 7233 时 lib 注入路径拒跑且报错点名生产台（离线 decl 探针零网络）；静态子用例——lib_inspection 子进程 env 构造钉 127.0.0.1:17233+sandbar-test 且 SANDBAR_TARGET_HOST 注入点覆盖 worker/trigger 双 spawn 路径；隔离台真跑子用例——私有队列自供给 worker 开票成功、票号带进程戳；退出自清子用例——with 退出后本进程开的票非 RUNNING 或查询点名不存在（僵尸票事故形态防线）；生产零写入条件子用例——7233 可达且 temporal CLI 在位时全程前后只读计数零新增（不可得按 N/A 折算，动态对照权威面在 implement 验收证据）。场景自身一切 spawn 显式钉隔离台（pre-implement 状态也绝不写生产）。与 t260905-03-period-journey intent 分工：彼守巡检全链旅程质量，本守测试子用例的平台归属红线。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台缺席=ENV_FAIL 点名（离线子用例已验部分如实陈述）",
     "python3 integration/t260910-11/sc_inspection_temporal_isolation.py", "exclusive"),
    ("t260910-11-ticket-query-face",
     "巡检票只读查询面（t260910-11 工单⑤，「巡检票无查询面」事故回归，灰盒 L2/L3，隔离台真票）：运维通道 CLI 按实例+期次查到存活票、回执与工单详情同构（id/stage/stage_state/status/face/timeline，findings 出摘要防刷屏）；查不存在精确点名实例/票号（不许笼统连不上/transient 话术把诊断引向网络方向——KI-029 同族反面教训）。与 t260905-03-period-journey 分工：彼守旅程全链（含 sign 收口），本守查询面契约本身；工单台（workbench 插件）侧查询是本票明确的降级口径（写集外留专门票），本条只锁运维通道。场景自身一切 spawn 显式钉隔离台 17233/sandbar-test。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/temporalio 缺席=ENV_FAIL 点名",
     "python3 integration/t260910-11/sc_inspection_ticket_query.py", "exclusive"),
    ("t260911-02-trigger-kinds",
     "触发 kind 接线（every-n-tickets/race-first）隔离台全链（t260911-02 工单①③，灰盒 L2/L3）：声明启用计数实例后夹具归档票计数达阈值即起票（期号 YYYYMMDD-<bucket> 形状）、未达阈值窗口内不起票；race-first 计数先到起票且 watcher 只读观测面回执基线/下次 cron 时点（cron 子用例设不可达时点 2/29——cron 触发侧的双侧复位真值表归 developer L1，L3 只锁确定性可判面，intent 内声明 scoping）；同桶重复触发 deduped（票号幂等）+cron 期号保持纯 8 位不受计数期扩展污染+重复触发 deduped 到同票（一票一期/心跳语义不变，工单验收 e）+同日 cron 期与计数期并存合法（R2）；watcher terminate→schedule-up 复活→再达阈值仍起票（KI-049「死机制无人知」回归注入子用例）；未知 kind 与启用计数实例缺 source/project_key 均显式报错点名（fail-closed 不随接线扩大松动，离线子用例）；巡检票查询面对计数期票可读（工单验收 f）。五子用例守卫承 t260910-11 场景③逐子用例（方案 R1 乙清单）：ambient=生产 7233 探针子进程拒跑点名（行为子用例）、spawn_env 单点 env 白名单（静态子用例，lib 单点复用不重复守）、夹具票号/项目键进程戳+退出自清（行为子用例）、生产台零写入对照（系统状态条件子用例缺席 N/A 不假绿）、畸形夹具注入子用例（归档目录容错）。与 t260905-03-period-journey 分工：彼守 cron 触发的巡检旅程质量，本守新触发 kind 的接线行为与复活契约；与 t260910-11-temporal-isolation-guard 分工：彼守隔离红线机制本身，本守业务行为（红线手法复用不重复守）。场景自身一切 spawn 经 lib.spawn_env 钉隔离台 17233；计数真源=SANDBAR_PROJECTS_DIR 临时根+archive.json 归档标记（与 project remove 归档判定锚同源）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/temporalio 缺席=ENV_FAIL 点名（离线子用例已验部分如实陈述）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260911-02/sc_inspection_trigger_kinds.py", "exclusive"),
    ("t260911-02-doc-face",
     "docs-sync 第二实例：doc 面扫描器契约+真跑一轮出报告（t260911-02 工单②，灰盒 L2/L3）：离线 CLI 子用例（同族 stdout 单行 JSON 契约）——脏夹具树必报六类注入（S8 缺登记/幽灵条目双向、S9 无 frontmatter/缺字段/坏 YAML 逐篇降级点名、S10 断链与 ../ 越界引用）且 doc-exempt 豁免篇不报（误报洪泛闸换形态）、静态面只 med 不判 high（方案 R1 甲-9）、全绿树零发现+heartbeat=true（反例不报+心跳）、index.json 坏 JSON 降级点名不崩不静默空转（KI-030 族三态禁静默）、真仓自扫只验发现六键结构不验内容（方案 R5 防 rot——真仓已知 2 条 frontmatter 发现走人审报单，不作场景判据）；在线 L3 全链子用例（工单验收 c）——docs-sync 实例 trigger→flow→scan(face=doc)→落账报告含注入命中+doc-lifecycle 依赖占位显式标注（不得静默空转）+人审 sign 收口子用例（收口未及让位：收口链由 t260905-03 journey 守，落账报告为验收 c 权威面）。与 t260905-03-scan-contract 分工：彼守测试面扫描器横向契约，本守 doc 面新扫描器同族契约与面分派；与 t260910-11-decl-v2-rename 分工：彼守字段表演进，本守 docs-sync 实例行为本身。S10 锚定=KI-051 族守卫锚点 doc 版常驻化（工单原文）。场景自身一切 spawn 显式钉隔离台 17233，夹具树临时目录退出即拆。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/temporalio 缺席=ENV_FAIL 点名（离线子用例已验部分如实陈述）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260911-02/sc_inspection_doc_face.py", "exclusive"),
    # ---- t260913-02: inspection's own workflow (own lane + full-suite stage) + daily schedule + dead-man ----
    ("t260913-02-lane-lifecycle",
     "巡检自有泳道生命周期契约（t260913-02 验收 A 的机械面，灰盒 L2 真 git 仓零 Temporal 零 docker）：命名空间——泳道落 <repo>/.lane/inspection-<实例>-<期>、分支 inspection/<实例>/<期>，同场真建开发泳道邻居对照，两者命名空间零交集；基点——prepare_workspace 用调用方给定 sha 落盘且 worktree HEAD==该 sha（非 HEAD 漂移可判别），既有泳道在场时恒 reused 且基点不移动（stale 残留把当期套件跑在旧代码上=静默假绿，故先清后搭是硬要求）；水位清扫——keep_period=当期时清「早于水位」的残留、水位之后（并发在跑的另一期）让行、别的巡检实例与开发泳道一律不碰，remove_period 定向模式只清指定期（跨仓泳道兜底），畸形 instance fail-closed 不误删；拆除——teardown_lane 零残留且两连拆幂等（不存在=成功不炸）；主树零改动（tracked 内容逐字节一致 + 工作区干净 + HEAD 未动 + worktree 注册表零巡检残留）；畸形实例 id/期号全拒。与 t260905-03 巡检票①场景分工：彼守扫描面与旅程，本条守本票新增的泳道机械面；与 t260913-02-suite-journey 不同层：本条离线直调活动（真 git 终态），彼走真 workflow 编排。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git 缺席=ENV_FAIL 点名",
     "python3 integration/t260913-02/sc_inspection_lane_lifecycle.py", "ro"),
    ("t260913-02-suite-journey",
     "巡检自有阶段机全链 + 套件证据进票面（t260913-02 验收 A/B/E 的真链路面，灰盒 L3：真 17233 隔离台 + 私有队列自供给 worker + 夹具仓快套件（两条夹具场景+恒红 integration.cmd；编排与票面证据才是本条对象；真规模/真全集的证据面见报告「测试资产变更审查」——不再套一条场景在闸内重跑全集（递归代价实锤 900s 超时，见该节））：阶段机 setup → scan → suite → report → close 且无 dev-lane 段（plan/implement/arbitrate/merge 零在场）；套件在巡检命名空间 worktree 里跑、票面给 worktree 与基点 sha（与夹具 main HEAD 交叉验证）；票面套件摘要 ran/passed/failed/逐场景 cases/墙钟/回执路径齐备且回执文件真在盘（红项点得出是哪几条）；红项=high 发现 + 建议溯源本巡检票号（source_inspection）；心跳不被红污染；人门真拦（未签停在 awaiting-human）且泳道在人门前已拆干净（人审不依赖活泳道）；收口落账保留套件证据；泳道搭不起来（非 git 仓）→ 票面 blocked 且落账带失败原因与时间线（漏跑不静默的 in-workflow 面）；全程夹具主树零改动。与 t260905-03-period-journey 分工：彼守无泳道的扫描/人门两拍，本条只增泳道+套件两阶段与其票面证据；与 t260910-11-ticket-query 分工：彼守查询面契约。一切 spawn 经 lib_inspection.spawn_env 钉隔离台；登记 exclusive（自供给 worker + 真票写共享测试台）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/temporalio 缺席=ENV_FAIL 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260913-02/sc_inspection_suite_journey.py", "exclusive"),
    ("t260913-02-schedule-daily-deadman",
     "每日调度接真 + 漏跑可见（dead-man）（t260913-02 验收 C/D，灰盒 L2/L3）：声明面＝integration-tests 的 cron 每天一次"
     "（minute/hour 固定、日/月/周全通配）且 suite=full，其余实例 cadence 未被顺手改动（零回归）；正规入口 schedule-up 在隔离台"
     "**真建成 Temporal Schedule**（回执 next_action_times 落在次日窗内、cron 原样）且场景自清（不遗留常驻定时器）；生产面现状只读核查"
     "＝「Temporal 上能查到该实例 schedule 且 NextRunTime 为次日」（查无该 schedule 即红——声明了没建正是工单原文的现状）；漏跑告警两面"
     "＝deadman 单行 JSON：缺日→missed 精确列出期号、alarmed=true、退出码 1、findings 出 high 且 suggest=false（漏跑不是代码缺陷），"
     "台账齐→零误报退出码 0，多期漏跑全列不截断、异实例台账不误计、畸形 json 点名不崩、当日不算漏；套件告警硬映射＝红项逐条 high（可点名）、"
     "ran=0 亦 high（红线「不得删减场景换跑通」的机械面）、环境红 med 且不生成修码建议、心跳只在套件全绿时成立。与 t260905-03-decl-gate"
     "（触发门行为：谁能跑/谁被拒）intent 不同面不重测；与 t260911-02-trigger-kinds（计数 kind watcher 拉活）不同面。实现段落地前红属预期",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260913-02/sc_inspection_schedule_daily.py"),

    ("t260913-02-integ-run-singleflight",
     "同泳道集成跑单飞锁契约（t260913-02 arbitrate gen10 根因面，灰盒 L2 纯 CLI+stdlib 秒级）："
     "两次并发全轮共用泳道级舞台工程名会互相拆台——拆在飞的台（中段连接被拒）、旧 ID 串台（夹具残留"
     "报成产品红）、console 族瞬时环境红；实况 260914 21:08-21:10 两个 199 条全轮重叠 85s，闸录得"
     "1 败 + 17 环境红。子用例＝无锁发车照跑（不误伤）／有锁发车退出码 2 且点名持有者（pid+锁档+起租时间，"
     "零场景开跑、无计数行不谎报）／显式 knob SANDBAR_INTEG_ALLOW_CONCURRENT=1 放行且留痕／只读资产"
     "查询面 --print-pool-assets 不占锁（闸并行查资产面不被挡）。设备=SANDBAR_INTEG_RUN_LOCK_PATH 临时"
     "锁档（不碰泳道真锁档）+「排除全部在册池」把全轮收成零条目（ran=0 与在册 0 一致、rc=0，秒级零 docker）。"
     "与 t260904-12-executor-three-state（三态计数/汇总自证）intent 不同面：彼守计数语义，本条守并发发车门。"
     "实现落地前红属预期（锁缺席=子用例2 照跑=红），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260913-02/sc_integ_run_singleflight.py", "ro"),

    ("t260910-06-ki067-entry-audit",
     "KI-067 工单操作入口收口（t260910-06，260910 两实证缺陷回归面，灰盒 L2/L3）：静默失败根治——正规入口 ticket.py 任何 op 失败=非零退出+stdout 结构化 {ok:false,error}（绝不空输出：260910 实证病灶=空输出+退出 0+admin.log 无痕；A 段 stdlib 直调现形状，create 缺参/无参/畸形 argsJSON/-h 全非零）；无差别自审计——client.py 每次调用无论来源记 admin.log（含未知子命令拒收/连接失败/-h，拒收不记=盲区），source 记 env SANDBAR_CLIENT_ENTRY 原值（缺省 bare；审计落 SANDBAR_ADMIN_LOG 覆盖 tmp，不污染真账）；回执嵌提醒——裸入口回执（含失败回执）附 entry_hint、env 精确等值 'ticket' 才安静、任意值（'ticket.py'）不获静默且 source 记原值（claimed-source 非身份鉴别，宿主 260910 裁非安全语义）、参数面注入 source 字段不污染标记；双行审计契约——ticket.py 直调一次=admin.log 两行（ticket.py-direct+ticket）call_id 一致（有意双行非重复记 bug，关联键=SANDBAR_CLIENT_CALL_ID）；sign/retry_qc 包进正规入口（who 调用方注入，包装层只加审计不加权力）——retry_qc 贴 workflow 裸串契约（隔离台真票 timeline reason 以 who 开头且无 dict 乱码={who,note} 误转发现形特征）、note 非空 CLI 层显式拒收点名 note、sign 通道 delivered=true 且 Signature payload 形状落 workflow 可观测面（fresh 票非人门→refused 条目 want 含 sign、who 原样，同 pause KI-061 族文档化回执面；人门签字接受面属 workflow 门逻辑 L1 不重复）。与 t260910-03 intent 分界：彼守多仓派生+双保险丝（create 链），本守入口收口面（退出码/审计/entry_hint/sign/retry_qc 包装）；与 t260908-01 分界：彼守 workflow 侧 pause/retry_qc 幂等唤醒语义，本守 CLI 包装与审计/提醒面。实现落地前红属预期（TDD 信号：A 段红即 KI-067 病灶形状复现），arbitrate/merge 期必须绿；三态契约无 SKIP——stdlib A 段恒跑，temporalio 缺失=ENV_FAIL 点名（B/C 段），docker/bench/隔离台库缺席=ENV_FAIL 点名（C 段）；红线：一切被测子进程 Temporal 地址指不可达桩 127.0.0.1:9 或一次性隔离台，真票只发生在一次性 namespace 跑完即拆",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260910-06/sc_ki067_entry_audit.py", "engine"),
    # ---- t260910-13: failure classification protocol + mechanical baseline attribution (gate decision table / pytest producer seam) ----

    ("t260910-13-failure-protocol-gate",
     "失败分类协议闸判定真缝（t260910-13 主证据，灰盒 L2/L3）：260910 三误判根治面——单行 JSON 规范行 + 闸机械判定。经 admin.py call verify_lane lane=integ 真入口钉死：规范行权威（{ 起始可 json.loads、必含最小字段，判定以行为准、文本行降兼容）；无证据 not-checked 闸内改判 FAIL 拦（fail-closed 治 ENV_FAIL 免责标签）；fail×prepare-reason=违约改判+violation 拦且不因 main 也红放行（capture-chat-active 型）；基线归属决策表——真 git 基线子用例（fixture 仓 main 提交桩×泳道脏改桩，闸真跑 worktree add --detach）：真回归×基线绿拦（t260910-10 型）、同红既有欠账记录不堵且汇总诚实计数、not-checked×self×绿拦 / ×external×绿记录促治理；基线缺席=降级显式声明不静默且产品红保守不放松；指纹闭环（summary.env_fingerprint 在场、baseline_ref 缺席显式 None）；畸形规范行（缺必填字段/伪 JSON 行/同名重复行）fail-closed 不静默零场景绿；闸不认识场景名（异名同 payload 同判、归属各归其名）；基线 worktree 终态回收零残留（git worktree list 断言）。与 t260904-12 甲/乙段（三态文本行不可穿闸）与 t260903-01 ②b-(a)（畸形 FAIL 行 fallback）intent 不同面：彼守旧文本协议，本守规范行+归属决策表；与 developer L1（决策表纯函数真值表/畸形 JSON 电池）不同层：本条锁真缝组装行为。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git 缺失=ENV_FAIL exit 2 点名（基线子用例不可验）。fixture 全落临时目录，零 3099/7233 零 docker",
     "python3 integration/t260910-13/sc_t260910_13_failure_protocol_gate.py", "ro"),
    ("t260910-13-failure-protocol-pytest-source",
     "失败分类协议 pytest 生产端映射真跑（t260910-13 锚⑤，灰盒 L2 缝守卫）：微型真 pytest（非 mock，KI-049 同族缝）钉死 conftest_result_protocol 经 -p 显式装配（cwd=integration，不依赖 pytest_plugins 非根 conftest 的版本敏感行为，方案 K5）——ERROR→not-checked（setup 炸点证据在案）、FAILED→fail、PASSED→pass；相位合并：teardown ERROR 不翻转已判 case 且噪声附记证据不静默吞；一行=一用例不变式（四用例恰四行）；规范行最小字段完备（dur_s 数值=巡检 B 面耗时趋势数据源、started/git_sha/suite 在场）、evidence 单行无内嵌换行。与 developer L1（pytest_runtest_logreport 钩子单测）不同层：本条锁真 pytest 进程 stdout 的生产端输出缝。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；pytest 缺失（venv 与系统均无）=ENV_FAIL exit 2 点名。微型测试文件落系统临时目录，零真仓写入",
     "python3 integration/t260910-13/sc_t260910_13_failure_protocol_pytest_source.py", "ro"),
    ("t260910-13-executor-fail-closed",
     "执行器条目完整性 fail-closed（t260911 仲裁 code-fault 打回的 L1 钉，monkeypatch 级）：复刻池级 submit 不存句柄 → 异常不上浮 → 条目静默丢失照常出绿的实锤形态（004654 报告），钉三层修复——池级异常句柄保留逐个 .result() 上浮=响亮产品红中止（FAIL [__executor__] 点名）；spawn OSError 在 _run_entry 内按协议分类落红（not-checked×external，evidence 点名原文，条目不丢 ran==在册数）；ran==在册数=唯一机械不变式（自校验 complete 红 + INTEG_SUMMARY.expected=在册数供闸复核，闸侧子用例见 failure-protocol-gate S9c）。注入锚=条目面 spawn（argv[0]==\"/bin/sh\"）且与 _docker_hygiene 解耦、双桩 serial 顺序由构造确定（t260912-01 缺陷①：旧「第 N 次 subprocess.run」注入被 hygiene 三连 subprocess.run 先行消费+except 吞掉=B 层假红守门狗自身失效）。与 failure-protocol-gate intent 分界：彼守闸解析与归属，本条守执行器自身条目完整性，同票两面不互替",
     "python3 integration/t260910-13/sc_t260910_13_executor_fail_closed.py", "ro"),

    ("t260908-02-mixed-payload",
     "混合形态工单的多仓明细以一等字段穿越 Temporal 编解码两跳（t260908-02，t260907-13 实锤 bug 的缝守卫）：TicketInput/WorkspacePrep 均有 repo_worktrees 显形字段（default_factory=list 保存量回放）；编解码往返全等（workflow 启动面不再 TypeError=dengzhufpv T2 停摆修复）；畸形分层拒绝精确——类型毁形在编解码层拒、语义非法在闸层拒互不冒充；新旧闸位同拒；单仓对照零回归。stdlib 子用例恒跑，temporalio 缺失=ENV_FAIL",
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
    # t260907-07-epic-next-prepare-project 已随 suggest_next 整链退役删除（t260910-14）。

    ("t260910-14-routes-resolver-parity",
     "路由表解析器 python/TS 一致性守卫（t260910-14 方案 M2）：paths.model_routes 双实现（引擎 shared.resolve_routes_table 查表面 × UI resolveRoutesFilePath 读写面）对同一 per-key 注册表夹具矩阵（相对/~展开/绝对/../逃逸/空值/缺 paths 节）逐项 state+path 全等、拒收子用例两侧同 fail-closed——读写同源不漂移（本票核心目的的机械保障）；畸形输入全走临时夹具零外部源；node 缺席=ENV_FAIL exit 2（KI-046 第三层）。实现落地前红属预期，arbitrate/merge 期必须绿",
     "server/engine/.venv/bin/python integration/t260910-14/sc_routes_resolver_parity.py", "ro"),

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
     "跨项目三面取数对照＋撞码不互串＋防穿越闸随项目根判界（t260907-11，KI-057 宿主实报「dengzhufpv 变更 tab 空」的 fixture 化=验收子用例①）：fpv 视图 epics 列表/详情读 fpv 仓、审批 POST 落 fpv 仓 server/dsh/reviews/ 且 sandbar 视图同 id 读空（写读两面均按项目键）、precache nextHintCached 与 dismiss 随项目根（同代号 demo-x 两项目缓存互不牵连=撞码面，epic 代号无跨项目唯一约束已实核）；diff 判界面=fpv 根内泳道可见（实报反面）而同一 worktree 换 sandbar 锚仍拒「越出」＋根外路径仍拒（红线：闸语义不弱化、判界基准随项目走）。进程内 apply+mock req/res（零端口零 Temporal 零 3099/7233），SANDBAR_PROJECTS_DIR 临时注册表（.migrated 跳种子迁移）；git 缺席=ENV_FAIL exit 2 点名；实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。与 developer L1（resolver/纯函数真值表）与 smoke/changes.mjs（单仓单项目）intent 不同面：本条锁双项目对照组装行为",
     "node integration/t260907-11/sc_wb_anchor_cross_project_faces.mjs"),
    ("t260907-11-wb-anchor-keys",
     "项目键解析契约面：零回归＋报错精确＋隔离语义＋env 收窄（t260907-11，KI-057，验收子用例②的 fixture 化）：无参回落默认仓且响应带 resolved 来源标记（方案承诺）；?project=<sandbar key> 注册表路径解析根与无参回落根逐字节一致（生产 UI 恒带 ?project=，钉住注册表条目不漂移=零回归闸）；未知 key 显式 400 且 error 点名项目键不伪装「越出仓库根」（报错必须精确）；隔离条目显式 502 透传注册表文案（不回落=不违隔离语义）；SANDBAR_EPICS_DIR 仅无参回落生效、per-project 不被 env 串味（红线「旧 env 覆盖链保留」×方案收窄声明双兑现）。进程内驱动零端口零 Temporal；实现落地前红属预期。与 developer L1（resolver 四边角单测）intent 不同层：本条锁路由组装后的响应契约；票面 t.project 与 query 优先级需引擎 ticket show，归 S5 实票不重复",
     "node integration/t260907-11/sc_wb_anchor_key_resolution.mjs"),
    ("t260907-11-wb-anchor-evidence",
     "证据目录锚项目化＋env 收窄（t260907-11，KI-057 第四面，含取图端点同族核销）：fpv 视图证据列表=归档 .suyou/evidence＋泳道 .worktrees 两候选三件、取图端点按 ?project= 读 fpv 根字节一致、sandbar 视图同 id 列表空/取图 404（不串项目）；SANDBAR_EVIDENCE_DIR 仅无参回落生效、per-project 不被串（红线 env 链保留×收窄声明）。进程内驱动零端口零 Temporal；证据防穿（文件名白名单/TICKET_ID_RE containment）归既有覆盖不重复；实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260907-11/sc_wb_anchor_evidence_family.mjs"),
    ("t260908-01-ki061-wake-revive",
     "仲裁超限 blocked 两相复活旅程（t260908-01，KI-061 验收①②的用户可感知面，真 docker 台双 worker 切换）：相一 SANDBAR_TEST_DISABLE_KI061=1（create_plan v2 S3 契约开关=模拟修复前 worker）＋tests-fault 桩驱动 6 轮超限 blocked→宿主注入裁决（host_ruling）→retry_qc 唤醒→断言吃 memoized 仲裁结论立即再 blocked 且 arbitrate 零 respawn（t260907-10 02:12 症状留证）；相二换修复 worker 再唤醒→断言 arbitrate 真 respawn（账本新 spawn、gen 递增）、prompt 含宿主终裁（host_rulings 注入消费面）、verdict=pass 后票离开 arbitrate blocked。与 t260905-10 sc_host_ruling_injection（KI-053 格式纠正路径、单 worker、畸形 ruling 拒收）intent 不同面；与 developer selfcheck（L2 time-skipping 两相闸）不同层不互替；实票复活归宿主发 retry（红线），本条隔离台等价复刻。断言面=stub 账本（agent 实收 prompt）/snapshot，不锚 prompt 文案；docker/舞台缺件=ENV_FAIL exit 2；merge_check 及其后不在范围。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260908-01/sc_ki061_overlimit_wake_revive.py", "engine"),  # engine: docker stage + two-generation worker switch, timing-sensitive legs
    ("t260908-01-ki061-replay-compat",
     "在飞 workflow 重放兼容契约（t260908-01，KI-061 验收②机械面，044c692 裸改重放炸 99809 的同族回归闸，真 docker 台）：先制造修复前形态在飞 history（DISABLE=1 worker 6 轮超限 blocked＋retry_qc 唤醒一次 settle→再 blocked＝t260907-10 现形态），replay_check 只读回放两子用例——子用例一 pre-fix 形态 history（含唤醒穿越点 patched 求值）用修复后代码回放 ok=true（命令序列零分歧）；子用例二修复 worker 复活（arbitrate respawn、KI-061 marker 入 history）后再回放 ok=true（marker notify 先行→同位 True 的消费路径确定性）。与场景①分工：彼锁 live 复活旅程、本条锁重放确定性；与 developer selfcheck（L2 环境内两相）不同层。replay_check 零写（list/fetch only）；docker/舞台缺件=ENV_FAIL exit 2。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260908-01/sc_ki061_inflight_replay_compat.py", "engine"),  # engine: docker stage + worker replay (read-only replay legs)
    ("t260908-01-ticket-pause-gate",
     "工单段间暂停/恢复全旅程（t260908-01，宿主拍板①-④验收面，灰盒 L3，真 docker 台+夹具仓桩脑链=真 DevLaneWorkflow/真 activities/SANDBAR_AGENT_STUB=1）：在飞段发 pause→当前段自然跑完→停段间门口（snapshot.paused+paused_phase=at_gate+timeline paused-waiting）→观察窗不派下一段→resume→走完全链到 closed；反馈可辨三笔（重复 pause/空态 resume/畸形 who 空白与 note 超限）refused 语义锚互辨且拒收不置位；暂停中 snapshot 照常可查（KI-008 面）+ticket-list 行带 paused（列表徽标数据源契约）；pause×rework 显式语义（暂停中压门口、恢复后先打回再推进）；通用性=非 dev-lane 模板（fixture_two_step，SANDBAR_FIXTURE_TEMPLATES 环境门）同款暂停生效+门关时开票拒收点名「未知模板」。拓扑过嵌套护栏（review R3 核准形态）：子进程 env 剥泳道标记三件套+钉 sandbar-ticket-<票id> 专属队列+只连一次性舞台 Temporal，递归按构造不可能，ticket-lifecycle 移出闸教训的收窄声明落场景头注。断言锚 CLI 回执/snapshot/timeline/refused/list 行公开契约，不锚实现内部；文案锚语义词不锚字面（KI-051）。与 ki061 两条（仲裁复活/重放兼容）intent 不同面；与 developer selfcheck_pause（常量/refused 文案/老实例拒收纯函数子用例）不同层不互替。docker/舞台缺件=ENV_FAIL exit 2 点名。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。t260914-04 扩子用例（KI-079 收口，review_plan C1-C5 条件内建）：L0b=离线契约脚本（integration/t260914-04/offline_ticket_pause_entry.py，零 Temporal：ticket.py pause/resume 包装层载荷逐键/D1 身份闸/CLI 畸形输入）；L3.6b=正规入口子用例（宪章所教形式经真仓工作树 ticket.py：回执 ok 且无 entry_hint、重复 pause/note 超限/空态 resume 落 refused 且 who=注入值、本票 snapshot timeline+refused 零 op-local、缺 by 在 CLI 层拒收——「who 空白→workflow refused」仍由 L3.1 裸入口子用例承载，层次分工不重复设防）",
     "python3 integration/t260908-01/sc_ticket_pause_gate.py", "engine"),  # engine: one docker stage + fixture-clone stub workers, two tickets sequential
    ("t260910-04-console-paused-list",
     "console 接口面暂停透传全链（t260910-04，KI-063「场景只测引擎面」封堵子用例，真 docker 台+私有全档台（逐跑 fresh boot+退出 stageDown 零残留）+夹具仓桩脑驻留 worker）：真引擎 pause 后断言 console 面 GET /wf/tickets?project= 行 paused/paused_phase 与 client.py ticket-query snapshot 逐键一致（t260908-01 合并后实测断点正是这一透传跳：ticket.py 薄壳投影丢键，host 直走引擎 ticket-list 修复）；resume 后行回 false、工单续派到收口（收口行按分支断言：水合窗内 paused=false 在场、缺键行不 throw）。护栏两钉：①台面代码新鲜（KI-058 同族）——私有台 fresh boot 挂当前树 /repo=新鲜 by construction，无 restart（共享常驻台形态已整体退场：其 restart 曾在多池并发窗掐断 browser 池在飞流式请求+吃 900s 执行器 kill，260910 实锤）；L0 写守卫=TARGET_HOST 钉本台端口 ∉ FORBIDDEN_PORTS（禁区表 .mjs 不导出时回落 stage_docker.py 读取，两路缺席 env_fail 拒绝空转守卫）；②活 worker 子用例——驻留 worker 形态照 sc_ticket_pause_gate（夹具仓 clone+SANDBAR_AGENT_STUB=1+剥泳道三件套+钉本票专属队列+TARGET_HOST 恒本台∉FORBIDDEN_PORTS）。与 t260908-01-ticket-pause-gate（引擎面语义）intent 不同面；与 workbench 假引擎 UT（host 形状/错误契约）两层各管一段。docker/舞台缺件=ENV_FAIL exit 2 点名。登记 exclusive（gen2 验收修正）：私有台形态下本条已零共享面足迹，但仍是**最重的 docker 台条目**（fresh 全档台+全仓 clone+全链旅程，典型 6-8 分钟）——run 260910-232102 实测并发窗内撞 900s 执行器 kill 帽（cross-pool daemon 争用，同窗 stage-docker/multi-tab/fix15 对一起红）；exclusive 先行独占执行两端都保护：本条预算不被 daemon 争用吃掉，其余池不被本条 boot herd 加压（compose-up herd 保持小的既有纪律）。代价=套件墙钟+~6 分钟。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260910-04/sc_console_paused_list.mjs", "exclusive"),  # exclusive: heaviest docker-stage journey (fresh full stage + clone + full lane ~6-8min) — 900s executor kill under cross-pool daemon pressure in run 260910-232102; exclusive protects both its budget and the other pools
    # ③ final-verification run E (260909): anchor boots two docker stages and is
    # the most stage-boot-sensitive entry (≈3/8 history regardless of engine
    # width; run E burned the whole 600s ensure budget when its boot coincided
    # with the main-pool with_stage herd at Phase-2 t=0, wall 924s). It runs
    # LAST in the engine lane: by then the other pools have drained, so its
    # stage boots land in a near-empty compose herd. Zero wall cost (engine
    # serial sum unchanged). The ticket-start concurrency under test is
    # internal to the scenario (barrier), unaffected by pool position.
    ("t260904-02-ticket-start-anchor",
     "裸入口开票硬闸+隔离台并发隔离端到端（t260904-19 起 docker 测试台双实例，epic 验收1/4/5，KI-032 修复回归）：裸 client.py ticket-start 带 project→Temporal 内 payload workspace.path 绝对路径且锚注册项目主目录/.lane/（worktree 同锚，落仓与执行 worker 解耦）；缺 project/未知 key=创建即拒收且两红因文案互辨；双槽并发开票时间重叠互不见对方工单（ticket-list 双向+跨槽 describe not_found）；审计钩子证被测子进程零连生产 7233/8233（含自证拦截子用例）+双台端口面核验（互异/不在禁区 3099/3199/7233/8233/17233/18233）+SANDBAR_TARGET_HOST 指生产构造即拒（红绿自证）；teardown 零残留（down 后 docker ps 无本工程容器）、端口释放、down 幂等二连、同工程名立即 re-up（t260904-19 docker 台语义，容器由 daemon 持有无锁可崩，取舍见 stage_docker 头注）；docker 缺席/镜像缺席=ENV_FAIL exit 2 点名",
     "python3 integration/t260904-02/sc_ticket_start_anchor.py", "engine"),  # engine-LAST (run E): stage boots land in the drained window; concurrency under test is internal

    # ---- t260910-10: docs per-project root (KI-070) + docs view mock v1 — project-anchor docs family ----
    ("t260910-10-docs-project-anchor",
     "docs tree/doc 按项目根解析（t260910-10，KI-070 主干 API 面，隔离台 HTTP 直读，工单必含①②）：非 sandbar 夹具项目（真目录真文件真读）锚下 tree 出夹具篇目（根级+嵌套 sub/）绝不含 sandbar 定稿库签名篇目、doc 真读出夹具正文且全文无 sandbar docs/notes 双签名串入（正反两面）、notes scope 同构（夹具 notes 在场/epics 不串）；resolved 可观测契约={source:'project',key,root=夹具注册主目录逐字节}（resolvedMark 六面路由统一口径；root 逐字节=KI-070 终态判据）；缺省/未锚回落引擎仓（tree/doc 读 sandbar 真库篇目、resolved source='default'、无夹具串入=旧行为零回归）；未注册 key 显式 400 且 error 点名「未知项目」、无 resolved、无 sandbar 篇目（不静默回落=防数据串仓）；空 scope 目录诚实降级（200 empty=true+人话 reason 非空+groups 空，不 500 不谎报，措辞不锚字面）。lib_fix17 自举临时注册表+双夹具项目，零浏览器依赖（纯 API 无 KI-036 环境用例）；端口红线 ≠3099/7233。与 t260905-06-doc-read-through intent 不同面：那条锁缺省锚单仓阅读链路+穿路径白名单+窄栏（本票回归面不重复设计），本条锁多项目锚解析/回落/注入。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260910-10/sc_docs_project_anchor.mjs", "ro"),
    ("t260910-10-docs-ui-mock-v1",
     "文档视图 mock v1 终态旅程（t260910-10，KI-070 UI 半+260910 过稿版式，隔离台浏览器走查，工单必含③；t260915-10 语义变更留痕：文档页初值起跟随壳层项目——初值=经夹具甲组「文档」图标进入的壳层当前项目 data-wb-doc-project-key='fixa'、首屏树=夹具篇目、初载 docs 请求带 project=fixa（壳层接线线上证据），旧稿「初值=缺省引擎仓选择态+初载无 project=」锁的正是 t260915-10 修的病灶语义已退役，缺省回落旅程=选择器手动选 sandbar/default 手动子用例（引擎库篇目回场+wire 无 project 请求=缺省回落零回归））；固定 UI 元素英文在场（Project/Docs/Notes/Search 输入框/On this page）；Project 切换器换夹具项目 → 请求带 ?project=<夹具>（wire 层反 viewProject 漂移）且树随所选项目切换（夹具篇目在场/sandbar 篇目退场）；开篇正文真渲染+五枚 chip 键在场（Status/Verified/Category/Updated/Path）、Verified 无数据源=显式 pending 占位且无日期形状（不留假值终态化）；On this page 大纲随选中文档渲染（h2 条目在场）且点击真跳转（目标标题入视口）；分组可折叠（组头点按条目可见性翻转）；Search 当前项目内过滤终态（收窄/清空还原）；空态退化（无 notes 的夹具切 Notes 页签 → 零条目+诚实 reason 在场+On this page 空+不残留旧项目内容+不炸）。断言锚=公开契约锚 data-wb-docs-root/[data-wb-doc-item]+元素角色/可见文本，不锚内部类名；playwright/浏览器缺失=env_fail（KI-036 家族）。与 t260905-06-doc-read-through intent 不同面：那条锁单仓阅读链路+代码块+窄栏单栏流+无溢出（回归归它），本条锁 mock v1 新元素与新旅程；与 t260910-10-docs-project-anchor 不同层（API 契约 vs DOM 终态）；与 t260915-10-docs-follow-project 不同面：本条锁 mock v1 版面旅程（初值跟随只作为进入前提断言），那条锁壳层接线语义全集（跟随/手动优先/重挂载/空态指引）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260910-10/sc_docs_ui_mock_v1.mjs", "ro"),

    # ---- t260915-10: DocsSection 接壳层 projectKey（KI-057 同族第二形态：文档页跟随当前项目）----
    ("t260915-10-docs-follow-project",
     "文档页跟随当前项目（t260915-10，DocsSection 接壳层 projectKey，KI-057 同族第二形态回归闸，隔离台浏览器走查）：壳层接线初值/跟随——经夹具甲组「文档」图标进入=初值夹具甲（data-wb-doc-project-key='fixa'+选中项含「夹具甲」+首屏树=夹具篇目+sandbar 篇目退场+wire 带 project=fixa=壳层入口直开线上证据）；手动优先（spec ②，touched guard）——子用例一选择器手动选缺省=引擎库篇目回场+wire 出无 project 请求（缺省回落零回归），子用例二点夹具乙组「文档」图标（viewProject fixa→fixb 真变化、同挂载、touched=true；同组同值点击=React bail out 空转子用例已弃，review_plan R1 教训）→选择器仍=缺省+无新 project=fixb 请求+树仍引擎库（判别力：无 guard 实现=选择器跳 fixb+请求发出+树变空，两态可辨）；重挂载重新跟随（touched 生命周期另一端，收敛口径评审已裁）——切夹具乙「工单列表」图标卸载文档视图再点回=初值 fixb；空态不冒充（spec ③）——夹具乙空根（无 docs/ 无 notes/）零条目+新契约锚 data-wb-doc-empty-hint 在场（文案含项目键与「回落」语义）+引擎库篇目不串入+wire 带 project=fixb（后端诚实降级 200+empty+reason，前端不回落），Notes 页签同构；既有面回归——选择器手动切回夹具甲树随切（t260910-10 切换面不破）。断言锚=公开契约锚 data-wb-docs-root/data-wb-doc-project-key/data-wb-doc-empty-hint/[data-wb-doc-item]+元素角色/可见文本，不锚内部类名。与 t260910-10-docs-ui-mock-v1 不同面：那条锁 mock v1 版面旅程，本条锁壳层接线语义全集（guard 是本票新语义里唯一无既有场景可兜底的行为面）；与 t260910-10-docs-project-anchor 不同层（API 契约 vs DOM 终态）。lib_fix17 自举（夹具甲 docs/notes 真文件+夹具乙空根注册即孤立），playwright/浏览器缺失=env_fail（KI-036 家族）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260915-10/sc_docs_follow_project.mjs", "ro"),

    # ---- t260910-14: suggest_next 退役 + 模型路由表迁出 git（真源=声明指向文件，宿主风险令 260910 夜口径）----
    ("t260910-14-routes-truth-fallback",
     "路由表真源随项目声明走（t260910-14 主题二读面；t260914-05 兜底分支退役口径）：声明 paths.model_routes 指向文件=引擎读面（改表→解析即新模型=验收 A 解析子用例）；无表三态分态可辨且**一律无表**——decl_missing（未声明，path=\"\"）/file_missing（文件缺失）/bad_content（内容坏，带 sha256 字节指纹），引擎面单点告警点名 state+路径+指纹（stderr 捕获断言），生效模型=None=profile 默认绝不静默取仓内表；**反毒子用例**：仓内 server/model-routes.yaml 即使在位（(b) 降级口径不删文件）也不被读；显式声明仓内相对路径=显式声明合法生效（state=ok）；`..` 逃逸 fail-closed、`~/x` 展开、空值拒收（形状子用例，夹具注册表 SANDBAR_PROJECTS_DIR 隔离零真环境写）。与 t260902-07 两守卫（表静态校验/查表性质，L2 随票重写）与 G6 重写钉（分态新语义）intent 不同面：本条锁真源随声明+无表三态点名的系统拼装行为。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；引擎 venv 缺席=ENV_FAIL exit 2",
     "python3 integration/t260910-14/sc_routes_truth_fallback.py", "ro"),
    ("t260910-14-routes-ui-parity-save",
     "路由真源迁移 UI 面读写同源（t260910-14 主题二，验收 B/宿主令④d）：saveRoutesTable 落声明指向的机器级文件（字节级）且夹具仓 git 工作区零变更；buildRoutesView 回传 routes_file=声明指向路径（生效路径+来源展示面）；initRoutesTable/engineRoutesTemplatePath 导出退场（init 引导退役，宿主拍板）。arbitrate 段去重：python/TS 解析矩阵一致性守卫归 t260910-14-routes-resolver-parity（named 函数双面逐项全等），本条剥原矩阵子用例专锁 UI 读写/展示终态（覆盖率由彼条保全非弱化）。与 t260910-14-routes-truth-fallback 不同面：彼锁 python 读面，本条锁 UI 读写同源终态。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；node/git 缺席=ENV_FAIL exit 2",
     "node integration/t260910-14/sc_routes_ui_parity_save.mjs", "ro"),
    ("t260910-14-retire-replay-compat",
     "suggest_next 退役 cutover 在飞重放兼容（t260910-14 主题一，方案 T1-2 三层机械面）：通过子用例=退役后代码回放无 suggestion 命令的在飞 history（docker 台 lib_ki061 成熟驱动 merge 签字前复杂形态）+全 RUNNING 集回放零分歧（drain 闸同款）；负向子用例=含 prepare_epic_next/suggest_next 活动命令的旧形态导出 history 回放**响亮红**（预期边界留档=drain 必要性机械证据；夹具缺席=显式红点名不静默，备齐程序见 integration/t260910-14/fixtures/README）。与 t260908-01 场景② intent 不同面：彼锁 KI-061 marker 消费重放，本条锁退役 cutover 命令序兼容边界。实现落地前子用例三红属预期（TDD 信号），arbitrate/merge 期按口径绿；docker/镜像/舞台缺件=ENV_FAIL exit 2",
     "python3 integration/t260910-14/sc_retire_replay_compat.py", "engine"),
    ("t260910-14-retire-surface-clear",
     "suggest_next/epic-next 退役面功能引用清零扫（t260910-14 主题一，验收 G 机械子用例）：dev_lane/agent_activities/shared/工作流参考快照全文字符零退役 token；workbench src+node.ts 零 epic-next 导入/路由/janitor/客户端入口；退役文件在位性九件（epic-next.ts、selfcheck_epic_next、t260901-19 两场景、t260907-07 建议场景、对应单测与 tests/smoke）均退场；ui-check 夹具零 suggest_next 段数据；run_scenarios 零指向退役文件的登记路径、auto-rework 场景旧源码锁断言串退场。白名单=notes/docs/roles 历史账（integration.yml:67 教训行）/.sandbar/workbench lib 构建产物/本票目录。与 t260907-05 suyou 命名残扫 intent 不同面（不同 token 族）；与 t260910-14 其他三条不同面（彼锁行为，本条锁退役完备性）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；纯 stdlib 恒可跑",
     "python3 integration/t260910-14/sc_retire_surface_clear.py", "ro"),
    # ---- t260910-15: build determinism — pin bundler version/args (byte-stable rebuild of committed lib/) ----
    ("t260910-15-build-reproducible",
     "同源码重建逐字节稳定（t260910-15 验收①② + t260911-06/KI-073 增子用例，灰盒 L3）：经组件公开构建入口（npm run build→仓内唯一构建脚本）依赖装一次（npm ci 按 lockfile，registry 漂移不混入断言）、同一 node_modules 连续两次构建 → lib/client.{cjs,js} sha256 逐字节相等且 cjs≡js 同体；构建后 git status 对 lib/ 为空=重建产物与落仓产物一致+零 map/gzip 等计划外副产物文件（porcelain 对 untracked 计数，副产物与「产物≠落仓」两意图并锚一条 porcelain，显式对比在 S5 拆分子用例）；mtime 注入子用例（改 src mtime 不改内容→第三次构建）sha 不变=时间戳不入产物（门禁/证据类断言的 mtime 干扰面）；S5 泳道内显式子用例（KI-073 验收 a/b）：重建 == HEAD committed 产物显式 sha256 对比、判红附 diff 首 40 行（压缩器写法抖动从 4 行噪音升格为点名证据）——判定前提=构建输入（src/config/双 lock/构建脚本/兄弟包 knowledge|providers src）与 HEAD 同批，implement 期票内改动未落盘时 na 属预期时点、arbitrate/merge 期必可判（na 记 na=W 不假绿，全 na→exit 1）；S6 入口唯一性子用例（KI-073）：构建实际解析版本（tsdown 横幅留痕）≡ lockfile 锁定 ≡ node_modules 安装三连一致，绕开 npm ci 的入口（npx 回落/陈旧 node_modules）在此点名——判定核心纯函数化先红绿自证（合成漂移样必咬恰 2 处、畸形 lockfile/坏 JSON 缺条目 FAIL 点名不 crash）；终态自证 lib/ 仍干净=场景净零副作用。S3 判红语义：HEAD 产物若非锁定工具链可复现（历史漂移版本所建）即病灶实锤，实施段校准重建（一次性真实 diff）后恒绿。npm ci 网络/缓存失败=ENV_FAIL exit 2 点名尾段不假红；依赖在位时构建非零退出=FAIL 产品红。与 developer L1（workbench/tests build-determinism）intent 不同层（彼随实现重写不作契约网，本条闸内常驻锚公开接口与磁盘终态）；与 t260903-04-client-bundle-sync（新鲜度特征词面快守卫）、t260903-13-workbench-bundle-loads（产物形态合同）、t260911-06-artifact-provenance（票型触发的闸侧归因点名）intent 不同面：本条守「重建必然逐字节可复现」常驻回归面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260910-15/sc_build_reproducible.mjs"),
    ("t260910-15-toolchain-pinned",
     "打包工具链锁定完备负锁（t260910-15 验收①前置=t260908-01 化妆噪音故障的复发条件移除守卫，灰盒 L2 纯读秒级）：仓内不存在任何会拉到非 0.22.2 tsdown 的活声明口径——package.json devDependencies 精确版本无 ^/~；package-lock.json 根 specifier 与 node_modules/tsdown resolved 双点、pnpm-lock.yaml importers 段 specifier/version 双点均 0.22.2（双锁矛盾即 260910 实锤病灶：pnpm 路径曾锁漂移版）；口径载体文件集（package.json/两把 lockfile/tsdown.config.ts/build-client.sh/README）零漂移版本词面负锁（活口径只长在承诺载体上；验收记录等叙述面合法不扫——词面全仓扫会误咬历史叙述并自咬本场景，试跑实录）；start-console.sh 的 npx@0.22.2 为写集外合法固定面，主版本锚不进载体集合）；组件公开构建入口 scripts.build 指向仓内构建脚本非裸 tsdown。判定器先红绿自证（0.22.14 合成锁样必咬≥4 处、0.22.2 锁样必绿=防恒真）；锁定载体文件缺失/不可解析=FAIL 点名（承诺载体被拆是产品红非环境缺）。与 developer L1 负锁断言 intent 不同层；与 t260903-12-merge-checks-pairs（护栏配置对齐面）不同面。锚文件终态不锚行号与内部结构。实现段落地前红属预期（TDD 信号：当前仓双锁矛盾在案），arbitrate/merge 期必须绿",
     "node integration/t260910-15/sc_toolchain_pinned.mjs", "ro"),

    # ---- t260911-06: KI-073 收口——产物 provenance 闸侧归因点名（票型触发） ----
    ("t260911-06-artifact-provenance",
     "产物 provenance 闸侧归因点名（t260911-06/KI-073③，灰盒 L3，票型触发）：票 diff 含 server/plugins/workbench/lib/client.{cjs,js}（工作树 lib 任一产物与 HEAD 有差，含删除/半缺件态——票删产物也是闸侧必须点名的 delta，双缺件判 MISSING 红不 na 假绿）时经唯一构建入口真实重建一次，把 lib delta 机械归因五态——SAME_BATCH 绿=重建==工作树 lib（产物与源码同批，t260910-14 确立的合法交付形态）；STALE 红=构建输入（src/config/双 lock/构建脚本/兄弟包 knowledge|providers src）相对 HEAD 有改动但重建≠工作树 lib（改了源没同批重建）；FOREIGN 红=输入与 HEAD 同批、重建逐字节复现 HEAD 但工作树 lib≠HEAD（delta 非本链产出=手改/外来工具链写入，t260911-02 被误判「越界写 lib/*」卡门的现场形态）；DRIFT 红=输入同批且锁定工具链连 HEAD 都复现不了（工具链/环境漂移，KI-073 核心病灶）；MISSING 红=工作树产物缺件（失败半旧/手删/被误清，锚缺件不误落 FOREIGN/DRIFT 误导归因）——红态附工作树 lib delta 的 diff 首 40 行点名。归因判定器纯函数化先红绿自证（CLEAN/SAME_BATCH 绿样、MISSING/STALE/FOREIGN/DRIFT/BUILD_FAIL 红样必咬、非 hex/undefined 畸形指纹 BAD_INPUT 点名不 crash，同 sc_toolchain_pinned 合成样先例）；非破坏性=触发路径先快照 lib 字节、重建取指纹后 finally 原样写回+缺席产物拆重建物（as-found，红态证据不被重建覆盖，硬杀 SIGKILL 例外已在场景头注声明复位路径）。成本口径：常驻干净树（lib==HEAD）零重建秒级，仅票型触发付一次 npm ci+tsdown（分钟级，与 t260910-15 同量级）；不做「lockfile 一致跳过 npm ci」捷径（入口唯一性要求真实走唯一入口）；唯一入口内 npm ci 失败（脚本显式点名）=ENV_FAIL exit 2 环境红不诬产品（同 15 号 S1 口径）；改源未重建且 lib 无 delta 的新鲜度面归 t260903-04 特征词触发（本条票型=lib 有 delta）；登记 exclusive 独占先跑=与同树构建场景机械互斥（main 池缺省并发 3，「串行池」说法不成立；build-client.sh 先拆旧产物再建，并发互踩会互染判定面——KI-072 负载敏感教训：互斥靠排他不靠运气）。intent 去重：与 t260910-15-build-reproducible（常驻回归面「重建必然逐字节可复现」，不问票型）不同面——本条是票型触发的闸侧归因器；与 t260903-04-client-bundle-sync（新鲜度特征词面快守卫，非逐字节不重建）、t260903-13-workbench-bundle-loads（产物形态合同/可加载面）不同面。文件落 integration/t260911-06/=本票目录（套件按票号归档惯例，C7）。git 只读；零 3099/7233 接触；exit 三态（t260904-12）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260911-06/sc_artifact_provenance.mjs", "exclusive"),

    # ---- t260911-01: 工单 diff 面多仓汇总 + 引擎过程产物过滤（dengzhufpv 260910 缺陷 2a/2b 回归面） ----
    ("t260911-01-multirepo-diff-faces",
     "多仓票 diff 面人审可见性主干（t260911-01 场景①，2a/2b 缺陷回归，临时 git 夹具多仓项目零真实依赖）：成员仓文件在逐仓汇总 repos[] 与顶层兼容层（<repo>/ 前缀定位口径归一）双面可见且 unified 可展开、各仓 base 各自对照不串；过程物（.sandbar/.dsh/out/__pycache__/node_modules/.venv，含嵌套 a/b/__pycache__ 与成员仓内形态）不进清单且 excludedPaths 点名到具体路径带仓前缀（验收 d「或点名」子用例，上限封顶）；单仓退化零回归（repo_worktrees 缺省/空 → 单仓路径原样无前缀）；畸形 repo_worktrees（非列表/缺字段/repo 含 .. 或绝对路径）整体视同单仓不炸不部分采纳；成员仓未物化 emptyReason 点名他仓照常；成员仓 >60 文件按仓封顶不全局互挤（R3：大成员仓不把根仓挤出清单、顶层=各仓封顶拼接）。被测缝=host 公开契约 computeTicketDiff（t260907-11 同款直驱先例），与 developer L1 真值表分层面；git 缺席=ENV_FAIL exit 2",
     "node integration/t260911-01/sc_t260911_01_multirepo_diff_faces.mjs", "ro"),
    ("t260911-01-filter-contract-guard",
     "过程物过滤口径单一真源契约护栏（t260911-01 场景②，读源断言 L2）：workbench 过滤表（changes.ts PROCESS_ARTIFACT_DIRS）⊇ 引擎两表现有排除（agent_activities.SETTLE_PATHSPEC + verify_lane.RUNTIME_PREFIXES，ast 抠字面量、跨语言无法 import 真源）——白名单可扩但不得丢 .dsh/.sandbar/.suyou 已有覆盖（丢=引擎自管过程物回流人审 diff 面，2b 复发形态即红）；派发白名单五目录（.sandbar/.dsh/out/__pycache__/node_modules）在表；闸3=handler 透传一跳护栏（node.ts computeTicketDiff 调用参数必须透传 repo_worktrees——t260908-01 同族「host 挑字段漏透传→场景全绿 UI 全瞎」断点防线）；挂账面可判定不判红——workbench 有而引擎侧没有的差集逐行打 LEDGER（out/pycache 误代落盘实案根因的引擎根修挂账，根修落地后差集收空即可销账）。纯 stdlib 零环境依赖",
     "python3 integration/t260911-01/sc_t260911_01_filter_contract_guard.py"),
    # ---- t260912-01: 集测三护栏缺陷回归（看门狗注入解耦 / 汇总计数单源化 / 依赖解析位置无关） ----
    ("t260912-01-summary-count-purity",
     "执行器汇总两套计数单源化回归（t260912-01 缺陷②，in-process monkeypatch 级，stdlib 秒级零 docker）："
     "合成「场景 stdout 混入嵌套 JSON」样（嵌套 pass 规范行 + exit 1）→ SCENARIOS 行与 INTEG_SUMMARY 行"
     "逐字段一致且真红不被顶替（子进程 stdout 不进 recount 输入——灌水缝构造性移除）；通过桩混入嵌套 JSON/"
     "畸形规范行（{not-json、[1,2、缺字段行）→ 不炸不计数两行照旧一致；闸同款解析子用例（对执行器自身 stdout 按 "
     "verify_lane strip→首字符→parse 口径重算）== INTEG_SUMMARY 且候选名集无嵌套名（尾段回显中和面闭合："
     "否则闸 recount_mismatch 错归因假红）；负锁——真灌水（recount 面多出一条 pass）、漏收（两条目缺一行明细，"
     "明细 ran<rc ran）、综合行与 rc 相矛盾（分叉双向）任一注入必 FAIL [__executor__] 汇总两套计数分叉 + rc=1"
     "（谎报即红）；_counts_mismatch 纯函数单元三态（一致 None/灌水点名/漏收点名；空明细=声明降级面返 None，"
     "单条目漏收不可机械检出的边界在案）；夹具桩 _docker_hygiene（被测面=结算计数，不耦合 docker 环境）",
     "python3 integration/t260912-01/sc_t260912_01_summary_count_purity.py", "ro"),
    ("t260912-01-pw-path-resolution",
     "浏览器场景 playwright-core 依赖解析位置无关守卫（t260912-01 缺陷③，读源断言 L2 + 运行互证）："
     "八条 mjs（t260903-07 两/t260904-07/t260905-09/t260901-24/baselines 三）统一引用 lib_pw_deps.mjs 单源"
     "（mainRoot=git rev-parse --git-common-dir 位置无关 + 四路探测 + SANDBAR_PLAYWRIGHT_PATH/MODULE 双 env 名）；"
     "禁词面=主树位置算术（resolve(REPO,'..','..')、path.resolve(REPO_ROOT,..,..)、MAIN_TREE、"
     "ui-check/node_modules/playwright-core 候选字面量）与谎报文案（playwright-core unavailable/沙箱外安装/"
     "本树+主树均无——布局算错不得说成依赖缺失），泳道根 HERE/../.. 形态显式豁免（位置无关合法面）；"
     "变异自证防恒真四样本（主树算术必咬/合法泳道根必过/干净样过/文案样必咬）；mainRoot 与 git 直呼双算互证；"
     "临时主仓+git worktree 位置无关子用例：非 .lane 布局（任意父目录）下 loadPlaywright() 组合路径真装载、"
     "mainRoot 落主仓内（git worktree add 终态回收+worktree list 零残留）；主树 playwright-core 可 import 且"
     "来源路径==mainRoot 拼出路径（防裸包侥幸命中盖住第④路缺陷）。git 缺席=ENV_FAIL exit 2 点名",
     "node integration/t260912-01/sc_t260912_01_pw_path_resolution.mjs", "ro"),

    # ---- t260912-02: 测试台生命周期三修（去名额闸留保险丝 / 残台自动认领并拆 / 起台自管网段）----
    # 六条 intent 互不重叠：burst=爆发规模×地址池零复发×清场（A/B/G）；
    # sweep-owner-gone=判拆矩阵+三负锁（C）；sweep-cost=成本+失败可见（D）；
    # net-table=分配契约缝；headroom=常驻不挤名额（F）；runaway=失控刹停点名（E）。
    # 残台形态注入=租约状态面手术（工单验收 C 明令注入口）；断言只锚 CLI 进程级
    # 行为与 docker 公开观测面（compose label/网络 IPAM/端口/进程表）。
    ("t260912-02-burst-managed-subnets",
     "并发 32 台 dsh 真台同一瞬爆发 32/32 成功、零超时红、墙钟≤60s；全部子进程输出与 docker network 事件流零命中「fully subnetted」（地址池报错零复发）且零保险丝红（缺省 100 不被 32 台触发）；逐台 inspect 断言网段全部∈受管网段表（base /16 切 /24）、跨台两两互异、无一等于手工直跑 compose 的缺省网段（保留槽不被分配器发出）；48 台 temporal 轮每路只许 rc=0 或环境红 rc=2（非环境类失败=产品红）且成功≥40；收口=80 工程容器/网络/卷逐项零残留、全机容器数与网络数回落跑前基线、3099/7233 LISTEN pid 跑前跑后一致（t260912-02 验收 A/B/G，灰盒 L3）。与 t260904-19-parallel-zero-residue（N=2 隔离/爆炸半径）、t260910-12-herd-no-crosstalk（N=6 端口互斥+幂等）intent 不同层：本条锚爆发规模下网段自管与地址池零复发，是病灶三的用户级证据。登记 exclusive：地址池/保险丝判定对共机负载敏感，并发池污染判定面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/测试镜像缺席=ENV_FAIL exit 2",
     "python3 integration/t260912-02/sc_stage_burst_managed_subnets.py", "exclusive"),
    ("t260912-02-sweep-owner-gone",
     "残台按主人存在性自动认领并拆（t260912-02 验收 C，灰盒 L3）：注入五残台形态（工作目录已删真台/目录删+pid 活+心跳新鲜合成台/泳道不在 worktree list/心跳陈旧 2h+pid 活/legacy 旧格式 repo_dir 已删）清扫必须全拆（容器+网络+卷逐项空）且报告逐条点名；三负锁不得误拆（booting 且心跳新鲜且 owner 非工作树=阀1、泳道在册健康台=阀2 零接触、legacy 活台 repo_dir 非工作树=fail-closed 不拆只留报告行）；sweep --dry-run 只认领不拆；起台时挂点行为证明（再造残台后正常 up 新工程，新台健康同时旧残台被顺手拆掉且健康台原封不动）；清扫二连幂等。pid 存活只是辅证的断言子用例=形态(i-a)/(iii)（pid 活+心跳新鲜/陈旧都拆得主）。与 t260910-12-holder-kill-reclaim（hold 被杀才触发的判死回收、租约四象限）intent 不同面：本条锚 hold 活着也拆得主的主人存在性清道夫（病灶二）。登记 engine：拆台按工程名隔离不碰他台。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260912-02/sc_stage_sweep_owner_gone.py", "engine"),
    ("t260912-02-sweep-cost-failure",
     "清扫成本与失败可见性（t260912-02 验收 D，灰盒 L3）：零残台时单次扫描+清理连续三遍每遍≤5s 且 rc=0、零点名（没有残台不得编造点名）；注入「主人目录已删」残台+置坏 docker 桩（PATH 前置必失败假体，只遮蔽 docker）→ sweep 必须非零退出并在输出点名该残台——静默吞掉=红；撤桩重扫同一残台被正常拆掉（恢复路径真通）；幂等二扫仍在预算内。与 t260912-02-sweep-owner-gone（拆谁/不拆谁的判定矩阵）intent 分工：本条锚拆得快不快、失败了看不看得见。登记 exclusive：≤5s 是负载敏感断言（KI-072 家族），并发池会打假红。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260912-02/sc_stage_sweep_cost_failure.py", "exclusive"),
    ("t260912-02-net-table-contract",
     "受管网段分配的 CLI 契约缝（t260912-02 病灶三用户级契约，灰盒 L2/L3）：两台真台各建一网网段∈受管表且互异（分配对照在册防撞号的用户级证据）；同项目 ensure 幂等复用 reused=true 且网段不漂移（复用不得重新分配）；down 后网络消失且该网段在全机 daemon 网络中不再被占（槽位归还）；compose 渲染契约（手工直跑路径）：无 env 渲染出缺省 ipam 子网∈受管表、显式注入自由槽后渲染=注入值（手工并行台错槽出路在场）；畸形 SANDBAR_STAGE_NET_BASE 按 usage 档拒收（rc 非 0/2）+输出点名旋钮+零容器产生。与 t260912-02-burst-managed-subnets（爆发规模系统行为）intent 分工：本条锚单台粒度分配契约缝；畸形底座真值表归 developer L1。登记 engine。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260912-02/sc_stage_net_table_contract.py", "engine"),
    ("t260912-02-fuse-headroom-resident",
     "常驻租约在场时并发起台不再自我挤压（t260912-02 验收 F，灰盒 L3）：注入 6 条常驻形态租约（在飞票控制台台/供给台镜像面：state=up+keep+持有者进程活+心跳续鲜+主人=本仓工作树）后并发 16 台 temporal 真台 ensure：16/16 全绿、端口两两互异、全部∉生产/禁区面、全程零保险丝红（6 常驻+16 场景=22 活租约远不触闸）；风暴后 6 条常驻租约原封不动（在册+持有者进程仍活）；风暴台终态零残留。与 t260912-02-fuse-runaway-named-stop（超限刹停）正反两面不互替；与 t260910-12-herd-no-crosstalk（N=6 端口互斥）不同层：本条锚「常驻在场」床位前提——旧满员闸把常驻计入 12 名额正是自挤根源（病灶一）。登记 exclusive：16 路并发 compose-up 是修复宣称的生产级负载，独占保判定面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/测试镜像缺席=ENV_FAIL exit 2",
     "python3 integration/t260912-02/sc_stage_fuse_headroom_resident.py", "exclusive"),
    ("t260912-02-fuse-runaway-named-stop",
     "失控起台循环被保险丝刹停并逐条点名（t260912-02 验收 E，灰盒 L3）：注入小保险丝（SANDBAR_STAGE_MAX_STAGES=4 隔离锁根；生产缺省 100 的不触闸面由 burst 场景与 L1 缺省值断言承担不在此重复）+一口气 200 路并发 up（失控循环样本）：恰≤4 路入位（原子不超售）、其余全部刹停且每路红行点名保险丝并附活租约清单（pid=/lease= 可核对——「点名」是硬断言）、刹停红一律环境档 rc=2；损害有界：全程在跑容器≤4 台规模、风暴结束无孤儿持有子用例进程残留（pgrep 公开观测面）、清理后零容器残留；全程零地址池报错。与 t260910-12-full-capacity-queue（小闸 2 路最小形态的语义迁移面）intent 分工：本条锚 200 路风暴的损害有界与逐条点名，是验收 E 本体强度。登记 exclusive。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/测试镜像缺席=ENV_FAIL exit 2",
     "python3 integration/t260912-02/sc_stage_fuse_runaway_named_stop.py", "exclusive"),

    # ---- t260911-05: KI-048 脏 main 合并门 + 详情人话状态卡 ----
    ("t260911-05-ki048-dirty-main-merge-gate",
     "KI-048 脏 main 合并门全链（t260911-05，真 git 临时仓 × merge_check/_squash_merge 接缝，灰盒 L2/L3）：合并前脏检查提前红灯点名文件（staged/未提交相交/未跟踪相撞三形态，验收a/c）且恒非冲突类（conflict=False、conflict_files 空不进自动消解回路）；处置后该检查项红→绿翻转（验收b 闸侧形态）；merge 回执分类脏工作区=action=dirty+协议 reason 码非空（main_dirty）+点名文件+「非冲突」人话文案，真冲突（main 已提交相撞）仍 action=conflict 两类不互吞、干净 main 收口 ok=True merged（验收①/b 对照面）；红线：全部失败路径前后 main 工作区文件字节哈希/HEAD/stash 计数/porcelain 逐项不变（无 auto-stash/auto-commit，260908 事故红线，验收f）；dev_lane 源码契约锁（docker 台外可守的分流面，t05/G 系同族）：dirty/failed→_blocked(\"merge\") 先于 conflict 唯一 _auto_rework(\"merge_check\")、blocked_detail{reason_code,files,next_action} 在位、dict 态回执重建回填 reason/files（R3 回归守卫）。与 developer L1（test_ki048_merge_classify 白盒纯函数电池）不同层、t260910-03 G7（保险丝B 清单缺失面）不同故障面、sc_check_auto_rework_trace（_auto_rework 统一入口锁）不同对象。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=行为子用例 ENV_FAIL 点名，stdlib 子用例恒跑",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260911-05/sc_ki048_dirty_main_merge_gate.py", "ro"),
    ("t260911-05-ki048-status-card-dom",
     "KI-048 详情人话状态卡 payload→pixel（t260911-05，隔离台浏览器走查=验收d/e 机械 repeatable 面，mock 260904 A 块四件）：blocked 脏工作区票抽屉内 .wb-status-card 恰 1 个红态卡——人话主文案（非冲突）、挡事文件点名 chip、下一步（retry_qc）、<details> 原始日志折叠四件齐且折叠摘要为英文固定元素（界面固定元素英文口径锚无 CJK 不锚措辞）、blocked_reason 横幅同页可达（验收d）；无 blocked 字段老票整卡不渲染零扰动；畸形 blocked_detail（空对象+无路径 reason）卡退化渲染不崩且绝不凭空捏造文件点名（UI 不翻译它没拿到的信息）；全旅程零 pageerror。与 developer L1（workbench status-card 视图模型纯函数/畸形输入用例）intent 不同层（L1 锁不住 JSX 运行时错/落位/降级渲染），t260904-06 spec-card-dom（spec 卡落位）/t260904-17 行卡面（列表四态）不同面。bundle 陈旧时以「卡不在 DOM」正确变红（归因 bundle_pairs 闸与 t260903-04 bundle-sync）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/playwright/chromium 缺席=ENV_FAIL 点名（KI-036）",
     "node integration/t260911-05/sc_ki048_status_card_dom.mjs", "browser-free"),
    # ---- t260913-03: 每票集测段池排除开关（声明面 apply + 命中被跳池资产强制全跑）----
    # integration 设计段产物（L2/L3 灰盒：真闸 + 真执行器 + mini 注册表夹具，秒级）。
    # 四条 intent 互不重叠：①消费形态矩阵（A/B/E）②例外分支正负锁（D）
    # ③红线对抗（不得吞在册红 / 缩围必须可见）④资产面在真注册表上闭合（独立机械复算）。
    # 与 developer 的 L1 电池分工：彼测入口解析/计数形状（白盒可随实现），
    # 本条测用户可感知的闸行为与机械不变式（绑定公开回执与执行器末行契约）。
    # 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t260913-03-pool-exclude-switch-forms",
     "池排除开关的消费形态矩阵（t260913-03 验收 A/B/E，灰盒 L2，真闸+真执行器+mini 注册表夹具）：声明面打开+每票段传 apply → 被跳池条目不在本轮在册（不计 ran/pass/fail）、汇总点名「本轮跳过池=engine,exclusive（少 N 条）」、INTEG_SUMMARY 的 ran==expected==本轮在册、条件键点名池与条数；声明面在场但不传 apply（巡检/手动/老回放形态）→ 恒全跑（开关不得外溢）；声明面缺省 + apply → 全跑且汇总零新增键（不假造排除面）。断言面=真入口 admin.py call verify_lane 的公开回执 + 执行器末行/汇总契约，不锚内部实现。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260913-03/sc_pool_exclude_switch_forms.py", "ro"),
    ("t260913-03-pool-exclude-force-assets",
     "例外分支：写集命中被跳池资产 → 强制全跑（t260913-03 验收 D，灰盒 L2）：判据纯机械=票面 write_set 与（声明固定资产 ∪ 注册表派生资产）求交非空，命中即不注入排除、被跳池条目回到在册并在回执 forced_by 点名命中资产；正用例覆盖声明固定资产（integration/stage_docker.py）/ 被跳场景文件本身（cmd token 派生）/ 写集目录前缀三形态；负锁覆盖写集不相交 / 空写集（老回放票语义）/ 只命中在册条目文件三形态（绝不误触发）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260913-03/sc_pool_exclude_force_assets.py", "ro"),
    ("t260913-03-pool-exclude-no-false-green",
     "排除不得吞在册红、被跳池红不得计成通过（t260913-03 红线对抗子用例，灰盒 L2）：在册条目红+被跳池条目红时闸必须红且红名单点名在册那条，被跳池那条既不在明细也不计 pass（不在本轮在册）；只有被跳池条目红时本轮不判它但必须点名「少 N 条」+ 汇总排除数如实在案（缩围可见，不是静默通过）。断言面=真闸回执 affiliation 红名单 + 执行器直跑点名行/汇总键。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260913-03/sc_pool_exclude_no_false_green.py", "ro"),
    ("t260913-03-pool-exclude-asset-closure",
     "例外分支资产面在真注册表上闭合（t260913-03 灰盒 L2，独立机械复算）：执行器资产入口 --print-pool-assets 读真注册表且不跑套件；被跳池每个条目 cmd 里的 integration/ 落盘 token（场景文件本身、with_stage.sh 等）与这些场景文件 import 到的共享模块（同目录 / integration 顶层可解析者，含舞台单点 stage_docker.py 与各协议库）逐条都在派生资产集内；非 integration/ token（PY=server/engine/.venv/... 形态）零误收；未知池名在资产入口与真闸两端都非零/红并点名（配错不得静默少跑或静默全跑）。先做有界安全探针（临时 cwd+短超时+杀进程组）防「入口缺席时真跑全量」拖住套件。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260913-03/sc_pool_exclude_asset_closure.py", "ro"),
    # ---- t260913-03 每票集测段池排除旋钮（机械过滤面自证；ro 池=纯 stdlib 秒级）----
    ("t260913-03-executor-pool-exclude-l1",
     "执行器池排除旋钮机械行为自证（t260913-03）：被排除池条目不在本轮在册数（不计 ran/expected，expected=本轮在册且 ran==expected 不变式保持）；点名行「本轮跳过池=…（少 N 条）」原文与两次点名；INTEG_SUMMARY 仅在排除生效时增 excluded_pools/excluded_count 键（缺省键集逐键全等=零新增）；非法 token 剥离+响亮 WARN 且 rc 语义不变；零命中响亮 WARN 不红；缺省路径与 git HEAD 改前执行器在假表上逐字节一致（源码级 A/B）；--print-pool-assets 真注册表派生（未知池 exit 2 点名、cmd token ∪ import 闭包 ∪ integration/ 根共享基建面、环境前缀 token 不误收、非被排除池资产不入面）；既有两条执行器电池在排除 env 继承下照常绿（回归用例）。与 t260904-12-executor-three-state（三态出口契约）/t260910-13-executor-fail-closed（条目完整性）intent 不同面：本条锚池排除旋钮自身",
     "python3 integration/tests/test_pool_exclude_executor.py", "ro"),

    # ---- t260913-04: agent 执行面容器化（macOS 无可用沙箱后端 → 每票容器内执行）----
    # integration 设计段产物（L2/L3 灰盒）。五条 intent 互不重叠：
    # ①引擎接线契约（挂载/env/user/无特权/pin/host 冻结/生产接线棒，hermetic）
    # ②镜像+supervisor 契约（真镜像真跑）③生命周期（常驻/收割/孤儿回收/零残留）
    # ④多仓形态（E）⑤真沙箱负锁（B/C 核心，真 agent 门控）。
    # A/F（真工单全段+计时）由实现段 Step 6 驱动脚本承担，判据钉在本票设计段结果文件。
    # 实现段落地前红属预期（TDD 验收棒），arbitrate/merge 期必须绿；
    # docker/镜像/凭据缺席=ENV_FAIL exit 2（点名构建命令/门控旋钮，无 SKIP）。
    ("t260913-04-wiring-contract",
     "引擎接线契约：docker 形态下传给 docker 的完整 argv 钉死该票泳道为容器可见世界（t260913-04 验收 B/C/D/G+红线 1/2/3/4，灰盒 L2/L3，hermetic）：挂载面=恰好泳道一项（无主树/~/.dsh 全量/docker.sock/他票路径）、env 白名单（DSH_HOME 在、DSH_PERMISSION_MODE 族结构性禁入）、user=宿主 worker uid:gid（容器内新建文件宿主可提交）、无 privileged/cap-add/pid=host/network=host、sandbox_pin 一次性 patch 用字面量 mode:'danger-full-access'+permission defaultPreset:'danger-full-access'（宿主 260914 A 案：容器内全权、隔离由挂载面承担；defaultPreset 缺位=合成缺省不匹配任何预设，dsh boot 拒启）+bash-sandbox 900000 且仅 docker 形态、容器名 sandbar-agent-<ticket>+label 锚票、host 缺省形态零 docker 调用+agent 宿主直跑+结果文件形状不变（存量冻结）、run_worker.sh 显式 export 旋钮（生产接线棒）。断言面=SANDBAR_DOCKER_BIN 注入桩记录的 argv 与泳道落盘物，不锚引擎内部函数。实现段落地前容器面红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260913-04/sc_t26091304_wiring_contract.py", "ro"),
    ("t260913-04-image-supervisor",
     "工程镜像与容器内 supervisor 契约（t260913-04 块 1，灰盒 L3，真 docker 真镜像）：镜像内 dsh 本体 PATH 可解析、node>=22、python3+pytest/temporalio/pyyaml 预装（工单源事故附带发现①）、git/zstd 在场；sandbar-exec 协议真跑：pgid 落盘→按组 kill -TERM 整组消失→退出清档→坏参非零点名（fail-closed 不静默）。这是验收 G 与 KI-009 收割语义在容器形态的物理前提；与 t260913-04-wiring-contract 分工：彼锁引擎传参，本条锁镜像里真跑的终态。实现段落地前红属预期；docker/镜像缺席=ENV_FAIL exit 2（点名 sh server/engine/build_agent_image.sh）",
     "python3 integration/t260913-04/sc_t26091304_image_supervisor.py", "engine"),
    ("t260913-04-lifecycle-gc",
     "容器生命周期：票在容器在/段间收割干净/异常可回收/收口零残留（t260913-04 验收 D/G+红线 3，灰盒 L3，真 docker+引擎 spawn 链直调）：spawn 即 ensure（sandbar-agent-<ticket> running）、agent 桩真在容器里跑（uid=宿主 worker uid、cwd=泳道、env 无沙箱旋钮、spy 经同路径挂载落回宿主）、结果文件/日志落泳道原位形状不变（验收 D）、迟写轮交付后进程树按组收割且 pgid 档清零（KI-009 容器形态）、孤儿容器（label 在泳道亡）被 gc 手工入口收走而泳道活容器不误杀（安全阀）、收尾容器/网络/卷三面零残留。与 t260910-12-herd/t260912-02 生命周期族 intent 分工：彼锁舞台台（compose 工程），本条锁 agent 工单容器。实现段落地前容器面红属预期；docker/镜像缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260913-04/sc_t26091304_lifecycle_gc.py", "engine"),
    ("t260913-04-multirepo",
     "多仓泳道容器形态：每棵成员仓树容器内可写、宿主可见、按树落盘（t260913-04 验收 E+红线 2+D2 降级面，灰盒 L3，真 docker）：两棵成员仓（真主仓+真注册 worktree）挂泳道根下，容器内对根/树A/树B 写入宿主全可见且属主=worker uid、inspect Mounts 源=仅泳道根（成员主树零暴露）、容器内 git status 呈预期失败形态 fatal: not a git repository（有意降级可辨，不误读为树坏）、宿主逐树 settle 直调后 commit 落各成员泳道分支。与 t260913-04-wiring-contract 分工：彼锁单仓接线 argv，本条锁多仓终态与 git 降级契约。实现段落地前容器面红属预期；docker/镜像缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260913-04/sc_t26091304_multirepo.py", "engine"),
    ("t260913-04-sandbox-neglock",
     "容器执行面锁：容器形态下 agent 命令面能用、宿主边界不可达、容器本地可干活（t260913-04 验收 B/C 核心+红线 2，灰盒 L3，真 dsh agent，门控）：正锁=工作区内写成功（不是全拒）；负锁（挂载面守卫）=宿主主树/他票路径在容器里不存在、/usr/local（uid OS 权限）零落盘；正用例（宿主 260914 A 案）=容器本地 /tmp 可写（容器内无 dsh 沙箱拦截）；>60s 命令跑完（D8：bash-sandbox 900000ms；工单源事故附带发现②）；会话档记录 sandbox mode=danger-full-access 与真实拒绝（pin 同时钉 permission defaultPreset，缺位时 dsh boot 拒启）；对抗轮=env 注入 DSH_PERMISSION_MODE=workspace-write、泳道 profile patch 注入 disabled，两条路 pin 字面量都必须仍钉在 danger-full-access 且正锁仍成立；git 预期失败形态（D2）。判据全机械落盘（文件存在性+证据档关键词），不读 agent 自我报告。跑法：缺省=单轮真 agent 基线（闸内默认真验 B/C，分钟级）；SANDBAR_E2E_REAL=1 追加 >65s 长命令子用例（D8）与两个对抗轮；缺 docker/镜像/凭据=ENV_FAIL exit 2 点名（供给面，非产品红）",
     "python3 integration/t260913-04/sc_t26091304_sandbox_neglock.py", "engine"),

    # ---- t260921-05: 单测去 Docker 依赖（host 拆/扫模式闸 + 容器行为全桩化）----
    # integration 设计段产物（L2/L3 灰盒，hermetic 零 docker 零网络）。两条 intent 互不
    # 重叠，与 t260913-04 族分工：wiring-contract 的 host 零调用锁 spawn 执行面（G），
    # lifecycle-gc 锁真 docker 健康路径回收终态；本族锁「拆/扫收口链」的 host 零依赖与
    # docker 形态故障容忍。merge 内联清理收口与 teardown 同走 remove_container 原语，
    # intent 同源不另造链。悬挂超时（daemon 假死 30s）形态归 developer L1 的 0.3s 快测
    # 用例，本族用快败注入（场景秒级纪律+t260920-01 等待预算化精神）。宿主令 260921。
    # 模式闸已随 implement 落地，两条当前即应全绿（红=回归，非预期红）。
    ("t260921-05-host-closeout-zero-docker",
     "host 形态收口/扫尾链零 docker 依赖（宿主令 260921，灰盒 L3，hermetic）：机器无 docker/daemon 假死时跑工单，票首容器扫尾（prepare_workspace 首活动 gc）与票尾收口拆容器（teardown_lane）不敲 docker CLI——SANDBAR_DOCKER_BIN 记录桩日志 0 行（零调用即零 30 秒等待）、拆道回执 ok 且 error 干净（不留「agent 容器回收」脏 warn，收口语义=warns 只装异常面）、拆道+扫尾全程墙钟有界；PATH 屏蔽 docker 变体重跑拆道链同样干净（零调用不依赖桩在场）。与 t260913-04-wiring-contract 分工：彼锁 spawn 执行面 host 零调用，本条锁拆/扫收口链；merge 内联清理与 teardown 同走 remove_container 原语不另造链。断言面=记录桩日志+回执 error，不锚引擎内部函数。模式闸已随 implement 落地，本条当前即应全绿（红=宿主令回归，非预期红）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-05/sc_t26092105_host_closeout_zero_docker.py", "ro"),
    ("t260921-05-docker-closeout-fault-tolerate",
     "docker 形态收口/扫尾故障容忍与语义冻结（t260921-05，灰盒 L3，hermetic 全桩）：daemon 故障（rm/ps/info 快败注入）时 teardown 回执 ok=True 收口不被拦、「agent 容器回收」点名异常面、绝不吞成「已拆」、remove/gc 幂等不外抛；docker 模式下 SANDBAR_DOCKER_BIN 可注入且调用形状含 rm -f sandbar-agent-<ticket>（模式闸不得误伤 docker 形态）；daemon 缺席时 gc 诚实降级留痕（「docker 不可用，跳过容器扫尾」容忍 note）；桩切成功态后收口回执干净（成功=零 warn 的 warns 契约）。与 t260913-04-lifecycle-gc 分工：彼锁真 docker 健康路径回收终态与安全阀，本条锁故障注入容忍语义；悬挂超时形态归 developer L1 0.3s 快测，不真等 30 秒。容忍语义已存在当前即绿；模式闸落地后必须仍绿（冻结守卫）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-05/sc_t26092105_docker_closeout_fault_tolerate.py", "ro"),

    # ---- t260914-01: 结算面三修（判脏含老名协调目录 / 空提交正常收口 / 多仓清单走真源）----
    # 三条 intent 互不重叠：①老名泳道正常收口终态与产物不丢 ②异常/边界态的可辨性与
    # 响亮性（空提交 vs 真失败）③多仓泳道协调目录名的写读姿态（新泳道不生老名、存量
    # 老泳道不翻转、读侧对存量位置零回归）。与 developer L1
    # （server/engine/tests/test_t260914_01_settle_lane_stance.py）分工：彼测纯函数/夹具级
    # 形状（含 monkeypatch 注入），本条测 activity 级真实 git 态终态（真 worktree、真
    # index.lock/hook 注入、逐仓 scope）。实现段落地前红属预期（TDD 信号），arbitrate/
    # merge 期必须绿；引擎 venv/temporalio 缺席=ENV_FAIL exit 2（直调 activity 无 stdlib 替代）。
    ("t260914-01-settle-old-lane-stance",
     "老名协调目录泳道的 settle 姿态（t260914-01 验收 B，灰盒 L2，真 git 夹具+直调 settle activity，零 docker 零 Temporal，秒级）：**只产出协调目录产物的段必须正常收口**——settle 返回可读回执、零代落盘 commit、**绝不抛异常**（抛异常=Temporal 判「agent 活动故障」→ 工单 blocked，而 agent 产物其实是好的=dengzhufpv/t260911-07 每次重跑卡 create_plan 的真形态）、结果文件零丢失；判脏面不含老名/新名协调目录条目（两名并存/空目录边界同判）；真实写集改动照旧代落盘且 commit 内容不含协调目录（不得把真改动吞成「干净」、也不得把过程物写进历史）；多仓形态下**逐仓**收口（根树+成员树各有协调产物，两树均零 commit、两树产物均在）。与 t260911-03 系（路径闸拒绝面）零重叠（本条不启用闸）；与 t260913-05 系（拆道回执/残留）零 merge 面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260914-01/sc_settle_old_lane_stance.py", "ro"),
    ("t260914-01-settle-empty-staging-locks",
     "空提交与真失败的可辨性负锁（t260914-01 验收 C，灰盒 L2，真 git 夹具+直调 settle activity）：「判脏非空但撤下协调目录后暂存区为空」是正常工作态——显式注入**修复前判脏口径**重演现场形态（注入点带非空转负锁：先证判脏确实非空、含老名目录条目，否则用例白跑）→ 回执可辨（含空暂存标记串、与干净回执文案不同）、**不得抛 RuntimeError**、零 commit、产物零丢失；同一注入世界下真实改动仍照旧代落盘（空提交分支不得吞真改动）；反向子用例=**真失败必须响亮**——真实 git 态注入（gitdir 内 index.lock 在场 → git add 失败；pre-commit hook 拒绝 → 暂存非空而 commit 失败）一律照旧抛异常且报错点名失败的那一步（add/commit），不吞成回执、不假落盘；三态文案（干净/空提交/代落盘）互不相同。与 developer L1（monkeypatch _git 注入）不同层：本条锚真实 git 态与公开回执可辨性。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260914-01/sc_settle_empty_staging_locks.py", "ro"),
    ("t260914-01-multirepo-dir-stance",
     "多仓泳道协调目录名的写读姿态（t260914-01 验收 D，灰盒 L2，真 git 夹具+直调 prepare activity，零 docker 零 Temporal，秒级）：**新建多仓泳道不再诞出老名目录**——清单落解析真源位（新泳道=新名协调目录）、清单条目与明细逐条一致、两树均为所属仓已注册 worktree；prepare 幂等重入位置不变；**存量老名泳道保持粘滞**——重进 prepare 原地复写、不诞出新名目录、不翻转在飞票（本修不得依赖任何手工迁移）；**读侧对存量位置零回归**——老名清单照旧可读（含「杂散新名目录＋老名清单」过渡形态仍取到清单、读动作零副作用），判定不放宽（清单损坏照旧 RuntimeError、无形单仓照旧回落 1 scope）。与 t260910-08/t260911-04/t260913-05 真链场景分工：本修只让那些场景的清单锚点跟随真源（intent 不变），本条守目录名姿态本体。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260914-01/sc_multirepo_dir_stance.py", "ro"),

    # ---- t260915-01: 详情数据面（受阻陈旧态清除 / 结构化红灯明细 / 轮次与分支维度）----
    # 两条 intent 互不重叠：①回执缝正负例三段（生产/消费/兼容，implement 段交付、本段
    # 登记；其 L1 正例已用 5 探针>cap 锁「清单全量不截断」）②详情数据面全链旅程（L3
    # 真台真票）。与 t260911-03 系（闸的 settle 执法终态）、t260911-05（merge 分类+
    # KI-048 状态卡）分界见各条 intent；developer L1（test_t260915_01_detail_face
    # 纯函数矩阵+源码锁）不同层。实现段落地前红属预期（TDD 信号），arbitrate/merge
    # 期必须绿；temporalio/docker/舞台缺供=ENV_FAIL exit 2 点名（三态契约）。
    ("t260915-01-detail-red-refusal-end2end",
     "闸拒绝结构化明细回执缝端到端（t260915-01 ②，灰盒 L2，真 git 夹具+直调 settle 单点，零 docker 零 Temporal）：路径闸拒绝落盘时**活动回执**除人读 note 外带结构化明细 gate_refusal——三缝各守一段：L0 兼容子用例=三处 refusal 形参缺省 None+StageResult/SettleLaneResult.gate_refusal 缺省 None（既有直调场景逐字不变、老回执重放不破）；L1 正例=acceptance_walkthrough 注入 5 个产品代码越权探针（>cap）→拒绝回执与判定/note 一致（reason_code 与 note 内嵌码一致、files 与闸判定清单全量相等且 5 探针一个不丢——_fmt_files cap 只许作用人读 note 文本，结构化面不得丢文件、evidence 与 note 逐字相同、check_id 点名段、red+next_action 在场、0 新 commit）；L2 反用例=写集内正常落盘→零明细收集不误挂；L3 受保护路径子用例=改已存在真源 verify.yaml→protected_path+人话名「受保护路径闸」；L4 接线子用例=真回执+真 refusal 喂 _apply_settle_note→挂载逐字不走样（非自造 dict）；L5 消费子用例=workflow 侧 _pin_agent_refusal 消费真回执→blocked_detail 结构键齐（check_id/item/red/reason_code/files/next_action/evidence）。从真实 settle 判定点驱动=接线断裂（dict 建了没传/传了没挂）必红（KI-046/049 反面）。与同票 journey 条分工：本条锁回执缝与清单保真（单段级），彼锁全链旅程与轮次/分支维度（票级）；与 t260911-03 系（闸执法终态 note 文本/0 落盘）intent 不同面；developer L1 纯函数矩阵不同层。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git/temporalio 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-01/tests/sc_detail_red_refusal_receipt.py", "ro"),
    ("t260915-01-detail-face-journey",
     "详情数据面全链旅程（t260915-01 ①②③验收的用户旅程面，灰盒 L3，真 docker 台+夹具仓桩脑链+工单专属 worker）：真票造真实闸拒绝（create_plan 运行中写越权探针，真判定器选必拒路径）→ blocked → 票面受阻原因=闸拒绝回执（不是与 stage_state 矛盾的「活动故障」脏文案）＋blocked_detail 结构化明细（reason_code 与真判定一致/全量 files 点名探针/next_action/red/check_id/evidence=回执原文）＋正规入口 ticket.py show 投影面同可达（跨组件缝）→ retry_qc 唤醒 → blocked_reason 清空+blocked_detail 清空（陈旧态清零、与 stage_state 自洽）而 timeline 原 blocked 条目仍在（机械断言，留痕不丢）+retry-requested 留痕 → 轮次与分支维度：timeline 条目带 gen、分叉期条目带 phase、meta.parallel_phase 两个分叉点各采样一次（parallel_impl_design/arb_acc_parallel，stub 拉宽窗口）、离场相位键同删、snapshot.gens 读 段→第几轮（重跑后 create_plan=第 2 轮）、handoff 条目带 gen；审计钩子自证零生产面接触。前置步（stdlib 恒跑的契约锁，docker 台外快速点名防三分钟白跑：门判定只在 _init 求值一次、snapshot 函数体零 workflow.patched、_blocked wake 清两字段且 _mark blocked 留痕写点仍在、_enter 清 detail、snapshot 透传面不回归+gens 段、set_parallel_stages 相位键、ticket.py 投影白名单带 gens——同一批源码锁的完整矩阵归 developer L1，本条只作旅程前置卫兵）。门对新部署新建票恒 True——blocked→唤醒清态断言只在新建票上成立（C8 前提）。与同票 end2end 条分工：彼锁回执缝与清单保真（单段级），本条锁全链旅程与轮次/分支维度（票级）；与 t260908-01 三条（超限复活/重放兼容/pause 旅程）intent 不同面；t260911-05 不碰 merge 面；t260911-03 只当判定器 oracle 造真实拒绝。docker/镜像/舞台/台库缺供=ENV_FAIL exit 2（前置契约锁仍恒跑）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-01/tests/sc_detail_face_journey.py", "engine"),

    # ---- t260914-05: 收口迁表裁决（删仓内旧路由表+缺表不静默+引用点退场）----
    # 四条 intent 互不重叠（integration 设计段产物，L2/L3 灰盒，全零 docker 零模型成本）：
    # ①取表来源封闭性+消费方点名可见（260914 现场 A 毒面泛化：未声明/坏声明/项目主目录
    #   同名旧表诱饵/跨项目串扰/表在场无命中）②告警内容指纹的诊断效力（内容敏感/稳定/
    #   跨进程一致/日志一致——指纹撒谎则验收 1「可机械断言」形同虚设）③隔离测试台自声明
    #   （现场 B 根因回归网：85 断言全绿仍放过真 agent 段 429 的盲区）④生产两项目声明面
    #   哨兵（验收 5：收口票最易出的回归是顺手伤生产）。
    # 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
    # temporalio/PyYAML/机器注册表缺席=ENV_FAIL exit 2（点名，无 SKIP）。
    ("t260914-05-routes-no-silent-pickup",
     "兜底表退役后的取表来源封闭性与消费方可见性（t260914-05 验收 1/2，灰盒 L2/L3，真 spawn 缝隙+夹具注册表注入，零 docker 零模型成本）：未声明/声明面坏（文件缺失/内容坏）的项目 agent 绝不被钉到任何没人声明的表——引擎仓内旧表、项目主目录里恰好同名的过期表（现场 A 毒面泛化）都不许被捡；无表现场与「表在场但该角色无命中」现场都必须点名可见（禁静默回落 profile 默认），两因文本可辨；项目间不串（一个项目的表不得影响另一个项目的 spawn）；绿锚=声明面好时表内容原样生效（不许为防过期引入内容新鲜度判定＝查表语义零改动红线）。与 t260910-14-routes-truth-fallback（真源随声明走+分层兜底留痕，随本票改口径）与 t260903-03-paths-failclosed-red（路径锚点红传导/roles 面）intent 不同面：本条锁兜底退役后的来源封闭性+消费方点名。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio/PyYAML 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260914-05/sc_routes_no_silent_pickup.py", "ro"),
    ("t260914-05-routes-fingerprint-diagnostics",
     "告警内容指纹的诊断效力（t260914-05 验收 1「含表路径与内容指纹（可机械断言）」，灰盒 L2，性质口径不锚摘要算法——换 sha256 为别的摘要不得打破本条）：指纹必须真能标识当时读到的字节——同文件两次解析同值、换内容变值、跨进程（子进程）同值（挡 hash()/id()/时间戳型指纹）、坏表（字节可读解析失败）仍给指纹且与好版本可辨、无字节两态（decl_missing/file_missing）不得拿常量冒充指纹；日志不撒谎：告警文本里的指纹=返回值指纹、无字节态告警仍点名路径。与 t260910-14/t260902-07（随本票改写，钉指纹在场性）intent 不同面：本条钉指纹的诊断效力。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；PyYAML 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260914-05/sc_routes_fingerprint_diagnostics.py", "ro"),
    ("t260914-05-routes-isolation-bench-selfdecl",
     "隔离测试台自声明路由表（t260914-05 验收 3 的根因回归网＝260914 现场 B，灰盒 L2，零 docker 零模型成本秒级）：e2e 夹具注册表条目必须自声明 paths.model_routes 且表可用（存在/可解析/implement 段 developer 条目 provider+model 非空——「先做隔离台自声明再删表」顺序的机械判据，防把「静默用错」换成「无表」），解析走声明面且路径落夹具根内（引擎仓退场），provider 在本机供应面（settings.yaml 或出厂适配器）有名（review R4 面：防表里写个容器没配的 provider 再撞 401）。与 t260913-04 五条（容器执行面）intent 不同面：彼锁执行面，本条锁夹具注册表的声明面契约——85 断言全绿仍放过现场 B 的盲区由本条闭合。直调 run_real_ticket_e2e.build_project（模块级无副作用，import 安全）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；PyYAML/引擎 venv 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260914-05/sc_routes_isolation_bench_declares_table.py", "ro"),
    ("t260914-05-routes-production-declarations",
     "生产两项目声明面照旧生效+引擎仓退出取表来源（t260914-05 验收 5，灰盒 L2 只读探针，零写零 docker）：sandbar/dengzhufpv 注册条目仍声明 paths.model_routes、解析 state=ok、roles.developer provider/model 非空（性质断言不钉值——模型是运行时可调项，260910 裁决心智）；解析路径在引擎仓之外（真源机器级不变式）；未登记 key 走三态口径（decl_missing/无表/路径不落仓）＝引擎仓对任何人不再是取表来源；只读 pledge（机器表字节摘要探针前后一致）。条目在场但声明缺失=产品红（契约被破坏），机器注册表/项目条目缺席=ENV_FAIL exit 2（点名）。与 t260902-07 表守卫（随本票改写，单项目表静态性质）intent 不同面：本条锁生产注册面端到端解析拼装+不许伤生产哨兵。本条落地前后都应绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260914-05/sc_routes_production_declarations.py", "ro"),

    ("t260915-04-write-set-root-entry-gate",
     "建票期拒收「整仓根形态」写集条目（t260915-04，KI-092 事故回归面，宿主 260915 口径一律列举，灰盒 L3，真 git 夹具+真实建票双入口，零 docker 零真 Temporal）：多仓混合形态（根仓+成员仓=dengzhufpv 现场）写集条目==成员仓根（'repo_a' 裸仓名与 'repo_a/' 尾斜杠两形态归一同判）→正规入口 ticket.py create 与裸入口 client.py ticket-start 均建票即拒、点名条目且文案含列举式改法关键词（整仓/逐个子目录/.gitignore——锚关键词不锚整串措辞）；仓内子目录/文件/'integration/'（归根仓）照常受理（放行对照子用例防判别面失真：拒收与「放行后败于连接」可辨）；单仓项目 '.' 建票拒收（与运行期闸同口径，经保险丝A 归属解析可达）、'*'/'**'/空串/纯空白/含哨兵字符样本建票期不再判合法（拒收并点名）、'..' 段既有拒收不因新判定失序、目录形子目录条目（'server/'）不误伤（存量兼容）；显式 worktree 不能绕过（保险丝A 传播同拒——判据是写集归属不是派生路径）；畸形输入（写集=字符串逐字符假清单形态）拒收点名须为列表；边角=成员仓名恰为 integration 的项目建票不炸（自动化并入撞闸被跳过）；纵深=legacy/手写载荷形态（显式明细在+根形态条目漏进）merge 期保险丝B fail-closed 红灯点名不静默。与 t260910-03-formal-entry-fuses intent 分界：彼守「成员仓子目录写集×明细缺失」双保险丝与正规入口补传（其写集全为仓内条目，新口径不翻红），本守「条目形态==仓根/项目根」的建票期形态闸（明细在也一样拒）；与 t260907-06/t260912（归属三态/嵌套仓 fail-closed）、t260914-01（泳道目录姿态）、notes-write-gate/t260904-18（建票口其它门）不同面；developer L1（resolve/validate 纯函数矩阵）不同层。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；引擎 venv/temporalio 缺席=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" integration/t260915-04/sc_t260915_04_write_set_root_entry_gate.py", "ro"),

    ("t260915-08-board-rows",
     "引擎工单板收录巡检票的行面契约（t260915-08 验收①，灰盒 L2 离线黑盒，stub temporalio+过滤串忠实桩——「过滤扩展收 InspectionPeriodicWorkflow」本身是被测行为，桩按 WorkflowType/ProjectKey/EpicCode 原子真过滤）：kind=inspection 巡检行字段齐（实例/期号/段/发现数/人门态——待签判定不依赖 face.human_gate 签字前常态缺键，review 打回4 行为面）；行 engine=inspection 标记（不给 dev-lane 管理操作位，坑B）；created 派生 wf.start_time（坑D）；三类僵尸（test-face 改名/suite-drill 未声明/mechanism-face 停用）不上板且零 snapshot 查询（查询前白名单预过滤=坑C，白烧负载=0）；闭合行 Flooding 有界（R8：超窗/close_ts 缺失不上板、窗内闭合=完整巡检形非匿名、result() 失败=显式降级行不消失）；默认列表行集合零变化+dev-lane 行键集 parity（R9，t02 族零扰动）；声明不可读=显式降级标记不株连 dev-lane；畸形快照（非 dict/face 缺/findings 非 list）不崩不株连；ticket-query 巡检分支 engine 在位+票面进 ticket 面+gate_id 单点（坑A/KI-025 族回归：缺了就被 _v2_query 谎报「工单不存在」）+dev-lane 查询键集 parity。与 t02（dev-lane RUNNING 降级面）、t260903-06 no_lie（dev-lane kind 分级）intent 不同面：本条守巡检分支本身。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；纯离线无 ENV_FAIL 子用例",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-08/sc_inspection_board_rows.py"),
    ("t260915-08-board-ui",
     "工单板巡检行 UI 渲染层（t260915-08 验收①「3199 隔离台真点」+②③④，灰盒 L3 browser-free，镜 baselines/sc_lane_parallel_dom.mjs 两层式，取舍见方案 §3.5 镜B）：S0 build-contract=双 bundle 同步+巡检锚点（合流端点 wf/inspection/tickets/gate 常量/签什么段/awaiting_gate 消费）+node.ts sign gate 透传源锚（写死空串=巡检签字必被拒收）；S1 真浏览器 API 桩真点——巡检行上板且实例/期号/发现数/段可见、data-state=waiting+黄底计算样式（mock ⑤H「等你一眼可见」核心诉求）、「去签字→」钮、点行下钻时间线/发现摘要/报告路径/签什么、去签字锚点落签什么段、签字 POST body 带 gate=inspection-close&decision=approve（零旁路的数据面）、畸形详情回执零 pageerror。与 t260901-09 泳道图 baseline（并行渲染）intent 不同面：本条守巡检行卡/详情下钻/签字通道。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；console/playwright-core/chromium 缺席=ENV_FAIL exit 2 点名（不假红不假绿）",
     "node integration/t260915-08/sc_inspection_board_ui.mjs", "browser-free"),
    ("t260915-08-sign-journey",
     "巡检人门签字链路真签收口（t260915-08 验收①「真签一张沙箱巡检票收口」+④零旁路，灰盒 L3 真台真票 exclusive，镜 t260905-03 journey+lib_inspection，取舍见方案 §3.5 镜C）：夹具声明+进程戳实例开真票→close/awaiting-human 常态 face 无 human_gate 键（签字前常态契约，待签判定走 stage_state）→错 gate 签=workflow 拒收 gate_error 可读且票留门内→agent 自签拒收（对的 gate 也不放）→对 gate 经工作台同款通道（client.py ticket op=sign——node.ts op=sign 调的即它）真签→closed+human_gate 落面（who 对）+落账在（out/inspection/<票号>.json）；附带签字前 ticket-query engine/ticket 面（gate_id/instance_id/period/report_path/title，坑A 活体半边）；板面收录子用例——收口票进 ticket-list{kind:inspection}（完整巡检形+inspection_filter 白名单回执，SANDBAR_INSPECTION_DECL 注入声明，规格① 真台端到端）。与 t260905-03-period-journey（巡检全链旅程：发现落面/心跳证明/双实例不串票）intent 分工：彼守链路质量，本守「签字通道把票签收口」；私有队列+StageWorker 自供给（生产 worker 不注册本 workflow 的竞态消除面照搬）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；temporalio/共享测试台缺席=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-08/sc_inspection_sign_journey.py", "exclusive"),

    ("t260915-09-epics-client-project-wire",
     "立项单视图跨项目取数走客户端真路径（t260915-09，KI-057 client 穿参收口=当年验收矩阵缺 client bundle 真路径维度的补维度，宿主实报 dengzhufpv 界面看得见 sandbar 10 张立项单的 fixture 化，工单验收①）：bootConsole 隔离台 fresh boot 挂泳道树+双项目注册表（fpv 夹具根自植 fpv-repo-split 一枚/sandbar=引擎仓）——点 dengzhufpv 项目行立项单图标列表=仅 fpv-repo-split 单一、切 sandbar=引擎仓全集、再切回=仍单一（切换重拉=列表随项目重取的用户可感知面）；详情/8s 轮询聚合/状态写全链真点走查（状态写「已保存」在场面+落夹具根文件字节在案=写路径真穿参，落引擎仓=串台写现形）；wire 面反空转断言=旅程收集的全部 /api/epics* 请求 project 参数恒非空（零裸调，收集面<4 fail-closed 不许空转咬不住）+状态写 POST 相位点名 project=dengzhufpv+详情态跨 8s 轮询窗聚合至少再一拍；http 前置子用例=无参回落引擎仓与 ?project=sandbar 同根同集（回落语义保留的负向证明；性质断言不钉真实仓清单——仓库每票必变钉清单必 rot）。写足迹=场景私有临时夹具根，零 3099/7233/3199 接触，退出全终态回收；playwright-core/浏览器/隔离台依赖缺失=ENV_FAIL exit 2 不写 SKIP（三态契约，KI-036/046 家族）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。与 t260907-11 三场景（进程内 apply+mock req/res 的 host 解析契约面）intent 不同层——彼锁 host 面，本条锁客户端 bundle 真请求路径（当年漏的正是这半）；与 t260903-04-client-bundle-sync（盘上特征词卫生面）不同面；与 t260910-10-docs-project-anchor（文档视图组件）intent 不同面",
     "node integration/t260915-09/sc_epics_client_project_wire.mjs", "ro"),

    # ---- t260915-05: 工单详情观测面重设计（真泳道图+人话状态卡+红灯翻译层，KI-019/027/048 族）----
    # 两条 intent 互不重叠：①engine 池三红旅程（merge 红/人门/关单的数据面+跨组件缝，
    # 路径闸拒绝子用例归 t260915-01 journey 防重复）②browser-free 池 DOM 对拍（渲染面九子用例，
    # 数据全桩）。与 t260911-05（merge 分类+KI-048 红卡 DOM 四件）、t260901-09（现行步骤条
    # 并行双亮，本条 L7a 反向守其降级回落）、t260915-01（详情数据面旅程）分界见各条 intent。
    ("t260915-05-detail-lane-reds",
     "详情观测面三红旅程（t260915-05 验收①③，灰盒 L3+契约锁，真 docker 台+夹具仓桩脑链+工单专属 worker）：一张真票走完 mock ①③ 完整用户旅程——①merge_check 失败分支：越写集探针提交进泳道分支（场景直构探针路径——判定器=merge_check 的 verify_lane_code 全量在场；不借 t260915-01 的 judge 探针机制：那是拒绝子用例造法，会把越界路径写进 create_plan 结果文件触发 settle 路径闸，票死在段上 merge 失败分支不成立；探针窗口=桩拉宽的并行分叉窗）→verify_lane_code 红（reason_code=verify_red）→非冲突红转 blocked，blocked_detail={check_id=verify_lane_code,red,reason_code,files 列表,next_action,evidence 点名越界文件（G2 按文件名可追查）}+gate_runs 尾轮红（轮次带数据源）+正规入口 ticket.py show 投影面同可达（跨组件缝）；②人门子用例：人 revert 探针+retry_qc→merge_check 第 2 轮全绿（gate_runs 红→绿两轮留痕=逐轮格真实数据）→merge 人门 awaiting-human：human_context.merge.context_text+stage_acceptance 在场（蓝卡「签什么」数据源）、blocked_detail 已清（R2 生命周期）；③关单子用例（KI-027 关单半）：正规入口 op=sign approve→落账 COMPLETED→ticket.py show 经 result() 终态快照仍可读 timeline/gens/gate_runs/topology 全套，topology 过投影白名单可达（引擎→ticket.py 跨组件缝：白名单缺 topology=快照半到不了 UI，本断言红点名）且 merge kind=human（人门虚线圈数据源不灭）。stdlib 契约锁（docker 台外恒跑，通道锚定不锚内部名）：list 通道拓扑导出结构（merge kind=human+两组成员==run() 两真分叉+组相位键==meta.parallel_phase 契约串+ui_evidence optional 注记+边含单向流末端）、SANDBAR_FIXTURE_TEMPLATES 门出没（fixture-two-step 行带线性 topology=渲染器通用性对拍通道；无门不出列=收窄守卫零扰动）、snapshot 透传 topology（终态快照同源）、投影白名单带 topology。分工：路径闸拒绝子用例不在此造（t260915-01 journey intent 本体，零重复断言）；t260911-05 锁 merge 分类与红卡 DOM（verify_red 族非其分类面）；t260908-01 系锁仲裁超限语义；t260912-03 锁 authorize 通道（本条只用 plain sign 正规入口，降级锚=sign 面有出入时该子用例断言到 awaiting-human 为止并点名，不造假绿）。借用清单（岗位纪律）：借 t260915-01 lib_detail_journey+t260908-01 lib_ki061 台架——带过来 tempfile 夹具仓/专属 worker 双前缀队列/admin.log 钉临时目录/审计钩子/TERM→KILL 收尾，不带 journey 的 blocked→唤醒清态断言、不带 judge 探针（理由见失败分支）；夹具仓分支名归一 main（_merge_base_ref 硬编码 merge-base main——不归一=merge_base_failed 环境性假红）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/镜像/舞台/venv 缺供=ENV_FAIL exit 2（锁已跑）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-05/tests/sc_detail_lane_reds.py", "engine"),
    ("t260915-05-detail-lane-map-dom",
     "详情观测面 DOM 对拍（t260915-05 验收①②③渲染面，灰盒 L3，隔离台真浏览器+API 桩，3099 零接触）：S0 build contract（twin bundle 同步+泳道图/词条表锚点在 bundle+buildLaneMap 纯模型冒烟）+S1 真 DOM 九子用例——L1 真泳道图：拓扑在场时并行双道虚线框×2（implement∥design_integration_tests、arbitrate∥acceptance_walkthrough）+人门虚线圈落在 merge 节点+节点标签全部来自拓扑；L2a/b 红灯翻译层：verify_red 与 main_dirty 两族同组件出不同人话主文案、绝不冒裸引擎码（表驱动断言的用户可感知面）、结构化 files 点名到卡面 chips、files 空不捏造 chip（callout C 原话）、原始日志 <details> 折叠展开见 evidence 原文；L3 人门蓝卡：awaiting-human 卡变蓝列出「签什么」=human_context.merge.context_text+stage_acceptance+绿 gate_runs 三源；L4 轮次带：create_plan 三轮逐轮格 hover 出该轮打回原因、×N 徽章在、节点不因返工重复（单向流）；L5 关单可见（KI-027）：closed 票同组件全图+轮次带仍在（拓扑走模板导出通道）；L6 渲染器通用性：fixture-two-step 线性拓扑同组件渲染、标签来自拓扑、DOM 零 dev-lane 业务词；L7 降级锚：拓扑缺席回落现行步骤条（t260901-09 双亮面零回归）+畸形 topology/gens/timeline 不炸；L8 检查明细区：gate_runs 逐轮逐条 ✓/✗+item+detail、红行点名文件与状态卡文件清单联动、<details> 展开见该轮 detail 原文；P 卫生子用例=全旅程零 pageerror/console.error。数据全桩（list/detail/workflows 三路由，契约形状={template,name,nodes[id,label,role,kind,optional?],edges,groups}——契约漂移=红点名）。分工：t260911-05 锁 merge-dirty 族红卡四件 payload→pixel（本条不复断其形状）；t260901-09 锁现行步骤条并行双亮；t260915-01 锁数据面引擎半（本条数据全桩）；developer L1（lane-map-model 纯函数矩阵/status-card 词条表 UT）不同层——L1 锁不住 JSX 运行时错/落位/降级渲染。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 点名）",
     "node integration/t260915-05/sc_ticket_detail_lane_map_dom.mjs", "browser-free"),

    # ---- t260915-17: 「文件行=链接」本票时刻只读查看器（mock 260904 标注 D 落地）----
    # 两条 intent 分工：①读取面契约（时刻口径语义×fail-closed 铁律×定位正确性，真 git
    # 夹具 micro 回放+真票逐字对照）②查看器/详情链接化契约（横幅锚×零编辑控件×bundle
    # 一致，离线结构锁档）。与 t260915-05-detail-lane-map-dom（详情渲染面对拍）、
    # t260901-13 灯箱（图片证据灯箱，本票=文本时刻版查看器）、changes 系 diff 场景
    # （diff 语义，本票=单文件时刻版语义）intent 不同面。
    ("t260915-17-ticket-time-file",
     "本票时刻读取面契约（t260915-17 验收①②③，灰盒 L3，真 git 夹具一仓全形态 micro 回放+真票逐字对照，零 docker 零台面）：settle=收口提交版逐字=git show——squash 形态 lane/<id> 只在 message body（「来源 lane/<id>」；真票 t260915-05 实证 subject 不含 lane/<id>，定位必须匹配完整 message）、merge 形态在 subject、teardown 残留分支形态在分支 tip；短 id 不命中长 id 票收口提交（changes.ts --grep 子串留档缺陷的注入回归：先 settle t260915-1 后 settle t260915-17 的 log 序）；fail-closed 铁律=在飞票（dispatched/rework，分支在场与否不影响）／泳道拆且无收口提交／路径不在该版本一律 200+ok:false 人话点名且响应绝不含工作树诱饵内容（回落=把「现在」冒充「本票时刻」）；base=基点版逐字、未登记/无效 ref 人话、与在飞无关（时刻=定值）；current=唯一工作树口径；畸形路径（../、绝对、反斜杠、空）与未知 mode 人话不抛；二进制不透传 NUL 乱码、大文件 2MB 封顶+truncated 在场；结构锁=host/shared 计算核零写性 git 子命令字面量（worktree 行级 list 白名单）+端点注册 tickets/<id>/file 形态与非 GET 405 分支在场；真票子用例=本仓历史真票 t260915-05 settle 读数与 git show 逐字相等（场景独立复算定位作对照真源）。驱动=直 import 方案承诺宿主读面模块（t01 同款），导出面按「恰一个 async 函数」探测+调用形状协商，实现缺席/签名漂移=FAIL 点名。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git 缺席=ENV_FAIL exit 2",
     "node integration/t260915-17/sc_ticket_time_file.mjs", "browser-free"),
    ("t260915-17-ticket-time-viewer",
     "本票时刻查看器与详情链接化契约（t260915-17 验收①③，灰盒 L3，离线结构锁档，3099 零接触）：横幅契约锚在场（data-testid=\"ticket-time-banner\"+人话文案「🕰 本票时刻 · 只读」+「跳到当前版」小链，mock D 原话）；跳到当前版接线=current 口径与横幅渲染同域（点击切当前版且横幅消失）；零编辑控件=查看器域无 textarea/contentEditable/保存语义（只读刚性，写路径仍归编辑器/agent——mock 边界重申原话）；详情文件行=链接（状态卡 sc-file 邻近可点语义）+「背景引用」行组按 refs 条件渲染（mode=base）；Escape/遮罩关闭接线在场（EvidenceLightbox 资源终态家族）；bundle 重建一致=client 源契约锚同批出现在 lib/client.cjs|js 产物（改源忘重建的静默穿透面，t260903-04 bundle-sync 同族）。分工：真点击/真渲染 DOM 子用例留隔离台 stage_docker 手法（同 t260915-05-detail-lane-map-dom 分层），本条红语义=契约锚缺席/接线断/未重建不判环境；与 t260901-13 灯箱 intent 不同面（彼=图片证据灯箱，本=文本时刻版查看器）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260915-17/sc_ticket_time_viewer.mjs", "browser-free"),

    # ---- t260915-19: 左栏收录巡检票（t260915-20 落仓后 v2 分拣制口径）----
    ("t260915-19-sidebar-inspection-ui",
     "左栏收录巡检票 UI 面（t260915-19 验收①②③④，灰盒 L3 browser-free，镜 t260915-08-board-ui 两层式；t260915-20 落仓后 v2 分拣制口径=项目会话授权改口，取舍见方案 v2 §1）：S0 build-contract=双 bundle 同步+左栏锚（wf/inspection/tickets 端点串/sidebar-inspection-head/sidebar-inspection-degraded 两个 data-testid/data-engine=inspection 黄调等值选择器——不锚易漂移文案字面，KI-051 语义锚）+node.ts 巡检 502 原文透传源锚（t260910-04 R3，降级横幅原文真源）；S1 真浏览器 API 桩（自带 /wf/projects 桩=项目组确定性渲染，不依赖台面真实注册表；数据只桩 API 边界，浏览器/bundle/React 全真，宿主 3099 零接触）——①分拣归位：有 SA 身份巡检行进对应项目组（走爬组头 project dot 判归属，组容器无类名=绑浅）②反沉底全序烟测（t260916-15 契约变更配套改写：夹具 ts 拉开断言三行全序 INS_A→DEV_A_WAIT→DEV_A_RUN=等你层（级内 updated_ts 倒序）→在跑层，两行相对序分不出级内倒序是否生效故断全序，「巡检票恒沉底」不得回归；含收口行/兜底组序的全矩阵归 t260916-15-sidebar-merged-sort-ui 不在此重复）③行1 标题「巡检 X · 期 Y」+行2「等你签字 · 发现 高x/中y/低z」与端点一致（inspection-face 既有词表零新词表）④无身份老票进「巡检」兜底组显式可见且不落任何项目组（不静默丢失）⑤零 dev 票项目组由巡检行呈现、无「无进行中工单」占位（空态语义）⑥等你黄调真机计算样式（巡检 waiting 行上漆+dev 等你对照行不上漆=左栏项目行零变化反断言，KI-055 台面绿真机红家族）⑦点巡检行→inspection-face 同组件锚（与中列同抽屉，零新面）⑧降级子用例：端点 ok:false→左栏横幅显错误原文子串（KI-051 断子串不锚整句）+上拍快照行保留（不吞成空列表）+错误文案不进数据字段（KI-018①）⑨全旅程零 pageerror。intent 分界：与 t260915-08-board-ui 不同面——彼守中列板面巡检行/详情/签字通道，本条守左栏分拣制（项目组归位/兜底组/反沉底烟测）/左栏等你黄调/降级显式性；与 t260903-07-click-no-chat-switch 不同面（彼守点行不切会话，本守左栏巡检行的存在与行为）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；stage console/playwright-core/chromium 缺席=ENV_FAIL exit 2 点名（不假红不假绿）",
     "node integration/t260915-19/sc_sidebar_inspection_ui.mjs", "browser-free"),
    # ---- t260915-20: 巡检分项目建模（声明带项目身份 + 起票盖 ProjectKey SA + repo_root 按项目注册表解析）----
    # 同票双场景不同层（参照 t260915-12 双半先例）：①离线声明门（ro 池，纯 stdlib
    # 恒可跑）②真链路用户旅程（exclusive 池，共享测试台写真票真调度）。intent 分工
    # 见各自登记行。
    ("t260915-20-decl-project-identity",
     "巡检声明的项目身份门 fail-closed 契约（t260915-20 交付④，灰盒 L2/L3 离线子用例，纯 stdlib 零 env 依赖）：实例级 project_key 成为声明身份字段后——启用实例缺 project_key 拒收且回执点名实例 id 与「project_key/项目身份」事由（无项目身份的巡检=无主票，绝不静默回落引擎仓=本票要杀的静默用错仓）；enabled=false 占位实例缺身份同样拒收（身份不是调度细节，schedule.source/n 的占位豁免惯例不适用——占位实例=无主票预定席）；形状畸形（大写/下划线出实例 id 词法白名单）拒收点名；正形声明过门且 schedule_specs 面实例身份各归各位（instance_project_key 与 instance_id 一一同位）；实例级身份与 schedule 级计数源两键并存（race-first 计数实例）过门且 specs 里 project_key==计数源值、instance_project_key==身份值——两字段作用域不同不串键（review R2「身份/计数源串键」教训的离线见证，260915 定稿）。分工：t260905-03-decl-gate 守声明门通用行为（畸形/未接线 kind/占位豁免/未知实例——其夹具不含本字段）；真链路半张 t260915-20-project-identity-realchain 守身份进起票面之后的行为；developer L1（decl 解析真值表）不同层。纯 stdlib 离线不存在环境红面——实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260915-20/sc_inspection_decl_project_identity.py", "ro"),
    ("t260915-20-project-identity-realchain",
     "巡检分项目归属的真链路用户旅程契约（t260915-20 验收①②③主证据，灰盒 L3，真 docker 台+真注册表缝+真专属 worker+真调度）：双项目夹具（SANDBAR_PROJECTS_DIR 临时注册表根：两项目各归各 sandbox 仓形夹具）各起一期巡检票（trigger 不带 --repo-root 真走注册表解析）——①工单板项目过滤天然含巡检票：kind=inspection+project=<key> 各归各（A 票只在 A 板不含 B 票、对称）、行 project 字段==各自 key（SA 是行 project 真源，无 SA 即不可见的用户面回归=本票题眼）；②票面 payload 与 SA 同源：describe 快照 project 键+ticket 详情回执 project 键均非空且==SA 值（两真源不漂移，review R3）；③扫对仓：两票发现各自命中本仓种下的独特漂移锚绝不串对方仓（内容级互斥=「扫在与套件跑在各自项目仓」可判定承接，KI-051 high 形态夹具）+被扫树逐字节不变（巡检不改码红线）；④迁移机制可证（review R1）：schedule-up 建（created）→改声明→第二次 schedule-up（update 路径）→temporal schedule describe 断言 action 已带新 payload（scan_face/project_key/repo_root）与 ProjectKey SA——update 不重铸 action 即红（t260913-02 只修 create 侧同族坑的常驻闸）；⑤未知项目键 fail-closed：声明身份指向未注册 key→trigger 显式报错点名该 key 与注册表语境，绝不报成网络错（报错必须说哪个检查失败）；⑥无主票守卫：旧调度 payload 形态（无 project_key 无 repo_root，直发 SDK 旁路起票）→patched 新 worker 判 blocked 终态、票面点名「无项目身份」——杀静默回落引擎仓的最后残窗。分工：离线半张 t260915-20-decl-project-identity 守解析门；t260905-03-period-journey 守单期全链旅程质量（人门/收口审计链不重测）；t260915-08-board-rows 守巡检行形状契约（彼时票无 SA 行 project 恒空不在其断言面，本条守项目过滤可见性）；t260915-12-gate-real-chain 守调用方项目身份闸（写操作维），本条守票归属项目身份（SA/扫描仓维）不同维；developer L1（resolve 三子用例/守卫两子用例/串键回归）不同层。资源回收：自建调度退出即删+STARTED_TICKETS 账本 cancel+夹具树拆除；docker 测试台/CLI/venv 缺件=ENV_FAIL exit 2 点名。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-20/sc_inspection_project_identity.py", "exclusive"),
    # ---- t260916-02: 巡检声明落位迁移A（每项目仓内单文件 + paths.inspection_decl 指路 + 票号统一工单号形式）----
    # 三条 intent 互不重叠：①真链主场景（声明进各项目仓根后的聚合解析链×票号 t 形×
    #   显式去重×指针三态×聚合调度——t260915-20 真链条守「声明住引擎仓+--decl-path 注入」
    #   时代，本条守迁移后世界，注入面正是被迁移对象）②聚合声明门离线半张（fail-closed
    #   /指路/跨项目重复/覆盖层兼容——t260905-03-decl-gate 守单文件门通用行为，本条守
    #   聚合维）③板面历史票三态半张（口径⑤降级可辨——t260915-08-board-rows 守行形状
    #   契约时票全旧形无 SA，不在其断言面）。共享前置在 lib_relocation.py（无 sc_ 前缀）。
    # 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t260916-02-relocation-realchain",
     "声明落位迁移后的多项目巡检真链用户旅程（t260916-02 验收①②③⑤主证据+口径①④⑤行为面，灰盒 L3，真 docker 台+真注册表缝+真仓根声明+真专属 worker）：双项目夹具（SANDBAR_PROJECTS_DIR 临时注册表根）声明各落**自己仓根** inspection.yaml（实例集互异：A 一实例、B 两实例=聚合子用例）、零 env 覆盖层零 --decl-path 零 --repo-root（聚合遍历=本票题眼），注册表缝混入一个坏声明项目——①票号形状子用例：trigger 起票票号==工单号形式 ^t\\d{6}-\\d{2,}$ 且日期段==期号日期段（口径②）；②去重子用例：同期重复 trigger→triggered:false/deduped:true、票号=既有、(实例,期) workflow 计数不增、退出码 0（口径②显式去重的行为等价承接）；③SA==票面：ProjectKey/InspectionInstance/InspectionPeriod 与回执票面同值+按实例 SA 查历史期恰好命中（口径②建议项）；④扫对仓：两票发现各自命中本仓独特漂移锚绝不串对方仓+被扫树逐字节不变（验收①「扫在各自项目仓」）；⑤板面聚合：零覆盖层下白名单=各项目实例并集、行 instance/period==SA 值、新票行零旧形前缀（验收②旧形零残留运行时子用例+验收⑤板面白名单收全）、板面项目过滤各归各；⑥分项目降级：坏声明项目不拖垮好项目板面+回执 degraded_projects 点名（「一份坏文件全板降级」的旧行为不许回归）；⑦指针三态真链注入：陈旧指针（指向不存在票+超 grace 龄）与畸形指针（半截字节+超 grace 龄）都不得谎报 deduped——自动清回执留痕点名路径后照常开票，指针目录走 SANDBAR_INSPECTION_DIR 覆盖链（review F2 修正的注入子用例）；⑧指针不污染 deadman：台账目录 .ticket 不进漏跑畸形清单（离线子用例）；⑨跨族票号互见：ticket-list id_prefix 全前缀扫描列出巡检票（巡检与 dev-lane 共用票号空间=防撞号的用户面承接）；⑩聚合调度：schedule-up 零 --decl-path 各读各自项目声明（A/B cron 字面各归各：temporal schedule describe 解码断言）+action 指向 spawner（起票时刻铸 t 形号承接面）。分工：t260915-20-project-identity-realchain 守「声明住引擎仓+--decl-path 注入」时代项目身份链路（其注入面=本票迁移对象）不同面；t260905-03-period-journey 守人门/收口审计链不重测；t260915-08-board-rows 守行形状契约（快照对拍）不同面；t260913-02-schedule-daily-deadman 守期号推导核心，本条只守聚合接线与指针不污染；陈旧/畸形指针细粒度真值表（grace 窗内外、SA 不一致不自动清）归 developer L1；t260916-02-decl-gate-aggregate 守聚合声明门离线面。资源回收：自建调度退出即删+STARTED_TICKETS 账本 cancel+夹具树拆除；docker 测试台/CLI/venv 缺件=ENV_FAIL exit 2 点名。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-02/sc_inspection_decl_relocation.py", "exclusive"),
    ("t260916-02-decl-gate-aggregate",
     "聚合声明门 fail-closed 契约（t260916-02 口径①③④的声明维+验收④主证据，灰盒 L2 离线子用例，纯 stdlib 拒绝子用例零网络）：声明来源改「遍历注册项目读各自声明」后——①聚合视图逐项目状态可读：ok 项目列实例、absent 项目=无巡检面不冒充错误、error 项目点名 key+路径+行号（fail-closed 红三要素）、enabled 并集=各项目实例之并（遍历非单文件的离线证据=验收⑤离线半）；②未知实例报错列出已扫项目与状态，绝不冒充网络错（报错必须说哪个检查失败）；③缺声明项目点名无巡检面，绝不借用他项目声明（口径①响亮点名）；④指路三态（paths.inspection_decl，与 paths.model_routes 同思路）：绝对形态与相对（拼 dirs[0]）形态都从指向处取到声明；指向不存在 fail-closed 点名声明路径——拼错路径静默关掉巡检面正是要杀的形态（KI-030 禁静默回落同族）；「..」逃逸词法拒绝（照抄 model_routes 放宽口径的拒绝半边）；⑤跨项目实例 id 重复 fail-closed 点名两处（配置事故绝不猜）；⑥引擎侧零回落：引擎仓旧声明已删（迁移交付本体）+空注册表显式报错+docs/inspection-sample.yaml 在场但样例实例不进聚合（不回落样例=验收④）；⑦覆盖层兼容（口径①）：env SANDBAR_INSPECTION_DECL 降级为测试覆盖——生效时单文件整体替代聚合（env 独有实例可解析、聚合实例不可解析=整体替代非并集），撤掉恢复聚合（兼容层可开可关）。分工：t260905-03-decl-gate 守单文件声明门通用行为（其 --decl-path 注入面=本票迁移对象）不同面；t260915-20-decl-project-identity 守实例级身份字段门不重测；t260916-02-relocation-realchain 守聚合解析链起票后的真链行为；deadman 期号推导核心归 t260913-02-schedule-daily-deadman；装载器跳过语义对齐=developer L1 单测（方案 §2.6③）不重复钉。纯 stdlib 离线（被测入口缺三方依赖=ENV_FAIL 点名不假红）——实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-02/sc_inspection_decl_gate_aggregate.py", "ro"),
    ("t260916-02-board-legacy-three-state",
     "历史票三态降级板面可见性（t260916-02 口径⑤主证据+口径②两路白名单承接，灰盒 L3，真 docker 台+直发旧形 id 夹具）：票号 t 形化+板面白名单改两路查询（SA 查询路径+legacy 查询路径）后——①20 前老票（旧形 id、无任何项目 SA）经 legacy 查询路径仍上板：行 project 空且显式点名「历史票·无项目身份」（legacy_unowned 面），绝不静默丢失；②20 后迁移前旧形票（旧形 id、有 ProjectKey 无实例/期 SA）legacy 查询路径收进：行标 legacy_id、project==SA 值（不误归他项目）、match_via=legacy_id 可观测；③白名单判定走聚合声明（零 env 覆盖层）：实例在册的旧形票上板、不在册旧形 id（僵尸形态）两子用例都不上板（R2 防僵尸收益在 legacy 查询路径保持）；④同一渲染内新/旧票合并呈现且 match_via 可观测（两路查询+合并的承接面）。夹具=SDK 直发三枚旧形 id workflow（workerless RUNNING：板面行来自列表面不依赖快照；L2 盖 ProjectKey SA、L1 零 SA、L3 僵尸实例），退出全 cancel。分工：t260915-08-board-rows 守行形状契约（彼时票全旧形无 SA、行 project 恒空不在其断言面）；本条守三态降级与两子用例合并可见性；真值表全组合（新/20后/20前×在册/僵尸×R8 窗口）离线对拍归 developer L1；t260915-20-project-identity-realchain 的无主票守卫守「起票面」本条守「板面读面」不同维；t260916-02-relocation-realchain 守新票链路不重测。资源回收：STARTED_TICKETS 账本 cancel+夹具拆除；docker 测试台/CLI/venv 缺件=ENV_FAIL exit 2 点名。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-02/sc_inspection_board_legacy_rows.py", "exclusive"),
    # ---- t260915-18: 测试台生命周期治理（被砍路径兜底回收/孤儿清扫半径/容量映射可见）----
    # 三条 intent 互不重叠：①编排层 kill/cancel/失败三路的台回收（工单①）
    # ②无租约孤儿的清扫判据与半径（工单②自愈+本设计段对抗发现=半径限定）
    # ③inventory 映射回执可见性（工单②容量可见；工单③热台复用缺省关=无
    # 用户可感知行为，归 developer L1，不立场景）。与 t260912-02（有租约残台
    # 判定矩阵/保险丝/网段）与 t260910-12（hold 被杀判死回收）分界见各条 intent。
    # 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t260915-18-capture-stage-kill-reclaim",
     "被砍/异常路径的舞台回收（t260915-18 工单①「怎么算好①」，灰盒 L3，真 docker 台）：四路终态显式 down 契约钉在编排公开协程 ui_capture_stage.run_capture_stage（方案 §1b「编排纯函数、capture_cmd 注入可桩」的落地形态；agent_activities 即经它驱动截图流程，其 docstring 明文「场景用 sleep 桩」；260915 gen1 收敛——实现先落原语+活动内联后抽取为此协程，场景随其合流）。子用例 A1 主修超时路——capture 桩（sleep 120）+capture_timeout_s=4 → wait_for 先响（超时分支确定性触发）→ 必须显式 down：容器数紧窗口（≤30s，显式 down 级；分钟级 hold ③ 兜底链达不到=备选 A 否决理由）回落到零、回执点名「超时」。子用例 A2 取消于捕获窗——租约 state=up 后 task.cancel()，取消语义=先拆台再按 Temporal 惯例重抛，容器紧窗口回落。子用例 A3 取消于起台窗——容器一出现（起台子用例仍在跑）即取消：落地形态=asyncio.shield 保起台收尾再补拆重抛（「绝不把半起的台丢给兜底链」），断言容器在 down 帽级窗口（≤150s）回落到零；260915 读码实锚过未护形态（CancelledError 直上抛、台活到 hold ⑥ 帽 4h），本子用例守该窗不退化。子用例 B 硬杀残局守卫——调用方进程 SIGKILL（worker 崩溃/OOM 形态，收割僵尸后判）后既有 hold ③ 锚死回收最终拆台+租约销账（验证对象=兜底非主修，修前应绿守其不退化）。子用例 C 回收失败响亮——SANDBAR_STAGE_INJECT_DOWN_FAIL=1 一次性注入：down 非零退出+输出点名+租约保留（账本不先于容器销，C4 裁决）+容器仍在（失败的 down 不得假报成功），撤注入恢复。与 t260910-12-holder-kill-reclaim（hold 被杀判死回收）intent 不同面：本条子用例 B 锚「锚进程死而 hold 活」的 ③ 路中间形态，子用例 A/C 为本票新增单主人显式 down 契约，不互替；capture 超时/取消分支的编排层单测归 developer L1 不同层。锁根经进程 env SANDBAR_STAGE_LOCK_DIR 隔离（引擎子进程继承）。登记 engine（真台生命周期面，拆台按工程名隔离不碰他台）。cmd 自带引擎 venv 回落（temporalio）；docker 缺席=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260915-18/sc_capture_stage_kill_reclaim.py", "engine"),
    ("t260915-18-stage-orphan-sweep-radius",
     "无租约孤儿的清扫判据与半径（t260915-18 工单②「自愈」+本设计段对抗发现，灰盒 L3，真 docker 台）：正用例——真起台后孤儿化（杀 hold+删租约=「本管域容器而无租约」真实形态，KI-077 当日 37 孤儿最小复现）+孤儿模式 sweep（env 开+年龄阀 0+前缀限定）必须 dry-run 先认领不拆、真跑 condemned 点名+容器清零+rc=0；半径限定（硬契约）——condemned 集合全部命中本票前缀，前缀外在管域容器（含共享供给台 sandbar-test-integ）零接触：孤儿容器是全机全局可见面，无半径的「在管域+超龄即拆」会让任何一次 sweep（含 ensure 挂点/巡检/场景误跑）把宿主存量孤儿一次性真拆（红线「真拆须宿主点头」失守，KI-077 先例=宿主授权清场），故清扫半径必须可限定（本场景锚 SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX，实现可选等效机制但须过本断言）；负锁×3 防判据恒真——租约新鲜台不拆（α 安全阀）、年龄阀内孤儿不拆（β SANDBAR_STAGE_ORPHAN_MIN_AGE_S 生效）、前缀命中但 working_dir 域外不拆（γ in-domain 判定 fail-closed，前缀不越过管域闸）。与 t260912-02-sweep-owner-gone（有租约残台的主人存在性判定矩阵，租约面手术注入）intent 不同面：本条锚无租约孤儿（容器面，租约缺失即失明的 KI-077 家族）与清扫半径，不互替。登记 engine。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260915-18/sc_stage_orphan_sweep.py", "engine"),
    ("t260915-18-stage-inventory-mapping",
     "attempt→台名映射回执可查+容量计数面（t260915-18 工单②「怎么算好②」+容量可见半边，灰盒 L3，真 docker 台）：stage_docker.py inventory 只读回执——capacity 计数面（containers/projects/leases/orphans/max_stages 等 ≥五键子集，上限真值同面呈现）+stages 逐台条目（落地形状=扁平 holder_ticket/working_dir/age_s/containers，260915 对齐；语义钉=台属于哪个泳道/票号可核对）；起台挂 SANDBAR_STAGE_TICKET=票号 → 回执 holder_ticket=票号（ticket→project→容器一眼可对，人工排障不再猜哈希台名=病灶四用户面）；未挂票号台 holder_ticket=unknown 缺省（不编造归属——报错精确纪律）；拆台后条目消失（清单跟随真实容器面，当日「锁根 1 租约 vs 38 容器」失明形态在回执层不可再现）。与 t260912-02 系（起台/清扫/网段行为面）intent 不同面：本条锚可见性回执（只读、零 docker 变更动作）；工单③热台复用缺省关无用户可感知行为归 developer L1，不立场景；t260910-12 租约四象限归 L1 不同层。登记 engine。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 integration/t260915-18/sc_stage_inventory_mapping.py", "engine"),

    # ---- t260916-04: 泳道图受阻着色语义（历史已解除受阻不显当前受阻红，t260916-02 实证）----
    # 与 t260915-05-detail-lane-map-dom 分工见 intent 末段：彼锁详情渲染面通用契约，
    # 本条只锁「受阻史的图面投影」新面（着色翻转/角标/hover 经过/保守边界/降级面同推导）。
    ("t260916-04-lane-map-everblocked-dom",
     "泳道图受阻着色语义 DOM 对拍（t260916-04 验收①②③④渲染面+验收⑤降级面，灰盒 L3，隔离台真浏览器+API 桩，3099 零接触）：用户可感知契约=段的显示态取当前语义而非最后一条流水——L1 复现子用例（t260916-02 实证形态：implement 同刻 done+blocked 双记录、兄弟段 design done 在后不构成证据、工作流推进 run_integration_tests）该段 data-vis=done（绝不当前受阻红）+data-ever-blocked=true 角标+hover 出经过（受阻时刻+受保护路径闸原因+已解除+推进措辞），且无受阻史段零误标；L2 真当前受阻子用例未解除保持 data-vis=blocked 且全图零角标；L3 保守兜底三子用例（零后续证据保持红/并行兄弟 done 不构成推进——mid-gather parallel_stages 在场实况/authorized 授权条目单独不解除，人放了话≠活干成了，t260912-03 留痕形态当前段无 gen/phase）；L4 关闭票子用例 closed 票历史受阻段完成色+角标+已解除经过；L5 重跑解除子用例（E1 本段 done）完成色+角标+经过（E1/E2 双证时不锁机制词，只锁已解除必在场）；L6 降级面拓扑缺席回落步骤条吃同一推导（.wb-d2-step[data-s] 不停 blocked——stale 红消除是一处推导两处消费）；S0 twin bundle 同步+ever-blocked 契约新鲜锚（src 已落而 lib 无=响亮点名重建，工单验收⑤）；P 卫生子用例全旅程零 pageerror/console.error。数据全桩（tickets/workflows 两路由 page.route，拓扑契约形状同 t260915-05 导出面）。分工：t260915-05-detail-lane-map-dom 锁详情渲染面通用契约（双道/红灯翻译/蓝卡/轮次带/关单可见/通用性/降级回落/检查明细）本条不复断其任何一面；t260901-09 锁步骤条并行双亮（本条 L6 只断降级面吃新推导）；t260911-05 锁红卡四件；developer UT（lane-blocked-history 推导矩阵）锁 L1 函数层，本条锁 JSX 接线/落位/两消费面。L2/L3a/L3b/L3c 保守子用例任何时刻不得红（红=把未解除画成完成色，漏报比 stale 红更危险）；L1/L4/L5/L6 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 点名面）",
     "node integration/t260916-04/sc_ticket_detail_lane_map_everblocked_dom.mjs", "browser-free"),
    # ---- t260916-05: 巡检票上泳道图（登记巡检模板拓扑+阶段声明真源+一致性锁）----
    # 三条 intent 互不重叠：①DOM 渲染面（本票验收①的用户可感知半）②查询回执缝（数据半：
    # 拓扑真从 snapshot 流到 ticket-query 回执，缝断=DOM 桩测不出）③双真源同步锁的闸内
    # 活性（验收③；锁本体=developer workbench UT，本条守「锁在集成闸内被真实执行」）。
    # 引擎 workflow 侧（snapshot 门两态/逐字段一致性锁/变异自证）归 developer L1
    # （server/engine/tests/test_t260916_05_inspection_topology.py）不同层。
    ("t260916-05-inspection-detail-lane-map-dom",
     "巡检票详情泳道图 DOM 对拍（t260916-05 验收①③，灰盒 L3，隔离台真浏览器+API 桩，3099 零接触）：S0 build-contract（twin bundle 同步+泳道图锚在 bundle+buildLaneMap 巡检夹具冒烟：5 节点/human/仅套件档注记）+S1 真 DOM 四子用例——L1 在飞票：引擎登记 inspection-lite 拓扑后泳道图自动在场（渲染器零改动=被测前提），节点集==阶段声明全集 {setup,scan,suite,report,close}、标签全部来自拓扑（零 dev-lane 业务词）、人门虚线圈恰落 close（data-kind=human）、条件段注记恰 setup+suite（wb-lm-opt 恰 2，「仅套件档」泄漏=图面撒谎形态）、在飞状态如实投影（已进入段 running/未进入段 todo——巡检 timeline 无逐段 done，多节点同显 running 是引擎现状的诚实投影）；L2 待签票：close data-vis=awaiting-human（人门到站）；L3 关闭票：全段 done 且图仍在（KI-027 关单可见同族）；L4 降级锚：详情无 topology 键（老实例重放常态）→零泳道图且零 dev-lane 步骤条回落（维持 t260915-08 现状降级，绝不拿步骤条冒充巡检图），巡检面时间线照常。数据全桩（list/detail/workflows 三路由；workflows 桩不带 topology=泳道图唯一图源是详情快照键的证明面），浏览器/bundle/React 全真。分工：t260915-05-detail-lane-map-dom 守 dev-lane 泳道图本体/渲染器通用性/畸形拓扑（本条不重复其面）；t260915-08-board-ui 守板面巡检行/签字通道。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台/playwright/chromium 缺席=ENV_FAIL exit 2",
     "node integration/t260916-05/sc_inspection_detail_lane_map_dom.mjs", "browser-free"),
    ("t260916-05-topology-receipt",
     "巡检查询回执携带拓扑导出的缝契约（t260916-05 验收①数据半，灰盒 L2，stub temporalio 离线，镜 t260915-08-board-rows 黑盒口径）：T1 新实例常态（snapshot 带 topology）→ticket-query 回执 ticket 面 topology 原样透传（逐键相等不重形：version=topology-v1/template=inspection-lite/5 节点/线性 4 边/close kind=human/setup·suite optional=仅套件档）+snapshot 通道同在（双通道互证）+face 既有字段不因加键丢失（findings/summary/report_path/gate_id/instance_id/period 照常——加键挤掉既有面=立即红）；T2 老实例重放常态（snapshot 无 topology，_patched 门关）→回执无 topology 键且 face 照常（省键降级契约，绝不编造）；T3 topology 畸形三态（非 dict：123/'garbage'/[]）→无键不炸、face 照常（查询边界绝不抛——KI-025 族谎报温床）。分工：渲染面归 t260916-05-inspection-detail-lane-map-dom；snapshot 门两态 workflow 侧归 developer L1（test_template_topology F 子用例同款）；t260915-08-board-rows G 组守巡检分支 engine 标记+dev-lane 键集 parity（本条不重复）。纯离线无 ENV_FAIL 子用例——环境红捂不住本面。实现落地前红属预期（TDD 信号：T1 红=透传缝未接），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-05/sc_inspection_topology_receipt.py", "browser-free"),
    ("t260916-05-dual-source-lock",
     "双真源同步锁的闸内活性（t260916-05 验收③，灰盒 L2 离线）：验收③「保留则同步锁在场，两者择一并以源码锁钉住」的机械执行点——锁的断言内容（引擎 inspection_flow.py STAGES 声明 ↔ workbench INSPECTION_TOPOLOGY 短名表逐位比对+变异自证）由 developer UT 交付（server/plugins/workbench/tests/t260916-05-inspection-topology-lock.mjs），本条守锁在集成闸内被真实执行且绿：锁文件缺席=fail 点名交付约定路径（文件缺失=产品面缺失非环境）；执行非零=fail 带 stdout/stderr 尾部（锁红=双真源漂移已发生，恰是本票要抓的形态）；exit 0=pass。没有本条，锁只活在 developer 自检里——merge 后改声明忘改词表没有任何机械闸会红（KI-046/049「测试在场≠测试生效/机制活性」家族；t260913 golden-freeze 补「唯一自动比对点」同族先例）。路径解析走爬根 helper（KI-075 族）。纯离线无 ENV_FAIL 子用例。实现落地前红属预期（TDD 信号：锁文件未交付=fail），arbitrate/merge 期必须绿",
     "node integration/t260916-05/sc_inspection_dual_source_lock.mjs", "browser-free"),

    # ---- t260916-15: 左栏工单合并排序 + 巡检行徽标可辨（巡检票不再沉底）----
    # 与 t260915-19-sidebar-inspection-ui 分工见 intent：彼守分拣制（归位/兜底组/黄调/
    # 降级）+反沉底烟测，本条守合并排序口径全矩阵（tier 边界/级内 updated_ts 倒序/兜底组
    # 同口径）与徽标可辨（命中/可见/文本/dev 零徽标对照）。
    ("t260916-15-sidebar-merged-sort-ui",
     "左栏合并排序与巡检徽标 UI 面（t260916-15 验收①②③渲染面，灰盒 L3 browser-free，镜 t260915-19 两层式）：S0 build-contract=双 bundle 同步+合并排序/徽标锚在 shipped bundle（wb-card-kind 类字面+data-kind-badge 属性字面——字符串字面过压缩器存活，函数名不锚=压缩器改名面；盘上 bundle 新鲜锚=KI-052 防改源忘重建静默穿透）；S1 真浏览器 API 桩（自带 /wf/projects 桩=项目组确定性渲染，数据只桩 API 边界，浏览器/bundle/React 全真，宿主 3099 零接触）——①合并排序全矩阵：甲组四行（dev 在跑 ts 中+dev 等你 ts 次新+巡检等你 ts 最新+巡检已收口 ts 最老，输入序=拼接序与期望序刻意错排防断言自我失效）DOM 行序==[巡检等你,dev 等你,dev 在跑,巡检收口]，一面同钉 tier 边界（在等你→在跑→已完成）+级内 updated_ts 倒序+反沉底核心（等你巡检行压在跑 dev 行之上=用户实报「恒沉底」的逆否）+已完成沉组底但仍可见不丢失；②兜底组同口径：unowned 两行（等你 ts 新+在跑 ts 老，输入序相反）序==[等你,在跑]（合并口径不分组）；③徽标可辨：巡检行卡内 [data-kind-badge] 恰一、可见、文本=巡检；④dev 零徽标对照（左栏 dev 行渲染零变化反断言）：dev 行卡内徽标元素数=0+甲组徽标总数==巡检行数；⑤行1 标题原样：巡检行文本含引擎标题「巡检 <实例> · 期 <期号>」（排序不得改行内容）；⑥行唯一性：组内 id 数==去重数==4（排序不得丢行/重复键）；⑦卫生子用例全旅程零 pageerror。分工：t260915-19-sidebar-inspection-ui 守分拣制（项目组归位/兜底组存在性/等你黄调/降级显式性）+反沉底烟测，本条不复断其任何一面；排序纯函数真值表（状态×来源×畸形 ts/缺键/null 元素/未知状态缺省行）归 developer L1 UT 不同层；t260903-07-click-no-chat-switch 守点行不切会话不同面。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；stage console/playwright-core/chromium 缺席=ENV_FAIL exit 2 点名（不假红不假绿）",
     "node integration/t260916-15/sc_sidebar_merged_sort_ui.mjs", "browser-free"),

    # ---- t260916-25: dsh 升级 stage 控制台（一键 harness）+ UI 兼容面 ----
    # 五条互为分面（见各 intent）：lifecycle=happy 主链+幂等+终态回收；guardrails=拒收干净；
    # fault_paths=异常终态回收与响亮；prepare_refresh=组装语义+凭据刷新分档（KI-016 钉）；
    # selfcheck_red=自检三态经壳出口透传。夹具=lib_stage_fixture 的 dsh 启动面测试桩
    # （假 dsh-root+catch-all 桩控制台），零真 dsh/零 docker/零 npm 网络/零 3099 接触；
    # 真版本（0.1.5-rc.2）全链归方案 S3/S4 实弹与 acceptance 人工走查，套件只锚 harness
    # 自身的编排契约（对被测件只从公开 CLI/FS 面驱动，灰盒绑定浅）。
    ("t260916-25-stage-console-lifecycle",
     "stage 控制台一键主链路+终态回收（t260916-25 验收「一条命令起 staging/自检全绿/打印 URL 与清单/停后零残留」的正半边，灰盒 L3 browser-free，dsh 启动面测试桩面零真台）：L0 交付物在位（stage_console.sh+断言库，缺失=fail 点名=TDD 红）；start（--dsh-root 桩/独立 home/独立高位口/--no-open）exit 0 且 stdout 含带 token URL（票面实测形态 http://127.0.0.1:<port>/?token=…）+只读警示随 URL 同出（票面④警示到达面）；staged home 组装面（票面「照此固化」的可见产物）：profiles/sandbar-stage/cordis.patch.yml 含所选端口且 3099 字样清零（sed 失守=真台抢 3099 前半程，红线面）、五插件软链在位可解析、profiles/node_modules→dsh-root/node_modules、凭据落位、sessions ≥1；selfcheck 子命令 exit 0（桩台供五插件名超集 bundle+workbench API JSON+会话 FS——对断言名集的 review R1 校准免疫）；url 子命令再出 URL+警示；checklist 子命令出清单非空；start 幂等二跑（同 URL、监听进程数不变=不二次起台）；stop→exit 0+端口释放+pidfile 清+cmdline 匹配夹具工作区的残留进程=0+stop 幂等再跑 exit 0（KI-077「池子没小是台没拆」家族回归面）。与本票 fault_paths 分面：彼锁异常终态（hang 超时/死 pid/僵 pidfile 误杀/URL 静默），本条只锁 happy 主链+幂等+终态回收。实现落地前红属预期（TDD 信号：L0 交付物缺失=fail），arbitrate/merge 期必须绿",
     "node integration/t260916-25/sc_stage_console_lifecycle.mjs", "browser-free"),
    ("t260916-25-stage-console-guardrails",
     "stage 控制台红线与防呆拒收（t260916-25 交付⑤红线+畸形输入的运行时行为半边，灰盒 L3 browser-free 桩面）：端口禁区三连 --port 3099/7233/8233 一律非零退出+零副作用（stage home 不落盘+零进程残留——护栏必须先于任何落盘/spawn）；缺省口被占即拒不抢不杀：高位口被无辜 decoy 占→start 非零+输出点名该端口+decoy 存活（「占用即拒打印占用者」契约，绝不杀对手）；home 防呆两形：--home 解析为 ~/.dsh 非零且 ~/.dsh/profiles/sandbar-stage 保持缺席（真 home 零污染；先已存在=污染断言降 na 系统状态用例）、--home==--src-home 非零（自我吞并拒收）；畸形参数全拒（--port abc/0/99999、start 缺 --version|--dsh-root、未知子命令）逐条非零。与 lifecycle（happy 主链）/fault_paths（异常终态回收）分面：本条只锁「拒收干净」——拒在先、零残留、不误伤。与 verify.yaml guard-3099-redline 机械闸不同层不互替：彼扫 bin/server 源码字面（pkill|kill -9 × 3099），本条测运行时行为。KI 对齐：KI-036「测试通道直连 3099」家族的运行时回归面。实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260916-25/sc_stage_console_guardrails.mjs", "browser-free"),
    ("t260916-25-stage-console-fault-paths",
     "stage 控制台故障路注入与资源回收对抗（t260916-25 验收「停脚本后端口释放、无残留进程」的负半边+review R3/R5 的机械执行点，灰盒 L3 browser-free 桩面）：pidfile 记账在位（stage home 下「纯 pid 内容且 pid 存活」文件；探不到=fail 点名「安全用例不可注入」，不猜位置不造误红）；僵 pidfile 误杀防护——无辜进程（sleep，cmdline 不含 stage home）pid 写入 pidfile 后 stop：无辜进程必须存活+exit 0（「只杀自己 pidfile 且 kill 前 ps 核对」契约的对抗面）；死 pid pidfile→stop 幂等清理 exit 0 不误报在役（死 pid 被系统即时复用=na 系统状态用例）；start 超时路——hang 桩（永不监听）+SANDBAR_STAGE_CONSOLE_UP_CAP_S=4→start 在 CAP 内非零退出（25s 兜底帽，兜底击杀=true=fail 点名 CAP 旋钮不生效或超时路挂死）+输出非空点名失败+自起 stub 零残留（spawn 的每个终态都要有回收）；URL 静默路——nolog 桩（端口在听但 URL 行缺）→start 非零响亮+自起 stub 零残留+端口释放（绝不静默无 URL 假成，也不留悬空台）。与 lifecycle/guardrails 分面：本条全是异常终态的回收与响亮。KI 对齐：KI-077（proc.kill 只杀 node 进程、拆台钩子没跑→台面残骸堆积）同族。实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260916-25/sc_stage_console_fault_paths.mjs", "browser-free"),
    ("t260916-25-stage-console-prepare-refresh",
     "stage home 组装口径与凭据刷新/会话稳定的幂等分档（t260916-25 交付① prepare 面+review R2 硬条件的机械执行点，KI-016 同族回归钉，灰盒 L3 browser-free 桩面）：prepare 组装一次到位（profile 拷贝/端口补丁含所选口且 3099 清零/五插件软链/依赖软链/凭据/会话）；凭据强制刷新——src 凭据 v1→prepare→staged 逐字节==v1，src 改 v2（含新 provider）→再 prepare→staged==v2（「目标已存在即跳过」形态在此即红）；settings 同口径；旧会话数据稳定——src 改已有会话内容→再 prepare→staged 旧会话字节不变（不删不毁不重拷，测试数据不随刷新蒸发）；prepare 幂等重跑 exit 0。语义=凭据/settings 是真源快照必须最新（旧凭据跑出的 auth 失败会被人工测试误读成升级 break），sessions 是测试数据必须稳定。与 lifecycle 分面：彼锁 start 一键链，本条锁 prepare 语义。KI 对齐：KI-016「_copy_creds 目标已存在即跳过→泳道凭据快照永不刷新」（open）。实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260916-25/sc_stage_console_prepare_refresh.mjs", "browser-free"),
    ("t260916-25-stage-console-selfcheck-red",
     "自检三态经壳出口透传+不造假绿（t260916-25 交付②「脚本内跑自检」×三态契约 t260904-12 的壳边界，灰盒 L3 browser-free 桩面）：绿对照——正常桩台 selfcheck exit 0（对照有效性自证，防场景永红自我失效）；降级台——badapi 桩（workbench API 恒 500 而端口/URL 正常）→selfcheck exit 1（红透传，绝不吞成 0 假绿）；会话空——删 staged sessions 后 selfcheck exit 1（FS 用例红，且自检绝不静默回填突变台面）；台不可达——未起台端口 selfcheck exit 2（环境红，三态出口不缺位）。与 developer L1（断言库 --selftest 进程内桩：500/慢响应/截断 HTML/非 JSON 等解析健壮性）不同层不同面——彼锁库内部，本条锁壳子命令透传出口与真 HTTP 面的三态语义；与 lifecycle 的 selfcheck-green 用例分面（彼只证绿通）。桩控制台供五插件名超集，对断言名集的 review R1 校准免疫。实现落地前红属预期，arbitrate/merge 期必须绿",
     "node integration/t260916-25/sc_stage_console_selfcheck_red.mjs", "browser-free"),
    # ---- t260916-26: dsh 0.1.5 会话视图扩展面适配（knowledge/providers 装机包双版本激活）----
    # 宿主 260916 实报：0.1.5 stage 控制台「Failed to load plugins / 2 entries did not
    # activate」——两插件 inject 声明了 0.1.5 已移除的 conversationViews 服务=永久 pending。
    # 三条分工：inject-contract 锁装机包对宿主的公开注入契约（判别修复的机械面）；selfcheck
    # 锁 stage 启停自检断言机器与 up/ensure 挂接（验收②，review C1/C6 面）；banner 子用例锁
    # 生产版本（0.1.1）真宿主装载活体零回归（验收①④的生产半边；0.1.5 活体归宿主 stage
    # 3199 走查，非本地机械可复现）。
    ("t260916-26-plugin-inject-contract",
     "客户端 entry 装机包「双版本可激活」注入契约（t260916-26，灰盒 L2 离线，vm 沙箱真实加载）：宿主装载契约=entry 按 inject 清单等服务注入、声明已移除服务即永久 pending（0.1.5 实报事故形态）——①装机包 lib/client.cjs 在 dsh 模块契约（ModuleLoader 外衣+外部化表）下可加载、exports.inject 是字符串数组且每项落双版本稳定集 {slots,sessions,workspaces}（证据=workbench 三项全声明且 0.1.5 实测正常；slots 另有宿主实报旁证：pending 只点名 conversationViews）；②本票两 entry（knowledge/providers）双产物零事故模式字面量残留（「conversationViews」双引号字符串字面量形态出现=活代码重新声明缺席服务键；注释散文/反引号形态不算——装机包头注收窄史是既定纪律，开发者 L1 smoke 同款锚形）；③全族排查：四 entry（+workbench/admin-ui）同线收敛，防下一家把脆弱服务名写回 inject（0.1.5 起会话页签扩展走 uiConversation.views 注册通道、不属注入面）；尺子自证红绿先行（缺导出/非数组/非字符串元素/空串/集外服务名五类坏样本全红、空数组=合法最大降级边界绿）。STABLE_SERVICES 维护契约：锚 workbench 0.1.5 激活单点活证，宿主再迁服务时随新双版本证据重推导（红=提醒重取证非误报）。与 t260903-13（workbench 模块加载契约）t260903-04（src↔lib 同步）intent 不同面；knowledge/providers 开发者 smoke 无闸内执行点，按 t260916-05 先例升格闸内可见。实现落地前红属预期（TDD 信号：零残留子用例红=装机包未重建），arbitrate/merge 期必须绿；纯离线无 ENV_FAIL 子用例",
     "node integration/t260916-26/sc_plugin_inject_contract.mjs", "ro"),
    ("t260916-26-stage-plugins-selfcheck",
     "stage 启停「全插件激活」自检断言面（t260916-26 验收②+review C1/C6，灰盒 L2 注入式假 console 黑盒 CLI + L3 真台面）：A 断言机器契约（假 console 按 S0 钉死的宿主 typert 线型回信封：POST /api/pluginInventory/list → {server-response,result.value.entries:[{moduleName,fiberPhase,enabled}]}，黑盒只经 `stage_docker.py plugins` CLI；S0 对齐注见场景头注，判定语义逐子用例不变）——健康回执→--assert exit0+回执 ok+pending/failed 双空；pending/failed 各一→非零且点名 entry id 与状态词（报错精确：哪个 entry 哪个状态）；非 JSON 回执→非零且点名畸形（不许误归因 unreachable——报错必须精确，诊断不许被引向网络面）；console 拒连→exit2 环境红；「全绿禁令」电池（entries 非列表/entry 缺 enabled/fiberPhase 未知值）一律不许得出全绿，部分清单按落地契约（通用投影、空真 ok）允许绿但判定所据必须可见：counts.{total,enabled} 须回显清单规模（少查必须可见，KI-046/049 家族）；只读性=假 console 只见 pluginInventory/list 一条只读 RPC（方法白名单，零其它路径）。B 真台面（docker，缺席=ENV_FAIL exit 2 点名）——B1 本场景自起冷台 ensure exit0 且租约回执可见 plugins 自检已跑（C1 挂接活性：探针随冷启动跑+热复用回显同一回执，锚「跑过且可见」非措辞），热复用 --check-plugins 健康台不误伤（升格负形由 A2/A3 同判定路径守），own-bench plugins --project --assert 零 pending 零 failed（真台活体=验收②实锤、自含），用完 down 回收；B2 共享供给台 plugins --assert 只读查询加演（查得到=实锤加演；锁根与供给契约对齐=场景内 setdefault 供给同款 /tmp/sandbar-test-stages，不对齐=降级锁根租约不可见=结构性 env_fail，台真缺席/非 up=ENV_FAIL 环境红点名，绝不从沙箱对共享台项目名跑 ensure）。B 面锚真台活体两面互不冒充。零 3099 接触、B1 own-bench 用完即收、B2 只读。arbitrate/merge 期必须绿",
     "python3 integration/t260916-26/sc_stage_plugins_selfcheck.py"),
    ("t260916-26-console-boot-no-plugin-banner",
     "生产版本真宿主装载活体零回归（t260916-26 验收①④生产半边，灰盒 L3 browser-free，隔离台=本泳道 worktree 直起 dsh 0.1.1-rc.2 台，t260915-19 通道先例）：同一份 knowledge/providers 装机包在生产版本（conversationViews 在场）上照常激活——台面无「Failed to load plugins / did not activate」事故文案（锚原文词不锚横幅类名）；正向控制先行（夹具甲项目行可见先证台面真渲染，absence 断言不空转=KI-052 绿≠真查防御；dsh 首跑 API key 向导先关不挡走查）；「模型路由」视图烟测渲染出显式状态（点夹具甲组 aria-label=模型路由 图标，作用域锚复制 t260915-10 同款；验收①「两页签可用」校准语义 providers 半边，docs 半边归 t260905-06/t260915-10 深锁不重复）。防错树夹具自检：台面 profile 三插件覆盖链（workbench/knowledge/providers）realpath 全落本泳道仓——lib_fix17 原样会把 knowledge/providers realpath 回主树旧产物（KI-052 别树假绿同族），故本台走 lib_t260916_26_bench 三插件泳道覆盖变体（漂移责任=两侧头注）。本台宿主=0.1.1，实现前后都应绿（纯回归守卫）；对修复的判别力归 t260916-26-plugin-inject-contract；0.1.5 活体子用例归宿主 stage 3199 走查非本地机械可复现。零 3099/7233/8233 接触、死端口 Temporal、票源桩、四路径回收。dsh/起台/playwright 缺席=ENV_FAIL exit 2 点名（KI-036 家族）",
     "node integration/t260916-26/sc_console_boot_no_plugin_banner.mjs", "browser-free"),
    # ---- t260916-24: dsh 升级 T4——版本钉路径可观测 + 预期不符响亮（epic dsh-upgrade）----
    # 三场景三面（探针工具自检 / 启动记录面 / spawn 执行面），两 engine 场景共享夹具
    # lib_t26091624.py（无 sc_ 前缀不登记）。断言契约=方案 gen1（integration review
    # verdict=pass）。intent 分工与 TDD 红预期见各自登记行。
    ("t260916-24-dsh-probe-selftest",
     "dsh 升级接缝探针离线自检子用例（t260916-24 验收①正负双自检，灰盒 L1 离线秒级，全程 /tmp 副本注入不改仓内 fixtures）：probe_dsh_seam.py --selftest——金样本 3 档必须全绿（v0 全键 / vN 全键+压缩 / vN 无 cacheReadTokens，且无 cacheRead 档必须恰出 WARN=可选键「缺席告警不拦停」语义自锁，C2 边界的机械守卫）+ 篡改 7 档逐项按预期断言名红（错文件名=断言 a 两代口径均不匹配 / 缺必填键与 cacheRead 在场非整型=断言 b / 钉模型不符=断言 d / 坏 JSON 行、截断半行、zstd 坏帧=成品完整性红即 KI-059 撕裂族第一道网）；方向不符=探针腐烂=产品红。intent 分工：本条守探针工具自身正负自检；t260916-24-dsh-face-meta 守引擎启动链记录面、t260916-24-dsh-expected-loud 守执行面响亮语义（同票三面不互替）。探针 live 档（npm 隔离安装+真凭据+分钟级五断言对账）不入 registry（验收④：不并入默认跑分面），升级门槛时显式调用（integration/t260916-24/RUNBOOK_GATE.md 门槛文本）",
     "python3 integration/t260916-24/sc_dsh_probe_selftest.py", "ro"),
    ("t260916-24-dsh-face-meta",
     "dsh 版本面启动可观测（t260916-24 验收③+②缺省半，灰盒 L3，docker 台 temporal-only+真 worker 起跑链）：归属 meta 落 dsh 版本面四子用例（来源字段拼写不锁 source/cmd_source——KI-051 锚语义）——①缺省子用例：无旋钮时来源=default、cmd 与文档化缺省口径逐元素等值、version 与宿主 `dsh --version` 实测一致（版本是探测来的不是抄配置）=「缺省不破现状」在真启动链上可查证；②钉路径子用例：SANDBAR_AGENT_CMD 指自执行版本桩 → 来源=env、version=桩自报、二进制路径解析到桩本体=显式钉路径生效且「机器实际在跑什么」可查（KI-058 机器层安装态≠代码态的对症观测）；③预期不符可查子用例：桩版本≠SANDBAR_DSH_EXPECTED_VERSION → expected/expected_state=mismatch 在案、worker 仍起（缺省 off 仅记录不拦）；④探测失败不挡启动子用例：SANDBAR_AGENT_CMD 指不存在路径 → version_state=error 附 detail 点名、meta 照落、worker 仍起（best-effort 契约，坏机器态显形而非静默或启动炸）。intent 分工：t260905-02-worker-lifecycle 守归属指纹生命周期面（同表面不同字段族，不互替）；sc_dsh_probe_selftest（本票探针自检子用例，implement 段交付）守探针工具自身正负自检、本条守引擎启动链接线；t260913-04-image-supervisor 守镜像内 dsh 在场；developer L1 UT 锚解析函数语义，本条锚真启动链接线。断言全落公开产物（meta JSON/进程终态），契约不变的实现重构不得打破。实现落地前红属预期（TDD 信号：meta 无 dsh 面=FAIL 点名），arbitrate/merge 期必须绿；docker/bench/宿主 dsh 缺席=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-24/sc_t260916_24_dsh_face_meta.py", "engine"),
    ("t260916-24-dsh-expected-loud",
     "dsh 版本与预期不符的执行面（t260916-24 验收③执行半边「版本与预期不符→响亮」，灰盒 L3，真 docker 台+真工单链+版本桩作 agent 脑秒回合法回执）：两子用例合取锚「响 + 不静默跑/不静默拦」组合语义，判定不锚 boot/spawn 哪个挂点（实现任一挂点响都算兑现用户承诺）——①缺省不拦子用例：桩版本(9.9.9-stub)≠expected(0.1.1-rc.2) → spawn 照走（桩被真调）+create_plan 出结果+worker 日志出现同时点名 actual/expected 两版本字面量的响亮行（KI-051 锚字面量同现不锁措辞）=「带病跑但喊得出来」；②STRICT 硬闸子用例（SANDBAR_DSH_STRICT=1）→ 版本桩 agent 形态调用恒 0（spawn 在执行被钉二进制前被拒）+日志硬闸红点名两版本=「宁可停也不悄悄跑错版本」（不另设 snapshot「不出结果」子用例：闸挂点在 worker 启动时票队列即无人服务、查询通道随之而死，该观测结构性不可达；闸腐烂由「调用恒 0」当场抓住）。两子用例合取同时抓住「静默跑错版本」与「静默拒跑」两个方向的腐烂。intent 分工：t260916-24-dsh-face-meta 守启动记录面（同旋钮不同行为面）；t260905-10-host-ruling-injection 只借其真票链手法（fixture 仓+专属 worker+snapshot 轮询），彼守裁决注入面；developer L1 UT 锚 check_expected 函数语义，本条锚真工作流链上的用户可感知终态（日志行/桩账本/票进度）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/bench 缺席=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-24/sc_t260916_24_dsh_expected_loud.py", "engine"),
    # ---- t260922-03: 探针 live 档修复票——live 入口对账面 + 失败归因面（epic dsh-upgrade 前置）----
    # 两场景三面（绿档 journey / 失败归因三态），共享夹具 lib_t26092203.py（无 sc_ 前缀
    # 不登记）。桩走 PATH 缝（npm 桩对 install --prefix 形状落假前缀 + .bin/dsh 桩；
    # 零真 npm 安装/零真网/秒级，不违反 T4 验收④「真版本分钟级 live 档不入 registry」
    # ——该约束指 npm 隔离安装+真凭据档，升级门槛仍按 RUNBOOK_GATE 显式调用）。
    # 不锚 --reuse-install（该旗标现况结构性失灵：探针每次 mkdtemp 新 tmp，prefix 恒在
    # 自己的空目录——t260922-03 结果文件缺陷上报，修不修由票面裁决）。
    ("t260922-03-dsh-probe-live-green",
     "探针 live 档绿档对账 journey（t260922-03 验收①②⑤的离线机械半，灰盒 L3，dsh 桩零真网零真 npm 安装秒级，全程 /tmp 不触宿主全局 dsh/console 3099）：对 integration/t260916-24/probe_dsh_seam.py 以 PATH 缝注入 npm 桩+dsh 桩（npm 桩只实现探针调用形状 install --prefix <p> @deepseek-ai/dsh@<ver>：落 package.json 钉同版本过 verify_install + .bin/dsh 桩只演用户可感知面：落 vN 会话产物 request/context+request/header 主备合一与 assistant/message usage 全键含整型 cacheReadTokens、cwd 泳道内写 probe_write_here.txt、主库 .git 模拟位不写=沙箱拒写形状、DSH_HEADLESS_SESSION 续写零新文件；其余 npm 形状 fail-closed 报错），SANDBAR_PROBE_EXPECTED_ROUTE 文档化旋钮钉期望路由 → 探针必须：①不再崩在会话 prompt 拼装（本票根因形状「not all arguments converted during string formatting」绝迹——实装前 :483 即炸，票面复现栈同形）；②五断言+沙箱行为+resume 全 PASS（文件名口径 session.v3.jsonl→vN 代、钉模型 stub-provider/stub-model、泳道内写成功、越界拒写、resume 会话文件集不变）；③退出码 0 结论「全绿」、墙钟秒级、零 traceback、退出后探针工作目录面无桩孤儿进程（spawn 资源回收全终态）。判据全落公开契约面（CLI 旗标/退出码/台账行字面/期望路由旋钮），探针内部实现重构不得破。intent 分工：本条守 live 入口绿档对账+可重跑性（runbook §1 门槛第 1 项的离线机械代理；真版本分钟级档按 T4 验收④不入 registry）；t260916-24-dsh-probe-selftest 守探针断言逻辑 fixture 正负自检（含本票新增守卫子用例）；t260922-03-dsh-probe-live-cred-env 守失败归因面（三面不互替）。修复已落本工单树，三档语义经直驱等价实证（探针 live 档直跑面），arbitrate/merge 期必须保持绿（回归锁）；探针/桩前置（探针本体/zstd/~/.dsh profile+settings+credentials）缺席=ENV_FAIL exit 2 点名",
     "python3 integration/t260922-03/sc_t260922_03_probe_live_green.py", "ro"),
    ("t260922-03-dsh-probe-live-cred-env",
     "探针 live 档失败归因三态（t260922-03 验收③，灰盒 L3，dsh 桩秒级零网络）：①凭据缺失子用例：桩自报 MISSING_CREDENTIAL（路由 stub-route-alpha、补救变量 STUB_API_KEY——即 0.1.5 实测报错形状的路由/变量位）后挂住不退 → 探针必须秒级早停收割（墙钟有上界，绝不复现「静默空等到会话超时 900s」的挂死形状）、ENV 红退出码 2、台账点名桩自报的路由与补救变量、零 traceback、收割后无桩孤儿进程（spawn 资源回收全终态）；②产品红保全子用例：桩退出码 3 且日志无 MISSING_CREDENTIAL 字面 → 探针维持拦停级 FAIL（退出码 1、FAIL 台账行在场）且零 ENV 行——「环境红不吞产品红、产品红不冒充环境红」双向锁（lib_env 三态契约 + RUNBOOK_GATE「环境缺=exit 2 补环境重跑」承诺的探针侧兑现；余失败语义零改动=验收④不放松的失败面）。判据不锚守望实现（轮询周期/字面量提取方式/文案措辞均可变），只锚用户可感知终态（退出码+点名字面+墙钟上界 30s+回收；守望若退化到只靠会话超时兜底，墙钟判据即红）。intent 分工：本条守 live 会话失败的归因面；t260916-24-dsh-probe-selftest 守断言逻辑自检、t260922-03-dsh-probe-live-green 守绿档对账面（三面不互替）。修复已落本工单树，语义经直驱等价实证（探针 live 档直跑面），arbitrate/merge 期必须保持绿（回归锁）；前置缺席=ENV_FAIL exit 2 点名",
     "python3 integration/t260922-03/sc_t260922_03_probe_live_cred_env.py", "ro"),
    # ---- t260922-06: dsh 升级前置——会话 id 寻址口径 / resume 专项收口（seam 矩阵 #5；真接缝=形状面）----
    # 票面根因经 create_plan 源码实证修正：0.1.5 原生支持自定义 id 寻址（目录名=encodeSegment(id)、
    # 头记录 id=自定义 id、findLog 全项目扫描），单点真源=自定义 id 本身、无需映射表；真崩点=
    # 插件 summarize 消费 0.1.5 已移除的 Session.events 形状。两条场景守【插件半边】（装配行为面
    # +装载/物化面），零 live 零凭据零网络秒级；读侧半边归 developer 引擎 UT
    # （server/engine/tests/test_t260922_06_resume_addressing.py）与 t260916-23 dualname 族；
    # 0.1.1/0.1.5 live 双版对照（验收④）归升级门槛机械段（RUNBOOK_GATE + probe --version），
    # 其 cold-start 缺口（探针 check_resume 无首次建档 spawn，0.1.1 基线也红）归 t260922-03/判据票。
    ("t260922-06-resume-seam-plugin-faces",
     "headless-resume 插件装配行为面（t260922-06 验收①②③的插件侧集成证据，灰盒 L2，fake-dsh 桩缝零网络秒级，全程 /tmp）：以临时桩包树（@deepseek-ai/dsh-agent/dsh-llm/dsh-session/schemastery——包名即接缝契约面）驱动真实 node.ts 公共入口 apply()，八个子用例收割 stderr/stdout/退出码/桩账本——F1 legacy（0.1.1 形状：events 数组、dsh-session 无 SessionSeq 导出）resume 成功 exit 0、自定义 id 原样进 agents.resume（不造 uuid=寻址真源即自定义 id 的装配级证据，验收①回归锚）；F2 v3（0.1.5 形状：无 events、eventAt+SessionSeq）resume 成功零回落（resume 命中 0.1.5 真会话形状）；F2E 双形状装配级 stdout 全等（同一轮 turn 两种会话形状同一聚合）；F3 会话形状不识别 → 「形状不识别…拒绝静默猜测」exit 1（验收②）；F4 agents.resume 返回缺 .agent → 守卫点名 + 「回落新建同 id 会话」显式宣告 + 同 id create 承接 exit 0（验收②+③合取）；F5 resume 失败+同 id create 失败（KI-059 撕裂链实况形状）→ 两级宣告带原始错因（报错精确）+「改用全新会话 id（上下文不可恢复）」+fresh id 承接 exit 0（上下文丢失大声说）；F6 无 resumeId 一次性 create 返回 null → 「agents.create 返回形状不识别」exit 1（第四处调用点；桩只备 create，误走 resume 即裸 TypeError 当场红）；F7 v3 seq 缺口 → 「seq 7 不可读（已捕获长度 9）」exit 1（取舍①装配级）；F8 fresh 位 create 返回 null → 守卫点名且两级宣告行不吞（第三处调用点）。全局判据：stderr 每行属词汇表形状（dsh:/dsh-headless-resume:/headless-resume: 前缀），零裸栈零「is not iterable」零 TypeError 字样（票面实证真崩点形状「不得复现」的机械形式）。判据锚语义短语与退出码/桩账本，不锚措辞全字面（KI-051 锚语义）。intent 分工：developer L1（server/headless-resume/test/summarize.test.mjs）守 summarize.js 纯函数语义，本条守装配面四处调用点守卫/回落链次序/SessionSeq 注入/退出码语义（纯函数单测过≠守卫接线在）；t260916-24/t260922-03 探针族守探针工具与 live 门槛判据，本条零 live 零凭据；t260916-23 dualname 族守读侧，本条守写/续侧插件本体（三面不互替）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；node/临时目录/子进程缺席=ENV_FAIL exit 2 点名，runner 真源缺席=产品红（探针同判）",
     "node integration/t260922-06/sc_t260922_06_resume_seam_faces.mjs", "ro"),
    ("t260922-06-resume-seam-plugin-wiring",
     "headless-resume 插件装载/物化面（t260922-06 方案 §5.1 头号遗留风险「TS loader sibling 导入」的机械代理 + 泳道物化缝守卫，灰盒 L2，零网络秒级，全程 /tmp）：本票把聚合逻辑拆到 sibling 模块 summarize.js 且 node.ts 以显式 URL 动态导入——装载缝一断症状是每次 spawn 开跑即死且只在物化副本上现形（引擎 copytree 整目录物化进泳道/容器，t260913-04 缝）。四子用例：W1 整目录拷贝（fs.cp recursive=物化 copytree 同语义代理）后在副本内按 node.ts 同款 URL 形状导入 ./summarize.js → 导出面齐全（summarizeSession/ShapeError/messages 十键词汇表）+副本内双形状 golden 输出等价（拷贝不改行为）；W2 node.ts 源内全部 new URL('./…') 相对引用逐个在插件目录内闭合（零匹配=URL 导入形状漂移=响亮红不静默）；W3 summarize.js 零依赖契约静态守卫（无静态 import/动态 import(/require(——头注文档化契约，破约=纯函数单测网静默死亡在此响亮）；W4 副本完整性 node.ts+summarize.js+test/summarize.test.mjs（物化不得静默丢件）。intent 分工：developer L1 在真源目录守 summarize.js 语义，本条守「拷贝副本仍自足可装载且行为不变」（真源单测过≠副本可装载）；live dsh TS loader 的最终裁决归升级门槛 live 双版对照（本泳道 implement 段 agent 会话「已恢复会话」行已是装载成功的在案实证）；faces 场景守装配行为、本条守装载/物化（两面不互替）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；临时目录不可用=ENV_FAIL exit 2 点名，插件真源缺席=产品红",
     "node integration/t260922-06/sc_t260922_06_resume_seam_wiring.mjs", "ro"),
    # ---- t260916-22: 巡检 agent 化（scan 段退役→inspect 段+发现级裁定）----
    # 分工三层：contract（灰盒 L2，活动级公开契约，桩缝全部子用例矩阵）→ journey（L3 真台
    # 真票全链旅程，验收①主证据）→ verdict-cli（L3 发现级裁定+假报跨期压制，验收④
    # 主证据）。与 developer 四件 UT（inspect_core/activity/flow/verdict）intent 分工：
    # UT 白盒随实现可重构，本组灰盒只钉公开缝名与用户可感知行为（缝契约留档见
    # integration/t260916-22/design.md Part3）。静态扫描退役致 t260910-11
    # -scan-misreport-calibration 整体退役（扫描器 S1 校准语义随 inspection_scan 退役
    # 作废，宿主令「不需要静态扫描」；检测半 ki051-anchor-replay/scan-contract 留守
    # ——旧票重放链仍在），登记与场景文件一并摘除。
    ("t260916-22-inspect-contract",
     "巡检 inspect 段活动级契约面（t260916-22 验收②③④的集成侧，灰盒 L2 纯离线，桩缝驱动 run_inspection_inspect/verify_inspection_findings 真活动）：①输出解析纪律——零围栏块/双围栏块/围栏外坏 JSON/findings 非清单/缺 evidence/severity 词表外/confidence 越界 → ok=false 且 reason 可读点名「哪个检查失败」（报错精确纪律）；②合法输出 → ok=true 且 meta 带 base_dir（复核基座=审查根承诺）；③证据机械复核八态——真引文/空白差异（缩进改版）→ verified；坏路径/../越界/绝对路径/行号超界/行号 0/引文不符 → unverified 且 reason 非空点名，verified 条目零 reason（降级必点名不静默丢，验收②）；④id=内容哈希——8 位 hex、同内容幂等、内容变 id 变（跨期去重键的机械铸造面）；⑤跨期三对照——上期同 id 标 recurring、裁定台账 false-positive 标 suppressed、纯压制票 summary 零计且 heartbeat=true（「假报跨期不再重复计数」契约半，验收④压制半）；⑥预算 41 条截断 ≤40 且带截断标记不静默丢（验收③截断半）；⑦零新发现且套件绿=heartbeat true、有新发现=heartbeat false（心跳=心跳证明不假绿）；⑧建议门 mix——verified&&conf≥0.6&&severity≥med 才进建议面（低置信/low/坏证据三反例）；⑨上期清单坏 JSON → 容错降级不 crash 且 reason 点名上期不可读（输入三态：畸形）；⑩红线判定化——全程被审查树逐字节不变+审查基座零 .dsh 残留（DSH_HOME 与基座解耦面，agent-home 目录语义容忍桩短路；真 spawn 面归 inspect-journey）。环境语义：temporalio 缺席=ENV_FAIL exit 2（离线活动驱动需 SDK 桩）。与 t260916-22-inspect-journey 分工：彼守真台真票全链旅程（真 spawn/CMD 链+超时+人门+落账），本守桩缝下活动级契约全矩阵（离线快、可进每轮基点）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260916-22/sc_inspection_inspect_contract.py", "ro"),
    ("t260916-22-inspect-journey",
     "巡检 inspect 段全链用户旅程（t260916-22 验收①主证据，灰盒 L3 真台真票，exclusive）：宿主手动触发一期巡检——agent 产出发现清单、证据机械复核、人门签字收口、发现落账、建议修复票只从「agent 判真」的发现出。混合桩子用例五类发现同票：verified（真引文锚夹具树真实文件行）/unverified（行号越界→降级+reason 点名）/低置信（不进建议）/low severity（不进建议）——建议门只收 verified&&conf≥0.6&&severity≥med；用户可见段名=inspect（scan 段退役的旅程面证据）；发现来源标记 scan==agent（schema 面）；人门两拍真拦（未签不终态/签后收口）；收口后落账留存（审计链=落账承诺面）。零发现桩子用例：空 findings 心跳票照开照收（heartbeat=true，全绿期=心跳证明）。真进程链超时子用例（SANDBAR_INSPECT_CMD 挂起脚本+inspect_timeout_min=2）：票到 blocked 点名「agent 未完成」不假绿+落账在+heartbeat 非真+agent-home 落台账目录（DSH_HOME 与审查基座解耦的运行时面）+进程 reap 干净（pgrep 零残留，资源生命周期纪律）。红线判定化：被审查树逐字节不变+基座零 .dsh。与 t260905-03-period-journey 分工：彼守单期全链旅程质量的通用面（旧签名链/心跳），本守 inspect 段新语义（段名/复核降级/建议门/超时不假绿/agent-home），journey_one 步骤共享 lib 夹具。环境语义：docker 测试台/venv 缺席=ENV_FAIL exit 2。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260916-22/sc_inspection_inspect_journey.py", "exclusive"),
    ("t260916-22-verdict-cli",
     "发现级裁定（verdict）落账与假报跨期压制（t260916-22 验收④主证据，灰盒 L3 真台真票，exclusive）：宿主对 agent 发现逐条裁定「假报/待修/存疑」——在途票 signal 通道（回执带 ticket_id、裁定落 face）与收口票直改台账两通道；who 闸 fail-closed（空 who/agent 角色名/超长 who/词表外 verdict/查无此 finding → 拒收且点名失败的检查项，报错精确纪律）；verdicts 台账 append 全留痕（同 finding 重复裁定 entries 不覆盖、票面取最新）；假报跨期压制——P1 裁假报 → P2 同内容发现（同机械 id=内容哈希跨期键）被压制点名、summary 零计、heartbeat 不破（「假报跨期不再重复计数」用户可感知行为，验收④）；deadman 词法子用例——-verdicts.json 非台账件不进漏跑/畸形清单（离线 deadman 纯查声明+台账，词法误报形态防线）。与 t260916-22-inspect-contract 分工：彼守活动级压制语义（纯 [dup] 票），本守 CLI 面+真票跨期全链（signal/直改/两期真票+裁定台账）。环境语义：docker 测试台缺席=ENV_FAIL exit 2。verdict 子命令未落地=FAIL（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260916-22/sc_inspection_verdict_cli.py", "exclusive"),
    # ---- t260916-21: admin.log 按天轮转 + 保留窗（默认 14 天）+ 同日过大顺切 + 审计写失败点名 ----
    # 与 t260910-06-ki067-entry-audit 分工见 intent：彼守入口收口/审计行形状/entry_hint，
    # 本条守日志文件生命周期面（轮转/归档/保留窗/同日过大顺切/写失败可感）；轮转原语纯函数矩阵
    # 归 developer L1（server/engine/tests）不同层。
    ("t260916-21-admin-log-rotation",
     "admin.log 日志文件生命周期面（t260916-21 验收①-⑥集成层，灰盒 L3，纯 stdlib 真子进程）：①跨日惰性轮转——活跃文件 mtime 本地日≠今日的首笔写入原子改名 admin.log.YYYYMMDD（归档名=文件关闭日）后续写新文件；同日多写零归档（一天一个反向锁）、落定后不二次轮转；②存量迁移考古——手工造两代 schema 行（旧 run_id/actor/name+新 call_id/source/sub，工单正文钦点）的现存文件跨日首写字节级原样归档（sha256 相等不删不截断）两代行照存；③多进程恰好一次+零静默分叉（两相）——相一=轮转写者×8 同栅栏竞速跨日首写：归档恰一份、无 rolling 残留、逐行 JSON 可解析（O_APPEND 单行完整性）、行数守恒、家族恰活跃+归档两文件；相二=轮转落定后纯按路径追加写者×4（tools_registry/node 插件同语义不参与轮转判定=review C1 混合写者普查面）+轮转写者×4 并发续写：全落活跃文件零丢失零重复家族不增（纯追加写者不进竞速相——先落笔会刷 mtime 掩蔽跨日态=出写集残留面，见场景报告）；④保留窗——默认 14 天（宿主 260916 定稿）过期仅删 admin.log.<8日>[-<6时>] 匹配面（缺省窗外 15 天档删/窗内 13 天档留=默认值行为锁），keep_days=30 显式桩可调生效，窗口内与命名面外（bak/形合日日期非法 20269999/同名目录条目）不碰不炸（review C3 畸形名容错）；⑤同日过大顺切（宿主定稿措辞：纯拆分无熔断告警语义）——admin_log.max_mb 桩小值当日切 admin.log.YYYYMMDD-HHMMSS 一刀、切后写新文件不连切、行数守恒；⑥配置面（宿主定稿：project metadata 不用 env 旋钮）——保留窗/阈值读引擎所属项目 project.yaml 顶层 admin_log:{keep_days,max_mb}（SANDBAR_PROJECTS_DIR 桩隔离，与 shared 装载器同注册表面），配置值畸形回落内置缺省 14/512 不炸不误删不误切；⑦写失败可感——SANDBAR_ADMIN_LOG 指目录=跨平台 OSError 桩：client.py 裸入口与 ticket.py 直 spawn 双公共入口回执均带 audit_write_failed 点名（marker 跨入口=审计先于打印的集成面兑现）+回执主契约 {ok,error} 不吞+stderr 留痕非空；SANDBAR_ADMIN_LOG 隔离全套生效+真仓 server/admin.log 起止 size/mtime 零接触（红线守卫子用例）。与 t260910-06-ki067-entry-audit 不同面（彼守入口收口/审计行形状/entry_hint/双行契约，其零回归由套件照跑保证）。环境口径：A/B/C/D2 段 stdlib 恒跑；D1（client.py 子用例）temporalio 缺失=ENV_FAIL exit 2 点名（D2 ticket.py 拒收子用例 stdlib 照跑），无 docker/真 Temporal/真 git 依赖。实现落地前红属预期（TDD 信号：A2/B1/D1b 红=轮转与点名未落地），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-21/sc_admin_log_rotation.py", "engine"),

    # ---- t260917-02: 调度路自愈重定向（旧 action 直发壳→t 形真票）+ 板面不可辨在跑可见 + 台账留史 ----
    # 三条 intent 互不重叠：①重定向+未跳（起票链写面，真台 exclusive）②板面读面（不可辨
    # 在跑降级可见+同期同注+两枚反用例，真台 exclusive）③台账留史事故回归（落盘函数边界
    # 不变式，离线 ro——engine 池不在每票闸清单，本条是验收③在闸内的唯一机械回归）。
    # 共享前置在 lib_t260917.py（无 sc_ 前缀）；跨票复用 t260905-03/t260916-02 两 lib。
    ("t260917-02-legacy-fire-redirect",
     "调度路径（旧 action 直发形态）自愈重定向用户旅程（t260917-02 验收①④主证据，灰盒 L3，真 docker 台+真专属 worker）：线上 260917 实况压缩复刻——①重定向子用例：直发旧 action 形壳（非 t 形 id、payload 无 project_key——线上原始字节逐字复刻，R2c 假绿防波堤）→壳秒级终（不扫描不落账不进人门，④结构前提）→真票承接：票号 t 形+SA 三件套齐且 ProjectKey==声明实例级身份（payload 缺 project_key 时身份回退链闭合）+票号日期段==期号日期段+台账恰好一份归属真票；真票进人门长挂（awaiting-human 在案=④的人门形态）；②未跳子用例（验收④主断言，review R4/C2）：interval(~10s) 自建调度（旧直发 action 形+OverlapPolicy=SKIP，1 日步长的机械等价——SKIP 只判上一 action 是否 Running）连续 fire 照常：num_actions 递增且 num_actions_skipped_overlap 保持基线不变（skip 以服务端 ScheduleInfo 计数直接断言，不由行为反推——C1 可观测面）+同期仍恰好一张 t 票（壳 deduped 复用）+调度无滞留 action；③dedup-closed 子用例（验收①复用半边）：真票收口后再来旧壳→deduped 不起第二张 t 票、(实例,期) 计数不增、台账不增；④deadman 回执子用例（review C1）：漏跑核查回执并 skip_count/running_actions 两键（additive，跳火可观测）且回执 ok。分工：t260905-03-period-journey 守手动全链旅程与人门审计链不同触发面；t260916-02-relocation-realchain 守聚合声明+新票链路（起票 happy 形）；t260916-02-board-legacy-three-state 守板面读面，本条守起票链写面；dedup 细粒度真值表（指针三态/撞号让位/grace 窗）归 developer L1 与 t260916-02 ⑦子用例；台账归档归 t260917-02-ledger-archive-regression，本条只断言壳不落账。资源回收：自建调度退出即删+STARTED_TICKETS 退出 cancel+夹具树/夹具台账拆除；docker 台/CLI/venv 缺件=ENV_FAIL exit 2。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-02/sc_inspection_legacy_fire_redirect.py", "exclusive"),
    ("t260917-02-board-unresolved-running",
     "板面可见性：不可辨在跑显式降级+同期同注（t260917-02 验收②主证据=260917「正在等人审的巡检跑在 UI 上不存在」事故回归，灰盒 L3，真 docker 台）：①不可辨在跑行上板：无实例/期 SA 且 id 非旧形词法的 RUNNING 巡检运行（今晨事故形态直发复刻）必须上板为显式降级行——行在场不静默丢失、不被悄悄归项目（identity_note 假设语气点名，锚语义不锚字面——KI-051 教训）、回执 kept_unresolved 键与闭合 dropped_unresolved 分账可辨；②闭合不可辨维持丢弃（僵尸纪律半边不动，本票只翻转在跑半边）+dropped_unresolved 计数在案；③同期 closed+awaiting-human 双行并存带注：真实触发票挂人门+SDK 直发同期 SA 票即取即闭（板面读面只认列表面，构造方式不进断言面）——两行都不隐藏，在跑行带 same_period_closed=<闭合票号> 注；④可辨但不在册实例 RUNNING 仍不上板（白名单纪律不因①放宽）。分工（与 t260916-02-board-legacy-three-state 对账）：彼守「可辨但不在册→不上板」与旧形三代降级读面（legacy 查询路径），本条守「不可辨但在跑→降级可见」翻转半边+同期同注+反用例钉死新边界（不同分支不矛盾）；t260915-08-board-rows 守行形状契约（快照对拍/R8 闭合窗）不同面。资源回收：StageWorker __exit__ 退出 cancel+夹具拆除；docker 台/CLI/venv 缺件=ENV_FAIL exit 2。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-02/sc_inspection_board_unresolved_running.py", "exclusive"),
    ("t260917-02-ledger-archive-regression",
     "台账跨票同名覆盖前归档留史的闸内回归（t260917-02 验收③=260917「91 条覆盖 89 条无归档」事故回归，灰盒 L2 离线，落盘函数公开边界）：①跨票覆盖→归档产生、旧记录 json 可读且内容==旧跑、canonical==新跑（每期一份语义不变）；②同票自身重写不归档（每跑一份以票为界）；③畸形旧件（坏字节）原字节整体搬移留痕（corrupt 标记）不拦新写；④缺 ticket_id 的畸形 json 旧件按他跑归档字节可读（身份不明≠丢弃——外部输入畸形三态）；⑤套件回执跨票覆盖同规则归档（同族面不漏——KI-055 实报即全族）+archive/ 不进 deadman 期号集合（台账扫描不污染）；⑥同秒连续两次跨票覆盖归档件逐次并存（修复自身不得含静默覆盖——review R3）；⑦归档失败不拦新写（系统态条件子用例：chmod 不可扰环境=N/A）。分工：developer L1（engine 池）守归档真值表全组合与回执键形状——但 engine 池不在每票闸清单（verify.yaml exclude_pools），本条是验收③在合并闸内的唯一机械回归（KI 事故回归纪律）；真链路台账行为（壳不落账/真票落账）归 t260917-02-legacy-fire-redirect R1f，本条只守落盘边界留史不变式。纯离线零网络；temporalio/venv 缺件=ENV_FAIL exit 2 点名（inspection_flow 导入面）。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-02/sc_inspection_ledger_archive.py", "ro"),
    # ---- t260917-08: agent bash 沙箱不可用=一等环境信号（env_fail）+ 移交命令 worker 承接（离线桩）----
    ("t260917-08-env-fail-handover",
     "agent 执行面环境不可用成为一等环境信号+验证交接承接（t260917-08 验收①②主证据，灰盒 L2 离线桩，零网络零 docker，可注入桩复现 t260917-05 实证形态）：①承接执行子用例：run_handover_legs 真跑 3 条命令（过/红 exit 3/畸形 cmd 解析失败不执行）→单列计数 ran=3/过=1/败=2、details 名全带 handover: 前缀与场景明细同形状、主口径 ran/passed/failed 保持缺省 0（红线④机械面：移交命令单列计数不进任何闸判定）；②信号+文案子用例：classify_env_block 命中 t260917-05 日志原话桩串（sandbox_apply denied）与 KI-083 消息（no sandbox backend）——实证/外部输入用固定桩串复现不靠真故障；_apply_env_signal 以 tmp 日志文件桩补位归因（[worker 归因] 前缀与自报可分辨、agent 自报优先不覆盖）；dev_lane 壳 blocked 文案点名「agent 沙箱不可用（环境）」+明示非实现缺位+出路（retry_qc/rework）+票不停摆声明（信号与阶段 status 不混同）；③承接机制子用例（review C1）：移交命令入 meta['env_handover_pending'] 债表→拾取→销账→二轮拾取为空（不重复执行）；无子用例可交不造垃圾债；④空清单子用例（R4）：env_note_for(env_fail+空清单) 点名「不当作已验证」+弃单记名进注记（不静默丢）、ok+env_fail 不误报失败文案、仲裁契约句在场（env_fail 段=验证未闭环不得当已验证）；⑤旋钮剥除子用例（review R2/L4）：三桩旋钮注入本进程 env→命令子进程 env 自报全 MISS、对照变量可见（桩行为不漏进被测子进程换假行为）。分工：developer L1（tests/test_t260917_08_env_fail_signal.py）守归一化全组合/解析点透传/超时排空/源码锁，本条守离线消费路径的端到端行为语义（登记入闸的机械回归）。资源回收：子进程命令只跑 python -c 短命令全终态（超时路 kill+wait 排空），tmp 目录一次性。引擎模块（temporalio/venv）缺席=ENV_FAIL exit 2 点名不假绿。实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-08/sc_t260917_08_env_fail_handover.py", "ro"),
    ("t260917-08-env-signal-boundary",
     "env 一等信号的活动边界装配（t260917-08 验收①入口面，灰盒 L2 离线桩，零网络零 docker，与 t260917-08-env-fail-handover 分工：彼守离线消费面（命令执行器/债表/文案/R4 空清单），本条守装配面——内部函数单测过≠入口接线在）：①桩旋钮注入→真实活动入口（temporalio ActivityEnvironment 驱动共享段实现）→ 回执 status=ok（信号不翻转红绿，红线④正面）、env_fail=true、env_reason 自报原文保真、合法条目归一保留、畸形子用例记名 dropped 不静默丢、磁盘结果文件四新键成套在位（结果契约层=幂等锚点）；②幂等缓存重放不丢信号（t260917-05 实证承接形态：worker 死在交付后归位前 → 同 result_file 二次调用走缓存 → env_fail/子用例/弃单全数存活，N2 并集保留）；③缓存命中+日志扫描补位（M1 挂点①行为面：旧格式回执无 env 键+spawn 日志含 t260917-05 原话 → env_fail=true、[worker 归因] 前缀与自报可分辨、点名 sandbox_apply；对照=日志读不到零改动不硬造）；④归因不污染（对抗面，M1 裁定②：桩路径有意不挂日志扫描——桩回执无旋钮+陈旧日志含 sandbox 字样 → env_fail 恒 False、子用例/弃单均空；钉死「为归一化把扫描挂上桩路径」的回归，陈旧日志不得伪造环境归因）。资源回收：全产物 tempfile 一次性清理、env 旋钮用后恢复、无子进程。环境缺件（venv/temporalio）=ENV_FAIL exit 2 点名不假绿；实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-08/sc_t260917_08_env_signal_boundary.py", "ro"),
    # ---- t260916-23: dsh 升级前置 T1——引擎读侧会话文件双名兼容（session.jsonl.zstd ∥ session.v3.jsonl.zstd；新名字面来自升级评估 260916，不符时单点常量即回）----
    ("t260916-23-session-dualname-faces",
     "会话文件双名兼容读侧·检疫与统计两面（dsh-upgrade T1 验收②py 子用例，灰盒 L3，零网络零 docker）：dsh 0.1.5 换名后引擎读侧双名发现。检疫面：①双名并存·新名好帧内撕裂→挪隔离区留档、旧名健康档原位（接住新代名）；②双名并存·旧名撕裂→照挪（检疫是全量清查不吃「组内取最新」——回退 dsh 0.1.1 不卡同一坑，epic 可回退原则的正面断言）；③双名全健康对照组→双双原位隔离区零新增（防「见档就隔离」反向事故）；④v3 名是目录→不检疫不崩（is_file 守卫防连锅端）。统计面：⑤双名并存组内只计 mtime 最新一份+跨 slug 目录各计（防两代双计/防全局只取一份漏计）；⑥旧名 mtime 更新→计旧名（最新语义与代数无关）；⑦仅新名→计新名（升级后新会话可统计）；⑧一层/三层深的同名旧名档不入集（发现半径钉两层=纯名字层加宽，「当前树行为逐字节不变」的半径钉子）；⑨零会话→tokens_zero 且 reason 含新名字面（文案与实现一致，验收④运行时子用例）；⑩v3 名是目录→统计不崩不计。断言面=文件系统结果+聚合返回值，不锚隔离文件名细节与日志。intent 分界：与 t260905-10-torn-session-quarantine 不同面（彼守单代撕裂检疫语义/恢复旅程/挪不动兜底）；与 t260904-09 settle 旅程不同面（彼守旧名统计旅程与快照落盘幂等）。实现落地前红属预期（TDD 信号：①⑤⑦⑨红、其余为双向回归钉），arbitrate/merge 期必须绿；zstd 缺席=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-23/sc_session_dualname_faces.py", "ro"),
    ("t260916-23-session-dualname-ts-faces",
     "会话文件双名兼容读侧·workbench 三消费面接线（dsh-upgrade T1 验收②ts 子用例，灰盒 L3，零网络零 docker 零浏览器）：用量页/实时面板/KB 徽标三端点会话发现双名化（resolveAllSessionFiles/resolveSessionFile/_sessionKbFast——后两处为票外同形坑，review 裁决纳入）。①用量页双名并存逐 <sub> 目录恰取 mtime 最新一份、多 sub 全收、别工单不混入（防双计/防漏）；②仅新名收新名、仅旧名收旧名（两代方向各一子用例）；③实时面板 exact 角色优先不破+exact sub 内取最新代（升级后活水面选中语义不断）；④KB 徽标取全局 mtime 最新代+旧扁平 session-*.zstd 兜底不破（agent-logs 260825「升级后静默恒 0」前科的回归钉）；⑤零会话 reason 含新名字面（文案与实现一致）。断言面=导出端点函数返回值，不锚内部 helper——与 developer 五态 UT 不同面（彼守 helper 单元语义，本条守三端点接线：helper 建了没接线/接错面在此现形）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；node<22.18 或 zstd 缺席=ENV_FAIL exit 2 点名",
     "node integration/t260916-23/sc_session_dualname_ts_faces.mjs", "ro"),
    # ---- t260916-28: 泳道 .dsh 缺 headless profile 的静默失效（spawn 前预检 + 六站分流 + 补件自愈）----
    ("t260916-28-lane-dsh-missing-profile",
     "泳道 .dsh 缺 headless profile 的静默失效全链（t260916-26 实报形态的端到端回归，灰盒 L3，真 docker 台+票专属 worker+假 dsh 桩）：SANDBAR_AGENT_CMD='dsh --profile sandbar-headless'（首词 dsh=预检触发条件本体）+PATH 前置假 dsh 桩（control 分行为：默认写合法回执、arbitrate 带 verdict=pass 防格式纠正混入；prune 列表 stage=删候选链源 profile 与泳道 .dsh profile 两处——host 形态泳道 profile 跨段持久、prep 有 exists 守卫，只删一处无法使泳道面缺件）+worker DSH_HOME=源 home/HOME=空 tmp home（候选链全空前提，不靠宿主真 home 运气）——一票串三子用例：子用例A 开票即源无 profile→create_plan blocked 点名（blocked_reason 含「泳道 .dsh 缺」「sandbar-headless」、绝不含「agent 活动故障」；blocked_detail.reason_code=lane_dsh_profile_missing；桩账本零 create_plan 记录=预检拦在 spawn 前）→补源+retry_qc 自愈（create_plan 真跑通过、账本有记录）；子用例B review_plan 桩两处删→impl fork 两边均撞预检→blocked 点名（含「agent 报失败」+「泳道 .dsh 缺」；timeline 无 rework、handoffs 无「实现完成/集成测试集就绪」假交接——failed 回执绝不被汇合边吞成完成）→补源+retry 两边重跑（implement/design 账本各恰 1 条）；子用例C design 重跑桩再删→arb_acc fork 双拦→blocked(arbitrate) 点名且绝无「缺 verdict= 标记」虚报、无「格式纠正」账→补源+retry→arbitrate verdict=pass 恰重跑 1 次→滞留 failed 的 acceptance 回执被门消费 blocked(acceptance) 点名、绝无「验收走查打回」假叙事、全程零 rework→补源+retry→acceptance 重跑 ok→票到达 merge_check（全链自愈终点；其后终态不判，t260912-03 同口径）。轮次判定用 snapshot.retry_count 阈值防旧 blocked 串台。实现未落地=产品红（TDD 信号），arbitrate/merge 期必须绿；docker/镜像/temporal CLI 缺席=ENV_FAIL exit 2 点名；审计钩子禁生产端口（终局账本空断言）。分工：t260905-10-host-ruling-injection 守 blocked 态注入面、t260908-01 守 KI-061 超限复活面，本条守缺件预检与 failed 回执分流面，不互替",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260916-28/sc_t260916_28_lane_dsh_missing_profile.py", "exclusive"),

    # ---- t260916-29: worker 停机 grace 契约（引擎 P1：优雅停实为立即取消）----
    # 与 developer 引擎侧 selfcheck（进程内桩 activity：grace 对在飞活动的收尾效果/
    # 取消归因/重跑兜底）分层——零模型 L3 起不了真 agent 段，彼面归引擎侧台；本组钉
    # 真实 worker.py 进程面的公开契约（旋钮取值/容错/透传接线、console 崩溃收养路
    # 语义）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t260916-29-worker-stop-grace-knob",
     "worker 停机 grace 旋钮契约经真实 worker.py 进程面（t260916-29 要求①，灰盒 L3 docker 舞台）：停机宽限不再是无旋钮硬编码 0（=立即取消在飞活动，260916 两轮全票假「agent 活动故障」第一现场）——子用例1 缺省=不设旋钮 SIGTERM 后 SDK 停机日志 will-wait 非 0（钉「非 0」不钉具体秒数，调参不破测试）+停机点名行在文（在飞活动点名面的空表形态）；子用例2 显式 0=逃生门（will wait 0:00:00，立即取消保留为运维显式选择）；子用例3 畸形三值（abc/-5/NaN）=不炸启动不采信畸形回缺省非 0（消费外部输入三态纪律，解析矩阵归 developer UT 不同层）；子用例4 显式 2=值透传 SDK（will wait 0:00:02，旋钮→Worker 接线的端到端证明——helper 级 UT 断言不了调用点真展开，恰是本票缺陷原始形态：helper 在接线缺）。每子用例附带 TERM 限期干净退（exit 0）守卫。分工：t260905-02-worker-lifecycle=进程生命周期（起/退/meta/异常输入）不涉 grace 取值；t260916-29-console-crash-graceful-stop=崩溃收养路语义，本条=直接信号路旋钮矩阵；developer selfcheck（方案场景A/B 进程内桩 activity）=grace 对在飞活动的实际效果（收尾/归因/重跑），零模型 L3 起不了真 agent 段归引擎侧台。旋钮名 SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC=本票方案定稿公开契约；SDK 停机日志=工单取证逐字来源（KI-051 正则锚）。被测子进程零连生产（审计钩子+自证子用例）；docker 台缺席=ENV_FAIL exit 2",
     "python3 integration/t260916-29/sc_worker_stop_grace_knob.py", "engine"),
    ("t260916-29-console-crash-graceful-stop",
     "console 崩溃收养路必经优雅停（t260916-29 要求①③的崩溃形态面，灰盒 L3 docker 舞台）：260916 事故形态②——console 被 SIGKILL/崩溃（dispose 跑不到）→票 worker 被 launchd 收养（ppid=1）→ppid 守卫自退；修复前自退路径同样 will wait 0:00:00（立即取消在飞段），崩溃路=烧段第二现场。子用例A 收养路缺省 grace=短命父拉起真 worker（watch 两 env 同置、监视不存在的 workflow id=查询失败不误退、票队列指空队列零活动领取面）→收养→限期自退（进程消失+自退语义日志在文）+will wait 非 0；子用例B 收养路旋钮=2→will wait 0:00:02（旋钮贯通崩溃路）；子用例C 直接信号对照（同 watch 形态、父存活、直跑子进程）→SIGTERM→grace 非 0+exit 0——保证场景不全部子用例 N/A（三态契约），并钉生产票 worker 形态下信号路同样优雅。N/A 仅给「收养目标 ppid」系统状态条件（macOS=launchd(1)；Linux subreaper 可≠1），恒不全部子用例 N/A；收养观测 ps 主通道+pgrep -P 1 回落双通道（ps 被拒沙箱可真判），双通道皆盲才 N/A；收养子用例被测进程非直跑子拿不到 returncode，终态=进程消失+自退日志（rc 面由子用例C 同形态承载）。分工：t260905-02-ticket-worker-watch-exit=自退三态（收口/收养/查询失败不误退）+meta 自清（清理面），本条不复断其任何一面，只钉自退那一刻的 grace 语义与旋钮贯通；developer selfcheck=grace 对在飞活动实际效果归引擎侧台。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；被测子进程零连生产（审计钩子+自证子用例）；docker 台缺席=ENV_FAIL exit 2",
     "python3 integration/t260916-29/sc_console_crash_graceful_stop.py", "engine"),

    # ---- t260917-05: 会话发现面零静默降级（T1 双名遗留：文件在、名字/格式对不上解析面必须响亮）----
    ("t260917-05-session-face-loud",
     "会话发现面零静默降级·engine 统计/检疫面（t260917-05 票面验收①②，T1 双名遗留的格式层，灰盒 L3，ro 池纯文件系统）：token 统计与坏会话隔离面对「本目录存在会话文件但名字/格式对不上本版本解析面」必须响亮、绝不静默 0——子用例A 双名+健康样本（本票+<票id>-developer 两目录入统计、他票不混入、note 干净=T1 回归锚）；子用例B 合法 zstd 帧包非 JSON 文本→note 票面例句（格式不认识/疑似 dsh 版本不匹配/统计值不可信）+点名文件+format_suspect 注记+tokens 记零不静默；子用例C 好+坏混合→金额只来自好文件而 suspect 注记与坏文件点名仍在场（部分降级不静默）；子用例D 刚启动边界（有事件无 usage/空档/纯空行）→保留既有「无 usage 事件」人话、不冤枉格式（防误报方向对抗子用例）；子用例E 发现集空而目录有他票三层/旧扁平/未知名三样→三类分流点名（前两类=未入统计、未知名=疑似 dsh 版本不匹配）+suspect_unmatched 注记；子用例F 30 个未知名档→点名单有界不膨胀（settle note 进不可变账本，MERGE_FILES_CAP 同纪律）；子用例G 检疫盲区→未知名会话样文件 warning 点名「隔离面未覆盖」且不挪不解析，健康/旧扁平档不动也不点名；子用例H TS 半同构判据（node>=22.18 type-stripping 子进程直调 lib_face_probe.mjs，implement 段补）→resolveAll 双名全取/健康无 suspect/混合态 suspectDetail 浮出/发现集空按类点名+suspectFiles/agent-live 单文件面 resolveOne 同点名。断言面=聚合返回的 note/tokens 契约+文件系统结果+root logger 捕获+TS probe JSON，零网络零 docker。实现段落地前红属预期（TDD 信号：B-G 判据未落地），arbitrate/merge 期必须绿；与 developer L1（判据纯函数 UT、检疫 UT）intent 不同面：本条守多文件合成后的整串 note 与三态分流/封顶/盲区整行为",
     "python3 integration/t260917-05/sc_t260917_05_session_face_loud.py", "ro"),
    ("t260917-05-session-face-loud-host",
     "会话发现面零静默降级·workbench 宿主面（t260917-05 要求③的数据契约面，灰盒 L3，ro 池）：用量/发现面对「文件在、名字/格式对不上解析面」必须响亮——UI 提示行吃的就是这份 {exists,reason,suspect,suspectFiles} 契约（渲染归组件 UT，本条守 UI 吃到的数据不静默）：子用例A 双名回归锚（两角色目录全取、他票不混入、加总 11/22）；子用例B 合法帧包非 JSON→exists=false+reason 票面例句+suspect=true；子用例C 好+坏混合→exists=true 金额来自好文件而 suspect=true 且 reason 点名坏文件；子用例D usage 对象缺全部已知键→suspect=true（dsh 改字段名形态）；子用例E 刚启动边界（有事件无 usage/空内容）→既有「刚启动」人话保留、suspect 不置位（防误报）；子用例F 发现集空而目录有他票/旧扁平/未知名→reason 三类分流点名+suspectFiles 含未知名（机器可读面）。node 直跑 src/host 模块（type-stripping=宿主半真实消费形态），zstd/node 缺席=ENV_FAIL exit 2。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；与 smoke/agent-usage.mjs B/C 段 intent 不同面：smoke 守单点降级与防穿回归（解压失败类），本条守三态分流与混合合成的整结果契约",
     "node integration/t260917-05/sc_t260917_05_session_face_loud_host.mjs", "ro"),
    # ---- t260917-04: 仲裁闸拒分支 patched 门——事故本体复现＋在飞回放兼容（事故回归闸）。
    # 激活语义（诚实直落）不在此断言：main 常量 id 形态有已知「唤醒不激活」缺陷
    # （KI-094，follow-up 门升级 base#seq per-entry），钉住=把缺陷写进契约。
    ("t260917-04-arb-refusal-replay-compat",
     "仲裁闸拒分支的 patched 门契约：事故本体复现＋在飞回放兼容（t260917-04，灰盒 L3 真/docker 台两代 worker 全保真子用例，ki061-replay-compat 同形态）：t260917-01（373741c）在 dev_lane 仲裁段新增 settle 闸拒直落分支未过 workflow.patched 门 → 在飞 t260916-19/-21 重放即 NondeterminismError（TMPRL1100，查询/推进全拒、stage 变 None）；main 侧紧急收口 2c1b4ee 补常量 id 门。本条精确复刻事故旅程再用被测树断言修复契约，零测试开关依赖（main 无 SANDBAR_TEST_DISABLE_ARB_REFUSAL 开关；pre-fix 形态由更早历史代码构造——373741c 出生的票当场走诚实脸，格式脸只属于 history 早于分支的票，v3 试跑实证）。子用例一用 git archive 1bf8d15（闸拒分支尚不存在的历史代码）起 worker 驱动票连收闸拒回执 → 旧路径把闸拒计入格式轮次（blocked_reason=「N 次缺 verdict= 标记」误导脸＝-19/-21 旅程与现形态留证）→ replay_check 用现行树代码只读回放该 history 断言 ok=true（事故回归闸；机制注记：该 history 走并行汇合路径，未落门树的纠正用例分支在重放中命令巧合——continue 后重排的下一命令与旧路径重合、终局双方皆零命令 wait 任务，重放只核命令流 → 未落门/已落门两态皆绿，v4 实证；事故的命令可见分歧面在串行仲裁分支＝fork memo=False 老票被分支跳过纠正活动命令＝「No command scheduled for event 201」报错形态，该面由 implement 段 S4 真票 -19/-21 replay_check 与 L1 源码锁承接，本条不构造上古 ref 串行票）；子用例二换现行树 worker → retry_qc 发信被受理（事故痛点面：唤醒不再被 Temporal 拒绝）→ 唤醒穿越老 history＋（树上已带门时）patched 求值、仲裁边真重跑 → 票仍可查且回到连贯 blocked → replay_check 回放全 history（老历史＋换码续段）再 ok=true（在飞票跨代码边界完整形态）。造拒刺激=桩回执 summary 直带机读键（shared.arbitrate_settle_refusal 判序 2 文本兜底契约面、t260917-01 除名场景 rogue 手法命中后的回执文本形态），非物理 rogue 文件——settle 路径闸的 lane dirty 文件判定面归 t260917-01 UT/其 L1 场景，本条只锁 workflow 侧分支语义。断言边界（防 rot 防钉缺陷）：激活语义（闸拒直落诚实脸/机读键上票面/计数解耦）不断言——main 常量 id 形态存在已知「唤醒不激活」缺陷（KI-094：在飞票首评落重放段 memo 固化 False，救治语义对停环票未达，follow-up 门升级 KI-061 base#seq per-entry），激活半边归 follow-up 票场景；patched marker 只作诊断不作断言锚（SDK 事件形态防漂移）。分工：与 t260908-01-ki061-replay-compat intent 不同面（彼锁 KI-061 唤醒重置 patch 的重放兼容/复活旅程，本条锁仲裁闸拒 patch 的重放兼容＋换码唤醒连贯）；与 developer 源码锁 test_t260917_04_replay_gate_lock（L1 形态/语义锁）不同层；t260917-01 场景已除名（nestedGuard 自守非形态否决），本条承接其「闸拒≠缺 verdict」痛点面的留证半边。三态：docker/镜像/舞台缺件、git archive 归档失败、replay_check 自身基建面（results 空＋error 在场＝connect/取历史失败，review R1 细则②：不记票红也不记票过）＝ENV_FAIL exit 2；回放分歧/断言破面＝exit 1——两子用例核心对未落门/已落门两态皆绿（机制注记见子用例一），arb/merge 期必须绿；零碰 3099/7233/8233",
     "python3 integration/t260917-04/sc_t260917_04_replay_compat.py", "engine"),

    # ---- t260917-07: 测试台命名空间一致性看守（一仓两个现役台名事故回归）----
    ("t260917-07-test-ns-consistency",
     "测试台命名空间一致性看守（t260917-07，主树不一致「一仓两个现役台名」事故回归，灰盒 L1 离线）：契约真源=server/docker-compose.test.yml 的 SANDBAR_TEST_NAMESPACE 缺省插值（恰 2 处且相等，记 C），四层锚定 fail-closed——integration/stage_docker.py 全部 opts.get(\"namespace\") 回落（恰 2 处）==C（起台入口显式覆盖 compose 声明=本票事故真源形态）、integration/baselines/ticket-lifecycle-scenes.mjs TEST_NS（恰 1 处）==C（保护文件只读断言，收口随人审放行或 main 直修）、integration 树 .py/.mjs 引号旧名字面量必须行含 naming-compat 且锚在 ALLOW 册（file→最大出现数→逐条理由）双锁内（单 marker 注释不得洗白——旧名漂移存活通道即此）、docs/testing-guide.md 与 integration/README.md 旧名表述零残留；锚缺失/数量≠预期/值不可解析一律红（vacuous pass 即本票钉死的静默漂移反面，KI-051 同族）；自证红绿=tmp 合成样本（干净样本绿/漂移样本红/锚缺失红/锚数异常红/双锁语义红绿/扫描器不误伤无引号注释）。与 t260910-11-temporal-isolation-guard 分工：彼守测试子用例不写生产台（目标面红线），本守测试台命名空间名全仓一致（名字面漂移）；与 t260907-04 命名看守分工见场景头注（契约值一致性 vs 全树旧标识零容忍，注释/文案面归彼不重复设防）。纯 stdlib 秒级零网络；实现落地前红属预期（TDD 信号，baselines 收口前 c 条+字面量条红=如实记账），arbitrate/merge 期必须绿",
     "python3 integration/t260917-07/sc_test_ns_consistency.py", "ro"),

    # ---- t260917-09: tests_rounds 上限连续语义 + 假封防护（260917 三票假封实证） ----
    # 三票共性=产品面干净、余红为环境/负载/存量第三方问题，但累计计数已达 6 → 一律
    # 转人工。本组两场景分层：streak_reset 锁「连续语义复位边」（code-fault/rework
    # 重入清零 + 上限对照），false_escalation_guard 锁「不计轮豁免面」（抖动/环境红
    # 不计入、不在册保守计轮、豁免超限面 authorize 真消费）。实现落地前红属预期
    # （TDD 信号），arbitrate/merge 期必须绿；docker/镜像/舞台缺件=ENV_FAIL exit 2。
    ("t260917-09-tests-streak-reset",
     "tests-fault 上限连续语义端到端（t260917-09 要求①②/验收①④，灰盒 L3，真 docker 台+桩脑序列桩+工单专属 worker）：shared.py:287 注释口径「连续 tests-fault 轮」兑现为行为——任何非 tests-fault 边后计数清零，长票不再被陈年轮次假封（260917 三票 t260916-19/-21、t260917-04 共性机制），上限本体不拆。相一 code-fault 复位边：桩判决序列 tf,tf,code-fault,tf×5+耗尽回落 pass（耗尽回落=主子用例确定性终态，防第 N+1 判决撞上限致场景自身假红）→ 打回 implement 后计数清零，后续 5 轮计 1..5 恒迭代、第 9 判决回落 pass 进 acceptance 全程不 blocked，handoff「测试集迭代（第 1 轮）」≥2 次（复位签名）+code-fault 打回边在场；旧累计语义第 8 判决必 blocked（语义反转强断言）。相二对照子用例：恒 tests-fault 第 7 判决 blocked，回执含「超限」且 authorize/rework/ruling/pause 出路关键词全在（要求④出路可执行，不许只写「转人工判读」）。相三 rework 重入复位边：tf×5 邻界（预增判定恒不封）→人 op=rework 打回 implement→重进测试段清零→再 2 轮 tf 计 1..2+回落 pass 推进不 blocked，「第 1 轮」≥2+implement 段重入证据在桩账本；旧语义重入不清零第 7 判决必 blocked——「被外部打断的长票必然累积到上限」的直击面。验收①矩阵 [tf,tf,pass,tf×4] 在 L1 纯函数层（developer 交付）：pass 判决直接路由 acceptance，复位只在重入时可观测，故 L3 钉 code-fault/rework 复位边（与 pass/authz 复位共用单点收口）。分工：t260908-01 sc_ki061_* 锁超限唤醒复活（KI-061）；t260912-03 sc_authz_* 锁 cap 面 authorize 通道；同票 sc_tests_false_escalation_guard 锁豁免面——不同面不互替。序列桩为本票自有（lib_ki061 桩是常量 verdict）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/镜像/舞台缺件=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-09/tests/sc_tests_streak_reset.py", "engine"),
    ("t260917-09-tests-false-escalation-guard",
     "假封防护面（t260917-09 要求③④/验收②③，灰盒 L3，真 docker 台+真 verify_lane integ 道+夹具迷你执行器+工单专属 worker）：tests-fault 但红属「负载抖动」（红项当轮串行复跑全绿，KI-072 同族：并发假红单跑绿=t260916-21「6 闸拦复跑 6/6 全绿」形态）或「环境面红」（env_fail>0 且产品红=0 且闸拦=0，=t260916-19/-04 形态）时该轮不计入上限。抖动子用例：夹具案首跑造记并红、复跑绿（marker 确定性形）→首轮不计入（票面留痕「不计入」+点名红项），其后红项已绿照计→第 8 判决才封（计 6>5；无豁免第 7 判决即封=计数算术强断言）。不在册子用例：陈旧红项名（刻意不在注册表，基线改名/闸拦面遗留形态）→探针 fail-closed 保守计轮并票面点名「不在册」→第 7 判决封（计数与旧语义同形=回归稳定面；点名=新行为钉子，封死死源静默当全绿）。环境失败分支：确定性环境红（not-checked+external 经真闸归属 record 不拦）→每轮豁免→第 6 轮连续豁免撞独立上限 blocked（出路文案在）→人 op=authorize 接受本判决+retry_qc 唤醒→复位计数推进 acceptance（uses≥1+handoff 点名接受与豁免面）——authorize 在豁免超限封面必须真消费（C2 新消费点；t260912-03 锁的是 cap 面通道，本条锁豁免面消费，不同面）。夹具链=真闸契约（规范行+INTEG_SUMMARY 五键+红面 rc≠0），mini 执行器为场景自有资产随夹具仓落库；闸拦面红项（真回归基线拦）的并集半边由 developer L1 钉（L3 强造基线竞态会引入不定性，诚实不造）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；docker/镜像/舞台缺件=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260917-09/tests/sc_tests_false_escalation_guard.py", "engine"),
    # ---- t260919-02: 终态失败票两面可见（列表失败行 + 详情失败面）----
    ("t260919-02-terminal-face-board",
     "终态失败票两面可见引擎契约（t260919-02 验收①②③主证据，灰盒 L2 离线，stub temporalio+过滤串忠实桩，共享夹具 _stub_temporalio）：终态失败票（FAILED/CANCELED）列表行不再显在跑（status/stage_state≠dispatched/running、不与 closed 混同、exec_status 失败标记在行、标题诚实无「查询超时/刷新重试」占位符——KI-018① 错误文案不进数据字段的注入子用例）、巡检行票身份（实例/期）不丢；dev-lane 失败行不再被缺省推在跑+行键集 parity（不加新键，t260915-08 R9 口径）；终态详情=kind:terminal（KI-025 分级零退化）+文案仍「刷新无效」（绝不诱导刷新/绝不瞬时/绝不存在，含否定形式也算）+可渲染失败面 face（执行状态/失败原因串/终态时刻/票身份/无快照及为何无显式说明——绝不空面）；反用例=原因不可得→显式「原因不可得」+执行状态保留+绝不编造；畸形子用例=desc 无 close_time 属性+SA 读炸→face 显式降级不崩、kind 仍 terminal；资源子用例=失败票零 snapshot 白烧查询（终态永不可查询，KI-003 族超时窗）；回归用例=RUNNING/COMPLETED 窗内/TERMINATED 混合板各行其形不串行+TERMINATED 不上板且零查询（僵尸纪律半边原样）。分工：t260903-06-query-kind-no-lie 守 kind 分级全链谎报面（dev-lane 形），本条守终态失败票的「面」（失败行形状+face 载荷）不重复彼分级矩阵；t260915-08-board-rows 守巡检行形状/R8 闭合窗/白名单僵尸（彼时无终态失败子用例），本条守失败类新面；t260916-02-board-legacy-three-state、t260917-02-board-unresolved-running 守旧形三代/不可辨在跑不同面；UI 词表与失败面视图呈现半边归 t260919-02-failed-state-ui-model。纯离线无 ENV_FAIL 子用例。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260919-02/sc_terminal_face_board.py", "ro"),
    ("t260919-02-failed-state-ui-model",
     "终态失败票 UI 词表契约（t260919-02 验收①「四态×文案对照」呈现半边+验收②失败面视图纯函数半边，灰盒 L2 组件契约，node 直 import 纯函数源，零浏览器零 3099）：deriveTicketState 真值表——失败族（FAILED/CANCELED/TIMED_OUT/未知新终态）→failed 与在跑可辨、缺 exec_status 现四态逐条旧值不变（存量行零扰动）、CONTINUED_AS_NEW 转场态不显失败、畸形 exec_status（数字/对象/数组/布尔）不 throw 落五态内、断链防御子用例（exec_status 缺失但 status/stage_state 词面 failed→failed——失败行不得因键断链回退显在跑）；「已失败」文案与四态文案互异可辨；chips 接线（countByState/filterRows 认 failed 键）；合并排序 failed→tier0 置顶（死票不沉底）；terminalFaceView 失败面视图——全字段 face 渲染（执行状态/原因串/票身份/无快照说明）、原因不可得→显式「原因不可得」+执行状态保留、畸形 face（null/串/数字/数组/空对象/undefined）全降级不抛不编造、视图=纯数据零函数值字段（失败面零操作入口的数据面前提）。分工：workbench/tests/t260904-17-ticket-list-model.mjs（developer L1 随票扩）钉词表快照与缺省行、ki025_show_error_split.mjs 钉 410 分级纯函数，本条在集成层独立钉「失败可辨」端到端词表契约+失败面视图降级面，不重复彼两面任何断言；引擎数据面（行形状/face 载荷/文案）归 t260919-02-terminal-face-board 不同层。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；node 缺席=ENV_FAIL exit 2 点名",
     "command -v node >/dev/null 2>&1 || { echo 'ENV_FAIL: node 缺席'; exit 2; }; node integration/t260919-02/sc_failed_state_ui_model.mjs", "browser-free"),
    # ---- t260920-01: 供给面判据接线+等待预算（stage-ops 票①，治「供给失败被计轮→假封」）----
    ("t260920-01-supply-assembly-seam",
     "闸出口×引擎签名消费接缝（stage-ops 票① 要求①④，灰盒 L2.5 离线，admin.py 真入口+真 verify_lane+真 dev_lane 模块）：t260916-25 第 10 轮假封链的两端——verify_lane 供给闸出口文案与引擎签名判据消费——任一端漂移豁免即静默失联，本场景用真进程出口锁接缝：供给装配失败两态（exit 7 失败态/timeout 1s 超时态）真跑闸产出的 err 含双标记（「supply 装配」+「供给面红」）且点名 need → 引擎签名命中 → 该回执形态（ran=0+零产品红+零闸拦+零环境红）不计入 tests-fault 轮次+留痕含「不计入」且点名供给面；反用例（宁窄勿宽）=非签名启动级文案（场景执行器整体超时，即事故 H2 形态）不命中签名、照旧保守计轮；对照组 PASS 桩=闸绿（红绿差异归因于供给面而非夹具）。现状注记：判据接线 HEAD 已通（t260917-09），本场景现在就应全绿，红了=接线回归非 TDD 预期红。分工：t260904-12 sc_supply_gate_ethred 锁闸 supply 机制本体（先行序/点名/畸形声明 fail-closed，假声明仓），t260917-09 sc_tests_false_escalation_guard 锁场景级环境红/抖动豁免与不在册保守计轮（真 docker 台），developer L1 锁判据函数行为（构造串直驱）——本条锁真出口 err×签名×计轮账本三环贯通，机制/场景级/函数级三面均不重复。纯离线秒级零 docker，无 环境用例",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260920-01/sc_supply_assembly_seam.py", "ro"),
    ("t260920-01-supply-wait-budget-probe",
     "供给链 daemon 等待预算 CLI 契约（stage-ops 票① 要求②③，灰盒 L2 离线注入，PATH 前置假 docker）：epic 背景 daemon 假死实案（socket 连通但 90s 无回包当日 3 次）下供给链无界接触=挂满 900s 兜底，收口后用户可感知：daemon 假死形态（命令挂住无回包）→等待预算内收口（绝不硬等 900/600s）、exit 2 诚实红、stderr 进度点名（在等 docker daemon+已等秒数）、无残留子进程（超时即回收）；docker 缺席形态→秒级快速红点名 docker；daemon 健康形态→exit 0 零代价（预算只在坏形态介入）；立即失败形态→快速红点名不重试风暴；预算 env 畸形（非整数）→不崩照常三态（回退数值面归 developer L1）。断言只锚 CLI 进程级公开行为（退出码/stderr 文案/墙钟/进程表），契约不变的实现重构不得打破。分工：t260904-19 sc_stage_docker_cli_contract 与 t260910-12 L1 电池锁起台/拆台/锁面（无 daemon 探活对象），developer L1 锁 wait_budget_s 纯函数数值——本条锁本票新增 daemon 探活预算面的进程级契约。纯离线零 docker 依赖无 环境用例。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260920-01/sc_supply_wait_budget_probe.py", "ro"),
    ("t260920-01-supply-ensure-wait-cap",
     "ensure 争用等待预算封顶+点名（stage-ops 票① 要求②③，灰盒 L2 离线注入，tmp 隔离锁根+fcntl 真持有者）：多泳道撞共享台实案下后到者硬等 600s 零进度，收口后用户可感知：争用形态（他人持 ensure 锁）→预算内诚实红 exit 2（绝不硬等）、stderr 点名在等谁（项目/锁名）与已等多久（秒数）、真持有者零波及（不误杀不抢锁）；无争用形态→行为不变（锁立得照常走到下一道门，docker 缺席=既有快速红点名，预算旋钮零代价——回归锚）；收尾锁可复抢（自己不残留）。区分锚=墙钟：预算封顶（2s 级）与旧 CLI 超时形态（--timeout 8s 兜底）机械可辨，旋钮不生效即墙钟用例红。分工：t260910-12 L1 电池与场景族锁锁获取有界等待/herd/保险丝/租约回收（无等待预算旋钮与等待期进度点名对象），同票 daemon-probe 场景锁等 daemon 面——本条锁等别人持台面。纯离线零 docker 依赖无 环境用例（争用红是被测行为非环境缺失）。实现落地前红属预期（TDD 信号：墙钟用例红+W2 回归锚绿），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260920-01/sc_supply_ensure_wait_cap.py", "ro"),
    ("t260920-01-supply-decl-contract",
     "仓根供给声明可执行纪律（stage-ops 票① 要求②③声明面+边界红线，灰盒 L2 离线，真解析器读仓根 verify.yaml）：供给声明是每轮集测必经的机器消费面，收口后用户可感知：声明结构纪律=supply[0] 无界裸 docker 接触（docker info/image inspect 裸命令）已摘除（daemon/镜像门交有界封装）、等待预算 env 旋钮已声明、失败出口全部 exit 2（三态不放宽，从旧 exit 1 收敛是收紧方向）；docker 缺席形态真跑声明全文（/bin/sh -c、cwd=仓根，与闸消费同款）→预算内快速诚实红 exit 2+ENV_FAIL 标记+docker 点名（绝不挂 900s、绝不是 exit 1），任何机器可判（受限 PATH 剔 docker 后声明应在第一个 docker 接触点快速收口）；声明「健康机器全文可通」回归面由每轮集测段自身 supply 步天然承担（同一条命令每票必跑），本场景不冗余起台。锚 intent 非字面排版：无界接触按裸命令在场判，未来票把门改回声明侧有界形态时红=人审更新契约的预期流程。分工：t260904-12 锁闸机制本体（假声明仓），同票场景②③锁 CLI 等待行为——本条锁本仓真声明内容契约。纯离线无 环境用例。实现落地前红属预期（TDD 信号：现声明裸 docker 在场且失败用例 exit 1），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260920-01/sc_supply_decl_contract.py", "ro"),

    # ---- t260920-03: 术语废止看守升闸级（L7 从 agent 自跑升为每条跑批必跑） ----
    ("t260920-03-terminology-l7-gate",
     "术语废止看守升闸级（t260920-03，灰盒 L1 离线秒级）：L7（lint_tests.lint_terminology，按文件出现次数基线判「新增即红」，行话真源=docs/terminology.md 禁用对照）从「agent 自跑」升为注册在册的跑批必跑面。真仓判定面：in-process 直调真 L7——新增用法/超帽/不在基线=产品红并点名文件与实际/上限；基线缺失/畸形=fail-closed 红；allowlist（值 -1：术语表本体/基线自身）不受限。自证红绿电池（tmp 同构树：字节级复制真 lint 脚本+同构基线，注入式逐态验证）：干净树绿→注入新文件红点名「不在基线内」→既有文件超帽红点名「新增用法」→移除复绿→allowlist 增量不受限仍绿→畸形基线红→基线缺失红→看守脚本缺席=env_fail 三态映射自证；场景源码自洁（被禁字零残留，需写出处全 chr 构词，T0 自证），看守对象自身不入基线不欠账；临时树 finally 全清理。与 L4/L5（注册完整性 lint）不同层：本条守 L7 判定语义本身在闸内的活性。lint 脚本缺席=ENV_FAIL exit 2；真仓 L7 红=FAIL exit 1",
     "python3 integration/t260920-03/sc_terminology_l7_gate.py", "ro"),
    ("t260920-03-terminology-baseline-floor",
     "术语基线帽单调看守（t260920-03 要求②「值只许降；上调=红」的机械化，灰盒 L1 离线秒级，纯标准库零子进程）：L7（兄弟条目 terminology-l7-gate 所守）只判用量不新增，对「改基线本身」全盲——抬帽/扩 allowlist/加新键都能把新增用量合法化而 L7 恒绿。本条把 S4 落地后的基线冻结为 floor 快照（integration/t260920-03/terminology-baseline-floor.json，程序化生成、只降恒绿无需随批更新）：逐键现值≤floor、键集只许收缩、allowlist（-1）面冻结为术语表本体与基线自身、汇总 total_before_allowlist 只许降，违例逐条点名（帽被抬/免红令面扩/基线扩面/汇总上调）——封死「加用量同时抬帽给自己发免红令」（t260911-03 改共享守卫期望值同族事故的术语域形态）。比较器合成数据红绿电池自证（抬帽红/下调绿/缩键绿/扩 allowlist 红/扩键红/汇总上调红/畸形红）防检测器失明；出路可达面=L7 红行指向的 docs/terminology.md「禁用对照」真源在册且真列被禁字（chr 构词断言，红行出路不得 404）。与 terminology-l7-gate 不同面（彼守用量维、本条守帽维），合壁才完整不互替；被看守文件缺损/畸形=产品红点名（仓内受控资产面，非环境缺席，无 ENV_FAIL 子用例）",
     "python3 integration/t260920-03/sc_terminology_baseline_floor.py", "ro"),
    ("t260921-03-close-health-board",
     "已结束工单的收口健康度引擎行/详情契约（t260921-03 验收①②③之数据面，灰盒 L2 离线，stub temporalio+过滤串忠实桩，共享夹具 _stub_temporalio 镜 t260919-02 桩法）：实案复现（t260920-02/t260921-01 形=面快照 blocked×工作流 COMPLETED×无报告）行带 close_health=abnormal+exec_status=COMPLETED+非空事实原因，词面事实原样保留（blocked_reason/findings=0 不回填不清洗——票面边界）；六格矩阵（COMPLETED/FAILED/TERMINATED×有/无产物）：COMPLETED×有产物=ok、×无产物=abnormal、FAILED 两格=failed（dev-lane 与巡检同口径）、TERMINATED 两格=不产生行且零 snapshot/result 查询（僵尸纪律半边原样+资源白烧=0）；反用例=正常收口（有报告）恒 ok 且 reason 空（对账不反向撒谎）、abnormal 必带原因（无因异常禁止）、failed 不混入 abnormal；详情 meta 补终态对账数据源（exec_status/close_health/close_health_reason/终态时刻——现状 meta 无 exec_status=详情表达缺口根）；畸形三态=face 缺失/非串 report_path/findings 非列表全降级不抛不编造、face 缺失的 COMPLETED 不判 ok（产物不可证≠产物在）、收口快照读不到=unreadable 显式存疑绝不冒充 ok、真在飞的查询超时降级行保持 ''+running 词面（KI-008 口径原样）；回归=dev-lane 四形状（meta/极简/失败/降级）既有键值零回归+close_health 键只加不改+四形状键集 parity、R8 闭合窗与白名单不上板口径原样、失败行标题诚实零回归；KI-018① 新增字段纪律=close_health_reason 等新增面不含「刷新重试/查询超时/瞬时」瞬态占位语（既有降级行 title 的占位语是 KI-018 在册面，不属本票不随手修）。分工：t260915-08-board-rows 深钉巡检行形状/R8 窗/白名单（彼时无健康度概念）、t260919-02-terminal-face-board 深钉失败行形状与失败面 face 载荷、t260916-02/t260917-02 守旧形三代/不可辨在跑，本条只钉健康度键存在性/词表语义/详情数据源+零扰动 spot，与彼零重叠；UI 词表与呈现半边归 t260921-03-close-health-ui-model。纯离线无 ENV_FAIL 子用例。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-03/sc_close_health_board.py", "ro"),
    ("t260921-03-close-health-ui-model",
     "已结束工单的 UI 终态对账与异常收口呈现契约（t260921-03 验收①③④⑤之呈现面，灰盒 L2 组件契约，node 直 import 纯函数源+源级锚，零浏览器零 3099，镜 t260919-02-failed-state-ui-model 手法）：U1 deriveTicketState 终态对账新判序——exec_status=COMPLETED→done 先于一切词面（blocked/running/failed/closed 等全词面组合暴力断言不得落 blocked/active/failed，实案形 blocked×COMPLETED 必 done——「绝不再显示在跑/阻塞」字面）、CONTINUED_AS_NEW 转场词面零扰动、失败族与缺 exec 旧值零回归 spot（全表归 t260919-02-failed-state-ui-model 不重复）、畸形 exec（数字/对象/数组/布尔/空串/缺失）不 throw；U2 closeHealthOf 部署窗镜像——键缺老行本地镜像只输出 {abnormal,failed,''} 三值绝不造 ok/unreadable（KI-052 版本错窗族的诚实防御）、降级闭合老行已知偏差显式钉值（镜像 abnormal 非 unreadable，同族不撒谎终态——review 意见2）、非法值不透传/null 行不抛；U3 徽标词表——abnormal→「已结束·异常（无报告）」/unreadable→「已结束·待核」/ok/failed 不贴（反用例③正常收口与失败态不重复标注）、与五态状态词互异、零瞬态占位语（KI-018①）；U4 排序——sortMergedTickets 端到端全序（时间戳反向构造防同档巧合绿：等你/失败→在跑→异常收口→正常收口）+档位相对关系（abnormal<ok、failed 最顶、在跑高于收口——不沉底不并入正常分组）；U5 筛选——独立 health=abnormal chip 命中 abnormal+unreadable 且与五态 chip AND、异常收口仍归 done 桶（countByState 分母——要求⑤归已结束桶）；U6 详情终态卡——buildStatusCard 对 COMPLETED×abnormal 出 amber 卡（headline 含「已结束」+点名缺了什么+blocked_reason 原因链可达+next 零 retry-qc/rework 话术）、正常收口不出异常措辞卡、畸形 detail 降级 null；U7 源级锚（宽容 guard 词探针，不绑实现形状）——详情头 stage_state 徽标/⛔受阻横幅/基本信息状态行三处陈旧词面站点必须被终态对账守卫（review 意见1 契约化：否则点开实案票详情仍见「受阻」=详情侧反向撒谎）。分工：L1 t260904-17 钉判序快照、t260919-02-failed-state-ui-model 钉失败族全表与失败面视图、t260919-02-terminal-face-board 钉引擎失败行数据面，本条独立钉「COMPLETED 终态对账+异常收口可辨」呈现契约与彼零重叠；引擎数据面归 t260921-03-close-health-board。node 缺席=ENV_FAIL exit 2 点名。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "command -v node >/dev/null 2>&1 || { echo 'ENV_FAIL: node 缺席'; exit 2; }; node integration/t260921-03/sc_close_health_ui_model.mjs", "browser-free"),

    # ---- t260921-06: 批级共享 Temporal 台看守族（批内 ns 隔离；宿主令 260921「一次集成测试至多一个 temporal 容器」） ----
    ("t260921-06-batch-runner-form",
     "批台 runner 生命周期与真全轮 churn 形态（t260921-06，灰盒 L3 真 docker）：宿主令验收①④的执法面——含台消费者的轮恰预起 1 个批台（batch-* 工程容器/卷/网各恰 1），窗口内本泳道新现其余 compose 工程名全部∈例外清单形（清单外即红=要求4 执法半边；窗口差分按 compose working_dir label 限定本泳道防并行泳道假红）；消费缝注入面（消费者子进程 env 拿 SANDBAR_STAGE_BATCH=批台名、两消费者各自 ns 同指一个批台地址）；每票集测段形态（exclude engine,exclusive）零预起零注入（最高频路径零回归）；轮终与 SIGTERM 信号路径批台拆台零残留（拆台纪律不因批共享改变）；docker 缺席=整轮 exit 2 快速环境红不烧整套。假表注入（SCENARIOS 覆写+run_inner_runner 子进程直调 main()，既有手法不经单飞锁），条目=真消费缝探针。与 batch-ns-isolation 不同面（彼守服务端 ns 隔离语义，本条守 runner 资产计数与生命周期）；与 t260910-12/t260912-02/t260904-19 族不同 intent（彼守单台机械本体，批台=普通租约复用其判据不重复）。实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2",
     "python3 -B integration/t260921-06/sc_batch_runner_form.py", "engine"),
    ("t260921-06-batch-ns-isolation",
     "批内命名空间隔离与反用例（t260921-06，灰盒 L3 真批台+temporal CLI）：宿主令验收②③+要求2/5——同批两并发 ns-acquire A/B ⇒ A 的自定义 SA 与 workflow 不出现在 B 的命名空间（服务端作用域语义非约定）；反用例段=A 搞坏自己 ns（优先 delete，CLI 不支持则污染形态降级并留痕）⇒ B 的 SA/workflow 面完好、批台容器身份不变；不假绿段=批台不在位 ns-acquire=ENV_FAIL exit 2 点名（绝不静默回落「没跑」）、ns-drop 幂等（NotFound=ok）且释放后可重申请。双模式看守：外层真全轮注入批 env 则直消费外层批台（生产形态零自建），独立跑自管批台 finally 拆台零残留。与 batch-runner-form 不同面（彼数 docker 资产/守生命周期，本条守 temporal 服务端隔离语义与反用例）；register_namespace 幂等单面归 stage_docker selftest/L1 不重复。实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿；docker/temporal CLI 缺席=ENV_FAIL exit 2",
     "python3 -B integration/t260921-06/sc_batch_ns_isolation.py", "engine"),
    ("t260921-06-batch-seam-regression",
     "消费缝迁移回归（t260921-06，灰盒 L2 组件契约）：「批级共享不得改变任何判定口径」的缝面执法——lib_gate.require_stage（约 30 场景唯一消费缝）env 缺席=现行行为逐字（自起独立台、sa_registered 判定、stage_down 拆台零残留=直跑/例外场景零回归锚），env 在场=批模式（零新建台、ns=申请值、地址=批台端口、stage_down 绝不拆批台）；with_stage.sh 壳面桩测（cwd 桩 stage_docker 记录子命令序列）：批模式=ns-acquire→跑→ns-drop 绝不 ensure/down、env 缺席=ensure→跑→down 现行逐字、ns-acquire 红=壳 exit 2 透传不吞不改；批台护栏=--kind batch 与 --keep 互斥 usage 拒收（「不得退化整机共享」CLI 闸）。与 batch-runner-form 不同面（彼守 runner 预起/收口/窗口形态，本条守缝与壳调用序契约）；与 t260904-19 CLI 契约族不同 intent（彼守单台 up/ensure/down 本体，本条只守批模式新增分叉）。真台段 docker 缺席=环境红（桩面段照跑）。实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿",
     "python3 -B integration/t260921-06/sc_batch_seam_regression.py", "engine"),
    ("t260921-06-batch-manifest-contract",
     "例外清单机器契约与起台清点判据不变式（t260921-06，灰盒 L2 离线 ro 每票段必跑哨兵）：要求4「例外通道显式」的执法面+gen0 拒因 C1 的永久化回归网——清单（batch_stage_exceptions.json）schema 五键完整 reason/evidence 非空、条目名逐字在册（机械取自注册表防手抄漂移）、记录池=注册表池、project_pattern 合法前缀形；清点判据不变式=源码面消费模式 grep（require_stage/do_up_public/stageUp(/stage_docker up|ensure/up_stage，含 *.sh）×注册表 cmd 引用文件交叉得批消费者候选集，断言候选 ⊆ engine/exclusive ∪ 清单（两头不占=分类器漏接=每票段假环境红/全轮漏注入的 C1 形态机械化身）；判据为一级源码面已知边界=经 lib 二级消费的正当例外由人审 reason/evidence 承担（哨兵注记不判红）。与 lint_tests L4/L5 不同层（彼守注册结构完整，本条守「消费者↔池↔清单」三角一致性）；与 batch-runner-form 不同面（彼动态窗口真 docker，本条纯静态零 docker）。被看守文件缺损=产品红点名；实现落地前红属预期（TDD：清单未落=红），arbitrate/merge 期必须绿",
     "python3 -B integration/t260921-06/sc_batch_manifest_contract.py", "ro"),
    # ---- t260921-04: developer 段验证纪律（宿主令 260921：单测可跑、集成禁跑+机械判据） ----
    ("t260921-04-discipline-clause-contract",
     "developer 段验证纪律的派活文案契约（t260921-04，宿主令 260921 要求①④文案侧，灰盒 L2 离线秒级）：dev-lane 两个 developer agent 段（create_plan/implement）的派活契约文本必须同批携带——禁跑语义锚（集成禁跑）、五类集成入口点名（run_scenarios.py、sc_ 场景脚本、integration/baselines 基线、with_stage.sh 包装器、verify_lane 验收脚本）、受影响面单测正道（pytest+integration/lint_tests.py）、只读放行语义、集成验证归属段（run_integration_tests 闸）与违规后果（红+票面点名），文案=人话+可执行（含可执行命令形态）非口号；其余 agent 段（review_plan/design_integration_tests/arbitrate/acceptance_walkthrough）的契约文本不携禁跑执法语义与集成执行器点名（执法与文案都只对 developer 段——「文案禁了机械不判/机械判了文案没说」单边态的文案半边+越段执法文案的反向误伤）。锚派活契约文本语义词与稳定文件名不锚全句（KI-051）；与 developer L1 口径同步测试（方案 S3 渲染产物字面）intent 不同面：本场景守公开派活契约面+他段负向对称。实现落地前红属预期（TDD 信号），run_integration_tests 期必须绿；引擎模块不可导入=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-04/sc_discipline_clause_contract.py", "ro"),
    ("t260921-04-discipline-receipt-journey",
     "developer 段集成禁跑的回执执法旅程（t260921-04，宿主令 260921 要求②③+验收①②③④引擎接线面，灰盒 L3 离线秒级，真 zstd 会话档×真活动入口缓存挂点零 spawn）：A 构造子用例——developer 会话集成入口执行（run_scenarios.py）+同回合只读提及→回执红+summary 点名完整命令+结果文件回写 integration_violations 恰 1 条+既有字段形状逐字保留（验收④）+重入幂等不双写；B 允许面——受影响面 pytest、integration/lint_tests.py、只读 grep/sed/cat→零红零点名且结果文件逐字节不动（无命中不回写）；C P1 并行防误伤（KI-093 同族）——并行 integration 角色档（双代名 session.v3）mtime 更新且含集成执行→developer 回执不背红；D P2 防漏判——developer 档真违规+integration 档更新→红不丢且点名来自 developer 档；E 角色门——同形态 integration 角色段不执法；F -c 嵌套串两合法解——递归判一条（bash -c 内执行入口红、只读 ls 不红）或 -c 边界已声明不执法（声明=执法；naive 子串粗匹配会误伤只读，两边都不占=红）。锚回执 JSON 契约与票面 summary 语义不锚内部结构；与 developer L1（方案 §5 函数级夹具/挂点单测）intent 不同面：本场景守真活动入口×真 zstd 档×结果文件落盘×角色钉档（role 钉 <ticket>-developer 目录）全链。实现落地前红属预期（TDD 信号），run_integration_tests 期必须绿；zstd/引擎模块缺席=ENV_FAIL exit 2 点名",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-04/sc_discipline_receipt_journey.py", "ro"),

    # ---- t260921-08: 巡检引文超长软提醒（宿主令 260921「软提醒不判红」+ 硬红只留不可定位形态） ----
    ("t260921-08-quote-overlong-soft-warn",
     "巡检引文超长软提醒契约（t260921-08，宿主令 260921「软提醒不判红」，灰盒 L2 离线桩缝驱动 run_inspection_inspect/verify_inspection_findings/build_ticket_face 真代码）：事故复现且不再报废——t260922-01 实案形态（agent 输出一条证据引文 227 字>上限 200，旧实现判畸形整份拒收：inspect 段失败→票 blocked→当日报告 findings=0、建议零产出=连续 5 天巡检零报告）。①同形夹具（227 字引文锚 238 字真实文件行）驱动解析入口：段不失败、三条发现全部在册（新旧行为对照留痕：旧=227 字→整份拒收 findings=0；新=227 字→在册+截断）；②截断保纯前缀（=原行前 200 字，report 段复核仍可校验）+证据项标注 quote_truncated/quote_original_chars=227+发现上人话点名（含 227/200 与「截断」可读字样，响亮不静默）；③报告计数位 quote_overlong_warn==1 落 verify meta 且经票面 scan_meta 在场（报告形状看守：键必在场），计数位与逐项点名可对账；④建议生成路径仍只看 verified——截断但复核过条照常进 suggested_fix_tickets，引文不符条不开票但仍票面点名（不静默丢）；⑤复核语义不变：截断引文 verified、不符引文 unverified 且 reason 非空（防幻觉面不放松）；⑥硬红对照（同入口新旧边界配对）：空 quote 报错点名 quote 检查、围栏缺失、围栏内坏 JSON 均 fail-closed 不变。intent 分工：t260916-22-inspect-contract 已守解析八态/复核八态/预算矩阵/去重压制横向契约、inspect-journey 守真台真票旅程，本条只守「引文超长软提醒」差异面+事故回归。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；引擎模块离线加载失败=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-08/sc_inspect_quote_overlong_soft_warn.py", "ro"),
    # ---- t260921-09: 多仓 merge_check 三态判据（判据对齐票） ----
    ("t260921-09-multirepo-zero-commit-gate",
     "多仓 merge_check 三态判据（t260921-09，灰盒 L2，ro 隔离临时多仓项目）：票面写集覆盖某仓而该仓确实零改动时不得判红（实证 nusuyou t260920-04：4 仓收口票唯一红灯=[service] 泳道分支有 commit: 0 个 commit，独立复核零改动为真非假红）——旧判据把「许可面」当「义务清单」逐仓必红，票在最后一道机械门前无正当出路。用户可感知契约：第 0 条粒度锁（多目录写集经 build_repo_worktrees 最长前缀归属合并为仓级清单，绝不逐条目化）；①某仓零改动×零 diff（提交面+未提交面）→ 推进不红且回执点名可见（绿项带 reason_code=no_changes_no_diff=新形状，不静默）；②零 commit×有 diff → 仍红（实现未落盘）且文案与①分叉（未提交面→settle 排查+越写集互指「工作区干净」项；仅提交面→位点异常）；③整票零 commit（排除 no_file_changes 票）→ 全局红点名各仓（宿主裁定②保住「什么都没提交却全绿」原防伪），rehearsal 保持 checks[-1]（冲突分类契约，全局红恒 blocked 交人不进自动消解回路）；no_file_changes 票豁免（与 review gate 同一豁免口径）；C1 查询失败=-1 哨兵，全局闸遇 -1 不产「零 commit」文案（红由逐仓 fail-closed 承担，报错与事实同向）。真 git tmp 多仓项目驱动真判定项与真聚合闸（聚合内 verify_lane 由桩承载，白盒四态/纯函数矩阵归引擎 UT 分工）。git 缺席=ENV_FAIL exit 2；任一子用例红=FAIL exit 1",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-09/sc_multirepo_zero_commit_gate.py", "ro"),
    ("t260921-09-multirepo-zero-commit-receipt",
     "多仓 merge_check 三态判据真聚合链回执（t260921-09，灰盒 L3，ro，真 worktree+真清单+真 KI-009 自愈前置直调真 activity，零 docker 零 Temporal server 零模型）：兄弟条 multirepo-zero-commit-gate（L2）直调判定项+桩聚合守判定口径与纯函数哨兵，本条不打桩守「拼起来通不通」组合面——任何一层各自对了拼错仍会红：真回执点名可见（某仓零改动→amber green=True+reason_code=no_changes_no_diff 落真回执且带 [仓名] 前缀——前缀在聚合层加，桩测守不到）、真链整票推进（amber 不拖垮整票、保险丝B 绿项共存、rehearsal 恒 checks[-1]=KI-047 位次契约在真项序下成立）、真自愈交互（写集外脏文件不自愈=KI-009 既有语义→未提交面差异真链存活为红「实现未落盘」+互指「工作区干净」、越写集 worktree_clean 红在场=验收④既有职责、其他仓不被拖红=红项可见性）、分支位点异常真链分叉（泳道分支落后 base：0 commit 但树≠base→「位点异常」）、查询失败（清单 base_ref 坏引用）fail-closed 红（commit_query_failed）不断言「未落盘」不触发全局「整票零 commit」文案（C1 -1 哨兵纪律）、真链 reason_code 三值互不相同机读可分。verify_lane 语义非本票对象：夹具仓 main 预提交最小 verify 工具替身（恒绿 JSON，在 base 提交里=零泳道提交零脏面，只稳定前提）。与 t260915-05（merge_check 红灯票面越写集探针）不同面。引擎 venv 缺席=ENV_FAIL exit 2；任一子用例红=FAIL exit 1",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-09/sc_multirepo_zero_commit_receipt.py", "ro"),
    ("t260921-09-single-repo-zero-commit-gate",
     "单仓票零回归+整票零 commit 防伪闸/豁免真链兑现（t260921-09，灰盒 L3，ro，真单仓泳道 worktree 直调真 activity）：判据三态化后单仓形态逐项保持（验收⑤）且全局防伪口径真链兑现（验收③，宿主裁定②「整票至少一个仓有 commit」）——单仓 0 commit×两差异面均无→逐仓项转 amber（可见非静默）后由整票全局闸兜红（「什么都没提交却全绿」防伪不松：全局红项在真回执、rehearsal 恒 checks[-1]、非冲突类 blocked 交人、出路文案含 allow_empty_write_set）；no_file_changes 声明票豁免（与 review gate 同口径）→ 推进不红且 amber 点名仍在场（行为变化点名：旧判据此形态红）；单仓有 commit→照旧绿且旧绿项契约零回归（只带 id 不带 reason_code——新形状只属零改动绿项，有 commit 票还不受豁免开关影响）；查询失败（base_ref 坏引用）→ fail-closed 红、不断言「未落盘」、-1 哨兵不可当 0 计故全局闸不误判「整票零 commit」（C1）；叠面可分（0 commit×越界脏文件→逐仓 no_commits 红 与 全局 all_repos_zero_commits 红同票并存、reason_code 互不相同机读可分）。与兄弟条 multirepo-zero-commit-gate/-receipt 分工：彼守仓粒度/多仓前缀面，本条守单仓形态与全局闸豁免/防伪两面；verify 替身同 receipt 条立场。引擎 venv 缺席=ENV_FAIL exit 2；任一子用例红=FAIL exit 1",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-09/sc_zero_commit_single_repo_gate.py", "ro"),

    # ---- t260921-14: dsh 升级 T3——声明键路径钉 + 三面版本自检 + 回退面（epic dsh-upgrade 接缝矩阵 #8）----
    ("t260921-14-pin-flip",
     "dsh 路径钉声明键的翻转/回归锚/遮蔽/docker 不消费四面（t260921-14 交付①，灰盒 L2，ro 离线秒级，直调 _prepare_agent_spawn 单点+桩进程账本观测，零真 docker 零 Temporal）：①per-key project.yaml 声明 paths.dsh_bin=桩绝对路径→spawn 预备产出 cmd[0]=桩、参数=文档化缺省逐元素（钉只钉二进制），桩账本出现与 prepared cmd 逐元素相同的执行记录（进程级「翻转变真用」非解析层空转），票面 dsh_pin_<tag>.json cmd_source=declared 且 cmd[0] 与 spawn 同一（face↔spawn 同源=KI-058「机器层安装态≠代码态」的观测解药）；②回归锚（票面硬要求）——无声明无 env 时 cmd 与缺省逐元素等值、face cmd_source=default、既有 face 键集全保持（防本票偷改行为；版本值不断言——真机全局 dsh 缺席属机器态，版本对账归 t260916-24-dsh-face-meta 真机子用例）；③SANDBAR_AGENT_CMD 与声明并存=env 整命令胜+face dsh_bin_shadowed=True+WARNING 点名遮蔽（不静默吞任何一边）；④docker 形态声明在场不消费（容器内解析 cmd 不钉、版本面由镜像承载）+WARNING 点名。intent 分工：t260916-24-dsh-face-meta 守 env 旋钮启动链 face 与探测失败不挡启动、t260916-24-dsh-expected-loud 守执行面期望响亮——本条只守「声明键」新旋钮族（翻转/回归/遮蔽/形态分叉）；声明词法/fail-closed 矩阵归 developer L1（test_t260921_14_dsh_path_pin，方案 §2.6 取舍清单 #1-#13）。真机全局 dsh 缺席不影响判定（版本断言全锚自报版本的桩）。实现落地前红属预期（TDD：①③④随接线转绿），arbitrate/merge 期必须绿；引擎模块不可导入=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-14/sc_t260921_14_pin_flip.py", "ro"),
    ("t260921-14-tri-face",
     "dsh 三面版本自检点名（t260921-14 交付③，接缝矩阵 #8「宿主/容器同票两段行为分叉」的点名机，灰盒 L2，ro 离线秒级：宿主面走 PATH 注入桩、容器面走假 docker 桩，零真 docker 零真全局 dsh）：①docker 形态三面互异（宿主 9.9.9-host/镜像 tag 提取 9.9.9-tag/容器实测 9.9.9-ctr）→票面 tri 块 consistency=divergent、divergences 逐对列全三面、人读 note 含三版本、spawn 日志 WARNING 点名（票面+日志双口径）；②三面同版→consistency=consistent 且零 dsh_pin WARNING（一致面不噪声）；③容器探针恒败→consistency=incomplete+incomplete 列点名 container 面+detail 留痕，spawn 照常产出 cmd/env（观测面不抢 spawn 职责：探针失败不挡启动），引擎面不受牵连仍可判；④face↔tri 同源（方案 C1 集成面）：host 形态+声明钉下 tri.faces.engine 与票面 face 同一 cmd/cmd_source=declared/bin、host 形态无容器面=缺席非失败、宿主全局≠被钉二进制=divergent（试验窗口预期点名形态）。intent 分工：tag-derived 弱证据语义与 TODO(T3/Q3) 关账归 developer L1；t260916-24-dsh-face-meta 守 docker 启动链接线（真 worker 起跑链），本条守三面对账判级矩阵（离线可复现），不同面不互替。实现落地前红属预期（TDD：tri 块/容器实测探针未接线=红），arbitrate/merge 期必须绿；引擎模块不可导入=ENV_FAIL exit 2（真 docker/真全局 dsh 缺席不 ENV_FAIL——全桩）",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-14/sc_t260921_14_tri_face.py", "ro"),
    ("t260921-14-rollback",
     "dsh 路径钉/镜像的回退剧本机械验证（t260921-14 交付④「回退是硬要求」，灰盒 L2，ro 离线秒级）：①A/B/A——无声明基线 B→加 paths.dsh_bin 行（钉生效前提同子用例自证）→删该行（行级手术=「配置改回一行」机械形态）：prepared cmd 与 B 逐元素等值+face 回 default（引擎层回退逐字回裸 dsh，不残留钉态尾巴）；②注释形态（# dsh_bin: … 先活后注释）=声明缺席语义同样逐字回 B（回退不留死键红）；③镜像回退=SANDBAR_AGENT_IMAGE 指回旧 tag 立即生效：face image_source=env、tag 提取版本=0.1.1-rc.2（无 docker 调用——旧镜像不删不覆盖即可指回）；④回退剧本文档守卫（review C4）：ROLLBACK.md 在场且含旧 tag 字面、dsh_bin: 回退指令、SANDBAR_AGENT_IMAGE 旋钮、宿主全局回退命令锚（事前快照 dsh-011-backup 或按版重装 @deepseek-ai/dsh）——回退面文档腐烂=红。intent 分工：镜像三处同步锁（DEFAULT_AGENT_IMAGE↔Dockerfile ARG↔build 脚本缺省）归既有 L1（test_镜像版本三处同步自动跟进），本条守回退操作行为面+剧本可读面不同对象。实现落地前红属预期（TDD：①A 态半边与④随 implement Step7 落地转绿，基线/回退半边锚现状语义应先行绿），arbitrate/merge 期必须绿；引擎模块不可导入=ENV_FAIL exit 2",
     "PY=server/engine/.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" -B integration/t260921-14/sc_t260921_14_rollback.py", "ro"),

    # ---- t260922-12: 集成门结果台账（按提交记账+查询+定点复跑，治「门永远红/反复整跑」）----
    # integration 设计段产物（L2/L3 灰盒，真缝 admin.py call verify_lane × 真 git 临时仓 ×
    # 桩执行器，秒级零 docker 零 console）。四条 intent 互不重叠：①查询 CLI 无假绿契约
    # ②正例面（欠账不拦+台账命中跳基线+主账 append-only 全键行）③拦截面（记账绿×泳道红
    # 仍拦+无记录回退实跑+基线定点复跑+脏树不写账）④基线依赖软链四态行为面。
    # 与 developer L1（test_t260922_12_* 四电池）分工：彼测模块级行为/env 注入形状/
    # 纯函数真值表（白盒随实现），本族测真缝组装行为、文件级不变式与用户可感知判定
    # （黑盒行为面：台账文件内容、桩执行日志、green/blockers/summary 公开回执）。
    # 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
    ("t260922-12-ledger-query-no-false-green",
     "台账查询 CLI 的无假绿契约（t260922-12 验收②对抗面，灰盒 L2/L3，临时台账目录+子进程 CLI 黑盒）：一条命令答「commit X 上场景 Y 红不红」且输出含判定/来源/指纹/时间要素；命中→显式判定面不误报无记录；无记录→显式「无记录」且输出绝不携带 pass 字样（「查不到当绿」=票据红线①的机械化身）；主账不可读（路径被占成目录）→不静默：stderr 点名在场且绝不凭空给 verdict；主账半行/坏 JSON 畸形行在场→好行照常可读、坏行绝不捏造判定（畸形行不可回 pass）；commit 属键——同场景异 commit 必须「无记录」（键语义不放宽）；--ledger 直连+任意 cwd 与 SANDBAR_SCENARIO_LEDGER_DIR 目录覆盖缝独立可用（闸写账同缝）。与 developer L1（scenario_ledger 格式/拒写/保留/并发模块电池）intent 不同面：彼锁模块级行为与 CLI 词表对账，本条锁黑盒 CLI 的消费端无假绿语义（「台账变假绿机」的主防线）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260922-12/sc_ledger_query_no_false_green.py", "ro"),
    ("t260922-12-gate-ledger-debt-not-blocked",
     "门先查账后实跑·正例面（t260922-12 验收③正例/⑥正例/①⑦文件面，灰盒 L3，真缝 admin.py call verify_lane × 真 git 临时仓 × 桩执行器，夹具内嵌 scenario_ledger 库=闸按泳道树文件位装载的同构体）：R1 泳道红×活基线同红→既有欠账记录不拦（green=true、blockers 空、summary 诚实计数 fail=1 不洗数），主账落 lane:/baseline 两源行且行行十字段全键（无脏行），桩日志 ref=HEAD 证明基线相真执行；R2 同输入再跑→台账命中：基线相零执行（桩基线执行数不增+基线源行零新增）、a 仍由台账判欠账（不靠重跑）、主账字节前缀保持且增长（append-only）、新增行仍全良构、worktree 零残留。断言锚=台账文件内容、桩执行日志、green/blockers/summary 公开回执，不锚闸回执内部新增键。与 developer L1（gate_ledger 白盒电池：env 形状/回执内部键/写失败降级）不同层：本条锁真缝组装行为与文件级不变式。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git 缺席=ENV_FAIL exit 2",
     "python3 integration/t260922-12/sc_gate_ledger_debt_not_blocked.py", "ro"),
    ("t260922-12-gate-ledger-regression-blocked",
     "门先查账后实跑·拦截面（t260922-12 验收③反例1/反例2+④⑥，灰盒 L3，同真缝夹具）：种子轮落台账 a=fail、b=pass 后——RB 反例1（「台账不变假绿机」的反向锁）：泳道脏改 b 红→b 仍拦（blockers 含 b 不含 a——台账绿不改判不松绑，拦来自保守原判方向）且基线相零执行（两红皆有可信台账答案：a=fail→欠账记录、b=pass→佐证 main 绿方向，不靠重跑）、脏树轮 lane 源行零新增（脏树不写账）、主账字节逐位不变；RC 反例2+④：泳道再添从没跑过的 z 红→基线必须真跑（无记录回退实跑不得当绿）且只跑 z（桩基线执行名单恰=[case-z]+SANDBAR_SCENARIO_ONLY 传导可见——门侧歧义名单注入的用户可感知形态，不整跑）、z=基线绿→拦、a 照旧欠账不拦、z 落 baseline 源行而 a 零新增。与 developer L1（only_scenarios 执行器电池：fail-closed/expected 不变式）intent 不同面：彼锁执行器入口自身，本条锁门侧「歧义名单注入基线」的组装行为。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git 缺席=ENV_FAIL exit 2",
     "python3 integration/t260922-12/sc_gate_ledger_regression_blocked.py", "ro"),
    ("t260922-12-gate-baseline-deps-links",
     "基线树依赖软链四态行为面（t260922-12 验收⑤，灰盒 L3，真缝+真 worktree，旋钮显式置位不依赖缺省——缺省值由取证 A'/B' 实录裁定场景不钉）：SANDBAR_GATE_BASELINE_DEPS=1 时 src 在场→软链建成（桩在基线相实测 app/node_modules islink）、dst 已在（仓内已跟踪真目录）→绝不覆盖（.venv 仍为真目录）、src 缺席→跳过不致命（ui-check playwright-core 与 temporal 两路径 absent）；=0 时一条不建（旋钮真的关得掉，若实现未接旋钮此轮红点名）；两轮基线跑均正常收口、台账写账不受软链影响、worktree 零残留。软链只读语义由「src 指向主仓共享目录」的夹具同构构造保证。与 developer L1（软链四态白盒单测）intent 不同层：彼测建链函数本身，本条锁基线执行相里依赖真实可见——「回退路线必须真能跑」的物理前提。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；git 缺席=ENV_FAIL exit 2",
     "python3 integration/t260922-12/sc_gate_baseline_deps_links.py", "ro"),

]

CMD_TIMEOUT = 900
_SPAWN_FAIL = -8   # spawn 面（OSError 等）：非超时非断言，综合为 not-checked×external


try:   # 协议纯函数核心（INTEG_SUMMARY 明细计数/规范行解析用）；缺席=回落旧计数
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "server", "engine"))
    import failure_protocol as _fp_mod
except Exception:   # pragma: no cover — 协议库缺席不炸执行器（观测面降级留痕）
    _fp_mod = None


def _env_fp_parts():
    """执行器侧指纹键集（运行语境不变面，t260910-13；与闸侧 verify_lane 同键集
    同算法——lane/基线各采一次，键集选成永 diff 面=归属恒 unknown）。键：
    python/node 工具链版本 + 协议库内容哈希（票改协议库 → 与 main 基线合法 diff）。
    排除工单语境键与临时路径（failure_protocol.FP_EXCLUDED_KEYS 同口径）。"""
    import platform
    parts = {"python": platform.python_version()}
    try:
        nv = subprocess.run(["node", "--version"], capture_output=True,
                            text=True, timeout=10)
        parts["node"] = nv.stdout.strip() if nv.returncode == 0 else "absent"
    except Exception:
        parts["node"] = "absent"
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for f in ("lib_env.py", "lib_result.py", "conftest_result_protocol.py",
              "conftest.py"):
        p = os.path.join(here, f)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                h.update(f.encode() + b"\0" + fh.read() + b"\0")
    parts["integ_protocol_libs"] = h.hexdigest()
    return parts


def _spec_from_output(name, pool, out, exit_code, dur, started):
    """执行器综合规范行（t260912-01 缺陷②起无条件综合——本层唯一生产缝）。

    旧口径「场景 stdout 出现 `{` 行即协议在产、执行器零综合」随 stdout 收集缝一并
    退役：该口径让嵌套执行器输出顶替本层综合行（260912 实锤：真红被嵌套 pass 顶成
    绿，两套汇总分叉照常放行）。场景 stdout 的 `{`/`[` 行一律视为嵌套产出物——既不
    进本层计数（收集缝已删，见 _emit），也不得经尾段回显混入闸候选（回显中和见
    _echo_tail）。旧场景只有退出码与文本尾巴，按三态契约反推：exit1=断言级产品红
    （cause=self/reason=assert_mismatch）、exit2=环境红（cause=external，evidence=
    尾巴——ENV_FAIL 行点名缺什么）。退出码封闭性之外的码按 fail×other 处理（不归环境）。"""
    started_iso = datetime.datetime.fromtimestamp(
        started, datetime.timezone.utc).isoformat(timespec="seconds")
    tail = " | ".join(ln.strip() for ln in out.splitlines() if ln.strip())[-500:]
    sha = os.environ.get("SANDBAR_GIT_SHA", "")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import lib_result
    if exit_code == 0:
        return lib_result.spec_line(name=name, suite=pool, status="pass",
                                    dur_s=round(dur, 3), started=started_iso,
                                    git_sha=sha)
    if exit_code == -9:
        # 超时不是断言失败（走查 gen1 问题④）：标签用 timeout，不冒充 assert_mismatch
        return lib_result.spec_line(name=name, suite=pool, status="fail",
                                    cause="self", reason="timeout",
                                    evidence="超时（>%ds）" % CMD_TIMEOUT,
                                    dur_s=round(dur, 3), started=started_iso,
                                    git_sha=sha)
    if exit_code == _SPAWN_FAIL:
        # spawn 面（t260911 仲裁①）：没跑到断言=not-checked×external，evidence
        # 点名 spawn 失败原文（_run_entry 已把原文放进 tail；out 全程为空）
        return lib_result.spec_line(name=name, suite=pool, status="not-checked",
                                    cause="external", reason="other",
                                    evidence=tail or "spawn 失败（原因缺失，异常）",
                                    dur_s=round(dur, 3), started=started_iso,
                                    git_sha=sha)
    if exit_code == 2:
        return lib_result.spec_line(name=name, suite=pool, status="not-checked",
                                    cause="external", reason="other",
                                    evidence=tail or "ENV_FAIL exit=2（无文本尾巴）",
                                    dur_s=round(dur, 3), started=started_iso,
                                    git_sha=sha)
    return lib_result.spec_line(name=name, suite=pool, status="fail",
                                cause="self", reason="assert_mismatch",
                                evidence=tail or ("exit=%d" % exit_code),
                                dur_s=round(dur, 3), started=started_iso,
                                git_sha=sha)


def _sweep_residue_stages():
    """套件前残台清扫（t260912-02 清理挂点①）：按主人存在性（compose 工作目录
    已删 / 泳道不在 git worktree list / 心跳陈旧超阈）判拆上一期留下的残台，
    判拆逐条点名、stdout 可见。清理失败响亮留痕但**不中止套件**——清道夫失败
    不应烧掉全量闸全部场景（每条场景起台时还会再扫一遍=清理挂点②，双重冗余）；
    docker 缺席时 sweep 子命令按三态诚实报 ENV_FAIL，同样只留痕不中止。"""
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage_docker.py")
    try:
        p = subprocess.run([sys.executable, cli, "sweep"], capture_output=True,
                           text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        # 词面前缀纪律同 batch-stage（t260921-06 仲裁 A 族同根顺手清）：`[` 起首行
        # 会被闸收成畸形规范行计红，自产通告一律 `stage-sweep: ` 起首。
        print("stage-sweep: 套件前清扫未跑成（%s: %s）——残台交起台时清扫/人工"
              % (type(e).__name__, e), flush=True)
        return
    for stream in (p.stdout or "", p.stderr or ""):
        for line in stream.splitlines():
            if line.startswith(("[stage-sweep]", "ENV_FAIL", "STAGE_")):
                # `[stage-sweep]` 行（cmd_sweep 扫描/判拆点名，stdout 无条件打）不能
                # 原样转发——闸候选面会收红；剥前缀改 `stage-sweep: ` 形转发（留痕
                # 语义不变；stage_docker 本体词面不动，t260912-02 场景断言锚定直跑
                # 输出，且本函数的挑选条件仍认原前缀）。ENV_FAIL/STAGE_ 行两种起首
                # 字符均安全，原样转发。
                if line.startswith("[stage-sweep]"):
                    print("stage-sweep:%s" % line[len("[stage-sweep]"):], flush=True)
                else:
                    print(line, flush=True)
    if p.returncode != 0:
        print("stage-sweep: 套件前清扫失败（rc=%d）——不中止套件，失败项已点名；"
              "起台时清扫与下一期套件前清扫会再试" % p.returncode, flush=True)


def _docker_hygiene():
    """起跑前台面卫生（t260910-14 arbitrate gen2/gen3，tests-fault 供给面迭代）：
    全量闸每期起 ~15+ 个 compose 台，场景崩溃/超时时 stage_docker 的 down 走不到，
    停止态容器与其网络逐期堆积 → docker 地址池耗尽（gen2 实锤：30 个 *_default
    网络后 'all predefined address pools have been fully subnetted'，19 个场景连坐
    ENV_FAIL）。本扫只动**停止态**的 compose 台容器与**闲置**网络——在跑台（含其他
    泳道的供给台）零接触；docker 缺席/任何失败=静默跳过（卫生是尽力而为，不是闸）。
    t260912-02 注：起台建网已显式带受管子网（stage_docker 分配，fully subnetted
    不再是活路径），且受管网络随 compose down 自拆——本卫生保留为防御面（手工
    直跑/旧期残留），在跑台零接触的边界原样。与 _sweep_residue_stages（残台清扫）
    分工：彼按租约判主人生死、可拆在跑的残台；本只扫无主停止态容器与闲置网络。
    """
    # t260913-02 arbitrate gen6（并发破坏面修复）：原实现是**全局**清场——
    # `docker rm -f` 掉全机所有停止态 compose 容器 + `docker network prune -f` 清全机
    # 闲置网络。单机多泳道并行时这是**破坏性**的：他泳道「建网 → 起容器」之间有一个
    # 网络短暂无容器的窗口，全局 prune 正好在那个窗口把它删掉 → 对方 `docker compose up`
    # 报 `network <project>_default not found` 直接红。本泳道实测复现（t260910-12-cwd 与
    # t260907-07-epic-cli 两条原生此形态），且删掉他泳道停止态容器会打乱其残留断言
    # （burst 的全机快照子用例、sweep-owner-gone 的残留子用例同源噪声）。
    # 口径修正：**只清「够旧」的资源**（until=10m）——新鲜创建期（任何泳道正在起台）
    # 一律零接触，而本函数的设计意图（函数注：手工直跑/旧期残留的防御面）本就是「旧」
    # 对象，语义不缩水。容器侧改用 container prune（同带 label 过滤，只碰 compose 台），
    # 不再枚举后逐个 rm。
    try:
        subprocess.run(
            ["docker", "container", "prune", "-f",
             "--filter", "label=com.docker.compose.project",
             "--filter", "until=10m"],
            capture_output=True, text=True, timeout=120)
        subprocess.run(["docker", "network", "prune", "-f", "--filter", "until=10m"],
                       capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001——卫生尽力而为；docker 缺席静默跳过
        pass


def _echo_tail(ln):
    """尾段回显一行（t260912-01 缺陷②闸层中和）：闸按 strip 后首字符筛规范行候选
    （verify_lane 同款口径，缩进不豁免），回显里 strip 后以 `{`/`[` 开头的行加 `| `
    前缀使其不成候选；行首 4 空格缩进保持（output_tail 捕获面不变）、原文保留
    （败因诊断面不破坏——t260910-08 型仲裁要读原文归因）。"""
    s = ln.strip()
    if s[:1] in ('{', '['):
        return "    | " + s
    return "    " + ln


def _counts_mismatch(spec_cases, ran, passed, failed, env_failed):
    """两套计数互证（t260912-01 缺陷②「谎报即红」）：规范行明细重算必须与 rc 三态
    计数逐字段相等——灌水（明细多出）、漏收（明细缺失）、重分类（状态漂移）任何一种
    都返回点名文本（供 FAIL [__executor__] 输出），一致返回 None。

    显式降级面（非静默）：协议库缺席（_fp_mod=None）或明细为空（spec_cases==[]，
    同 INTEG_SUMMARY 的 rc 回落支路口径——回落时 stdout 上的综合行仍在，闸侧独立
    recount 与 rc 计数一致，不构成谎报面）→ 返回 None。因此漏收可机械检出的前提是
    明细非空但 ran<rc ran（条目数 ≥2 时缺行可检出；单条目明细独苗被漏收即触发回落
    支路，属声明降级边界，记录于回归场景/报告）。"""
    if _fp_mod is None or not spec_cases:
        return None
    try:
        c = _fp_mod.recount(spec_cases)
    except Exception as ex:   # noqa: BLE001 —— 明细形状坏本身就是分叉，点名不吞
        return "明细重算失败（%s: %s）" % (type(ex).__name__, ex)
    want = (("ran", ran), ("pass", passed), ("fail", failed),
            ("not_checked", env_failed))
    diff = ["%s 明细=%s rc=%s" % (k, c.get(k), v) for k, v in want if c.get(k) != v]
    return "；".join(diff) if diff else None


def _run_entry(entry):
    """Run one scenario (cmd via /bin/sh -c, cwd = repo root). Returns
    (name, exit_code, tail, dur_s). dur_s = that scenario's wall time
    (KI-060 prep 2: timing distribution — the summary line only gives the
    total; finding the slow scenarios relies on these per-entry marks)."""
    name, cmd = entry[0], entry[2]
    t_start = time.time()
    # 净化 lane 自身 env 再下放（t260910-08 arbitrate）：机械跑若从 dev-lane 内
    # 发起（runner 本身住在泳道里），SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW
    # 会触发带递归守卫的场景（capture 族/auto-rework-trace）的「嵌套于 lane 步」
    # ENV_FAIL——那是运行姿势误伤，不是被测环境缺席。顶层跑场景=被授权的顶层，
    # 守卫针对的递归自举不适用。
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("SANDBAR_TASK_QUEUE", "SANDBAR_WATCH_WORKFLOW")}
    # 批台注入（t260921-06）：恰批消费者条目拿 SANDBAR_STAGE_BATCH=批台工程名——
    # 消费缝（lib_gate.require_stage / with_stage.sh）据此走 ns 面；例外条目与
    # 非消费者条目零注入（例外通道显式化，env 缺席=逐字旧行为）。
    if _BATCH_STATE["project"] and name in _BATCH_STATE["consumers"]:
        child_env[BATCH_ENV] = _BATCH_STATE["project"]
    try:
        # 解码加固（t260911-04 仲裁 gen3 实锤）：text=True 默认严格解码，任一场景输出
        # 含非法字节即抛 UnicodeDecodeError 穿透池线程 → 池级异常 → 该池未跑条目静默
        # 丢失（实案：192 跑 ≠ 在册 216，池级异常点名 0xef 处解码失败）。诊断文本按
        # 替换字符净化，判定仍严格由退出码承载——不弱化三态契约，只堵条目丢失。
        proc = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=CMD_TIMEOUT, env=child_env)
        return (name, proc.returncode,
                ((proc.stdout or "") + (proc.stderr or ""))[-1500:],
                time.time() - t_start, t_start,
                ((proc.stdout or "") + (proc.stderr or "")))
    except subprocess.TimeoutExpired:
        return (name, -9, "超时（>%ds）" % CMD_TIMEOUT, time.time() - t_start,
                t_start, "")
    except OSError as ex:
        # spawn 面（t260911 仲裁实锤：宿主资源压力下 spawn 可抛 OSError）——
        # 按协议分类落红绝不 raise 穿透（条目静默丢失＝fail-open 家族复发）：
        # 专用码 -8（非超时非断言），综合为 not-checked×external，evidence 点名原文。
        return (name, _SPAWN_FAIL, "spawn 失败: %s: %s" % (type(ex).__name__, ex),
                time.time() - t_start, t_start, "")
    except Exception as e:  # noqa: BLE001
        # 丢单防御（t260910-14 arbitrate gen3）：起跑侧任何异常若穿出到 drain 线程，
        # 该场景将零结果行（gen0 实锤：登记 196 实跑 195、t02 静默消失）——兜底记
        # ENV 口径一行留痕（起跑失败=环境/供给事件，非产品红），计数保持诚实。
        # （6 元组形态随 main 侧协议扩展对齐；OSError 已由上一支专用码承接。）
        return (name, 2,
                "runner 捕获场景进程异常（留痕不静默丢场景）：%r" % (e,),
                time.time() - t_start, t_start, "")


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_EXCLUDE_TOKEN = re.compile(r"^[a-z0-9-]+$")

# 被排除池共用的根级共享基建面（t260913-03 R5 收口）：integration/ 一级文件里的
# 舞台链/协议库/执行器自身——sc_ 前缀是注册场景文件（归属各自池），不入此面。
_SHARED_INFRA_SUFFIXES = (".py", ".mjs", ".sh")


def pool_of(entry):
    """条目所属池名（与 main() 的注册表切分同口径的单源）。

    第 4 元 "exclusive"=exclusive 池；为空或 "serial"（无池标注的串行条目）=main
    池；其余值即池名。"""
    opt = entry[3] if len(entry) > 3 else None
    return opt if (opt and opt != "serial") else "main"


# 注册表自有的池词汇表（模块导入期快照，t260913-03）：--print-pool-assets 的未知池
# 判据用它、而不是调用时的 SCENARIOS——注入式夹具把 mini 注册表插在 __main__ 之前，
# SCENARIOS 会被换成小表，但池词汇表必须仍代表本仓注册表的池名全集：否则「声明面照旧
# 列出 engine,exclusive、而 mini 表恰好没有 exclusive 条目」这一合法形态会被误判未知池
# （t260913-03 设计段场景③实锤）。判据与「跳过集合」解耦是 R2 收口面。
_REGISTRY_POOL_VOCAB = frozenset(pool_of(e) for e in SCENARIOS)


def parse_exclude_pools(raw):
    """池排除串解析 → (合法池名列表, 违规 token 列表)。

    逗号切分+strip+去空+去重；token 语法 [a-z0-9-]+。违规 token 只剥离不判红——
    主路径必须与「注入假场景表」的既有电池共存（那些假表里没有 engine/exclusive
    池，按「未知池红」会把每张过滤生效的票判红）。配置错误的判红单点在
    --print-pool-assets（独立进程读真注册表）。"""
    names, bad = [], []
    for tok in str(raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if _EXCLUDE_TOKEN.match(tok):
            if tok not in names:
                names.append(tok)
        else:
            bad.append(tok)
    return names, bad


def parse_only_scenarios(raw):
    """点名串解析（t260922-12 ④定点复跑）→ 名单（逗号切分+strip+去空+去重保序）。

    解析层纯面、不做注册表校验：fail-closed 判红单点在 main()——名单含不在册
    条目时**一条都不跑**（与 --reprobe 同族语义：点名错=调用方 bug，绝不静默
    跑剩下的）。缺省（raw 空）= 空名单 = 全量跑，主路径零分支。"""
    names = []
    for tok in str(raw or "").split(","):
        tok = tok.strip()
        if tok and tok not in names:
            names.append(tok)
    return names


def _cmd_asset_tokens(cmd):
    """cmd 中形如仓内真实文件的 integration/ 路径 token（环境前缀 token 如
    PY=server/… 不以 integration/ 开头，机械排除）。"""
    out = []
    for raw in re.split(r"[\s;|&()]+", str(cmd)):
        tok = raw.strip().strip("'\"")
        if not tok.startswith("integration/") or tok in out:
            continue
        if os.path.isfile(os.path.join(_REPO_ROOT, tok)):
            out.append(tok)
    return out


def _py_import_targets(rel):
    """py 文件的 import 目标候选（框定 integration/ 前缀，存在性由调用方判）。"""
    with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                mods.add("." * node.level + (node.module or ""))
            elif node.module:
                mods.add(node.module)
    base = os.path.dirname(rel)
    cands = set()
    for m in mods:
        if m.startswith("."):
            name = m.lstrip(".").replace(".", "/")
            stem = os.path.join(base, name) if name else base
            cands.add(stem + ".py")
            cands.add(os.path.join(stem, "__init__.py"))
        else:
            p = m.replace(".", "/")
            cands.add(p + ".py")                        # 仓根解析
            cands.add(os.path.join(base, p + ".py"))    # 同目录
            cands.add("integration/" + p + ".py")       # 场景约定 sys.path=integration/
            cands.add(os.path.join("integration", p, "__init__.py"))
    return cands


_MJS_IMPORT = re.compile(r"""(?:from|import|require)\s*\(?\s*['"](\.[^'"]+)['"]""")


def _mjs_import_targets(rel):
    with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8") as fh:
        src = fh.read()
    base = os.path.dirname(rel)
    out = set()
    for m in _MJS_IMPORT.findall(src):
        p = os.path.normpath(os.path.join(base, m))
        out.add(p)
        out.update(p + ext for ext in (".mjs", ".js", "/index.mjs", "/index.js"))
    return out


def _shared_infra_assets():
    """integration/ 一级共享基建文件（非 sc_ 场景文件）：舞台链/协议库/执行器自身。
    保守面——宁多触发全跑，不漏被排除池消费面；新增根级共享文件自动入面。"""
    integ = os.path.join(_REPO_ROOT, "integration")
    out = []
    try:
        names = sorted(os.listdir(integ))
    except OSError:
        return out
    for name in names:
        p = os.path.join(integ, name)
        if not os.path.isfile(p) or name.startswith("sc_"):
            continue
        if os.path.splitext(name)[1] in _SHARED_INFRA_SUFFIXES:
            out.append("integration/" + name)
    return out


def collect_pool_assets(pool_names):
    """被排除池资产面（机械派生）：cmd token ∪ import/require 传递闭包 ∪ 根共享基建面。

    返回 (assets, warnings)。闭包解析失败=保留该文件并告警（不阻断派生；方向安全=
    交集只增不减=更易强制全跑）。"""
    warnings = []
    seen = set()
    queue = []
    for entry in SCENARIOS:
        if pool_of(entry) not in pool_names:
            continue
        for tok in _cmd_asset_tokens(entry[2]):
            if tok not in seen:
                seen.add(tok)
                queue.append(tok)
    while queue:
        rel = queue.pop()
        try:
            if rel.endswith(".py"):
                cands = _py_import_targets(rel)
            elif rel.endswith((".mjs", ".js")):
                cands = _mjs_import_targets(rel)
            else:
                continue
        except (OSError, SyntaxError, ValueError) as ex:
            warnings.append("%s 解析失败（%s: %s）——保留该文件，闭包未展开"
                            % (rel, type(ex).__name__, ex))
            continue
        for cand in cands:
            cand = os.path.normpath(cand)
            if not cand.startswith("integration/") or cand in seen:
                continue
            if os.path.isfile(os.path.join(_REPO_ROOT, cand)):
                seen.add(cand)
                queue.append(cand)
    seen.update(_shared_infra_assets())
    return sorted(seen), warnings


def print_pool_assets(pool_arg):
    """--print-pool-assets：真注册表校验池名（未知池=exit 2 点名）+ 资产面派生。

    闸侧单点判红面（独立进程读真注册表，进程内注入假表够不到）。"""
    names, bad = parse_exclude_pools(pool_arg)
    known = sorted(_REGISTRY_POOL_VOCAB)
    bad_all = bad + [p for p in names if p not in _REGISTRY_POOL_VOCAB]
    if not names or bad_all:
        sys.stderr.write("池名非法或不在册：%s；在册池=%s\n"
                         % (",".join(bad_all) or "（空）", ",".join(known)))
        return 2
    assets, warnings = collect_pool_assets(set(names))
    print(json.dumps({"pools": names, "assets": assets, "warnings": warnings},
                     ensure_ascii=False), flush=True)
    return 0


def reprobe_main(names) -> int:
    """--reprobe：只复跑点名条目，串行逐条（t260917-09 探针出口，证据面非闸面）。

    消费方=引擎 activity reprobe_red_scenarios（仲裁判 tests-fault 后，对红项串行
    复跑一轮取证「负载抖动」：全绿→该轮不计入 tests-fault 轮次）。设计纪律：
    - name→cmd 单一真源=本文件 SCENARIOS 注册表；调用方只报名单，绝不携带 cmd
      （activity 侧另立执行语义=双实现，禁）。
    - 执行语义与全量跑**同一实现**（复用 _run_entry：/bin/sh -c＋仓根 cwd＋
      CMD_TIMEOUT，超时/OSError 分类落红不穿透）。
    - 占同泳道单飞锁（真执行≠--print-pool-assets 的纯读免锁）；锁忙=fail-closed。
    - fail-closed 两态统一打 REPROBE_SUMMARY 行（R1 定案）：任一名字不在册→**一条
      都不跑**、error 点名 missing（保守计轮的机械信号）；请求名单空→同 fail-closed
      （探针无名单=调用方 bug，不静默当全绿）。
    - 缺省路径（无 flag）逐字节不变；本出口独立进程可注入 mini 注册表（既有电池
      先例）。
    """
    req = []
    for n in (names or []):
        n = str(n).strip()
        if n and n not in req:
            req.append(n)
    by_name = {e[0]: e for e in SCENARIOS}
    found = [by_name[n] for n in req if n in by_name]
    missing = [n for n in req if n not in by_name]

    def _summary(ran, passed, failed, env_failed, missing_, error, entries):
        print("REPROBE_SUMMARY %s" % json.dumps(
            {"ran": ran, "passed": passed, "failed": failed,
             "env_fail": env_failed, "missing": missing_, "error": error,
             "entries": entries}, ensure_ascii=False), flush=True)

    if not req or missing:
        _summary(0, 0, 0, 0, missing,
                 "reprobe 名单非法（空名单/含不在册名）——一条都未跑" if not req
                 else "红项不在册：%s——一条都未跑（保守计轮信号）" % ",".join(missing),
                 [])
        return 2
    fd = _acquire_run_lock()
    if fd == -1:
        _summary(0, 0, 0, 0, [], "同泳道单飞锁忙（有全量跑在途）——本轮未复跑", [])
        return 2
    ran = passed = failed = env_failed = 0
    entries = []
    try:
        for e in found:
            name, code, tail, dur, _t0, _full = _run_entry(e)
            ran += 1
            if code == 0:
                passed += 1
            elif code == 1:
                failed += 1
            else:
                env_failed += 1
            entries.append({"name": name, "exit": int(code), "dur_s": round(dur, 1)})
            mark = "过" if code == 0 else ("败" if code == 1 else "环境红")
            print("  复跑 [%s] %s（exit=%s，%.0fs）%s"
                  % (name, mark, code, dur, tail.strip().replace("\n", " ⏎ ")[:200]),
                  flush=True)
    finally:
        _summary(ran, passed, failed, env_failed, [], "", entries)
    return 0 if (ran == len(found) and failed == 0 and env_failed == 0) else 1


# ---------------------------------------------------------------- 批级共享台（t260921-06，runner 生命周期面）
# 宿主令 260921：「整机一个不行，顶多一次集成测试用一个 temporal 容器。」——共享
# 粒度=批（一次跑批）：本执行器对含消费者的轮恰预起 1 个 kind=batch 台（+1 卷 +1 网），
# 批内各场景经消费缝（lib_gate.require_stage / with_stage.sh，识别 env
# SANDBAR_STAGE_BATCH）按命名空间隔离复用；批终 down 全灭零残留（批间隔离不变）。
# 例外条目（batch_stage_exceptions.json 在册：被测对象就是 server 本体启停/多台机械）
# 不注入、自管私台——例外通道显式化（要求4）。
# 本段全部 stdout 行的词面前缀纪律（t260921-06 仲裁 A 族）：verify_lane integ 道把
# 首字符 {/[ 的行当规范行候选、解析失败计红（malformed 非空=闸红），明细行规则另收
# `ENV_FAIL [` 起首行为幻影条目——故通告一律 `batch-stage: ` 起首、环境红一律
# `ENV_FAIL: ` 形（不带 `[`）。看守 t260912-01-summary-count-purity S2b 机械执法此面。

BATCH_ENV = "SANDBAR_STAGE_BATCH"                # 消费缝注入键（lib_gate/with_stage.sh）
BATCH_MANIFEST_ENV = "SANDBAR_BATCH_MANIFEST"    # 例外清单路径覆盖（看守桩测缝）
# 进程级批台态（_run_entry 注入面读取；一进程一轮，嵌套轮=独立子进程直调本文件）。
_BATCH_STATE = {"project": None, "consumers": frozenset()}


def batch_exception_entries():
    """例外清单装载（机器真源 integration/batch_stage_exceptions.json）。缺失/畸形=
    响亮警告+空例外集——分类器 fail-safe 方向=「宁过起不漏注」（多建台可观测、
    漏注入=批消费者静默无台假绿，方向不可反）。路径覆盖 env=看守桩测缝。"""
    path = os.environ.get(BATCH_MANIFEST_ENV) or os.path.join(
        _REPO_ROOT, "integration", "batch_stage_exceptions.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        print("BATCH_STAGE_WARN 例外清单不可读（%s：%s:%s）——按空例外集分类（宁过起不漏注）"
              % (path, type(e).__name__, e), flush=True)
        return set()
    if not isinstance(data, list):
        print("BATCH_STAGE_WARN 例外清单形态非数组（%s）——按空例外集分类（宁过起不漏注）"
              % path, flush=True)
        return set()
    return {str(it.get("entry")) for it in data if isinstance(it, dict) and it.get("entry")}


def batch_consumers(entries):
    """分类器（候选 A）：pool ∈ {engine, exclusive} ∧ entry ∉ 例外清单 ⇒ 批消费者。
    池面依据=review gen1 交叉实证（批消费者条目 ⊆ engine∪exclusive，池外零命中；
    每票集测段 exclude engine,exclusive ⇒ 全不在册 ⇒ 零预起零注入=最高频路径零回归）。
    分类不变式由 t260921-06-batch-manifest-contract 每票段静态执法（候选 ⊆ 两池 ∪ 清单）。"""
    exc = batch_exception_entries()
    return [e for e in entries
            if pool_of(e) in ("engine", "exclusive") and e[0] not in exc]


def _batch_project_name():
    """批台工程名 batch-<runid8>-<pwdhash8>：同轮稳定，跨轮/跨仓互异（pwdhash=仓根
    md5 前 8，与 with_stage.sh 泳道化同源）；形过 stage_docker PROJECT_RE。"""
    rid = "%08x" % (int(time.time() * 1000) % 0x100000000)
    ph = hashlib.md5(_REPO_ROOT.encode("utf-8")).hexdigest()[:8]
    return "batch-%s-%s" % (rid, ph)


def _stage_cli_path():
    return os.path.join(_REPO_ROOT, "integration", "stage_docker.py")


def batch_preboot(consumers):
    """批台预起（stage_docker ensure --kind batch；清扫后、场景前）。零消费者轮=零建台
    零注入（打印留痕，最高频路径零回归）。失败=响亮 ENV_FAIL（调用方 exit 2 快速红：
    本轮零场景开跑零注入——要求⑤不假绿，绝不带病开跑）。"""
    if not consumers:
        print("batch-stage: 本轮零批台消费者（engine/exclusive − 例外清单为空集）"
              "——零建台零注入", flush=True)
        return True
    project = _batch_project_name()
    names = ",".join(e[0] for e in consumers)
    print("batch-stage: 批台预起 ensure --project %s --kind batch（消费者 %d 条：%s%s）"
          % (project, len(consumers), names[:160], "…" if len(names) > 160 else ""),
          flush=True)
    try:
        p = subprocess.run(
            [sys.executable, "-B", _stage_cli_path(), "ensure", "--project", project,
             "--services", "temporal", "--kind", "batch"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, cwd=_REPO_ROOT)
    except subprocess.TimeoutExpired:
        print("ENV_FAIL: 批台预起超时（>600s）——本轮拒绝开跑（不假绿；batch-stage）",
              flush=True)
        return False
    tail = ((p.stdout or "") + (p.stderr or ""))[-600:]
    state = None
    if p.returncode == 0:
        for line in reversed((p.stdout or "").strip().splitlines()):
            s = line.strip()
            if s.startswith("{"):
                try:
                    state = json.loads(s)
                    break
                except ValueError:
                    continue
    if p.returncode != 0 or not isinstance(state, dict) \
            or not ((state.get("ports") or {}).get("temporal")):
        print("ENV_FAIL: 批台预起失败（rc=%s 回执=%s）——本轮拒绝开跑"
              "（要求⑤：不假绿；batch-stage）尾段=%s"
              % (p.returncode, "有" if isinstance(state, dict) else "无", tail), flush=True)
        return False
    _BATCH_STATE["project"] = project
    _BATCH_STATE["consumers"] = frozenset(e[0] for e in consumers)
    return True


def batch_teardown():
    """批终收口（stage_docker down：容器/卷/网全灭零残留——批间隔离不变）。失败响亮
    留痕不拦收口（拆台纪律）；幂等：未持有=零操作；调用后批态清零（重入安全）。"""
    project = _BATCH_STATE["project"]
    _BATCH_STATE["project"] = None
    _BATCH_STATE["consumers"] = frozenset()
    if not project:
        return
    print("batch-stage: 批终收口 down %s（容器/卷/网全灭）" % project, flush=True)
    try:
        p = subprocess.run([sys.executable, "-B", _stage_cli_path(), "down",
                            "--project", project],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, cwd=_REPO_ROOT)
    except (subprocess.TimeoutExpired, OSError) as e:
        print("BATCH_STAGE_WARN 批台收口 down 异常（%s: %s）——残留已留痕（失败不拦收口）"
              % (type(e).__name__, e), flush=True)
        return
    if p.returncode != 0:
        print("BATCH_STAGE_WARN 批台收口 down 非零（rc=%s）——残留需归因：尾段=%s"
              % (p.returncode, ((p.stdout or "") + (p.stderr or ""))[-300:]), flush=True)


def _batch_signal_teardown(signum, frame):
    """信号路径（SIGINT/SIGTERM，t260921-06 全终态收口段）：批台就地 down 后快速退
    （os._exit——执行器已无完整结果，半轮=诚实中断；在飞场景子进程由自身超时/管道
    断开兜底，批台 zero-residue 由本 down 保证）。"""
    print("batch-stage: 收到信号 %s——批台就地收口后退出" % signum, flush=True)
    batch_teardown()
    os._exit(130)


def main(exclude_pools=None, only_scenarios=None) -> int:
    """Run the registry as pools (host-ordered t260902 pool split): an entry
    may carry an optional fourth element — None/absent = the "main" pool;
    "ro"/any other string = a named pool; "exclusive" = runs alone before all
    pools (since campaign 3b only the shared-temporal ticket writer stays
    there; the other 10 former exclusives are the concurrent "engine" pool).
    Pools run in parallel; within a pool it is strictly serial (order and
    reproducibility). Cross-pool ordering may interleave —
    the engine/tools parse line by line and do not care about order.

    只跑点名（t260922-12 ④定点复跑）：only_scenarios（缺省读 env
    SANDBAR_SCENARIO_ONLY，与排除旋钮同注入模式，verify.yaml cmd 零改动）非空时
    本轮只跑点名条目——名单含不在册条目=一条都不跑 rc=2（fail-closed，reprobe
    同族）；expected/ran 口径=本轮点名在册（未被点名的条目不在本轮在册，不冒充
    已跑）；点名与池排除可叠加（点名∩非排除池才跑）。场景判定本身与池排除口径
    零改动。

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
    # ---- t260913-03 池排除（缺省零分支：无 env/CLI 时 excluded=[]，逐字节同改前）----
    excluded, bad_tokens = parse_exclude_pools(
        os.environ.get("SANDBAR_SCENARIO_EXCLUDE_POOLS")
        if exclude_pools is None else exclude_pools)
    for tok in bad_tokens:
        print("EXCLUDE_POOLS_WARN [%s] 池名 token 非法（合法形 [a-z0-9-]+）——已剥离，"
              "本轮未排除该 token" % tok, flush=True)
    excluded_entries = [e for e in SCENARIOS if excluded and pool_of(e) in excluded]
    if excluded:
        _known = sorted({pool_of(e) for e in SCENARIOS})
        for _p in excluded:
            if _p not in _known:
                print("EXCLUDE_POOLS_WARN [%s] 在册池零命中（在册池=%s）——本轮未因此少跑"
                      "任何条目；闸侧 --print-pool-assets 会把未知池判红"
                      % (_p, ",".join(_known)), flush=True)
        print("本轮跳过池=%s（少 %d 条）" % (",".join(excluded), len(excluded_entries)),
              flush=True)
        for e in excluded_entries:
            print("  跳过 [%s]（池=%s）" % (e[0], pool_of(e)), flush=True)
    # ---- t260922-12 只跑点名（缺省零分支：无 env/CLI 时 only=[]，逐字节同改前）----
    only_names = parse_only_scenarios(
        os.environ.get("SANDBAR_SCENARIO_ONLY")
        if only_scenarios is None else only_scenarios)
    registry = SCENARIOS
    if only_names:
        by_name = {e[0]: e for e in SCENARIOS}
        missing_only = [n for n in only_names if n not in by_name]
        if missing_only:
            # fail-closed（reprobe 同族）：点名错=调用方 bug——一条不跑、零副作用，
            # 在任何起台/卫生钩子之前返回（不烧 docker 面）。
            print("FAIL [__executor__] 点名名单含不在册条目：%s——一条都未跑"
                  "（--only fail-closed，t260922-12）" % ",".join(missing_only),
                  flush=True)
            print("SCENARIOS ran=0 pass=0 fail=0 env_fail=0 na=0 (0.0s)", flush=True)
            print("ONLY_SUMMARY %s" % json.dumps(
                {"ran": 0, "missing": missing_only,
                 "error": "点名名单含不在册条目"}, ensure_ascii=False), flush=True)
            return 2
        registry = [by_name[n] for n in only_names
                    if not (excluded and pool_of(by_name[n]) in excluded)]
        _skipped_only = len(only_names) - len(registry)
        print("本轮只跑点名 %d 条（点名=%s%s）"
              % (len(registry), ",".join(only_names),
                 ("；其中 %d 条属被排除池未跑" % _skipped_only) if _skipped_only else ""),
              flush=True)
        for e in registry:
            print("  点名 [%s]（池=%s）" % (e[0], pool_of(e)), flush=True)
    pools, exclusives = {}, []
    for e in registry:
        if excluded and pool_of(e) in excluded:
            continue
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
        name, exit_code, tail_out, dur, t_start, full_out = _run_entry(e)
        spec = _spec_from_output(name, pool_name, full_out, exit_code, dur, t_start)
        if spec:
            print(spec, flush=True)   # 规范行（协议消费面；本层唯一生产缝=执行器综合，t260912-01）
        # 计数单源化（t260912-01 缺陷②）：spec_cases 只收执行器本层综合行，子进程
        # stdout 一律不进 recount 输入——旧「场景 stdout 的 `{` 行即协议在产」收集缝
        # 把嵌套执行器输出灌进明细（260912 实锤：+1 pass 重分类 fail，两套汇总分叉
        # 照常放行）。`_fp_mod` 显式守卫：协议库缺席时明细留空 → INTEG_SUMMARY 走
        # rc 回落支路、_counts_mismatch 降级返回 None（声明降级面，真实可达）。
        with lock:
            if spec and _fp_mod is not None:
                obj = _fp_mod.parse_spec_line(spec)
                if obj and '__malformed__' not in obj:
                    spec_cases.append(_fp_mod.normalize_case(obj))
        dur_tag = " (%.1fs)" % dur
        # Three-state line: 0=PASS / 2=ENV_FAIL (environment red — the indented
        # tail says what is missing) / -8=spawn 面（同 ENV_FAIL 口径，t260911 仲裁①）
        # / anything else = FAIL product red.
        env_like = exit_code in (2, _SPAWN_FAIL)
        if exit_code == 0:
            block = ["PASS [%s]%s" % (name, dur_tag)]
        elif env_like:
            block = (["ENV_FAIL [%s] exit=%s%s" % (name, exit_code, dur_tag)]
                     + [_echo_tail(ln) for ln in tail_out.splitlines()[-6:]])
        else:
            block = (["FAIL [%s] exit=%d%s" % (name, exit_code, dur_tag)]
                     + [_echo_tail(ln) for ln in tail_out.splitlines()[-6:]])
        with lock:
            ran += 1
            passed += (exit_code == 0)
            env_failed += env_like
            failed += (exit_code not in (0, 2, _SPAWN_FAIL))
            timings.append({"pool": pool_name, "name": name,
                            "status": ("PASS" if exit_code == 0
                                       else "ENV_FAIL" if exit_code == 2 else "FAIL"),
                            "dur_s": round(dur, 1),
                            # 非绿条目持久化尾段（t260910-08 arbitrate gen3）：此前
                            # tail 只进 stdout 即弃，报告对 FAIL 无败因可读，仲裁轮
                            # 只能盲跑复现。PASS 不存（体积与隐私面，绿的无须读）。
                            **({} if exit_code == 0 else {"tail": tail_out[-1200:]})})
            print("\n".join(block), flush=True)

    timings = []   # KI-060 prep 2: timing distribution (one row per scenario, with pool attribution)
    _sweep_residue_stages()   # t260912-02 清理挂点①：套件前残台清扫（判拆点名；失败响亮不中止）
    _docker_hygiene()   # 起跑前台面卫生（t260910-14 arbitrate gen2/gen3：见函数注）
    # ---- t260921-06 批台预起（清扫后、场景前）：恰一批消费者轮=恰起 1 个批台 ----
    selected = list(exclusives) + [e for _lst in pools.values() for (e, _s) in _lst]
    consumers = batch_consumers(selected)
    if not batch_preboot(consumers):
        # 快速环境红（要求⑤不假绿）：本轮零场景开跑零注入，不烧整套
        return 2
    _prev_sig = {}
    if _BATCH_STATE["project"]:
        for _s in (signal.SIGINT, signal.SIGTERM):
            try:
                _prev_sig[_s] = signal.signal(_s, _batch_signal_teardown)
            except (OSError, ValueError):
                pass
    spec_cases = []   # t260912-01：规范行明细（只收执行器本层综合行；子进程 stdout 不进计数），INTEG_SUMMARY 以此为准
    executor_error = None   # t260911 仲裁②：池级异常必须响亮产品红，绝不静默吞
    try:
        for e in exclusives:      # exclusives go first, overlapping no pool (always serial)
            _drain([(e, True)], "exclusive")
        try:
            if conc_width <= 1:
                # SANDBAR_POOL_CONC=1 = 全串行回退语义（提速战役③步骤0 计划验收②）：
                # 不光池内宽度收 1，池间也顺次排开——否则六个池各一路并发，负载
                # 敏感场景（起台族/capture 全视图走查）在「回退」里仍要扛六路并发，
                # 回退形同虚设（260910 实锤：只设池内宽度时 wall=467s 与缺省无差）。
                for fname, pv in pools.items():
                    _drain(pv, fname or "main")
            else:
                with ThreadPoolExecutor(max_workers=max(1, len(pools))) as ex:
                    # 句柄必须保留逐个 .result()（t260911 仲裁②实锤：submit 不存句柄
                    # 时池级异常从不上浮=条目静默丢失照常出绿——自家注释承诺落空态）
                    futs = [ex.submit(_drain, pv, fname or "main")
                            for fname, pv in pools.items()]
                    for f in futs:
                        f.result()
        except Exception as ex:   # noqa: BLE001 —— 任何池级异常 = 响亮产品红中止
            executor_error = "池级异常（%s: %s）——条目可能丢失，响亮产品红中止" % (
                type(ex).__name__, ex)
            print("FAIL [__executor__] %s" % executor_error, flush=True)
    finally:
        # 批终收口（t260921-06 验收④）：正常/异常/信号每条路径都 down 批台零残留；
        # 恢复既有信号处理（外层 runner 的信号语义不被本层吞掉）。
        batch_teardown()
        for _s, _h in _prev_sig.items():
            try:
                signal.signal(_s, _h)
            except (OSError, ValueError, TypeError):
                pass
    # Summary five counters (t260904-12): na=N/A is a leg-level state, already
    # folded into pass/fail inside the scenario (all legs N/A = scenario red),
    # so at runner level it is always 0 — kept as a placeholder for the shape.
    # ran=pass+fail+env_fail is the "clean in both directions" invariant;
    # violating it = the summary is lying, exit product red (runner self-check).
    consistent = (ran == passed + failed + env_failed)
    wall = time.time() - t0
    # t260911 仲裁③：ran==在册数是唯一机械不变式（汇总自洽挡不住条目级丢失）
    # t260913-03：在册数=本轮在册（扣除被排除池条目——不在本轮在册，不冒充已跑）
    # t260922-12：点名轮的在册=点名∩非排除池（未被点名的条目不在本轮在册）
    expected = len(registry) if only_names else (len(SCENARIOS) - len(excluded_entries))
    complete = (ran == expected) and executor_error is None
    if ran != expected:
        print("FAIL [__executor__] 清单残缺：ran=%d != 在册 %d（条目静默丢失面，"
              "fail-closed 红）" % (ran, expected), flush=True)
    if excluded:
        print("本轮跳过池=%s（少 %d 条）" % (",".join(excluded), len(excluded_entries)),
              flush=True)
    print("SCENARIOS ran=%d pass=%d fail=%d env_fail=%d na=0 (%.0fs)"
          % (ran, passed, failed, env_failed, wall), flush=True)

    # ---- t260910-13：执行器汇总行（闸补 baseline_ref 并以规范行明细重算复核——
    # C6 分工：执行器产计数/耗时/并发/指纹，测试不写汇总；此行是执行器前置快检，
    # 复核权威=闸重算）。计数来源：有规范行明细时按明细计（明细=执行器本层综合行，
    # 与 rc 三态计数由 _counts_mismatch 强制互证）；明细空/协议库缺席回落旧三态计数
    # （声明降级面）。----
    # 谎报即红（t260912-01 缺陷②）：明细重算与 rc 三态计数必须逐字段相等——灌水/
    # 漏收/重分类任何分叉 = 响亮产品红，绝不带着分叉出绿；INTEG_SUMMARY 行保持
    # 明确实值照印（观测面暴露分叉，红因点名见上一行）。
    summary_lie = False
    _mismatch = _counts_mismatch(spec_cases, ran, passed, failed, env_failed)
    if _mismatch:
        summary_lie = True
        print("FAIL [__executor__] 汇总两套计数分叉（谎报即红，t260912-01）：%s"
              % _mismatch, flush=True)
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(_here, "..", "server", "engine"))
        import failure_protocol as _fp
        _parts = _env_fp_parts()
        _fpv = _fp.env_fingerprint(_parts)
        if spec_cases and _fp_mod is not None:
            _counts = _fp.recount(spec_cases)
            _ran, _p, _f, _nc = (_counts["ran"], _counts["pass"],
                                 _counts["fail"], _counts["not_checked"])
        else:
            _ran, _p, _f, _nc = ran, passed, failed, env_failed
        _summary = {
            "ran": _ran, "pass": _p, "fail": _f,
            "not_checked": _nc, "wall_s": round(wall, 1),
            "concurrency": conc_width,
            "pool_config": ",".join(sorted("%s:%s" % kv for kv in conc_pools.items())),
            "env_fingerprint": _fpv["value"],
            "expected": expected,   # t260911 仲裁③：在册条数——闸复核 ran==expected
            # t260913-03：条件键——仅排除旋钮生效时出现（缺省键集逐字节不变）
        }
        if excluded:
            _summary["excluded_pools"] = list(excluded)
            _summary["excluded_count"] = len(excluded_entries)
        if only_names:
            _summary["only_scenarios"] = list(only_names)
        print("INTEG_SUMMARY " + json.dumps(_summary, ensure_ascii=False), flush=True)
    except Exception as _ex:   # 汇总行失败不改场景红绿（观测面），但大声留痕
        print("INTEG_SUMMARY_ERROR %r" % _ex, flush=True)

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
        _report = {"ran": ran, "pass": passed, "fail": failed, "env_fail": env_failed,
                   "wall_s": round(wall, 1), "generated": _dt.datetime.now().isoformat(),
                   "conc_width": conc_width,
                   "conc_pools": sorted("%s:%s" % kv for kv in conc_pools.items()),
                   "timings": timings}
        if excluded:
            _report["excluded_pools"] = list(excluded)
            _report["excluded_count"] = len(excluded_entries)
        if only_names:
            _report["only_scenarios"] = list(only_names)
        rp.write_text(_json.dumps(_report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("报告落档：%s" % rp, flush=True)
    except OSError:
        pass   # a failed report write does not change the exit code (the report is an observation surface)

    if not complete or not consistent or summary_lie:
        # 清单残缺/池级异常/汇总撒谎/两套计数分叉都是执行器自校验红（t260911 仲裁③：
        # ran==在册数是唯一机械不变式，自洽性挡不住条目级丢失；t260912-01：明细与
        # rc 计数互证挡住灌水/漏收/重分类型谎报）
        return 1
    if failed > 0:            # product red first (C7): with FAILs present, environment reds do not dilute the product red
        return 1
    if env_failed > 0:
        return 2
    return 0


# ---- 同泳道单飞锁（t260913-02 arbitrate gen10，闸红 / 17 环境红的根因面）-------
# 实况（260914 21:08-21:10，本泳道）：两个 199 条全轮**并发**在跑——前一轮（墙钟
# 7898s）尾巴落地 21:10:07，后一轮 21:08:42 发车、21:10:32 落档，重叠 85s。两轮共用
# 的是**泳道级**舞台工程名（stage-console-<泳道指纹> / t26090704-sched-<指纹>），
# 于是并发跑互相拆台，三种伤口同源：
#   ① 一轮的 ensure/down 拆掉另一轮在飞的台 → 场景三条子用例齐齐「连接被拒」（实测复现）；
#   ② 一轮子用例 3 种下的旧 ID 让另一轮子用例 1 看到两个 ID → 报出**伪装成产品红的子用例 1 红**
#      （本票闸拦条目 t260907-04-schedule-legacy-retire 即此形）；
#   ③ console 族 17 条在 0.2~0.6s 内瞬时 ENV_FAIL（同名工程活租约冲突，不是产品面）。
# 舞台工程名只有「泳道」维度、没有「run」维度——with_stage.sh 记的 t260910-14 跨泳道
# 同族教训的**下一个面**（同泳道并发）。故并发跑必须机械挡在门外，不靠人记得。
# 边界：只挡 CLI 入口的真全轮；注入式电池（sc_executor_* 等以 importlib 直调
# rs.main()）不经过本锁——嵌套调用不会被自锁死（零回归面）。
RUN_LOCK_OFF_ENV = "SANDBAR_INTEG_ALLOW_CONCURRENT"


def _run_lock_path():
    """锁文件落平台临时区（不脏工作树）：键=本泳道仓根 realpath——同泳道共享一把，
    跨泳道互不影响。显式覆盖 knob 供回归场景（t260913-02-integ-run-singleflight）
    与人工演练指定锁档——缺省恒为泳道键。"""
    override = os.environ.get("SANDBAR_INTEG_RUN_LOCK_PATH")
    if override:
        return override
    root = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    key = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "sandbar-integ-run-%s.lock" % key)


def _acquire_run_lock():
    """非阻塞抢「本泳道集成跑」单飞锁：返回 fd（持有到进程结束，flock 随进程消亡自
    释放）；抢不到返回 -1（调用方以环境红 2 收口——本次**零场景开跑**，按环境面归因）；
    无 fcntl 平台/显式关闭返回 None（无锁但留痕，不静默）。"""
    if os.environ.get(RUN_LOCK_OFF_ENV) == "1":
        print("INTEG_RUN_LOCK 已显式关闭（%s=1）：并发跑的同泳道串台风险由调用方承担"
              % RUN_LOCK_OFF_ENV, flush=True)
        return None
    try:
        import fcntl
    except ImportError:                       # 非 POSIX 平台无 flock：退化面留痕
        print("INTEG_RUN_LOCK 跳过：本平台无 fcntl，无法做同泳道单飞", flush=True)
        return None
    path = _run_lock_path()
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                holder = fh.read().strip().replace("\n", "；")
        except OSError:
            holder = ""
        print("ENV_FAIL: 同一泳道的集成跑已在进行中（%s：%s）——两次并发全轮共用泳道级"
              "舞台工程名会互相拆台（拆在飞的台=连接被拒／旧 ID 串台=产品红误判／console 族"
              "瞬时环境红）。等它跑完再发车；确需并发时显式 %s=1。本次未开跑任何场景，"
              "按环境红收口" % (path, holder or "持有者未留痕", RUN_LOCK_OFF_ENV), flush=True)
        os.close(fd)
        return -1
    try:                                      # 持有者留痕：让后一位的点名有内容可读
        os.ftruncate(fd, 0)
        os.write(fd, ("pid=%d 起于=%s repo=%s\n"
                      % (os.getpid(), datetime.datetime.now().isoformat(),
                         os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                 .encode("utf-8"))
        os.fsync(fd)
    except OSError:
        pass
    return fd


def _cli(argv):
    """唯一 argv 解析点（t260913-03）：main() 缺省不读 sys.argv——既有注入式电池
    无参直调 rs.main() 必须字节兼容（全树无带参调用者：verify.yaml 的 integration.cmd
    无参数）。未知 flag 忽略（保持旧调用面宽容）。

    t260913-02 arbitrate gen10：真全轮先抢同泳道单飞锁（`--print-pool-assets` 只读
    查询面不占锁——闸会与在跑的轮并行查资产面，占锁会把它挡出闸）。"""
    if "--print-pool-assets" in argv:
        i = argv.index("--print-pool-assets")
        return print_pool_assets(argv[i + 1] if i + 1 < len(argv) else "")
    # --reprobe（t260917-09）：探针出口自带单飞锁获取（reprobe_main 内），故在
    # 通用锁获取之前分流；名单 CSV 逗号分隔（注册表名=[a-z0-9-] 族 slug）。
    if "--reprobe" in argv:
        i = argv.index("--reprobe")
        raw = argv[i + 1] if i + 1 < len(argv) else ""
        return reprobe_main([x for x in raw.split(",") if x.strip()])
    if _acquire_run_lock() == -1:
        return 2
    # --only（t260922-12 ④）：只跑点名条目；与 --exclude-pools 可叠加。None=未
    # 指定（main 内读 env 缺省面）；空串=显式空名单（=全量跑，与未指定同效）。
    only_raw = None
    if "--only" in argv:
        i = argv.index("--only")
        only_raw = argv[i + 1] if i + 1 < len(argv) else ""
    if "--exclude-pools" in argv:
        i = argv.index("--exclude-pools")
        return main(exclude_pools=argv[i + 1] if i + 1 < len(argv) else "",
                    only_scenarios=only_raw)
    return main(only_scenarios=only_raw)


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
