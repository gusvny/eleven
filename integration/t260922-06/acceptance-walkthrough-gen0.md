# t260922-06 验收走查报告（acceptance_walkthrough gen0，integration）

走查人视角：不预设「测试已通过」，从用户场景独立实证。走查日期 2026-09-22。
结论先行：**status=ok**——票面五条验收判据中 ①②③⑤ 判定通过，④ 为「判据载体已声明、live 执行外置升级门槛（且有前置缺口登记）」的未验项，不属本票半径；机械集成 9 败经逐条归因全部为他票/环境既有红，零本票归因。

## 一、本票做了什么（给不熟悉本票的人）

票面原判「0.1.5 按 uuid 寻址 → 自定义 id resume 必然 not found」。create_plan 段以源码实证
**修正了根因**：0.1.1 与 0.1.5 的会话 id 寻址口径**无漂移**——自定义 id（`<ticket>-<role>`）
原生全链路有效；探针看到的 `session-<uuid>` 目录只是 stock runner 自己传 uuid 的结果。
真正的接缝是**形状面**：0.1.5 移除了 `Session.events` 快照数组（改走
`eventAt(SessionSeq(seq))` 半开区间），旧插件每次 spawn 跑完后在收尾聚合处抛
`events is not iterable`（exit 1）——resume 机制实效全灭，且「看着续上了却随后崩」。

修复落点（都在写集内）：

| 文件 | 改动 |
| --- | --- |
| `server/headless-resume/summarize.js`（新增） | 会话事件读取/聚合纯函数层：双形状自动判定（v3=eventAt 半开区间 / 0.1.1=events 数组），形状违约一律 `ShapeError` 响亮点名；stderr 词汇表 `messages` 单点（现行四条文案逐字锚） |
| `server/headless-resume/node.ts`（修改） | `agents.resume`/`agents.create` 全部四处调用点加返回形状守卫 `requireAgent`（缺 `.agent` 即点名，不裸崩）；聚合委托 summarize.js（显式 URL 动态导入 sibling）；legacy stderr 四条文案逐字不变 |
| `server/engine/agent_activities.py`（修改） | 纯注释（机械复核非注释改动行数=0）：0.1.5 寻址口径实证补记 |
| `server/engine/tests/test_t260922_06_resume_addressing.py`（新增） | 引擎读侧 0.1.5 布局锚 8 例 |
| `server/headless-resume/test/summarize.test.mjs`（新增） | summarize.js 单测 15 例（取舍①-⑥对锚+畸形输入族） |
| `integration/t260922-06/sc_*.mjs` 两条 + 登记 | L2 灰盒场景：装配行为面八面 + 装载/物化面四面，池=ro 秒级零网络 |

## 二、逐判据验收结论（票面五条，逐条给证据）

### ① id 映射面（核心）——通过

**结论**：单点真源=自定义 id 本身，无需任何映射表；resume 按该口径命中 0.1.5 真会话；
0.1.1 路径行为逐字不变。票面设想的「映射承载三选一」被源码证据否决（任何映射表都是
多余失配面），这一否决有 integration 独立复核背书（见下）。

integration 独立源码实证（不信 developer 转述，解包 /tmp 的 0.1.5-rc.2 六包 + 本机 0.1.1-rc.2 实装逐条核对）：

- 0.1.5 `dsh-session` `SessionStore.prepare`（lib/index.js:1374-1379）：调用方传 id 时
  `sessionId = brandString(id)` **原样采用**，仅 id 缺省才铸 `session-<n>`；
- 0.1.5 `dsh-session-persistence` `assertStoredId`（:157-159）：头记录 id ≠ 请求 id →
  `stored session identity mismatch` 响亮拒绝；
- 0.1.5 `dsh-session-persistence-jsonl`：`encodeSegment`（:852，`[A-Za-z0-9._-]` 恒等+
  `~XXXX` 转义）、`sessionDir = projectDir/encodeSegment(id)`（:913-914，两层半径）、
  `findLog` 跨全部项目目录扫描寻址、重名响亮 `duplicate JSONL session id`（:3194-3205）；
- 0.1.5 stock headless 自己传 `session-${randomUUID()}`（lib/index.js:135）——uuid 目录的
  真正来源，**票面根因表述（按 uuid 寻址）不成立**；
- 0.1.1 侧（本机实装）：`get events()`（dsh-session :1401）、`get seq()`（:1406）在场，
  `eventAt`/`SessionSeq` 均不存在（grep 0 命中）→ 双形状判定在 0.1.1 必走 legacy 分支，
  无误判面。

装配级证据：faces 场景 F1/F2 桩账本断言自定义 id **原样**进 `agents.resume`（不造 uuid、
不查映射表）；引擎 spawn 侧注入位 `agent_activities.py:2321`
`DSH_HEADLESS_SESSION = session_key or "<ticket>-<role>"` 与之同源。

