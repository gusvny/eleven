# 左栏「线面」与行面设计说明（261011）

> 这份是**实现细节**的归属地：真源锚点、类名、断言面、影响面、未存在的读面，都写在这里。
> 同目录的 `261011-develop-buffer-faces-faithful-sample.html` 只放**样子**（图），不再夹注释。
> 状态：设计讨论中（宿主逐条定稿），尚未开票。

## 1 定稿顺序（宿主令，按时间）

| # | 令 | 落点 |
|---|---|---|
| 1 | 左栏要有"有没有走 line、走到什么状态"的标记；一个图标或一枚 `LineOn` 的 pill | 选 **B**：一枚定宽 `LineOn` 徽标 |
| 2 | `LineOn` **用不同颜色表示不同状态** | 颜色即状态（不放进 pill 的字形） |
| 3 | 原来 item 上的元素还要有 | 行上原元素一个不少（点/状态字面/标题/类别/暂停/健康/票号 …） |
| 4 | 暂停徽标太长，**一个图标就行** | `⏸` 单字形（两相位靠实线/虚线；词进 tooltip 与 aria） |
| 5 | **title 单独占一行** | 行卡改纵向三段（状态行／标题行／元数据行） |
| 6 | **保留进度点阵与 step name** | 十格 `.wb-stage-dot` ×10 ＋ `.wb-card-stage` |
| 7 | `waiting for certification` 这类**文字不要** | 行上不放整句（只进 tooltip 与详情头） |
| 8 | **ticket id 永远开头** | 行首元素＝票号 |
| 9 | 带颜色的**左条（左括号）不要** | 左栏卡片 `border-left-width:0`（本来就无） |
| 10 | 行首**状态点去掉**；`active` 交给**点阵颜色** | 状态＝点阵当前格颜色 ＋ 行底色 |
| 11 | **排队位次太不明显** | 位次改醒目（候选见 mock 的位次一节） |

## 2 信息分区（一行＝哪些面）

- **第一行（身份＋状态＋线）**：票号 → 排队位次 → `LineOn` → `⏸`（若暂停）→ 行尾排序控件（仅 queued 行）
- **第二行**：标题（独占）
- **第三行（元数据）**：step name → 类别 chip → 十格点阵（右端）

## 3 状态与颜色（值只从引擎来，颜色只用既有令牌）

### 3.1 线状态（`LineOn` 徽标；文字恒为 `LineOn`）
| 状态（引擎词） | 判据 | 颜色（令牌族） |
|---|---|---|
| 在线上、未落地（基准） | `lane_version=develop-buffer-v1` ＋ `develop_line`，且无 landing 行 | muted 描边 |
| `waiting` | `ticket_wait_state.state == waiting` | warn |
| `waiting` ＋ `overdue` | 等待超过声明上界 | warn ＋ `!` 后缀 |
| `red_implicated` | 落在红认证的派生区间 | danger |
| `certified` | `state == certified` → `covered_by` | success（描边） |
| `delivered` | `ticket_outcome.delivered_in` | success（实心） |
| 已撤回 | `ending: withdrawn` / `reverts` 关系 | muted（实心） |
| 不在线上 | `lane_version != develop-buffer-v1` | 不渲染 |

### 3.2 票状态（行面）
| 状态 | 点阵当前格 | 行底色 | 备注 |
|---|---|---|---|
| `active` | accent | 无 | 排序位次/控件在场（queued 行） |
| `waiting` | warn | warn 派生底 | `⏸` 若被暂停 |
| `blocked` | danger | danger 派生底 | |
| `failed` | danger-solid | danger 派生底 | **与 blocked 同族红**，要分清需形状差异 |
| `done` | success（＝已过格） | 整行 0.72 淡 | |

## 4 行面元素与真源锚点（断言面）

