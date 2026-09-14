# t260913-01 验收走查报告（acceptance_walkthrough gen2，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 213 过 / 0 败 / 20 环境红）
仅作输入，关键腿自己重跑/自己复现。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- 验收 **A–F 全部满足**，其中 F（实票解扣）在本轮再次只读取证仍成立（两票都已按各自授权推进、`uses≥1`）。
- 本轮唯一新增改动是**仲裁段对测试资产的修复**（`integration/t260911-02/sc_inspection_doc_face.py`，
  另一票的潜伏假红），本段逐处核实为**真 bug 修复 + 同源对齐**，无断言语义放宽（详见专节）。
- 引擎实现（gen0）+ gen1 三处 capture 基线修正**本轮零改动**，gen1 的独立复跑结论继续有效；
  本段另复跑：lint 0/0、新场景 37/0、doc_face 修复后 EXIT=0。
- 机械口径 20 条环境红**全部为基础设施面**（共享供给台租约僵死 18 条 + 端口抢占 1 条 + 内层 pytest
  负载敏感首轮假红 1 条），与本票写集/依赖零交集；本票四条在册场景机械口径**全部 PASS**。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正腿·受保护路径（送达+消费） | 通过 | 机械口径 PASS（1.9s 消费面 / 15.1s 送达面）；gen1 独立复跑 37/0 双半 |
| B | 正腿·仲裁超限 | 通过 | 机械口径 `t260912-03-authz-overlimit-accept` PASS 86.5s；gen1 独立复跑 30/0 |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 机械口径 PASS + 本轮独立复跑新场景 37/0（含「载荷解析失败」与「非人审等待中」可辨断言） |
| D | 真往返守卫 | 通过（合成口径） | 两腿真信号、均在册；字面读法偏离沿用 review C6 裁定（gen1 已标注） |
| E | 零回归 | 通过 | 三个其它 handler 源码零 diff；普通签字逐字节锁 + 103 UT 绿；engine UT 722 passed（gen1 亲跑，本轮引擎零改动） |
| F | 实票验证 | 通过 | 13:10 只读取证：t260911-05 `merge_check/blocked`（已离 arbitrate）+ `uses` 含判决原文；t260912-01 `run_integration_tests/running` + `uses` 含受保护路径豁免明细 |
| — | 本轮测试资产变更审查 | 通过 | doc_face 潜伏 bug 修复：机制独立复现 + 同族三处同源自证 + 修后独立复跑绿 |

## 做了什么

1. 复核本轮改动面：`git log` / `git diff --numstat 9c102d7 HEAD` —— 新增一次提交 `62fada7`
   （arbitrate gen1：`integration/t260911-02/sc_inspection_doc_face.py` +5/−2，另含我上轮报告落盘）；
   **引擎五文件（shared/dev_lane/client/worker + ticket.py）零改动**，本票 UT 文件零改动。
2. 审查该测试资产修复：读 diff、独立复现缺陷机制（字符串推导，零时空成本）、核对「同族全量排查」
   自称（三处同族逐处亲核）、独立复跑该场景确认修后绿。
3. 读本轮机械报告原件 `out/integration-report-260913-124150.json`（233/213/0/20），逐条归类 20 条非绿。
4. 复跑本票关键腿（lint / 新场景）+ 线上 F 只读取证（真 Temporal 7233，query 零副作用）。

## 怎么验证的（证据引用）

### 本轮独立复跑（原文 `.sandbar/evidence/gen2_checks.log`）

```
python3 integration/lint_tests.py                                   → 0 error / 0 warn (exit 0)
server/engine/.venv/bin/python integration/t260911-02/sc_inspection_doc_face.py → EXIT=0
    PASS: 腿a 脏树命中 ok(findings=10); 腿b 全绿树零发现+heartbeat ok; 腿c 坏 index 降级点名 ok(findings=3);
          腿d 真仓观测 ok(findings=140); 腿e 真跑报告 ok(键齐)
sc_authz_signal_delivery.py                                         → pass=37 fail=0 (exit 0)
```

### 机械口径（本轮，报告原件）

```
ran=233 pass=213 fail=0 env_fail=20 wall=1434s generated=2026-09-13T12:41:50
本票四条全 PASS：t260912-03-authz-protected-path 1.9 / -authz-cli-queryable 12.9 /
                t260913-01-authz-signal-delivery 15.1 / -authz-overlimit-accept 86.5
上轮四条 FAIL 现状：t260911-02-doc-face PASS 21.3 ；t260912-02-sweep-owner-gone PASS 40.7 ；
                    t260912-02-net-table-contract PASS 20.7 ；ticket-session-restore → ENV_FAIL（共享台租约僵死，见下）
上上轮三条 blocker：capture-chat-active PASS 37.9 ；capture-chat-e2e PASS 38.9 （gen1 修法真跑见效，非改判）
```

