# t260922-06 验收走查报告（acceptance_walkthrough gen5，integration）

走查人视角：不预设「测试已通过」，从用户场景独立实证。走查日期 2026-09-22（本段第 6 次）。
结论先行：**status=ok**——票面五条验收判据中 ①②③⑤ 判定通过，④ 为「判据载体已声明、live 执行外置升级门槛（前置缺口已三处在案登记）」的未验项，不属本票半径；本轮机械 7 败 + 4 环境红经逐条归因**零本票归因**；本票两场景**六轮全绿**。

## 一、gen4→gen5 什么变了（给不熟悉本工单的人）

- **产品代码与测试资产零变化**：gen4 走查后唯一入库 commit（4cc99f6）内容=我 gen4 验收报告
  md（worker 代落盘）；写集全部文件内容与 mtime 和 gen0 走查时全同。**gen0–gen4 全部技术结论
  原样继承**（源码实证详版=已入库 `acceptance-walkthrough-gen0.md`，delta 见 gen1–gen4）。
- 本轮机械回执（out/integration-report-260922-122958.json，12:29）红集进一步收窄至最简结构：
  **6 条确定性他票债 + stage-console 族 5 条口耗尽**，再无其它。上轮红脸
  t260903-07-chat-project-tag 本轮转绿——与仲裁 gen4 直跑二次证绿（8/8 exit 0）互证其
  「供给态+console-miss 三态失真」归因。六轮红集轨迹（9败/0环 → 7败/4环 → 11败/8环 →
  8败/4环 → 8败/4环 → 7败/4环）呈单调收敛：环境噪声在翻转后沉淀为唯一持续项（口位耗尽），
  确定性核心 6 条五轮+逐条不动。本票两场景（池=ro 零网络零台面）六轮全绿。

## 二、逐判据验收结论（票面五条；证据链详版见 gen0–gen4 报告）

### ① id 映射面（核心）——通过

单点真源=**自定义 id 本身**（`<ticket>-<role>`），无需映射表；0.1.1/0.1.5 寻址口径无漂移。
integration 独立源码实证（解包 0.1.5-rc.2 六包+本机 0.1.1-rc.2 实装核对）：0.1.5
`SessionStore.prepare` 传 id 原样采用（dsh-session :1374-1379）；`assertStoredId`（persistence
:157）响亮校验；`sessionDir=projectDir/encodeSegment(id)`（persistence-jsonl :852/:913）；
`findLog` 跨项目扫描+重名响亮（:3194-3205）；uuid 目录来源=stock runner 自传
`session-${randomUUID()}`（stock headless :135）——票面「按 uuid 寻址」根因表述不成立，真
接缝=形状面。装配级：faces F1/F2 桩账本断言自定义 id 原样进 `agents.resume`；引擎注入位
`agent_activities.py:2321` 同源。0.1.1 回归锚：legacy 四条 stderr 文案逐字保持（L1 golden
+HEAD~1 对照），legacy 聚合语义逐字同构。

### ② 形状面响亮报错点名、不崩栈——通过

`requireAgent` 守卫覆盖全部四处调用点（faces F4/F6/F8+回落链）；会话形状/seq 缺口/content
链断裂各有点名词（F3/F7+L1 畸形族）；全局判据=八面 stderr 全行词汇表形状、零裸栈、零
「is not iterable」零 TypeError（本轮实跑 49/49 绿）。对抗突变自证 4 项：判据真能红，回归
形态仍是响亮点名。

### ③ 禁静默——通过

回落链两级宣告逐字保留且带原始错因（F4/F5）；KI-059 撕裂链实况形状双宣告齐全+「上下文不可
恢复」大声说；本票 implement 段自身撕裂会话检疫在案（`.sandbar/quarantine/torn-*`）。

### ④ 可重跑判据（0.1.1/0.1.5 同命令对照）——判据载体已声明，live 执行外置，未验

判据载体=探针 `--version` 双版对照（升级门槛集成闸机械段执行）。**响亮标注**：探针
`check_resume` 缺「首次建档 spawn」→ 冷启动在 0.1.1 基线也红、两侧皆红不可判定；该
cold-start 缺口按票面边界（探针工具归 t260922-03）在方案附2+登记行+README 第 10 组三处在案，
**升级门槛执行验收④前必须先收口**（前置拦停条件）。泳道内可机械化部分已收：双形状装配级
等价（F2E）+读侧同 id 双向锚。

