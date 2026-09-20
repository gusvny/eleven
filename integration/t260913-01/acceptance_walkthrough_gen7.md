# t260913-01 验收走查报告（acceptance_walkthrough gen7，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；**本轮机械口径又是空的（0 跑）**，因此本轮结论
全部来自本段的独立复跑与只读取证。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **本轮机械口径 = 0 跑**（`集成测试 activity 故障：ActivityError: Activity task failed`）→ 本轮无机械证据。
  这是**连续第三轮**机械覆盖缺失/残缺：19:53 那轮跑了 233 条（本票四条全 PASS）之后，上一轮 supply 装配失败
  0 跑、本轮 activity 故障 0 跑。供给台本身现在健康（21350 带，`Up` 45 分钟+）。
- **本段独立复跑**（在 26 个容器、load average 38–49 的忙窗内）：lint 0/0、本票新场景
  `pass=37 fail=0 (exit=0)`、引擎 UT **721 passed + 1 failed**——唯一红是
  `test_t260901_25_t03_reap_process_group`，**单跑 1.30s 绿**（KI-072 负载敏感假红；该测试包的是
  `integration/t260901-25/` 的脚本，与本票 diff 零交集；这也是我 gen0 轮遇到过的同一条）。
- **本轮零代码 / 零测试资产改动**：新增提交仅我上轮的走查报告；仲裁 gen6 `files_changed=[]`。
- **A–F 结论未变（引擎实现自 gen0 起零改动）**；F 仍成立且**继续推进**：t260912-01 现为
  `acceptance_walkthrough/running`（该票已走完 design_integration_tests → run_integration_tests → 验收走查），
  t260911-05 `implement/blocked`（已远离 `arbitrate/blocked`），两票 `used=1`。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正用例·受保护路径（送达+消费） | 通过 | 本轮亲跑新场景 37/0（送达面）；消费面沿用 gen0–gen5 真跑（`path_gate_authz_used` 记名）；引擎/场景本轮零改动 |
| B | 正用例·仲裁超限 | 通过 | 上轮机械 PASS 93.0s；本轮引擎零改动；F 生产面 t260911-05 即该判定实票实证 |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本轮亲跑新场景 `pass=37 fail=0`（含「载荷解析失败」vs「非人审等待中」可辨断言） |
| D | 真往返守卫 | 通过（合成口径） | 两子用例真信号、均在册；本段亲跑 A 子用例真信号链（真 CLI→真信号→真 worker→真 workflow） |
| E | 零回归 | 通过 | 引擎三 handler 源码零 diff；本段亲跑 UT 721 passed（唯一红＝KI-072 负载假红，单跑绿） |
| F | 实票验证 | 通过 | 22:52 只读取证：t260912-01 → `acceptance_walkthrough/running`；t260911-05 `used=1` |
| — | 测试资产变更审查 | 本轮无变更 | `git diff`（仅我上轮报告）与仲裁 `files_changed=[]` 双向确认 |

## 做了什么

1. 核对本轮改动面：`git diff --numstat 145e19f HEAD` → 仅我上轮报告（+143/−0）；`git status` 干净；
   累计 diff 与前几轮逐字节相同（引擎五文件 + 场景 + 2 UT + 六处测试资产）。
2. 读本轮机械记录（0 跑 + ActivityError）与 `out/` 最新产物：只有 22:46–22:47 的 ran=1/2 小跑，
   没有 233 条的整轮报告 → 本轮整轮未完成。
3. 环境现场只读核对（决定我能不能自己跑）：供给台 `sandbar-test-integ` 21350 带 `Up`；26–29 个容器在跑、
   `docker ps` 见 herd/reup/`t26091203c` 等租约 22:51 仍在刷新 → **有套件在并发执行**（我的复跑在忙窗内完成）。
4. **本段独立复跑**：lint / 本票新场景 / 引擎全量 UT（并单跑判红项定性）。
5. 线上 F 只读取证（真 Temporal 7233）。
6. 读仲裁 gen6 结果（`files_changed=[]`、供给面归因、供给硬化建议），与我的观察交叉核对。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen7_checks.log`）

```
python3 integration/lint_tests.py                                   → 0 error / 0 warn (exit 0)
server/engine/.venv/bin/python -B integration/t260913-01/tests/sc_authz_signal_delivery.py
    → SC sc_authz_signal_delivery pass=37 fail=0 (exit=0)；拆台 residue=[]
server/engine/.venv/bin/python -m pytest server/engine/tests -q     → 1 failed, 721 passed in 55.06s
server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260901_25_t03_reap_process_group.py -q
    → 1 passed in 1.30s        ← 判红项单跑绿
