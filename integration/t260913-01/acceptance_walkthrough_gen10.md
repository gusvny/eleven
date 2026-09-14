# t260913-01 验收走查报告（acceptance_walkthrough gen10，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 213 过 / 1 败 / 19 环境红）
仅作输入，关键腿自己重跑、新改动自己读源。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **本轮唯一改动 = 同族起台腿归档修复的第三批（t260910-12 herd 族）**，审计通过：`lib_herd_case.py`
  纯新增 `ensure_leg`（rc 档位归档，+25 行，既有函数零改动）；`sc_herd_no_crosstalk.py` 起台腿改用它
  （+14/−2），并在**任一环境拒跑**时把下游「全部交付/端口/幂等」腿一并 not-checked。产品断言本体逐字未动，
  `rc=1/64` 仍 FAIL，环境态不改判 0。
- **机械口径本票四条全 PASS**（19.4 / 91.2 / 15.8 / 4.4s）；**修法见效**：`t260910-12-herd-no-crosstalk`
  由上一轮的 FAIL 转 **PASS 38.4s**；capture 双胞胎 PASS 41.5/45.3s。
- **本段亲跑**：lint 0/0；`herd-no-crosstalk` **pass=44 fail=0 exit 0**；全量 UT **724 passed**；
  本票新场景本轮亲跑撞 docker 端口竞态（`Bind 127.0.0.1:21061 already allocated` → 场景自判 ENV_FAIL
  exit 2），而同小时机械口径该场景 PASS 19.4s ⇒ 明确归环境。
- **唯一机械 FAIL 是我连续三轮预告的家族残留点**：`t260912-02-fuse-headroom-resident`
  「16/16 全绿（实得 14，非零 [(b02, **2**), (b05, **2**)])」——两个非零全是 **rc=2＝env 档**，被旧口径
  `oks=[rc==0]` 记成产品 FAIL（属别票面，非本票产品红）。
- **F**：`t260912-01` closed（09-13 23:12）；`t260911-05` `used=1`（解扣留痕在册）。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正腿·受保护路径（送达+消费） | 通过 | 机械：`t260913-01-authz-signal-delivery` PASS 19.4s + `-authz-protected-path` PASS 4.4s |
| B | 正腿·仲裁超限 | 通过 | 机械：`-authz-overlimit-accept` PASS 91.2s |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 机械 PASS 19.4s（含可辨文案断言） |
| D | 真往返守卫 | 通过（合成口径） | 两腿真信号、均在册 |
| E | 零回归 | 通过 | 引擎三 handler 语义未变；本段亲跑 UT 724 passed |
| F | 实票验证 | 通过 | `t260912-01` closed；`t260911-05` `used=1` |
| — | 测试资产变更审查 | 通过（1 条残留已指名） | herd 族归档修复；残留＝fuse-headroom 批量腿 |

## 做了什么

1. 核对本轮改动面：`git diff --numstat fff7dd2 HEAD` → `lib_herd_case.py`(+25)、`sc_herd_no_crosstalk.py`(+14/−2)、
   我 gen9 报告；工作区干净，累计改动全在写集内。
2. **逐行审计 herd 修复**：diff 全文核（只动起台腿 + import + 下游短路），断言本体未改；核对
   `ensure_leg` 的档位判据与库内 `up_ok`/`up_batch_env_only` 同口径（rc=2/3→env、其余→fail），
   并把「环境账不与产品契约混账」落实到下游腿 not-checked。
3. **本段亲跑**：lint、本票新场景、本轮被修场景（herd）、全量 UT。
4. 读本轮机械报告（`out/integration-report-260914-133914.json`）非绿 tail，定性唯一 FAIL 与 19 条环境红。
5. 线上 F 只读取证（用户级 `ticket list`）。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen10_checks.log`）

```
python3 integration/lint_tests.py                    → 0 error / 0 warn (exit 0)
sc_authz_signal_delivery.py                          → exit 2（ENV_FAIL）
   原因：Bind for 127.0.0.1:21061 failed: port is already allocated（跨泳道端口竞态，场景自判环境）
