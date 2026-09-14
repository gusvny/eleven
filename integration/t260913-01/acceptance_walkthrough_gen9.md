# t260913-01 验收走查报告（acceptance_walkthrough gen9，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 211 过 / 1 败 / 21 环境红）
仅作输入，关键腿自己重跑、新改动自己读源 + 变异复核。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

本轮是本票**产品面收口**的一轮，新增两处实质改动，均已通过本段审计：

- **①集成道「预算对」修法（空机械轮的根因）**：内层守卫 `BATCH_TIMEOUT_SEC` 5400→**3000**（+300 =
  3300s），严格小于外层 `dev_lane.INTEG_RUN_TO`（60min=3600s）。旧值 5400+300=5700s **晚于外层**，
  导致内层的结构化超时回报是**死代码**——套件只会被 Temporal 硬杀成 `Activity task timed out
  （ran=0，无归因）`，再叠 `RETRY(3)` 白烧。这正好解释我在 gen6–gen8 连续记录的「空机械轮」。
- **②同族起台腿归档补齐**：`integration/t260912-02/sc_stage_sweep_owner_gone.py` 起台腿改按引擎
  自报档位归档（rc 2/3→ENV_FAIL 带每台证据；rc 1/64→FAIL）——机械实证已由 FAIL 转 ENV_FAIL。
- **③工作树复位**：本票 HEAD 复位（未偷渡 main 侧文件、verify.yaml 未改、写集外零改动、本票 7 项增量全在）。
- **机械口径本票四条全 PASS**（19.1 / 92.8 / 14.9 / 3.4s），**本段亲跑全量 UT 724 passed**、lint 0/0。
- **F**：`t260912-01` 已 **closed**；`t260911-05` `used=1`（解扣留痕仍在）。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正腿·受保护路径（送达+消费） | 通过 | 机械：`t260913-01-authz-signal-delivery` PASS 19.1s + `-authz-protected-path` PASS 3.4s |
| B | 正腿·仲裁超限 | 通过 | 机械：`-authz-overlimit-accept` PASS 92.8s（判决原文 + `uses≥1` + 推进） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 机械 PASS 19.1s（含「载荷解析失败」vs「非人审等待中」可辨断言） |
| D | 真往返守卫 | 通过（合成口径） | 两腿真信号、均在册；本轮机械两条均真跑 PASS |
| E | 零回归 | 通过 | 引擎三 handler 语义未变；**本段亲跑 UT 724 passed**（含新预算对守卫 2 条） |
| F | 实票验证 | 通过 | 22 只读：`t260912-01` closed（09-13 23:12）、`t260911-05` `used=1` |
| — | 测试资产/引擎改动审查 | 通过（含 2 条残留） | 见下「改动审计」 |

## 做了什么

1. 定位并读本轮新改动面：`git diff --numstat 9b70d02 HEAD` → `agent_activities.py`(+8/−1)、`dev_lane.py`(+3)、
   新 `tests/test_t260913_01_integ_budget_pair.py`(+46)、`sc_stage_sweep_owner_gone.py`(+17/−3) + 我 gen7/gen8 报告。
2. **复位审计**：`git status`（除 `.sandbar/` 外干净）、`git diff --stat … -- verify.yaml`（空）、
   `git diff --name-only 9c102d7 HEAD` 过滤写集外（空）、7 项本票增量逐个 grep 在场（7/7）。
3. **预算对审计**：读源定位真实守卫点，做算术核对 + **内存变异检查**（不改文件）验证新单测非恒真。
4. **同族修法审计**：逐行 diff 核 sweep 场景（只有起台腿两处改归档 + import；其余断言未动）。
5. **本段亲跑**：lint、本票新场景、net-table、全量 UT。
6. 读本轮机械报告（`out/integration-report-260914-111726.json`），逐条读非绿 tail 定性。
7. 线上 F 只读取证（用户级 `ticket list`）。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen9_checks.log`）

```
python3 integration/lint_tests.py                                → 0 error / 0 warn (exit 0)
sc_authz_signal_delivery.py（本票新场景）                         → exit 2（ENV_FAIL）
    原因：docker 建网竞态「network t26091301a-35334_default not found」——场景自身**正确判 ENV_FAIL**
    （不是 FAIL）；同小时机械口径该场景 PASS 19.1s（见下）⇒ 本轮红项＝环境