### 20 条环境红归类（本票零交集）

| 条数 | 现象 | 归类 |
|---|---|---|
| 18 | `[ENV_FAIL] stage-console — STAGE_ENV: 供给台 stage-console-bcaea9b9 租约过期但 holder pid=65302 仍在（心跳停更）——疑似 pid 复用或 holder 僵死` | 共享供给台僵死租约（fail-closed 拒跑，正确行为）；受影响的是所有 console/browser/main 系场景（ticket-session-restore、ticket-evidence-images、t260903-07-chat-project-tag、t260904-05-*、multi-tab、lane-parallel-dom…） |
| 1 | `t260904-19-stage-docker`：共享锁根内有新鲜外来工程状态（多泳道起台窗内不作产品判定） | 跨泳道起台争抢 |
| 1 | `t260904-02-ticket-start-anchor`：`Bind for 127.0.0.1:21161 failed: port is already allocated` | 端口抢占（环境） |
| — | `scenario-guard-pipeline-landed` 内层 pytest 首轮 1 failed（`test_t260901_25_t03_reap_process_group`）/721 passed | KI-072 负载敏感假红（该条单跑绿，前两轮已多次复现） |

补充事实（非推测）：本段早前 `docker ps` 已见 5 个 `stage-console-*` 栈（20–50 分钟龄）来自其它泳道，
`stage-sweep` 对其中两个判「C4b 活台 fail-closed 不拆」——共享台位面本就是脏的，与 18 条 ENV_FAIL 同源。
**结论：20 条环境红无一落在本票写集、依赖面或本票场景上**；本票四条场景在同一轮里全部真跑 PASS。

### F 实票验证（本轮复证 13:10:36）

| 票 | 现状 | 授权消费留痕 |
|----|------|--------------|
| t260911-05 | `merge_check/blocked`（已离开 arbitrate 超限 blocked；当前红是泳道内 verify_lane + 越界写 `.sandbox_tmp_gen9.md`，与授权通道无关） | `接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough`（stage=arbitrate） |
| t260912-01 | `run_integration_tests/running`（已离开 design_integration_tests blocked） | `受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,sc_ticket_evidence_images.mjs,sc_ticket_session_restore.mjs`（stage=integ_join） |

gen1 已记录的生产根因实证（03:19 授权未被消费 vs 03:20:56 重启后重签被消费，唯一变量=worker 进程代码）
依然成立，本轮无反复。

## 测试资产变更审查（本段铁律小节）

### 本轮变更：`integration/t260911-02/sc_inspection_doc_face.py`（+5/−2）

- **改动内容**：声明模板键 `%(pid)s`（填未补零原值 `PID`）→ `%(stamp)s`（填 `STAMP="%05d" % PID`），
  并加注释说明同源要求。**断言面（腿 a–e 的判定表达式）一行未动**。
- **缺陷机制独立复现**（本段亲跑，纯推导）：
  ```
  PID=4619   old: decl=docs-sync-4619  req=docs-sync-04619  相等=False   ← 假红
             new: decl=docs-sync-04619 相等=True
  PID=12345  old: decl=docs-sync-12345 req=docs-sync-12345  相等=True    ← 碰巧绿（解释「PID≥10000 才绿」）
  ```
  与机械原文 `实例 'docs-sync-04619' 未在声明中（在册：docs-sync-4619）` 逐字吻合 → **是测试自身的
  声明/请求不同源**，引擎拒收正确（引擎无过错）。
- **同族全量排查自称核对**（本段 grep 亲核，非采信）：`t260905-03/sc_inspection_period_journey.py`
  （声明 `docs-sync-%05d` 填 `_STAMP`，请求 `"docs-sync-%05d" % _STAMP` = 同源 ✓）、
  `t260911-02/sc_inspection_trigger_kinds.py`（`STAMP="%05d"%PID` + `%(stamp)s` + `% {"stamp": STAMP}` = 同源 ✓）、
  `t260911-02/sc_inspection_doc_face.py`（修后同源 ✓）→ **doc_face 确为唯一不一致点**，排查结论属实。
- **修后独立复跑**：`EXIT=0`，腿 a–e 全 ok（findings=10 / 零发现+heartbeat / 坏 index 降级 3 / 真仓 140 / 报告键齐）。
- **授权与写集**：文件在 `integration/`（本票写集）内；该场景属**已闭票 t260911-02**（09-11 merged）
  的测试资产 → 交叉改动需在合并记录中留痕（见遗留 1）；无其它泳道并发改它的风险（该票已闭）。

