# 集成红项清账（260929 快照 · 草稿待定稿）

> 这是 **260929 当天的一次性快照**，不是进度表，不做维护——红项现状一律查票面/Temporal。
> 目的：把"套件里那些一直红、没人管"的项**具名、归类、定去留**，让集成门的判据重新变成信号。

## 一、结论（先给答案）

**问题不是"用例有没有意义"，是"红没有归属、也没有离场机制"，而且环境红与真红混在同一个「败」里计数。**

当天事实（票面原话为证）：

| 事实 | 数据 |
| --- | --- |
| 每轮场景数 | 346（07）/ 348（08）；本轮跳过池 engine、exclusive 少 81 条 |
| 每轮"败" | 23–25 条 |
| 其中**在册已知红** | 9 条（挂账 3–5 天） |
| 其中**未在册** | 5 条 |
| 其中**环境红（供给/台面）** | 每轮 ~11 条（只在计数里，没有具名出口） |
| 门的判据 | "套件全绿才放行" → 在当前环境下**不可满足** |
| 代价 | 每票每轮 50–60 分钟纯机械循环；260929 两票合计约 **5.3 小时**机时 |
| 对照：两票真正的编码时间 | t260929-07 = **7 分钟**；t260929-08 = **21 分钟**（+3 分钟返工） |

两条泳道的仲裁报告**自己**就判定了"不是本票的错"：

- `t260929-07`（仲裁第 5 轮原文）：`Verdict: tests-fault (shared-infrastructure supply/concurrency face; NOT code-fault; NOT the scenario assertions)`；本票面连续 5 轮绿；blockers 在**同一棵树上换第三批**，且**单独复跑全绿**（0.5s / 115.5s / 3.2s）。
- `t260929-08`（仲裁 gen3 原文）：本票 3 场景连续 4 轮全绿（11.7s / 7.1s / 6.1s）；12 条红里 **11 条是在册已知红**；唯一 blocker `auto-rework-trace` 已被四轮证据定性为**双稳态共享台 flake**（干净主线 @9856f14 上 PASS 14.5s、gen0 闸 PASS 14.9s，泳道内 FAIL 93–99s）。

## 二、在册红：25 条（挂账 3–5 天，册子 = `integration/known-red-baseline.json`）

| 族（册子自带的 home） | 条数 | 项 |
| --- | --- | --- |
| workbench UI 族欠账（"待 workbench 专项修"） | 6 | chat-project-tag、click-no-chat-switch、top-entry-retired-form、charter-prompt-wire-contract、stale-handshake-banner、platform-context-fold-stacked（挂 3 天） |
| docs/UI 浏览器面存量欠账 | 3 | chat-band-affiliation、session-lifecycle-ui、charter-injection-journey（挂 5 天） |
| 捕获族（KI-051 同族后续） | 2 | capture-chat-active、capture-chat-e2e（挂 5 天） |
| dsh 0.1.5 迁移在途面 | 2 | dsh-probe-live-green、dsh-probe-live-cred-env（挂 5 天） |
| 巡检发现证据复核语义面 | 2 | t260915-20-project-identity-realchain、t260916-02-relocation-realchain（挂 5 天） |
| 调度路人门/台账面 | 2 | t260917-02-legacy-fire-redirect、t260917-02-board-unresolved-running（挂 5 天） |
| 守卫/台账族 lane 适配欠账 | 2 | t260907-04-naming-grep-assert、t260910-12-lease-unit（挂 3 天） |
| stage 供给/台面（按环境面隔离） | 2 | t260916-25-stage-console-prepare-refresh、t260916-26-stage-plugins-selfcheck（挂 3 天） |
| 其它单条 | 4 | t260910-04-console-paused-list、t260911-02-trigger-kinds、t260910-11-temporal-isolation-guard、t260913-02-suite-journey（挂 5 天） |

**共同的毛病**：册子只有 `booked_at / booked_sha / home / note`——**没有 owner、没有"何时撤红"、"挂多久算过期"**。挂账因此变成了另一种遗忘方式（最老的已挂 5 天）。

## 三、今天出现但**不在册**的红：5 条

| 项 | 260929 观察 | 建议 |
| --- | --- | --- |
| `auto-rework-trace` | 08 每轮的**唯一门 blocker**；已定性双稳态共享台 flake（干净主线过、泳道内挂） | **单开一张修票**（共享台双稳态），修好前按环境面隔离挂账 |
| `t260904-12-no-skip-guard` | 两票每轮都出现 | 补挂账（要写 owner 与撤账条件） |
| `t260904-05-ledger-adversarial-boot` | 两票每轮都出现 | 补挂账 |
| `t260907-05-profile-farm-sandbar-links` | 两票每轮都出现 | 补挂账（疑似 lane 口径环境面） |
| `ticket-session-restore` | 07 每轮出现 | 补挂账或判为环境面 |

## 四、环境红：每轮 ~11 条（**没有具名出口**）

- 性质：不是产品红，是"**跑不起来**"——共享台供给/端口/容器持有/docker 面。07 仲裁原文：`gate red surface is dominated by shared test-stage contention under gate concurrency`；门回执里的证据串有「base 未由本项目容器持有（端口改配/异树串连窗）」「共享供给台不可查询（台缺席/非 up）」。
- 从仲裁报告里能点到名的样本（**单独复跑全绿**）：`t260925-12-executor-timings-receipt`、`t260924-04-project-template-journey`、`t260916-25-stage-console-prepare-refresh`。
- **它是这套门最伤的地方**：11 条环境红混进"败"，把真红淹掉，还把诊断引向错误方向（人看到的是一堆红，分不清哪条是新伤、哪条是环境缺件）。
- 建议：**从"败"里拆出来**，走单独的 ENV 通道（项目里本来就有"三态：过 / 败 / 环境不可用 exit 2"的约定，只是没接进门判据），带上限与具名，不参与"全绿"判据。

## 五、要立的规矩（三条）

1. **每条红必须三选一，不许在门口挂着**：**修**（带责任人 + 期限）/ **挂账定责**（进册，必带 owner 与"何时撤红"，期间不算门红）/ **退役或降级**（场景本身过期、重复、环境不可能满足）。无主的红不许进门的判据。
2. **门判据收口**：只对"**本票新增红 + 未挂账红**"判红（用项目已有的按提交记账台账做基线对照）；**环境红走 ENV 通道**，不混进"败"，不计入全绿判定。
3. **定期点名**：挂账超期无人认领 → 自动转修票或退役票，不许无声无限续期。

## 六、260929 当天已做 / 待拍

**已做**（都在不可变历史里）：

- 两票投了**宿主裁决**（host ruling）+ **人授权**（`kind=arbitration_verdict`，12 小时有效）：超轮次上限时改走验收而不是卡死；裁决内容同时告诉下一轮仲裁"环境红与在册红不计入本票判据、按类具名、不许回工整跑"。
- 开票 `t260929-09`（engine-hardening）：补 L10 闸的盲区（变量可执行文件 / `.sh` 启动面），因为 260929 的浏览器弹窗真凶就藏在闸看不见的地方。
- 直修 `ebb52c9`：watchdog 真宿主 bench 起台补 `--no-open`（弹窗元凶，已真机验证）。

**待你拍**：

1. 按上面三条把 **25 条在册 + 5 条未在册 + 环境红**定性（谁认领、谁退役）——要不要我照这张表开"清账票"（一批挂账/退役 + 一批修票）？
2. **门判据收口**（环境红拆通道 + 只判新增/未挂账红）现在开票吗？
3. `auto-rework-trace` 单开一张"共享台双稳态"修票吗？
