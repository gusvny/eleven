# ui-check —— 控制台 UI 验收截图通道（t260828-09）

UI 改动票的验收证据：headless 浏览器截控制台关键视图，落泳道 `.suyou/screenshots/`，
integration 审读 agent 看图判定，merge_check 机械查「UI 票无 png → 红灯」。

## 用法

```bash
# 依赖一次安装（playwright-core，仅 devDependency）
cd server/ui-check && npm install

# 干跑自检（不起浏览器）
node capture.mjs --selftest

# 截图（通常由工单引擎 worker 代跑，也可手动补跑）
node capture.mjs --url http://127.0.0.1:3199 --out <泳道worktree>/.suyou/screenshots

# 泳道隔离台一键（临时 DSH_HOME+临时端口，不碰 3099）
node capture-lane.mjs --lane <泳道worktree> --out <dir>
```

## 环境变量

| 变量 | 缺省 | 说明 |
|---|---|---|
| `SUYOU_CONSOLE_URL` | `http://127.0.0.1:3099` | 控制台地址（测试环境 3199） |
| `SUYOU_UI_CAPTURE_TIMEOUT_MS` | `60000` | 单页面超时（activity 侧另有 120s 进程兜底） |
| `SUYOU_UI_CAPTURE_CHAT_ACTIVE_MS` | 带旗 90000 / 直连 25000 | 等 `data-phase=active` 的窗口（隔离台种子消息走真模型，往返有延迟） |
| `SUYOU_UI_CAPTURE_TRANSCRIPT_MS` | `30000` | 种子消息发出后等**消息上屏**（进会话转录）的窗口，独立于 active 预算（active 翻转快于转录渲染） |
| `SUYOU_UI_CAPTURE_SEED_PROMPT` | `（截图台造数）请只回复两个字：收到` | 种子消息词（--allow-seed 路径） |
| `SUYOU_UI_CAPTURE_ALLOW_SEED` | 不设 | 台内造数门旗 env（等价 `--allow-seed`） |
| `SUYOU_PLAYWRIGHT_MODULE` | 不设 | 泳道无 node_modules 时指主树 playwright-core 包目录（selftest 与实拍共用） |
| `SUYOU_CAPTURE_PRESET_SOURCE` | `$HOME/.dsh/.agent-presets/suyou-integration` | 隔离台 preset 物化源（单测/基线桩覆盖用） |
| `SUYOU_CAPTURE_FIXTURES` | 不设 | **capture-lane 专用**（bench 级开关）：`=1` 时向 capture.mjs 追加 `--fixtures`，开启状态注入 |
| `SUYOU_UI_CAPTURE_FIXTURES` | 不设 | **capture.mjs 直跑专用**（capture 级开关）：`=1` 等价 `--fixtures`。两个 env 名不通用，见下节 |

## 状态注入（fixture 票，t260901-24）

根治「隔离台全新空家 → ui_evidence 只能拍 7 张渲染正常级」的证据缺口：把 fixture
票预置到指定 stage/门，让实拍到达**审批抽屉**与**泳道并行态**。实现=浏览器层
Playwright `page.route` 拦截 wf **读**端点回 `fixtures/*.json`（不改 workbench/node.ts、
不碰 Temporal）。

```bash
# 隔离台路径（推荐）：bench 级 opt-in
SUYOU_CAPTURE_FIXTURES=1 node capture-lane.mjs --lane <worktree> --out <dir>
#   → 产出 9 张图（7 标准视图 + console-approval.png + console-lane-parallel.png）
#     + fixture-manifest.json（URL→fixture 拦截映射）

# capture.mjs 直跑路径（须自己组台）
node capture.mjs --url http://127.0.0.1:<port>/ --out <dir> --allow-seed --fixtures [dir]
```

硬条款：

- **显式 opt-in，缺省关闭**：capture-lane 缺省不传 `--fixtures`——缺省=7 视图口径
  逐字节不变，agent_activities 两处调用方（ui_evidence 段 / acceptance 走查）的
  证据永不含虚构票。真 Temporal 在线时隔离台会出现真票，默认注入会把真伪票混进
  同一批 PNG（PNG 无法自标真伪）——所以注入必须是显式动作。
