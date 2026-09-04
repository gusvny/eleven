---
title: "项目管理 UI 设计（左栏内嵌）"
category: design
tags:
  - sandbar
  - workbench
  - 项目管理
  - UI
status: active
updated: 2026-09-04
---

# 项目管理 UI 设计（左栏内嵌）

> project-lifecycle 票③（t260904-15）交付文档；底稿=notes/discussions/260904-project-ui-mock.html
> （mock v5 过稿，宿主修订11 两枚重绘后终稿）。定稿口径真源=notes/epics/project-lifecycle.md
> 面 D + 决策 8 + 验收 11-14，本文档是 UI 面（入口/交互/降级/确认口径）的展开，不覆盖 epic。

## Problem（问题）

sandbar 的项目注册表（`~/.sandbar/projects/<key>/project.yaml`，契约 ①a）此前进出全靠手搓：
接入=手工建目录+手写 YAML+手工跑 credentials 迁移；摘除=手删目录（在飞票查询面悬空、归档数据蒸发风险）。
票①② 已把这两个操作收口为安装器 CLI（`sandbar project add|remove|list`，fail-closed 前置校验+在飞闸+purge
双旗），但宿主的操作面仍是终端——而 console 左栏本就按注册表列项目组，是宿主天然的操作面。
缺的是：把 CLI 能力内嵌进左栏的 UI 入口，以及与注册表状态对齐的三类呈现（隔离条目、组头设置入口、接入行）。
另有一个纯呈现问题：组头四个视图入口是 emoji（📋📖🔀🗂️），尺寸小、风格不统一（宿主令 260904：顺便做一套）。

## Requirement（需求）

1. 左栏新增恰三处（不建独立页/tab/中列视图，260904 宿主裁定降级）：
   - **组头「项目设置」入口**：常驻可见的第五个图标，与四视图图标同排同款；点开**项目设置弹层**
     （只读：key/显示名/根目录 + 票计数[在飞/完结/已归档，Temporal 不可达降级「—」提示不红] +
     体检区 + 底部 danger 区「摘除项目…」）。本期设置弹层只读，编辑器=Nongoal。
   - **「＋ 接入项目」行**：项目组列表末尾，方框＋语言同组内会话区；弹层表单含预检 dry-run，
     六类拒收错误就地显示（无需翻后端日志），黄牌不阻塞；成功后左栏即时出现新项目组。
     空/全隔离注册表仍渲染本行（首个项目接入恰恰发生在空注册表时）。
   - **隔离行**：装载器隔离的 key 以红色一行呈现，点击弹层看原因（含 `<dir>/project.yaml`
     定位与修复指路）；隔离期间无组头无设置入口（无装载条目可设置）。
2. **摘除四步全在弹层内**（自设置弹层 danger 区进入）：在飞闸结果（拒摘报票号；Temporal 不可达
   fail-closed 文案含「先 sandbar up」指路）→ 处置勾选（默认全保留）→ dry-run 清单（将删/将留）先行展示
   → purge 勾选后需输入 key 二次确认；执行结果与 CLI 同口径（`--json` 同源）。
   接入弹层预检口径（t260904-15 arbitrate gen1 F1 修订）：CLI `project add` 无 `--dry-run` 旗
   （补旗=跨写集改动，裁定项上浮宿主/epic）——预检降档为**弹层本地形状检查**（key 白名单正则/
   根目录绝对路径/非空，零落盘不调 CLI，不实现 CLI 校验语义）；确认时由 CLI 做深度校验
   （存在性/交叉/重复/legacy）并就地显示。
3. **图标族统一**（验收 11b）：五枚 SVG 线性图标（工单列表/知识库/模型路由/立项单/项目设置），
   统一规格：viewBox 20×20 · stroke=currentColor · 线宽 1.6 · 圆帽圆角 · fill none · 显形 18px ·
   命中区 26×26（radius 6）· 三态（idle/hover/active）· title+aria-label 可辨识；设置=滑杆（三轨偏置
   旋钮）、路由=带箭头分流（mock v5 修订11 重绘终稿：轮辐齿轮像太阳、节点连线像 share，均已避开）。
   四枚存量视图图标换装后行为零回归（工单列表图标的回列表联动语义照旧）；渲染点与注释中的
   emoji 引用清零（sidebar/index/epics 三文件；index 的 🤖⚙️👤 执行主体徽标不在图标族范围，豁免）。
4. **写路径薄壳单源**（决策 8）：workbench host 写路由 spawn `sandbar project add|remove --json`
   （真实入口=仓根 `sandbar` 薄壳→installer.cli；UI 侧零校验/闸逻辑），CLI 拒收错误体原样透传就地显示；
   注册表读面走 TS 装载器（GET /wf/projects，消费方即装载器，防两份漂移）并扩展隔离条目；
   票计数属 Temporal 查询=CLI 独有数据，由 host 读路由 spawn `sandbar project list --json` 单点取数
   （spawn 恰是同源而非第二份，不违背决策 8 的注册表读面口径）。写路由不进工具桥（agent 无消费方）。
5. 零回归与红线：既有组头四图标/会话区/工单列表行为零回归；console 3099 零接触（改动上线=宿主择机
   重启 console 生效，staleness banner 口径）；测试全走隔离台。

## Nongoal（不做什么）

