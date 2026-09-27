---
title: "溯游 admin × DeepSeek Harness（dsh）应用方案"
category: ops
tags:
  - admin
  - dsh
  - 应用方案
status: active
updated: 2026-08-19
---

# 溯游 admin × DeepSeek Harness（dsh）应用方案

> 版本：v0.1｜日期：2026-08-19｜状态：调研结论 + 路线建议，未动任何代码
> 研究对象：`/Users/user/Documents/deepseek-harness`（0.1.0-rc.7 Developer Preview，纯静态阅读，未 install 未构建）
> 对照基线：`server/serve.py` / `server/admin.py` / `server/tools_registry.py` / `server/tools/*` / 《平台架构设计》§12

---

## 1. dsh 架构速览（半页版）

DeepSeek Harness（`dsh`）是 DeepSeek 官方开源的 agent harness：**「一切皆插件」**，底层是 vendored 的 Cordis 框架（`vendor/cordis`，源码内嵌而非 npm 依赖，见 `vendor/README.md`）。产品的每一部分——模型适配器、工具注册表、会话日志、审批策略、agent loop 本身——都是一个 Cordis 插件，挂到共享上下文 `ctx` 上（`ctx.tools` / `ctx.llm` / `ctx.sessions` / `ctx.approval` …），全部可以从配置层替换。

**形态**：一个 Node CLI（`npx @deepseek-ai/dsh`），两个出厂 profile：

- `dsh web` —— 起 Web UI（默认 `http://127.0.0.1:3080`，只绑回环）。浏览器里是完整的 agent 控制台：会话列表+全文搜索、对话流、**每次工具调用渲染成卡片**（generic/terminal/diff/search 五种卡面，pending→完成两态）、需要审批的操作在页面上弹「允许/拒绝」、设置页有模型管理（填 API key 即热生效，无需重启）。会话选择工作区后才能跑。
- `dsh --profile headless "任务"` —— 一次性无人值守运行：新开一个持久化会话，跑完把最后一条 assistant 消息打到 stdout 然后退出，不开端口。这就是现成的「CLI 调 agent」形态。

**组装**：运行时是一棵插件树，按序叠加四层 patch——profile 列出的 bundle（`dsh-base` 底座 + `dsh-web-app`/`dsh-headless` 表层）→ profile 自己的 `cordis.patch.yml` → 全局 `$DSH_HOME/cordis.patch.yml` → 命令行 `--patch` 文件。一条 patch 按 `id` 定位某行并整体替换其 config，或 `insert` 新行。`dsh --dump-config` 不起服务直接打印实际组装树。

**插件**：一个导出 `apply(ctx)` 的 TS 模块就是一个插件；`ctx.tools.register(defineTool({...}))` 注册一个模型可见工具，参数 schema 自动进系统提示词，插件卸载时注册自动撤销。插件可以是一个 npm 包（`dsh plugin add` 走 pnpm 装进 profile 目录），也可以是**一个绝对路径的 .ts 文件**直接写进 `--patch` 的 cordis.yml（官方「第一个插件」教程就是这么做的，Node 22.19+/24 原生类型剥离直接加载 .ts）。

**会话**：每会话一份 append-only 事件日志（JSONL，默认 zstd 压缩，存 `$DSH_HOME/sessions/`），`tool/call`/`tool/result`/`approval/asked`/`approval/decided` 全部落盘、可回放；格式版本 `SESSION_FORMAT_VERSION = 0`（预发布，不承诺兼容）。

**模型**：出厂自带 `deepseek-official` 路由（`dsh-llm-deepseek` 适配器，直连 `api.deepseek.com` 流式协议），默认模型 deepseek-v4-flash / v4-pro；key 走凭据 seam（`$DSH_HOME/.credentials.yaml` ← `DEEPSEEK_API_KEY` env ← `.env`），**BYOK 是一等公民**：Web 设置页存 key 即生效，配置里只存 `apiKeyEnv` 引用、绝不存字面 key。

**动态插件**：`dsh-tool-cordis` 提供 `cordis_inspect / cordis_define / cordis_run / cordis_stop / cordis_undefine` 五个模型可见工具，agent 可以在运行中的进程里定义并在 vm 沙箱里挂载/卸载临时插件（官方自述：「沙箱隔离全局变量，但不是安全边界」「应当像对待 bash 访问一样对待它」）。临时插件只存在于进程内存，进程退出即消失——适合做实验，不适合做正式工具面。

