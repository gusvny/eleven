# 立项单：engine-hardening

| 字段 | 值 |
| --- | --- |
| 代号 | `engine-hardening` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-09-04 |
| 备注 | 起因=260904 t260904-01 首开脑裂事故链（KI-032×KI-033 叠加）；票①=硬闸+指纹+探测+隔离测试台 |

## 背景与问题

260904 实案链：裸 `client.py ticket-start` 不锚 `project_root` → 泳道存**相对路径**，落仓由「抢到 activity 的 worker 按自身 REPO_ROOT」决定 → suyou 侧遗留 headless（僵尸进程，带 supervisor 的 15s ticketEnsure）抢先伺服同一条专属队列 → worktree 建进冻结仓 suyou、agent 跑错仓（跨仓脑裂）。当日处置：cancel 作废 + 杀僵尸进程族 + 清两仓残骸 + 正规入口重开。本 epic 把处置上升为**机制**，并补上集成测试面「引擎行为零覆盖」的结构性空白（现套件纯替身层）。

## 目标（第 1 面）

1. **开票硬闸（KI-032 修复）**：`client.py ticket-start` 收到 `project` 即自查机器级注册表（`SANDBAR_PROJECTS_DIR` 覆盖语义保持）锚 `project_root`，与 `ticket.py:664-669` 同源（加载器收敛单一真源，不双份漂移）；未锚定即**拒收**——任何入口开票必得绝对路径泳道，落仓与执行 worker 解耦。
2. **worker 归属指纹（KI-033 修复）**：工单 worker 注册带引擎仓指纹；ensure 发现**异仓 worker** 伺服同票 → 告警/拒接，跨仓双 serve 不再静默。
3. **doctor 僵尸探测**：`sandbar doctor` 加「异仓引擎进程」扫描——cwd 指向非当前引擎仓的 node/python 引擎进程，红了报出来（迁移/切换后清场从纪律变命令）。
4. **隔离测试台（老仓模式迁回）**：boot 骨架（临时 DSH_HOME / 临时 profile / **port-0 内核分配**真启动 / teardown 三钩子幂等）收成 `integration/` 共享库；temporalite **槽位制**起停（`~/.sandbar/test-benches/slot-N`，flock 独占、崩溃自释、满槽排队不假红）；首个引擎行为场景=裸入口开票 → 断言 workspace 为绝对路径且锚项目主目录（未锚定形态修复后必须拒收）。

## 宿主红线（260904 钦点，验收一票否决）

- **隔离台互不冲突**：多票并行跑场景零假红、零串台（console 端口=内核分配；temporalite=槽位端口 + 槽专属 db + namespace 纵深）。
- **绝不影响生产 temporal**：隔离台不碰 7233/8233（temporalite 的 frontend/UI/metrics **全端口**隔离或禁用，UI 默认 8233 是暗雷必须显式覆盖）；不写生产库；生产 console 的 ensure 永远看不见隔离台里的票（可见域=各自连接的 Temporal）。`SUYOU_TARGET_HOST` 指向生产地址=拒跑（fail-closed）。
- **console 3099 红线照旧**：不重启不停不占用；temporal-tools（console 侧）改动上线后由宿主择机重启生效（staleness banner 提示，不自动）。

## 面/票拆解

- **票①（t260904-02，在飞）**：目标 1–4。写集=引擎（temporal-poc：client/shared/worker + tests）、console 侧 supervisor（temporal-tools/node.ts）、安装器（installer/doctor 面）、`integration/`（bench 库+场景+登记）、KI 册与 epic 本档。**与在飞 t260904-01（workbench 面）写集零重叠，可并行。**
- **票②（t260904-03，宿主令 260904 拍板「索引化」，与票①并行）**：派活上下文索引化——派活头③（dispatch 指令与 dispatch-next 两处）改**恒定知识库规约**（目录=docs/README.md 每篇一句话用途，agent 对照标题/写集按需读；结算 note 列参考 docs 清单作审计），WORKFLOW_CONTEXT/TITLE_CONTEXT_RULES 两表退役（content-pipeline 断链随之消解）；保底两项（CLAUDE.md+岗位说明书）不变。前置=4 篇 frontmatter 补齐（integration 已完成，d63a8bf）。**注意：与票①写集同文件（temporal-poc/shared.py），merge 串行——后并者 rebase 主树消解。**
  - **落地（260904，t260904-03 implement 段）**：两路派活头已换恒定规约（v1 dispatch ③ + dispatch-next ②，文案同源）、两表+context_docs 退役（墓碑注释在位）、结算 note/交付契约两处审计句入位、docs/README.md 去死引用；UT 回归锁 4 例（tests/test_t260904_03_t01_dispatch_header_indexed.py）绿，全量套件失败集与基线逐行一致（存量红=未迁场景薄包装 24 条，KI-038——main 已登记（b896608）、triage 三判清单已落（6484e31）；acceptance 走查曾在泳道隔离视图下补登 KI-036 并改此处引用，merge 轮发现 main 的 KI-036=ui_evidence、本债真号=KI-038，实锤细节已并归 KI-038 行、引用归位）；KI-035 已转 closed（含知识库设计.md §4/§7/§8-M4 漂移登记，修订待人审另票）。
