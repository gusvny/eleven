# t260922-06 验收走查报告（acceptance_walkthrough gen2，integration）

走查人视角：不预设「测试已通过」，从用户场景独立实证。走查日期 2026-09-22（本段第 3 次，gen1 走查随仲裁回路作废后重走）。
结论先行：**status=ok**——票面五条验收判据中 ①②③⑤ 判定通过，④ 为「判据载体已声明、live 执行外置升级门槛（前置缺口已三处在案登记）」的未验项，不属本票半径；本轮机械 11 败 + 8 环境红经逐条归因**零本票归因**。

## 一、gen1→gen2 什么变了（给不熟悉本工单的人）

- **产品代码与测试资产零变化**：gen1 走查后唯一入库 commit（64651df）内容=我 gen1 的验收报告
  md（worker 代落盘）；写集全部文件（node.ts / summarize.js / 两个单测 / 两条场景 / 引擎读侧
  UT）内容与 mtime 均与前两轮走查时全同。**gen0/gen1 的全部技术结论原样继承**（完整源码实证
  链见已入库的 `integration/t260922-06/acceptance-walkthrough-gen0.md`，delta 见
  `acceptance-walkthrough-gen1.md`）。
- 变化的又是**机械环境噪声分布**：本轮共享测试台（127.0.0.1:21050）的事件通道
  （`/api/events.mux` WebSocket）拒连，使 browser 链红翻转（t13 / lane-parallel-dom 上轮绿
  本轮红，charter-injection 反之）并新现两条「console-hygiene」失败；另有一族 decl-gate/deadman
  类场景按三态契约如实报 ENV_FAIL（temporalio/共享台不可达）。三轮合看（9 败/0 环 → 7 败/4 环 →
  11 败/8 环），红集在环境/台面层轮转翻覆、无一条稳定落在本票面；本票两场景三轮全绿
  （本组场景池=ro 零网络零台面，设计上对该噪声免疫）。

## 二、逐判据验收结论（票面五条；证据链详版见 gen0/gen1 报告）

### ① id 映射面（核心）——通过

单点真源=**自定义 id 本身**（`<ticket>-<role>`），无需映射表；0.1.1/0.1.5 寻址口径无漂移。
integration 独立源码实证（解包 0.1.5-rc.2 六包+本机 0.1.1-rc.2 实装核对）：0.1.5
`SessionStore.prepare` 传 id 原样采用（dsh-session lib/index.js:1374-1379）；`assertStoredId`
（persistence :157）头记录校验响亮；`sessionDir = projectDir/encodeSegment(id)`
（persistence-jsonl :852/:913）；`findLog` 跨项目扫描+重名响亮（:3194-3205）；uuid 目录来源=
stock runner 自传 `session-${randomUUID()}`（stock headless :135）——票面「按 uuid 寻址」根因
表述不成立，真接缝=形状面。装配级：faces F1/F2 桩账本断言自定义 id 原样进 `agents.resume`；
引擎注入位 `agent_activities.py:2321` 同源。0.1.1 回归锚：legacy 四条 stderr 文案逐字保持
（L1 golden+HEAD~1 对照），legacy 聚合语义逐字同构。

### ② 形状面响亮报错点名、不崩栈——通过

`requireAgent` 守卫覆盖全部四处调用点（faces F4/F6/F8+回落链）；会话形状/seq 缺口/content
链断裂各有点名词（F3/F7+L1 畸形族）；全局判据=八面 stderr 全行词汇表形状、零裸栈、零
「is not iterable」零 TypeError（本轮实跑 49/49 绿）。对抗突变自证 4 项（design 三项+走查
新增 legacy 分支打死）：判据真能红，回归形态仍是响亮点名。

### ③ 禁静默——通过

回落链两级宣告逐字保留且带原始错因（F4/F5）；KI-059 撕裂链实况形状（resume not found→同 id
create 撞撕裂帧→fresh id 兜底）双宣告齐全+「上下文不可恢复」大声说；本票 implement 段自身
撕裂会话检疫在案（`.sandbar/quarantine/torn-*`）。

### ④ 可重跑判据（0.1.1/0.1.5 同命令对照）——判据载体已声明，live 执行外置，未验

判据载体=探针 `--version` 双版对照（升级门槛集成闸机械段执行）。**响亮标注**：探针
`check_resume` 缺「首次建档 spawn」→ 冷启动在 0.1.1 基线也红、两侧皆红不可判定；该
cold-start 缺口按票面边界（探针工具归 t260922-03）在方案附2+登记行+README 第 10 组三处在案，
**升级门槛执行验收④前必须先收口**（前置拦停条件）。泳道内可机械化部分已收：双形状装配级
等价（F2E）+读侧同 id 双向锚。

### ⑤ read-side 一致——通过

引擎读侧 UT 8 例（0.1.5 布局命中/头记录 type=session 入册/encodeSegment 引擎字符集恒等/两层
半径不扩大）+ dualname 23 例并行绿；读侧匹配与写/续侧同源同 id，杜绝「读得到但续不上」。

## 三、本轮机械集成结果归属（273 跑 / 254 过 / 11 败 / 8 环境红；跳过池=engine、exclusive）

本票两场景本轮机械跑 **PASS**（faces 0.7s / wiring 0.0s），三轮全绿。19 条非 PASS 逐条归因，
**零本票归因**（无一条触及 server/headless-resume、server/engine、integration/t260922-06）：

