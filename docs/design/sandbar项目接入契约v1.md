<!-- 同源副本声明：本文件是 suyou 仓 docs/design/sandbar项目接入契约v1.md（v1.7，
     2026-09-03，t260903-08 落地）的**只读同源副本**；真源在 suyou 仓同名路径，
     本副本不独立演进，内容逐字自 v1.7 真源拷贝（仅本 HTML 注释为 sandbar 仓所加）。
     消费方：sandbar 安装器 `sandbar upgrade` / `sandbar doctor`（M2-C 代码票
     t260903-10）；副本漂移 guard 归后续票（交接单 §6）。 -->
---
title: sandbar 项目接入契约 v1
category: design
tags:
  - sandbar
  - 契约
  - 接入
  - schema版本
status: active
updated: 2026-09-03
---

# sandbar 项目接入契约 v1

> sandbar 是一个「IDE」——独立安装、独立升级的多项目工单引擎。项目向 IDE 注册
> 接入；IDE 升级不影响任何项目的开发和使用。本文档定义**项目接入 IDE 时的全部
> 接触面（契约）**：五样转正面，每样带 schema 版本号与关闭语义。五样之外的一切
> 都是 sandbar 内部实现，随时会变，不构成稳定承诺。
> 契约的结构骨架见本文；各样声明文件的字段级定义随配置化工单落地后补充，
> 字段细节不属于本契约文本。

## Problem（问题）

### 现状哪里不好

1. 引擎住在项目仓里（`server/dsh/`）：引擎读项目，项目背着引擎。IDE 自己的升级
   与项目的开发、使用耦合死——升级 IDE 要动项目仓，项目升级要跟着引擎走。
2. 契约未成文：`docs/` 下没有契约文件，没有 `verify.yaml`、没有 `.sandbar/`
   工作区声明。后续「就地反转」「物理搬迁」工单没有前置依据——不知道引擎
   应该经哪些文件读项目、项目应该提供什么。
3. 项目特定的策略检查（如 src 改了必须重建 bundle）没有稳定的家：它们要么硬编码
   进引擎（换一个项目不成立），要么散落各处靠纪律维持。

### 背景知识

- **sandbar 立项**：把工单驱动开发全套设施做成独立通用 IDE；关键动作是**依赖方向
  反转**——现状引擎读项目，目标形态是项目向 IDE 注册，项目仓里一行引擎代码都没有。
  路线为「契约化 → 就地反转 → 物理搬迁」，顺序不可倒。
- **机制与策略分离**：引擎只提供机制（跑项目声明的集成测试、判红绿），检查内容
  由项目自带（策略）。`server/dsh/merge-checks.yaml` 是这条路线已实证的先行样板：
  策略外置到项目仓，引擎读文件、无文件则不生效。
- **schema 版本**：契约面每样声明一个版本号。版本化是升级解耦的前提——IDE 升级
  时必须知道项目声明的是哪一版语法，项目升级时旧 IDE 必须能识别或明确拒绝。

### 证据

- 立项单 sandbar 的 M0 承诺与验收标准 4（五样转正面 + schema 版本号 + 缺文件=
  关闭语义 + 语境合成顺序）。
- 仓库现状：`docs/` 下无契约文件，无 `verify.yaml`，无 `.sandbar/` 工作区声明；
  `merge-checks.yaml` 是唯一已落地的策略外置样板。

## Requirement（需求）

以下每条都可验证，是本文档的验收标准：

1. 契约恰好转正五样，不多不少：①项目注册与目录模型；②策略配置与集成测试
   声明；③角色 persona 覆盖；④立项单内容位置；⑤工具桥协议。每样带 schema
   版本号。
2. 每样的关闭语义覆盖三态，口径明确：
   - **缺失**：文件不存在或无该项声明 = 该道关闭，引擎不得有内置默认项目策略；
   - **畸形**：文件存在但不可解析或结构不合法 = fail-closed，显式报错并指明
     是哪个文件、哪项检查失败，不得按「无声明」静默处理；
   - **版本未知或高于引擎支持** = fail-closed，报错写明项目声明的版本与引擎
     当前支持的版本区间。
3. docs 语境合成顺序成文：agent 所在 repo 的 docs ⊕ 项目级 docs；IDE docs 不进
   项目工单语境。
4. 明示哪些面是稳定契约（五样）、哪些是 sandbar 内部实现（模版六子类、插件
   API、`.suyou` 内部布局），内部实现随时会变。
5. 有契约变更记录机制：契约每次变更有记录，文档内 append 式。
6. 升级解耦机制成文：semver + 弃用先留 N 个版本旧读法 + 兼容矩阵。兼容矩阵
   只承诺机制（轴与格的定义、随版本 append 的规则），不预填 v1 之外的空格。
7. 「契约面即升级包袱、升格等第三个项目真实需求」成文：五样之外的面不进契约，
   直到出现真实项目需求。

## Nongoal（不做什么）

- **不写引擎/配置实现**：verify.yaml 的解析器、persona 合并代码、三态判定的实现
  都是后续配置化工单的事，本契约只定义「是什么、为什么」。
- **不定字段级 schema 定义全文**：本文档写每样的结构骨架与语义；字段级定义随
  配置化工单落地，不作为本契约文本的一部分。
- **不做 dsh 上游化、不改模版六子类与插件 API**：它们属于内部实现面，随时会变。
- **不预填兼容矩阵空格**：v1 只有一格已验证（schema v1 × 当前 IDE 版本），空格
  留给真实验证结果，不被读成已支持的承诺。
- **不定义多项目间的策略隔离机制细节**：「项目注册后不触发其他项目策略」的
  具体实现属内部实现；契约只保证接触面稳定。

## Proposal（方案）

### High level

