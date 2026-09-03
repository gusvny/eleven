# 会话 tab 全项目显示（260904 宿主决策）

> 记录人：integration（全局把关）。日期：2026-09-04。实施口径以本文为真源。

## 背景（缺陷定位摘要）

- 现象：经顶部「+ 新建会话」→ 项目选单新建的会话，顶部 tab 行不显示；
  刷新页面后所有已登记 tab 全部隐没，直到点过某项目的视图图标。
- 根因：**新建落点项目**（`handleNew` 的 `pk`）与 **tab 行过滤项目**（侧栏
  `viewProject`）是两个互不同步的状态源——`pickSwitchTargets` 按
  `project === viewProject` 过滤，`viewProject=''`（未选项目/刷新重置）时
  直接返回空列表（`src/shared/sessions.ts` 旧 194 行），登记正确的账册条目
  也被滤掉。多项目注册表（sandbar + suyou）下必现。

## 决策（宿主原话）

> 「tab的显示不依赖当前项目是什么，都显示出来。」（2026-09-04）

释义：顶部会话 tab 行的显示**不依赖当前项目**——账册内条目跨项目混排、
全量参排（MRU 序、上限 5、current 保底等既有规则不变）。

## 口径变更

| 项 | 旧口径 | 新口径 |
| --- | --- | --- |
| tab 行过滤 | 只列 `project === 当前项目` 的账册条目；未选项目 → 空列表 | **不过滤**，账册全量参排 |
| ↺ 最近关闭菜单 | 按当前项目过滤 | 同步放开（同一显示面，避免「关了找不到」） |
| 账册 `project` 字段 | 过滤键 | 保留为登记归属记录（展示/诊断用），不参与过滤 |
| 「+ 新建会话」落点 | 当前视图项目 / 选单所选项目 | **不变**（新建仍需落点项目绑工作区） |
| 上限 / 排序 / current 保底 | ≤5、lastOpenedAt 降序、current 掉出前 5 保底 | 不变 |

## 影响面（实施清单）

- `server/dsh/workbench/src/shared/sessions.ts`：`pickSwitchTargets` 去除
  project 入参与过滤；
- `server/dsh/workbench/src/client/session-entry.tsx`：targets 推导、空态
  文案、↺ 菜单过滤放开；
- `server/dsh/workbench/smoke/sessions.mjs`、`smoke/hero.mjs`：E/J 组等
  断言随口径重写；
- `server/dsh/workbench/lib/client.js`：随 src/client 变更同批重建
  （merge-checks bundle_pairs 要求）。

## 验收标准

1. 刷新页面、未点选任何项目：顶部行直接显示账册内 tab（跨项目混排，
   active 高亮当前会话）；
2. 「+ 新建会话」经选单选任意项目新建：新 tab 立即可见；
3. ↺ 菜单列出全部最近关闭条目（不按项目）；
4. `node smoke/sessions.mjs`、`node smoke/hero.mjs` 全绿。

## 与既有设计文档的关系

suyou 仓《docs/design/右栏会话入口与hero定制设计.md》§2/§4 的「会话跟项目
走、不做全局会话池」列表口径，就 tab 行显示一项**废止**（suyou 仓对本仓
只读不回写，以本记录为真源）。账册仍按项目登记归属（`project` 字段），
「只登记 UI 主动打开/新建」的记账口径不变。
