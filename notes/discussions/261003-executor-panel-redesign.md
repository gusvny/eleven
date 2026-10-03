# 执行器面板改版（261003 宿主定稿口径）

> 来源：261003 与宿主的逐轮过稿。宿主原话要点：「这个设计太烂了」「UI 简洁一点，不要搞一堆
> 说明文字」「有选项的 request 就不要让人填文字」「overview 里显示 executor 最近做的事情，
> 比如 sign 了某个 ticket、retry 了某个 ticket」「要有一个按钮可以 enable/disable executor」
> 「needs you 的信息按 80% 的 ASD-STE100 标准来写作」「把 overview 和 requests 合并，两个竖排
> 并列」「grants 可以开个 tab，让人选择」。
>
> 视觉基准（宿主已过目）：`notes/discussions/261003-executor-panel-redesign-mock.html`。
> 本文是草稿账本条目（notes 属草稿纸）；定稿迁 `docs/design/` 由宿主决定。

## 1. 为什么要改（现状的四个毛病）

1. **看不出「有没有事等你」**：未答与已答的区别藏在详情里（有无输入框），列表本身不告诉人。
2. **答过的行永久占着主视野**：请求行设计上不删除，于是列表只增不减，越用越糊。
3. **满屏解释性长句**：界面上到处是给自己辩白的长文案，读起来像说明书，不像操作面。
4. **没有「它最近做了什么」**，也没有能开关执行器的地方；授权只能在接口层面改，页面上
   没有授予控件（详见 §5）。

## 2. 版面（定稿）

- 顶部只有 `Executor` + 项目标签。**不要**项目选择器（下拉 / 手填 key / Load 按钮），
  **不要**轮询状态行（"polling every 5s · last ok …"）——从哪个项目行进面板，就是哪个项目。
- 页签：**Overview / Grants / Alerts / Ledger / Settings**，等待条数以徽标挂在 Overview 上。
- **Overview 与 Requests 合并**（原 Requests 页签取消）：**两栏并列**——左「等你回」，
  右「最近动作」；窗口窄于约 760px 自动改为上下叠放（面板挂在控制台中列，宽度不定）。
- Ledger 简化成四个数字（行数 / 重复 / 坏行 / 缺口）+ 账本路径 + 最近三条事件。
- Settings 只留守望者与提醒配置。

## 3. 交互（定稿）

- **每条 waiting 项可展开**：收起态一行（状态点 + 问题 + 类型·等待时长 + 三角）；展开后三段：
  ① 详细内容（等宽小字块，超高自动内滚，最高约 170px，再长也不撑爆列表）；
  ② 回答控件；③ 溯源小字（谁提的 / 请求 id / 默认动作）。
- **有选项的请求给按钮，不让人打字**；没有选项的才给输入框。选项与默认动作由请求方在提出时
  一并给出（新增数据面，见 §6）。兜底入口叫「Type an answer」。
- 答完即收进折叠的 `Answered`，可再展开回看（详细内容与答复都保留）。
- **授权集中在 Grants 页签**：总开关 + 被点名的执行器会话 + 六个权限各一个开关 +
  「仅宿主」的改权限条目（灰、不可点）+ Give all / Give none 快捷键 + Save。
- Overview 上的 `Disable executor` 与 Grants 总开关是**同一份状态**：关掉＝
  **收回全部授权**（它只能看和问），**守望者照常运行**（仍唤醒、仍告警）。
- 「最近动作」每条：时间 + 动作 + 票号 + 一句话结果；动作上标出**凭哪条权限**做的。

## 4. 文案（定稿：按 80% ASD-STE100 口径写）

规则：

1. 短句：描述句不超过约 25 词；一句一个意思。
2. 主动语态、现在时；要人做的事用命令句。
3. 一个词一个意思，全文固定术语：ticket / executor / permission / session / stage / gate /
   merge / alert / watchdog。
4. 不用行话、比喻、缩写词；不用缩略形式（don't、won't 一律写全）。
5. 名词簇不超过三个词。
6. 标识与数字用冒号引出（`Ticket:`、`Request id:`、`Default action:`）。
7. 状态句也写成完整句（「Self-lock cleared.」）。
8. 面板内所有文案（含 Grants / Settings / Ledger / Alerts）一律照此口径，不留例外。

样例（改前 → 改后）：

| 改前 | 改后 |
|---|---|
| Anything to add before I open this ticket? | Do you have more instructions before the executor opens this ticket? |
| Grant executor permissions? | Which permissions do you give to the executor? |
| …locked by a shared fixture, so a future rename … instead of drifting silently. | A shared test file locks two lists: the knob list and the permission words. / If you change one name on one side, the build stops. / The two lists cannot go out of step without a signal. |
| 选项 None | 选项 No permission |
| stall — t261002-10 idle 16m | Ticket t261002-10 did not move for 16 minutes. |
| 区标题 Needs you（习语） | Needs your answer |
| 兜底链接 Other… | Type an answer |

## 5. 本次改版必须一并覆盖的既有缺陷（定位已核实，只定位未修）

1. **授权保存面会静默丢掉「点名执行器会话」**：保存回执报成功，但写盘的声明里没有这一项。
   引擎侧认这个字段、读出面也认，唯独保存路径不搬运它。后果两个：界面上保存「点名」会丢；
   此后任何一次保存（包括一键收回）都会把它一起抹掉。**改版后的 Grants 页有会话输入框，
   等于把这个洞摆到台面上，必须先修。**
2. **授权读出把「行数」当「操作数」**：读出面的计数按「操作 × 模板」的行数统计，六个操作会被
   报成 18，界面上写成「18 个操作已授予」。改版后必须是「Permissions: 6 of 6」这种口径。
3. **会话点名缺失时的读出面**：点名缺席时能力矩阵仍照常渲染，容易读成「已授予」。改版后的
   读出面要显式区分「没点名 / 点名了但零授予 / 已授予」。

## 6. 待定项（给实现方，别另拍）

- **「最近动作」的数据来源**：必须能回答「做了什么 + 凭哪条权限」。引擎对受闸写动作已留下
  可核对的观测键；实现方须选一个稳定的只读来源，并规定不可得时**显式降级**（点名原因），
  绝不用空列表冒充「最近没动作」。
- **请求的选项数据面**：提出请求时一并给出选项与默认动作；没有选项才退回自由文本。

## 7. 验收要点（票面 acceptance 引用本节）

- 版面与 §2 一致：五个页签；项目选择器与轮询状态行不存在。
- 交互与 §3 一致：选项按钮、条目可展开且长内容内滚、两栏并列且窄屏叠放、收回授权只影响授权。
- 文案全量符合 §4（Grants / Settings / Ledger / Alerts 逐页抽查）。
- §5 三条各有回归：保存后点名仍在；读数报「6 of 6」；点名缺席时读出面显式区分三态。
- 视觉以 mock 为基准：`notes/discussions/261003-executor-panel-redesign-mock.html`。