契约 = 项目向 IDE 注册时的全部接触面。换项目时，项目需要提供的只有五样声明
及其承载文件；IDE 需要保证的只有五样的读取语义（含三态关闭）。其余一切——
模版怎么实现、插件 API 长什么样、`.suyou` 目录内部怎么布局——都在 sandbar
内部，项目不接触、也不该依赖。

```
项目仓                     sandbar（IDE）
┌─────────────────┐        ┌──────────────────────┐
│ 项目注册与目录模型 │ ─────▶ │ ①注册：单/多 repo、     │
│   （注册声明）     │        │   docs 三级层级        │
│ .sandbar/        │ ─────▶ │ ②策略：verify.yaml     │
│   verify.yaml    │        │   （集成测试声明）        │
│   merge-checks   │        │   merge-checks.yaml    │
│     .yaml        │        │   （扩展检查）           │
│   persona 覆盖    │ ─────▶ │ ③persona 三层合并       │
│ 立项单内容        │ ─────▶ │ ④立项单定位与加载        │
│ 工具桥入口声明     │ ─────▶ │ ⑤工具桥调用             │
└─────────────────┘        └──────────────────────┘
        五样之外 ⇄ IDE 内部：互不接触
```

取舍：刻意克制。契约面就是升级包袱——每转正一样，IDE 升版时就要背一份兼容
义务。所以 v1 只转正立项明确需要的五样，宁可让内部实现保持灵活，也不提前
把会变的东西锁成承诺。

### 关闭语义：三态总纲

五样每一项的关闭语义统一按三态判定，引擎实现不得偏离：

| 态 | 判定 | 引擎行为 |
| --- | --- | --- |
| 缺失 | 文件不存在，或文件存在但无该项声明 | 该道关闭：不执行、不报错、继续其余道。引擎不得为任何项目内置默认策略。 |
| 畸形 | 文件存在但不可解析、结构不合法 | fail-closed：显式报错，指明哪个文件、哪项检查失败；该工单对应道转红，不得按「缺失」静默跳过。 |
| 版本不支持 | 声明的 schema 版本未知，或高于引擎支持 | fail-closed：报错写明项目声明的版本与引擎支持的版本区间；不得猜测解读。 |

「缺失」态不是降级路径，是声明的本意：项目明说「这道不适用」。畸形与版本
不支持是项目说了话但 IDE 听不懂——此时宁可拒跑，不可猜着跑。现行
`merge-checks.yaml` 的「无此文件 = 无扩展检查」即缺失态语义，本契约将其纳入
三态框架，行为不变。

### ① 项目注册与目录模型（schema: v1）

**是什么**：项目向 IDE 注册时声明自己的目录结构。两个要点：

- **项目 = 目录**。单 repo 项目就是一个 repo 目录；多 repo 项目是父目录作项目
  目录、各 repo 为子目录。工单与泳道落在某个 repo；立项单与项目级策略挂在
  项目目录。
- **docs 三级层级声明**：项目声明自己的 docs 层级——IDE docs（sandbar 自身
  的文档，只服务 sandbar 开发）、项目级 docs（项目目录下，跨 repo 共享）、
  repo 级 docs（各 repo 子目录下）。注册时声明各层的位置。

**为什么稳定**：这是依赖方向反转的锚点。「项目向 IDE 注册」反转成立的前提，
是 IDE 能机械地知道「哪个目录是哪个项目、哪个 repo 归哪个项目、docs 在哪
几层」。目录模型不稳定，反转就无处可落。

**关闭语义**（按三态总纲）：未注册的项目 IDE 不服务（缺失态的边界情形，注册
声明本身就是接入前提）；注册声明畸形或版本不支持 = fail-closed。

#### ①a per-key 目录模型与装载语义（schema v1，随 t260901-14 出仓工单落地）

本节是 ① 的承载级真源。注册表出仓后（sandbar M1-1）形状：**一项目一目录**，
机器级根目录 `~/.sandbar/projects/`（env `SANDBAR_PROJECTS_DIR` 可覆盖），
注册条目 = 目录内 `project.yaml`，装载 = 扫描根目录下各项目子目录的
project.yaml。条目文件格式（严格最小 YAML 子集）：

```
schema: v1            # 必带；缺失=畸形，非 v1=版本不支持（报错写声明与支持集）
project:
  - key: <key>        # 必须与所在目录名全等；目录名/ key 同过 key 白名单
    name: <名>
    dirs:
      - /abs/path    # 首个=主目录
```

装载语义（引擎不得偏离）：

- **单条目隔离**：某条 project.yaml 畸形或版本不支持 = 该项目 fail-closed 隔离
  （错误含 `<dir>/project.yaml` 定位），不影响其他条目装载；按隔离 key 查询 =
  显式报错（非静默当未知）。根目录存在但零条目、或条目全部被隔离 = 抛错列原因。
- **目录约定**：`projects/<key>/` 下放注册条目；`projects/<key>/data/` 是引擎数据
  保留位（M1-3 迁入；metrics 缓存将来落 `data/metrics/`，路径约定统一、本单不落盘）；
  credentials 保留位由 M1-2 落地（见 ①b）。无 project.yaml 的子目录（含 data/）装载时跳过。
- **迁移**：从旧单文件注册表自动迁移，跳过判据只认根目录 `.migrated` 标记。
  无标记且根里有内容时分三类：盘上条目全是迁移源条目的精确字节子集 = 崩溃
  残留，续迁补齐并补标记；与迁移源零交集 = 人工注册表，接受；部分相关但不可
  复现 = 混合现场，fail-closed 抛错人工处置。不得静默跳过。
- **legacy 兼容**：env `SUYOU_PROJECTS_YAML` 指向旧格式单文件时按旧格式装载
  （行为与出仓前一致），优先级高于 per-key 目录模式。

### ①b per-key credentials.yaml（随 t260901-21 出仓工单落地）

