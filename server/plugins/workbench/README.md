# sandbar-workbench —— 工单工作流台插件（dsh UI 插件）

> 本目录是 dsh 管理台的工单工作流台插件：宿主半（`node.ts`）在 dsh webServer 上挂
> `/sandbar-workbench/api/*`；浏览器半（`src/client/`，构建产物 `lib/client.js`）
> 通过 dsh 插件槽机制接管界面。设计真源：
> `docs/design/工单工作流台设计.md`、`docs/design/右栏会话入口与hero定制设计.md`。

## 目录

| 路径 | 是什么 |
| --- | --- |
| `node.ts` | 宿主半：webServer 路由（wf/* API、global-session/open、ticket-session/open） |
| `src/client/index.tsx` | 浏览器半入口：工单台视图 + `apply()` 槽注册总装 |
| `src/client/sidebar.tsx` | 侧栏接管（左列项目分组+工单 / 中列四视图），双列布局与样式 |
| `src/client/session-entry.tsx` | 会话入口共享层：记账 hook + 侧栏「会话」区（唯一会话入口） |
| `src/client/hero.tsx` | （已退役）hero 接管退役记录（t260829-01 退场，防复发样本，不再被引用） |
| `src/client/epics.tsx` 等 | 立项单视图等 |
| `src/shared/` | 纯函数层（无 DOM / 无 IO，`smoke/*.mjs` 直跑）：sessions（会话记账口径）、hero（hero 项目 key 推导，t260829-06 起仅此一项）、view-project（中列当前项目单态）、parts、workspace |
| `smoke/` | 冒烟测试：`node smoke/<name>.mjs` 直跑，无需浏览器 |
| `lib/` | tsdown 构建产物（`client.cjs`/`client.js`），随仓库提交；改 `src/client/` 后须重建 |

## 挂载方式（槽机制）

dsh 单槽（`kind:'single'`）按 **priority 最低者渲染**（lowest renders）选举；
`ctx.slots.inject(name, () => ctx.slots.register({ name, priority }, component))`
是标准注册写法，同优先级重复注册会 throw。

| 槽 | priority | 挂什么 | 出处 |
| --- | --- | --- | --- |
| `sidebar.workspaces` | -10 | `WorkbenchSidebar`（顶掉出厂工作区浏览器） | t260825 |
| `conversation.hero.workspace` | -10 | `HeroEntry`（紧凑会话入口，与侧栏同一账册） | t260829-06 |
| `conversation.hero.agentPreset` / `.brand.mark` | -10 | 空（出厂 preset 选择能力移除=功能性损失，人审已确认） | t260829-06 |

> hero 槽位替换纪律（t260829-06 定稿）：**零 CSS 压制**——不做任何出厂元素
> 样式匹配/注入；大标题/大输入卡无接管槽，按设计文档修订口径共存。
> try/catch 放在 `slots.inject` 回调体内（inject 回调在槽未声明时于声明方
> register() 内延迟执行，包在 inject() 外的 catch 接不到），注册失败软退化
> 回弹出厂形态。

## 会话区（session-entry 立项）

**口径**（真源 `docs/design/右栏会话入口与hero定制设计.md` §2/§4/附录）：
会话分两类——工单会话（`ticket-<工单id>`，点工单 find-or-create，有自己常驻入口）
与项目会话（用户 UI 主动打开，跟项目走）。本插件只管后者，列表=**插件自建账册**
（`localStorage['sandbar-workbench-opened-sessions-v1']`，MRU ≤5、当前高亮），
只登记用户经本插件 UI 主动打开/新建的会话；磁盘存量、工单、subagent 会话一律不进。
`ctx.sessions.list` 只取 `displayTitle`（行标签）与 `current`（高亮），不做列表数据源。

**入口两处，同一账册**（`src/client/session-entry.tsx`）：
侧栏「会话」区（t260825-02 建、t260828-02 改为记账口径）：左列顶部常驻，
根治「刷新回不去」；hero 紧凑入口（`HeroSessionEntry`，t260829-06 纯槽位替换
重进）：挂 `conversation.hero.workspace` 槽。两处消费同一个 `useSessionEntry`
（同 `LEDGER_KEY` 账册、同 `handleNew`/`handleOpen`），hero 新建/切换的会话
刷新后可从侧栏回到。
（t260828-06 首版 hero 入口因 CSS 压制误伤出厂 chat 于 t260829-01 退场；
t260829-06 以非压制手段重进——三槽注册、零出厂元素样式匹配。）

**hero 压制方向为何永久关闭**：t260828-06 的接管 = 三槽抢占 + `src/shared/hero.ts`
语义锚点 CSS 压制（selector 以 `[data-phase="hero"]` 开头 + 类名后缀子串匹配），
其中后缀匹配与出厂组件类名全集交叉面过大，实测把出厂 chat 唯一入口（大输入卡，
variant 类 `<哈希>_hero`）整体 display:none，方向上不可收敛。t260829-01 处置：
三槽注册与 `<style>` 注入全部拆除；t260829-06 修订设计口径并重进为纯槽位替换。
`smoke/hero.mjs` 的 C 段静态断言持续看住「压制面残留为零」。

**新建链路**：`POST /sandbar-workbench/api/global-session/open {project}`
→ 宿主端 always-create（不带工单前缀、不注入工单上下文），会话落当前项目主目录
→ `session_id` 立即入账册 → `sessions.refresh()` → `waitForScope`（list 流同步有
延迟，轮询 ≤8s）→ `sessions.open(sid)`。任一步失败：console.error 留痕不静默；
账册已登记，刷新后可从列表进入。

## 构建

```
cd server/plugins/workbench
bash build-client.sh                        # 唯一构建入口：npm ci → tsdown → cjs≡js 复核 → sha256
node tests/build-determinism.mjs            # 确定性自测：同源码连续两次构建 sha256 相等 + lib 无 git diff
for f in smoke/*.mjs; do node "$f"; done   # 冒烟全绿
```

**版本与参数钉死口径**（t260910-15）：tsdown 精确钉在 `0.22.2`——`package.json`
（无 `^`/`~`）、`package-lock.json`、`pnpm-lock.yaml`（`pnpm import` 自 npm 锁同源
导入，rolldown/oxc 压缩链两把锁版本一致）三处锁定；构建参数全部来自
`tsdown.config.ts`。**禁止绕过 build-client.sh 手跑 tsdown/npx/pnpm 构建**：
npx 与裸 pnpm install 的传递依赖（rolldown/oxc）不受本目录 lockfile 约束，
是几百行压缩器化妆噪音（`Infinity`↔`1/0`、花括号风格）的复燃入口。

**副产物口径**：产物仅 `lib/client.cjs` 与 `lib/client.js` 两个（config 未开
sourcemap、无 gzip 步骤，无 mtime 类副产物进产物）；未来若开 sourcemap，
map 内含绝对路径，不入仓。

**遗留面（写集外，建议后续小票处置）**：仓根 `start-console.sh:56-65` 有活的
自动构建入口——console 启动时 `src/client/index.tsx -nt lib/client.js` 即自动
重建，三支：本地 `node_modules/.bin/tsdown`（本票钉死后拿 0.22.2）、回退
`npx -y tsdown@0.22.2`（主版本有锚但传递依赖不受本目录 lockfile 约束=残余
漂移面）、均不可用则跳过并显式告警。三分支参数都来自 tsdown.config.ts；建议
后续小票把该自动构建改为调 `build-client.sh` 收口。

产物已随仓库提交；只有改了 `src/client/` 才需要重建。dsh console 加载 `lib/client.js`
生效（重启 console 由用户执行，3099 不由工单 agent 操作）。
