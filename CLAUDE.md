# sandbar — 多项目工单引擎

从 suyou 仓物理搬迁而来（M2-B，v0.1.0 干净基线）。本仓=sandbar 引擎真源
（suyou 侧引擎已冻结，只改本仓）。逐文件判定真源与搬迁史见 suyou 仓
notes/debts/sandbar-m2-migration-manifest.md。

## 目录
- server/engine/：引擎本体（base/dev_lane/worker/client/agent_activities）
- server/plugins/：插件族（ui/workbench/knowledge/providers/temporal-tools 等）
- server/profile/、server/profile-headless/：装配配方两变体（headless 的 patch 仍为软链）
- server/tools/：verify_lane/ticket/workflow/dispatcher_loop
- server/roles/、server/model-routes.yaml：项目侧声明（角色 persona/模型路由）
- server/headless-resume/、server/workflows/、server/ui-check/：平移件与界面核查面

## 硬规则
1. console（3099）永属用户操作面：任何代码/测试/安装器不得重启/停止/占用。
2. 小步 commit；写集白名单内干活。
3. 文档与代码注释用**英文**、按 8 条 STE 口径写（261004 宿主令：本条原「现代中文」
   口径退役，**存量不动**、改到哪处就按新规范；旧口径的机械闸见
   `integration/lint_copy_language.py`）。`notes/` 知识库账本（KI 册、立项单、
   讨论稿）**保持中文**，新写文字按同文件的受控中文 8 条。细则以
   `server/session_charter.md` 与 `docs/reference/writing-standard.md` 为准。
4. 本仓只读 ~/Documents/suyou 的历史文档作参考，不回写。
4b. **提选项说人话、说短、一律标号**（宿主令 261016）：给宿主列选项时用大白话——
    一条选项一行，写明「选它会发生什么」；**选项一律用小写字母 a/b/c/d 标号**
    （不混用甲乙丙或 1/2/3）；不要长篇技术论证、不要堆术语、不要大段行话。
    整条回复能短就短（宿主原话：「凡是提出选项，必须说人话，而且不要写长篇大论」
    「给选项一律 a,b,c,d」）。
5. 「suyou」之名退役（宿主令 260904）：新开发的代码、文档、注释、命名一律
   不再用 suyou 字样——新环境变量、路径、API 前缀、工具与文件名用 sandbar
   或中性名。存量 suyou 标识（如 SUYOU_* env、/suyou-workbench/ 前缀）是
   历史欠账，只随专门迁移票处置，不随手改。
6. 工单（ticket）的标题与内容一律用**英文**写（宿主令 260924）：新开票的
   title、spec、body、deliverables、acceptance，以及返工原因、签字与裁决等
   票面文字，全用英文——票面是给跨项目收件人看的对外件。文档与代码注释的
   语言口径见规则 3（261004 后：文档/代码注释英文，`notes/` 知识库中文），
   两者分工明确：**票英文**，不要把中文票面混进来。
   补充（宿主令 260925）：**控制台 UI 的界面文案一律英文**——含左侧工单列表字段、
   泳道图阶段标签、状态与枚举标签（「进行中」类）、区块标题等；**数据不译**：票面
   正文、交接报告、台账等保持各自原语言（「英文界面 + 中文内容」是预期形态）。
   英文标签以**引擎既有英文标识**为真源（stage id、stage_state、status），由前端
   映射表统一映射，不另造词、不逐页各译。