---

## 2. §12 harness 契约四条 ↔ dsh 机制映射

| 溯游契约（§12.2） | 现状（python 自写） | dsh 对应机制 | 结论 |
|---|---|---|---|
| ①工具化：JSON in/out、schema 齐全、任意 harness 可绑 | `tools_registry.py`：TOOL dict=DeepSeek function-calling schema 直出 | `ctx.tools.register()` + `defineTool`；也接受**裸 JSON Schema 工具**（自行校验输入） | **无缝**：python 侧的 schema dump 可以逐字映射成 dsh 工具注册 |
| ②幂等 + dry-run | 靠各 python 工具自己实现 | dsh 不管这层（工具 execute 内部事务） | 留在 python 工具层，不变 |
| ③两阶段提交 + 凭据隔离 | v0 只有 admin token 分层，无审批队列 | `ctx.approval` seam + `tools/pre-execute` 返回 `ask` → Web UI 弹人类审批；审批决定写 `approval/asked`/`approval/decided` 审计事件；策略 `ask`/`never` | **dsh 直接补上我们缺的审批环节**；但它是本机单用户 UI 审批，没有 TOTP/远程审批队列，跨机部署时此条仍需自建 |
| ④run-id 审计 | `admin.log` JSONL，每次调用 uuid run-id | 会话事件日志 append-only 落盘（tool/call+tool/result 全量参数与结果），自带崩溃恢复 | **双层审计**：python 层 run-id 不动；把 run_id 放进工具返回值，它自动进 dsh 会话日志，两边可互查 |

dsh 白捡的能力（我们自写 loop 没有的）：≤8 轮硬上限 → dsh 无上限但有 guard 插件（repeat-tool-reminder/timeout-policy）+ 审批熔断；上下文压缩（compaction）；会话 fork/恢复/全文搜索；subagent；Web UI 工具 trace 卡片；模型热切换；**`dsh --profile headless "任务"` 直接替代 `admin.py chat`**。

---

## 3. 三条应用路线对比

| | A. 整体迁移 | B. dsh 当控制台（HTTP 薄壳） | C. 混合（本地薄壳） |
|---|---|---|---|
| 一句话 | admin 的 CLI/WebUI/对话全交给 dsh；python 工具被 TS 插件逐一改写或包裹 | dsh 插件只做一个「打 `/api/admin/call`」的转发器 | dsh 插件 spawn 现有 `admin.py call`，WebUI 用 `dsh web` |
| 工具真源 | 迁到 TS（或 TS 壳） | **不动**，python | **不动**，python |
| serve.py | 退回纯内容服务 | 不变（admin API 照旧） | 不变（admin API 照旧留作远程形态） |
| admin.py chat | 删除（headless 替代） | 保留作降级 | 保留作降级 |
| 审计 | 只留 dsh 会话日志 | run-id 在 python 层，dsh 日志只记「调了 HTTP」 | run-id 进工具返回值 → **双层一致** |
| 审批 | dsh approval seam | 同左 | 同左 |
| 改动量 | 大（每个工具一个 TS 壳+重写校验） | 最小（1 个插件 ~80 行） | 小（1 个插件 ~150 行，自动生成工具表） |
| 新依赖 | Node 22.19+/24 + npx dsh（必装） | 同左 | 同左 |
| 远程 admin（将来服务器部署） | 要重想（dsh 是本机进程） | **天然支持**（HTTP 打远端） | 加一个 HTTP 后端开关即可 |
| 风险 | 工具语义在翻译中漂移；TS/Python 双实现 | dsh 端看不到工具细节 trace（只有一个 http 调用卡） | 要求 dsh 与仓库同机；spawn 开销每次 ~100ms 级 |
| 与「纯 stdlib 部署」路线冲突 | 大 | 中 | 中（admin 侧引入 Node，内容服务不受影响） |

### 路线 A：admin 整体迁到 dsh

把 `server/tools/*.py` 逐个改写为 dsh 插件包（TS），qc_run 等重逻辑仍可 spawn python 管线脚本，但 schema/校验/审计全在 TS 侧。serve.py 删掉 `/api/admin/*`，退回纯内容服务。
**优点**：最「纯」的 dsh 用法，工具 trace 卡片最细，approval/pre-execute 粒度到单个工具。
**缺点**：工具真源从 python 搬到 TS，违背「管线与 admin 同语言同目录」的现状；QC 判定逻辑双写风险；将来部署到服务器时 dsh 是本机进程模型，还得再架一层。

