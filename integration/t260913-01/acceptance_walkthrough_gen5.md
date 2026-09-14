# t260913-01 验收走查报告（acceptance_walkthrough gen5，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 213 过 / 1 败 / 19 环境红）
仅作输入，关键腿自己重跑。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **本轮改动 = 三处测试资产处置**（implement gen2，提交 `49c50be`）：①`integration/t260912-02/lib_lifecycle_case.py`
  **纯新增** 32 行（`up_ok` / `up_batch_env_only` / 档位常量）；②`integration/t260912-02/sc_stage_net_table_contract.py`
  A/B 起台两行改用 `up_ok` + import 一行；③**越界预置改动已按红线回滚**（`sc_stage_sweep_owner_gone.py`
  与本段核实与 HEAD 逐字节无差异、工作区干净）。另含我上轮报告。
- **A–F 全部满足**：机械口径本票四条在册场景**全 PASS**（15.4s / 93.0s / 15.4s / 5.3s）；本段亲跑
  lint 0/0、新场景 `pass=37 fail=0`、UT 722 passed；F 两票 `used=1` 仍成立。
- **本轮测试资产改动审计通过**（重点小节）：档位判据**读源亲核**与引擎自报退出码一致，
  且 `rc=1/64` 仍判 FAIL（**不可能掩盖产品红**）；断言语义零改动；独立复跑绿。
- **闸唯一 FAIL（`t260912-02-burst-managed-subnets`）与本票零交集**：别票场景、前四轮均 PASS、
  本轮 99 腿中 6 腿红且在 18 条 console 环境红 + 端口占用的高载窗口内 → 归因属仲裁。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正腿·受保护路径（送达+消费） | 通过 | `t260913-01-authz-signal-delivery` PASS 15.4s；`t260912-03-authz-protected-path` PASS 5.3s |
| B | 正腿·仲裁超限 | 通过 | `t260912-03-authz-overlimit-accept` PASS 93.0s（判决原文 + `uses≥1` + 推进） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本段亲跑新场景 `pass=37 fail=0`（含可辨文案断言）；机械口径 PASS |
| D | 真往返守卫 | 通过（合成口径） | 两腿真信号、均在册（字面读法偏离沿用 review C6 裁定） |
| E | 零回归 | 通过 | 引擎三 handler 源码零 diff；本段亲跑 UT 722 passed；`-authz-cli-queryable` PASS 15.4s |
| F | 实票验证 | 通过 | 20:23 只读取证：两票各 `used=1`；t260912-01 `run_integration_tests/running`，t260911-05 已远离 `arbitrate/blocked` |
| — | 测试资产变更审查 | 通过（含 1 条全族线索） | 见专节 |

## 做了什么

1. 核对本轮改动面：`git diff --numstat e7009d3 HEAD` → lib（+32）／net_table 场景（+3−2）／我上轮报告；
   另**独立核实越界回滚**：`git diff --stat -- integration/t260912-02/sc_stage_sweep_owner_gone.py`
   为空、`git status integration/ server/` 干净。
2. **档位判据读源亲核**（不采信注释）：`integration/stage_docker.py:275`
   `EXIT_OK, EXIT_ENV, EXIT_CONFLICT, EXIT_FAIL, EXIT_USAGE = 0, 2, 3, 1, 64`；`do_up` 的
   `docker compose up 失败` 分支 `raise StageError(..., kind="env")`（1909/1926 行）→ `StageError`
   经 285-286 行 `{"env":2,"conflict":3,"usage":64,"fail":1}` 映射为进程退出码。判据成立。
3. 读逐行 diff 核断言面：net_table 场景**只有 A/B 起台两行**替换（+import 一行），其余断言
   （256 槽/表内/互异/幂等 reused/还槽/渲染/usage 拒收）逐字未动；lib 为纯新增，既有函数零改动。
4. 本段亲跑：lint、本票新场景、**本轮被修的别票场景（net-table）独立复跑**、`up_ok` 五档确定性 smoke、
   引擎全量 UT。
5. 线上 F 只读取证 + 全族（同形态起台腿）静态排查。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen5_checks.log`）

```
python3 integration/lint_tests.py                                  → 0 error / 0 warn (exit 0)
sc_authz_signal_delivery.py                                        → pass=37 fail=0 (exit 0)
python3 integration/t260912-02/sc_stage_net_table_contract.py      → SUMMARY pass=19 fail=0 env_fail=0 na=0 (exit 0)
   （含 ok A 台起台 rc=0 / ok B 台起台 rc=0 / 幂等 reused / 网段归还 / 畸形底座 usage 档拒收）
