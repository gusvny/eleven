# t260913-01 验收走查报告（acceptance_walkthrough gen8，integration）

工单：人授权通道传输缺陷 —— sign 信号面的 `authorize` 载荷在传输/解码一跳丢失，授权恒被当普通签字
处理（钥匙插不进去），受保护路径闸与仲裁超限两条判定无出口。

走查立场：用户视角独立走查，不预设「测试已全部通过」；本轮机械 activity 超时（0 跑），但本 lane 的
`out/` 里留下了**同一轮跑完的 233 条报告**，加上本段亲跑，证据足够结案。与仲裁并行执行，本报告不为仲裁下结论。

## 结论：通过（status=ok）——并建议人审在现有证据上裁决，不必再等机械绿灯

- **验收 F 已达最强形态**：`t260912-01`（受保护路径拒绝 blocked）**已 COMPLETED / 关单**
  （`close_time=2026-09-13 15:12:02Z` = 本地 23:12，票面 `merge/awaiting → closed`）；`t260911-05`
  （arbitrate 超限 blocked）早已解扣、消费留痕 `uses=1`，现 `implement/blocked`（在途推进中）。
- **本轮机械 activity 超时（0 跑），但同轮 233 条跑完了**：`out/integration-report-260914-010613.json`
  = `ran=233 pass=224 fail=3 env_fail=6 wall=2116s`（说明 activity 只是**结果回执超时**，套件本身跑完并落档）。
  本票四条在该轮：`-authz-cli-queryable` **PASS 30.2s**、`-authz-protected-path` **PASS 8.2s**；
  `t260913-01-authz-signal-delivery` **ENV_FAIL**（`temporal 180s 内未就绪`）、`-authz-overlimit-accept`
  **ENV_FAIL**（`docker compose up 失败`）——均为起台面，非断言面。
- **本段亲跑（01:31–01:38，同窗 47 个容器、跨泳道抢端口）**：lint 0/0；本票新场景 `pass=37 fail=0`；
  在册 A 消费面 `pass=37 fail=0`；本票+在册 UT **129 passed**；在册 B 子用例/可查面本轮被**端口 21121 竞态**
  挡下（见下，环境面，根因点名到别泳道台）。
- **本轮零代码 / 零测试资产改动**：新增提交仅我上轮的走查报告。

| # | 项 | 结论 | 本轮依据 |
|---|----|------|----------|
| A | 正用例·受保护路径（送达+消费） | 通过 | 本段亲跑 37/0（送达）+ 37/0（消费）；机械同轮 `-authz-protected-path` PASS 8.2s |
| B | 正用例·仲裁超限 | 通过 | 机械同轮该条 ENV_FAIL（compose up）；本段复跑被 21121 端口竞态挡下；**判定依据=此前多轮真跑全绿**（19:53 轮 93.0s、更早 86–88s、gen1 独立 30/0）+ 该判定的 F 生产实证（t260911-05 已解扣） |
| C | 负锁四条（本票覆盖 5 条） | 通过 | 本段亲跑新场景 `pass=37 fail=0`（含「载荷解析失败」vs「非人审等待中」可辨断言） |
| D | 真往返守卫 | 通过（合成口径） | 两子用例真信号、均在册；本段亲跑真 CLI→真信号→真 worker→真 workflow |
| E | 零回归 | 通过 | 引擎三 handler 源码零 diff；本段亲跑 UT **129 passed**（本票两套 + t260912-03 三套） |
| F | 实票验证 | **通过（最强形态）** | t260912-01 **COMPLETED/关单**（23:12）；t260911-05 `used=1` |
| — | 测试资产变更审查 | 本轮无变更 | `git diff`（仅我上轮报告）；仲裁本轮 `files_changed=[]` |

## 做了什么