- 后续面（验收后按需再立，不在本面承诺）：引擎行为场景扩展（worker 生命周期/收口自退/多 console 防重）、跨项目 docsDir 解析（KI-034 残余②同族）。

## 验收标准（票①）

1. 裸 `client.py ticket-start` 带 project：产出 workspace 为**绝对路径**且锚 `<项目主目录>/.lane/`；无 project 且无显式锚=明确报错拒收（不是静默相对路径）。
2. 隔离场景里起异仓/异指纹 worker 伺服同票：ensure 侧可见告警或拒接记录（日志/回执可断言）。
3. `sandbar doctor`：fixture 注入假异仓进程 → 探测红；干净环境 → 绿（自证红绿，沿用套件纪律）。
4. 隔离台场景在**两路并发**下各跑各的 temporalite：零端口冲突、零数据串台、断言互不干扰；teardown 后槽位/db/临时家全清。
5. 场景断言**不出现**对生产 7233/8233 的任何连接尝试（含 UI/metrics 端口探测负向断言）。
6. KI-032/KI-033 在册子中转 closed（附票号）；epic 本档面状态更新。

## 票① 交付记录（t260904-02，implement 段）

- **验收 1（KI-032）**：注册表装载器上收 temporal-poc/shared.py（单一真源，ticket.py:112-467 整块改薄壳委托，错误文案逐字保留）；client.py ticket-start 硬闸——lookup_project 锚 project_root → derive_lane_workspace → check_paths_under_project 双查（workspace+worktree）；缺 project/未知 key/路径越界三态各自可辨拒收。
- **验收 2（KI-033）**：worker.py 起跑早写归属指纹 meta（{version,pid,repo_root,ts}，connect 前；SUYOU_WORKER_META 指路 / daemon=<pidfile>.meta；优雅退 best-effort 清）；node.ts `ensureTicketWorkersOnce(deps)→{decisions}`（对外契约，依赖可注入）——同仓 held-same / 异仓 held-foreign（warn{repoRoot,pid,tid}+拒接不杀）/ 畸形 held-unknown（reason 含 meta 路径+state 不哑巴）；apply 闭包真跑注入真件。
- **验收 3**：installer/zombies.py（探针名 probe-engine-zombies；census 注入 `{"processes":[…]}`/live lsof/缺省内嵌样本三档；家族判定=git 归属，主树+兄弟 worktree 不误报——实现期真机实扫 336 进程 0 假红）；doctor.py 拼装第五面，尾行面数动态计数。
- **验收 4/5**：integration/bench.py 槽位制（端口 1910N/1920N/1930N 三显式、槽专属 db+namespace、flock fd 移交 temporalite=崩溃自释）+ bench_console.mjs 薄壳（复用 ui-check/capture-lane.mjs 真源）+ python 审计钩子（socket.connect 对 7233/8233 先记后抛=阻断）。
- **场景证据**：`python3 integration/run_scenarios.py` → **13/13 绿（95s）**（新增 3：ticket-start-anchor / worker-fingerprint-gate / doctor-zombie）；生产 7233/8233 监听面前后 lsof 对照零扰动。
- **槽位全清口径（C7）**：teardown 后槽目录仅剩空 lock 文件=**槽锚**（unlink 会让旧 flock inode 与新建文件失去互斥=假独占风险）；「全清」指 db/wal/shm/日志/临时产物，lock 锚保留。
- **存量联动**：t260903-10 doctor-compat 场景 EXPECTED_PROBES 4→5 + run_scenarios 该条 intent 措辞同步（dispatch 授权的唯一存量触碰）；temporal-tools 改动上线后宿主择机重启 supervisor 生效（不自动重启 console）。
- **遗留**：泳道缺 bin/temporal 与 .venv 由 gitfile 主树回退兜住（KI-020③ 邻接绷带，根治归 dispatcher）；23 个 t260901-XX 测试包装器指向迁仓未带的 integration 目录=既有 latent red（非本票引入，处置另立票）。