本节是项目凭据的承载级真源。凭据真源迁入项目目录：
`<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/credentials.yaml`。文件格式 =
现行 `~/.dsh/.credentials.yaml` 原样——其内的 `version` 等字段由 dsh credentials
seam 自管，原样保留；sandbar 侧**不加** schema 声明字段（凭据内容不参与 IDE 升级
解耦，路径约定才是本契约面）。

读侧解析语义（引擎与项目工具不得偏离，Python/JS 两侧同构）：

1. **per-key 首选**：项目 key 过 key 白名单（同 ①a），且
   `<root>/<key>/credentials.yaml` 是文件 → 用它；
2. **legacy 回落**（弃用窗口）：per-key 未命中时回落旧全局
   `$DSH_HOME/.credentials.yaml` → `$HOME/.dsh/.credentials.yaml`，命中回落 = 项目
   凭据未迁移，须打可见提示日志；
3. **两处皆无** = 项目无凭据，读侧不拷贝（不静默造默认凭据）；既有报错
   （如 headless agent MISSING_CREDENTIAL）口径不变。

三态口径：**缺失** = per-key 未命中，回落/无凭据按声明走，引擎不得内置默认凭据
路径之外的猜测逻辑；**畸形**（内容不可解析）= fail-closed，由 dsh credentials
seam 报错——读侧只做路径解析与拷贝，不重复实现解析器；**不可读**（权限/属主）=
fail-closed，拷贝报错须含源路径，不许静默吞。引擎读凭据的位置不变
（`$DSH_HOME/.credentials.yaml`），出仓改的只是**拷贝源**——零停机：不迁文件
照常可跑（回落即 M1-2 前行为）。

迁移步骤（写侧文档化；写侧 seam 在 dsh-credentials-local 插件层，其直写 per-key
路径属后续工单，本节先立人工步骤）：

```
mkdir -p ~/.sandbar/projects/<key>/
install -m 0600 ~/.dsh/.credentials.yaml ~/.sandbar/projects/<key>/credentials.yaml
```

原 `~/.dsh/.credentials.yaml` 保留至 legacy 回落删除，防迁移窗口断供。

### ①c per-key 引擎数据目录 data/tickets/（随 t260902-02 出仓工单落地）

本节是完结工单数据归档的承载级真源（sandbar 关键决策 3 本体）。归档真源出仓到
机器级 per-key 数据目录：

```
<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/data/tickets/<ticket_id>/
├── archive.json          # manifest（schema v1，骨架见下）
├── stages/               # .suyou/stage_*.json（stage 结果/结算报告）
├── screenshots/          # .suyou/screenshots/**/*.png（UI 证据，保相对层级）
└── sessions/             # <worktree>/.dsh/sessions/<repo-slug>/*（会话落盘事件文件）
```

**为什么稳定**：根因是「完结工单 stage 报告随泳道拆除丢失」+「Temporal 保留期
无上界」（2026-09-01 实测 31MB/40 票）。归档是 IDE 的数据，审计真源归机器级
IDE 数据目录；项目仓（含泳道 worktree 与主树 `.suyou/`）只留可弃缓存
（node_modules 待遇）。dev-lane 收口顺序为此定型为三段：`merge`（只落账）→
`archive_ticket`（出仓，fail-closed）→ `teardown_lane`（拆泳道）——归档成功
是拆泳道「不丢报告」的前提。

**archive.json manifest 骨架**（schema v1；字段细节属 sandbar 内部实现，不进契约）：

```json
{"schema": "v1", "ticket_id": "<id>", "legacy": false, "archived_at": "<ISO>",
 "meta": {…}, "files": [{"src": "…", "dst": "…", "bytes": 0}],
 "absent": [], "excluded_rules": [], "reason": "…"}
```

入档口径（三系）：stage 结果文件、UI 截图、会话落盘。**排除**口径（记入
`excluded_rules`，不入档）：agent spawn 运行时日志、model/resume patch、
profile 镜像、**一切 `.credentials.yaml`（凭据绝不入档）**。文件按字节级拷贝
（坏 JSON 原样入档，归档不解析内容，消费侧读时才判畸形）；会话目录缺失 =
软处理（manifest 记 `absent`，同 usage 端点既有降级口径）。

`legacy: true` 语义：存量诚实过账——「归档前泳道已拆除、stage 报告不可恢复」
的历史工单，`ticket archive-legacy` 写空文件清单 + 明牌 `reason` 的 manifest，
**不伪造不补产**；`ticket prune` 对 legacy 票需 `--allow-legacy` 双旗才删。

**关闭语义**（按三态总纲）：

| 态 | 判定 | 引擎行为 |
| --- | --- | --- |
| 缺失 | `<key>/data/tickets/<id>/archive.json` 不存在 | 该票「未归档」：prune 拒删（Temporal 历史保留，历史不蒸发） |
| 畸形 | manifest 不可解析 / 缺 `schema: v1` | fail-closed：prune 计失败、人工处置；archive_ticket 见已存在 manifest 畸形时**不静默重产**（重产即消灭证据），上抛转 blocked 泳道不拆 |
| 拷贝失败 | 目标不可写 / IO 失败 | fail-closed：archive_ticket 上抛 → 工单 blocked、泳道保留 |

### ①d project.yaml paths 节：项目内路径声明（schema v1，t260903-03 随引擎消费点落地）

本节是项目内路径的承载级声明：引擎不得再约定「项目内某固定路径」（sandbar M2
物理搬迁的前置——独立仓后引擎与项目不再同仓）。项目在注册条目
`<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/project.yaml` 顶层声明可选
`paths` 节，引擎经注册表取值。现行两处消费点：①角色 preset patch 与岗位说明书
目录（spawn 时 `<泳道>/server/dsh/roles/<role>.yml`；prompt 装配的 role_doc 同源）；
②模型路由表（运行时查表文件）。声明形状（与 ①a 严格最小 YAML 子集同传统）：

