# 项目级会话的职责与注入机制（260904 讨论与拍板）

> 记录人：integration。日期：2026-09-04。
> 状态：拍板①②③已定（宿主原话在案）；charter 模板=草稿，待宿主定稿。
> 背景：session-entry 第 3 面落地后，会话入口长在项目上；宿主提出项目级
> session 的三项职责，并就「预置上下文 vs 独立 role」征求意见。

## 宿主原始诉求（2026-09-04，原话）

> 每个 session 作为项目级别的，主要的职责是 a）和人类讨论，确定方案，落到
> notes 或者 epics 里 b）检查解决在跑工单的问题 c）带跑一个跨多工单的长任务，
> 比如一个 epic，可能分成多个工单，相互有依赖，那这个 session 就可以负责
> 分步骤跑，检验，代签完成的，然后再往下继续建工单。所以这个 session 是要
> 有一些预定义的 context 的，或者用一个独立的 role？

## 拍板（2026-09-04，宿主）

1. **代签：允许，须注明授权来源**（原话：「可以代签，只要说明是在哪里得到
   授权，代签的时候写明就可以」）。
   - 落地口径（integration 拟，待随票细化）：授权出处=立项单/charter/单次
     指令，且要在代签动作**之前**已在案；sign note 必须引用出处（谁、何时、
     在哪授权的）。审计链三环：授权声明（用户可见可改）→ 注入（会话首条
     消息，会话内可见）→ 执行（sign 进 Temporal 不可变事件历史）。
   - 红线口径更新：由「agent 不得自签人工门」调整为「**无在案授权出处不得
     代签**；授权与执行全程留痕」。跳过人类审查环节（既无授权又无留痕）
     仍是红线。
2. **epic 带跑不走引擎 workflow**（原话：「不做引擎 workflow 来 drive epic，
   不确定性太多，需要 agent 的灵活性」）。session agent 直接用工具开票/
   验票/续票；可审计性不靠 workflow 编排，靠**每个动作过引擎**（create/sign
   全进 Temporal 历史 + admin.log）。断线/恢复由人盯 + 会话上下文承担
   （接受此取舍）。
3. **先不做独立 role**；改为**会话创建时注入预置 prompt**（本文下节）。
4. **charter 落点：引擎仓 `server/dsh/session_charter.md` 单一文件**（260904
   宿主定；原拟项目 notes/ 下放被否——notes/ 是知识库账本，charter 是会话
   开局声明这类活配置，语义归位到 server/dsh 项目侧声明族）。

## 注入机制结论（integration 实查，2026-09-04）

**可以注入，平台有现成 API，且本仓有生产级先例。**

- 先例：t260831-08 工单会话链——服务端建会话带回 context，客户端把它作为
  首条消息注入（当时 API=会话域 ctx 的 conversation.send；t260903-07 只
  下线了工单联动，node.ts 端点与 ticketContext 契约保留在案）。
- 现行 API（实查 dsh-client-runtime 产物）：
  `ctx.sessions.scope(id)` → 会话域 actx → `ctx.sessions.sessionOf(actx)`
  → Session 对象 → **`session.prompt(content, 'queue')`**（平台自己的
  首条消息路径：blank 位 + firstPromptPendingTurn 语义就是为首条 prompt
  设计的；注入会真实发出并触发一轮 agent 回复——即 kick-off）。
- 注入守卫（防污染，沿 t260831-08 ⑥ 口径）：只在「本项目行 + 新建且
  staged 会话 blank 位=true」时注入**恰好一次**；恢复/切换/非 blank 绝不
  注入。
- 内容源（拍板④，260904 宿主定）：**引擎仓 `server/dsh/session_charter.md`
  单一文件**（不放 notes/——那是知识库账本；也不放项目仓/机器级目录）。
  结构=首段通用 charter（占位符 {{project_key}}/{{project_name}}/
  {{primary_dir}} 端点现填）+ 可选 `## project:<key>` 分段（命中的项目把该段
  追加在通用部分后，无分段项目只吃通用模板）。node.ts 加 GET
  /suyou-workbench/api/session-charter?project=<key> 现读现渲染（改文件即
  生效）；文件缺失回落插件内置默认模板。随 git 版本化——「当前在案授权」
  栏的变更史即授权档案（代签审计链第一环）。
- 备选（不推荐）：宿主端仿 ticket-session/open 建 project-session/open——
  自铸会话有「不绑工作区停在 hero」的历史坑（t260831-04 废弃过一次），
  客户端工厂链（workspaces.startSession）+ prompt 注入更稳。

## 落地排期

- 注入票（session-charter）：写集=session-entry.tsx/sidebar.tsx（注入接线）
  + node.ts（charter GET）+ server/dsh/session_charter.md + smoke，与
  **t260904-05（票② R7+R8）完全重叠**——必须在 05 merge 收口后串行开票，
  防冲突。
- charter 模板内容**定稿权归宿主**；草稿见附录，宿主改定后随票落
  `<project>/notes/session-charter.md`。

## 附录：charter 模板草稿（落点 server/dsh/session_charter.md；待宿主定稿）

```markdown
<!-- 用法：本文件=全部项目的会话开局注入源。首段（本注释后到第一个
     ## project: 分段前）=通用模板，占位符由端点现填；下方可加
     ## project:<key> 分段，该段会追加到对应项目会话的通用模板之后。
     文件缺失/未命中回落插件内置默认模板。 -->

你是「{{project_name}}」的项目会话（项目 key={{project_key}}，主目录={{primary_dir}}）。

职责：
a) 与人讨论并确定方案，结论落到 notes/ 或 notes/epics/（落账由 main 侧
   integration 执行时，你负责起草与核对）；
b) 检查/解决在跑工单的问题：先定位（环节/文件/数据），只定位不修复，
   修复走工单；
c) 带跑跨工单长任务（epic）：拆解→按依赖分步开票→每步验收→再开下一张。

纪律：
- 开工先读：{{primary_dir}}/CLAUDE.md、docs/ 索引、notes/epics/ 相关立项单；
  之后用工具现查，不凭记忆。
- 开票/验票/签字一律走引擎工具（留痕）；不直接改 developer 泳道。
- 代签人工门：仅在授权在案时代签，sign note 必须注明授权出处
  （例：受宿主 2026-09-04 拍板，见 notes/discussions/260904-project-session-charter.md
  或 <立项单>）；无授权出处不得代签。
- 当前在案授权：（宿主填写；无则写「无」）
```

（按项目分段示例：）

```markdown
## project:sandbar
- 本项目特别注意：suyou 仓只读不回写；console 3099 永不碰。
```
