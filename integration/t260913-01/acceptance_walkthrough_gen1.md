# t260913-01 验收走查报告（acceptance_walkthrough gen1，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通
签字处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 226 过 / 4 败 / 3 环境红）
仅作输入，本段关键子用例**自己重跑/自己复现**。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

上一轮（gen0）唯一打回项 **F 已闭合**：两张目标实票都已按各自授权**真实推进**（生产实证，见下 F 节）。
验收 A–E 在本轮代码树（gen0 引擎实现 + gen1 测试资产修正）上独立复跑全绿。
本轮重点审查的 gen1 三处 `integration/baselines/*` 改动，逐处核实为**契约精确化**（三态归属订正），
无断言语义放宽、无把红改判绿，附独立复现证据。另留两条**轻微、非阻塞**的实现观察与一条残差面（见遗留）。

| # | 项 | 结论 | 关键证据 |
|---|----|------|----------|
| A | 正用例·受保护路径（送达 + 消费） | 通过 | 送达：落账六要素 + timeline 签发事件 + 回执 `landing=landed`（37/0）；消费：settle 回执带 `path_gate_authz_used=宿主@1789261882:integration/baselines/sc_battery.py`（37/0） |
| B | 正用例·仲裁超限 | 通过 | 无授权仍 blocked → 授权接受判决 → 不阻断推进 `acceptance_walkthrough`，`uses≥1` + 判决原文 + 授权人（30/0） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 过期 / 别票 scope / agent 自签 / marker 载荷丢失 / 畸形裸 dict，全真信号投递、全部 refused 点名、全部不落账；「载荷解析失败」与「非人审等待中」机械可辨 |
| D | 真往返守卫 | 通过（合成口径） | 两子用例各自在册且真信号（A=新场景、B=在册 overlimit）；「单场景跑通 A+B」字面读法未满足，依 review C6 合成裁定 |
| E | 零回归 | 通过 | 三个其它 handler 源码零 diff；普通签字逐字节锁 + t260912-03 三套 103 UT 绿；三个在册 authz 场景在新三态回执下不翻红 |
| F | 实票验证 | **通过** | t260911-05：arbitrate 超限 blocked → 推进到 `merge_check`；t260912-01：受保护路径拒绝 blocked → 推进到 `run_integration_tests/running`；两票 `uses≥1` |
| — | gen1 测试资产变更审查 | 通过（1 条残差面已标注） | 3 文件逐行 diff + 三态语义复现 + README/失败分类协议对照，见专节 |

## 做了什么

1. 复核 gen1 提交（`e4a5e2f`，4 文件）与整票累计 diff（`9c102d7..HEAD`）：引擎五文件本轮零改动，
   gen1 全部落在 `integration/baselines/` 三个共享文件（=宿主授权 scope 点名面）。
2. **独立复跑**本票全部验收子用例（lint / 全量 UT / 三条 L3 场景），不复用注入的机械结果。
3. **逐行审查 gen1 三处测试资产改动**并按 `docs/design/失败分类协议v1.md` + `integration/README.md`
   对照其「三态归属」主张，另跑三条针对性复现（工具链解析真跑、env_fail 通道真跑、e2e 顶层真跑）。
4. **线上只读取证 F**：真 Temporal 7233 上读两票 snapshot，取授权消费留痕（`uses`）与时间线，
   确认两票确实离开了各自 blocked 并被推进。
5. 核对本轮机械口径的 4 个 blocker 与本票的**写集/依赖交集**（结论：零交集，详见专节）。

## 怎么验证的（逐场景结论与证据）

### 独立复跑（本段亲跑，原文见 `.sandbar/evidence/verify_gen1.log`）

```
python3 integration/lint_tests.py                    → LINT done: 0 error / 0 warn, exit 0
server/engine/.venv/bin/python -m pytest server/engine/tests -q → 722 passed in 30.42s
sc_authz_signal_delivery.py    → pass=37 fail=0 exit=0   （A 子用例送达 + 5 负锁 + 收口）
sc_authz_protected_path.py     → pass=37 fail=0 exit=0   （A 子用例消费：settle 放行 + 记名点名 + 普通签字零回归）
sc_authz_overlimit_accept.py   → pass=30 fail=0 exit=0   （B 子用例全链：授权接受判决 → 推进 → uses≥1）
```

### F 实票验证（本轮闭合项，生产只读取证）

| 票 | 走查前（gen0 取证） | 走查后（本轮 12:17 取证） | 授权消费留痕（`uses`） |
|----|---------------------|---------------------------|------------------------|
| t260911-05 | `arbitrate/blocked`、`az=0`、refused=`sign()` | **`merge_check/blocked`**（新红是另一回事：泳道内 verify_lane 红 + 越界写 `.sandbox_tmp_gen9.md`） | `{"detail":"接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough","stage":"arbitrate"}` |
| t260912-01 | `design_integration_tests/blocked`、`az=0` | **`run_integration_tests/running`** | `{"detail":"受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,sc_ticket_evidence_images.mjs,sc_ticket_session_restore.mjs","stage":"integ_join"}` |