```
schema: v1
project:
  - key: <key>
    name: <名>
    dirs:
      - /abs/path
paths:                     # 可选整节；缺 = 全部回落现行约定
  roles_dir: server/dsh/roles                   # 角色目录，相对项目根
  model_routes: server/dsh/model-routes.yaml    # 模型路由表文件，相对项目根
```

**schema 保 v1**：纯增量可选字段，旧条目（无 paths 节）解析行为不变。援引 ②a
v1.5 裁定：勘误与增量不升 schema 版，不触发 semver 升版义务。

**解析基准**：`项目根` = 注册条目 `dirs[0]`（主目录）。两条声明必须是非空相对
路径（strip 后判空 = 畸形，纯空白值同），禁绝对路径、禁 `..` 越界、禁 `~` 与
非标量（`{}`/`[]` 形）。基准差异是声明语义的一部分：`roles_dir` 相对 **spawn
cwd（泳道 worktree）** 解析——保「worktree 内副本 = 工单快照」语义；`model_routes`
相对**项目主目录（dirs[0]）** 解析——保运行时真源随主仓、不随泳道漂移的现行语义。

**读取器解析子集（引擎侧 stdlib-only 手写，与 ①a 装载器同口径：值不含 `#`、
行尾 `#` 起截断）**：顶层只认 `schema:`、`project:`、`paths:` 三键；`schema`
必须存在且为 `v1`（缺失 = 畸形，非 v1 = 版本不支持）；paths 节内只认
`roles_dir`、`model_routes` 两键，未知键、节本身非映射、键值非标量、嵌套加深
一律畸形。`project:` 节内的条目字段形状归 ①a 装载器管——读取器只取 `dirs`
首项作解析基准，不复验条目全形（装载器在建票/注册时已 fail-closed 同一文件；
两层读者职责不重复）。

**四态判定（引擎读取器不得偏离）**：

| 态 | 判定 | 引擎行为 |
| --- | --- | --- |
| 回落 | 无 paths 节 / 节内缺某键 / 条目文件不存在 / project key 为空、不过白名单或项目未注册 | 该项回落现行约定（`server/dsh/roles`、`server/dsh/model-routes.yaml`），行为与未出仓前逐字节一致。suyou 不声明 paths，零改动零回归 |
| 畸形（声明值） | 声明值非相对 / `..` 越界 / 空或纯空白 / 非标量 / paths 节非映射 / 未知键 | fail-closed：显式报错，含条目文件路径与键名，不静默过滤（同 ②c 纲） |
| 畸形（条目文件） | project.yaml 存在但顶层形状不可解析（顶层未知键、schema 缺失或非 v1、非 UTF-8） | fail-closed：报错点名 `<key>/project.yaml` 与原因，**不回落不静默**——spawn 时段该文件唯一读者就是本读取器，按「缺失」跳过即三态总纲禁止的猜着跑 |
| 声明锚点缺失 / 错位 | `model_routes` 解析后不存在或非文件；`roles_dir` 解析后不存在或非目录 | fail-closed 红：报错点名解析后绝对路径（缺失与类型错位都点名同一路径，语义分开写明） |

**锚点 vs 内容**：fail-closed 只覆盖声明锚点本身，不覆盖声明对象的内容语义。
两条边界裁定随本节成文：①`roles_dir` 声明后某具体角色的 yml/md 缺失 = 维持
既有软跳过（缺 patch 退化为默认 persona，契约③「只加不改」）；②`model_routes`
声明表存在但 role 条目查不到 = 维持查表函数返回空（agent 用 profile 默认模型）。
同纲：`model_routes` 声明表**内容**不可解析，继承查表函数既有容错语义（返回空
→ 默认模型），与未声明回落路径同语义——本节四态只覆盖声明值与锚点，不覆盖表
内容；若需表内容 fail-closed，另立工单升语义。

**过渡状态**：现行注册表装载器（`server/tools/ticket.py` 条目解析顶层白名单
只认 `schema:` 与 `project:`；`server/dsh/suyou-projects.ts` 同构）对顶层
`paths:` 节按「顶层只认两键」拒收——放开工单落地前，任何项目声明 paths 即被
①a 单条目隔离（fail-closed 可见，不静默）。**本节语义以装载器放开工单落地为
生效前提**；suyou 不声明 paths，不受影响。引擎侧消费点（spawn 取角色目录与
路由表路径、prompt 装配 role_doc）已按本节取值，回落态与现行约定一致。

### ② 策略配置与集成测试声明（schema: v1）

**是什么**：项目在工作区（约定目录 `.sandbar/`）声明两类策略文件：

- **verify.yaml——集成测试声明**：集成测试的入口命令、红绿判据、超时。dev-lane
  的 integration 段是纯机制：跑项目声明的集成测试、按声明的判据判红绿，引擎
  不夹带任何项目特定判断。sandbar 测安装/接线/升级，suyou 测自己的四件套，
  互不夹带，各项目自带内容。
- **merge-checks.yaml——扩展检查**：合并检查门的项目特定扩展（现行
  `server/dsh/merge-checks.yaml` 即此样板的实例：src 前缀有改动而 out 前缀
  无改动即红）。格式约束：引擎内置解析的最小 YAML 子集，值一律裸 token。

**为什么稳定**：这是「机制与策略分离」的落点，也是「检查是项目相关的」问题的
终局答案。检查内容若写进引擎，换一个项目就不成立；只有声明进契约，引擎才能
真正做到零项目特定逻辑。schema 版本化让引擎升级时知道按哪版语法读。

**关闭语义**（按三态总纲，t260903-01 勘误对齐引擎）：verify.yaml 整文件缺失 =
**两路**：① code 道按项目声明关闭（green 项可见非静默）；② integration 道
**fail-closed 报错**——integration 道没有「缺失=关闭」态，凡调道必判（见 ②b）。
旧口径「integration 段无集成测试可跑，按既有空转口径」作废（引擎薄壳化后缺失
即 err，不空转）。merge-checks.yaml 缺失 = 无扩展检查，与现行行为一致（缺失态）；
文件畸形或版本不支持 = fail-closed，报错指明文件与检查项。