0.1.1 回归锚：四条 stderr 文案经 `messages` 词汇表**逐字**保持——L1 golden 单测锁死，
并与 `git show HEAD~1:server/headless-resume/node.ts` 原文逐一对照相符；legacy 聚合语义
（events 数组+`seq < firstSeq` 跳过）与改前实现逐字同构（diff 复核，零行为漂移）。

### ② 形状面响亮报错点名、不崩栈——通过

- `requireAgent` 守卫覆盖**全部四处调用点**（resume ×1 + create ×3：同 id 回落/全新 id
  兜底/无 resumeId 一次性），判式 `returned == null || returned.agent == null` 兼抓两态
  （faces F4/F6/F8 分别钉 resume、一次性 create、fresh create 三点；同 id create 位由
  F5/F8 链路覆盖）；
- 会话读取面形状守卫（F3 无 eventAt 无 events → 「形状不识别…拒绝静默猜测」exit 1）、
  v3 seq 缺口点名（F7「seq 7 不可读（已捕获长度 9）」）、`session.seq` 非法点名、
  content 链断裂点名（L1 取舍④族）；
- 全局机械判据：八面 stderr **每一行**必须属词汇表形状（`dsh:` / `dsh-headless-resume:` /
  `headless-resume:` 前缀），零裸栈、零 `is not iterable`、零 `TypeError` 字样——
  票面实证真崩点形状「不得复现」的机械形式，实跑 49/49 绿。

### ③ 禁静默（回落新建必须显式点名）——通过

回落链两级宣告逐字保留且带原始错因（报错精确）：F4「恢复会话 X 失败（回落新建同 id
会话）」带 id 与错因；F5（KI-059 撕裂链实况形状：resume not found + 同 id create 撞
zstd 撕裂帧）两级宣告齐全 + 「改用全新会话 id（上下文不可恢复…）」大声说 + fresh id
承接后流程 exit 0。用户不可能「以为续上了」。

### ④ 可重跑判据（0.1.1/0.1.5 同命令对照）——判据载体已声明，live 执行外置，未验

- 判据载体=探针 `--version 0.1.1-rc.2 / 0.1.5-rc.2` 双版对照（升级门槛集成闸机械段执行，
  dev 段禁跑 live，方案 §3 已声明）；
- **响亮标注**：探针 `check_resume` 现版缺「首次建档 spawn」，冷启动回落新建在 0.1.1
  基线上也产新会话文件 → 两侧皆红、机械不可判定。该 cold-start 缺口已按边界条款
  （「探针工具可用性归 t260922-03」）登记为前置（方案附2 + run_scenarios 登记行 +
  integration/README 第 10 组三处在案）。**升级门槛执行验收④前必须先收口此缺口**；
- 本泳道内可机械化的部分已收：双形状装配级等价（F2E stdout 全等）+ 读侧同 id 双向锚
  （读得到即可续上）。

### ⑤ read-side 一致——通过

引擎读侧 UT 8 例：0.1.5 布局（`<--projectKey-->/<id>/session.v3.jsonl.zstd` + v3 头记录
`{"type":"session","version":3,"id":<自定义id>}`）被 `_aggregate_lane_usage` 正常命中；
头记录 type 在 `SESSION_KNOWN_TYPES` 不翻「格式不认识」；encodeSegment 在引擎 id 字符集
下恒等（目录名即 id，读/写/续同源）；负向样例钉住两层半径不扩大。dualname 既有套件
23 例并行绿（零回归）。杜绝「读得到但续不上」：读侧 sub 目录名匹配规则与写/续侧
`encodeSegment(自定义 id)=恒等` 同源同 id。

## 三、机械集成测试结果归属（与仲裁同源，273 跑 / 264 过 / 9 败 / 0 环境红）

本票两条场景 **PASS**：`t260922-06-resume-seam-plugin-faces`（0.9s）、
`t260922-06-resume-seam-plugin-wiring`（0.1s）。9 败逐条归因（无一条触及
server/headless-resume、server/engine、integration/t260922-06）：

| 失败场景 | 归因 |
| --- | --- |
| t260903-02-lock-update-integrity / t260904-12-no-skip-guard | 第二次 main merge 带入的 t260917-02 资产造成的锁漂移/残留（他票） |
| t260907-04-naming-grep-assert / t260907-05-naming-residue-fulltext | 旧名残留族（他票 acceptance 文档残留；闸拦在册） |
| auto-rework-trace + t260917-07-test-ns-consistency | 同根：测试台命名空间字面量漂移（旧 TEST_NS 未随契约改），t260917-07 在册 TDD 信号窗口（他票） |
| t13-evidence-lightbox / lane-parallel-dom / t260904-07-charter-injection-journey | 3099 台面拒连（`ERR_CONNECTION_REFUSED`）+ 在册闸拦（他票/环境面） |

