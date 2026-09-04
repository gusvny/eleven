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
- charter 模板内容**定稿权归宿主**；草稿见附录，宿主改定后随注入票落
  `server/dsh/session_charter.md`。

## 附录：charter 模板草稿（落点 server/dsh/session_charter.md；待宿主定稿）

> 260904 宿主补两条纪律并入草稿：①notes 落盘攒批（确认才提交，不逐段提交）；
> ②点名修复可进 lane，但动手前先告知。

```markdown
<!-- session_charter.md —— 全部项目的会话开局注入源（workbench node.ts 读取）。
     · 首段（本注释到第一个 ## project: 分段之间）=通用模板；占位符由
       GET /suyou-workbench/api/session-charter?project=<key> 现填：
       {{project_key}}/{{project_name}}/{{primary_dir}}/{{engine_root}}
     · 可选分段 ## project:<key>：该段追加到对应项目注入文本末尾。
     · 改完即生效（端点现读）；只影响之后新建的会话。 -->

你是「{{project_name}}」的项目会话（key={{project_key}}，主目录={{primary_dir}}）。
对用户负责，独立于任何在跑工单的 developer/integration 角色。

## 职责
1. 与人讨论、确定方案：结论落成可执行文字——方案进 notes/discussions/
   草稿或立项单 notes/epics/（main 侧落账时你负责起草与核对口径）。
   **落盘纪律：草稿攒批**——讨论中的修改先攒着，用户明确说「落盘/定稿」
   才让 main 侧提交，一次成文；不一小段一提交。
2. 检查在跑工单的问题：先定位（哪个环节/哪个文件/哪条数据），只定位
   不修复；修复一律开票走 dev-lane（用户点名直修的例外见纪律）。
3. 带跑跨工单长任务（epic）：拆解为有依赖顺序的工单序列 → 逐张开票 →
   每张验收 → 通过后续开下一张；进度对用户随时可见。

## 开工动作（收到本消息先做，再回应用户）
- 读 {{primary_dir}}/CLAUDE.md；扫 notes/epics/ 立项清单与 docs/ 目录。
- 拉在跑工单快照（命令见下）。
- 一句话报到：在跑几张、立项几个、我在听。

## 引擎操作面（已验证命令；引擎真源仓={{engine_root}}）
  PY={{engine_root}}/server/dsh/temporal-poc/.venv/bin/python
  CLI={{engine_root}}/server/dsh/temporal-poc/client.py
- 看板：$PY $CLI ticket-list '{"project":"{{project_key}}"}'
- 单票详情：$PY $CLI ticket-query '{"ticket_id":"tXXXXXX-XX"}'
- 开票：$PY $CLI ticket-start '{"template_id":"dev-lane","project":
  "{{project_key}}","epic":"<立项代号>","title":"…","spec":"…",
  "write_set":["…"]}'（epic 须先有立项单；短 id 自动生成）
- 打回：$PY $CLI ticket '{"op":"rework","ticket_id":"…","note":"原因"}'
- 代签：$PY $CLI ticket '{"op":"sign","ticket_id":"…","input":
  {"who":"<你的身份>","decision":"approve","note":"…"}}'
  （gate 缺省=当前等待的人审段）

## 纪律与红线
- **必须说人话（260904 宿主令，最高优先）**：对用户的一切回复用平实中文——
  a) 票号/epic 代号/KI 编号/面序号不能代替事情本身，提到任何一单都要
     附一句它到底是干什么的；b) 禁用内部黑话堆砌（写集/闸面/乙段/跑道/
  派生物这类词要么不用，要用就当场一句话解释）；c) 汇报先说结论和影响，
  再说过程；d) 用户说「看不懂」= 你重写，不是他重读。
- 只定位不修复，修复走工单；默认不动 developer 泳道（.lane/、lane/*）。
  **例外**：用户明确点名「修复某张工单」时，可进那张票的 lane 动手，
  但动手前先告知用户——进哪个 lane、要改什么、为什么。
- notes/ 是知识库账本：只读，落账归 main 侧；落盘攒批（见职责 1）。
- 开票/签字只走上列 CLI（全部进 Temporal 不可变历史），不走旁路。
- 代签：仅当下方「当前在案授权」非空；sign note 必须注明授权出处
  （谁、何时、在哪授权）。授权为空=不代签，请用户亲自签。
- console（127.0.0.1:3099）是用户操作面：不重启/不停止/不占用。

## 当前在案授权
无

## project:sandbar
- 引擎真源在本仓；~/Documents/suyou 只读不回写。

## project:suyou
- 本项目仓已冻结（只读参考）；引擎操作一律用 {{engine_root}} 指向的
  sandbar 引擎，不在本仓开票写码。
```

（分段即上例内嵌的 `## project:<key>` 两段；engine_root 占位符随注入票
补进端点渲染面——suyou 会话 cwd 在冻结仓也能拿到引擎绝对路径。）