## 票① 验收记录（t260904-02 acceptance gen1，260904）

- **六条验收全过**：①payload 绝对锚定+三态拒收（场景①走查实证）；②ensure 真执行三态 decisions+异仓 warn 三要素（场景②）；③doctor 注入红绿+矩阵 5 行+文案自辨（场景③）；④双槽并发隔离+teardown 全清；⑤审计钩子零记录含拦截自证腿+三端口显式，生产 7233/8233/3099 监听者走查前后 PID 零扰动；⑥KI-032/033 本轮转 closed（附票号）。
- **打回轮收敛复核（acceptance gen0 打回三项全闭合）**：P1 bench 槽根降级探测（受限环境原形态必裸 PermissionError → 现真写+删探针探测，明示降级一行带旋钮指路，锁文件不可建=MissingAsset 可辨）；P2 ensure fetch 后 isDisposed 短路；P3 shared.py PROJECT_KEY_RE 收敛单一定义；打回建议腿补齐=integration/tests/test_bench.py 7/7（含满槽排队 BenchBusy「槽满」真 flock 争用断言）。
- **面状态**：票①验收通过；后续面（引擎行为场景扩展/裸入口收敛）按本档约定宿主再立。
- **走查新登记（非阻塞，随后续票处置）**：槽端口为机器全局固定基址而 flock 互斥仅限单一槽根——两个槽根（如降级临时区 vs ~/.sandbar）并行跑同号槽会瞬时 BenchEnvConflict（分类可辨、不对抗语义符合设计；单机同时只跑一个套件/统一槽根即可避免）；降级根落平台共享临时区放大了该撞面，建议后续给降级根掺会话唯一后缀或冲突文案点名「他槽根在跑」。

## 票③：notes/ 写集机械闸（宿主令 260904 直落 main，integration 岗）
动因：t260904-01/03 两单 lane 侧票据账与 main 直修同区相撞（含一次 KI-038 语义冲突须人工取舍）、notes/epics/ 出现草案直落。落地三执法点：verify_lane 合并闸（A/M/T/D 全拦、独立于写集声明）+ ticket.create 建单即拒（纯函数 validate_write_set_no_notes）+ write_allow 除名；守卫场景 sc_notes_write_gate.py 13 断言入清单（套件 92/92）。副作用收红：lane agent 票据账动作改走结算 note→integration main 落账。

### 引擎加固·人工判读注入通道（KI-053，260906 现场=19 号仲裁超限）
现状：blocked 转人工判读后，人工意见无正规注入通道——rework 备注只流 create_plan/implement
（arbitrate/acceptance 只吃机械测试结果 JSON），sign 拒收非人门段，retry_qc 无载荷。
本夜过渡=泳道 .suyou/HOST_RULING.md 自描述文件＋retry_qc（仲裁席续会话时读协调区可见）。
根治面：①build_stage_prompt 增加 host_ruling 注入（meta 字段，sign/rework 通道写）；
②或 blocked 态开放 sign(gate=arbitrate) 裁决专用；③过渡约定写进角色 prompt（判读等待时先看
HOST_RULING.md）。

### 写集粒度目录级→文件级（并发开票的结构性前提，260906 宿主挑战立案）
现状：write_set 按目录声明，所有票都含 integration/（场景=验收资产）→ 串行纪律保守过头
（目录重叠但文件不相交的票也被排成串行，宿主 260906「为什么不并发开票」直指）。
根治面：①写集支持文件级条目（目录=前缀语义保留）；②或 integration/ 按票子目录＋共享
清单点；③合并闸已有 merge-tree 预演+三轮自动消解当安全网——粒度细化后并发开票成为
默认，冲突轮盘退化为兜底。宿主裁定 260906 14:2X：「integration/ 不会冲突，都是各写各的。冲突了票也可以自己解决」——并发开票=默认（同刻五轨在飞实证），merge-tree 预演+三轮自动消解=兜底；文件级写集细化仍立项（记录精度与碰撞面可见性，非并发前提）。