- **双 env 名不通用（错配=静默不注入）**：`SUYOU_CAPTURE_FIXTURES` 只被
  capture-lane 读（bench 级）；`SUYOU_UI_CAPTURE_FIXTURES` 只被 capture.mjs 直跑读
  （capture 级）。capture-lane spawn 时会把后者从子进程 env 剥掉——台内注入单一
  开关来源，误设 capture 级 env 名不会在台内形成第二开关。错设名字的行为是
  「明确不注入（照常 7 视图）」，不会报错。
- **联锁**：注入通路必须与 `--allow-seed`（或 `SUYOU_UI_CAPTURE_ALLOW_SEED=1`）
  同现——直连真生产台注入假票=污染真数据，违反即退出 2 人话拒跑。
- **只拦 GET**：`/wf/tickets`（list/show/diff）与 `/wf/workflows` 命中才 fulfill；
  POST accept/advance/dispatch-next/rework/update 恒放行；projects 等其余端点放行
  走真数据。fulfill 恒显式 `contentType: application/json`（客户端 `res.json()`
  依赖，缺了会静默渲染空态=伪造「渲染正常」）。URL 只比 pathname 不比 query
  （`withProject` 会挂 `?project=`，整串匹配会静默放行→空列表假象）。
- **实体性校验**：`loadFixtures` 逐文件校验普通实体文件（拒软链）、JSON 可解析、
  `_fixture: true` 标记在、必需键与 TicketRow/TicketDetail/Wf/TicketDiffResult 同构
  ——缺/畸形一律人话拒因退出 2（证据素材宁可拒跑不静默降级）。
- **路由 LIFO 取舍**：Playwright 路由 LIFO 匹配、多 handler 易被后注册者反超——
  本设计单 handler 内部经 `routeDecision` 分派，从结构上绕开；install 在首个
  `page.goto` 之前。
- **退出码口径**：fixture 视图失败走既有 best-effort 通路→整 run 退出码 1（worker
  侧软失败不拦主链语义不变）。失败行带前缀 `状态注入视图失败（FIXTURE-MODE）：`
  ——审读人据此读作「注入/fixture 数据问题，修 fixture 重拍」，而非「渲染故障」。
- **证据自证**：PNG 无法自标注入态——fixture 模式 stdout 打 `FIXTURE-MODE` 行 +
  out 目录落 `fixture-manifest.json`（URL→fixture 映射）。真票共存取舍：opt-in 是
  显式动作，开启者自担「当次证据为注入态」；不设「真票在场即拒跑」（那需要读
  Temporal，恰是本机制要绕开的依赖）。

fixture 票（`fixtures/`，全带 `_fixture: true`）：T-FIX-A=awaiting-human@merge（带
pending 审批理由；驱动 `.wb-d2-step[data-s="awaiting-human"]` ✋ 审批抽屉），T-FIX-B
=implement ∥ design_integration_tests 双 running（running 条数>attempts，驱动
lane-states.ts 规则 4 双活跃步 ▶ 与 `.wb-d2-par` 并行徽标）。视图只看不批：绝不点
approve/签字/打回提交。

断言基线：`node integration/t260901-24/test_t260901_24.mjs`（纯函数黑盒 + 畸形输入
桩 + 子进程联锁/env 错配行为，34 断言，不起浏览器）。

## 台内造数门旗（--allow-seed，t260901-02 根治 + t260901-03 收口）

隔离台（capture-lane）下 MRU 账册必为空，chat 态视图开不出来。带 `--allow-seed`
（或 env `SUYOU_UI_CAPTURE_ALLOW_SEED=1`）时允许台内造数：经隔离台自己的 API 建
两个会话 + 写本插件 localStorage 账册，chat 视图走**点台上「+ 新建会话」**（工厂
同款：绑工作区+staging）+ 发一条种子消息驱动 `data-phase=active`——平台语义
「空内容会话恒 hero」（composerPhase blank ⟺ 无可见会话内容），只有真消息才翻
active（dbg-chat.mjs 实证链）。造数端点回空 cwd 时快速显式失败（cwd 非空断言，
t260901-03）。**直连/生产路径绝不带此旗**：门旗缺失时无 MRU 行=明确报错交人，
零写操作（不静默假过也不静默跳过）。

