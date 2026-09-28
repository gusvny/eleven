# 立项单：project-lifecycle

| 字段 | 值 |
| --- | --- |
| 代号 | `project-lifecycle` |
| 状态 | 已立项（功能交付，验证中——不得完结，宿主 260910 钦点） |
| 立项日期 | 2026-09-04 |
| 备注 | 宿主令 260904：sandbar 需要创建 project 的功能，也要能把现有 project 移出去；⚑ 已清零、UI mock v5 已过稿。票①②③已交付（add/list/remove/UI 面），但验收未完结——另开项目 dengzhufpv 实测暴露多仓缺陷（t260910-01 静默丢代码，KI-066）等一批问题，收口挂在验证完成（修复票 t260910-03 等）后。 |

## 背景与问题

注册表已出仓为机器级 per-key 目录（契约①a：`~/.sandbar/projects/<key>/project.yaml`，
装载器 Python/TS 双侧同构），但**注册表的进出全靠手搓**：

1. **接入无工具**：新项目接入 = 手工建目录 + 手写 project.yaml（严格最小 YAML 子集，
   写坏即被装载器单条目隔离 fail-closed）+ 手工跑 credentials 迁移命令（①b 先立的是
   人工步骤）。没有前置校验：key 形状白名单、根目录存在性、根目录与他项目交叉
   或互为嵌套（票的空间=项目根 `.lane/`，根交叠=归属歧义）、
   legacy env 模式（`SUYOU_PROJECTS_YAML` 在位时运行时读旧单文件，往 per-key 目录
   写=静默无效）全靠人脑。漏配项要到第一张票才炸（如 verify.yaml 缺失 →
   dev-lane integration 道 fail-closed）。
2. **摘除无语义**：把项目移出去 = 手删 `<key>/` 目录，但一处注册表背后挂着六样东西：
   在飞工单（Temporal `ProjectKey`）、完结工单归档（`data/tickets/`，审计真源，
   契约①c）、credentials、metrics 缓存、项目仓 `.lane/` 泳道残骸、异仓 worker
   （KI-033 家族）。手删目录 = 在飞票的查询面（`?project=` API 族）一律 4xx、
   ensure/报告链路悬空；归档数据随目录蒸发——**审计真源不容蒸发**。
3. **多项目已成事实**：注册表现有 sandbar（dogfood）+ suyou（冻结侧）两条目。
   M2-D/M3（切安装制、摘除、dogfood）每一步都是注册表状态的显式变更，
   没有工具 = 每步都是一次手搓风险。

## 目标（四面）

**面A 接入（add）**：一条命令完成注册——fail-closed 前置校验（key 过
`PROJECT_KEY_RE` 白名单、**恰一个根目录**且存在、为绝对路径、key 不重复
（幂等重跑同拒）、根目录不与既有项目交叉或互为嵌套、legacy env 模式在位时
拒收并指路）→ 原子写 project.yaml（tmp+rename、不覆盖既有）→ 接入体检报告
（黄牌不阻塞：verify.yaml 存在性、per-key credentials 缺失回落提示、paths
声明提示）。写出的文件必须被两侧装载器零隔离接受；根目录解析复用装载器同源
（`shared.py` / `suyou-projects.ts` 同口径），不双份漂移。

**面B 摘除（remove）**：默认 = **可逆摘除**——在飞闸（Temporal 按 `ProjectKey`
查 running 票，有即拒摘并报票号；Temporal 不可达 = fail-closed 拒摘）→
project.yaml 退役移位（不删数据；根扫描对无 project.yaml 的子目录本就跳过，
①a 语义现成）→ 摘除报告（项目根 `.lane/` 下各票泳道残骸**只报不删**、
closed 未归档票计数黄牌、摘最后一个项目时的零条目警告——装载器空表抛错语义
点名）。数据处置三态显式分离：`data/`（归档+metrics）与 `credentials.yaml`
默认原样保留；`--purge-data` / `--purge-credentials` 显式旗才删；purge-data
前置「closed 票全归档」闸 + dry-run 清单。再接入（re-add）：同 key 重新 add，
`data/tickets/` 归档链连续不断。

**面C 报告（list）**：注册表条目、隔离条目（含原因与 `<dir>/project.yaml`
定位）、每 key 在飞/完结/归档票计数（Temporal 不可达时降级为注册表面+提示，
只读报告不 fail-closed）。add/remove 输出与人读摘要 + `--json` 共用报告口径
（同 installer status 机器口径惯例）。