### ⑤ read-side 一致——通过

引擎读侧 UT 8 例（0.1.5 布局命中/头记录 type=session 入册/encodeSegment 引擎字符集恒等/两层
半径不扩大）+ dualname 23 例并行绿；读侧匹配与写/续侧同源同 id，杜绝「读得到但续不上」。

## 三、本轮机械集成结果归属（273 跑 / 262 过 / 7 败 / 4 环境红；跳过池=engine、exclusive）

本票两场景本轮机械跑 **PASS**（faces 1.4s / wiring 0.1s，六轮全绿）。11 条非 PASS 逐条归因，
**零本票归因**（无一条触及 server/headless-resume、server/engine、integration/t260922-06）：

| # | 场景 | 归因 |
| --- | --- | --- |
| 1 | t260903-02-lock-update-integrity | 他票资产带入的打回点计数锁漂移（六轮稳定） |
| 2 | t260904-12-no-skip-guard | 残留守卫命中他票资产（t260917-02 / t260921-04/05 族） |
| 3 | t260907-04-naming-grep-assert | 旧名残留命中他票 acceptance 文档 |
| 4 | t260907-05-naming-residue-fulltext | 旧名全文残留族（唯一稳定闸拦，六轮不动） |
| 5 | auto-rework-trace + t260917-07 | 同根：测试台命名空间字面量漂移（在册 TDD 信号窗口） |
| 6 | t260916-25-stage-console-{lifecycle,guardrails,fault-paths,prepare-refresh} | 4×ENV_FAIL：高位口 3511-3549 全被占（五轮同象，机器层口位耗尽未恢复；三态契约如实报不造假红） |
| 7 | t260916-25-stage-console-selfcheck-red | FAIL 同因（三行判据均自报「高位口耗尽」） |

上轮红脸 t260903-07-chat-project-tag 本轮转绿（与仲裁 gen4 直跑 8/8 证绿互证）；browser 链
（t13 / lane-parallel-dom / charter-injection）本轮亦全绿。红集已收敛至「他票资产债 + 机器层
口位耗尽」两个与环境供给相关的稳定族，本票面六轮零归因。

## 四、测试资产变更审查（对照打回轮次）

gen4 走查 → 本轮：**测试资产零变更**（git 唯一新 commit=我 gen4 验收 md；写集文件 mtime/内容
与 gen0 走查时全同）。本票测试资产全部本票新建、gen0 已逐文件审读（断言锚公开契约、无绿灯
捷径、4 项突变红侧自证），结论维持，无新增审查对象。

## 五、并行期 UI 呈现检查

**不适用**：本票改动面为 server 端插件（headless-resume）、引擎注释与读侧 UT、CLI 形态集成
场景，无任何 UI/泳道图渲染面。

## 六、收口两问（承 gen0–gen4，结论不变）

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

## 七、遗留与风险（交下一棒/升级门槛，承前五轮不变）

1. **验收④ live 双版对照未跑**（本泳道禁跑 live）：升级门槛机械段执行；执行前必须先由
   t260922-03/判据票收口探针 cold-start 缺口——升级门槛前置拦停条件，不是可选项。
2. TS loader 对 sibling URL 导入的完整 live 裁决归升级门槛（在案旁证=本泳道 implement 段
   真实 dsh 会话「已恢复会话」行；wiring 场景守物化/拷贝副本面；兜底判据已写死 node.ts 头注）。
3. 0.1.5 对既有 0.1.1 旧档代数迁移可续性未实证（机制在场已实证，live 判定归升级门槛对照）。
4. 机械非 PASS 全为他票/环境既有债：确定性核心 6 条六轮同象（属主随码刷新，在本票迭代面外）；
   stage-console 高位口耗尽五轮未恢复（merge 期按环境缺件处置：补空口位/错峰重跑）。均不计入本票。

## 参考 docs 清单（读过）

- docs/README.md（目录）
- docs/design/dsh_seam需求书v1.md（A4 节 / resume 行为契约 / 对标取舍表 / 验收样例 / Nongoal，逐节读）
- 非 docs 侧声明路径：integration/README.md（第 10 组）、integration/run_scenarios.py（登记行）、notes/debts/known-issues.md（KI-059/051/046）、.sandbar/plan_t260922-06_resume_addressing.md（方案+review 补记）