### ②a verify.yaml 字段级定义（schema v1 真源；t260901-08 落地，t260903-01 按实现重写）

本节是 ② 的字段级真源。声明值 `v1` ↔ 引擎读法 `'v1'`（字符串全等比较），支持集={"v1"}。
承载位置由项目注册自定（suyou 注册在仓库根 `verify.yaml`；契约示例的 `.sandbar/` 不是硬性路径）。

**schema 保 v1 裁定**（v1.5）：本节 v1.1 版曾载五类型键式字段表（已退役失真键式：
`checks.shotdebug.file`/`checks.deps_dir`/`checks.tsc.cwd`/`checks.smoke.dir` 与
`integration.entry`/`integration.red_green.*`）——该形状**引擎从未实现**，属文档
超前于实现的失真；现行引擎读法自始就是列表命令制（见下表）。本次以实现为真源
回写，属勘误而非已发布语法被破坏，故 schema 不升版、不触发 semver 升版义务。

| 字段 | 类型 | 语义 | 键缺失时 |
| --- | --- | --- | --- |
| `schema` | 裸 token，支持集 {v1} | 语法版本声明 | 畸形（版本是接入前提，不猜） |
| `lanes.code.write_allow` | 非空前缀/路径列表（块列表或行内 `[...]`） | code 道写集白名单粗判据；合并闸传工单 write_set 时按工单精判，此处兜手动调用。`.suyou/`、`.dsh/` 引擎运行时目录一律不判 | 畸形（声明 code 道即须声明写集边界，不猜） |
| `lanes.code.checks` | 非空列表 `[{id, cmd, cwd?, timeout?}]`（**列表命令制**，无类型词表） | code 道命令检查：`id`=人读名；`cmd` 经 `/bin/sh -c` 执行，exit 非零=红；`cwd` 相对声明根（缺省 `.`）；`timeout` 秒（缺省 600）。各条并行跑 | 该项关闭（整键可省略；在位而结构不合法=畸形） |
| `integration.cmd` | 非空字符串（一条命令） | integration 道唯一声明：引擎 `/bin/sh -c`、cwd=声明根执行；红绿判据=退出码 + ②b 三行协议解析；整体超时 env `SUYOU_INTEG_BATCH_TIMEOUT_SEC`（缺省 5400） | integration 段整体缺失 = integration 道 fail-closed（②b：本道无「缺失=关闭」态）；段在位而 `cmd` 缺失或为空 = 畸形 fail-closed |

一切未知键（顶层/`lanes`/`lanes.code`/checks 条目级，含旧五类型键式）= 畸形
fail-closed，不静默过滤。

缺失态映射（勘误后口径，防误读）：**verify.yaml 整文件缺失 = ① code 道按项目
声明关闭（t260901-08 扩展；green 项可见非静默）+ ② integration 道 fail-closed
报错（t260903-01 勘误；见 ②b）**。前者是声明的本意，后者是引擎「凡调道必判」
的语义；两者都不是降级路径，引擎不得据此回退到任何内置默认策略。

### ②b 输出契约 = 接入方对 verify 道的全部可编程接触面（v1.5 入约）

#### ②b-1 integration 道「输出契约三行」（integration.cmd 的字符级子契约）

场景执行器（integration.cmd 的项目侧实现）按三行协议输出：

1. `PASS [场景名]` —— 一条场景绿；
2. `FAIL [场景名] exit=<code>` —— 一条场景红；其后**四空格缩进行**为该场景的
   输出尾段（引擎逐行收进，截尾 4000 字符）；
3. 末行 `SCENARIOS ran=N pass=N fail=N` —— **参考性日志/人读汇总行**：引擎解析
   只认前两类行与缩进行，**不读本行、也不校验它与明细的一致性**（汇总与明细
   不一致不会被判红）；产出它是执行器的输出惯例，不构成引擎判据。

红绿判据（引擎机械执行，零项目策略）：

- **绿 = 执行器退出码 0 且解析出的 fail=0**。
- exit 非零必不绿；无任何结果行（ran=0）且 rc≠0 = **err 态**（非红非绿）：
  执行器未产出结果，属测试道自身故障，上抛交仲裁。
- FAIL 行格式不符按 name=整行、exit=-1 计——畸形输出不静默吞。
- **零场景绿**：ran=0 且 rc=0 = 绿（ran=0, pass=0, fail=0）。引擎**不强制**
  stdout 产出三行协议——缺协议即得零场景绿，这是引擎不校验的事实（风险面），
  接入方自检须含至少一条必红场景验证。**integration 道没有 code 道那种
  「缺失=关闭」态（见 ②a）；要表达「该道无事可做」，声明一条恒成功空命令
  （如 `cmd: true`）得零场景绿——这是本道唯一的关闭惯用法。**
- **err 语义**：err 非 null ⇒ green 恒 false 且 ran/pass/fail 无意义。「验证本身
  没跑成」（verify.yaml 缺失/畸形、cmd 缺失或为空、执行器整体超时、零结果）与
  「跑成了但有场景红」是两类结果，消费方据此分流测试道故障与场景红。

#### ②b-2 verify_lane 分道返回形状（JSON API）

- **content/code 道**：`{lane, green, red_count, checks:[{check, level,
  items:[{detail}], note?}]}`，level ∈ {red, green}，red_count = 红项 items 数之和。
- **integ 道**：`{lane, green, ran, pass, fail, scenarios:[{name, exit,
  output_tail}], err}`；各失败路径返回 `{lane, green:false, err}`——没有
  red_count/checks，消费方不得按 content 形状读 integ。
- 此二形状 = 接入方对 verify 道的全部可编程接触面：合并闸、工作流 verify 步、
  工作台 UI 一律消费该形状，**不得旁路自行读 verify.yaml 重新判定**。

