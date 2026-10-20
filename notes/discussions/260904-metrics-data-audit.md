# metrics 数据问题审计（260904，宿主问「数据的问题还有哪些」触发）

状态：已转工单（**t260904-04**，dev-lane/developer，260904 开票；宿主拍板：项目下拉
**启用**、UI 收敛与 host 数据修复合并一票、token 出仓快照另立票待批；见文末「工单映射」）

## 背景

宿主原话：「metrics的数据依然令人失望，ui上的项目也不能选。取消泳道和立项的
选择。你研究一下，数据的问题还有哪些」。本文=取证报告：main 当日实跑
metrics 双前门（HTTP 3099 + metrics-cli.mjs）× 缓存记录原文（~/.sandbar/projects/
*/data/metrics/）× git 真值三方对照，只定位不修复；修复走工单（见文末）。

术语对齐：宿主所说「泳道的选择」= 面板筛选行的**模板下拉**（默认值 dev-lane，
显示名「开发泳道」）；「立项的选择」= **立项下拉**。两者按宿主令退役。

## 问题清单（按伤害排序）

### ① 缓存命中的失败维永不自愈 → 交付视图近全空（KI-040）

- 现象：sandbar 6 张纳票中 5 张报「delivery 维不可算（泳道不可用且主仓无引用
  本票的提交）」，但 git 里 **6/6 全有引用提交**（06ef0b2/91327b9/7e2b475/
  ffe2d24/e37b715/9233bf3）。
- 根因：`ticketRecord` 缓存命中即早退（metrics.ts L536-547），`delivery=null` 的
  记录永不重算。t260903-11/12/13 的缓存算于 09-03T15:34Z（merge 前），此后
  squash 落 main 也不再有重算机会——**merge 前算过的票，交付数永久为零**。
- 连带（open 陈旧）：t260904-02 缓存算于闭单前 5 秒（computed_at 02:26:00.391Z
  vs close_ts 02:26:05.390Z），`open=true` 永久化。同窗同项目跨视图自相矛盾：
  time/delivery/token 视图 closed=**4**，health 直查 closed=**5**。suyou 同病：
  time 48 vs health 50。
- 唯一有数的 t260904-01 还超算：归档口径 add 2436 / commits 6（grep 把预解/
  记账提交 53e9b8d/157df23 等一并计入）vs squash 真值 `git diff ffe2d24^1` =
  **add 2135**，虚高 14%（KI-017① 多提交双算面在 sandbar 的实证）。

### ② 泳道活口径死于 join 毒路径（KI-041）

- 现象：在制票 t260904-03（泳道活着、base_ref=e5e6f0a）报「泳道不可用」。
- 根因：worktree 字段存**绝对路径**（/Users/xingu/Documents/sandbar/.lane/
  t260904-03），`join(repo, 绝对路径)` 拼出 `/…/sandbar/Users/xingu/…` 不存在
  的路径（Node path.join 不把第二参当绝对），git fatal: cannot change to …。
  实证真值：活泳道 `git diff e5e6f0a...HEAD` = **+671/−43/6 commits**，全部丢失。
  KI-032 修复后 worktree 恒锚根为绝对路径，本毒路径从那时起杀死全部活口径。

### ③ 立项下拉恒空壳 + 项目下拉硬禁用（KI-042）

- metrics.tsx L125 取 `${API}/wf/epics` → **404**（正确路由是 `/api/epics`，实测
  返回 engine-hardening/session-entry 两条）→ 立项下拉从上线起只有「全部/无」，
  fetch 失败还被静默吞掉。
- 项目下拉 L225 `disabled` + title「按项目筛选随契约 bump」——过时：冻结契约
  块 2 **本就有** `project=<key>` 参数且后端已实现校验（parseMetricsQuery/
  checkProject），禁用纯是 UI 层遗留。

### ④ 聚合宇宙两个洞（KI-043）

- **跨项目 repo 错位**：node.ts 前门 repo 恒按本文件位置推导（=sandbar），传
  `project=suyou` 时 git/会话解析仍指向 sandbar——suyou 50 张票历史（缓存 50 条
  记录俱在）要么不可见要么按错仓回落数字。多项目引擎实际只聚合得出 sandbar
  6 张票。
- **模板过滤静默吞票**：list 7 票中 t260903-10（workflow=''）被 template 过滤
  丢弃（L678），reason 无任何记载——宇宙缩水对用户不可见。

### ⑤ token 维只覆盖 2/56 票（KI-017③ 引擎侧欠账延续）

- tokens_total=2,492,477 仅来自 02/03 两张幸存会话票；闭单即拆会话 →
  `resolveLedgerSessionFiles` 账本回落因 `SUYOU_USAGE_LEDGER_DIR` 未设而空转
  （引擎侧出仓落盘本就没实现）。真实消耗大幅低计，K3 配额对账无账可查。

### 已知非新账（契约成文的降级，此处仅记账）

- health 视图 tokens_total/avg_delivery 恒 0、window≠all 时按 list.updated 近似
  计数（metrics.ts L991-1008 成文）；时间维 v1=handoff 近似（v2=08 终态精确，
  归 M2c 修约）。

## 真值对照（证据表）

| 票 | squash 真值（diff ^1） | 面板现状 | 根因 |
| --- | --- | --- | --- |
| t260903-11 | +5230/−260 | 不可算 | ① 缓存 pre-merge null |
| t260903-12 | +1652/−486 | 不可算 | ① |
| t260903-13 | +939/−384 | 不可算 | ① |
| t260904-01 | +2135/−217 | 2436/218（超算 14%） | ① 归档口径多提交 |
| t260904-02 | +3576/−388 | 不可算 | ①（缓存 open=true 陈旧） |
| t260904-03（在制） | 活口径 +671/−43/6c | 不可算 | ② join 毒路径 |

## 工单映射（260904 宿主拍板）

- **合并票（t260904-04，dev-lane/developer）**：UI 筛选行收敛（泳道/立项选择器
  退役、项目下拉启用、/wf/epics 死代码清理）+ host 数据正确性（①缓存失败维与
  open 陈旧自愈、②绝对 worktree 归一、④per-project repo 解析+模板吞票显式
  reason）。写集=workbench src/client + src/host(+node.ts) + lib 产物 + tests +
  integration/；契约 schema 冻结不私改，需 bump 走候选上报。
- **另立票（260904 宿主批，扩围后已开 t260904-09）：收口出仓快照**——settle 时刻
  冻结 token 汇总**+交付 squash 真身**双快照到项目级账本
  （~/.sandbar/projects/<key>/data/settle/），metrics 读侧优先消费快照、无快照才回落
  活口径/grep 口径；同票收窄归档口径（只认票号开头的 squash 收口提交，他账剔除）
  + donut 拆「未交付/不可算」两桶。写集在引擎（temporal-poc）+ workbench host，
  命名遵守 CLAUDE.md 硬规则⑤（零 suyou 字样）。触发对话：宿主问「不是工单结束时
  一次性计算然后保存的吗」——现状确为按需现算+可弃缓存，本票即「收口固化」落地。

## KI 对应

KI-040（①缓存陈旧化）/ KI-041（②毒路径）/ KI-042（③选择器失效族）/
KI-043（④宇宙双洞）→ notes/debts/known-issues.md 同批登记，修复面=上述两票。
