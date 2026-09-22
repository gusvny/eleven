# t260922-06 验收走查报告（acceptance_walkthrough gen1，integration）

走查人视角：不预设「测试已通过」，从用户场景独立实证。走查日期 2026-09-22（本段第 2 次，gen0 走查随仲裁回路作废后重走）。
结论先行：**status=ok**——票面五条验收判据中 ①②③⑤ 判定通过，④ 为「判据载体已声明、live 执行外置升级门槛（前置缺口已三处在案登记）」的未验项，不属本票半径；本轮机械 7 败 + 4 环境红经逐条归因**零本票归因**。

## 一、gen0→gen1 什么变了（给不熟悉本工单的人）

- **产品代码与测试资产零变化**：gen0 走查后入库的唯一 commit（71f90ac）内容=我 gen0 的验收报告
  md 本身（worker 代落盘）；node.ts / summarize.js / 两个单测 / 两条场景的 mtime 与内容均与
  gen0 走查时全同。**gen0 的全部技术结论原样继承**（完整源码实证链见
  `integration/t260922-06/acceptance-walkthrough-gen0.md`，已入库）。
- 变化的只有**机械集成环境噪声的分布**：上轮 3099 台面拒连的三条（t13-evidence-lightbox /
  lane-parallel-dom / charter-injection-journey）本轮全部转绿——反证 gen0「环境面」归因正确；
  本轮新增 stage-console 族高位口（3511-3549）耗尽 → 4 条 ENV_FAIL + 1 条 FAIL（同因）。
- 仲裁 gen0 verdict=tests-fault（九红无一落本票写集产品面）与本走查独立归因一致；本报告
  不替仲裁下结论，只给走查事实。

## 二、逐判据验收结论（票面五条；证据链详版见 gen0 报告）

### ① id 映射面（核心）——通过

单点真源=**自定义 id 本身**（`<ticket>-<role>`），无需映射表；0.1.1/0.1.5 寻址口径无漂移。
integration 独立源码实证（解包 0.1.5-rc.2 六包 + 本机 0.1.1-rc.2 实装逐条核对）：0.1.5
`SessionStore.prepare`（dsh-session lib/index.js:1374-1379）传 id 原样采用；`assertStoredId`
（persistence :157）头记录 id 不符响亮拒绝；`sessionDir = projectDir/encodeSegment(id)`
（persistence-jsonl :852/:913，两层半径）；`findLog` 跨项目目录扫描+重名响亮（:3194-3205）；
uuid 目录的来源=stock runner 自己传 `session-${randomUUID()}`（stock headless :135）——
**票面根因表述（按 uuid 寻址）不成立，真接缝=形状面**。装配级：faces F1/F2 桩账本断言自定义
id 原样进 `agents.resume`；引擎注入位 `agent_activities.py:2321` 同源。0.1.1 回归锚：legacy
四条 stderr 文案逐字保持（L1 golden 锁死 + 对照 HEAD~1 原文相符），legacy 聚合语义逐字同构。

### ② 形状面响亮报错点名、不崩栈——通过

`requireAgent` 守卫覆盖全部四处调用点（faces F4/F6/F8+回落链覆盖）；会话形状/seq 缺口/content
链断裂各有点名词（F3/F7 + L1 畸形族）；全局机械判据=八面 stderr 全行词汇表形状、零裸栈、
零「is not iterable」零 TypeError 字样（本轮实跑 49/49 绿）。integration 对抗突变探针（gen0，
/tmp 副本打死 legacy 形状分支）：突变后 exit 1 + 诊断行保真 + 响亮点名，判据真能红且失败
形态仍是本判据承诺的响亮点名。

### ③ 禁静默——通过

回落链两级宣告逐字保留且带原始错因：「恢复会话 X 失败（回落新建同 id 会话）」（F4/F5 带 id
与错因）、「同 id 新建仍失败…改用全新会话 id（上下文不可恢复…）」（F5，KI-059 撕裂链实况
形状；本票 implement 段自身即发生撕裂会话并检疫——`.sandbar/quarantine/torn-*` 在案）。
用户不可能「以为续上了」。

### ④ 可重跑判据（0.1.1/0.1.5 同命令对照）——判据载体已声明，live 执行外置，未验

判据载体=探针 `--version` 双版对照（升级门槛集成闸机械段执行，dev 段禁跑 live）。**响亮
标注**：探针 `check_resume` 现版缺「首次建档 spawn」→ 冷启动回落新建在 0.1.1 基线上也产
新会话文件 → 两侧皆红不可判定；该 cold-start 缺口按票面边界（探针工具归 t260922-03）在
方案附2 + run_scenarios 登记行 + integration/README 第 10 组三处在案。**升级门槛执行验收④
前必须先收口此缺口**（前置拦停条件，非可选）。泳道内可机械化的部分已收：双形状装配级
等价（F2E）+ 读侧同 id 双向锚。

### ⑤ read-side 一致——通过

引擎读侧 UT 8 例（0.1.5 布局命中 / 头记录 type=session 入册不翻「格式不认识」/
encodeSegment 在引擎 id 字符集下恒等 / 两层半径不扩大）+ dualname 既有套件 23 例并行绿。
读侧 sub 目录名匹配与写/续侧 `encodeSegment(自定义 id)=恒等` 同源同 id——「读得到即可续上」。

## 三、本轮机械集成结果归属（273 跑 / 262 过 / 7 败 / 4 环境红；跳过池=engine、exclusive）