**面D UI（左栏内嵌，260904 宿主令追加、同日裁定降级——不建独立页）**：
项目管理内嵌 console 左栏（workbench 插件）——**console 本就是用户操作面，
增删项目经 UI = 宿主亲手操作**，与「写=宿主-only」红线自洽。左栏本就按注册表
列项目组，**不新建页面/tab/中列视图**，新增仅三处：**组头「⚙️」项目设置
入口**（宿主提议，260904 采纳，替代 v2 的 hover「⋯」——常驻可见的第五个
图标，与四视图图标同排同款；点开**项目设置弹层**=只读信息
[key/显示名/根目录] + 票计数[在飞/完结/已归档，Temporal 不可达降级「—」
提示不红] + 接入体检 chips + 底部 danger 区「摘除项目…」；本期设置弹层
**只读**，编辑器=Nongoal）、**「＋ 接入项目」行**（项目组列表末尾，方框＋
语言同组内会话区；弹层表单含预检 dry-run，错误与黄牌就地显示——session-entry
确认弹层先例）、**隔离行**（装载器隔离的 key 以红色一行呈现，点击弹层看
原因含 `<dir>/project.yaml` 定位与修复指路；隔离期间无组头无 ⚙️）。摘除流
四步全在弹层内：在飞闸结果 / 处置勾选默认全保留 / dry-run 清单 / purge
输入 key 二次确认。票计数与体检黄牌只进设置弹层不占日常视图。**组头图标族
统一**（宿主令 260904「四个 icon 太小、不统一，顺便做一套」）：emoji
（📋📖🔀🗂️）→ **SVG 线性图标五枚**（工单列表/知识库/模型路由/立项单/
项目设置），统一规格=viewBox 20×20 · stroke=currentColor · 线宽 1.6 ·
圆帽圆角 · fill none · 显形 18px · 命中区 26×26（radius 6）· 三态
（idle #57606a / hover #0969da+#f0f6ff / active=当前视图 #0969da）·
title+aria-label 可辨识；规格随 UI 设计文档成文，替换含 sidebar.tsx 等处
注释里的 emoji 引用。写路径薄壳：workbench host 路由 spawn
`sandbar project … --json`（单源=CLI，`runAdminCli`/`execFileP` spawn 先例），
不另实现校验与闸逻辑；写路由不进工具桥（agent 无消费方）。

## 宿主红线（提案，随拍板定稿）

- **审计真源不蒸发**：remove 默认不删 `data/`；purge 必须显式旗+闸，
  任何路径不得静默删归档。
- **注册表只读放开、增删改宿主-only**（260904 宿主问询后修订，原「agent
  不碰注册表」一刀切过强）：**读**（list/lookup）面向 agent 开放——ticket 面
  本就要求知道项目清单，只读无风险；**写**（add/remove/purge/边界字段 key·dirs
  编辑）只落安装器 CLI（宿主操作面），不进工具桥⑤——理由是结构性的：①dirs 是
  KI-032 锚定闸的规则本体，被闸裁判者不能自改边界；②工单人审闸只审仓内 diff，
  机器级状态变更不流经任何闸，放开写=无人审的全局状态通道；③purge 碰审计真源。
  项目自述字段（name/paths）的 agent 编辑：本期不做，等真实需求（rule of three）；
  将来 agent 主导接入可做 prepare/apply 两段式（agent 产内容+体检，apply 走宿主
  或带人审通道），口径留门不承诺。
- **console 3099 红线照旧，UI 属其本义**：项目管理 UI 落 workbench（console=
  用户操作面），增删项目经 UI = 宿主亲手操作，与「写=宿主-only」自洽；workbench
  改动上线 = 宿主择机重启 console 生效（staleness banner 口径，engine-hardening
  先例），代码/测试/安装器不得自动重启；写路由不进工具桥（agent 无消费方）。
- **fail-closed 纪律**：校验不过 / Temporal 不可达 / 装载歧义，一律显式拒绝
  且错误可辨，不猜着做、不留半成品。

## 关键决策（260904 定稿，拍板沿革见状态节）

1. **落点 = 安装器 CLI 子命令族** `sandbar project add|remove|list`（新模块
   `server/installer/projects.py`）。理由：注册表属五层架构之「机器级配置」层，
   安装器已是机器级生命周期管理者（init/up/down/status/doctor/upgrade），
   同面收敛。命令分组用子命令族（260904 拍板）。
