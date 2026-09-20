# t260913-01 验收走查报告（acceptance_walkthrough gen0，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通
签字处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 227 过 / 3 败 / 3 环境红，
闸拦 capture-chat-active、capture-chat-e2e、t260903-07-chat-project-tag）仅作输入，本段全部关键子用例
**自己重跑/自己复现**。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：不通过（status=failed）

- **唯一不通过项 = 验收 F（实票未解开）**：截至本段取证（260913 09:1x），t260911-05 仍
  `arbitrate/blocked`、t260912-01 仍 `design_integration_tests/blocked`，两票 `authorizations=0`、
  `refused=1`，且两票专属 worker 的 `sign_face` query **absent**（代码早于本票）。
  新 CLI（本票代码）对 t260911-05 发 authorize 已能**拒发并点名**（`worker 代码早于本票…已拒发未投递`），
  但钥匙仍未插进去。**这不是代码缺陷，是宿主动作没做**：需按
  `.sandbar/runbook_t260913_01_live_rollout.md` §2 逐票 SIGTERM 重启两票专属 worker，再执行 §3。
  工单原文「本票不算完成，直到两票至少一张实际被解开」→ 本段不能判 ok。
- **代码/场景面全绿**（独立复跑，非复用机械口径）：lint 0 error/0 warn；UT 722 passed；
  三场景真跑 `37/0`、`37/0`、`30/0`。
- 另附**两条轻微实现缺陷**（发现 2/3，非阻塞，随手可修）与**一处覆盖缺口**（观察项）。

| # | 项 | 结论 | 关键证据 |
|---|----|------|----------|
| A | 正用例·受保护路径（送达 + 消费） | 通过 | 落账字段全 + timeline 签发事件 + `landing=landed`；消费面 settle 回执真文本带 `path_gate_authz_used=宿主@1789261882:integration/baselines/sc_battery.py` 且 37/37 |
| B | 正用例·仲裁超限 | 通过 | 无授权仍 blocked → 授权接受判决 → 不阻断推进 `acceptance_walkthrough`，`uses≥1` + 判决原文 + 授权人（30/30） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 过期 / 别票 scope / agent 自签 / marker 载荷丢失 / 畸形裸 dict —— 全真信号投递、全部 refused 点名、全部不落账；「载荷解析失败」与「非人审等待中」机械可辨 |
| D | 真往返守卫 | 通过（合成口径） | 两子用例各自在册且真信号；「单场景跑通 A+B」的字面读法未满足 → 依 review C6 合成裁定（见下） |
| E | 零回归 | 通过 | base/workflows/inspection_flow 三 handler 源码零 diff；普通签字逐字节锁 + t260912-03 三套 103 UT 绿；三个在册 authz 场景在新三态回执下不翻红 |
| F | 实票验证 | **不通过** | 两票仍 blocked + `sign_face` absent（只读取证，见下） |

## 做了什么

1. **通读本票全部 8 个改动文件**（diff 逐行），核对写集边界、fail-closed 方向、既有语义保全。
2. **独立复跑**（不复用注入的机械结果）：`lint_tests.py`、全量 `server/engine/tests`、三条相关 L3 场景
  （新场景 + A 消费面 + B 子用例）。
3. **独立复现事故根因**（不采信方案自述）：用 temporalio `DefaultPayloadConverter` 直调，
  以「旧形 Signature（无 authorize 字段）」解码新载荷，验证未知字段是否静默丢弃、marker 标量是否存活。
4. **线上只读取证**：真 Temporal 7233 上只读 query 两票 `snapshot`/`sign_face`，并用本票新 CLI 对
  t260911-05 跑一次 op=authorize（face 前置检查在投递前拒发，零副作用、零信号投递）。
5. **对抗探针**：对新增的 `evaluate_authz_landing`（落账三态判定纯函数）构造两类边界输入，找误判/炸点。
6. **测试资产变更审查**：`git diff --numstat` 逐文件核对增删行，确认既有断言零改动。

## 怎么验证的（逐场景结论与证据）

### 独立复跑口径（全部本段亲跑，输出原文见 `.sandbar/evidence/verify_run.log`）

```
python3 integration/lint_tests.py                        → LINT done: 0 error / 0 warn, exit 0
server/engine/.venv/bin/python -m pytest server/engine/tests -q
    → 首轮 1 failed / 721 passed（test_t260901_25_t03_reap_process_group，单跑 1 passed，复跑 722 passed
      ⇒ KI-072「负载敏感的不稳定检查」同族假红，与本票 diff 无交集）
sc_authz_signal_delivery.py        → SC ... pass=37 fail=0 (exit=0)
sc_authz_protected_path.py         → SC ... pass=37 fail=0 (exit=0)
sc_authz_overlimit_accept.py       → SC ... pass=30 fail=0 (exit=0)
```