### 路线 B：dsh 只当 agent 控制台（HTTP 转发）

写一个 dsh 插件，注册少量元工具（如 `suyou_admin_call(name, args)`），内部 `fetch` 打现有 `POST /api/admin/call`（带 admin token）。python 侧一行不动。
**优点**：改动最小；天然支持远程 serve.py。
**缺点**：模型看到的是「一个会调工具的工具」，schema 不透明（除非再把 `/api/admin/tools` 的 schema 逐字透传注册成 dsh 裸 JSON Schema 工具——这就趋近 C 了）；admin token 进了 dsh 侧配置，凭据隔离口径要讲清。

### 路线 C：混合（推荐）

写一个 dsh 插件包 `dsh-sandbar-admin`：

- 启动时跑 `python3 server/admin.py tools` 拿到全部工具的 DeepSeek schema dump，**逐字映射注册为 dsh 裸 JSON Schema 工具**（dsh 明确支持：「直接注册的原始 JSON Schema 工具自行负责输入校验」，`docs/cookbook/adding-a-tool.zh.md`）；
- 每个工具的 `execute` = `spawn('python3', ['server/admin.py', 'call', name, JSON.stringify(args)])`，解析 stdout 的 `{ok, result|error, run_id}` 原样返回——**run-id 审计单一真源仍在 python `admin.log`**，run_id 随返回值进 dsh 会话日志，双层互查；
- 另挂一个 `tools/pre-execute` 监听器：命中破坏性工具名单（`params_set` 及将来 §12.4 的发布/下架/调账）→ 走 `ctx.approval` 弹人工审批（§12.2-③ 两阶段提交的 v1 形态）；
- WebUI 直接用 `dsh web`（工具卡片、审批弹窗、会话回放全白捡）；CLI 用 `dsh --profile headless "跑 260627 的 QC 并列出红项"` 替代 `admin.py chat`；
- `admin.py chat` / `/api/admin/chat` 保留作无 Node 环境的降级路径；serve.py 一行不动。

**选 C 的理由**：满足「真用 dsh」的硬要求（agent loop、WebUI、审批、会话审计、插件机制全是 dsh 的），同时工具真源、run-id 审计、stdlib 内容服务三块现状零破坏；python 工具层继续按 §12.2 契约生长，dsh 侧永远只是一层自动生成的壳，**不存在双写漂移**（schema 每次启动现取现注册）。

---

## 4. 路线 C 落地步骤（文件级）

前置：装 Node ≥22.19（或 24+）。不需要 clone/build dsh 源码，直接 `npx @deepseek-ai/dsh`。

1. **装 dsh 并冒烟**（不改 suyou 仓库）：
   ```sh
   npx @deepseek-ai/dsh@0.1.0-rc.7 web   # 首次自动初始化 ~/.dsh/profiles/web
   ```
   浏览器开 127.0.0.1:3080 → 设置→模型 填 DEEPSEEK_API_KEY（写入 `~/.dsh/.credentials.yaml`，热生效）→ 加工作区指向 suyou 仓库 → 跑一句「列出当前目录文件」验证 bash 工具与审批弹窗。
   （版本钉死 rc.7；升级走提案。）

2. **新建插件**（本方案唯一新增的 suyou 侧产物，建议落 `server-plugin/`，不动现有任何文件）：
   ```
   server-plugin/
     sandbar-admin.ts        # 插件本体（下述骨架）
     cordis.yml            # --patch 覆盖层
   ```
   `cordis.yml`：
   ```yaml
   - insert:
       - id: sandbar-admin
         name: '/Users/user/Documents/suyou/server-plugin/sandbar-admin.ts'
   ```
   启动：`npx @deepseek-ai/dsh@0.1.0-rc.7 web --patch server-plugin/cordis.yml`