两票时间线还留下**事故根因的生产实证**：03:19 首批授权（issued 后紧跟 `retry-requested`）**未被消费**
（`uses` 空、票仍 blocked）；03:20:56 宿主**重启该票专属 worker 后重签**（授权 reason 原文含
「工人重启后重签」）→ 03:21 重跑 → 授权被消费、票推进。同一 CLI、同一载荷形状，唯一变量=worker 进程
代码 → 「陈旧 worker 解码时静默丢弃 authorize 字段」这条根因在生产上被独立坐实，与方案 R5（重启生效）
一致。**F 判据（两票至少一张实际被解开）由两票同时满足。**

诚实边界：线上 worker 跑的是 main（`9c102d7`）代码，**不含本票的 `sign_face`/marker 防线**（防线只在
本 worktree）——所以线上这次证明的是「根因+重启疗法+授权消费通路（t260912-03 面）成立」，本票新增的
防线代码则由 docker 台场景证明（A/C 子用例）。两半合起来才是完整闭环，本报告分开标注、不混。

### A/B/C/D/E（本轮复跑，与 gen0 结论一致）

- **A 送达半边**：新场景真 CLI → 真 sign 信号 → 真专属 worker → 真 workflow：`authorizations 0→1`，
  尾条 who/kind/scope/reason/expires/issued/uses 六要素齐，`timeline state=authorized 0→1`，
  回执 `landing=landed` + `authorization` 记名块。**消费半边**：在册 protected-path 场景真跑 37/37，
  settle 回执真文本 `…path_gate_authz_used=宿主@1789261882:integration/baselines/sc_battery.py；worker
  代落盘 commit 5e26a78`，记名点名（授权人/路径/签发时间/理由）断言全绿。
- **B 子用例**：无授权超限仍 blocked → 生效授权（`arbitration_verdict`，scope=本票票号）→ `retry_qc` →
  不阻断、推进 `acceptance_walkthrough` 或更后，handoff 含判决原文 + `verdict=tests-fault` + 授权人，`uses≥1`。
- **C 负锁**：五条全真信号投递，均 `want=sign(authorize)` + why 点名 + 不落账；相位④（marker 在场而
  载荷缺失）同时断言 `"载荷解析失败" in why` **且** `"非人审等待中" not in why` ——旧事故形态
  （静默回落 `want="sign()"`）不可能满足该断言。全程恰 1 条生效授权 + 1 条签发事件，审计账本 0 条，
  拆台 `residue=[]`。
- **E 零回归**：`server/engine/base.py` / `workflows.py` / `inspection_flow.py` 源码零 diff（对 authorize
  载荷的显式拒收语义 = t260912-03 原样）；普通签字路径在 diff 里全是上下文行，且被 L1 逐字节锁
  （含 260913 生产复现的原始形态 `{"want":"sign()","why":"当前步 arbitrate 非人审等待中，签字无效"}`）；
  t260912-03 三套 UT 103 条全绿；三个在册 authz 场景在新回执（新增 `landing`/`refused_why`、保留
  `ok:true`+`delivered`）下不翻红。
- **D**：两子用例均真信号、均在册（`run_scenarios.py` 登记，lint L4 清单三元组完整），无一条以直调纯函数
  代替。**偏离如实标注**：验收 D 字面「至少一条集成场景跑通 A 与 B」未满足，由 review_plan C6 裁定的
  合成口径承担（A=新场景、B=在册 overlimit）。若人审取字面读法，应回流并票另开「A+B 同场景」用例，
  本段不扩场景（避免 intent 级重复）。

## 测试资产变更审查（本轮重点）

### 变更清单（`git diff efbcf9e..e4a5e2f`，4 文件）

| 文件 | 改动 | 意图判定 |
|---|---|---|
| `integration/baselines/capture-ensure-build.mjs` | 新增 `resolveTsdown(laneRoot)`：候选=**被测树优先**、主检出（git-common-dir 推导）回落；`ensureLaneBuild` 改用之；两处都无才 fail loud | **契约精确化（真缺陷修复）** |
| `integration/baselines/sc_capture_chat_active.mjs` | C1 的 `buildErr` 分支：`fail` → `env_fail`（文案点名「前提未满足（not-checked）」） | **三态归属订正** |
| `integration/baselines/sc_capture_chat_e2e.mjs` | 新增 `envRefused = !run.timedOut && run.code === 2`；A1–A8 改经 `recordLeg` 落状态；env_fail 时 detail 带内层 stderr 尾 3 行 | **三态归属订正** |