### A 正用例（受保护路径）

- **送达半边（新场景，真 CLI → 真 sign 信号 → 真专属 worker → 真 workflow）**：`authorizations 0→1`，
  尾条 `{"who":"宿主","kind":"protected_path","scope":["integration/baselines"],"reason":…,
  "expires":1789265469,"issued":1789261869,"uses":[]}` 六要素齐；`timeline state=authorized 0→1`；
  回执 `landing=landed` + `authorization` 记名块 ✅
- **消费半边（在册 `t260912-03-authz-protected-path`）**：本段真跑 37/37，settle 回执尾原文
  `…path_gate_authz_used=宿主@1789261882:integration/baselines/sc_battery.py；worker 代落盘 commit
  5e26a78（1 项：integration/baselines/sc_battery.py）`，场景断言的记名点名（授权人 / 被批路径 /
  签发时间 / 理由）全绿 ✅
- **观察项（覆盖缺口，非阻塞）**：机读键 `path_gate_authz_used=` 的**字面量本身没有断言锁**
  （全仓 grep：仅引擎侧生产/消费该键，integration 侧无断言）。键被静默改名时该场景不会翻红，
  只会掉到「记名点名」的宽断言上。建议下一轮 integration 迭代补一条断言（本票不改他人资产）。

### B 正用例（仲裁超限）

在册 `t260912-03-authz-overlimit-accept` 本段真跑 30/30：B① 无授权超限 → 仍 `blocked`（含「超限」）；
B③ 过期授权 → 回执 `ok`+`landing=refused`+`refused_why="expires 已过期(…)"`、不落账、不推进；
B② 生效授权（`arbitration_verdict` scope=本票票号）→ `retry_qc` 唤醒后**不阻断**，推进到
`acceptance_walkthrough` 或更后，handoff 含「经人授权接受判决」+ 判决原文关键词 + `verdict=tests-fault`
+ 授权人「宿主」，该授权 `uses≥1` ✅

### C 负锁（验收要求 4 条，本票覆盖 5 条，全部真信号投递）

| 负锁 | 投递形态 | 票面 | 落账 |
|---|---|---|---|
| ① 过期授权 | 真 CLI op=authorize（expires=now−10） | `refused want=sign(authorize) why="expires 已过期…死授权不进历史"`，回执 `landing=refused` | 不落账 ✅ |
| ② `arbitration_verdict` scope=别票 | 真 CLI | `why="arbitration_verdict 的 scope 必须恰为本票票号 't26091301a-authz-d'…"` | 不落账 ✅ |
| ③ who=agent 角色名（自签） | 真 CLI（who=developer） | `why="agent 不得自签（who='developer' 是 agent 角色名；授权只能人签发）"` | 不落账 ✅ |
| ④ 载荷解析失败（事故等价形态） | 直发 SDK：`gate=marker` 而 authorize 缺失 | `want=sign(authorize) why="authorize 载荷解析失败：gate 标记在场但载荷为空（传输/反序列化一跳丢失…）；不按普通签字处理"` | 不落账 ✅ |
| ⑤ 畸形载荷 | 直发 SDK：裸 dict 缺字段 | `want=sign(authorize)`、why 非空、非「非人审等待中」 | 不落账 ✅ |

相位④是「可辨文案」的机械锁：断言同时要求 `"载荷解析失败" in why` **且** `"非人审等待中" not in why`
——静默回落普通签字的旧形态（`want="sign()"`）不可能满足。全程恰 1 条生效授权 + 1 条签发事件，
审计账本 0 条，拆台 `residue=[]` ✅

### D 真往返守卫

- 两子用例都是**真信号投递**（真 CLI / 真 SDK → 真 Temporal → 真 worker → 真 workflow），无一条以直调纯函数代替；
  两子用例都已在 `integration/run_scenarios.py` 在册、按登记制命名（`t260913-01-authz-signal-delivery` 登记于
  engine 池，本段在册条目在场核对通过，lint L4 清单 233 条三元组完整）。
- **偏离（如实标注）**：验收 D 字面「至少一条集成场景跑通 A 与 B」未满足——A 子用例在新场景、B 子用例在在册
  `t260912-03-authz-overlimit-accept`，是**合成口径**（review_plan C6 裁定：两子用例均有真信号在册场景即满足
  D 的意图＝「不得用直调纯函数冒充真往返」）。本段不为凑字面扩场景（会造 intent 级重复）；若人审要字面读法，
  应回流并票，再单开一条「A+B 同场景」用例。

