# t260913-01 验收走查报告（acceptance_walkthrough gen11，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；本轮机械口径 **197 跑 / 196 过 / 1 败 / 0 环境红**
且**跳过 engine+exclusive 池（少 47 条）——本票四条场景未在其中**，故本段全部手跑补证。与仲裁并行执行，
本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **lane 已并入 main（merge commit `ec8762b`），合并正确性审计通过**：本票相对 main 的差异＝恰好本票自己的面
  （引擎 5 文件 + 3 UT + integration 测试资产 + 本票场景）；合并时点的 main head（`1e6f360`）是 HEAD 祖先；
  7 项增量全在；**合并树 UT 760 passed**、lint 0/0。未发现「丢掉 main 内容」的消解缺陷。
- **merge_check 两条红的处置正确且待落盘**：`.sandbar/routes-migration-260911/` 两个文件在 main 侧 **0 tracked**
  （`git ls-tree -r main` 空）⇒ 待删 tracked 状态是历史欠账（KI-090），删除方向正确；当前工作区仍呈 2 个 ` D`，
  按落盘纪律交由 worker 随本段结果提交。
- **本段手跑补证（因 engine 池被每票段跳过）**：`-authz-protected-path` **37/0**、`-authz-overlimit-accept` **30/0**、
  `-authz-cli-queryable` **24/0**、`t260913-01-authz-signal-delivery` **37/0**（首跑撞 docker 建网竞态 exit 2，
  随后**连续两次 37/0 绿**）；lint **0/0**；UT **760 passed**。
- **闸唯一 FAIL 非本票面**：`t260913-03-executor-pool-exclude-l1`（别票 ro 池），本段复跑 **32/0 exit 0**（H1 绿）→ 瞬态。
- **家族起台子用例归档本轮再补两例**（fuse_headroom / fuse_runaway），审计通过；残点见遗留。
- **F**：`t260912-01` closed；`t260911-05` `used=1`。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正用例·受保护路径（送达+消费） | 通过 | 本段手跑 `sc_authz_signal_delivery` **37/0**（送达）、`-authz-protected-path` **37/0**（消费） |
| B | 正用例·仲裁超限 | 通过 | 本段手跑 `-authz-overlimit-accept` **30/0**（merged 树上，判决原文+`uses≥1`+推进） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本段手跑新场景 37/0（含「载荷解析失败」vs「非人审等待中」可辨断言） |
| D | 真往返守卫 | 通过（合成口径） | 两子用例真信号、均在册；本段手跑两条真信号链 |
| E | 零回归 | 通过 | 引擎三 handler 语义未变；合并树 UT **760 passed** |
| F | 实票验证 | 通过 | `t260912-01` closed；`t260911-05` `used=1` |
| — | 测试资产/合并审查 | 通过（残点已列） | 合并正确性三方圆核 + 家族归档两例审计 |

## 做了什么

1. 核对本轮状态：`git log`（HEAD=`ec8762b` 合并提交）、`git status`（除 `.sandbar/` 外恰 2 行 ` D`）、
   `git ls-files .sandbar/`（2，待删）、`verify.yaml`（`exclude_pools: engine,exclusive` 已随 main 并入）。
2. **合并正确性三方圆核**（本段重点）：`git diff main HEAD`（本票差异＝自己的面）、
   `git merge-base --is-ancestor 1e6f360 HEAD`（✓）、`git log HEAD -- notes/debts/known-issues.md`
   （最后改动是 main 的提交，本票零改动）、`git ls-tree -r main -- .sandbar/routes-migration-260911/`（0）。
3. **本段手跑**：lint、合并树全量 UT、本票四条场景（因为 engine 池被跳过，机械口径本轮不含它们）。
4. 读本轮机械结果，定性唯一 FAIL；复跑该 FAIL 对应的 ro 池用例（32/0 绿）。
5. 审计本轮新增的两例家族归档（fuse_headroom / fuse_runaway）diff。
6. 家族残留扫描（全仓 grep 起台子用例直判形态）+ 线上 F 只读取证。

## 怎么验证的（证据引用）

### 本段手跑（原文 `.sandbar/evidence/gen11_checks.log` + `gen11_retry.log`）

