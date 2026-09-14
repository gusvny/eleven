# t260913-01 验收走查报告（acceptance_walkthrough gen6，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；**本轮机械口径为空（0 跑）**，因此本轮结论
完全建立在本段的独立复跑与只读取证上。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）

- **本轮机械口径 = 0 跑 / 0 过 / 0 败 / 0 环境红**：供给装配失败——共享供给台 `sandbar-test-integ`
  起台撞端口（`Bind for 127.0.0.1:21000 failed: port is already allocated`），`stage-sweep` 先判
  「crit_iii 心跳陈旧 4951s（holder 亡）」→ 拆台与重建同一项目撞在旧容器仍占的 21000 上。**这不是产品红，
  是闸整轮空转**（本轮没有任何场景被跑过）。
- 供给台现已恢复：本段 22:06 实测 `sandbar-test-integ-{dsh,temporal}` `Up`，端口改到 **21350/21351/21352**
  带（旧 21000 带已释放）。
- **本段独立复跑全绿**（供给台重建后）：lint 0/0、本票新场景 `pass=37 fail=0`、本轮被修资产
  `net-table-contract` `pass=19 fail=0`、引擎 UT 722 passed。**A–F 结论未变**（引擎实现自 gen0 起零改动）。
- **本轮零代码 / 零测试资产改动**：新增提交仅我上轮的走查报告；仲裁 gen5 结果文件 `files_changed=[]`
  （其动作全在供给面：停掉孤儿心跳腿）。
- **F 实票验证加强**：t260912-01 已从 `run_integration_tests/running` 推进到 **`acceptance_walkthrough/running`**；
  t260911-05 `implement/blocked`（已远离 `arbitrate/blocked`）；两票 `used=1`。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正腿·受保护路径（送达+消费） | 通过 | 本轮机械空转；本段亲跑新场景 37/0（送达面）；消费面口径沿用 gen0–gen5 真跑（`path_gate_authz_used` 记名）；引擎/场景本轮零改动 |
| B | 正腿·仲裁超限 | 通过 | 同上（`t260912-03-authz-overlimit-accept` 上轮 PASS 93.0s；本轮引擎零改动；F 生产面 t260911-05 即该判定的实票实证） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本段亲跑新场景 `pass=37 fail=0`（含「载荷解析失败」与「非人审等待中」可辨断言） |
| D | 真往返守卫 | 通过（合成口径） | 两腿真信号、均在册（字面读法偏离沿用 review C6 裁定）；本段亲跑 A 腿真信号链 |
| E | 零回归 | 通过 | 引擎三 handler 源码零 diff；本段亲跑 UT 722 passed |
| F | 实票验证 | 通过 | 22:06 只读取证：t260912-01 → `acceptance_walkthrough/running`（继续推进）、t260911-05 `used=1` |
| — | 测试资产变更审查 | 本轮无变更 | `git diff`（仅我上轮报告）与仲裁 `files_changed=[]` 双向确认 |

## 做了什么

1. 核对本轮改动面：`git diff --numstat 49c50be HEAD` → 仅我上轮报告（+170/−0）；`git status` 干净；
   累计 diff 中 `integration/t260912-02/` 只有 lib（+32）与 net_table 场景（+3−2）两文件（sweep 文件仍与 base 零差异）。
2. 读本轮机械记录：`{"ran":0,"passed":0,"failed":0,"error":"supply 装配失败…"}` + 供给台 STAGE_ENV 原文；
   `out/` 最新报告仍为上一轮 19:53 的 233 条（本轮未产生新报告）。
3. 供给面只读诊断 + 恢复确认（`docker ps`：21350 带 Up）。
4. **本段独立复跑**：lint / 本票新场景 / 本轮被修资产场景 / 引擎全量 UT（供给台重建后全部真跑）。
5. 线上 F 只读取证（真 Temporal 7233）。
6. 读仲裁 gen5 结果文件（其 `files_changed=[]` 与供给面处置），与我的观察交叉核对。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen6_checks.log`）

```
python3 integration/lint_tests.py                                   → 0 error / 0 warn (exit 0)
server/engine/.venv/bin/python -B integration/t260913-01/tests/sc_authz_signal_delivery.py
    → SC sc_authz_signal_delivery pass=37 fail=0 (exit=0)   （拆台 residue=[]）