2. **摘除 = 注册条目退役，不是删目录**：project.yaml 移位退役（如
   `project.yaml.retired-<ISO>`）留在原 key 目录；①a 的「目录名/key 全等」约束
   只在 project.yaml 在位时生效，退役后子目录被根扫描自然跳过——**零契约 schema
   改动即可实现可逆摘除**。退役文件命名/位置随票定，不上升立项。
3. **摘除与目录模型语义入契约**：契约①a 现只写成接入与装载语义，两个增量节
   补进①a（援引 v1.5 裁定：增量不升 schema）——「摘除/再接入/数据处置三态」；
   「单根目录口径」（工具恰写一条 dirs，dirs 多条=遗留形状：装载容忍、工具
   不产——契约①「项目=目录」本义的工具面落字）。**契约真源已裁定（260904
   宿主：sandbar 仓下文档一律以本仓为准）**：契约文档已改头部声明+变更记录
   v1.8 落账，suyou 侧同名文件降为历史冻结件——增补节直接落本仓，无前置阻塞。
4. **在飞闸实现复用 client.py ticket-list**（project 过滤），安装器不另造
   Temporal 客户端。Temporal 不可达口径（260904 拍板）：**fail-closed 拒摘、
   无绕过旗**——要摘先起 server（`sandbar up`）；引擎真死透时走手工路径，
   工具不背静默锅；`--offline-ack` 备选案弃用。
5. **add 的接入体检是报告不是闸**：verify.yaml 缺失等项目侧配置按契约三态属
   「项目声明的本意」，IDE 不内置项目策略、不代写项目仓任何文件——只黄牌提示
   「第一张 dev-lane 票会在 integration 道红」。**credentials 定案（260904 宿主）：
   add 不代拷**——新项目按①b 现行回落跑通（per-key 无 → dsh 平台文件，弃用
   窗口口径**不变**），体检只提示；`--copy-credentials-from` 旗**不做**。
   **IDE-global 凭据档记一笔留门（不做）**：sandbar 名下现状无 global 档
   （`~/.sandbar/credentials.yaml` 不存在；回落借的是 dsh 平台用户级文件）——
   宿主裁定 260904「现在没有就先不做」；等真实需求出现再议（rule of three），
   届时连带重估①b「弃用窗口」口径是否转正为三档常驻
   （per-key → 平台 global → 无）。
6. **单根目录模型**（260904 宿主重申，出处=契约①「项目=目录」/立项单 sandbar
   「目录与知识模型」）：一项目恰一个根目录；多 repo 项目=父目录作根，各 repo
   为子目录。空间层级：项目根 → `.lane/<票id>/`（lane=票的空间）→ lane 内
   worktree（一票涉多 repo 时多棵树同居一 lane）。add 恰写一条 dirs（schema v1
   列表形状兼容，多目录输入=拒收）；根目录交叉或互为父子嵌套=阻塞闸（票的空间
   与归属判定按根目录，交叠=歧义，宁可拒收报两个 key）。原 ⚑「非主目录交叉
   是否阻塞」**撤销**（多目录语义不再提供；旧 projects.yaml「其余目录用于归属
   判定」头注=冻结侧遗留口径，不随本立项延续）。
7. **现状不迁移不动账**：本期不给存量两条目（sandbar/suyou）做任何自动改写；
   首个真实用户 = 第三个项目接入时用新命令。
8. **UI 写路径薄壳单源**（260904 宿主令追加面D；入口同日两轮裁定）：workbench 写路由
   spawn CLI `--json`，不另实现校验/闸逻辑；读沿用既有 `/api/wf/projects` 扩展
   （TS 装载器即消费方）——CLI 与 UI 行为同源，防两份漂移。UI 入口已定=左栏
   内嵌三处（组头「⚙️」项目设置入口[含摘除 danger 区] /「＋接入项目」行 /
   隔离行，见面D），不建独立页；弹层内交互细节随票 + UI 设计文档定。
9. **命名守硬规则5（suyou 退役令，260904）**：本立项一切新命名面全中性
   （`sandbar project …` 命令族、`server/installer/projects.py`、报告文案、
   UI 文案）；档内出现的 `SUYOU_PROJECTS_YAML`（存量 env）、
   `suyou-projects.ts`（存量装载器文件名）、注册表 suyou 条目（事实陈述）
   均为存量标识——退役随专门迁移票处置，本立项不随手改、不新增。

