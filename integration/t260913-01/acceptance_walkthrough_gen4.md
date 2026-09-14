# t260913-01 验收走查报告（acceptance_walkthrough gen4，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 231 过 / 1 败 / 1 环境红）
仅作输入，关键腿自己重跑。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **本轮零代码、零测试资产改动**：新增提交 `e7009d3` 内容仅我上轮的走查报告；仲裁 gen3 结果文件自报
  `files_changed=[]`，动作全在**供给面（docker 容器/临时锁根清理）**。累计 diff 与前两轮逐字节相同。
- **A–F 全部满足**：机械口径本票四条在册场景**全 PASS**（16.1s / 88.5s / 14.6s / 2.5s）；本段亲跑
  lint 0/0、新场景 `pass=37 fail=0 exit=0`、引擎 UT 722 passed；F 两票 `used=1` 且 t260912-01 仍在推进。
- **闸唯一 FAIL 已定性为起台瞬态**：`t260912-02-net-table-contract`（别票场景，engine 池）失败腿是
  `A 台起台 rc=0`（`up_stage` 返回非零=起台失败），本段独立复跑 **19/0 exit 0** → 瞬态，与本票零交集。
- **环境面显著改善**：上轮 19 条环境红 → 本轮 1 条（多泳道起台窗）。上轮由死供给台连坐的 17 条
  console 依赖场景**本轮全部转绿**（`t260903-07-chat-project-tag` 9.2s、`ticket-session-restore` 19.6s、
  `multi-tab-coexistence` 70.2s…），我上轮报告的「容器仍在」观察已被本轮事实更新。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正腿·受保护路径（送达+消费） | 通过 | `t260913-01-authz-signal-delivery` PASS 16.1s（送达面）；`t260912-03-authz-protected-path` PASS 2.5s（消费面含 `path_gate_authz_used` 记名） |
| B | 正腿·仲裁超限 | 通过 | `t260912-03-authz-overlimit-accept` PASS 88.5s（判决原文 + `uses≥1` + 推进 acceptance_walkthrough） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本段亲跑新场景 `pass=37 fail=0 exit=0`（含「载荷解析失败」与「非人审等待中」机械可辨断言）；机械口径 PASS |
| D | 真往返守卫 | 通过（合成口径） | 两腿真信号、均在册（字面读法偏离沿用 review C6 裁定，gen1–gen3 已标注） |
| E | 零回归 | 通过 | 引擎三 handler 源码零 diff（累计 diff 未变）；本段亲跑 UT 722 passed；`t260912-03-authz-cli-queryable` PASS 14.6s |
| F | 实票验证 | 通过 | 17:41 只读取证：两票各 `used=1`；t260912-01 `run_integration_tests/running`（持续推进），t260911-05 已远离 `arbitrate/blocked`（现 `implement/blocked`，历史推进由授权消费留痕锁定） |
| — | 测试资产变更审查 | 本轮无变更 | `git diff` 与仲裁 `files_changed=[]` 双向确认为零；累计四文件保持审计后形态且机械口径全绿 |

## 做了什么

1. 核对本轮改动面：`git diff --numstat 00f17f0 HEAD` → 仅我上轮报告（+163/−0）；`git diff --numstat 9c102d7 HEAD`
   累计面与前轮**逐字节相同**（引擎五文件、场景、UT、四个测试资产文件均无新增改动）。
2. 读本轮机械报告原件 `out/integration-report-260913-171325.json`（233/231/1/1），逐条读 tail 定性两条非绿。
3. 本段亲跑：lint + 本票新场景（真 docker 台真信号）+ **闸 blocker 独立复跑** + 引擎全量 UT。
4. 线上 F 只读取证（真 Temporal 7233，query 零副作用），并与仲裁 gen3 报告的 F 结论对照。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen4_checks.log`）

```
python3 integration/lint_tests.py                                        → 0 error / 0 warn (exit 0)
server/engine/.venv/bin/python -B integration/t260913-01/tests/sc_authz_signal_delivery.py
    → SC sc_authz_signal_delivery pass=37 fail=0 (exit=0)