### 逐处核实（用户视角 + 协议对照，不采信自述）

1. **断言语义零改动**：diff 逐行核过——e2e 的 A1–A8 **判定表达式**（`run.code===0?pass:fail`、
   `missing.length===0 && tiny.length===0`、哈希不等、锚出现、`健全性断言绿`、无裸 TypeError、拆台拒连…）
   逐字节未动，只有「记录函数」换成 `recordLeg`；active 只改 `buildErr` 一个分支，其下 `fullChain()`
   的断言链一行未改。**没有任何期望值被放宽或删除。**
2. **不是把红改判绿**：`env_fail` 在这两条基线里 → `process.exit(2)`（本段真跑复现：
   `SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL=1` → `SUMMARY pass=14 fail=0 env_fail=1`，
   `EXIT=2`）。三态协议里 ENV_FAIL=not-checked≠pass；机械口径的 exit 2 仍进「环境红」计数，
   不冒充已跑绿。
3. **协议依据属实**（引文亲核，非转述）：`integration/README.md` 明写这两条基线「泳道机械跑环境天然
   不满足，故**一律 ENV_FAIL（exit 2，不再 exit 0 假绿）**」；`docs/design/失败分类协议v1.md` 明写
   `fail × prepare 型 reason`（self_precheck/connect_refused/lock_busy/missing_asset）= **协议违约**，
   且 ENV_FAIL 必须带 reason+evidence（新文案确实点名缺什么/带内层 stderr 证据）。
4. **①的工具链解析真跑复现**（本段亲跑）：
   `resolveTsdown(本泳道)` → `<lane>/server/plugins/workbench/node_modules/.bin/tsdown`（被测树优先命中；
   主检出该路径在本机确实不存在=旧实现必 null 的同一环境）；`resolveTsdown(空目录)` → `null`
   （两处都无仍 fail loud，不静默放过旧 bundle）。
5. **e2e 顶层真跑复现**（本段亲跑，剥离泳道 worker 变量）：**A1–A8 全 PASS，`SUMMARY pass=8 fail=0`，
   exit 0**（含真模型种子消息上屏、7 视图齐且非空白、chat≠default 字节级不同、拆台后端口拒连）。
   说明判定链在真跑下完好，改动只影响「前提无法满足」这一态。
6. **授权与写集**：三文件属 `integration/baselines`，宿主 `protected_path` 授权在场且已消费（本票自身
   `meta.authorizations[0].uses` = `受保护路径豁免：capture-ensure-build.mjs,sc_capture_chat_active.mjs,
   sc_capture_chat_e2e.mjs`）——**不是夹带越界写**。
7. **依赖面（爆炸半径）**：全仓 grep，`capture-ensure-build.mjs` 只被 `sc_capture_chat_active.mjs` 与
   `sc_capture_chat_e2e.mjs` 引用（+注册表条目）；其余任何场景/代码都不消费它 → 改动影响面=这两条基线本身。

### 审查结论

三处改动**无绿灯捷径、无断言弱化**，属仲裁 tests-fault 裁定下的正当测试面修复（`verdict=tests-fault`，
见 `.sandbar/stage_arbitrate_gen0.json`）。**一条残差面如实标注**（见遗留 3）：真实字节漂移
（源码改了未重建 bundle）这一失败形态被一并收进 not-checked —— 本段判为可接受（该面属「捕获证据前提」
而非产品断言，内层 capture-lane 本来也以拒跑 exit 2 表达），但若项目要把「提交的 bundle 与源码不一致」
当产品红，应另加显式断言，而不是依赖 prepare 分支。
另有一处**报告精确性问题**（非代码问题）：implement gen1 结果文件称 e2e 红是「A8/A6 FAIL（内层真跑
exit 1）」，与仲裁台账（内层 exit 2、A1 红、A2–A8 下游）不一致；本段实测的顶层真跑为 8/8 绿，
两说均无法从现有证据复现，属对已消失红态的**回溯描述不精确**——建议后续报告以机械原文为据。

## 机械口径归因（本轮 4 败 / 3 环境红）

闸拦：`t260911-02-doc-face`、`ticket-session-restore`、`t260912-02-sweep-owner-gone`、
`t260912-02-net-table-contract`；闸自报 `归属置信=unknown(baseline_unavailable)`，基线=b614392。

- **与本票写集/依赖零交集**：本票改动=引擎 authz 四文件 + 三条 capture 基线；`t260911-02-doc-face`
  与 `ticket-session-restore` 的 grep 对 `authz/authorize/sign_face/client.py/dev_lane` 命中数=**0**；
  `capture-ensure-build.mjs` 的引用者只有两条 capture 基线。四个 blocker 分属别票面（t260911-02 的
  docs-sync 实例、t260912-02 的残台清扫/网段契约、既有 session 基线）。