## 面/票拆解（建议）

- **票①（add/list 面）= t260904-10（260904 开工）**：`server/installer/projects.py`（add+list+校验闸+原子写
  +体检报告）+ installer tests + 集成场景（双侧装载断言 / 拒收路径全枚举 /
  legacy 拒收 / 幂等 / 拒收零残留，按 integration/ 现行登记制落册）+ ops 手册
  初版。写集 = server/installer/、integration/、docs/ops/（epic 档账本由
  integration 在 main 直管——建票机械闸禁 notes/ 写集，260904；票进程随结算
  note 报回，本档随收尾固化）。
- **票②（remove 面，依赖票① CLI 骨架）**：remove（在飞闸 / 退役移位 / 摘除报告 /
  purge 双旗 + dry-run）+ re-add 归档链场景 + 在飞闸真票场景（复用
  engine-hardening 票①隔离台基建，槽位制起 temporalite 真开一张票）+ 契约①a
  增补节（真源已裁定，直接落本仓）+ 连带清理：`server/installer/upgrade.py`
  docstring「真源在 suyou 仓，文首标注承接」表述同步（260904 已过时，一行注释）。
  写集同票① + docs/design/（契约）。
- **票③（UI 面，依赖票①②的 CLI `--json` 口径）**：workbench host 写路由
  （spawn CLI 薄壳）+ projects API 扩展（隔离条目）+ 左栏三处新增（组头「⚙️」
  设置入口/「＋接入项目」行/隔离行）与三个弹层（项目设置[只读+danger 区]/
  接入/摘除）+ **组头图标族统一**（图标模块五枚 SVG + emoji 渲染点与注释
  引用替换）+ workbench smoke + 浏览器捕获场景（复用 bench_console.mjs 先例，
  隔离台跑 UI 族）。写集 = server/dsh/workbench/、integration/、docs/（UI 设计
  文档）、本档。
- **写集冲突排查**：本立项对 `shared.py` 仅 import 复用（装载器/根解析），
  与在飞 t260904-03（索引化，改 shared.py）无同文件写冲突，可并行；票中若需
  动装载器本体，与该票 merge 串行、后并者 rebase。

## 验收标准

票①（add/list）：

1. 隔离根（`SANDBAR_PROJECTS_DIR` 指临时目录）add fixture 项目 → Python
   （`shared.load_projects_registry`）与 TS（`suyou-projects.ts`）两侧装载出该
   条目、零隔离、既有条目不受影响（双侧断言进场景）。
2. 拒收路径各错误可辨（文案点名原因）：key 不过白名单 / key 已存在（幂等重跑
   同判）/ 根目录空·相对路径·不存在·**多条输入**（单根模型，多目录=拒收）/
   根目录交叉或互为父子嵌套（报两个 key）/
   `SUYOU_PROJECTS_YAML` legacy 模式在位；且拒收零残留（根目录不留半成品）。
3. add 成功输出体检报告：verify.yaml / credentials / paths 三类黄牌按 fixture
   有无如实亮；`--json` 机器可判。
4. list：注册+隔离条目全列，隔离原因含 `<dir>/project.yaml` 定位；`--json`
   同构；Temporal 不可达时票计数列降级并提示（不红）。

票②（remove）：

5. 隔离台起一张 running 票 → remove 拒摘报票号；收口（cancel 或完结+归档）后
   remove 成功。
6. 默认摘除后：project.yaml 退役在位、`data/tickets/` 与 credentials 与
   metrics 字节数不变（场景断言）；双侧装载器不再列该项目、其余项目装载不变；
   re-add 同 key 成功且 `data/tickets/` 票数连续（归档链不断）。
7. Temporal 不可达 → remove fail-closed 拒摘（文案含可达性诊断指路；260904
    拍板：无绕过旗，要摘先 `sandbar up`）。
8. purge：无旗不删任何数据；`--purge-data` 先过「closed 全归档」闸（有未归档
   closed 票 = 拒，列票号）；dry-run 输出将删清单（路径+字节+票计数）；
   `--purge-credentials` 独立生效。
9. 摘最后一个项目：零条目警告（点名装载器空表抛错语义）+ 显式确认旗。
10. 摘除报告含项目根 `.lane/` 各票泳道清单（lane=票的空间；只报不删，指路
     teardown / 手工清理）与 closed 未归档计数。