python3 integration/t260912-02/sc_stage_net_table_contract.py            → SUMMARY pass=19 fail=0 env_fail=0 na=0 (exit 0)
server/engine/.venv/bin/python -m pytest server/engine/tests -q          → 722 passed in 27.07s
```

### 机械口径（本轮原件 `out/integration-report-260913-171325.json`）

```
ran=233 pass=231 fail=1 env_fail=1 wall_s=1470.6 generated=2026-09-13T17:13:25
本票四条全 PASS：t260913-01-authz-signal-delivery 16.1 / t260912-03-authz-overlimit-accept 88.5 /
                -authz-cli-queryable 14.6 / -authz-protected-path 2.5
capture 双胞胎续绿：capture-chat-active 38.6 / capture-chat-e2e 39.3
console 族（上轮 17 连坐的全部）本轮 PASS：t260903-07-chat-project-tag 9.2 / ticket-session-restore 19.6 /
                ticket-evidence-images 9.2 / multi-tab-coexistence 70.2 / t260904-05-* / t13-evidence-lightbox…（≈17 条）
唯一 FAIL：t260912-02-net-table-contract 11.6s → 「ok 受管网段表=256 槽（实得 256） FAIL A 台起台 rc=0」
唯一 ENV_FAIL：t260904-19-stage-docker 0.1s → 「共享锁根内有新鲜外来工程状态（t26091004-sc-4826，120s 内有起台活动）」
```

### 闸 blocker 定性（独立复跑）

- 失败腿读源：`sc_stage_net_table_contract.py:126` `if not check(proca.returncode == 0, "A 台起台 rc=0")`
  —— 即 `up_stage(...services="temporal")` **起台进程返回非零**，属起台/环境面，不是断言面回归。
- 本段同码独立复跑：`SUMMARY pass=19 fail=0 env_fail=0 na=0`，`exit 0`（含受管网段表 256 槽、两台真台
  分配互异、归还池、畸形底座拒收等全腿）→ **该 FAIL 判为瞬态**（KI-072 同族：负载/并发下起台假红）。
- 与本票交集：**零**——该场景属 t260912-02 面（残台清扫/网段契约），本票 diff 未触碰 `stage_docker.py`、
  网段表或该场景；本票四条场景同轮全 PASS。
- 唯一 ENV_FAIL 同为环境面：共享锁根 120s 内有并行泳道（t26091004-sc-4826）起台活动，闸自带「多泳道起台
  窗内不作产品判定」语义。

### F 实票验证（本轮复证 17:41:40）

| 票 | 当前态 | 授权消费留痕（历史事实） |
|----|--------|--------------------------|
| t260911-05 | `implement/blocked`（已远离 `arbitrate/blocked`） | `接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough`（stage=arbitrate） |
| t260912-01 | `run_integration_tests/running`（已离开 `design_integration_tests/blocked`） | `受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,sc_ticket_evidence_images.mjs,sc_ticket_session_restore.mjs`（stage=integ_join） |

**与仲裁 gen3 报告的一处不一致（如实点名，属报告精确性问题）**：仲裁 gen3 的「遗留与风险」写
「验收 F（两票真解开）仍待宿主执行：…两票未解前本票不得算完成」，与本段（及 gen1–gen3）线上只读取证
不符——两票的授权消费留痕与时间线自 260913 03:2x 起就在场，t260912-01 至今仍在 `run_integration_tests`
推进。**本段判定 F 已满足**；建议下游以「快照 `meta.authorizations[].uses` + timeline」为 F 判据，
不要只看 stage 名（`blocked` 字样出现在两票的**其它**环节，易被误读）。

## 测试资产变更审查（本轮）

- **本轮零变更**（双向确认）：`git diff --numstat 00f17f0 HEAD` 仅我上轮报告；仲裁 gen3 `files_changed=[]`。
- 累计四个测试资产文件（gen1 三处 capture 基线 + gen2 一处 doc_face）保持前几轮审计后的形态；本轮机械口径
  给出正向佐证：capture 双胞胎真跑 PASS（38.6/39.3s）、doc_face PASS 21.4s、net-table 场景复跑绿。
- 前几轮审查结论（断言表达式逐字节未动、`env_fail`→exit 2 ≠ 假绿、doc_face 修复为同源对齐、授权 scope
  覆盖写入面）继续有效，**无新增弱化面**。

## 并行期 UI 呈现

**不适用**（结论不变）：本票无 UI/泳道渲染代码改动。补充本轮事实：上轮因死供给台连坐的 17 条 console/UI
证据类场景本轮全部转绿（含 `t260903-07-chat-project-tag`、`ticket-session-restore`、`multi-tab-coexistence`），
说明 UI 证据链本身无回归，环境面已恢复。

## 遗留与风险

1. **合并面**：main 仍为 `b614392`（t260913-03 声明 `exclude_pools: engine,exclusive`），本 worktree 基于
   `9c102d7` → 合并需先对齐。该声明使每票集测段跳过 engine 池，本票新场景与 t260912-03 三条正腿只由
   **每日巡检**覆盖，而巡检票 **t260913-02 当前 `acceptance_walkthrough/blocked`**；建议人审裁定「写集命中
   `server/engine/` 时是否强制全跑」——本段只报观察。
2. **合并冲突线索**：并行票 t260912-01 获授权改 `integration/baselines/sc_capture_chat_active.mjs`（其 `uses`
   明细为证），与本票 gen1 同文件；另本票 gen2 改了已闭票 t260911-02 的场景文件——两处交叉改动请在合并
   记录/交接里点名留痕。
3. **供给台结构性风险（仲裁已提修法建议，本段附议并登记 KI 候选）**：①hold 到期自退不清台 → 台在
   「过期+holder 已走」态被 ensure fail-closed 拒跑 → 单台可连坐 ~17 条 console 依赖场景；②锁根分裂
   （沙箱降级根写入 lease 对闸侧不可见）→ 「容器在跑却报租约已死/缺失」半态，纪律上「受限沙箱内不得跑
   console 族场景」。本轮两类均已清理，现象归零，但机制性修法（清台/单锁根）尚未落地。
4. **残差面（接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品
   信号，应显式断言「committed bundle == 源码重建产物」。
5. **gen0 两条轻微实现观察仍开放**（引擎自 gen0 起未再改动）：①同秒重复签发同一授权 → 落账判定认不出新
   条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；②畸形值
   （非数值 expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring「任何畸形…不炸」
   不符。均非阻塞，建议随 KI 候选登记。
6. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
7. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网
   worker 需按 runbook §S0→§S6 再重启一次才能继续用人授权。
8. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查新增三条
   （④回执机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台 hold 到期不清台/锁根分裂连坐）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  理由：本票确立/坐实了跨票复用的引擎机制事实，docs/ 无任何承载（全库 grep 无 authorize/人授权/signal
  载荷纪律条目）——①逐票常驻 worker 的内存代码可早于磁盘代码（本票生产实证：重启前授权不落账、
  03:20:56 重启后重签即落账并被消费，唯一变量=worker 进程代码）；②temporalio 解码对未知字段静默丢弃
  （本段用 DefaultPayloadConverter + 旧形类独立复现）；③故载荷演进必须走「标量 marker 可见化 +
  sign_face 指纹先验 + 三态回执(landed/refused/unconfirmed)」三步纪律，新字段上线=必须重启在途票 worker；
  ④指纹严格相等 ⇒ 加任何字段都拒发未重启 worker（运维含义）。`docs/` 不在本票写集（review_plan R1 已裁），
  故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 两条 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义/归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现（普通签字零改动、授权通道为
  新增例外面、fail-closed 不放宽、prepare 型原因归 not-checked 且带 reason+evidence）与上述成文主张一致，
  未发现被推翻的 claim → 不产生 pending-doc-sync 债条目。