### ②c 手写解析器语法子集 = 可写域

verify.yaml 由引擎内置手写解析器读取（stdlib-only，裸 python3 无 pyyaml）。
**项目可写域 = 下述子集能表达的形状；写出子集之外的 YAML 即拒收（畸形
fail-closed），引擎不做宽容解析。**

支持的语法形态（每形态一条正例，测试钉死）：

- 两空格缩进嵌套映射；tab 展开为两空格；
- 裸 token 标量与引号标量；
- `- ` 字符串列表（块列表）与行内流列表 `[a, b]`；
- `- k: v` 列表套映射（checks 条目），条目后续更深缩进行并入该条目；
- 注释：行首 `#` 跳过；值内 ` #`（# 前有空格）才截断——`url#anchor` 等紧贴
  `#` 的值不误伤。

fail-closed 声明：未知行、未知键、结构残缺一律报错转红，**不静默过滤**——
verify.yaml 是道的本体声明，残缺即按三态总纲之「畸形」fail-closed。

### ②d 薄壳执行拓扑 = 工具单源

- code 道 checks 与 integration.cmd 均由引擎经 `/bin/sh -c` 执行：cwd 取声明值
  （相对**声明根** = verify.yaml 所在目录；主树即仓库根，泳道内即 worktree 根）、
  timeout 取声明值、并行跑（独立子进程，超时杀进程回收终态）。
- 项目侧入口是**薄壳**：一切项目工具逻辑收在项目仓单源执行器内（suyou 实例 =
  仓库根 verify.yaml 指向 `integration/run_scenarios.py`；SCENARIOS 三元组、
  sc_ 前缀铁律、池调度属项目内部约定，不进契约）。
- 引擎零项目策略：不内嵌任何项目工具、不感知「场景」概念，只跑声明命令、按
  ②b 判红绿、透传输出尾段。执行与解析全天下唯引擎一份——上层只下单 + 翻译 JSON。

### ②e 复用三级 + rule of three

复用分三级：

- **一级 = 引擎机制**：跨项目通用，属 sandbar（verify 道跑与判、三态判定、
  薄壳执行拓扑——即本契约各章）；
- **二级 = 项目仓共享层**：项目内多场景共用的模块/夹具（suyou 实例 =
  integration/ 下不带 sc_ 前缀的共享代码）；
- **三级 = 场景私有**：sc_ 前缀场景文件自带，不外借。

抽象门槛 = **rule of three**：同形重复出现第三次才下沉升一级，宁重复勿早抽象。
一级升格另受「第三个项目真实需求」总原则约束（见升格原则节）。

### ③ 角色 persona 覆盖（schema: v1）

**是什么**：项目可在工作区声明角色 persona 覆盖，叠加在 sandbar 内置角色骨架
之上。合并为三层：内置角色骨架（流程/纪律/输出格式，随 sandbar 走）⊕ 工作区
persona 覆盖（业务语境，项目自带）⊕ 机器级默认。覆盖只加业务语境，不改骨架
的流程与纪律。

**为什么稳定**：角色骨架会随 sandbar 升级（内部实现面），但「项目要给自己的
业务上下文」是所有项目的真实需求，且需求形态稳定——就是一份覆盖声明。把它
转正，IDE 升级换骨架时项目只需保留覆盖文件。

**关闭语义**（按三态总纲）：无覆盖 = 纯骨架（缺失态，也是多数项目的状态）；
覆盖声明畸形或版本不支持 = fail-closed，宁可拒跑不静默退回纯骨架——退回纯
骨架意味着项目自认的业务语境被悄悄丢掉。

### ④ 立项单内容位置（schema: v1）

**是什么**：立项单（epic）的内容挂在项目目录下，具体位置由项目注册声明，
不写死任何项目的既定路径。sandbar 经注册声明找到立项单内容，承载「立项 =
目标 + 验收标准 + 关键决策 + 归档快照」的完整生命周期。

**为什么稳定**：立项单是工单之上的语义单元，工单与立项的关联靠机器可查的
立项代号（见机制文档「立项单与工单关联」）。代号存在性以文件存在性作强校验，
所以「立项单在哪」必须是契约问题而不是约定俗成。

**关闭语义**（按三态总纲）：项目无立项单 = 该维度功能关闭（工单仍可跑，无
立项维度）；立项单内容位置声明畸形或版本不支持 = fail-closed。

### ⑤ 工具桥协议（schema: v1）

**是什么**：项目自带的管理/运维工具（admin 脚本那类）经声明暴露给 agent 使用。
协议 = 入口声明（工具在哪、怎么调用）+ 调用约定（输入输出形态）。工具内容
项目自带，IDE 不规定项目工具做什么。

**为什么稳定**：工单执行中 agent 常需触发项目特定的机械动作（建单、查状态、
触发发布）。这个接触面是所有项目的真实需求；把「怎么暴露」转正，工具本身
的实现仍在项目手里，IDE 升级不影响。

**关闭语义**（按三态总纲）：无声明 = 无工具桥可用；声明畸形或版本不支持 =
fail-closed，报错指明哪个入口声明失败。

### ⑧ dsh 平台兼容区间与升版必查项（schema: v1，t260903-08 随契约成文落地）

> 本节是 sandbar 对 **dsh 平台层**的兼容承诺真源（关键决策 4「dsh 零 patch、
> 跟版升级」的承载条文），属 sandbar 自报面而非项目声明面——项目不写它，
> 但项目的可用性受它约束。消费方：sandbar 安装器（`sandbar upgrade`）、
> 兼容矩阵探针集（`sandbar doctor`）。

**⑧-1 兼容区间声明**：sandbar 对 `@deepseek-ai/dsh` 的兼容面以**已验证点列举**
为口径，不写数学区间——每一个已验证点都必须有探针绿证据背书。已验证点：
`0.1.1-rc.2`（唯一数据点，2026-09-03）。扩点规则：新 dsh 版本须在 sandbar
探针集全绿后才 append 进本清单；未列举的版本 = 未验证（不是不支持，是没证据）。