### gen1 三文件（capture 基线）本轮复核

`git diff --numstat` 显示 gen1 后三者**零新增改动**；gen1 审计结论（断言表达式逐字节未动、
`env_fail` → exit 2 ≠ 假绿、README/失败分类协议成文依据、爆炸半径=两条 capture 基线）继续有效。
本轮机械口径给出**最强佐证**：`capture-chat-active` 37.9s **PASS**、`capture-chat-e2e` 38.9s **PASS**
——修好的工具链解析让它们**真跑通过**，不是把红改判成绿（若只是改判，二者会停在 ENV_FAIL）。

### 总判定

两轮累计的 4 个测试资产文件（gen1 三 + 本轮一）均为**契约精确化/真 bug 修复**，未发现绿灯捷径或
断言弱化；无 `assert True`、无期望值删除、无「skip/exit 0 假绿」。**未触发 status=failed。**

## 并行期 UI 呈现

**不适用**（结论不变）：本票无 UI/泳道渲染代码改动（引擎 authz 四文件 + integration 测试资产）。
补一句边界说明：本轮 20 条环境红里 18 条恰好是**供给台（console 台）租约僵死**导致 console 系场景
无法起跑——那是基础设施面（台位治理），不是本票 UI 面，也不是本票能改的面。

## 遗留与风险

1. **交叉改动留痕**：本票提交改了已闭票 `t260911-02` 的场景文件（gate 拦红驱动，arbitrate tests-fault
   裁定下修复）。合并记录/交接里请点名，避免后人追「谁动了已闭票的资产」时失去线索。
2. **合并面**：main 已前进到 `b614392`（t260913-03 声明落 main），本 worktree 基于 `9c102d7` →
   合并需先对齐 main。该声明 `exclude_pools: engine,exclusive` 使**每票集测段跳过 engine 池**，
   本票新场景与 t260912-03 三条正腿都在该池 → 只靠**每日巡检**覆盖；而巡检票 **t260913-02 当前
   blocked**（acceptance_walkthrough/blocked）。建议人审裁定：engine 池（含引擎源码被测面）是否应
   随写集命中 `server/engine/` 强制全跑——本段只报观察，不改别票声明。
3. **合并冲突风险（线索）**：并行票 t260912-01 获授权改 `integration/baselines/sc_capture_chat_active.mjs`
   （其 `uses` 明细为证），与本票 gen1 同文件 → 两票语义叠加需人工确认。
4. **残差面（本段接受，建议另开断言）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进
   not-checked；若要保留这条产品信号，应显式断言「committed bundle == 源码重建产物」。
5. **gen0 两条轻微实现观察仍开放**（引擎本轮未动）：①同秒重复签发同一授权 → `evaluate_authz_landing`
   认不出新条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；
   ②畸形值（非数值 expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring
   「任何畸形…不炸」不符（结构畸形已容错、值畸形未容错）。均非阻塞，建议随 KI 候选登记。
6. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
7. **运维面（设计固有）**：合并后 CLI 对任何未含 `sign_face` 的 worker 拒发 authorize（fail-closed）
   → 现网两票 worker（main `9c102d7` 代码）需按 runbook §S0→§S6 再重启一次才能继续用人授权。
8. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条（①逐票常驻 worker
   陈旧=全信号面结构性风险；②signal 载荷演进纪律成文；③毒载荷宽松解码）+ 本报告新增两条
   （④回执机读键无断言锁类覆盖缺口；⑤上表第 5 条两条轻微实现缺陷，可与 ③ 合登）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  理由：本票确立/坐实了跨票复用的引擎机制事实，docs/ 无任何承载（全库 grep 无 authorize/人授权/信号载荷
  纪律条目）——①逐票常驻 worker 的内存代码可早于磁盘代码（本票生产实证：03:19 授权未被消费 vs 03:21
  重启后重签被消费，唯一变量=worker 进程代码）；②temporalio 解码对未知字段静默丢弃（DefaultPayloadConverter
  + 旧形类独立复现）；③故载荷演进必须走「标量 marker 可见化 + sign_face 指纹先验 + 三态回执」三步纪律，
  新字段上线=必须重启在途票 worker；④指纹严格相等 ⇒ 加字段即拒发未重启 worker（运维含义）。`docs/` 不在
  本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 两条 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义与归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现（普通签字零改动、授权通道为
  新增例外面、fail-closed 不放宽、prepare 型原因归 not-checked 且带 reason+evidence）与上述成文主张一致，
  未发现被推翻的 claim → 不产生 pending-doc-sync 债条目。
