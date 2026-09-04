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
    ("t260904-03-dispatch-knowledge-constant",
     "派活头索引化核心承诺（KI-035 宿主拍板，t260904-03）：两条组装路径（v1 dispatch 头③ / v2 dispatch-next②）的知识段在 workflow×标题×段形态×畸形输入全电池下恒定——恰一行、逐字节同一、含目录锚 docs/README.md（不随票面相关性膨胀=「60-80k token/票、与票面相关性无关的重复消耗」根除面）；且 prompt 内提及的一切 docs/*.md|json 路径落盘存在（旧表「掌握→掌握模型设计.md、content-pipeline→平台架构设计.md」留守 suyou 断链形态的根除守护）。锚公开渲染契约不锚实现，文案重构不改契约则不红；实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-03/sc_dispatch_knowledge_constant_and_linked.py", "ro"),
    ("t260904-03-dispatch-composition-integrity",
     "恒定知识行×派活契约组合完整性（t260904-03，用户旅程=被打回重派的 agent 收到的完整指令仍自洽）：注入 previous_context 后 v2 顶层编号整体后移一位且合法（1 起/无重号/严格递增；条件节缺席跳号=既有占位契约，全节在位形态 1..N 连续——注入/交接/朴素三态实得序列直接钉在断言标签里）、知识段恰一行且缩进块 1 内；前段交接多行 report+多行 user_request+spec 共存不扰动；v1 段专项条款（content-pipeline/ai-review）/分工实例/写集在否——均不扰动知识段文本（与朴素基线逐字节同）。防插错列表位破坏编号/分支双写/条款吞噬/重派路径漏新行；实现段落地前红属预期",
     "python3 integration/t260904-03/sc_dispatch_composition_integrity.py", "ro"),
    ("t260904-03-forced-reading-retired",
     "KI-035 修复反向守护（t260904-03 验收 E 机械化，merge 关卡可跑）：server/**/*.py（引擎代码面）+活文档 docs/README.md 对 WORKFLOW_CONTEXT/TITLE_CONTEXT_RULES/context_docs 零活引用残留——防旧映射表从旧代码/旧文档抄回（照搬带回旧债的静态守护）；notes/ 历史审计行、.suyou/ 段快照、temporal-poc/tests L1 负断言源码豁免（断言面≠消费面，写明防误判）；扫描器自证红绿。实现段落地前红属预期",
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
     "项目会话区账册状态旅程（t260904-01 面①，灰盒 L3）：多项目用户从顶部行时代旧账册（无 seq）升级——J1 存量迁移各项目独立 1..n+幂等+serialize 往返持久化；J2 编号生命周期兑现拍板 1（关闭不回收余 tab 保号、新会话续号不填空、blank 换绑保号、关闭不回退计数器；↺ 重开已随票② R8 退役）；J3 项目行（pickProjectTabs 过滤/seq 升序/title 三级兜底/active 唯一/工单不进）——票② R8 顶部行消费面已退役，项目行是账册唯一渲染面；J4 跨键不一致对抗（计数器孤高跳号不重发、偏低/丢失按现存最大兜底防撞、账册手改撞号不崩 active 至多一、畸形 seq 剔字段不剔条目后 backfill 重补、LEDGER_CAP 淘汰后计数器不回退）。与随票 smoke（单点纯函数+源文本锚）步骤级共享、intent 级不同：旅程连续状态转移×两消费面交叉×跨键不一致。锚 shared/sessions.ts 公开导出面（方案 D1/D2 定稿：seq 字段/nextProjectSeq max 语义），不锚内部实现；确认框交互/正方形形态/折叠同隐/弹层裁剪为 node 不可测面，人工走查清单见该票结果文件",
     "node integration/t260904-01/sc_project_sessions_ledger_journey.mjs", "ro"),

    # ---- 260904 P3/e2e 回迁（KI-038 收尾）：browser 族 16 条 + t260902-02 e2e 2 条。
    # 前置已齐：票①(D) 隔离台（bench.py 槽位制）随 t260904-02 落 main；playwright-core
    # 仍缺（KI-036）——缺环境场景须干净 SKIP 不假红，依赖恢复后自动生效。
    ("ticket-session-restore",
     "ticket-session 面双半契约（t260831-08 起；browser 半被 t260903-07 反转）：服务端 POST ticket-session/open 保留 find-or-create（session_id=ticket-<id>、created 旗标、重开不重复）与畸形 id/缺 project/未知 project/不存在工单显式 4xx；浏览器半=点工单行中列详情照常开、右栏 chat 零切换（快照零注入、phase 不变、多行点击零 churn）",
     "node integration/baselines/sc_ticket_session_restore.mjs"),
    ("ticket-evidence-images",
     "(black-box, user perspective): // QA screenshots (.suyou/screenshots/*.png in the lane) ",
     "node integration/baselines/sc_ticket_evidence_images.mjs"),
    # （session-top-entry / session-tab-interactions 两基线随票② R8 顶部行退役
    #   正当退役，t260904-05：被测面 SessionTopEntry/wb-sessTop 家族已删，无残留
    #   消费方；替代看守=smoke/hero.mjs 反转断言 + project-sessions.mjs S6。）
    ("capture-lane-preset",
     "capture-lane-preset.mjs —— 隔离台 preset 物化基线（t260901-02）。 // // 断言 server/dsh/ui-check/cap",
     "node integration/baselines/sc_capture_lane_preset.mjs", "browser"),
    ("capture-chat-e2e",
     "(black-box, user perspective): // t260901-02 acceptance walk found the capture evidence ",
     "node integration/baselines/sc_capture_chat_e2e.mjs", "browser"),
    ("capture-chat-active",
     "（黑盒，用户视角）： // t260901-02 验收走查实证：隔离台端到端实跑 chat 视图 25s 内未出现 // data-phase=active，capture 退",
     "node integration/baselines/sc_capture_chat_active.mjs", "browser"),
    ("capture-redline-gate",
     "(black-box, user perspective): // The capture evidence tool may create sessions and SEND",
     "node integration/baselines/sc_capture_redline_gate.mjs", "browser"),
    ("t13-evidence-lightbox",
     "(black-box, user perspective): 工单详情抽屉的截图证据缩略图网格 // (t260831-08) 现在支持看图灯箱。用户可感知契约（以 t2609",
     "node integration/t260901-13/sc_evidence_lightbox_dom.mjs", "browser"),
    ("lane-parallel-dom",
     "(black-box, user perspective): t260901-05 shipped the lane diagram's // parallel-fork re",
     "node integration/baselines/sc_lane_parallel_dom.mjs", "browser"),
    ("metrics-donut-dom",
     "t260903-09 度量三 donut 白板修复的 DOM 级基线（黑盒） // 用户视角：有数据时三张环形图——时间去哪了/有无代码变更票占比/模型份额——真渲染非白板（canvas 有非透明像素），人审扇区独立橙色，畸形数据走人话空态不崩；cache-first 先吐 stale 快照角标后台全量替换 // 两层结构同 sc_lane_parallel_dom：S0 bundle 契约+纯逻辑 smoke（全环境跑），S1 隔离测试台真浏览器 DOM（缺环境干净 SKIP）",
     "node integration/baselines/sc_metrics_donut_dom.mjs", "browser"),
    ("multi-tab-coexistence",
     "(black-box, user perspective): the ticket workbench is used with // MULTIPLE console tab",
     "node integration/baselines/sc_multi_tab_coexistence.mjs", "browser"),
    ("t22-t260901-22-approve-modal-ui",
     "* * integration/t260901-22/t02_approve_modal_ui.mjs * —— KI-004「approve 弹层自由备注」用户可感知 UI ",
     "node integration/t260901-22/sc_t02_approve_modal_ui.mjs", "browser"),
    ("t22-t260901-22-approve-modal-faultmodes",
     "本 UI 家族（wb-modal）无 Esc/外点关闭处理器（rework 打回弹层同样只有「确认/取消」 // 两条真实关闭路径）——验收口径改为：每一处 setApprov",
     "node integration/t260901-22/sc_t03_approve_modal_faultmodes.mjs", "browser"),
    ("t02-t260902-02-prune-e2e",
     "client.py 末行 JSON 回执；解析失败 = FAIL。",
     "python3 integration/t260902-02/sc_t05_prune_e2e.py"),
    ("t02-t260902-02-archive-legacy-e2e",
     "注入缝直调真命令逻辑（活文件系统，零 Temporal server 依赖）。",
     "python3 integration/t260902-02/sc_t06_archive_legacy_e2e.py"),
    ("t260903-07-click-no-chat-switch",
     "点工单不切右侧会话（t260903-07①核心反转）：点工单行后中列详情照常开（.wb-d2-steps 在场）、右栏 chat 零变化——【工单上下文】快照零注入、data-phase 不变、项目会话区 tab 全集不含 ticket- 行（票② R8 改锚：顶部行已退役，判据改 [data-wb-psess-tab] 全集）；多行重复点击零注入零 churn（旧契约「点行→开 ticket- 会话」的显式反转守卫，防联动复活）",
     "node integration/t260903-07/sc_t01_click_no_chat_switch.mjs", "browser"),
    ("t260903-07-chat-project-tag",
     "全局 chat 用户消息项目 tag 契约（t260903-07②）：引用真实工单 id 的消息行渲染文本=注册项目 key 的 chip（颜色非空）；同项目恒同色、不同项目不同色、页面重载后同色（确定性映射的用户可感知面）；全部 chip 文本 ∈ 注册项目键不造假 key；「归属不了→不渲染」是 env 相关声明行为、不在场景层强断言（L1 DOM 桩已锁，chip 经 ::before 伪元素渲染故断言走 getComputedStyle）",
     "node integration/t260903-07/sc_t02_chat_project_tag.mjs", "browser"),
    ("notes-write-gate",
     "机械闸守卫：dev-lane 工单禁写 notes/（宿主令 260904——票据/知识库账本归 main 侧直管，t260904-01/03 的 KI 行合并冲突与 notes/epics 草案直落为动因）。三执法点：A 合并闸 verify_lane 四态真子进程（声明了 notes/ 也拦防自授权/D 删账同拦/写集内普通文件不误伤/粗判据分支同拦）；B 建单侧 ticket.create 写集含 notes/ 创建即拒（纯函数面零 Temporal，人话指路结算 note）；C 本仓 verify.yaml write_allow 无 notes/ 静态防回潮。tmp git 仓全本地",
     "python3 -B integration/baselines/sc_notes_write_gate.py", "ro"),


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
    ("t260904-05-top-entry-retired-form",
     "顶部行退役后的入口形态契约（R8+R7 左栏，browser）：lib 产物零退役符号（SessionTopEntry/wb-sessTop/pickSwitchTargets/renameEntry/data-wb-session-*）且含新锚（projband/psess-dot/psess-color）；DOM 中 data-wb-session-{entry,new,row,reopen} 全不在场、无 wb-sessTop 类元素；出厂全局新建钮继续被压制不回显（拍板 1）；组头色点/+钮/根容器 --wb-psess-color 三处同色且 ∈ 确定性色板、刷新恒色（验收 5）；关闭确认弹层文案含「仅关闭入口/不删除」且无「↺/最近关闭」表述（拍板 2）；console 零 error",
     "node integration/t260904-05/sc_top_entry_retired_form.mjs", "browser"),
    ("t260904-05-chat-band-affiliation",
     "右栏 chat 项目色带归属通道（R7 核心新意=用户需求③，browser）：fresh 空账册不渲染色带（不在册声明行为）；项目行 + 新建后 [data-conversation-scroll] 本体带 data-wb-chat-projband=<该项目 key>（属性锚非包裹节点=零 childList 侵入的可感知面）；色带 3px + head 自有 style 在场且色与左栏 --wb-psess-color 同源；点工单行归属不动（t01 同契约：chat 不切换）；刷新后归属恢复（账册持久）；console 零 error",
     "node integration/t260904-05/sc_chat_band_affiliation.mjs", "browser"),
    ("t260904-05-session-lifecycle-ui",
     "项目行会话生命周期 UI 全链（接管随 R8 退役的 session-tab-interactions 用户路径 intent，browser）：+ 新建续号且 active 恰一；关闭确认取消不动/确认才关；序号不回收（关掉的号不填洞，拍板 1）；刷新后整组 tab 持久；关完全部再新建仍续大号（BO-1 closed 号域防撞、计数器不回退）。与 t260904-01 journey（纯函数账册状态机）intent 级不同层：本条=用户操作流×真实 UI 呈现",
     "node integration/t260904-05/sc_session_lifecycle_ui.mjs", "browser"),
    ("t260904-05-ledger-adversarial-boot",
     "账册外部输入三态的真实 boot 对抗（畸形/缺失/旧版，browser；journey J4 的 boot 路径复验，intent=boot 韧性非函数容错）：旧顶部行时代账册（无 seq+title）升级渲染且补号、ticket- 条目永不进 tab；project 字段畸形（非字符串/空串）条目不落任何项目组、色带不渲染、+钮仍可用；账册+计数器双键坏 JSON → 按丢失处理 boot 干净；各 case console 零 error",
     "node integration/t260904-05/sc_ledger_adversarial_boot.mjs", "browser"),
    ("t260904-06-spec-card-dom",
     "工单详情「执行规格（spec）」卡渲染契约（t260904-06，宿主拍板 B 形态，真浏览器 S1-only 无 S0 段）：API 边界桩 fixture、浏览器/console/shipped bundle/React 渲染全真——有 spec 票抽屉正文卡正下方出蓝左条卡（恰 1 个、data-v=B、ttl 含「执行规格（spec）」、徽标=spec.length+「 字」、.txt 全文逐字保真、HTML 特殊字符纯文本零注入、border-left 4px rgb(9,105,218)、pre-wrap）；无 spec 字段老票卡不渲染且正文卡照旧零扰动；超长 spec 限高 260px 滚动收敛不撑爆抽屉、badge 仍计全文；全旅程零 pageerror。与 developer L1 spec-card-ui.mjs 三产物字符串锁 intent 分工：本场景只锁 payload→像素真渲染面（L1 锁不住 JSX 运行时错/落位/徽标算错/换行丢失）；bundle 陈旧时本场景以「卡不在 DOM」正确变红，归因归 merge-checks 闸与 t260903-04 bundle-sync；缺隔离台/playwright 干净 SKIP 注明 KI-036 依赖恢复自动生效；refusing 3099 红线（t260904-06）",
     "node integration/t260904-06/sc_spec_card_dom.mjs", "browser"),
    ("t260904-09-settle-snapshot-write-journey",
     "收口出仓快照写路径用户旅程（t260904-09，灰盒 L3，真仓真 merge）：工单收口那一刻项目账本上有一份冻结快照（SANDBAR_SETTLE_SNAPSHOT_DIR/<票>.json，schema_version/squash_commit=merge 回执真身/tokens/delivery 键齐）——token 只加总 assistant/message usage（chunk 翻倍哨兵 999 不计、模型归因当时 provider/model）、delivery=squash 真身 numstat 不靠事后 grep；重复收口（Temporal 重试态）载荷稳定不双算、账面被篡改保留旧件不回写（不可变）；会话目录缺失/zstd 撕裂帧软降级 merge 照常 ok（观测欠账不卡交付）；真·无内容可收（HEAD=他票 squash）zero_change=true 不吸他票账；票 id 注入 ../ 不落 settle 目录之外。与 developer L1（temporal-poc/tests 纯函数电池）intent 不同层：本条守「真 git squash merge→快照文件契约」跨组件写路径。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-09/sc_settle_snapshot_write_journey.py"),
    ("t260904-09-settle-snapshot-read-journey",
     "settle 快照读侧消费用户旅程（t260904-09，灰盒 L3）：面板交付/token 数字来自 settle 冻结快照（优先级=快照>活口径>归档 grep；有快照即 frozen，不再随后读侧实现/泳道拆除抖动）；无快照存量票归档口径只认 message 以票号开头的 squash 收口提交（引用性提及他账剔除，12 非 62）；口径变更对存量缓存可达（v1 宽口径存量被重算治愈——05 锚同构，宽口径不永续）；donut 四桶（有变更/已收口·零变更/未交付（在制）/不可算（数据缺失））互斥且 Σ=票数、零变更已闭票不落不可算；快照坏 JSON 不炸面板、票走回落口径留人话 reason；SANDBAR_SETTLE_SNAPSHOT_DIR 覆盖根被消费。与 t260904-04-stale-cache-heal-journey（失败维/open 陈旧自愈）、t260903-13-metrics-golden-freeze（响应形状冻结）、workbench/tests delivery-recovery（L1 记录内部机制）intent 不同面：本条守「快照成为数字真源」消费契约与口径收窄/四桶语义。实现段落地前红属预期（R0 夹具自检除外），arbitrate/merge 期必须绿",
     "node integration/t260904-09/sc_metrics_settle_snapshot_read_journey.mjs", "ro"),
    # ---- t260904-07 项目会话开局注入 session-charter（charter 文件+GET 端点+blank 恰一次注入）----
    ("t260904-07-charter-source-contract",
     "charter 交付契约冻结（t260904-07，ro 静态面）：server/dsh/session_charter.md 与宿主定稿真源（notes/discussions/260904-project-session-charter.md 附录 fenced 模板）逐字同步——该文件是「当前在案授权」授权档案第一环（git 版本化），漂移=授权声明与定稿脱钩，宿主合法定稿变更须两处同步（回真源补口径后自回绿）；结构要素在文（四占位符/两纪律语义锚：notes 落盘攒批+点名修复先告知/当前在案授权节在/sandbar、suyou 两分段）；端点注册路径与客户端请求路径两侧各自可解析到同一路径字面量（直字面量或同源常量两实现形态都过——KI-042 同族「路径漂移→恒 404 静默吞」的对症看守）；内置回落模板在位含占位符（缺文件回落不 5xx 的前提）。与随票 smoke intent 级不同层：smoke 锚实现守卫源锚（L1/L2），本条锚交付物↔宿主定稿真源一致性与跨端接线一致性。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-07/sc_session_charter_source_contract.mjs", "ro"),
    ("t260904-07-charter-endpoint-live",
     "charter 端点活体契约（t260904-07，ro fetch 级，隔离台 3199 拒 3099）：GET session-charter?project=<key> 部署后可感知契约——命中项目 200+{ok,charter}+key 实值化+零 {{ 残留（统一渲染）+命中分段头在文；未命中项目仍 200 只回通用段+无该 key 分段+{{project_name}} 弱化=key；缺/空串 project=400 形状错误 JSON 不崩不 5xx；404 时源锚复核精确归因（源码已接线未部署=fail，pre-merge=干净 skip 部署后自动生效）。与随票 smoke intent 级不同层：smoke 直测渲染纯函数（内存面），本条锚 HTTP 可达面（真宿主真文件真路由）；「文件缺失回落」「改文件即生效」需对受控文件写操作不在活体腿，回落归 smoke 纯函数直测、现读现渲染列人工走查",
     "node integration/t260904-07/sc_session_charter_endpoint_live.mjs", "ro"),
    ("t260904-07-charter-injection-journey",
     "charter 注入用户旅程（t260904-07，browser 隔离台）：项目行点 + 新建会话不输入任何内容即见 charter 为首条消息（占位符实值化无 {{ 残留——「每个 session 创建时注入我们想要的 prompt」原话验收面）+截图证据落 .suyou/screenshots/（KI-044 UI 票证据自觉）；随后切换相邻 tab 再切回、reload 重进既有会话，charter 特征串出现次数恒定+tab 集合不变（守卫：恢复/切换路径绝不注入，沿 t260831-08 ⑥ 口径）；console 卫生零 error（过滤无凭据环境已知凭据类噪音）。断言上限=注入链 UI 面，agent kick-off 回复链不在断言面（无凭据隔离台已知限制，有凭据环境人工复判）；未上屏且仅凭据类错误=干净 skip 不假红。与 t260904-05 生命周期场景（tab 形态/续号/关闭链）intent 级不同层：本条锚注入内容可感知行为",
     "node integration/t260904-07/sc_session_charter_injection_journey.mjs", "browser"),
    ("t260904-08-template-face-narrowing",
     "工单模板面收窄契约（宿主令 260904，t260904-08）：真源三表（TEMPLATE_CLASS_NAMES/TEMPLATE_CLASSES/TEMPLATE_DISPLAY_NAMES）恰存 dev-lane、四退役 .py/.yaml 物理退场、v1 幸存面（workflows.py 步1 类+DispatcherScanWorkflow）不过删；用户拒收面——create/ticket-start 传四退役模板任一被拒且报错文案恰列 dev-lane（列全=仅 dev-lane，多列/漏列都算文案失真）、dev-lane 仍过模板闸（推进到下一道必填校验而非「未知模板」）；suggest_next 推荐面收「开新 dev-lane 票 / main 侧直跑验证」两类出路且零退役模板名；client start 类型面收敛 dispatcher-scan（文案锚）。stdlib 段零依赖恒跑；ticket-start CLI 段 venv-half（解释器缺失干净 SKIP 注原因，KI-020③）。与既有模板面守卫无 intent 重复（退役收窄为本票新契约）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "python3 integration/t260904-08/sc_template_face_narrowing.py", "ro"),
    ("t260904-08-template-retire-no-revival",
     "模板退役防复活负扫描（宿主令 260904，t260904-08）：写集五面（引擎/tools/integration/两篇指定 docs）对四退役类名+content-pipeline 记号零无豁免活引用——防从历史抄回复活注册、防半截清除（注册删了但 USAGE/示例仍教学可用）；豁免=带退役标注的注释、v1 留存引擎样例（t260904-03 R1 裁定面+shared.py 留存数据表键）、声明保留的 v1 演示面与退役标注面（两 docs/两 README，且场景反向钉标注在位防豁免黑洞）、注册表 intent 文本与 test_t260904_03_t01 历史对照夹具（C1）；扫描器自证红绿（活引用样本红+标注样本豁免+留存键/留存文件规则命中+面完整性哨兵防空面假绿）。与 t260904-03-forced-reading-retired 分工：彼守 KI-035 旧文档映射表零活引用，本守 260904 模板族退役零活引用，对象不同不互替。实现段落地前红属预期，扫描红输出即待清残留清单，arbitrate/merge 期必须绿",
     "python3 integration/t260904-08/sc_template_retire_no_revival.py", "ro"),
    ("t260904-13-ui-diff-judgement",
     "UI 票判定源=泳道实际 diff×UI 前缀表（t260904-13 KI-044 根治面，灰盒 L2，ro 隔离临时仓）：真 git 仓 merge-base 三点 diff 驱动——粗目录声明（t260904-05 形态：只声明 server/dsh/workbench/ 父目录、实际改会话区 UI 产物）按实际命中（修复面对照：旧声明口径同形态确实漏判，证明修复的票真实存在）；纯引擎 diff 空清单不误伤；声明 UI 但实际无 UI diff 仍为空（按实际不按声明，防 or 实现）；main 侧他人改 UI 不算本票面（t260901-16 三点承诺在 UI 判定面兑现）；混合票只含 UI 前缀路径；脏输入（None/非列表/非字符串/绝对路径/含 ..）不抛按未命中（developer L1 畸形用例随实现重写，本条=持久契约面）；ui_changed_paths activity 接线结构锁（锚 _merge_base_ref 不回落 main 字面、走共享判定辅助、git 失败 err 进 detail fail-closed、进 worker 注册清单）。与 sc_ki044_merge_gate_ui_item（闸输出合同）/sc_ki044_lane_patchgate_wiring（编排接线）intent 不同面；与 developer L1（白盒纯函数、禁真 git）不同层。实现已随本票落地全绿；实现回退或契约破面则红，arbitrate/merge 期必须绿",
     "python3 integration/t260904-13/sc_ki044_ui_diff_judgement.py", "ro"),
    ("t260904-13-merge-gate-ui-item",
     "merge_check 3.6 UI 证据闸输出契约（t260904-13 KI-044 闸面，灰盒 L2）：判定源退役声明口径（3.6 段不再吃 is_ui_write_set(args.write_set)——粒度越粗关卡越弱的 t260904-05 直过根因）、换共享判定辅助（两处同源的闸侧兑现）、复用第 3 项已解析泳道基线 wl_base（t260901-18 假阳性教训不回潮）、命中路径落 check detail「按 diff 判定」留痕+capture.mjs 红灯处置指引不丢、git 层故障该项红不静默（KI-046 同族「验证承诺静默蒸发」堵洞面）、MergeCheckArgs.write_set 字段保留（旧实例回放不破 Args 形状）、selfcheck 旧源码锁退役+新判定源/patched 门锁在场（防改码忘改锁的假绿网）。temporalio 泳道不可用→源码契约锁（t05 同族落地形态；t05 锁 diff base 各归各位，本条锁 UI 判定源与闸文案，不同面）。实现已随本票落地全绿；实现回退或契约破面则红，arbitrate/merge 期必须绿",
     "python3 integration/t260904-13/sc_ki044_merge_gate_ui_item.py", "ro"),
    ("t260904-13-lane-patchgate-wiring",
     "dev_lane UI 判定源接线与部署兼容结构（t260904-13 KI-044 编排面，灰盒 L3）：主链判定换新 activity 必须套 workflow.patched 兼容门（新实例走 diff 判定、挂起中存量实例重放走旧布尔分支=命令序列与旧历史严格一致，部署不破存量工单）；patch id 值钉死 dev-lane-ui-diff-v1（历史标记键改名=存量重放断裂）；新命令恰 1 处（旧链尾——仅存量重放可达——冻结不引入新命令）；patch 门先于新命令（门控形状）；新路径入参取 meta 泳道三件套 worktree/branch/base_ref。与判定源/闸两场景 intent 不同面；与 developer selfcheck（锁字面随实现重写）不同深度——本条锁不可随重构漂移的部署承诺。temporalio 泳道不可用→源码契约结构锁（t05 同族）。实现已随本票落地全绿；实现回退或契约破面则红，arbitrate/merge 期必须绿",
     "python3 integration/t260904-13/sc_ki044_lane_patchgate_wiring.py", "ro"),
    # ---- t260904-10 project lifecycle 票①：sandbar project add/list（注册表接入面）----
    ("t260904-10-project-add-dual-loader",
     "add 产出条目的双侧装载一致性（t260904-10，ro 隔离根）：真跑 `sandbar project add` 后 Python shared.load_projects_registry 与 TS suyou-projects.ts.loadRegistry 从同一隔离根（SANDBAR_PROJECTS_DIR 临时目录）装载出同一条目（key/name/dirs 全等）、零隔离；首装载×seed 自动播种真路径（tracked 种子 suyou 在案+.migrated 落盘）且 add 后种子条目字节不动（决策7 不动账）；体检报告三词汇（verify.yaml/credentials/paths）在文且 credentials 先布置/裸目录两态输出可辨——排他性锚 project.yaml 文件而非条目目录（契约①b：目录与 per-key credentials 可先于 add 布置，O_EXCL 架在目录 mkdir 上=此腿红契约对）；写入零 .tmp. 残留；--json 机器可判。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿",
     "node integration/t260904-10/sc_project_add_dual_loader.mjs", "ro"),
    ("t260904-10-project-add-rejections",
     "add 拒收面全枚举 CLI 真跑（t260904-10，ro 隔离根）：key 白名单（大写/下划线/首字符中划线/42 字符拒，41 字符上界收）；根目录形态（缺参/相对路径/不存在/是文件非目录）；多目录输入语义化拒收（epic 验收2 独立拒收路径：旗标面须能表达多目录输入，且文案点名「单根模型/多目录」——裸 argparse 用法错不算语义拒收）；已注册幂等同判（两次出口码+输出全等）；隔离条目同名拒收；根交叉与互为父子嵌套（父目录/子目录/恰等三向，文案报两个 key）；SUYOU_PROJECTS_YAML legacy 拒收指路（文案点名存量 env）；name 三态（空/含 #/含换行拒且文案点名 name，首尾空白 trim 后收并读回验证）；每拒收腿注册表根字节级零残留（快照比对+.tmp. 泄漏检查）；并发同 key 双 add 恰一成一拒且赢家条目 name/dirs 自洽不混写（TOCTOU 闸）；remove 点位稳定钉（输出点名 remove、无裸 traceback、注册表不动——票①骨架恒红/票②真实现两期皆存活）。实现落地前红属预期",
     "node integration/t260904-10/sc_project_add_rejections.mjs", "ro"),
    ("t260904-10-project-list-report",
     "list 报告契约（t260904-10，ro 隔离根）：人读与 --json 同列注册+隔离条目，隔离原因含 <dir>/project.yaml 定位字面，无 project.yaml 的保留目录不列；票计数降级三态——服务不可达（SUYOU_TARGET_HOST 死端口注入）与 SDK 缺失（PYTHONPATH 空壳 temporalio 包注入，KI-039 教训：依赖缺失不得吞成无数据）两态均 exit 0 不红、条目照列、两态输出可辨；正常计数腿在测试台 17233 可达时真跑（不可达有声 SKIP）。全程显式 env 钉死防缺省外溢生产 7233，零 3099 接触。实现落地前红属预期",
     "node integration/t260904-10/sc_project_list_report.mjs", "ro"),
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