- 不做项目设置编辑器（name/paths/roles 改写）——与「自述字段编辑等真实需求」同口径，本期设置弹层只读。
- 不建独立项目管理页/tab/中列视图；不做批量操作、拖拽、跨机迁移向导。
- 不在 UI/路由侧实现任何校验/闸/体检逻辑（薄壳红线）：六类拒收、在飞闸、purge 前置闸全在 CLI 侧；
  接入预检仅为本地形状白名单检查（见 Requirement 2 修订口径），非 CLI 校验语义的复刻。
- 体检 chips 本期降档为「体检数据源未接入」中性提示位——CLI list 暂无体检字段（体检黄牌只在 add
  一次性报告），「CLI list --json 增 projects[].health 字段」为跨写集改动，待宿主/epic 追加裁定后
  小票补齐（UI 已留渲染位，届时零结构改动）。epic 验收 11 该子项以降档口径交付，非静默偏离。
- 不改契约 schema 版本（摘除语义=契约 ①a-1，v1.9 已落账）。

## Proposal（方案）

### 入口与组件

| 面 | 落点 | 内容 |
|---|---|---|
| 图标族 | `src/client/project-icons.tsx` | 五枚 SVG 组件 + 规格常量单源（viewBox/线宽）+ PROJECT_ICON_SPECS（title=aria-label） |
| 左栏三处 | `src/client/sidebar.tsx` | 组头第五枚设置入口（data-wb-project-settings-entry）、「＋ 接入项目」行（data-wb-project-add-row）、隔离红行（data-wb-quarantine-row）；数据源=GET /wf/projects 的 projects+quarantined（loadRegistry()，空/全隔离不 500） |
| 四弹层 | `src/client/project-modals.tsx` | 设置（只读+票计数降级+体检占位+danger 区）/接入（预检 dry-run+就地错误）/摘除（四步状态机 gate→dispose→dry→confirm→executing）/隔离详情 |
| host 路由 | `node.ts` + `src/host/project-admin.ts` | GET /wf/projects（注册表+隔离条目）；GET /wf/projects/detail?key=（票计数，spawn CLI list --json）；POST /wf/projects/add|remove（写面，dry_run/purge_data/purge_credentials/confirm_last 旗与 CLI 一一对应） |

### spawn 薄壳故障模式口径（runProjectCli，取舍真源=create_plan gen1 R1-①）

repo 锚定=node.ts `config?.repo ?? SUYOU_REPO ?? DEFAULT_REPO` 同源传入（cwd=repo、entry=`<repo>/sandbar`，
防异仓执行错注册表）；超时 30s（非 admin CLI 的 300s），文案点名「CLI 执行超时」；四终态全回收——正常=解析
stdout，超时=SIGTERM+await exit 转 504，取消=AbortSignal 转 499（均不留僵尸，UT 断言用时）；stdout 畸形/
超 16MB=转 502 精确文案不裸抛堆栈。**非零退出按 exit 码分流**（arbitrate gen1 F3 定稿）：
JSON 错误体（FailClosed 机器口径）→ 409 原体透传；exit 1 且人话非 JSON → 409+原文转述（用户输入拒收≠
上游故障；票① add 拒收现状输出 `[红]` 人话，JSON 化为跨票契约缺口已上报）；exit 2 → 502「参数错误」
（argparse 用法错=路由 argv 拼装与 CLI 契约不符，是路由自己的 bug）；旗标断言锚真 CLI `--help`
（UT A0 腿实跑，防 stub 把错误 argv 钉成期望——arbitrate gen1 UT 盲区教训）。

### 交互与确认口径

- 弹层骨架=session-entry 确认弹层先例：在飞禁点（busy disabled、结果驱动关闭）、ESC/遮罩关闭、错误就地显示；
  **执行中（executing）弹层锁定**（ESC/遮罩/✕ 全禁），防半途弃置假示完成。
- 摘除处置勾选默认全不勾（默认=可逆摘除：只退役注册条目，数据全保留）；任一 purge 勾选后确认钮需输入
  key 逐字匹配才可用；dry-run 清单先于确认展示。
- 语义锚：弹层锚 data-wb-pmod-*（smoke/project-modals.mjs 断言面），零 CSS 类名与出厂交叉。

### 图标族配色口径

图标本体吃 currentColor，几何规格（viewBox/线宽/显形/命中区/圆角）统一是本票契约；mock 规格卡的三态配色
（idle #57606a / hover #0969da+#f0f6ff / active #0969da）为 mock 浅色语境定稿，侧栏深色语境沿用其既有
三态色板（换装零回归优先）——如需对齐浅色卡配色，随主题化票处置。

### 测试与验收映射

- UT：`tests/project-admin.mjs`（spawn 四终态+畸形输入 17 断言）、`tests/project-routes.mjs`（三路由契约
  +空注册表+隔离条目 21 断言）、`tests/project-icons.mjs`（图标族规格+emoji 清零 29 断言）。
- smoke：`smoke/project-modals.mjs`（四弹层语义锚+确认纪律 29 断言）。
- 集成：`integration/t260904-15/` 三场景（host 路由契约/左栏三处+接入摘除旅程/设置面+隔离+空注册表首接），
  run_scenarios.py 登记制、SUMMARY 末行契约、playwright-core 缺失=干净 SKIP（KI-036 守卫）。
- 验收 11/11b/12/13/14 逐条对应关系见各场景 intent 字段。