票③（UI）：

11. 左栏三处新增就位：组头「⚙️」项目设置入口（第五图标，常驻可见与四视图
    图标同款；设置弹层含只读信息[key/显示名/根目录]、票计数[Temporal 不可达
    降级「—」不红]、体检 chips、底部 danger 区摘除入口）、「＋ 接入项目」行
    （项目组列表末尾，方框＋语言同会话区）、隔离 key 红色行（点击可见原因含
    `<dir>/project.yaml` 定位与修复指路）；既有组头四图标、会话区、工单列表
    零回归。
11b. 图标族统一：五枚 SVG 规格一致（viewBox/线宽/圆角/显形 18px/命中区
    26×26），title+aria-label 齐备，三态（idle/hover/active）正确；四枚
    存量视图图标换装后行为零回归（📋 联动语义=点图标回工单列表等照旧）；
    渲染点与注释中的 emoji 引用清零（组头一处渲染 + sidebar/index/epics
    注释引用）。
12. 接入弹层：拒收路径（验收 2 的全部枚举）错误就地显示，无需翻后端日志；
    黄牌不阻塞；成功后左栏即时出现新项目组（`/wf/projects` 读回=装载器
    消费方）。
13. 摘除弹层（自设置弹层 danger 区进入）：有在飞票时显示拒摘与票号
    （Temporal 不可达显示 fail-closed 文案）；处置勾选默认全保留；dry-run
    清单（将删/将留）先展示、显式确认才执行；purge 勾选后需输入 key 二次
    确认；执行结果与 CLI 同口径（`--json` 同源）。
14. 浏览器捕获场景进套件（隔离台跑，console 不被测试重启——bench 纪律）。

回归：现行集成场景套件全绿（基线数以验收时 main 实跑为准）；workbench /
providers / knowledge 现有 smoke 零回归；生产 7233/8233/3099 监听面零扰动
（隔离台纪律照旧）。

## 交付文档（验收逐条核对）

- docs/ops/：《项目生命周期操作手册》新增（add/remove/purge 步骤、红线、
  故障口径；含 UI 操作路径；或并入既有 ops 文档，随票定）。
- docs/design/project-management-ui-design.md（新增，票③交付）：入口/交互/降级与确认口径
  （按设计文档写作指南四段）。
- docs/design/sandbar-project-onboarding-contract-v1.md：①a 增补「摘除与再接入」+「单根目录
  工具口径」节 + 变更记录一行（真源已转正本仓，v1.8 之后记行）。
- docs/terminology.md：补「摘除 / 退役 / 再接入」词条。
- notes/epics/project-lifecycle.md：本档（状态与归档快照随收尾固化）。

## Nongoal（本期不做）

- UI 面只做生命周期三操作（列表/接入/摘除）：不做项目设置编辑器（name/paths/
  roles 改写——与「自述字段编辑等真实需求」决策同口径）、不做批量/拖拽、
  不做跨机迁移向导。
- 不做跨机迁移/项目导出包（「移出去」= 本机停止服务+数据处置；搬机器另立）。
- 不做批量操作（多 key 一次摘/迁）。
- 不改契约 schema 版本（增量节援引 v1.5 裁定，不升 v2）。
- 不处理 KI-034 残余②（跨项目 docsDir/EPICS_DIR 解析）——新项目接入后 epic/docs
  目录解析仍按现行引擎锚点，另立票。
- add 不代写项目仓内任何文件（verify.yaml / roles / epics 项目自备——契约：
  策略自带，IDE 不夹带）。

## 状态与归档快照

- 2026-09-04：立项草案落档（integration 代笔）。⚑ 待拍板清单：①CLI 命令面
  落点与命名；②摘除默认保留数据的处置三态；③Temporal 不可达口径（fail-closed
  vs `--offline-ack`）；④契约真源归属（suyou 冻结件 vs 本仓副本转正）；
  ⑤非主目录交叉是否阻塞；⑥add 是否代拷 credentials。
- 2026-09-04（修订）：宿主问询「不让 agent 改会不会有点强」——红线②改为
  分级口径：只读放开、增删改与边界字段宿主-only、自述字段编辑等真实需求、
  prepare/apply 两段式留门（详见宿主红线节）。
- 2026-09-04（修订2）：宿主令「project 要 UI」——原 Nongoal「不做 UI 面」
  反转，立项扩为四面：新增面D UI（workbench 项目管理页，写路径薄壳 spawn
  CLI 单源）、票③、验收 11–14、UI 设计文档交付项；console 红线条款改为
  「UI 属用户操作面本义 + 宿主择机重启生效」。
