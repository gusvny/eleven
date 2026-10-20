# 260917 下午：在跑工单处置（项目会话）

**范围**：除 dsh 升级四张（`t260916-24/-25/-26`、`t260917-05` 属 epic dsh-upgrade）之外的
在跑票。处置时板面 9 张在跑，本稿只覆盖其中 4 张非 dsh-升级票。

**授权出处**：本会话当面「处理一下除了dsh升级以外的在执行的工单」；全部动作经
`server/tools/ticket.py` 正规入口，进 Temporal 不可变历史。

---

## 一、处置结论一览

| 票 | 是什么事 | 处置 | 依据 |
|---|---|---|---|
| `t260916-19` | 并行汇合段一处闸卡死后出路不可达 + 越权改动滞留 | **留 blocked，不动** | 余红含「合入 main 后才收敛」的过渡态守卫，属自锁结构，见 §3.1 |
| `t260916-21` | admin.log 按天轮转（现 1.7GB 从未轮转） | **已发 retry_qc 实测，再次 blocked** | 实测复现，非沉默失败，见 §3.2 |
| `t260916-22` | 巡检 agent 化：scan 段退役、新增 inspect 段 | **留 paused，不动** | 写集申报缺 workbench 产物面，见 §3.3 |
| `t260917-05` | dsh 升级 T1 遗留：会话发现面零静默降级 | 无需动作 | 16:17 已由引擎自动续跑（implement/gen2 running） |

---

## 二、`t260916-21` 的实测记录（我这轮唯一发的写操作）

票面原状：`arbitrate / blocked`，原因「测试集迭代 6 轮超限（上限 5），转人工判读。」

判断依据（发信号前核过）：
- 最近一轮仲裁（gen16）**结论是 `verdict=tests-fault`，且明确写「t260916-21 产品面零归因」**；
- 验收走查 3/3 完成（gen7 原文：电池全绿——L1 113 + 本票场景 39×2 + 入口审计 15）；
- `merge_check` 4/4 全绿（泳道有 commit、工作区干净、泳道内 verify_lane 绿灯、merge 预演无冲突）；
- 唯一没过的 `ui_evidence` 项对该票不适用（非 UI 票）。

动作：`retry_qc`（who = 宿主（经 sandbar 项目会话执行；授权出处：本会话当面原话））。

实测结果（**这是本轮最硬的一条证据**）：
1. 唤醒生效——`blocked_reason` 被清空、`stage=arbitrate` 真重跑（不是「唤醒后原地不动」的 KI-061 旧形态）。
2. 重跑出的新结论 **gen16 仍是 `verdict=tests-fault`**，报告写明：红项全在测试面——
   ① `integration/baselines/ticket-lifecycle-scenes.mjs:129` `ensureTestTemporal` 缺命名空间就绪闸
      （auto-rework-trace 竞态假红；串行 10/10×3 全绿在案）；
   ② `integration/t260914-04/offline_ticket_pause_entry.py:71` 假桩签名滞后（假红）；
   ③ `integration/run_scenarios.py` decl-gate 双命令供给波动；
   ④ browser 族四条的负载抖动（闸拦当轮串行复跑全绿）。
3. 于是路由再次走 `blocked:测试集迭代…超限`——**在共享面这三个红没消之前，重跑只会一轮一轮复现同一判定**。

结论：这不是引擎故障，是**共享测试面的存量红**（三条与 dsh 升级无关）。引擎的出路是
「人判读后放行」，不是无限重试。

---

## 三、三张票各自卡在哪（根因，含代码/文件锚点）

### 3.1 `t260916-19` — 过渡态自锁

- 最近一轮仲裁（gen11，16:17 附近）：`verdict=tests-fault`，报告点名两件余红，**均声明为零产品红**：
  - `auto-rework-trace` 纯半 = mjs 电池钉（`integration/baselines/sc_auto_rework_trace.mjs:258`
    期望总数 8，当前树实际 9 = 1 壳 + 8 内部）——报告原话：**「宿主 260917 令 a′ 已认领
    「t260916-19 合入 main 后收敛为 8」，合入前该子用例必红属过渡态预期」**；
  - auto-rework-trace 的 `workflow disappeared` 用例 = 台面供给面。