```
python3 integration/lint_tests.py                      → 0 error / 0 warn (exit 0)
pytest server/engine/tests -q                          → 760 passed in 75.74s   ← 合并树口径（本 lane 724 + main 36）
sc_authz_protected_path.py                             → pass=37 fail=0 (exit 0)
sc_authz_overlimit_accept.py                           → pass=30 fail=0 (exit 0)
sc_authz_cli_queryable.py                              → pass=24 fail=0 (exit 0)
sc_authz_signal_delivery.py                            → 首跑 exit 2（docker 建网竞态 network …_default not found）
                                                         重试 ×2 → pass=37 fail=0 (exit 0) ×2
```

### 机械口径（本轮，含覆盖口径变化）

```
197 跑 / 196 过 / 1 败 / 0 环境红 ｜ 本轮跳过池=engine、exclusive（少 47 条）
唯一 FAIL：t260913-03-executor-pool-exclude-l1（H1「缺省路径输出与改前执行器逐字节一致」）
本段复跑该用例：SUMMARY pass=32 fail=0 env_fail=0 ；exit 0  ⇒ 瞬态，非本票面
闸拦（决策表）：t260913-03-executor-pool-exclude-l1 ｜ 归属置信=unknown(baseline_unavailable) ｜ 基线=268591a0d6b1acd9a7d8c6dc02f821316c361553
```

### 合并正确性审计（本段重点）

| 检查点 | 结论 | 证据 |
|---|---|---|
| 合并时点 main 是否在树内 | **是** | `git merge-base --is-ancestor 1e6f360 HEAD` → YES |
| 本票差异是否只有自己的面 | **是** | `git diff --name-only main`（去报告）= `server/engine/{agent_activities,client,dev_lane,shared,worker}.py` + 3 UT + `integration/{baselines×3,run_scenarios,t260910-12×2,t260911-02,t260912-02×4,t260913-01/tests}` |
| 是否有 main 内容被消解丢掉 | **无** | 唯一「vs main 为负」的文件是 `notes/debts/known-issues.md`（−24 行）：该 −24 对应 main **更晚**的 `268591a`（KI-090）；本 lane 侧该文件最后改动是 main 的 `1e6f360`、**本票零改动** ⇒ 属「main 已前进」而非丢内容；合并回 main 时该文件无冲突、KI-090 保留 |
| 待删两文件方向是否正确 | **正确** | `git ls-tree -r main -- .sandbar/routes-migration-260911/` = **0** ⇒ 删除后与 main 对齐（KI-090 同源欠账） |
| 合并树是否健康 | **是** | UT **760 passed**（本 lane 724 + main 36）、lint 0/0、本票四条场景手跑全绿 |

### 家族起台子用例归档（本轮新增两例，审计通过）

```
sc_stage_fuse_headroom_resident.py（arbitrate gen6 落）：
  非零全为 env(2)/conflict(3) → envfail（点名每台 rc，not-checked）；否则走原 check(len(oks)==N_BURST)
sc_stage_fuse_runaway_named_stop.py：
  other 桶按档位分家：全 2/3 → envfail；含 1/64/-1 → 原 check 照旧判产品红（「执行器杀死按产品红记录」口径不变）
审计：原 check 表达式在 else 分支逐字保留；rc=1/64/-1 仍产品红；ENV_FAIL 带 rc 证据 ⇒ 契约精确化，非放宽
```

**家族残留（如实列出，非本票 blocker）**：`sc_stage_burst_managed_subnets.py:160`（32/32 起台成功直判）、
`acc_g_cleanup.py:55`（起 1 台成功直判）、`sc_cwd_independence.py:59`、`sc_holder_kill_reclaim.py:75`。
建议按同一授权流程补授修尽。

### 覆盖口径变化（重要，需人审知晓）

- main 现行 `verify.yaml` 声明 `exclude_pools: engine,exclusive`（例外分支已由宿主撤除），**每票集测段不再跑
  engine 池** → 本票自带的真信号守卫（`t260913-01-authz-signal-delivery`）与 t260912-03 三条正用例**都不在每票段**，
  改由每日巡检（`t260913-02`，当前 `acceptance_walkthrough/running`）或人工跑覆盖。
