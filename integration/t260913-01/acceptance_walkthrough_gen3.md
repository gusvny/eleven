# t260913-01 验收走查报告（acceptance_walkthrough gen3，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；机械口径（233 跑 / 214 过 / 0 败 / 19 环境红）
仅作输入，关键子用例自己重跑。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **本轮零代码、零测试资产改动**：`git log` 新增一次提交 `00f17f0`，内容仅我上轮的走查报告
  （`acceptance_walkthrough_gen2.md`，+166/−0）；仲裁 gen2 结果文件自报 `files_changed=[]`，
  其动作全在**供给面（docker 容器清理）**，不触碰任何断言/覆盖子用例。因此前两轮的验收结论与
  测试资产审查结论继续有效，本轮只做复证 + 供给面新发现。
- **A–F 仍全部满足**：机械口径本票四条在册场景**全 PASS**（15.8s / 88.9s / 13.2s / 1.9s）；
  本段另亲跑 lint 0/0、新场景 37/0、引擎 UT 722 passed；F 两票 `uses=1`（授权消费留痕仍在）。
- **19 条环境红与本票零交集**（17 条为同一死供给台连坐、1 条跨泳道锁根、1 条 docker 网络创建失败）。
- **本段新发现（供给面，需人工处置）**：上一轮仲裁自称已拆的 `stage-console-bcaea9b9` 台**实际未拆**——
  容器仍 `Up 4 hours`，且下一轮（16:20）机械跑仍报 17 条同源环境红。证据见下，处置建议见遗留 1。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正用例·受保护路径（送达+消费） | 通过 | 机械口径：送达面 `t260913-01-authz-signal-delivery` PASS 15.8s；消费面 `t260912-03-authz-protected-path` PASS 1.9s |
| B | 正用例·仲裁超限 | 通过 | 机械口径 `t260912-03-authz-overlimit-accept` PASS 88.9s（判决原文 + `uses≥1` + 推进） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本段亲跑新场景 `pass=37 fail=0 exit=0`（含「载荷解析失败」与「非人审等待中」可辨断言）；机械口径 PASS |
| D | 真往返守卫 | 通过（合成口径） | 两子用例真信号、均在册（字面读法偏离沿用 review C6 裁定，gen1/gen2 已标注） |
| E | 零回归 | 通过 | 引擎三 handler 源码零 diff（累计 diff 未变）；本段亲跑 UT 722 passed；`t260912-03-authz-cli-queryable` PASS 13.2s |
| F | 实票验证 | 通过 | 16:47 只读取证：两票各 `used=1`；t260912-01 现 `run_integration_tests/running`，t260911-05 现 `implement/blocked`（历史推进事实由授权消费留痕与时间线锁定，非当前态） |
| — | 测试资产变更审查 | 本轮无变更 | `git diff` 与仲裁 `files_changed=[]` 双向确认为零；累计四文件已在前两轮逐处审计 |

## 做了什么

1. 核对本轮改动面：`git diff --numstat 62fada7 HEAD` → 仅我上轮报告一份；`git diff --numstat 9c102d7 HEAD`
   累计面与前一轮**逐字节相同**（引擎五文件、场景、UT、四个测试资产文件都无新增改动）。
2. 读本轮机械报告原件 `out/integration-report-260913-162026.json`（233/214/0/19），逐条归类 19 条非绿。
3. 本段亲跑：lint + 本票新场景（真 docker 台真信号）+ 引擎全量 UT。
4. 线上 F 只读取证（真 Temporal 7233，query 零副作用）。
5. 供给面只读核查（`docker ps` + 租约日志），核对上一轮仲裁的「已清理」自称是否在环境中兑现。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen3_checks.log`）

```
python3 integration/lint_tests.py                                   → 0 error / 0 warn (exit 0)
server/engine/.venv/bin/python -B integration/t260913-01/tests/sc_authz_signal_delivery.py → pass=37 fail=0 (exit 0)
server/engine/.venv/bin/python -m pytest server/engine/tests -q     → 722 passed in 27.76s
```

### 机械口径（本轮原件 `out/integration-report-260913-162026.json`）

```
ran=233 pass=214 fail=0 env_fail=19 wall_s=1441.3 generated=2026-09-13T16:20:26
本票四条全 PASS：t260913-01-authz-signal-delivery 15.8 / t260912-03-authz-overlimit-accept 88.9 /
                -authz-cli-queryable 13.2 / -authz-protected-path 1.9