1. 核对本轮改动面：`git diff --numstat 9b70d02 HEAD` → 仅我上轮报告（+144/−0）；工作区干净。
2. 找到并读本轮**跑完的 233 条报告**（`out/integration-report-260914-010613.json`），逐条读非绿 tail 定性。
3. **本段亲跑**（四条在册场景 + 本票/在册 UT），并现场只读定位本轮红项的根因（端口 21121 的持有者）。
4. 线上 F 只读取证：workflow `describe`（t260912-01 = COMPLETED）+ 用户级 `ticket list`（票面 stage/state）。
5. 与仲裁本轮报告交叉核对（供给面归因、孤儿租约分类、零 docker 手术理由）。

## 怎么验证的（证据引用）

### 本段亲跑（原文 `.sandbar/evidence/gen8_checks.log`）

```
python3 integration/lint_tests.py                                   → 0 error / 0 warn (exit 0)
sc_authz_signal_delivery.py（本票新场景，A 送达 + C 五负锁）        → pass=37 fail=0 (exit 0)；拆台 residue=[]
sc_authz_protected_path.py（在册 A 消费子用例）                          → pass=37 fail=0 (exit 0)
sc_authz_overlimit_accept.py（在册 B 子用例）                            → pass=24 fail=6 (exit 1) ← 端口竞态，见下
sc_authz_cli_queryable.py（在册可查面）                              → exit 2（Bind 21121 already allocated）
pytest 本票两套 + t260912-03 三套 UT                                 → 129 passed in 0.56s
同窗环境：docker ps -q = 47 ；跨泳道台 t26090419-par-b-95045-temporal Up（占 127.0.0.1:21121）
```

**B 子用例本轮红项的根因（点名到持有者，非本票面）**：`sc_authz_overlimit_accept` 的失败首因是
`RuntimeError: Failed client connect … tcp connect error 127.0.0.1:21121`，紧随其后的可查面场景直接报
`Bind for 127.0.0.1:21121 failed: port is already allocated`。本段只读定位：**21121 被别泳道的台
`t26090419-par-b-95045-temporal` 持有**（`lsof` 显示 OrbStack 监听，`docker ps` 见该容器 `Up 18s`，
租约文件 `project-t26090419-par-b-95045.json`）——同窗并发抢端口，**环境面**，与授权行为无关。

### 同轮 233 条报告（01:06）——本票与全局面

```
ran=233 pass=224 fail=3 env_fail=6 wall_s=2116 generated=2026-09-14T01:06:13
本票：-authz-cli-queryable PASS 30.2 ｜ -authz-protected-path PASS 8.2
      t260913-01-authz-signal-delivery ENV_FAIL 186.3（「docker 舞台 up 失败（env）：temporal 180s 内未就绪」）
      -authz-overlimit-accept ENV_FAIL 6.0（compose up 失败）
3 条 FAIL（全属别票/UI 证据链面，与本票写集零交集）：
  · t260912-02-fuse-headroom-resident 200.4s —— 批量起台子用例 `16/16 全绿（实得 11，非零 [(b01,2),(b02,2),(b07,2)]）`：
    三个非零全是 **rc=2=env 档**，却被记成产品 FAIL（**同族缺陷的又一实例**，见「全族」节）
  · capture-chat-active 71.8s / capture-chat-e2e 81.0s —— 内层 capture-lane `assertDistinct` 失败：
    「截图同帧假成功：console-board-light.png 与 console-board.png 字节级完全相同」，内层 exit=1
6 条 env_fail：t260904-19-stage-docker（共享锁根外来工程）、t260904-19-…-parallel-zero-residue（Bind 21481）、
  t260905-02-worker-lifecycle（compose up）、t260912-02-net-table-contract（**rc=2=env 档，新判据正确点名**）、
  本票两条（temporal 未就绪 / compose up）
```