python3 integration/t260912-02/sc_stage_net_table_contract.py       → SUMMARY pass=19 fail=0 env_fail=0 (exit 0)
server/engine/.venv/bin/python -m pytest server/engine/tests -q     → 722 passed in 33.91s
```

### 本轮机械空转的取证与归因

```
机械口径：{"ran": 0, "passed": 0, "failed": 0, "error": "supply 装配失败（need=docker 测试台在位
          （t260904-19…），exit=1）…"}
stage-sweep：判拆 sandbar-test-integ：crit_iii：心跳陈旧 4951s > 阈 600s（holder亡）
重建：#  Network/Volume/Container 全部 Created → Started 后
      Error response from daemon: … Bind for 127.0.0.1:21000 failed: port is already allocated
本段 22:06 实测：sandbar-test-integ-dsh Up 127.0.0.1:21350->3199 ；-temporal Up 21351/21352
```
- **判读**：这是「供给台生命周期不一致」家族的又一形态——旧容器仍在占 21000，而 sweep 依心跳判其
  holder 已亡并拆台，随后 ensure 用同一端口带重建 → 撞端口。**与产品代码、与本票 diff 无关**；
  本轮**没有任何场景得到执行**（闸这一轮对全部 233 条都零覆盖）。
- 供给台现已在 **21350 带**恢复（`Up`），本段随后的真跑全部成功，说明恢复有效。
- 建议（供宿主/闸维护）：撞端口时按「同项目旧容器先 down 再重建」的幂等次序处理；与仲裁 gen5 建议的
  「lease `state=up` 但 `container_ids` 逐个 `docker inspect` 不存在 → 判死重建」同源。

### 测试资产变更审查（本轮）

- **本轮零变更**（双向确认）：`git diff --numstat 49c50be HEAD` 仅我上轮报告；仲裁 gen5 `files_changed=[]`。
- 累计测试资产改动仍是前几轮审计过的 6 个文件（capture×3 / doc_face / lib_lifecycle_case / net_table 场景），
  形态未变；本段本轮复跑其中的 net-table 场景 19/0 绿。
- 与仲裁 gen5 的一致结论（交叉印证）：同族「prepare 型原因记 FAIL」仍有 **2 处**未修
  （`sc_stage_sweep_owner_gone.py:240`、`acc_g_cleanup.py:55`）——我 gen5 报告的静态排查与仲裁的
  独立结论一致；**本轮未再出现 ping-pong**（无人重施未授权的补丁）。建议按授权流程一次补授修全族。

### F 实票验证（本轮复证 22:06:47）

| 票 | 当前态 | 授权消费留痕 |
|----|--------|--------------|
| t260911-05 | `implement/blocked`（已远离 `arbitrate/blocked`） | `接受仲裁判决：verdict=tests-fault（测试集迭代 6 轮超限（上限 5），转人工判读）→ acceptance_walkthrough` |
| t260912-01 | **`acceptance_walkthrough/running`**（较上轮 `run_integration_tests` 又推进一段） | `受保护路径豁免：integration/baselines/sc_capture_chat_active.mjs,…` |

**再次点名同一处报告不精确（第二次）**：仲裁 gen5 的「遗留与风险」仍写「验收 F（两票真解开）仍待宿主执行：
…两票未解前本票不得算完成」。**与线上只读证据不符**——两票的授权消费留痕自 260913 03:2x 起就在场，
t260912-01 现已推进到 `acceptance_walkthrough`。建议：①F 判据统一取「快照 `meta.authorizations[].uses`
+ timeline 推进」，不取 stage 名（两票的 `blocked` 字样出现在**其它**环节，极易误读）；②该口径建议入
KI/交接模板，避免后续每轮报告重复该误判。

## 并行期 UI 呈现

**不适用**：本票无 UI/泳道渲染代码改动；且本轮 **0 场景执行**——所有 console/UI 证据类场景本轮根本没跑，
不存在本轮 UI 面结论（上一轮这些场景为供给台状态所困，本轮供给台已在 21350 带恢复）。

## 遗留与风险

1. **本轮闸空转（最高优先，需供给面处置）**：共享供给台起台撞 21000 端口 → 整轮零覆盖；虽已恢复到
   21350 带，但「旧容器占端口 + sweep 判拆 + 重建撞端口」的次序缺陷仍在，随时可复发（与 console 台
   三种不一致态同族）。建议把「同项目旧容器先 down」做成 ensure 的幂等前置步骤。
2. **全族未修点（与仲裁结论一致）**：`sc_stage_sweep_owner_gone.py:240`、`acc_g_cleanup.py:55` 仍是
   「起台腿 rc==0 直判」（rc=2 env 档被记产品 FAIL 的历史实录）；建议一次补授修全族。
3. **F 判据口径**（见上）：建议以 `uses`+timeline 为准并入模板/KI，消除仲裁报告两轮重复的误判。
4. **合并面**：main 仍为 `b614392`（t260913-03 声明 `exclude_pools: engine,exclusive`），本 worktree 基于
   `9c102d7` → 合并需先对齐；engine 池被每票段跳过 → 本票新场景与 t260912-03 三条正腿只由每日巡检覆盖，
   而巡检票 t260913-02 状态需人审确认（上一轮观察为 `acceptance_walkthrough/blocked`）。
5. **合并冲突线索**：并行票 t260912-01 获授权改 `integration/baselines/sc_capture_chat_active.mjs`（`uses` 为证），
   与本票 gen1 同文件；本票累计还改了已闭票 t260911-02 的场景文件与 t260912-02 的两个测试资产文件——
   请在合并记录/交接里逐项点名。
6. **残差面（接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
7. **gen0 两条轻微实现观察仍开放**（引擎自 gen0 起未再改动）：①同秒重复签发同一授权 → 落账判定认不出新条目、
   CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；②畸形值（非数值
   expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring「任何畸形…不炸」不符。
8. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
9. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
   需按 runbook §S0→§S6 再重启一次才能继续用人授权。
10. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查新增五条
    （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台/console 台生命周期不一致三形态 + 本轮「旧容器占端口→
    重建撞端口」第四形态；⑦同族起台腿直判未清；⑧F 判据口径（uses+timeline）未入模板致仲裁报告两轮误判）。

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