**⑧-2 升版必查项**（真源=`notes/debts/sandbar-m0-dsh-touchpoints.md` 汇总节，
随本节转正；dsh 升级时逐条复扫，任一失配 = 区间不扩）：

1. **settings/resolve 层叠顺序**（touchpoints A3）：GUI 默认模型段与声明层
   patch 的合成次序变更，会使「路由优先于 GUI」语义静默失效；
2. **headless runner 装配与启动钩子**（A4/A5）：stock runner 的 cordis id、
   `inject:[headlessStartup]` 注入点、`DSH_HEADLESS_SESSION` 约定任一变更，
   会话延续 patch 失效（表现为会话延续静默丢失，非硬失败）；
3. **dsh home 布局与会话存储格式**（B1/C1/C2）：profiles/credentials/settings
   目录布局与文件名、会话落盘路径、压缩格式（zstd 行式事件流）、事件字段
   （`data.usage`、`request/context|header`）任一变更，波及 spawn 拷贝链与
   workbench 观测面；
4. **headless SIGTERM 语义**（D1）：terminate 后「会话文件完整+无孤儿」的
   假设变更，表现为「agent 退出未写结果文件」红（显式可观测，不静默）。

**⑧-3 兼容矩阵机制**：矩阵行 = **sandbar 版本 × dsh 已验证点 × 项目 schema
版本**，探针跑绿一条 append 一条（append 制，落 `~/.sandbar/compat-matrix.json`，
schema 由 sandbar 仓维护）；矩阵空格 = 未验证，不承诺支持。

**⑧-4 版本自报口径**：引擎快照对外自报 `sandbar_version`（semver，读 sandbar
仓根 VERSION，自 `0.1.0` 起）；历史快照的 `temporal_engine_version` 整数键
**原值保留不迁移、不造历史 semver 映射**（v2 时代的引擎从未以 semver 存在，
事后映射即伪造历史）；消费方遇未知 int 按历史口径原样展示，遇 `sandbar_version`
畸形（非 semver）= fail-closed 红。两键并存，legacy int 键不作废。

**⑧-5 升版执行序**：dsh 新版本放行路径 = 探针集全绿 → ⑧-1 清单 append →
sandbar 发版 → 项目跟进；禁止跳过探针直接扩区间（关键决策 4 的机制化）。

### docs 语境合成顺序

知识库是 IDE 的一等组件，docs 三级 = 三级工作语境。agent 干活时的语境合成：

- **取「所在 repo 的 docs ⊕ 项目级 docs」**：repo 级是工作语境的主体，项目级
  提供跨 repo 共享的语境，两者合成。
- **IDE docs 不进项目工单语境**：IDE docs 只服务 sandbar 自身的开发。例外不是
  通道而是身份——dogfood 时 sandbar 自己的仓库注册为项目，IDE docs 以「该
  项目的项目级/repo 级 docs」身份进入语境，走的是注册后的正常合成，不是旁路。

合成顺序与三态独立：docs 层的缺失就是该层语境不存在（docs 目录没有即没有），
不存在「docs 畸形 fail-closed」的判定——docs 是自然语言文档，不适用 schema
版本，结构不合法时由知识库组件按自身口径处理。

### 稳定契约面 vs 内部实现面

| 面 | 内容 | 承诺 |
| --- | --- | --- |
| 稳定契约 | 五样：注册与目录模型、策略与集成测试声明、persona 覆盖、立项单位置、工具桥协议 | 遵守 semver；变更走变更记录；弃用先留 N 个版本旧读法 |
| 内部实现 | 模版六子类、插件 API、`.suyou` 内部布局，及其余一切 | 随时会变，项目不得依赖；不进契约 |

升格原则：**等第三个项目出现真实需求**。某内部实现面被两个以上项目真实需要
时，才评估转正进契约；转正即背升级包袱，宁慢勿滥。

### 升级解耦与兼容矩阵

契约面的升级解耦靠机制不靠纪律：

- **semver**：sandbar 按语义化版本发布，契约面变更体现在版本号里。
- **弃用先留 N 个版本旧读法**：契约某项弃用时，旧读法保留 N 个版本，项目有
  明确的迁移窗口。
- **兼容矩阵**：轴 = 项目声明的 schema 版本 × IDE 版本（dsh 版本轴由 sandbar
  对 dsh 的兼容区间声明承载，见机制文档；v1.7 起细化为三轴——IDE 版本轴 =
  sandbar 版本 + dsh 区间的复合，见⑧-3）。矩阵只承诺机制——轴与格的定义、
  随版本验证 append 的规则；空格不代表「已支持」，只代表「未验证」，v1 仅
  一格已验证：schema v1 × 当前 IDE 版本。

### 契约变更记录机制

本文档末尾维护 append 式「变更记录」表（版本 / 日期 / 变更内容 / 影响面）。
契约每次变更——新增转正面、schema 升版、关闭语义修订——必须落一条记录；
记录与契约正文同真源（git），不依赖执行引擎。升格（内部实现面转正）同样
走记录，并标注驱动它的项目需求。

### 回扣

- 解决 Problem 1（引擎住项目仓、耦合死）：五样定义了反转后的全部接触面，
  项目仓不再背引擎。
- 解决 Problem 2（契约未成文、后续工单无前置）：五样、schema 版本、三态
  关闭语义全部成文，就地反转与物理搬迁工单有了可引用的契约。
- 解决 Problem 3（项目策略无稳定的家）：策略配置与集成测试声明转正（Requirement
  1、2），机制与策略分离落到可验证的条文。
- 满足 Requirement 3（语境合成顺序）、4（稳定/内部边界）、5（变更记录）、
  6（semver/弃用/兼容矩阵机制）、7（升格原则）各有专节。