3. **插件骨架**（关键路径，约 120 行；API 形态来自 `docs/cookbook/adding-a-tool.zh.md` 与 `docs/user/develop/basic/tool.zh.md`，均为文档实读）：
   ```ts
   import { execFile } from 'node:child_process'
   import { promisify } from 'node:util'
   import type { Context } from '@deepseek-ai/cordis'

   const execFileP = promisify(execFile)
   const REPO = '/Users/user/Documents/suyou'
   // 破坏性工具名单：命中即转人工审批（§12.2-③ 两阶段提交 v1）
   const NEEDS_APPROVAL = new Set(['params_set'])

   export const name = 'sandbar-admin'
   export const inject = ['tools']

   async function py(args: string[]) {
     const { stdout } = await execFileP('python3', ['server/admin.py', ...args],
       { cwd: REPO, maxBuffer: 16 * 1024 * 1024 })
     return JSON.parse(stdout)
   }

   export async function apply(ctx: Context) {
     // ① 启动时从 python 注册表现取工具表（DeepSeek function-calling schema 直出）
     const tools: any[] = await py(['tools'])
     for (const t of tools) {
       const fn = t.function
       // ② 裸 JSON Schema 工具注册（输入校验沿用 python 侧 tools_registry 的口径）
       ctx.tools.register({
         name: fn.name,
         description: fn.description,
         parameters: fn.parameters,          // 原样透传 JSON Schema
         async execute(args: any) {
           const res = await py(['call', fn.name, JSON.stringify(args ?? {})])
           // ③ run_id 随结果返回 → 同时落 dsh 会话日志与 python admin.log
           return res
         },
       } as any)
     }
     // ④ 两阶段提交：破坏性工具先过人工审批（tools/pre-execute 是 waterfall）
     ctx.on('tools/pre-execute', async (exec: any, next: any) => {
       if (NEEDS_APPROVAL.has(exec.name)) {
         const verdict = await (ctx as any).approval?.request?.({
           agent: exec.agent, tool: exec.name, reason: '溯游 admin 破坏性操作，需人工确认',
         })
         if (verdict !== 'allowed-once') return { kind: 'deny', reason: '人工审批未通过' }
       }
       return next()
     })
   }
   ```
   注：`ctx.tools.register` 裸注册的精确类型签名、`ctx.approval.request` 的请求字段以 `packages/core/tools/README.md` 与 `docs/subsystems/approval.md` 的生成区块为准（本文写作时按文档口径示意，**首次实跑前照生成文档校准一次**——这是骨架里唯一可能与 rc.7 实况有出入的地方）。

4. **验证清单**：
   - Web UI 里对 agent 说「跑一下 QC」，确认它自主调 `qc_run`，工具卡片展示结构化红绿灯，`~/.dsh/sessions/` 的 JSONL 与 `server/admin.log` 出现同一次 run_id；
   - 让它 `params_set`，确认弹出审批、拒绝后工具以 deny 收尾；
   - CLI 形态：`npx @deepseek-ai/dsh@0.1.0-rc.7 --profile headless --patch <同上> "盘点数据并报告"`（headless profile 无 Web 审批应答者，破坏性工具会 fail-closed——这恰好是对的：无人值守时人不在场就不许批）。

5. **文档收尾**：CLAUDE.md「当前状态」加一行 admin 双形态（python CLI/API 照旧 + dsh 控制台），《平台架构设计》§12.2-③ 标注「审批环节 v1 = dsh approval seam（本机 UI），TOTP/远程审批队列待部署步②再评」。

**明确不做**：不改 serve.py/admin.py/tools_registry.py 一行；不把 python 工具翻译成 TS；不启用 `dsh-tool-cordis` 动态插件（官方自述「像 bash 访问一样对待」，admin 场景无此需求，徒增攻击面）。

---

## 5. 风险清单

