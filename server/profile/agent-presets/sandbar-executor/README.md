# server/profile/agent-presets/ —— 执行器会话 preset 的仓内真源

工单 t260928-29（epic project-executor，设计稿 260927 决定 8）。本目录是
**项目执行器会话 preset 的 repo 真源**——机器上真正生效的副本在
`$DSH_HOME/.agent-presets/<名字>/`，那是机器状态（实体拷贝），会随升级/重建
漂移；改身份先改这里，再重新拷贝。

## 现有 preset

- `sandbar-executor/`：项目执行器（project executor）。`agent.cordis.yml` =
  0.1.5 出厂 standard 组合 + 通用执行器人设；`preset.yml` = roster 展示名。

## 安装（人手一步；不需要重启控制台）

```sh
mkdir -p ~/.dsh/.agent-presets
cp -R server/profile/agent-presets/sandbar-executor ~/.dsh/.agent-presets/
```

然后在新会话的 preset 选择器里选「项目执行器」。roster 每次调用现扫目录，
装完即生效，**不许用软链**（roster 不扫软链，链了等于没装）。

## 不变式（改本目录前先读）

1. **永不改指 `agent-presets.default`**（`cordis.patch.yml`）、永不进
   `$DSH_HOME/settings.yaml`——260824 事故：default 指向被删的 preset，
   控制台起不了新会话。本 preset 只做加法，靠人手选择。
2. **本目录只是真源，不是挂载根**：profile patch 里配 roots 会被 profile-boot
   overlay 钉死覆盖（rc.8 实证），用户 preset 唯一入口就是
   `$DSH_HOME/.agent-presets/`。
3. **内容分工**：通用执行器人设（你是谁/能做什么/绝做什么/最小权限默认）
   在 persona 块；项目专属身份与纪律在 `server/session_charter.md` 的
   `## project:<key>` 段（随开局注入送达）。两边互补，不重复维护。

## 已知风险与重建口径

dsh 升级可能改 persona/plugin 的 schema（KI-100 mode C：机器级 GUI preset
不在兼容面），旧拷贝会挂载失败（260923 先例）。重建口径：以**当时出厂
standard 组合**为底原样拷贝，只换 persona 块（`agent.cordis.yml` 头注释同款
说明）。

## 装与不装，各发生什么

- **装了**：选本 preset 新开的会话，系统提示词常驻执行器人设（抗上下文折叠），
  开局再收 charter 注入。
- **不装**：什么都不坏——charter 注入不依赖本 preset，声明项目的新会话
  照样收到执行器身份（`## project:<key>` 段）；缺的只是系统提示词那层常驻人设。

## 后续票（不在本票范围）

- workbench 按项目自动选 preset：`startSession(workspaceId)` 今天没有 preset
  参数，逐项目自动套执行器身份需要在 `server/plugins/workbench/` 会话创建处
  接线——落地后上面的人手选择步骤退役。