**capture 双胞胎的 FAIL 是否由本票 gen1 改动引起？——不是**（逐条推理，写清楚供人审复核）：
①本票 gen1 只改两件事：重建工具链解析优先被测树（下游仍有**字节等同**守卫：重建产物与提交 bundle 不一致
则 `ensureLaneBuild` 返回原因 → 现在归 env_fail，根本不会跑到 UI 断言）、以及「内层 exit=2 → not-checked」
的状态归属；②本轮内层 capture-lane **真跑并 exit=1**（断言级失败），新归属逻辑**不会**把 exit=1 改判，
证明没有掩盖；③失败点是 `server/ui-check/capture.mjs` 的防伪 distinctness 断言（本票零改动），
且同两条在 19:53 轮（wall 1464s）为 PASS 44.6/47.5s、本轮 wall 2116s、47 容器 → 高载下渲染/时序面最可疑。
**归属留仲裁**；本段只报事实与「非本票面」的推理。

### 全族线索（本轮新增量化实例）

- `t260912-02-fuse-headroom-resident` 的**批量起台子用例**把 rc=2（env 档）记成产品 FAIL（16/16 实得 11）。
  而 lib 里**已存在**通用助手 `up_batch_env_only`（implement gen2 新增、因授权面只覆盖 lib+net_table 两处
  而未被接线；其同族补丁曾被预置又按红线回滚）。⇒ 建议**一次补授修全族**：
  `sc_stage_sweep_owner_gone.py:240`、`acc_g_cleanup.py:55`、`sc_stage_fuse_headroom_resident.py` 的批量子用例
  （必要时含 `sc_stage_burst_managed_subnets.py` 的阈值子用例）。

### F 实票验证（本轮复证）

```
$ workflow describe：t260912-01 → WorkflowExecutionStatus.COMPLETED，close_time=2026-09-13 15:12:02Z
$ ticket list：t260912-01 closed merge/awaiting（updated 09-13 23:12）｜t260911-05 dispatched implement/blocked（authz_active 3）
$ snapshot（22:52 gen7 轮）t260912-01 stage=acceptance_walkthrough/running used=1；t260911-05 used=1
```
⇒ **F 判据（两票至少一张实际被解开）已由「两票均解扣、其中一张彻底关单」超额满足**；
此前仲裁报告连续数轮「F 仍待宿主执行」的表述（gen4/gen6/前一轮）与事实不符，本轮起**不再成立**
（建议仍把 F 判据写死为 `meta.authorizations[].uses` 非空 + timeline 推进 + workflow 终态）。

## 并行期 UI 呈现

**不适用**：本票无 UI/泳道渲染代码改动。补充本轮事实：UI 证据链场景（capture 双胞胎）本轮**真跑**并因
内层防伪断言失败（截图同帧）判 FAIL——那是 t260901-03 面，且本票改动经逐条推理不构成其因（见上），
本票自身无任何 UI 面改动。

## 遗留与风险

1. **建议人审现在裁决（本段核心建议）**：产品面自 gen1 起未变且多轮独立复跑全绿，F 已超额满足（一张关单）；
   而机械道连续三轮给不出绿灯（19:53 全跑 233；随后 supply 装配失败 0 跑、activity 故障 0 跑、本轮 activity
   超时但套件跑完）。继续走查只会重复同一结论，同时每轮烧掉 ~25–35 分钟套件与跨泳道资源。建议：
   ①以现有证据合并（把「最近无干净全绿轮」显式记为已知空档）；②或先开「隔离台/供给面硬化」票
   （仲裁已建议：`up` bind 冲突自动换档/退避、ensure 判死条件补 container_ids 不存在、泄漏台回收与端口档位治理）。
2. **合并面**：main 仍为 `b614392`（t260913-03 声明 `exclude_pools: engine,exclusive`），本 worktree 基于
   `9c102d7` → 合并需先对齐；engine 池被每票段跳过 → 本票新场景与 t260912-03 三条正用例只由每日巡检覆盖。
3. **全族未修点（见上，附本轮量化实例）**：建议一次补授修全族。
4. **同轮 3 条 FAIL 属别票面**（fuse-headroom 批量子用例 / capture 双胞胎 UI 断言）→ 与本票零交集；
   但它们会卡 merge 闸，需对应票或台位治理处置。