sc_stage_net_table_contract.py                                   → SUMMARY pass=19 fail=0 env_fail=0 (exit 0)
pytest server/engine/tests -q                                    → 724 passed in 41.09s
```

### 预算对修法审计（本轮重点）

```
$ grep -n BATCH_TIMEOUT_SEC server/engine/agent_activities.py
3682: BATCH_TIMEOUT_SEC = int(os.environ.get("SANDBAR_INTEG_BATCH_TIMEOUT_SEC") or 3000)
3713: p_out_b, p_err_b = await asyncio.wait_for(p.communicate(), timeout=BATCH_TIMEOUT_SEC + 300)
3717: return IntegrationRunResult(error="场景执行器整体超时（>%ds）" % BATCH_TIMEOUT_SEC)
现行：内层守卫 3300s（3000+300） < 外层 3600s（dev_lane.INTEG_RUN_TO=60min）✓
旧值：内层守卫 5700s（5400+300） > 外层 3600s ⇒ 结构化回报不可达（死代码）+ Temporal 硬杀 ✓ 与实测吻合
内存变异检查（本段亲做，零文件改动）：
  BATCH_TIMEOUT_SEC=5400 → test_inner_budget_fits_inside_activity_timeout 按预期 AssertionError ✓
  BATCH_TIMEOUT_SEC=4000 → test_default_inner_budget_not_widened 按预期 AssertionError ✓
  复位 → 两用例绿 ✓  ⇒ 新单测**非恒真**，任一侧改坏会红并点名查哪侧
```
- **红线核对**：本改动只**收紧**预算窗口（>50min 的套件现在走结构化超时回报，仍是红；此前是被硬杀，
  也是红），不放宽任何断言、不碰 fail-closed、不涉及自签；`SANDBAR_INTEG_BATCH_TIMEOUT_SEC` 覆盖仍生效
  （注释要求同步抬外层，由单测兜住默认面）。

### 同族修法审计（sweep 起台腿）

```
$ git diff 9b70d02 HEAD -- integration/t260912-02/sc_stage_sweep_owner_gone.py
+ 批量起台失败：rcs = {台: rc}; if up_batch_env_only(rcs) → envfail(点名每台 rc)；否则 check(False, "含非 env/conflict 档＝产品/契约面")
+ 挂点腿：check(proc_n.returncode == 0, …) → up_ok(proc_n, …)
其余断言（残台形态/清扫/零残留/端口…）逐字未动
机械实证：本轮该场景 `ENV_FAIL 7 台真台全部起好：3 台起台失败（rc 档位全为 env/conflict＝prepare 型环境/
          并发面，非产品红）：{…live: 2, …legit: 2, …hook: 2}` —— 原口径下这会是一条**假产品 FAIL**
```
**家族残留（如实列出，未修）**：`sc_stage_fuse_headroom_resident.py:100-102` 批量腿仍是
`oks=[rc==0]` + `check(16/16)`（gen8 实测三个 rc=2 被记 FAIL）、`acc_g_cleanup.py:55` 仍
`check(rc==0)`（burst 走 stderr 特征 `env_guard`）。建议一次补授修全族。

### 复位审计

```
$ git status --short | grep -v '^?? .sandbar'      → 空（工作树 = HEAD，零脏文件）
$ git diff --stat 9c102d7 HEAD -- verify.yaml      → 空（分叉点形态，无 exclude_pools）
$ git diff --name-only 9c102d7 HEAD | grep -vE '^(server/engine/|server/tools/ticket.py|integration/)' → 空
$ 增量在场核验（grep）：AUTHZ_SIGNAL_GATE_MARKER / def sign_face / landing / resolveTsdown / envRefused /
  def up_ok / up_batch_env_only → 7/7 命中
```
⇒ 复位未丢本票增量、未偷渡 main 侧文件（notes/、build-client.sh、lib/* 等零残留）。

### 机械口径（本轮 `out/integration-report-260914-111726.json`）

```
ran=233 pass=211 fail=1 env_fail=21 wall_s=1774.2 generated=2026-09-14T11:17:26
本票四条全 PASS：t260913-01-authz-signal-delivery 19.1 / -authz-overlimit-accept 92.8 /
                -authz-cli-queryable 14.9 / -authz-protected-path 3.4
capture-chat-active PASS 43.4（上一轮高载下的 FAIL 已自愈，佐证那轮是并发窗）
唯一 FAIL：t260910-12-herd-no-crosstalk 33.5s（别票；其 ensure 腿拿 rc=2 + STAGE_ENV compose up 失败
          却被记 FAIL —— **同一「prepare 型记产品红」家族**，属该票面）