- Nongoal 划出的实现细节、字段级定义、矩阵空格，全部留给后续工单，本文不碰。

### 变更记录

| 版本 | 日期 | 变更 | 影响面 |
| --- | --- | --- | --- |
| v1 | 2026-08-31 | 首版成文：五样转正面（schema v1）、三态关闭语义、语境合成顺序、稳定面/内部实现边界、升级解耦机制、升格原则 | 全部五样；后续配置化/反转/搬迁工单的引用基准 |
| v1.1 | 2026-09-01 | t260901-08 配置化工单落地：verify.yaml 字段级定义成文（新增 ②a 节：lanes.code.write_allow/checks、integration.entry/red_green）；承载位置定为项目注册自定（suyou=仓库根，非 .sandbar/）；缺失态映射扩展——verify.yaml 缺失除 integration 段无测试可跑外，code 道亦按声明关闭（green 可见非静默） | ②/②a；verify_lane code 道 |
| v1.2 | 2026-09-01 | t260901-14 出仓工单落地：注册表真源出仓为机器级 per-key 目录 `~/.sandbar/projects/<key>/project.yaml`（新增 ①a 节：条目格式、单条目隔离三态、目录/data/metrics 路径约定、.migrated 迁移判据与三类现场处置、legacy env 兼容）；凭据与引擎 data 仅立路径约定不动内容（M1-2/M1-3 迁） | ①/①a；注册表装载器（TS/Python 两侧同构） |
| v1.3 | 2026-09-01 | t260901-21 凭据出仓工单落地：凭据真源迁入 `<root>/<key>/credentials.yaml`（新增 ①b 节：读侧两级解析=per-key 首选+legacy 弃用窗口回落、三态口径、拷贝源/读取位分离的零停机语义、人工迁移步骤）；引擎读凭据位置与 dsh credentials seam 不变 | ①/①b；读侧拷贝点（agent_activities.py、ui-check） |
| v1.4 | 2026-09-02 | t260902-02 引擎数据出仓工单落地：完结工单归档真源出仓为 per-key 数据目录 `<root>/<key>/data/tickets/<id>/`（新增 ①c 节：三系入档/排除口径、archive.json manifest 骨架、legacy 诚实过账语义、三态关闭语义）；dev-lane 收口定型为 merge→archive→teardown 三段（归档 fail-closed 是拆泳道前提）；Temporal 回归运行态=`ticket prune` 主动清理 closed 且已归档的 workflow 历史（默认 dry-run、legacy 双旗） | ①/①c；dev-lane 三段收口、archive_ticket/teardown_lane activity、client.py ticket-prune/ticket-archive-legacy |
| v1.5 | 2026-09-03 | t260903-01 声明制对齐：②a 按引擎实现重写为 v2 列表命令制（`checks=[{id,cmd,cwd?,timeout?}]`、`integration.cmd`；v1.1 五类型字段表系文档失真——引擎从未实现，勘误不升 schema 版，裁定随 ②a 入文）；② 缺失态勘误（integration 道 fail-closed，「空转口径」作废）；新增 ②b 输出契约（三行协议+分道返回形状+err 语义+零场景绿关闭惯用法）、②c 手写解析器语法子集=可写域、②d 薄壳执行拓扑=工具单源、②e 复用三级+rule of three | ②/②a/②b/②c/②d/②e；verify_lane code/integ 道 |
| v1.6 | 2026-09-03 | t260903-03 路径契约化落地：新增 ①d——project.yaml 顶层可选 `paths` 节声明项目内路径（`roles_dir` 角色目录相对 spawn cwd 泳道快照解析、`model_routes` 路由表相对主目录解析），引擎 spawn 取角色目录/路由表、prompt 装配 role_doc 改经声明取值；四态判定（回落四类零回归 / 声明值畸形 / 条目文件畸形 / 声明锚点缺失或错位=fail-closed 红点名文件）、锚点 vs 内容边界（per-role 缺失软跳过、表内容损坏继承查表容错）、过渡状态（现行装载器顶层白名单未放开 paths，声明即被 ①a 隔离——①d 以放开工单落地为生效前提）；schema 保 v1（增量可选字段） | ①/①d；agent_activities spawn 两消费点、shared.py prompt 装配与模型路由查表；注册表装载器（TS/Python）待放开工单 |
| v1.7 | 2026-09-03 | t260903-08 dsh 兼容区间成文：新增 ⑧——dsh 平台兼容区间声明（已验证点列举制，当前唯一点=0.1.1-rc.2，扩点须探针绿后 append）、升版必查项四条转正（touchpoints 汇总节 A3/A4+A5/B1+C1+C2/D1）、兼容矩阵三轴机制（sandbar 版本×dsh 已验证点×项目 schema 版本，append 制）、引擎版本自报口径（`sandbar_version` semver 自 0.1.0 起；历史 `temporal_engine_version` int 原值保留不造映射，畸形 fail-closed）、升版执行序（探针绿→扩区间→发版→项目跟进）；「升级解耦与兼容矩阵」节两轴表述补 v1.7 三轴衔接（IDE 轴=sandbar+dsh 复合）。安装器/探针/VERSION 代码面=sandbar 仓 M2-C 代码票承接（交接单 notes/debts/sandbar-m2-c-installer-handoff.md） | ⑧（新增）；「升级解耦与兼容矩阵」节；消费方=安装器 upgrade/doctor 探针集（代码票待落地） |

> 来源立项：sandbar

## 相关文档

- [DeepSeek Harness and Temporal based multi-agent mechanism](../design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md)——机制真源；五层架构与依赖方向反转见其中专节
- [设计文档写作指南](../design/设计文档写作指南.md)——本文的结构依据
- 立项单 `notes/epics/sandbar.md`——「契约第一版（刻意克制）」与关键决策 4/5/6/7 的出处
