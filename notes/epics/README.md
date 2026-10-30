# 立项产物目录约定（宿主 261030 定：b）

## 结论

立项（epic）自己的**产物**放在 `notes/epics/<代号>/`，与立项单 `notes/epics/<代号>.md` 同级。

立项产物指：属于**某一个立项**、供人看的设计材料——界面 mock、样张、流程图、评审截图、草稿。
它们不是文档正文（文档正文在 `docs/`），也不是引擎/契约真源（真源在 `server/`、`integration/`）。

## 为什么是 b 而不是 `docs/epics/<代号>/`

- `docs/` 是**文档面**：给人读、要求结构（frontmatter、目录登记、索引）。把 mock 和截图塞进去，索引与门会开始为聊天记录收税。
- `notes/` 是**账本面**：立项单、决策稿、知识与过程材料本来就在这里，产物与立项单同处一目录，追溯时一眼对上。
- 两者职责不混：文档写"是什么、为什么"，账本记"当时怎么想的、长什么样"。

## 存量怎么算（宽限规则）

约定只对**新产物**强制。存量按"改到哪、搬到哪"迁移，不做一次性大搬家——因为存量里有 16 个 mock 被 `server/`、`integration/` 下 29 处代码/文档按路径引用，
搬一个就要同时改引用者，不能凭记忆改。

已迁移（261030，integration 在 main 直落，11 个 mock 进了各自目录）：

- `develop-buffer/`：`261011-develop-buffer-faces-faithful-sample.html`、`261011-develop-buffer-faces-mock.html`、`261011-line-round-ui-mock.html`
- `project-executor/`：`260927-project-executor-mock.html`、`261003-executor-panel-redesign-mock.html`、`261009-executor-certification-tab-mock.html`、`261009-executor-overview-events-alerts-mock.html`、`261009-executor-panel-overview-mock.html`
- `concurrency-limit/`：`261004-concurrency-limit-mock.html`
- `inspection/`：`261004-inspection-tab-mock.html`
- `project-lifecycle/`：`260904-project-ui-mock.html`

留在 `notes/discussions/` 的 5 个——`260904-notes-ui-mock.html`、`260910-docs-view-mock.html`、`260904-ticket-detail-ui-mock.html`、
`260904-spec-card-mockup.html`、`261010-demo-ppt.html`——**没有单一立项可归**，不搬。

仍欠的引用更新（搬家只动 `notes/`，代码侧的注释指针另票处理）：`server/plugins/` 下 6 处、`integration/` 下 2 处；
`docs/design/project-management-ui-design.md` 里 1 处属受保护路径，需宿主授权后随设计文档改动一起改。

## 边界

- 本约定不改变 `docs/epics/*.md` 的登记结构（另见 `docs/design/epic-registry-v1.md`）。
- 迁移一个产物时，必须同批改掉所有按旧路径引用它的地方；改不动的（例如受保护路径里的引用）先登记，不静默留悬空路径。