- 2026-09-04（修订3）：宿主重申单根目录模型（出处=契约①/立项单 sandbar
  「目录与知识模型」：项目=一个根目录，多 repo=父目录作根；票的空间=lane，
  多 worktree 同居一 lane）——决策6 重写为单根口径（多目录输入拒收、根交叉
  含互为父子=阻塞、⚑「非主目录交叉」撤销）；面A/面B/验收2·10 同步改；
  契约①a 增补节并入「单根目录工具口径」。⚑ 清单现余五项（①②③④⑥）。
- 2026-09-04（修订4）：CLAUDE.md 硬规则5（suyou 之名退役）落地本档——新增
  决策9（新命名面全中性；存量标识引用只随专门迁移票退役）。注意：⚑④（契约
  真源归属）被硬规则 4+5 事实收紧——suyou 仓不可回写且其名退役，契约增补
  只能落本仓副本，建议随本立项一并裁定「真源转正本仓」。
- 2026-09-04（修订5）：⚑④ 已拍板（宿主：sandbar 仓下文档一律以本仓为准）——
  契约头部声明改写+变更记录 v1.8 落账（真源转正，suyou 侧降历史冻结件，正文
  语义零变更）；决策3/票② 同步（增补节直接落本仓；upgrade.py docstring
  连带清理入票②）。⚑ 清单现余四项（①②③⑥）。
- 2026-09-04（修订6）：⚑⑥ 已拍板（宿主：现在没有 global 就先不做，记一笔）——
  credentials 定案=add 不代拷、`--copy-credentials-from` 不做、①b 弃用窗口
  口径不变；「IDE-global 凭据档」留门记入决策5（等真实需求再议，届时连带
  重估①b 三档常驻口径）。⚑ 清单现余三项（①②③）。
- 2026-09-04（修订7）：⚑①②③ 宿主过稿（「这些没问题了」，按建议口径拍板）：
  ①命令面=`sandbar project add|remove|list` 子命令族；②摘除默认全保留
  +`--purge-data`/`--purge-credentials` 双显式旗；③Temporal 不可达=fail-closed
  拒摘、无绕过旗。**⚑ 清零**；决策1/4 标记同步。下一步=UI mock 过稿后开工单
  （mock 落 notes/discussions/260904-project-ui-mock.html，票③ UI 设计文档
  的底稿）。
- 2026-09-04（修订8）：宿主裁定 UI 降级——「不需要单独一页，左栏已列项目，
  找个合适位置放创建按钮」。面D 重写为左栏内嵌三处新增（「＋接入项目」行 /
  组头「⋯」菜单 / 隔离行），交互全走小弹层（session-entry 确认弹层先例）；
  票计数与体检黄牌只进弹层不进日常视图；决策8 入口定稿、票③ 交付面与
  验收 11–13 同步重写；mock v2 同路径重写。
- 2026-09-04（修订9）：宿主问询「可能需要每个项目单独的设置入口？摘除怎么
  进的没看懂」——v2 的 hover「⋯」过隐蔽，弃用；采纳宿主提议=组头「⚙️」
  项目设置入口（常驻第五图标），设置弹层（只读：信息/票计数/体检+底部
  danger 区摘除）成为摘除的显式入口；面D/决策8/票③/验收11·13 同步；
  mock v3 同路径重写。
- 2026-09-04（修订10）：宿主令「四个 icon 太小、不统一，顺便做一套」——
  组头图标族统一入面D/票③/验收11b：emoji（📋📖🔀🗂️）→ SVG 线性图标
  五枚（工单/知识库/路由/立项/设置），规格成文（20 viewBox·1.6 线宽·
  currentColor·18px 显形·26×26 命中区·三态）；存量四图标换装零回归入验收；
  mock v4 同路径重写（含图标族规格卡）。
- 2026-09-04（修订11）：宿主图标反馈两枚重绘——「设置 icon 不太合适」
  （轮辐齿轮读作太阳）→ 改**滑杆**（三轨偏置旋钮）；「路由那个通常是
  share」→ 改**带箭头分流**（箭头=方向性，与 share 的节点连线无箭头拉开）；
  规格不变，mock v5 同路径更新。