- 即结构是自锁：**要合入才绿，而合入前它必红** → 只能由人判读放行（或在合入窗口收编该用例）。
- 另：该票验收走查段尚未完成（3 项全未勾），仲裁段 2 项也未勾（门没落全）。

### 3.2 `t260916-21` — 见 §2，共享面三条存量红。

### 3.3 `t260916-22` — 写集申报缺口（引擎机制缺口，非本票独有）

- 票面状态 `create_plan / blocked`；时间线最后两条 = 06:14:05 `paused`
  （原话：宿主（经 sandbar 项目会话执行；授权出处：本会话当面「再放一些受阻的票出来」；
  理由=方案段第 4 次撞写集外产物，根因=写集申报不足，先暂停释放名额，待写集问题专门处置）→
  06:15:04 `paused-waiting`（段间暂停生效，等 resume signal）。
- 反复撞闸的实证（该票时间线里 4 次同族，跨 create_plan/implement/arbitrate 三段）：
  段 `implement` 拒收 `server/plugins/workbench/lib/client.cjs`、`client.js`
  （`path_gate_reason=unauthorized_path`）。
- 根因已实证：该票当前**写集 51 条**，含 `server/plugins/workbench/src/host/inspection-face.ts`
  与两个 tests 文件，**但不含 `server/plugins/workbench/lib/`**——而 lib 双产物是被 git 跟踪的
  构建产物，必须随票落盘。引擎的写集刷新通道只认方案段（`create_plan`）的 `files_changed`，
  且该通道**吸纳不进「构建生成物」**（该票 gen4/gen5 已两轮申报 52 件、实现段仍被拒）。
- 同源受害：`t260917-05` 也曾以「bundle 未随票重建」被判验收不通过。
- 结论：这是**引擎侧机制缺口**，正路是在 main 侧补「写集可登记构建产物面」，不是本票自己挣扎。

---

## 四、需要宿主决策或 main 侧动作的事项（我做不到的）

1. **`t260916-21` / `t260916-19` 放行**：两票都要「人判读后放行」这个动作。按 KI-061，
   该通道 = `host_ruling` 信号（记名裁定）+ 随后 `retry_qc` 唤醒；**`host_ruling` 不在我
   可用的操作面里**（我的工具面只有 sign / retry_qc），所以要么你在 console 上做，要么把
   通道给我。不做则两票停在 blocked 等人。
2. **共享测试面三条存量红**（`ticket-lifecycle-scenes.mjs:129` 命名空间就绪闸、
   `offline_ticket_pause_entry.py:71` 假桩签名、`run_scenarios.py` decl-gate 双命令）：
   按纪律「共享守卫/期望值只许 main 侧改」，必须 main 侧开票处置。
   **建议**：第 ① 条并进 `t260917-07`（该票正在查测试台命名空间迁移只做了一半，
   同族根因）；第 ②③ 条各开一张小票。
   `t260916-21` 泳道里已备好修复包 `.sandbar/arbitrate_fixes_r4_shared_only.patch`
   （103 行，对当前 main 树 `git apply --check` 干净通过、审查记录「零断言弱化」），
   可直接作为开票素材——**我不动它，它是泳道内产物**。
3. **`t260916-22` 的写集机制缺口**：建议单开一张 main 侧票（引擎：写集可登记构建产物面，
   或构建产物面豁免），否则该票 resume 后会在同一步再撞第四次同族闸。
4. **已关票的人审签字**：`t260917-01`、`t260917-02` 票面 `merge` 段仍停「等人签字」
   （`t260916-23` 同形）。我在案授权为空，不代签。

---

## 五、我没有做的事（留痕）

- 未修改任何泳道文件、未动 developer 泳道内容、未改任何共享守卫或断言。
- 未替 `t260916-19` 发重跑（自锁结构下重跑只会复现）；未替 `t260916-22` 发 resume
  （写集缺口未处置前 resume 是空转）。
- 未在 notes/ 内改账本（本稿为讨论稿，落账归 main 侧）。