1. **Developer Preview 破坏式变更（最大风险）**。README 明牌：「未来将出现破坏兼容性的变更」；会话日志格式 `SESSION_FORMAT_VERSION = 0` 明示不承诺兼容（升级后旧会话可能直接拒读）；`packages/bundle/base/cordis.patch.yml` 行 id/结构在变。**对策**：版本钉死 `0.1.0-rc.7`（npx 带版本号）；升级走提案制，先 `--dump-config` 对比再切；我们的插件只用 `register`+`pre-execute`+`approval` 三个面，漂移半径小，升级校准成本 ≈ 半天。
2. **vendor/cordis 维护性**。cordis 以源码 vendor 进 dsh（`@deepseek-ai/cordis`，本地补丁 18 条记录在 `vendor/README.md`，含 fiber 生命周期硬化、Include 事务化等**dsh 私有修复**）——上游 cordiverse/cordis 与 dsh 的 fork 已在分叉。我们永远不该绕过 dsh 直接用 cordis；跟踪策略=只跟 dsh  release tag，不看 cordis 上游。
3. **对「纯 stdlib 部署」路线的冲击**。admin 侧从「python3 即可」变成「python3 + Node 22.19+/24 + npx 拉取 dsh 运行时」。**边界划清**：内容服务（serve.py）保持纯 stdlib 不动，Node 只是管理员/agent 本机的控制台依赖，不进服务端部署路径；无 Node 环境降级到 `admin.py chat`（功能等价、少 WebUI 与审批 UI）。81M 是源码仓库体积，运行只需 npx 安装的发布包（体积未实测，首次冒烟时记录）。
4. **审批≠§12.2-③ 的完整形态**。dsh approval 是本机单用户一次性授权（无 allow-always、无审批队列持久化、无 TOTP；源码实读 `packages/interaction/user-approval/README.zh.md`「已知限制」逐条列明）。将来 admin 上服务器（迁移步②③）时，两阶段提交的服务端审批队列仍要自建，dsh 这层当「本机确认」用。
5. **动态插件安全面**。`cordis_define/cordis_run` 官方定性「不是安全边界」。默认 profile **不含**它（需 `--patch` 显式挂，见 `examples/web-cordis/cordis.yml`），我们不挂即可；但要意识到 dsh 默认工具面含 bash/文件写，admin 会话的工作区应限定 suyou 仓库、权限模式保持 `workspace-write + ask`（出厂默认）。
6. **spawn python 的进程模型**。每次工具调用 fork 一个 python（~百毫秒级），对 QC 这类秒级工具无感；若将来有高频小调用，再在同一插件里加 HTTP 后端（打 `/api/admin/call`，即路线 B 能力）作为 config 开关——骨架已按「py() 是唯一出口」写好，切换点唯一。
7. **TCC/授权类环境坑**。macOS 上 dsh 进程访问 `~/Documents` 下的仓库会触发系统文档目录授权（与 app 热更层同款 TCC 弹窗），首跑手点 Allow 一次即可。

---

## 6. 结论出处标注

**源码实读**（文件路径，deepseek-harness 仓库内）：
- `packages/bundle/base/cordis.patch.yml` —— 底座插件全集、approval/permission/sandbox 默认策略、DeepSeek 适配器挂载方式、凭据 seam 注释
- `apps/cli/src/plugin.ts` —— `dsh plugin` = pnpm 转发器 + bundle 声明自动进层
- `apps/cli/README.md` —— profile 目录结构、四层 patch 叠加顺序、`--dump-config`
- `vendor/loader/src/internal.ts` + `vendor/README.md` —— Node 22/24 原生 TS 加载（.ts 插件直挂的依据）、vendor 同步流程与 18 条本地补丁
- `examples/web-cordis/cordis.yml`、`examples/jsonrpc-agent/minimal.cordis.yml` —— patch overlay 与最小组合的实样

**文档实读**（docs/ 与包 README，zh 版）：`docs/architecture.zh.md`（轮次流程/事件三域/能力 seam/扩展点映射表）、`docs/cordis-primer.zh.md`（五个核心概念/waterfall 语义）、`docs/cookbook/adding-a-tool.zh.md`（defineTool 约定、裸 JSON Schema 工具、pre-execute 策略点）、`docs/user/develop/basic/index.zh.md`+`tool.zh.md`（最小插件与绝对路径挂载教程）、`packages/extensions/tool-cordis/README.zh.md`（cordis_* 五工具与信任立场）、`packages/llm/llm-deepseek/README.zh.md`（BYOK/settings 热更/凭据 seam）、`packages/interaction/user-approval/README.zh.md`（审批 seam 能力与限制）、`packages/bundle/headless/README.zh.md`（headless 一次性运行器）、`docs/subsystems/persistence.zh.md`（会话日志后端/崩溃恢复/格式版本立场）、`docs/user/guide/python-sdk.zh.md`（Python SDK 与 macOS arm64 支持矩阵）、`docs/user/guide/index.zh.md`（Web UI 使用流程）。

**未实测**（本文标注为推断、首次冒烟时需验证）：npx 发布包体积与启动开销；裸 JSON Schema 注册的精确 TS 签名；`ctx.approval.request` 请求字段；headless profile 下 `--patch` 与审批 fail-closed 的组合行为。

## 相关文档

- [平台架构设计](../design/平台架构设计.md)（§12 admin，本文为其落地）
- [工单工作流台设计](../design/工单工作流台设计.md)（实践参考：多角色协作）
- [知识库设计](../design/知识库设计.md)（实践参考：知识库插件承载）