| 元素 | 锚点 | 真源 | 备注 |
|---|---|---|---|
| 票号 | `data-ticket-id`（行级） | `ticket-row-card.tsx` `.wb-card-id` | **T5 断言叶子文本含票号** |
| 排队位次 | `data-order-pos` | `ticket-row-card.tsx:255-258` | 仅 `queued` 行；`atwork/hold/paused` **不渲染位次、不渲染控件** |
| 排队点 | `data-order-dot=work\|hold\|paused` | 同上 `:259-268` | 8px 圆：work 绿 / hold·paused 琥珀 |
| `LineOn` | 待定（建议 `data-line-face=<state>`） | 本票新增 | 值只来自引擎行 |
| 暂停 | `data-paused` / `data-paused-phase` | `.wb-card-paused` | 源码锁：`tests/t260908-01-ticket-pause-ui.mjs:48-49` |
| 标题 | `data-wb-row-title` / `data-title-src` | `.wb-card-title` | |
| step name | `data-wb-row-stage` | `.wb-card-stage` | 由 `stageDisplayLabel()` 派生 |
| 十格点阵 | `.wb-stage-dot` ×10（`data-on`） | `ticket-row-card.tsx:399-402` | 今天只区分蓝/灰 |

## 5 要改的实现点与影响面

1. **十格点带状态色**：左栏十格点今天由 `ordering.dotsLit` 决定"亮几格"（只蓝/灰）。要表达 `active`/`waiting`/… 需要：**已过格＝绿、当前格＝状态色、未到＝灰**。板面已有同款写法（`index.tsx` 的 `.wb-card-lane-dot[data-visual=current][data-state=…]`），**照抄它，不新造色**。
2. **左栏卡片基线**：`.wb-sb .wb-card` 已是透明底、`border-left-width:0`（`sidebar.tsx:415-427`）。新增元素不得把 4px 彩条带回来。
3. **既有断言（`integration/t261008-08/sc_t26100808_left_column_row_composition.mjs`）**：
   - **T1b**：`stateWord===false`、`stage` 在场、`epic` 在场、`.wb-stage-dot` 数量＝**10**、无进展句元素、无相对时间元素。→ 新元素（`LineOn`）不影响；**十格点数量必须仍是 10**。
   - **T1c**：行本体左边条宽 <2px；排序控件右缘贴齐行右缘；**位次号在拖拽把手左侧**。
   - **T3**：paused 行＝**只有琥珀点、无位次、无控件**。→ 若要让 paused 行也显示位次，**必须同票改这条断言**（属集成资产，改动要写进票面）。
   - **T5**：票号必须仍在行面叶子文本里。
4. **暂停徽标的 L1 电池**：`tests/t260908-01-ticket-pause-ui.mjs` 有两条**逐字钉 copy** 的断言（`pausedBadgeText(...)`）→ 图标化必须同票重写为"锚点 ＋ title/aria 取词"。

## 6 还不存在的读面（本设计的依赖）

- 列表投影今天只带成员身份：`lane_version` / `develop_line`（`t261011-02` 的 parity 已修）。
- **线状态**（waiting / certified / red / delivered / withdrawn）在落地账本里，今天只有 executor 面板的 certification adapter 在读 ⇒ 需要一个**小读面**：列表投影新增 `line_face`（或复用同一份 derivation）。**前端不得自行推导状态**。
- 词表：沿用 `certification-model.ts` 的 `FACE_WORDS`。

## 7 开放问题（等宿主）

1. 位次标记的样子（加粗数字 / 小胶囊 `#3` / 实心圆徽标）。
2. `certified`（绿描边）与 `delivered`（绿实心）是否要一眼可分。
3. 行数：三行（状态行／标题／元数据）还是压成两行。
4. 线级 `FROZEN` 放哪：建议左栏表头/筛选项（线不是票的属性）。
5. `LineOn` 是否兼当筛选器（要就按按钮语义：键盘可达）。
6. 行首状态点去掉后，`blocked` 与 `failed` 是否要给形状差异。

## 8 纪律

- 新增元素一律**具名锚点**（便于集成用例绑定，别用类名主体做断言）。
- 颜色只用既有令牌（warn / danger / success / muted 四族）。
- 状态值只能来自引擎（票面或线账本），不在前端推导。
- 动到既有组成（T3 那一类）时，**同票更新断言**，不静默放宽。

## 9 关联

- 样子：`notes/discussions/261011-develop-buffer-faces-faithful-sample.html`
- 左栏组成的现行定稿与断言的来源票：`t261008-08`（左栏行组成）、`t261009-43`（dismiss 面）、`t261005-10`（UI-2 选项卡）
- 线面相关 KI：`KI-01M4KJ022G8R0RRAZ03C7T9TZ4`（落地前置）、`KI-01M4MRB4Z62JGVHVNXPTDV0THS`（绿轮面可被收窄轮铸出）、`KI-01M4MVHTHHS52JXZ9C6JRE8KXM`（池口径 ⇒ 线轮红）

