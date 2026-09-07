# sandbar-providers —— LLM provider 管理与优先级（B 版）

t260821-08。手动排序 + 一键切换，**不做自动 failover**（用户拍板）。

## 功能

- 列出 4 个 provider（`deepseek-official` / `kimi-coding` / `zai` / `scnet`），显示当前激活 provider；
- 优先级排序（↑↓ 按钮 + HTML5 拖拽），顺序持久化到 `server/dsh/providers/state.json`（独立 json，不进 settings.yaml）；
- 每个 provider 计费档说明可编辑（同样存 `state.json` 的 `notes`）；
- 「设为当前」一键写 `agent-default-model`（provider + model，可带 reasoningEffort）；
- 「添加 provider」表单：baseURL / 协议（openai-completions|openai-responses|anthropic-messages）/ 模型 id 列表 / key 环境变量 → 写 settings.yaml 的 `llm-pi-ai.providers`；
- `scnet` 预置：openai-completions `https://api.scnet.cn/api/llm/v1` + `SCNET_API_KEY`，anthropic 备选 `https://api.scnet.cn/api/llm/anthropic` 仅作注释；**模型 id 留用户填**。

## 安全红线（deepseek-official 教训）

- 写 settings 的 provider **必须先 dry-run 校验「合法可解析」**。本插件不手改 settings.yaml 文本，而是走 dsh 设置 seam：
  `ctx.settings.mutate('llm-pi-ai', …)` 在持久化之前先跑 llm-pi-ai 适配器注册的 `assertServiceable`
  （= `resolveProfiles`：协议 ∈ 白名单、baseURL 非空且 http(s)、模型 id 非空不重复、手声明 route 必带 api/baseURL/models），
  坏 provider 直接拒绝、**不落盘**。
- `deepseek-official` 由 `dsh-llm-deepseek` 适配器拥有，永远拒绝写进 `llm-pi-ai.providers`（只读列出、可「设为当前」、不可 add/delete）。

## 结构

```
server/dsh/providers/
  node.ts              宿主半：/sandbar-providers/api/* 路由 + settings 读写
  src/client/index.tsx 浏览器半：设置面板「模型」分区
  lib/client.js        tsdown 产物（改 src 后重建）
  state.json           优先级 + 计费说明（独立 json 持久化）
```

## 构建

```
cd server/dsh/providers
npx -y tsdown@0.22.2 -c tsdown.config.ts   # 产物 lib/client.js
```

挂载：`server/dsh/profile/node_modules/sandbar-providers -> ../../providers`（headless 同款软链），
并在 `server/dsh/profile/cordis.patch.yml` 的插件列表插入 `sandbar-providers`。