现场负载：uptime load average 38.33 / 42.37 / 49.26 ；docker ps -q 计数 26
```

### 本轮机械 0 跑的判读

```
注入结果：{"ran": 0, "passed": 0, "failed": 0, "error": "集成测试 activity 故障：ActivityError: Activity task failed"}
out/ 最新：integration-report-260913-224746.json（ran=2 pass=2）/ …224745（ran=2 pass=1 env=1）/ …224650（ran=1 fail=1）
供给台：sandbar-test-integ-{dsh,temporal} Up 45 分钟+（21350/21351/21352）→ 台本身健康
```
- **判读**：本轮闸的集成测试 activity 自身失败（非产品红、非本票红）；结合上一轮 supply 装配失败，
  这是**套件执行面**的连续故障。仲裁 gen6 的独立归因结论与之同向（其判 tests-fault、指向供给台
  端口竞态与泄漏台回收，并建议开「隔离台/供给面硬化」票）。
- 对本票的含义：**产品面证据不受影响**——引擎与场景自 gen1 起未变，本轮与上一轮的独立复跑均全绿；
  但**闸无法给出机械绿灯**，这是合并裁决时必须由人审显式处理的空档。

### 测试资产变更审查（本轮）

- **本轮零变更**（双向确认）：`git diff --numstat 145e19f HEAD` 仅我上轮报告；仲裁 gen6 `files_changed=[]`。
- 累计六个测试资产文件（capture×3 / doc_face / lib_lifecycle_case / net_table 场景）形态未变；
  前几轮审计结论（断言表达式逐字节未动、`env_fail`→exit 2 ≠ 假绿、档位判据与引擎自报一致、
  `rc=1/64` 仍 FAIL、越界补丁保持回滚态）继续有效。
- 本段本轮复跑：本票新场景 37/0（含负锁矩阵）；上一轮复跑 net-table 19/0 绿。

### F 实票验证（本轮复证 22:52:04）

| 票 | 当前态 | 授权消费留痕 |
|----|--------|--------------|
| t260911-05 | `implement/blocked`（已远离 `arbitrate/blocked`） | `接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough` |
| t260912-01 | **`acceptance_walkthrough/running`** | `受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,…` |

**同一处报告不精确（第三次出现）**：仲裁 gen6 的「遗留与风险」仍写「验收 F（两票真解开）仍待宿主执行：
…两票未解前本票不得算完成」。线上只读证据相反——两票的授权消费留痕自 260913 03:2x 起就在场，
t260912-01 现已推进到验收走查段。**建议把 F 判据写死为「快照 `meta.authorizations[].uses` 非空 + timeline
出现对应推进」并纳入交接模板**，否则每轮报告都会重复这一误判（gen4/gen6/本轮已三次）。

## 并行期 UI 呈现

**不适用**：本票无 UI/泳道渲染代码改动；且本轮 **0 场景执行**，UI/console 类场景本轮未跑，
本轮不产生 UI 面结论（供给侧舞台面问题由仲裁另案归因）。

## 遗留与风险

1. **闸执行面连续故障（最高优先，供宿主/流程处置）**：19:53 一轮 233 条之后，连续两轮 0 跑
   （supply 装配失败 → activity 故障）。产品侧本票自 gen1 起持续全绿、F 已满足，**唯一阻碍是闸跑不起来**。
   建议二选一：①先做「隔离台/供给面硬化」（仲裁 gen6 已建议开票：`up` bind 冲突自动换档/退避、
   ensure 判死条件补「lease state=up 但 container_ids 不存在」、泄漏台回收与端口档位治理）；
   ②人审以现有证据（本票 A–F 多轮独立复跑 + 机械一轮 233 条全绿 + F 实票推进）裁决合并，
   把「空机械轮」显式记录为已知空档而不是默认否决。
2. **F 判据口径**（见上，第三次点名）：建议写死并入模板/KI。
3. **全族未修点**（与仲裁独立结论一致）：`sc_stage_sweep_owner_gone.py:240`、`acc_g_cleanup.py:55`
   仍是「起台子用例 rc==0 直判」（rc=2 env 档被记产品 FAIL 的历史实录）；建议一次补授修全族。
4. **合并面**：main 仍为 `b614392`（t260913-03 声明 `exclude_pools: engine,exclusive`），本 worktree 基于
   `9c102d7` → 合并需先对齐；engine 池被每票段跳过 → 本票新场景与 t260912-03 三条正用例只由每日巡检覆盖
   （巡检票 t260913-02 状态需人审确认）。
5. **合并冲突线索**：并行票 t260912-01 获授权改 `integration/baselines/sc_capture_chat_active.mjs`（`uses` 为证），
   与本票 gen1 同文件；本票累计还改了已闭票 t260911-02 的场景文件与 t260912-02 的两个测试资产文件——
   请在合并记录/交接里逐项点名。
6. **残差面（接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
7. **gen0 两条轻微实现观察仍开放**（引擎自 gen0 起未再改动）：①同秒重复签发同一授权 → 落账判定认不出新条目、
   CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；②畸形值（非数值
   expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring「任何畸形…不炸」不符。
8. **KI-072 现场再证**：本轮 UT 唯一红＝`test_t260901_25_t03_reap_process_group`，单跑 1.30s 绿
   （load 38–49、26 容器忙窗）——与本票 diff 零交集，建议并入 KI-072 的实证清单。
9. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
10. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
    需按 runbook §S0→§S6 再重启一次才能继续用人授权。
11. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查新增五条
    （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台/console 台生命周期不一致四形态；⑦同族起台子用例直判未清；
    ⑧F 判据口径未入模板致仲裁报告三轮误判）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  理由：本票确立/坐实了跨票复用的引擎机制事实，docs/ 无任何承载（全库 grep 无 authorize/人授权/signal
  载荷纪律条目）——①逐票常驻 worker 的内存代码可早于磁盘代码（本票生产实证：重启前授权不落账、
  重启后重签即落账并被消费，唯一变量=worker 进程代码）；②temporalio 解码对未知字段静默丢弃
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