up_ok 档位 smoke（假 proc，零 docker）：rc=0→PASS；rc=2→ENV_FAIL(env 档)；rc=3→ENV_FAIL(conflict 档)；
   rc=1→FAIL(产品/契约面)；rc=64→FAIL(产品/契约面)
up_batch_env_only：{2,3}→True；{2,1}→False；{}→False
pytest server/engine/tests -q                                      → 722 passed in 30.49s
```

### 测试资产变更审查（本轮重点）

| 检查点 | 结论 | 证据 |
|---|---|---|
| 档位判据是否与引擎自报一致 | **一致** | `stage_docker.py:275` 常量 + `do_up` compose-up 失败 `kind="env"`（1909/1926）+ 285-286 kind→exit 映射 |
| 是否可能掩盖产品红 | **不会** | `up_ok` 仅把 rc∈{2,3} 归 ENV_FAIL；`rc=1/64` 仍 `check(False,...)` 判 FAIL（smoke 实证） |
| 断言语义是否被放宽 | **未放宽** | net_table：仅 A/B 起台两行 + import；其余断言逐字未动（diff 逐行核）。lib：纯新增，既有函数零改动 |
| ENV_FAIL 是否带 reason+evidence | **是** | 文案点名档位（env/conflict）+ 进程输出末 220 字（符合失败分类协议「not-checked 必须带 reason+evidence」） |
| 越界预置改动是否已回滚 | **是** | `sc_stage_sweep_owner_gone.py` 与 HEAD 零差异、工作区干净（本段独立核） |
| 授权面 | 无闸依赖，但 scope 命名偏窄 | 活授权 `protected_path scope=["integration/t260912-02/lib_lifecycle_case.py"]`（3 天期，`uses=[]`）；`integration/t260912-02/` **不在** `path_gates.PROTECTED_PATHS`（仅 `integration/baselines`、`verify.yaml`、`server/*.yaml|roles`、`docs/design`、`path_gates.py` 自身）→ 第二处改动无保护路径闸依赖；两处改动 ⊆ 派单授权面。建议合并记录点名 |
| 修后真实效果 | **见效** | 机械口径 `t260912-02-net-table-contract` 由 FAIL 转 **PASS 16.1s**；本段独立复跑 19/0 绿 |

**总判定：契约精确化（prepare 型起台失败的三态归属订正），非绿灯捷径。** 与 t260910-13 决策表
「`fail × prepare 型 reason` = 协议违约（闸改判 not-checked + violation）」同向，且比 stderr 特征匹配
（既有 `env_guard`）更可靠——判据是引擎**自报退出码档位**，不猜文本。

### 全族线索（本段静态排查，实报即全族）

同形态「起台腿直接 `check(rc == 0)`」仍有在册未修点（本票授权面未覆盖）：

- `integration/t260912-02/sc_stage_sweep_owner_gone.py:240` —— `check(proc_n.returncode == 0, "挂点腿新台 up 成功（rc=%s）")`；
  **历史实录**：本轮之前的机械跑曾出现 `FAIL 挂点腿新台 up 成功（rc=2）`——rc=2 恰是 env 档，
  即本轮修法针对的**同一形态**（该文件的同族修法曾被预置进场、又按授权红线回滚，diff 留痕在 implement evidence）。
- `integration/t260912-02/acc_g_cleanup.py:55` —— `check(p.returncode == 0, "起 1 台成功（rc=%s）")`。
- `sc_stage_burst_managed_subnets.py:158/211` 走既有 `env_guard`（stderr 特征面），不属该形态。

建议：按同一授权流程**一次补授修全族**（否则会逐轮回合打地鼠）；本段不代改（写集内但非本票授权面，
且属别票资产）。

### 机械口径（本轮原件 `out/integration-report-260913-195348.json`）

```
ran=233 pass=213 fail=1 env_fail=19 wall_s=1464.7 generated=2026-09-13T19:53:48
本票四条全 PASS：t260913-01-authz-signal-delivery 15.4 / t260912-03-authz-overlimit-accept 93.0 /
                -authz-cli-queryable 15.4 / -authz-protected-path 5.3
capture 双胞胎：capture-chat-active PASS 44.6 / capture-chat-e2e PASS 47.5
本轮被修项：t260912-02-net-table-contract **PASS 16.1s**（修法见效）
唯一 FAIL：t260912-02-burst-managed-subnets 109.2s —— SUMMARY pass=93 fail=6（99 腿 6 红；前四轮 86.3/86.5/98.9s 均 PASS）
19 条环境红归类（逐条读 tail；共 20 条非绿=19 env_fail + 1 FAIL）：
   17 × console 台不可达（`test console not reachable at http://127.0.0.1:21020`，browser/browser-free/main 系场景连坐）
  ＋1 × t260904-19-stage-docker（共享锁根内有新鲜外来工程状态 stage-console-33d3151d）
  ＋1 × t260908-01-ticket-pause-gate（`Bind 127.0.0.1:21061 failed: port is already allocated`）
  ＋1 × FAIL t260912-02-burst-managed-subnets（见下）
```

- **与本票交集=零**：burst 属 t260912-02 面；本票 diff 未触碰 burst/网段表/stage_docker；本票四条场景同轮全 PASS。
- 高载窗口旁证：同轮 18 条 console 台不可达 + 端口 21061 占用（本段 `docker ps` 见
  `stage-console-4bba26a2-temporal` 自数小时前就发布 21061 → 与 `t260908-01-ticket-pause-gate` 的
  `Bind 21061 failed` 同源）——环境面，非任何产品红。
- **artifact 局限（如实记录）**：机械报告只保留每条 tail 末 1200 字，burst 的 6 条失败腿身份在
  artifact 内不可得 → 本段**不据 artifact 猜**；归因留仲裁/复跑。建议（非本票面）闸报告对 FAIL 条目
  保留失败腿身份，便于事后归因。

### F 实票验证（本轮复证 20:23:27）

| 票 | 当前态 | 授权消费留痕 |
|----|--------|--------------|
| t260911-05 | `implement/blocked`（已远离 `arbitrate/blocked`） | `接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough` |
| t260912-01 | `run_integration_tests/running` | `受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,…` |

两票 `used=1` 无反复；F 判据（至少一张实际被解开）持续满足（判据取快照 `meta.authorizations[].uses`
+ timeline，不看 stage 名——理由见 gen4 报告的点名）。

## 并行期 UI 呈现

**不适用**（结论不变）：本票无 UI/泳道渲染代码改动。本轮 18 条 console 环境红是 UI 证据台的
**宿主不可达**（台位/基础设施面），不是 UI 渲染面回归；UI 证据链本身本轮由 capture 双胞胎真跑 PASS 背书。

## 遗留与风险

1. **全族未修点**（见上「全族线索」）：`sweep_owner_gone:240`、`acc_g_cleanup:55` 仍是「起台 rc==0 直判」
   形态 → 同类假产品红会复现；建议一次补授修全族（本段不代改）。
2. **闸 blocker 环境面**：`burst-managed-subnets` 6/99 腿红 + 18 条 console 台不可达 + 端口 21061 占用，
   同属供给面（多泳道共用台位/端口）；与本票零交集，但会持续卡 merge 闸，需台位治理（含 5 小时龄的
   `stage-console-4bba26a2` 等旧台归谁处置）。
3. **合并面**：main 仍为 `b614392`（t260913-03 声明 `exclude_pools: engine,exclusive`），本 worktree 基于
   `9c102d7` → 合并需先对齐；engine 池被每票段跳过 → 本票新场景与 t260912-03 三条正腿只由每日巡检覆盖，
   而巡检票 t260913-02 当前 `acceptance_walkthrough/blocked`（建议人审裁定「写集命中 server/engine/ 时是否强制全跑」）。
4. **合并冲突线索**：并行票 t260912-01 获授权改 `integration/baselines/sc_capture_chat_active.mjs`（`uses` 为证），
   与本票 gen1 同文件；本票累计还改了已闭票 t260911-02 的场景文件与 t260912-02 的两个测试资产文件——
   请在合并记录/交接里逐项点名（交叉改动留痕）。
5. **残差面（接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
6. **gen0 两条轻微实现观察仍开放**（引擎自 gen0 起未再改动）：①同秒重复签发同一授权 → 落账判定认不出新条目、
   CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；②畸形值（非数值
   expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring「任何畸形…不炸」不符。
7. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
8. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
   需按 runbook §S0→§S6 再重启一次才能继续用人授权。
9. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查新增四条
   （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台 hold/锁根半态连坐；⑦同族起台腿直判未清）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  理由：本票确立/坐实了跨票复用的引擎机制事实，docs/ 无任何承载（全库 grep 无 authorize/人授权/signal
  载荷纪律条目）——①逐票常驻 worker 的内存代码可早于磁盘代码（本票生产实证：重启前授权不落账、
  03:20:56 重启后重签即落账并被消费，唯一变量=worker 进程代码）；②temporalio 解码对未知字段静默丢弃
  （DefaultPayloadConverter + 旧形类独立复现）；③故载荷演进必须走「标量 marker 可见化 + sign_face 指纹先验
  + 三态回执(landed/refused/unconfirmed)」三步纪律，新字段上线=必须重启在途票 worker；④指纹严格相等
  ⇒ 加任何字段都拒发未重启 worker（运维含义）。`docs/` 不在本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义/归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现与上述成文主张一致，未发现被推翻的
  claim → 不产生 pending-doc-sync 债条目。