sc_herd_no_crosstalk.py（本轮被修场景）               → SUMMARY pass=44 fail=0 env_fail=0 ；exit 0
pytest server/engine/tests -q                        → 724 passed in 44.62s
```

### 机械口径（本轮 `out/integration-report-260914-133914.json`）

```
ran=233 pass=213 fail=1 env_fail=19 wall_s=1678.1 generated=2026-09-14T13:39:14
本票四条全 PASS：19.4 / 91.2 / 15.8 / 4.4
t260910-12-herd-no-crosstalk PASS 38.4（上一轮 FAIL → 本轮修法见效）
capture-chat-active PASS 41.5 ｜ capture-chat-e2e PASS 45.3
唯一 FAIL：t260912-02-fuse-headroom-resident 31.7s
  ok 6 条常驻租约注入在册
  FAIL 16/16 全绿（实得 14，非零 [('…-b02', 2), ('…-b05', 2)]）   ← 两个非零均为 rc=2＝env 档
  ok 全程零保险丝红 / ok 16 台端口两两互异 / ok 端口∉生产禁区 / ok 16 台墙钟有界 / ok 常驻全在册 / ok 零误伤 / ok 拆台零残留
19 环境红：18 × console/台面 + 1 × t260907-04-schedule-legacy-retire（temporal 180s 未就绪）
闸拦：t260912-02-fuse-headroom-resident ｜ 归属置信=unknown(baseline_unavailable) ｜ 基线=f66345b8…
```

### 测试资产变更审查（本轮）

| 检查点 | 结论 | 证据 |
|---|---|---|
| 断言语义是否放宽 | **未放宽** | diff 全文：起台腿 `check(rc==0,…)` → `ensure_leg(...)`；下游「六台全部交付」腿**原文保留**，仅加环境短路口；端口互异/禁区/档位窗/幂等 container_ids/零残留逐字未动 |
| 是否把产品红洗成环境红 | **不会** | `ensure_leg` 只把 rc∈{2,3} 归 ENV_FAIL；`rc=1/64` 走 `check(False,…)` 仍 FAIL 且文案点名「非 0/2/3＝产品/契约面」 |
| ENV_FAIL 是否带 reason+evidence | **是** | 点名档位（env/conflict）+ 两流合并末段 160 字（修正了「只取 stderr 会把诊断引错方向」——真因常在 stdout 的 STAGE_ENV 行） |
| 环境态是否被改判 0 | **否** | `finish()` 仍 `exit(2 if env_fail and not fail else …)`；环境短路口直接 finish，不产生 pass |
| 下游腿是否被误当已验 | **否** | 有环境拒跑 ⇒ 「六台全部交付」腿整体 not-checked（不评产品契约），符合失败分类协议 |
| 家族一致性 | **同口径** | `ensure_leg`（herd 族）与 `up_ok`/`up_batch_env_only`（t260912-02 族）判据一致；lib_herd_case 被 10 个文件 import（6×acc_* + 4×t260910-12） |

**总判定：契约精确化（prepare 型起台失败的三态归属），非绿灯捷径。**

### 家族残留（下一顺位，已是当前唯一机械 blocker）

`sc_stage_fuse_headroom_resident.py:100-102`：
```python
oks = [(p, rc) for p, rc, _o, _e in results if rc == 0]
check(len(oks) == N_BURST, "16/16 全绿（实得 %d，非零 %s）" % …)
```
—— 本轮实测两个非零 rc=2（env 档）被记 FAIL。**同目录 lib 里已有现成单源助手 `up_batch_env_only`**
（implement gen2 新增），属一行级接线；另 `acc_g_cleanup.py:55` 亦同形态。建议按同一条授权流程补授后一次修尽，
以免每轮换一个场景当 blocker（t260910-12 → 修；fuse-headroom → 待修）。

### F 实票验证（本轮）

```
$ ticket list：t260912-01 closed merge/awaiting（09-13 23:12）｜t260911-05 dispatched implement/blocked
  （authz_active 3；uses=1：接受仲裁判决 → acceptance_walkthrough）｜t260913-01 acceptance_walkthrough/running