21 环境红：18 × console/台面（stage-console 不可达/共享锁根外来工程）+ 2 × net（Pool overlaps / network
          not found）+ 1 × t260912-02-sweep-owner-gone（**新归档生效：ENV_FAIL 点名三台 rc=2**）
```

### F 实票验证（本轮）

```
$ ticket list：t260912-01 closed merge/awaiting（updated 09-13 23:12）｜t260911-05 dispatched implement/blocked
  （authz_active 3，消费留痕 uses=1 在册：接受仲裁判决 → acceptance_walkthrough）｜t260913-01 acceptance_walkthrough/running
```
⇒ F 判据（至少一张实际被解开）已由**两票均解扣 + 一张彻底关单**超额满足。

## 并行期 UI 呈现

**不适用**：本票无 UI/泳道渲染代码改动（累计 diff = `server/engine/` 引擎面 + `integration/` 测试资产）。
本轮 UI 证据链场景（capture 双胞胎之一）真跑 PASS 43.4s，无 UI 面回归信号；21 条环境红里的 console 族
是**台位供给面**，非渲染面。

## 遗留与风险

1. **合并建议（本段核心建议）**：产品面已收口——①传输修复（gen0）②空机械轮根因修复（本轮预算对）
   ③测试资产族修（capture/doc_face/net_table/sweep）；四条验收腿机械全 PASS、UT 724 绿、F 超额满足。
   建议人审在现有证据上签字合并；合并前需处理下面第 2 条（main 对齐）。
2. **main 对齐**：main 已到 `8ab007c`（含 KI-087/KI-088 notes），本 lane 基 `9c102d7`；宿主曾令
   「把泳道 merge main」，implement 段尝试后按阶段闸反馈**复位**（并入的 main 侧文件被算成本段改动而拒收）。
   ⇒ 合并需由 merge 执行人在 main 侧对齐（本 lane 的 verify.yaml 是分叉点形态、无 `exclude_pools`，
   与 main 现行声明不同，属预期）。
3. **家族残留（建议一次补授）**：`sc_stage_fuse_headroom_resident.py:100-102` 批量腿、
   `acc_g_cleanup.py:55`；另本轮 mechanical 里别票 `t260910-12-herd-no-crosstalk` 也是同一形态。
4. **残差面（本段接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
5. **gen0 两条轻微实现观察仍开放**（引擎 authz 面自 gen0 未再动）：①同秒重复签发同一授权 → 落账判定认不出
   新条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」；②畸形值（非数值 expires/issued）在 `int()` 处抛异常，
   与 `_authz_entries` docstring「任何畸形…不炸」不符。
6. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
7. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
   需按 runbook §S0→§S6 再重启一次才能继续用人授权。
8. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查累计六条
   （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台/console 台生命周期不一致族；⑦同族起台腿直判未清
   （本轮已修 lib/net_table/sweep，余 fuse-headroom 批量腿与 acc_g_cleanup）；⑧F 判据口径（本轮已自证）；
   ⑨闸执行面故障——**其根因（预算对死代码）已在票内修复**，可转为已闭项上报）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「集成测试道预算对 + sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 同族节）。
  理由（两件跨票事实，docs/ 均无承载）：①**预算对不变量**——机械集测 activity 的内层
  `BATCH_TIMEOUT_SEC+300` 必须严格小于外层 `INTEG_RUN_TO`，否则内层结构化超时回报是死代码、套件被硬杀成
  `ran=0 无归因` 且 RETRY 白烧（本票实测三连空轮，修前 5400+300 > 3600，修后 3000+300 < 3600，单测锁死）；
  ②**sign 信号载荷演进纪律**——逐票常驻 worker 的内存代码可早于磁盘代码（重启前授权不落账、重启后即落账，
  唯一变量=worker 进程代码），temporalio 解码静默丢弃未知字段（DefaultPayloadConverter + 旧形类独立复现），
  故载荷演进必须走「标量 marker 可见化 + sign_face 指纹先验 + 三态回执(landed/refused/unconfirmed)」三步，
  新字段上线=必须重启在途票 worker；指纹严格相等 ⇒ 加字段即拒发未重启 worker（运维含义）。
  `docs/` 不在本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义/归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现与上述成文主张一致，未发现被推翻的
  claim → 不产生 pending-doc-sync 债条目。