- 2026-09-04（修订12）：宿主过稿令「可以了，开始这个epic吧。建第一个
  工单」——状态 已立项（待开工单）→ **已立项（执行中）**；**票① 开工
  = t260904-10**（dev-lane / developer / EpicCode=project-lifecycle /
  泳道 .lane/t260904-10；写集 server/installer/+integration/+docs/ops/——
  本档原写集含「本档」一项，因建票机械闸禁 notes/ 修正为 integration 在
  main 直管）；验收7 残留「⚑4 拍板后钉死」尾巴清理（拍板早已落）。
- 2026-09-04（修订13）：票① 收口+票② 开工。t260904-10 merge 人门代签
  （授权出处=宿主「看下project-lifecycle的票，往下接着做」，本签仅覆盖该票）
  → squash 落 main（30d70d7：projects.py 427 行 add/list+校验闸+原子写+体检
  报告、installer tests 494 行、双侧装载/拒收枚举/list 报告三场景、ops 手册
  初版）；main 抽查=projects.py 语法 OK、deliverables 齐位。**票② 开工
  = t260904-14**（dev-lane / EpicCode=project-lifecycle / 泳道
  .lane/t260904-14；写集 server/installer/+integration/+docs/ops/+docs/design/
  ——remove 面：在飞闸/退役移位/purge 双旗+dry-run/re-add 归档链/契约①a
  两增补节/upgrade.py docstring 清理；验收 5-10）。票③（UI 面）待票②
  CLI --json 口径定稿后开工。
- 归档快照：收尾时补（`EpicCode` 查询工单清单 + 结论固化进本档）。
- 2026-09-05（收官句号，260904 夜间授权代笔）：**三票全落地，epic 完结**。
  `EpicCode` 查询实录：t260904-10（close 09-04 11:06，接入面 CLI+校验闸）、
  t260904-14（close 12:43，remove 面+契约 v1.9）、t260904-15（close 15:50，
  UI 面三处新增+三弹层+图标族）。全周期人门签=宿主直接/授权代签混合
  （14 两签含 KI-048 首签蒸发重签先例）。结论固化：项目接入→退役→UI 呈现
  全链可用；契约真源=sandbar 侧（宿主裁定 26f174c）。台账句号，后续增量
  需求另立票挂本 epic 或新开。

> **存档补注（260910 integration）**：上述 t260904-10/14/15 三票的 Temporal
> 事件历史已于 260908 数据事故（KI-065）中丢失——现 Temporal 查无此三单属正常，
> 非未交付。交付真实存在的三方佐证=本档文字记录 + workbench 源码（泳道图/执行
> 规格卡/快照要点/平铺行卡 v4/项目 UI 路由）+ 常驻场景（t260904-15-project-ui-
> host-routes、t260905-07-ticket-detail-panel、t260904-06-spec-card-dom 等全绿）。
> 注意区分：本 epic 的 mock v5=**项目管理 UI**（260904-project-ui-mock.html），
> 已随票③落地；而「工单详情 UI 重设计」是**另一个 mock**（260904-ticket-detail-
> ui-mock.html，六屏，驱动面=KI-019 泳道图失真/KI-024·027 观测盲区/KI-048 观测面），
> 无落地票，仅部分片段被后续票顺带实现（快照要点/并行分叉/执行规格卡），主体
> （①总布局人话状态卡·泳道图·检查明细、②红灯文案对照、③真泳道双道与逐轮分格）
> 未落地。归「工单详情观测面重设计」票，见排队计划 260910-ticket-queue-plan.md。
- 2026-09-04（修订14）：票② 收口+票③ 开工。t260904-14 merge 人门两签落
  main（3f99dce：remove 面+契约①a-1 v1.9 增补节）；首签被 main 脏工作区
  （宿主未提交的契约 v1.8 真源转正编辑）挡 squash 蒸发——处置=v1.8 经确认
  代提交（26f174c，宿主裁定：本仓契约即真源、suyou 侧降历史冻结）+main 预
  并泳道（d1c933f，v1.8/v1.9 两行并集）+重签；观测缺口记 KI-048。**票③
  开工 = t260904-15**（dev-lane / EpicCode=project-lifecycle / 泳道
  .lane/t260904-15；写集 server/dsh/workbench/+integration/+docs/design/
  ——UI 面：左栏三处新增+三弹层+图标族 SVG 五枚+写路由薄壳；验收 11-14；
  mock v5 过稿落档 400a870 作票内背景件）。