## composer 输入配方（t260901-03 定性收口）

**症状**：对出厂 composer 用 playwright `fill`/`type`/`click` 常态失效——值写不进、
点击被吞。**定性**：出厂 hero 区遮罩层（mask）拦截 pointer 事件 + 键盘 focus 不稳；
属出厂 shell 行为（写集外不修），证据工具侧换输入配方绕过。**配方三要素**
（`capture.mjs seedChatMessage`，复现链见 `dbg-chat.mjs`）：

1. textarea 上用 prototype native setter 写 value + dispatch bubbling `input`
   （React 受控组件 onChange 生效）；
2. 写后**回读校验**，值不粘住等 1s 重来（composer 挂稳有窗口期，过早拿到的是
   将被换装的 hero composer），20s 仍不粘 → loud 报错；
3. 发送走 DOM 直点 send 按钮（`aria-label="Send message"`），不可用则退避聚焦回车。

**准入模态双保险**（同票）：chat 视图截图前 `dismissAdmissionModal`（Configure
later/可用钮/Escape → 轮询 `[role=dialog]` 消失），截图时刻 DOM 仍有 dialog =
loud 失败（chat 证据被遮挡不算数）。

## 隔离台 preset 物化（t260901-02）

capture-lane.mjs boot 隔离台时把 `suyou-integration` agent preset **实体复制**进临时
DSH_HOME——控制台默认 preset 缺失会导致建会话报 agent-preset-not-found，chat 态
造不出、UI 票截图恒失败（t260901-01 三轮人工补证据的根因）。要点：

- **来源 = 主 checkout 用户真实家实体**（固定 `$HOME/.dsh/...`，不随 env DSH_HOME——
  空家模拟时 env 只是隔离台目标）。不现拼：`agent.cordis.yml` 是 dsh 出厂 standard
  组合原样拷贝 + persona 内联，仓库内无真源，复制真实生效工件才与生产台同构。
- **必须实体复制**：roster 只扫 `$DSH_HOME/.agent-presets/` 实体目录，软链不被扫描
  （`server/profile/cordis.patch.yml` agent-presets 注释实证）。
- **缺失/畸形源 → 拒跑非零退出**，人话指路按 cordis.patch.yml 注释重建；不自造假
  preset（造假证据红线）。物化全落临时家内，五路径 teardown 天然回收。
- 断言基线：`node integration/baselines/capture-lane-preset.mjs`（三态，不 boot）。
- **失败尽力视图**（worker 侧 `prepare_ui_evidence`）：capture 失败时已拍 PNG 归档
  主树 `.suyou/evidence/<ticket>/`，归档成功的从泳道 screenshots 移出（机械闸
  png_count 归 0 维持红灯，残缺视图不假通过），归档失败的留泳道可人工捞回。

## 截图最小集 v1

1. `console-default.png` —— 控制台默认落地页（hero 态）
2. `console-chat.png` —— chat 态（`data-phase=active`，含种子消息与模型回复）

导航定位一律用语义锚（`data-phase`、可见文本、`data-wb-*`），禁哈希类名选择器。

## 只读红线

只 GET 打开控制台页面并做导航点击，**不提交任何表单、不发工单、不碰任何进程端口**。
台内写操作（建会话/种子消息）仅限 `--allow-seed` 隔离台路径。

## 流水线接线

- `dev_lane` implement 落盘后：UI 票（`shared.is_ui_write_set` 命中）自动执行
  `prepare_ui_evidence`（worker 代跑本脚本，`SUYOU_UI_CAPTURE_STUB=1` 可桩跑）；
- `integration_review` prompt 注入截图清单（含 mtime），审读按「无截图证据=打回」；
- `merge_check`：UI 票且 `.suyou/screenshots/` 无 png → 红灯 + 处置指引。

## 故障语义

浏览器优先系统 Chrome（`channel:"chrome"`），探测不到退 playwright 自带 chromium；
两者都不可用 → 非零退出 + 明确报错，不静默降级。chat 态锚找不到 → 该视图失败
写进 stderr 与退出码，另一张图仍保留。隔离台 preset 源（$HOME/.dsh/.agent-presets/
suyou-integration）缺失/畸形 → capture-lane 拒跑指路，不自造假 preset 造假证据。