5. **合并冲突线索**：本票累计改了 6 个测试资产文件（capture×3 / doc_face / t260912-02 lib + net_table 场景），
   其中 `sc_capture_chat_active.mjs` 与并行票 t260912-01 的授权面重叠（其 `uses` 为证）——请在合并记录点名。
6. **残差面（接受）**：`真实字节漂移`（源码改了未重建 bundle）从 FAIL 收进 not-checked；若要保留该产品信号，
   应显式断言「committed bundle == 源码重建产物」。
7. **gen0 两条轻微实现观察仍开放**（引擎自 gen0 起未再改动）：①同秒重复签发同一授权 → 落账判定认不出新条目、
   CLI 假报 `unconfirmed` 且文案指向「重启 worker」（方向错，fail-closed 不假报成功）；②畸形值（非数值
   expires/issued）在 `int()` 处抛 `ValueError`，与 `_authz_entries` docstring「任何畸形…不炸」不符。
8. **覆盖缺口（沿用）**：`path_gate_authz_used=` 机读键字面量在 integration 侧无断言锁（仅真跑可见）。
9. **运维面（设计固有）**：合并后 CLI 对未含 `sign_face` 的 worker 拒发 authorize（fail-closed）→ 现网 worker
   需按 runbook §S0→§S6 再重启一次才能继续用人授权。
10. KI 候选待 main 侧 integration 落册（本段写集不含 `notes/`）：implement gen0 三条 + 走查新增六条
    （④机读键无断言锁；⑤两条轻微实现缺陷；⑥供给台/console 台生命周期不一致四形态；⑦同族起台子用例直判未清
    （本轮新增 fuse-headroom 批量子用例实例）；⑧F 判据口径未入模板（曾致仲裁多轮误判，本轮起事实已自证）；
    ⑨闸执行面连续故障致机械绿灯缺失；⑩跨泳道端口抢用（本轮 21121 被别台持有，直接吃掉本票两条在册场景的复跑））。

## 收口两问

- **沉淀一问（doc_sediment）**：want=true。target=`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`
  新增小节「sign 信号载荷演进纪律」（备用落点 `docs/testing-guide.md` 的「动输入契约必带全链场景」同族节）。
  理由：本票确立/坐实了跨票复用的引擎机制事实，docs/ 无任何承载（全库 grep 无 authorize/人授权/signal
  载荷纪律条目）——①逐票常驻 worker 的内存代码可早于磁盘代码（本票生产实证 + 两张实票解扣/关单）；
  ②temporalio 解码对未知字段静默丢弃（DefaultPayloadConverter + 旧形类独立复现）；③故载荷演进必须走
  「标量 marker 可见化 + sign_face 指纹先验 + 三态回执(landed/refused/unconfirmed)」三步纪律，
  新字段上线=必须重启在途票 worker；④指纹严格相等 ⇒ 加任何字段都拒发未重启 worker（运维含义）。
  `docs/` 不在本票写集（review_plan R1 已裁），故只提建议、不落笔。
- **反向同步闸（doc_conflicts）**：空（无矛盾）。本段实际读过并逐条核对：`docs/README.md`、
  `integration/README.md`（L22-26 三态退出码、L124-128 capture 基线泳道机械跑一律 ENV_FAIL）、
  `docs/design/失败分类协议v1.md`（L36-63 三态语义/归属决策表）、
  `docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md`（人审签字门「行为不变」）、
  `docs/design/工单工作流台设计.md`（人门 awaiting-human 段）、`docs/testing-guide.md`（KI-063 全链纪律段）、
  `notes/debts/known-issues.md`（只读 KI-033/061/063/067/072）。本票实现与上述成文主张一致，未发现被推翻的
  claim → 不产生 pending-doc-sync 债条目。