## 10 追加：行底色（黄/红整行底）的用途与取舍（261011 宿主提问）

**它是什么**：`.wb-card[data-state=waiting|blocked|failed]` 的整行背景（warn/danger 派生底，`t260905-08` 起走主题令牌）。
**当初为什么有它**：不是装饰——`t260905-08` 是一次**对比度事故的修复**（原先行底写死浅色，深色主题下浅字撞浅底 ⇒ 不可读），于是行底改成令牌派生，并由对比度看守（`t260905-08-wb-contrast-guard`，注册在 `run_scenarios.py:1318`）逐元素量「文字 vs 有效背景 ≥ 4.5:1（done 行 3.0）」。
**它的功能**：**整行的扫视信号**——不读任何字，余光扫一列就能看出"哪几行要留意"。与"点阵当前格的颜色"是**同一个状态的两条通道**（信息冗余）。

**若按宿主设想去掉行底色**（状态只由点阵当前格表达）：
- **不丢信息**：状态仍在（点阵当前格 ＋ 行内 `LineOn` ＋ `⏸`）。
- **丢扫视力**：5px 方块要**定睛找到那一格**；行底色是余光可见。左栏一列几十行，这个差别明显。
- **blocked vs failed**：两者同族红，行底是它们**唯一**的"整行"区别；去掉后只剩两个 5px 格子的色差（`#cf222e` vs `#d1242f`，肉眼几乎不可分）。
- **顺带的好处**：没有行底就没有"底色 × 深色主题"的对比度面（少一类事故面）。
- **影响面**：`t260905-08-wb-contrast-guard` 量的是每个元素的**有效背景**——去掉行底后它量的对象变成面板/画布底，需要**同票重跑**并在票面写明"期望值改变"（它不在 known-red 名册里，红就是红）；左栏组成场景 T1c 只断言"无彩色左条"，与行底无关。

**本岗建议**（若真要去掉）：用一个**更便宜的整行记号**替代余光信号，而不是什么都不留——候选：
1. **标题变色**：`blocked/failed` 行的标题用 danger 色（一行字的事，扫视有效，且不引入底色）；
2. 行首一个 3px 高的**短记号**（不是整行底、也不是被否掉的 4px 左条）；
3. 只在 **`failed`**（终态坏）保留行底，`waiting/blocked` 交给点阵（分级：越靠终局越强）。

## 11 追加：点阵变色的两种读法（宿主澄清"整个点阵都变色"）

宿主令：**状态由整个点阵的颜色表示**，不是只有最后一格。两种读法都满足这句话：

| | 怎么画 | 保留"走到第几格" | 色块长度 | 代价 |
|---|---|---|---|---|
| **M1** | **已过格 ＋ 当前格**上状态色，未到格仍灰 | **是**（灰格＝还没到） | 到当前格为止 | 色块可能很短（前几格时只有 2–3 格） |
| **M2** | **十格全部**上状态色 | 否（进度只由 step name 说） | 满格 | 丢掉"进度"这一维；与 step name 语义部分重叠 |

- 与行底色（§10）的组合：选 **M2** 时色带最长最显眼 ⇒ **去掉行底色的理由更足**；选 **M1** 时色块偏短 ⇒ 建议保留行底色，或改用"标题变色"这类便宜的整行记号。
- 与 `LineOn` 的关系：`LineOn` 载的是**线状态**，点阵载的是**票状态**，两者正交、都不该消失。
- 实现面（同 §5 第 1 条）：今天左栏十格由 `ordering.dotsLit` 决定亮几格、只区分蓝/灰。M1 需要"哪格是当前"＋"整段换色"；M2 只需把十格整体染成状态色（更简单）。**板面已有 `data-visual=current` ＋ `data-state` 的写法可参照，颜色只用既有令牌。**
- 断言面：`t261008-08` 的 T1b 只查 `.wb-stage-dot` **数量＝10**（不查颜色）⇒ 两种读法都不破它；`blocked` 与 `failed` 同为红族，任何读法下"只靠颜色"都分不出这一对（要分清须形状差异或 tooltip 词）。