```
⇒ F 判据（至少一张实际被解开）持续超额满足。

## 并行期 UI 呈现

**不适用**：本票无 UI/泳道渲染代码改动（累计 diff = 引擎面 + 测试资产）。本轮 capture 双胞胎真跑 PASS
（41.5/45.3s），UI 证据链无回归信号；19 条环境红里的 console 族是台位供给面，非渲染面。

## 遗留与风险

1. **合并建议**：本票产品面已收口（传输修复 + 预算对根因修复 + 家族归档三批），四条验收腿机械全 PASS、
   UT 724 绿、F 超额满足。**唯一机械 blocker 是别票场景的家族残留**（fuse-headroom 批量腿 rc=2 被记 FAIL），
   不是本票产品红。建议人审据此签字合并；若闸坚持拦，则先按第 2 条补授修尽。
2. **家族残留（建议一次补授修尽）**：`sc_stage_fuse_headroom_resident.py:100-102`（本轮 blocker）、
   `acc_g_cleanup.py:55`；burst 走 stderr 特征 `env_guard`（半覆盖）。lib 已有 `up_batch_env_only` 可直接接线。
3. **合并对齐**：main 已到 `1e6f360`（KI-089 结论二次修正），本 lane 基 `9c102d7`、本票 HEAD `5602036`；
   宿主曾令「把泳道 merge main」但被阶段闸判为越界而复位 ⇒ 合并需在 main 侧对齐（本 lane 的 verify.yaml
   是分叉点形态，无 `exclude_pools`，与 main 现行声明不同属预期）。
4. **残差面（本段接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
5. **gen0 两条轻微实现观察仍开放**（引擎 authz 面自 gen0 未再动）：①同秒重复签发同一授权 → 落账判定认不出
   新条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」；②畸形值（非数值 expires/issued）在 `int()` 处抛异常，
   与 `_authz_entries` docstring「任何畸形…不炸」不符。
6. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
7. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
   需按 runbook §S0→§S6 再重启一次才能继续用人授权。
8. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查累计六条
   （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台/console 台生命周期不一致族；⑦家族起台腿直判
   ——本轮已修至第三批（lib/net_table/sweep + herd），余 fuse-headroom 批量腿与 acc_g_cleanup；
   ⑧F 判据口径；⑨闸执行面空轮根因＝预算对死代码，**本票已修**，建议记已闭并转 docs 沉淀）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「集成测试道预算对 + 起台腿三态归档 + sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 同族节）。
  理由（三件跨票事实，docs/ 均无承载）：①**预算对不变量**——内层 `BATCH_TIMEOUT_SEC+300` 必须严格小于外层
  `INTEG_RUN_TO`，否则结构化超时回报是死代码、套件被硬杀成 `ran=0 无归因` 且 RETRY 白烧（本票修 + 单测锁死）；
  ②**起台腿三态归档单源**——起台是 prepare 型前置面，rc=2/3 应记 ENV_FAIL 带证据、rc=1/64 仍 FAIL，
  且环境拒跑时下游腿一并 not-checked（本票已在 t260912-02 族与 t260910-12 herd 族落地两种单源实现，
  宜统一成一处共享 helper）；③**sign 信号载荷演进纪律**——逐票常驻 worker 内存代码可早于磁盘代码
  （重启前授权不落账、重启后即落账，唯一变量=worker 进程代码）、temporalio 解码静默丢弃未知字段，
  故必须走「标量 marker 可见化 + sign_face 指纹先验 + 三态回执」三步，新字段上线=必须重启在途票 worker。
  `docs/` 不在本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义/归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现与上述成文主张一致，未发现被推翻的
  claim → 不产生 pending-doc-sync 债条目。