- 本轮即为实证：197 跑里没有本票任何场景；本段以手跑四种补足。**建议**：本票合并后把「authz 四场景纳入巡检
  显式清单/或纳入强制面」作为已知覆盖口径记录（本段只报观察，不改 main 声明）。

### F 实票验证（本轮）

```
$ ticket list：t260912-01 closed merge/awaiting（09-13 23:12）｜t260911-05 dispatched implement/blocked
  （authz_active 3；uses=1：接受仲裁判决 → acceptance_walkthrough）｜t260913-01 acceptance_walkthrough/running
```
⇒ F 判据（至少一张实际被解开）持续超额满足。

## 并行期 UI 呈现

**不适用**：本票无 UI/泳道渲染代码改动（本票差异清单为引擎面 + integration 测试资产）。合并带入的
main 侧 UI 改动（chat-project-tag 等）属别票面，其场景在本轮 197 跑中为 PASS。

## 遗留与风险

1. **待落盘**：`.sandbar/routes-migration-260911/` 两个 tracked 文件的删除（工作区已 ` D`，盘上已不存在）
   需 worker 随本段结果提交；落定判据 `git ls-files -- .sandbar/routes-migration-260911/` 为空、
   `git status` 干净。**本段未自行 git add/commit**（落盘纪律）。
2. **覆盖口径**（见上）：engine 池不在每票段；本票守卫场景的自动覆盖依赖每日巡检。建议在合并记录里点名。
3. **家族残留**（非本票 blocker）：burst:160 / acc_g_cleanup:55 / cwd_independence:59 / holder_kill_reclaim:75。
4. **KI-090 建议未实施**：`.gitignore` 仍无 `.sandbar/`（该目录按设计从不入库；现靠「不 add」挡住）——
   属 main 侧 notes 建议面，不在本票写集，转呈宿主。
5. **残差面（接受）**：真实字节漂移（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
6. **gen0 两条轻微实现观察仍开放**（引擎 authz 面自 gen0 未再动）：①同秒重复签发同一授权 → 落账判定认不出
   新条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」；②畸形值（非数值 expires/issued）在 `int()` 处抛异常，
   与 `_authz_entries` docstring「任何畸形…不炸」不符。
7. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
8. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
   需按 runbook §S0→§S6 再重启一次才能继续用人授权。
9. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查累计六条
   （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台/console 台生命周期不一致族；⑦家族起台子用例直判
   ——本轮已修至第五例（lib/net_table/sweep/herd/fuse×2），余 burst/acc_g_cleanup/cwd_independence/holder_kill_reclaim；
   ⑧F 判据口径；⑨闸执行面空轮根因＝预算对死代码（本票已修）；**⑩新增：engine 池被每票段排除 → 本票守卫场景
   仅由日巡覆盖**）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「集成测试道预算对 + 起台子用例三态归档 + sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 同族节）。
  理由（本轮新增第 4 件跨票事实，前三件见 gen10）：①**预算对不变量**（内层 `BATCH_TIMEOUT_SEC+300` 必须严格
  小于外层 `INTEG_RUN_TO`，否则结构化超时回报是死代码→硬杀→`ran=0` 无归因 + RETRY 白烧；本票修并单测锁死）；
  ②**起台子用例三态归档单源**（prepare 型 rc=2/3 记 ENV_FAIL 带证据、rc=1/64 仍 FAIL、环境拒跑时下游子用例 not-checked；
  本票已在 t260912-02 与 t260910-12 两族落地 `up_ok`/`up_batch_env_only`/`ensure_leg` 三处同口径实现）；③**sign
  信号载荷演进纪律**（worker 内存码可早于磁盘码、temporalio 静默丢未知字段 ⇒「marker 可见化 + sign_face 指纹
  先验 + 三态回执」，新字段上线必须重启在途票 worker）；④**每票集测段覆盖口径**——`verify.yaml exclude_pools`
  使 engine 池不进每票段，票自带 L3 守卫只有日巡/人工覆盖（须在票面显式声明，避免「以为机械跑过」）。
  `docs/` 不在本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义/归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读；含 main 新增 KI-089/KI-090，其中 KI-090 正描述本票 merge_check 两条红）。
  本票实现与上述成文主张一致，未发现被推翻的 claim → 不产生 pending-doc-sync 债条目。