### E 零回归

- `git diff --numstat 9c102d7..HEAD`：`server/engine/base.py` / `workflows.py` / `inspection_flow.py`
  **零改动**（对 authorize 载荷的显式拒收语义 = t260912-03 原样）；`dev_lane.py` 26+/1−（1− 是 docstring
  行改写）、`shared.py` 25+/0−、`worker.py` 47+/0−，普通签字路径全部在 diff 的上下文行里。
- 新增 L1：`test_marker_gate_without_authorize_is_named_parse_failure`、`test_plain_sign_at_merge_gate_unchanged`、
  `test_plain_sign_refusal_wording_unchanged`、`test_empty_gate_plain_sign_refusal_wording_unchanged`
  （逐字节锁 `{"want":"sign()","why":"当前步 arbitrate 非人审等待中，签字无效"}`——即 260913 生产复现的原始形态）。
- t260912-03 三套 103 UT 全绿；三个在册 authz 场景在新三态回执（新增 `landing`/`refused_why`、保留
  `ok:true`+`delivered`）下**不翻红**，本段亲跑复证（R2b）。

### F 实票验证 —— 不通过（本段唯一打回项）

线上只读取证（真 Temporal 7233，query 无副作用；未触碰 console 3099、未重启任何进程、未进任何别票泳道）：

```
t260911-05 status=RUNNING sign_face=WorkflowQueryFailedError: expected but not found
           stage=arbitrate/blocked              authorizations=0 refused=1
t260912-01 status=RUNNING sign_face=WorkflowQueryFailedError: expected but not found
           stage=design_integration_tests/blocked authorizations=0 refused=1
t260911-06 / t260913-01  同样 sign_face absent（同批陈旧 worker）
本票新 CLI：op=authorize id=t260911-05 → exit 1
  {"ok": false, "error": "ValueError: Temporal 拒绝: worker 代码早于本票（sign_face query 不存在）
   ——旧 Signature 类解码时会静默丢弃 authorize 载荷，已拒发未投递。处置：重启该票专属 worker…"}
```

→ 新链路在**真实事故票**上表现正确（拒发 + 点名 + 零副作用），但**两票都还没被解开**。
达标需要宿主执行（agent 无权限、也不该做）：S6 逐票 `kill -TERM $(cat data/worker-<票号>.pid)`
（console keepalive 重生新代码 worker）→ 判据 `sign_face` 由 absent 变 match → §3 两票授权推进命令。
runbook 已在 `.sandbar/runbook_t260913_01_live_rollout.md`，本段已把 S0 直证替他做掉（两票 absent 已证）。

## 发现（本段对抗探针，均纯函数复现，零副作用）

### 发现 1（阻塞级，非代码）：验收 F 未闭环 —— 见上「F」节。归因=宿主动作未执行；不归 developer。

### 发现 2（轻微，precision）：同秒重复签发同一授权 → 回执假报 `unconfirmed`（误导诊断方向）

- 复现（纯函数，`server/engine/client.py` `evaluate_authz_landing`）：
  ```python
  rec = {"kind":"protected_path","who":"宿主","scope":["integration/baselines"],
         "reason":"r","issued":1000,"expires":2000,"uses":[]}
  client.evaluate_authz_landing([rec], [], {"meta":{"authorizations":[rec, dict(rec)]}},
                                "宿主","protected_path",2000)
  # → ('pending', '')   ← 授权其实已落账（meta 里两条），却判 pending
  ```
- 根因：`authorization_record` 的 `issued` 是 `workflow.now()` **秒**粒度；intake 是 `append` 不去重。
  同一秒内重发**同样 who/kind/expires** 的授权 → 新条目 `(who,kind,expires,issued)` 键与基线完全同形 →
  落账判定认不出「新条目」→ CLI 走 `_err(KIND_AUTHZ_LANDING_UNCONFIRMED)`，文案把用户指向
  「核 worker 血统 / 重启 worker」——**方向错**（票面其实已生效）。方向仍是 fail-closed（不假报成功），
  故非阻塞；建议 `_authz_key` 增 `scope/reason` 或改用条数+内容双判，文案加「可能为重复签发」分支。
- 影响面：只在本票新增的回执判定上，不动引擎语义。

### 发现 3（轻微，健壮性）：畸形**值**（非数值 expires/issued）会抛异常，与函数自述「一律降级不炸」不符