- 两条 t260912-02 红是**起台失败**（`挂点子用例新台 up 成功（rc=2）`／`A 台起台 rc=0`）→ 属环境/端口
  争抢类（与 KI-072 负载敏感、供给台跨泳道争抢同族）。
- `ticket-session-restore` 的一条**线索**（不构成结论）：并行票 **t260912-01 的授权 uses 明细恰好点名
  `integration/baselines/sc_ticket_session_restore.mjs`**，其授权 reason=「本票要修八处界面场景的路径
  探测（统一到 git-common-dir 口径）」——该红很可能就是 t260912-01 正在修的那条，属其面而非本票面；
  最终归属需基线或该票自身验证，本段不替闸裁。
- 本票在册四条场景（新场景 + t260912-03 三条）机械口径全部 exit 0，与本段独立复跑一致。

## 并行期 UI 呈现

**不适用**（同 gen0 判定，并补一句边界说明）：本票写集无 UI/泳道渲染代码（gen0 引擎四文件 + gen1 的
三条 `integration/baselines/*` 属**UI 证据捕获链的前提/归属**，不是 UI 渲染面），故不取隔离台截图/DOM
断言证据；「并行分叉期步骤条双边同亮」属工单台 UI 面，不在本票改动面。本轮 UI 证据链本身已由
e2e 顶层真跑 8/8 绿间接复证（该链无回归）。

## 遗留与风险

1. **合并面（需人审/merge 执行人注意）**：main 已前进到 `b614392`（t260913-03 声明落 main），本
   worktree 基于 `9c102d7` → 合并需先对齐 main。另外 t260913-03 声明 `exclude_pools: engine,exclusive`
   使**每票集测段跳过 engine 池**，而本票新增的 L3 守卫场景（`t260913-01-authz-signal-delivery`）与
   t260912-03 三条正用例都在 engine 池 → **只由每天一次的集成测试巡检覆盖**，不进每票段。本票写集恰恰
   命中 `server/engine/`（被跳池场景的真实被测面），是否应把引擎源码纳入 `exclude_pools_force_assets`
   的强制面，建议人审顺带裁定（本段只报观察，不改别票声明）。
2. **合并冲突风险（实证线索）**：并行票 t260912-01 获授权修改 `integration/baselines/
   sc_capture_chat_active.mjs`（其 uses 明细为证），与本票 gen1 改的是**同一文件**；两票对同一文件的
   语义叠加（路径探测口径 vs C1 三态归属）需在合并时人工确认，避免互相覆盖。
3. **残差面（本段接受，建议另开断言）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进
   not-checked；若要保留这条产品信号，应显式断言「committed bundle == 源码重建产物」，而不是靠
   prepare 分支的归属。
4. **gen0 两条轻微实现观察仍开放**（gen1 未碰引擎，故原样在）：①**同秒重复签发**同一授权 →
   `evaluate_authz_landing` 认不出新条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，
   fail-closed 不假报成功）；②**畸形值**（非数值 expires/issued）在 `_authz_key/int()` 处抛 `ValueError`，
   与其 docstring「任何畸形…不炸」不符（结构畸形已容错、值畸形未容错）。两条均可随手修，不构成
   本轮打回项；建议随 KI 候选登记。
5. **覆盖缺口（沿用 gen0）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑
   可见）——键被改名不会翻红，建议下一轮 integration 迭代补断言。
6. **运维面（本票设计的固有含义，需人审知晓）**：合并后 CLI 对**任何未含 `sign_face` 的 worker**
   拒发 authorize（fail-closed）——现网两票 worker 是重启到 main `9c102d7` 的（无本票防线），
   合并后需按 `.sandbox`/`.sandbar/runbook_t260913_01_live_rollout.md` §S0→§S6 再重启一次才能继续
   用人授权；这是设计取向（不许盲投旧 worker）而非缺陷。
7. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条（①逐票常驻 worker
   陈旧=全信号面结构性风险；②signal 载荷演进纪律成文；③毒载荷宽松解码）+ 本报告新增两条
   （④回执机读键无断言锁类覆盖缺口；⑤上表第 4 条两条轻微实现缺陷，可与 ③ 合登）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。本票留下值得进 docs/ 的引擎机制事实（worker 内存代码可
  早于磁盘代码 + temporalio 未知字段静默丢弃 + 「marker 可见化 / sign_face 指纹先验 / 三态回执」三步
  纪律 + 加字段必重启的运维含义），而 docs/ 现无任何承载（全库 grep 无 authorize/人授权/信号载荷纪律
  条目）。建议 target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  `docs/` 不在本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、`docs/testing-guide.md`、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/design/失败分类协议v1.md`（三态语义）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现（普通签字零改动、授权通道为
  新增例外面、fail-closed 不放宽、prepare 型原因归 not-checked）与上述成文主张一致，未发现被推翻的
  claim，故不产生债条目。
