# 261004 notes/ 的去向（**待议，票未开、文件未动**）

> 宿主 261004 的想法：把 `notes/` 挪到**项目目录**下、**不再放 git**；理由是「一旦 doc 有巡检来补齐，
> 我们就没有必要留这么多 notes 了」。宿主随后指示：**先不开票，后面再具体讨论，还有很多不清楚的地方**。
> 本页只记**已核事实**与**待答问题**，不做设计定稿、不动任何文件。

## 一、已核事实（可当讨论的地基）

| 事实 | 证据 |
| --- | --- |
| `notes/` 构成：`discussions/` **55 篇 996 KB（58%）**、`epics/` 13 篇 164 KB、`debts/known-issues.md` 1 篇 **424 KB**；合计 105 文件 1.7 MB | `find`/`du` 实测 |
| **泳道不许写 notes/**（只有 main 侧会话动它） | `server/tools/ticket.py:693` 的 `validate_write_set_no_notes` |
| `notes/epics/<code>.md` 是**票面契约**：`create --epic` 靠它的存在性校验 | `client.py:1139`、`validate_epic_code` |
| 引擎解析 epics 的规则**本来就是 `<项目主目录>/notes/epics`**；sandbar 恰好主目录＝本仓（`dirs: [/Users/xingu/Documents/sandbar]`），所以今天看着像"仓内 notes" | `shared.py:resolve_epics_dir`（三级解析 + `SANDBAR_EPICS_DIR` 逃生口） |
| `notes/debts/known-issues.md` 是**巡检 inspect 段的输入面**（open 条目喂 prompt），路径写在 prompt 与解析里 | `inspection_inspect.py:807/932` |
| 项目目录 `~/.sandbar/projects/sandbar/` 现在**没有 notes/**（只有 ledger/grants/watchdog/requests/sessions 面） | `ls` 实测 |
| 今天的实例代价：main 工作区的**草稿脏文件挡了 4 次 merge**（每次多一轮闸 + 竞态） | 执行器 request `-0021` |

## 二、不确定的地方（要宿主先拍这几件，别的都跟着它走）

> **261004 后补（宿主新方向，已另落两份稿）**：立项单的去向**不由本篇决定**了——宿主令它迁进
> **定稿库**（`261004-epics-into-docs-design.md`），于是本篇 **第 2 问的 epics 那一半**与 **第 4 问
> （基准 mock 的地位）** 已收敛：定稿件（立项单、设计稿、拍过板的 mock）进定稿库，未定稿仍留讨论库。
> 另外宿主提出「文档泳道」以避免 main 直写（`261004-doclane-design.md`），第 9 问的一部分随之有答案形态。
> **其余各问（1/3/5/6/7/8，以及第 2 问的 KI 册那一半）仍然开**，本篇继续是 `notes/` 整体的待议件。

1. **搬到哪**：`~/.sandbar/projects/<key>/notes/`（机器状态、换机就丢）还是 `<repo>/.sandbar/notes/`（仓内但不进 git、
   跟着仓走）？两者在**备份 / 清理 / 多机 / 多仓**上的行为完全不同。
2. **epics 与 KI 册搬不搬**：它们是机器在读的契约（开票校验、巡检输入）。搬 ⇒ 要新增声明键（例如
   `project.yaml: paths.notes`）并让两处解析读它，且**坏了要 fail-closed 点名**；不搬 ⇒ `notes/` 会留两三个"钉子户"。
3. **草稿的寿命与删除权**：谁有权删（宿主 / 我 / 巡检建议）？毕业后多久删？删之前要不要在 KI 册或立项单留一行
   「决定已毕业，出处＝草稿 X（已删）」？——宿主的意思像是"毕业即可删"，但**删除权与留痕**没定。
4. **基准 mock 的地位**：设计稿把 mock 写成"**视觉基准**"，票要照着实现；mock 一旦离开 git，票面就指不到东西。
   ⇒ 是不是**开票时**就把基准 mock 毕业进 `docs/`（或作为票附件），只有草稿期的 mock 留项目目录？
5. **文档面巡检要不要读项目目录的草稿**：它现在扫的是仓（`docs_root` 默认 `docs/`）。要判「只在草稿里的决定」，
   它就得读草稿面——**跨项目/跨机的边界**怎么定？读不到时算 finding 还是算降级？
6. **历史怎么办**：现有 55 篇 discussions 是**一次性搬走**还是按「已毕业/未毕业」分批？git 历史里的旧草稿要不要清
   （我倾向**不动历史**，只把工作树的搬走）。
7. **备份**：`~/.sandbar/` 现在的备份口径是什么？（草稿一旦只在机器上，宿主编辑器/会话没了就没了。）
8. **并发面变化**：搬走后不再有「草稿挡 merge」，但会出现「多个会话同时写同一草稿」——要不要约定单写者？
9. **纪律落点**：这些规矩写进哪（`server/session_charter.md` / 角色 / `docs/reference/`）？谁执法（巡检 finding + 人审，
   还是机械闸）？

## 三、我现在没做的事（等宿主下次讨论后再说）

- **没开票**、**没动任何文件**（`notes/` 原样，`project.yaml` 未改）；
- 也没有把本页当成定稿：它只是把上面这些"不清楚的地方"记下来，免得下次从零开始。

## 四、关联

- 需求原话与背景：本会话（宿主 261004）。
- 相关既有稿：`notes/discussions/261004-docs-face-inspection-design.md`（草稿面判据「决策有没有毕业」）、
  `notes/discussions/261004-design-index.md`（本批草稿的入口）。
- 相关引擎面：`resolve_epics_dir`（epics 目录单点解析）、`validate_write_set_no_notes`（泳道禁写 notes）、
  巡检 inspect 的 KI 输入面。