gen1 修好的 capture 双胞胎续绿：capture-chat-active 38.2 / capture-chat-e2e 38.4
上轮四条翻转项：t260911-02-doc-face PASS 21.3 ；t260912-02-sweep-owner-gone PASS 33.8 ；
                t260912-02-net-table-contract PASS 16.1 ；t260904-02-ticket-start-anchor PASS 81.3（端口耗尽已解）
19 条环境红归类：
  17 × [ENV_FAIL] stage-console — STAGE_ENV: 供给台 stage-console-bcaea9b9 有无主容器在跑（租约已死/缺失）
       ——--keep 语义不拆在跑台，人工核查后 down
   1 × t260904-19-stage-docker：共享锁根内有新鲜外来工程状态（t26090801b-33489，120s 内起台活动 = 别泳道在跑）
   1 × t260905-02-ticket-worker-watch-exit：docker `network t26090502-watch-88051_default not found`（起台瞬态）
→ 无一条落在本票写集、依赖面或本票场景上
```

### 供给面新发现：自称已拆的死供给台实际仍在（只读取证）

```
$ docker ps | grep -i bcaea9b9
stage-console-bcaea9b9-dsh        Up 4 hours   127.0.0.1:21050->3199/tcp
stage-console-bcaea9b9-temporal   Up 4 hours   127.0.0.1:21051->7233/tcp, 127.0.0.1:21052->8233/tcp
$ cat ~/.sandbar/test-stages/hold-stage-console-bcaea9b9.log
STAGE_HOLD_CAP: hold 超过最大持有期 14400s 自退——台留给租约过期回收或人工 down（…可调小
SANDBAR_MAX_HOLD_S 或显式 down）
$ ls ~/.sandbar/test-stages/ | grep bcaea9b9
ensure-stage-console-bcaea9b9.lock（08:23，空）｜ hold-stage-console-bcaea9b9.log（12:23）
```

- **事实**：该台持有超过 14400s 上限后 holder **自退但未清台** → 租约记录消失（本轮 tail 的措辞由
  上轮「租约过期但 holder pid 仍在」变为「有无主容器在跑（租约已死/缺失）」），而容器仍在跑；
  `ensure` 对「活容器 + 无有效租约」**fail-closed 拒跑** → **一台死亡连坐 17 个 console 依赖场景**。
- **与上一轮仲裁自称的关系（只陈述观测）**：仲裁 gen2 报告称已 `down --project stage-console-bcaea9b9`
  且 `residue: []`、并复跑三条代表场景绿；但滞后于该动作的 16:20 全量跑仍 17 条同源红，且本段
  `docker ps` 实测容器 `Up 4 hours`。**净效果=该 17 条环境红未解除**（清理只清掉了租约/锁记录，
  未停容器）。
- **处置边界（本段未动手，理由写明）**：该台是**共享供给面**（非本票泳道，且容器可能仍在被并行泳道
  使用；提示语明确写「人工核查后 down」、`--keep` 语义「不拆在跑台」）。agent 不硬拆——本段只给证据
  与命令：`python3 integration/stage_docker.py down --project stage-console-bcaea9b9`
  （若引擎 CLI 无效，再 `docker compose -p stage-console-bcaea9b9 down -v`），由人/宿主核查后执行。

### F 实票验证（本轮复证 16:47:23）

| 票 | 当前态 | 授权消费留痕（历史事实，不随当前态改变） |
|----|--------|------------------------------------------|
| t260911-05 | `implement/blocked`（已远离 `arbitrate/blocked`；现红与授权通道无关） | `接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough`（stage=arbitrate） |
| t260912-01 | `run_integration_tests/running`（已离开 `design_integration_tests/blocked`） | `受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,sc_ticket_evidence_images.mjs,sc_ticket_session_restore.mjs`（stage=integ_join） |

gen1 记录的生产根因实证（03:19 授权未被消费 vs 03:20:56 重启后重签被消费，唯一变量=worker 进程代码）
依旧成立；两票 `used=1` 无反复。**F 判据（两票至少一张实际被解开）持续满足。**

## 测试资产变更审查（本轮）

- **本轮零变更**（双向确认）：`git diff --numstat 62fada7 HEAD` 仅我上轮报告；仲裁 gen2
  `files_changed=[]`。
- 累计四个测试资产文件（gen1 三处 capture 基线 + gen2 一处 doc_face）**保持前两轮审计后的形态**，
  本轮无新改动可审；且机械口径给出**正向佐证**：capture 双胞胎真跑 PASS（38.2/38.4s）、doc_face PASS（21.3s）
  ——修复是让它们**真跑通过**，不是把红改判成绿。
- 前两轮的审查结论（断言表达式逐字节未动、`env_fail`→exit 2 ≠ 假绿、同源对齐修的是测试自身 bug、
  授权 scope 覆盖写入面）继续有效，无新增弱化面。

## 并行期 UI 呈现

**不适用**（结论不变，边界说明补强）：本票无 UI/泳道渲染代码改动。值得写清的是：本轮 19 条环境红里
**17 条正是 console 供给台（UI 证据台的宿主）死亡连坐**——那是台位/基础设施面，不是本票 UI 面；
UI 证据链本身在本轮机械口径里由 capture 双胞胎真跑 PASS 证明无回归。

## 遗留与风险

1. **【需人工/宿主处置·本段新发现】** `stage-console-bcaea9b9` 死供给台容器仍在跑（`Up 4 hours`，
   21050–21052），持续连坐 17 条 console 依赖环境红；上一轮的清理未真正停容器。建议人工核查后
   `down`（命令见上）。agent 不越权硬拆（共享供给面 + `--keep` 语义 + 可能被并行泳道使用）。
   建议同时登记 KI 候选：**「供给台 hold 到期自退不清台 → 租约死亡+孤儿容器 → 全部 console 依赖场景
   fail-closed 连坐」**（本轮形态：一台连坐 17 条；属系统性供给面缺陷，非本票面）。
2. **合并面**：main 仍为 `b614392`（t260913-03 声明 `exclude_pools: engine,exclusive`），本 worktree
   基于 `9c102d7` → 合并需先对齐。该声明使每票集测段跳过 engine 池，本票新场景与 t260912-03 三条
   正用例只由**每日巡检**覆盖，而巡检票 **t260913-02 当前 `acceptance_walkthrough/blocked`**；建议人审
   裁定「写集命中 `server/engine/` 时是否强制全跑」——本段只报观察。
3. **合并冲突线索**：并行票 t260912-01 获授权改 `integration/baselines/sc_capture_chat_active.mjs`
   （其 `uses` 明细为证），与本票 gen1 同文件；另本票 gen2 改了已闭票 t260911-02 的场景文件——
   两处交叉改动请在合并记录/交接里点名留痕。
4. **残差面（接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该
   产品信号，应显式断言「committed bundle == 源码重建产物」。
5. **gen0 两条轻微实现观察仍开放**（引擎自 gen0 起未再改动）：①同秒重复签发同一授权 → 落账判定认不出
   新条目、CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；
   ②畸形值（非数值 expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring
   「任何畸形…不炸」不符。均非阻塞，建议随 KI 候选登记。
6. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
7. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→
   现网 worker 需按 runbook §S0→§S6 再重启一次才能继续用人授权。
8. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条（①逐票常驻 worker
   陈旧=全信号面结构性风险；②signal 载荷演进纪律成文；③毒载荷宽松解码）+ 走查新增三条
   （④回执机读键无断言锁类覆盖缺口；⑤两条轻微实现缺陷，可与 ③ 合登；⑥供给台 hold 到期不清台连坐）。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  理由：本票确立/坐实了跨票复用的引擎机制事实，docs/ 无任何承载（全库 grep 无 authorize/人授权/
  signal 载荷纪律条目）——①逐票常驻 worker 的内存代码可早于磁盘代码（本票生产实证：重启前授权不落账、
  重启后重签即落账，唯一变量=worker 进程代码）；②temporalio 解码对未知字段静默丢弃（本段用
  DefaultPayloadConverter + 旧形类独立复现）；③故载荷演进必须走「标量 marker 可见化 + sign_face
  指纹先验 + 三态回执(landed/refused/unconfirmed)」三步纪律，新字段上线=必须重启在途票 worker；
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