## 四、测试资产变更审查（对照打回轮次）

本票测试资产（L1 两件 + L2 两场景）全部为**本票新建**，无「打回轮次期间被改」的对照面；
逐文件审读结论：**无绿灯捷径**。

- 断言锚公开契约（stderr 词汇语义、退出码、stdout 聚合结果、桩账本=接缝契约面），
  不锚内部结构/私有命名；语义短语判据而非全字面（KI-051 锚语义纪律）；
- 对抗自证判据能红，共 4 项突变：design 段三项（守卫旁路→F4 三重红；v3 判定打死→F2 红；
  回落宣告词被吞→F4 宣告判据红）+ **本轮走查新增一项**（/tmp 副本内打死 legacy 形状
  分支，模拟 0.1.1 路径失效）→ 基线 exit 0+已恢复行+golden；突变后 exit 1 + 诊断行保真
  （已恢复行在场）+「会话事件读取面形状不识别…拒绝静默猜测」点名，无裸栈——回归锚
  判据真能红，且即便回归发生，失败形态仍是验收②承诺的响亮点名；
- intent 分工清晰无重复：L1 守纯函数语义 / faces 守装配面 / wiring 守装载物化面 /
  dualname 族守读侧 / 探针族守 live 门槛——登记行已写明互不替代。

## 五、并行期 UI 呈现检查

**不适用**：本票改动面为 server 端插件（headless-resume）、引擎注释与读侧 UT、CLI 形态
集成场景，无任何 UI/泳道图渲染面。

## 六、收口两问

### doc_sediment（沉淀一问）

**want=true**。建议：`target=docs/design/dsh_seam需求书v1.md（A4 事实基线节 + 对标取舍表）`，
`reason=` 本票源码实证产出三条属 dsh 接缝域的长期有效事实，而该文档 A4 现锚
0.1.1-rc.2：①0.1.5 寻址口径与 0.1.1 无漂移（自定义 id 原生有效、uuid 目录仅 stock 自传，
直接修正「升级即失效」的直觉误判）；②0.1.5 真接缝=形状面（`Session.events` 移除 →
`eventAt(SessionSeq(seq))` 半开区间），自研 runner 已双形状兼容；③对标取舍表引用的
node.ts 行号（:82/:99/:106-107/:118-124/:150-153/:157-160）经本票重构后已漂移（行为
主张仍全部成立，仅锚位陈旧），补 0.1.5 实证时应顺手刷新。docs 不在本票写集 → 交
merge 关卡/后续 doc 票执行。

### doc_conflicts（反向同步闸）

**无被推翻主张（空清单）**。核对基线=实际逐节读过的 `docs/design/dsh_seam需求书v1.md`：
A4 节（stock 无 resume、workdown 三内部细节依赖）、行为契约 6 条（resume→同 id 回落→
fresh 回落/未置一次性/flush 后退/退出码按 turn 结局）与实现及八面场景逐条吻合；
取舍表行为主张全部成立（仅行号陈旧，见 doc_sediment ③，不构成主张推翻）。
`docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md` 仅做关键词
扫描未逐节读，无主张级核对结论，不列入。

## 七、遗留与风险（交下一棒/升级门槛）

1. **验收④ live 双版对照未跑**（本泳道禁跑 live）：升级门槛机械段执行；执行前必须先由
   t260922-03/判据票收口探针 cold-start 缺口，否则两侧皆红不可判定——这是升级门槛的
   **前置拦停条件**，不是可选项。
2. TS loader 对 sibling URL 导入的完整 live 裁决归升级门槛（在案旁证=本泳道 implement 段
   真实 dsh 会话「已恢复会话」行=装载成功；wiring 场景守的是物化/拷贝副本面）。
   兜底判据已写死 node.ts 头注（仅 `ERR_MODULE_NOT_FOUND` 指向 summarize.js 才内联回退）。
3. 0.1.5 对既有 0.1.1 旧档的代数迁移可续性未实证（0.1.5 源码确有版本排序的迁移选择
   机制 `resolveGenerationInDirectory`，本票实证到机制在场；live 判定归升级门槛对照）。
4. 9 条机械红全为他票/环境既有债（第三节清单），不在本票收口半径；merge 关卡按在册
   归属处置，不计入本票。

## 参考 docs 清单（读过）

- docs/README.md（目录）
- docs/design/dsh_seam需求书v1.md（A4 节 / resume 行为契约 / 对标取舍表 / 验收样例 / Nongoal，逐节读）
- 非 docs 侧声明路径：integration/README.md（第 10 组）、integration/run_scenarios.py（登记行）、notes/debts/known-issues.md（KI-059/051/046）、.sandbar/plan_t260922-06_resume_addressing.md（方案+review 补记）