本票两条场景本轮机械跑 **PASS**（faces 0.8s / wiring 0.0s），且本泳道复跑双绿。11 条非 PASS
逐条归因，**零本票归因**（无一条触及 server/headless-resume、server/engine、integration/t260922-06）：

| # | 场景 | 归因 |
| --- | --- | --- |
| 1 | t260903-02-lock-update-integrity | 他票资产带入的打回点计数锁漂移（dev_lane 演进 vs 锁） |
| 2 | t260904-12-no-skip-guard | 残留守卫命中他票资产（t260917-02 / t260921-04/05 族） |
| 3 | t260907-04-naming-grep-assert | 旧名残留命中他票 acceptance 文档（t260916-24 gen5） |
| 4 | t260907-05-naming-residue-fulltext | 旧名全文残留族（在册闸拦；仲裁轮新增发现=tracked 审计日志档命中） |
| 5 | auto-rework-trace | 测试台命名空间字面量漂移（test Temporal 无该命名空间） |
| 6 | t260917-07-test-ns-consistency | 同 #5 根：保护文件 TEST_NS 漂移，在册 TDD 信号窗口 |
| 7 | t260916-25-stage-console-selfcheck-red | **本轮新现，环境面**：高位口 3511-3549 全被占（其三行判据均自报「高位口耗尽」） |
| 8-11 | t260916-25-stage-console-{lifecycle,guardrails,fault-paths,prepare-refresh} | 4×ENV_FAIL，同因高位口耗尽——场景按三态契约如实报环境红，不造假红 |

上轮三条 3099 拒连（t13-evidence-lightbox / lane-parallel-dom / charter-injection-journey）
本轮全绿，证实 gen0「环境拒连」归因；本轮 stage-console 口耗尽属机器层瞬时状态，与上轮
同族（环境噪声在不同场景上轮转），两轮合看无一条稳定落在本票面。

## 四、测试资产变更审查（对照打回轮次）

gen0 走查 → 本轮：**测试资产零变更**（git 唯一新 commit=我 gen0 的验收 md；L1 两件 + 两场景
+ 引擎读侧 UT 的 mtime/内容与 gen0 走查时全同）。本票测试资产全部为本票新建，gen0 已逐文件
审读（断言锚公开契约、无绿灯捷径；4 项突变红侧自证），结论维持。本轮无新增审查对象。

## 五、并行期 UI 呈现检查

**不适用**：本票改动面为 server 端插件（headless-resume）、引擎注释与读侧 UT、CLI 形态集成
场景，无任何 UI/泳道图渲染面。

## 六、收口两问（承 gen0，结论不变）

### doc_sediment（沉淀一问）

**want=true**。`target=docs/design/dsh_seam需求书v1.md（A4 事实基线节 + 对标取舍表）`；
`reason=` 本票源码实证产出三条 dsh 接缝域长期有效事实而 A4 现锚 0.1.1-rc.2：①0.1.5 会话
id 寻址口径与 0.1.1 无漂移（自定义 id 原生有效、uuid 目录仅 stock 自传）；②0.1.5 真接缝=
形状面（`Session.events` 移除→`eventAt(SessionSeq(seq))` 半开区间），自研 runner 已双形状
兼容；③取舍表引用的 node.ts 行号（:82/:99/:106-107/:118-124/:150-153/:157-160）经本票
重构后漂移（行为主张仍成立，仅锚位陈旧）。docs 不在本票写集→交 merge 关卡/后续 doc 票。

### doc_conflicts（反向同步闸）

**无被推翻主张（空清单）**。核对基线=实际逐节读过的 `docs/design/dsh_seam需求书v1.md`：
A4 节、行为契约 6 条、对标取舍表、验收样例、Nongoal 与实现及八面场景逐条吻合（详见 gen0
报告第六节）。deepseek_harness 主档仅关键词扫描未逐节读，不列主张级结论。

## 七、遗留与风险（交下一棒/升级门槛，承 gen0 不变）

1. **验收④ live 双版对照未跑**（本泳道禁跑 live）：升级门槛机械段执行；执行前必须先由
   t260922-03/判据票收口探针 cold-start 缺口——升级门槛的前置拦停条件，不是可选项。
2. TS loader 对 sibling URL 导入的完整 live 裁决归升级门槛（在案旁证=本泳道 implement 段
   真实 dsh 会话「已恢复会话」行=装载成功；wiring 场景守物化/拷贝副本面；兜底判据已写死
   node.ts 头注：仅 `ERR_MODULE_NOT_FOUND` 指向 summarize.js 才内联回退）。
3. 0.1.5 对既有 0.1.1 旧档的代数迁移可续性未实证（0.1.5 源码确有版本排序迁移选择机制，
   本票实证到机制在场；live 判定归升级门槛对照）。
4. 机械非 PASS 全为他票/环境既有债（第三节清单）；stage-console 口耗尽属机器层瞬时状态，
   若 merge 期复跑仍在，按环境缺件处置（补空口位/错峰重跑），不计入本票。

## 参考 docs 清单（读过）

- docs/README.md（目录）
- docs/design/dsh_seam需求书v1.md（A4 节 / resume 行为契约 / 对标取舍表 / 验收样例 / Nongoal，逐节读）
- 非 docs 侧声明路径：integration/README.md（第 10 组）、integration/run_scenarios.py（登记行）、notes/debts/known-issues.md（KI-059/051/046）、.sandbar/plan_t260922-06_resume_addressing.md（方案+review 补记）