| # | 场景 | 归因 |
| --- | --- | --- |
| 1 | t260903-02-lock-update-integrity | 他票资产带入的打回点计数锁漂移（三轮稳定在册） |
| 2 | t260904-12-no-skip-guard | 残留守卫命中他票资产（t260917-02 / t260921-04/05 族） |
| 3 | t260907-04-naming-grep-assert | 旧名残留命中他票 acceptance 文档 |
| 4 | t260907-05-naming-residue-fulltext | 旧名全文残留族（唯一稳定闸拦） |
| 5 | auto-rework-trace + t260917-07 | 同根：测试台命名空间字面量漂移（在册 TDD 信号窗口） |
| 6 | ticket-session-restore | **本轮新现**：功能面 9 项全 PASS（open-shape/reopen-no-duplicate/malformed-id/missing-project/unknown-project/404/零注入等），唯一 FAIL=`browser/console-hygiene`——共享台 21050 `events.mux` WebSocket 拒连（ERR_CONNECTION_REFUSED），台面事件通道环境面，非会话恢复功能面；与本票写集无涉 |
| 7 | t260904-05-top-entry-retired-form | 同 #6 根：t6 console-hygiene 同一 events.mux 拒连 + ERR_INCOMPLETE_CHUNKED；功能面 9 项全 PASS |
| 8 | t13-evidence-lightbox / lane-parallel-dom | browser 链台面拒连翻转（上轮绿本轮红，charter-injection 反向翻转）——台面可用性环境噪声 |
| 9 | t260905-03-decl-gate / t260910-09-ms-decl-gate / t260913-02-schedule-daily-deadman / t260916-26-stage-plugins-selfcheck | 4×ENV_FAIL：temporalio/共享测试台/docker 台不可达——三态契约如实报环境红，不假红不假绿 |
| 10 | t260916-25-stage-console-{lifecycle,guardrails,fault-paths,prepare-refresh,selfcheck-red} | 4×ENV_FAIL+1×FAIL：高位口 3511-3549 全被占（同 gen1，机器层瞬时状态） |

## 四、测试资产变更审查（对照打回轮次）

gen1 走查 → 本轮：**测试资产零变更**（git 唯一新 commit=我 gen1 验收 md；写集文件 mtime/内容
与 gen0 走查时全同）。本票测试资产全部本票新建、gen0 已逐文件审读（断言锚公开契约、无绿灯
捷径、4 项突变红侧自证），结论维持，无新增审查对象。

## 五、并行期 UI 呈现检查

**不适用**：本票改动面为 server 端插件（headless-resume）、引擎注释与读侧 UT、CLI 形态集成
场景，无任何 UI/泳道图渲染面。

## 六、收口两问（承 gen0/gen1，结论不变）

### doc_sediment（沉淀一问）

**want=true**。`target=docs/design/dsh_seam需求书v1.md（A4 事实基线节 + 对标取舍表）`；
`reason=` 本票源码实证产出三条 dsh 接缝域长期有效事实而 A4 现锚 0.1.1-rc.2：①0.1.5 会话 id
寻址口径与 0.1.1 无漂移（自定义 id 原生有效、uuid 目录仅 stock 自传）；②0.1.5 真接缝=形状面
（`Session.events` 移除→`eventAt(SessionSeq(seq))` 半开区间），自研 runner 已双形状兼容；
③取舍表引用的 node.ts 行号（:82/:99/:106-107/:118-124/:150-153/:157-160）经本票重构后漂移
（行为主张仍成立，仅锚位陈旧）。docs 不在本票写集→交 merge 关卡/后续 doc 票。

### doc_conflicts（反向同步闸）

**无被推翻主张（空清单）**。核对基线=实际逐节读过的 `docs/design/dsh_seam需求书v1.md`：
A4 节、行为契约 6 条、对标取舍表、验收样例、Nongoal 与实现及八面场景逐条吻合（详版见 gen0
报告第六节）。deepseek_harness 主档仅关键词扫描未逐节读，不列主张级结论。

## 七、遗留与风险（交下一棒/升级门槛，承前两轮不变）

1. **验收④ live 双版对照未跑**（本泳道禁跑 live）：升级门槛机械段执行；执行前必须先由
   t260922-03/判据票收口探针 cold-start 缺口——升级门槛前置拦停条件，不是可选项。
2. TS loader 对 sibling URL 导入的完整 live 裁决归升级门槛（在案旁证=本泳道 implement 段
   真实 dsh 会话「已恢复会话」行；wiring 场景守物化/拷贝副本面；兜底判据已写死 node.ts 头注）。
3. 0.1.5 对既有 0.1.1 旧档代数迁移可续性未实证（机制在场已实证，live 判定归升级门槛对照）。
4. 机械非 PASS 全为他票/环境既有债（第三节清单）。共享台事件通道（events.mux）与高位口耗尽
   属机器层瞬时状态，两轮间已见翻转；merge 期复跑若仍在，按环境缺件处置（恢复台面/补空口位/
   错峰重跑），不计入本票。

## 参考 docs 清单（读过）

- docs/README.md（目录）
- docs/design/dsh_seam需求书v1.md（A4 节 / resume 行为契约 / 对标取舍表 / 验收样例 / Nongoal，逐节读）
- 非 docs 侧声明路径：integration/README.md（第 10 组）、integration/run_scenarios.py（登记行）、notes/debts/known-issues.md（KI-059/051/046）、.sandbar/plan_t260922-06_resume_addressing.md（方案+review 补记）