- 复现（纯函数）：`evaluate_authz_landing([{"who":"宿主","kind":"protected_path","expires":"abc",
  "issued":1}], [], {"meta":{"authorizations":[…]}}, "宿主","protected_path",2000)`
  → `ValueError: invalid literal for int() with base 10: 'abc'`（`_authz_key`/`evaluate_authz_landing`
  的 `int()` 转换未包异常）。`_authz_entries` 的 docstring 声明「任何畸形…不炸、不误判」，实测只覆盖
  **结构**畸形（非 dict/非 list），不覆盖**值**畸形。
- 可达性：`meta.authorizations` 由引擎写入，正常恒为整数 → 现实低概率；但它是本段新引入的读面，
  且 `client.py` 的崩点会以裸异常出到用户面（KI-067 家族形态）。建议 `_authz_int` 式容错读。

## 测试资产变更审查（对照 implement 段，逐处核实意图）

**结论：既有测试资产零改动，无绿灯捷径；新增资产的断言行审读为契约锚定。**

- 本票改动 8 文件全在写集 `{server/engine/, server/tools/ticket.py, integration/}` 内；
  `server/tools/ticket.py` 零改动（实现走的是 `client.py` op 面，ticket.py 只透传）。
- `git diff --numstat`：**无任何既有测试文件被修改**（改动 = 4 个引擎文件 + 2 个新 UT + 1 个新场景 +
  `run_scenarios.py` +6/−1，那 1 行是空行移位——**在册场景条目的 intent 文案与命令逐字节未动**）。
- 新增断言审读（三个文件逐行过）：A 子用例锁「字段六要素 + timeline 事件 + 回执 landing」；
  负锁锁「want=sign(authorize) + why 点名要素 + 不落账」；marker 子用例锁「与『非人审等待中』可辨」；
  L1 锁「普通签字文案逐字节」。无恒真断言、无 `assert True`、无把断言面让给实现细节（拒收文案只锁点名要素，
  不锁整句）。**事故形态（静默回落 → `want="sign()"`）在负锁④会被判红**，即防回归网真的能兜住本票事故。
- **唯一轻微宽松（建议收紧，非阻塞）**：新场景负锁② 的谓词是
  `OTHER_TID in why or "票号" in why or "scope" in why` 三选一 OR。实测文案插值的是**本票票号**
  （「必须恰为本票票号 't26091301a-authz-d'」），故走「票号」支命中；OR 的另两支偏宽，
  建议收紧为「本票票号 + 『必须恰为本票票号』」双要素。
- 运行史（design 段自述）两轮自伤修正（`len()` 误用于计数、谓词假红）已核对：修的是**场景自身 bug**，
  断言逻辑方向未放宽；本段独立复跑与 design 段结论一致（37/0）。

## 并行期 UI 呈现

**不适用。** 本票写集与 diff 均无 UI/泳道渲染文件（8 文件 = server/engine 4 + integration 4；
零 `src/client`、零 workbench、零 capture/视图资产），无 UI 回归面，故不取隔离台截图/DOM 证据
（无改动的面不产 UI 证据）。机械口径里 3 红 + 3 环境红全部是 chat/UI 场景
（`capture-chat-active`、`capture-chat-e2e`、`t260903-07-chat-project-tag`：chip 探得=[]/
reload 未恢复会话），与本票写集**零交集**，且闸自报 `归属置信=unknown(baseline_unavailable)`
→ 本段判定「与本票无关」，但不宣称「预存即有」（基线不可得，无法机械证明其先红）。

## 遗留与风险

1. **F 是本票唯一硬缺口**：宿主执行 runbook 后，本票才算完成；在此之前应保持 blocked。
   执行后需回填的证据：两票 `sign_face` 由 absent→match、`landing=landed` 回执、t260911-05 推进
   `acceptance_walkthrough` 且 `uses≥1`（或 t260912-01 settle 放行带 `path_gate_authz_used`）。
2. 发现 2/3 两条轻微实现缺陷（可随打回轮顺手修，不构成独立打回项）。
3. 覆盖缺口：`path_gate_authz_used=` 机读键无断言锁（A 消费面）。
4. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement 三条
   （①逐票常驻 worker 陈旧=全信号面结构性风险；②signal 载荷演进纪律成文；③毒载荷宽松解码）+
   本段建议第 4 条（「回执机读键无断言锁」类覆盖缺口，可与 ① 合登）。
5. face 指纹是**严格相等**判定：日后给 `Signature`/`HumanAuthorization` 加任何字段，未重启的在途
   worker 一律被拒发（fail-closed，但运维面=「加字段必重启全票 worker」）——建议随 KI 候选②成文。
6. 环境侧：本机 `~/.sandbar` 不可写，stage 锁根降级 `/var/folders/...`（stage_docker 自明示，
   不影响判定）；docker 台残留多个他票 stage 容器（stage-sweep 判「仅报告不拆」），不属本票面。
