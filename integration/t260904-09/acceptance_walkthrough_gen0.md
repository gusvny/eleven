# t260904-09 验收走查报告（acceptance_walkthrough gen0，integration）

工单：收口出仓快照——settle 时刻冻结 token+交付（squash 真身）到项目级账本，metrics 读侧优先消费。
走查立场：用户视角独立走查，不预设「测试已全部通过」；与仲裁并行，机械口径（101 跑 / 97 过 / 4 败）仅作输入。

## 结论：不通过（status=failed）

两个**代码问题**（非测试问题），任一独立构成打回：

| # | 发现 | 归因文件 | 断言源 |
|---|------|----------|--------|
| 1 | 票号路径防穿缺失：注入 `../` 的票 id，快照落 settle 目录之外（W8 红） | `server/engine/agent_activities.py`（`_freeze_settle_snapshot` 路径拼接） | 场景 W8 + 快照路径契约 `<settle>/<票>.json` |
| 2 | 测试缝读写两侧分叉：`SANDBAR_SETTLE_SNAPSHOT_DIR` 只被引擎写侧消费，TS 读侧根链无此环（R6 红） | `server/plugins/workbench/src/host/metrics.ts`（`resolveMetricsCacheDir`） | 契约增补段 1「读写两侧同一解析语义」+ 场景 R6 |

## 做了什么

1. 通读两侧实现（引擎 `agent_activities.py` 快照族函数；读侧 `metrics.ts` 快照消费/取数序/donut 四桶）与契约增补段，核对「工单条 1–7」逐条兑现度。
2. 独立实跑本票双 L3 旅程（不复用机械结果）：写旅程 15/16 断言绿、读旅程 16/17 断言绿，红的两条即下述两发现；独立复现与机械口径一致。
3. 用生产 git 真史实证归档收窄锚（验收条「存量票 05≈5658 而非 5783」）：见下「怎么验证的」。
4. 实跑 developer L1（workbench 侧）：`t260904_09_settle_snapshot.mjs` 22/22、`delivery-recovery.mjs` 50/50 绿。
5. 逐处审查 implement 段对既有测试资产与 golden 的 22 处改动意图（见「测试资产变更审查」）。
6. 命名红线、console 红线、契约文档落档核查。

## 怎么验证的（逐场景结论与证据）

### 绿面（兑现良好，列出关键项）

- **W0–W7 写路径旅程（真仓真 git squash merge）**：快照出仓 `<settle>/<票>.json` 在场、schema_version/ticket_id/squash_commit/tokens/delivery 键齐；squash_commit=merge 回执 short hash；token 只加总 assistant/message（chunk 翻倍哨兵 999 不计）、归因当时 provider/model；delivery=squash 真身 numstat（+12/−12 含删除行）、base=squash 父提交——不再依赖事后 grep ✅。
- **W4 幂等（重试态）**：同分支重入 merge 载荷逐字节稳定（settled_at 除外）、账本恰一份 ✅。**W5 不可变**：账面篡改后重收口保留旧件不回写、merge 仍 ok ✅。
- **W6 软降级**：会话目录缺失 / zstd 撕裂帧 → merge 照常 ok、delivery 照常出仓、token 不虚计（观测欠账不卡交付）✅。**W7 零变更收口**：HEAD=他票 squash 时 zero_change=true、add/del/commits=0、不吸他票账 ✅。
- **R1 快照优先级**：有快照的票交付=快照值（101+9）、token=快照值（500+120），该票无 git 提交（快照不生效即不可算，对照干净）✅。
- **R2 归档收窄 + R3 口径变更可达性**：真 git fixture 仓只认票号前缀提交（12 非 62）、reason 标归档口径；v1 宽口径存量缓存被 SOURCE_VERSION bump 治愈（宽口径不永续，05 锚同构）✅。
- **R4 donut 四桶**：有变更 / 已收口·零变更 / 未交付（在制）/ 不可算（数据缺失）互斥且 Σ=票数，零变更闭票不落「不可算」✅。**R5 畸形快照**：坏 JSON 不炸面板、留人话 reason、不当真源 ✅。
- **生产真值锚实证**（本仓真 git 史，只读）：`t260904-05` 相关提交 5 条，前缀命中**唯一** 455320d=**5658** 行；他账 4 条=33（立项收尾）+1（KI-044 登记）+83（讨论档）+8（编号修正）=**125** 行；宽口径合计=**5783**。与工单派发规格数字逐字吻合——归档收窄语义（message 首行票号前缀）在真实生产史上成立 ✅。
- **红线核查**：新命名零 suyou（`SANDBAR_SETTLE_SNAPSHOT_DIR` 中性）；`SANDBAR_USAGE_LEDGER_DIR` 零新增引用；console（3099）零触碰（diff 无相关文件）；契约增补段 6 条已落 `docs/design/metrics-api契约v1.md`（schema 冻结不破）✅。

### 发现 1：票号路径防穿缺失（W8，代码问题）

- **复现**：`_squash_merge(ticket_id="../escape_t260904-09", project_key="demo")` → 快照落盘 `<settle根>/demo/data/escape_t260904-09.json`——在 settle 目录（`<settle根>/demo/data/settle/`）**之外**。机械跑与本走查跑独立复现两次，路径一致。
- **根因**：`agent_activities.py` `_freeze_settle_snapshot` 以 `path = d / ("%s.json" % ticket_id)` 原样拼接票号；防穿白名单只盖 project_key（`_settle_snapshot_dir` 的 PROJECT_KEY_RE），ticket_id 全链路（merge activity → `_squash_merge` → 快照）无任何格式校验。
- **影响面（按危害排序）**：① `ticket_id="../settle/<他票>"` 可在 settle 目录内**新建**他票名下的伪造快照——读侧会 `delivery_frozen=true` 采信（已存在文件有 keep-old 不可变护栏挡覆写，挡不住新建）；② 多级 `../` 可越出项目数据目录写任意 `.json` 路径。定性：**防呆缺失**而非现实可达漏洞（生产票号由引擎派发自产、格式规整），但「快照只落 settle 目录内」是路径契约的一部分，且场景登记明文「arbitrate/merge 期必须绿」。
- **修法方向（供 developer 参考，不代改）**：票号入快照路径前过与 PROJECT_KEY_RE 同族的白名单（如 `^t\d{6}-\d+$` 或拒绝含 `/`、`\`、`..`、`.`/`..` 全名），拒绝时按软降级语义跳过快照并留 note（不阻塞 merge），与既有失败语义一致。

### 发现 2：测试缝读写两侧分叉（R6，代码问题）

- **复现**：读旅程 R1（快照放 `SANDBAR_METRICS_DIR` 根链，stub harness 注入）→ 读侧消费=绿；R6（同一形状快照放 `SANDBAR_SETTLE_SNAPSHOT_DIR` 根链）→ `top=undefined`，快照对读侧不可见=红。两断言唯一差异是根链 env。
- **根因**：`metrics.ts` `resolveMetricsCacheDir` 根链 = `SANDBAR_METRICS_DIR ?? SANDBAR_PROJECTS_DIR ?? ~/.sandbar/projects`，**缺 `SANDBAR_SETTLE_SNAPSHOT_DIR` 环**；引擎写侧 `_settle_snapshot_dir` 根链第一环恰是它。契约增补段 1 成文「测试缝 env SANDBAR_SETTLE_SNAPSHOT_DIR 替换项目根整体，与 SANDBAR_METRICS_DIR ?? SANDBAR_PROJECTS_DIR ?? ~/.sandbar/projects 同链，**读写两侧同一解析语义**」——实现未兑现成文语义；`metrics.ts` 内注释「与缓存同一条根链（引擎 _settle_snapshot_dir 两侧同序互指）」与事实不符（注释精确性问题，一并修）。
- **影响面**：缝生效环境（测试/隔离台/任何按缝部署）里引擎把快照写进读侧永不读的目录——**静默 split-brain**，面板无提示回落归档口径，数字与账本不一致且用户无感知。全 env 未设的生产现状两侧同落 `~/.sandbar/projects`，暂无用户可见错误——但工单核心承诺「读侧优先消费」恰以该缝为测试面，缝失效=本票验收面缺角。
- **修法方向（供 developer 参考，不代改）**：读侧 `resolveMetricsCacheDir` 根链补第一环（`process.env.SANDBAR_SETTLE_SNAPSHOT_DIR ?? SANDBAR_METRICS_DIR ?? …`），两侧同序；developer L1 补一条读侧消费该 env 的断言（现 L1 只测 SANDBAR_METRICS_DIR 链，缝漏网）。

### 测试资产变更审查（对照 implement 段改动，逐处核实意图）

**结论：全部为契约升级的正当伴随改动，无绿灯捷径。**

- `delivery-recovery.mjs`（49 行）：stub 格式随实现换代（`--format=%H` → `--format=%H %s`，收窄需要 subject）；①b/④ 反向**加严**——新加他账引用提交并断言被剔（commits 2→1）、④由「双算面记录为已知行为」改为「断言收窄正面关闭双算」（t09-mB 仅他账引用→null+reason 点名）；⑧a reason 文案「多提交」→「归档口径」随契约增补段 3 的成文取代。断言强度只增不减。
- `donut-render-dispatch.mjs`（5 行）：2 桶断言 → 4 桶+逐字类目名断言，加严。
- `terminate-universe.mjs`（4 行）：桶级断言从 data[0]/data[1] 两桶 → 四桶逐桶值断言（含零断言），加严。
- `golden_serial×12`：source_version v1→v2 + donut 四桶类目/数据（[0,5]→[0,0,1,4]），为契约增补段 4/5 的声明性后果（响应形状冻结测试的 golden 随成文契约换代）；其余数字逐字节未动。
- integration 侧（本角色资产）：implement 段对双旅程场景文件**零改动**（git stat 仅 run_scenarios.py 登记 + 两文件新增，均 design 段产物），无测试被为实现让路。

### UI 呈现检查项：不适用

本票改动全部落在 host 数据层（`metrics.ts`）、引擎层（`agent_activities.py`）、测试与契约文档——无 UI 组件/泳道图渲染代码改动。donut 四桶是 charts payload 数据面变化，其像素渲染由既有基线场景 `metrics-donut-dom`（机械口径 exit 0）覆盖不回归，本票未触碰渲染路径。

## 遗留与风险

1. **两发现的修复责任**：归 developer（打回）；仲裁若另判 tests-fault 与本报告冲突处，以本报告的实证复现路径为准可当场重放。
2. **机械口径 4 败的剩余 2 败**：注入上下文列表截断，只能确认 2 败归属本票双旅程（均已独立复现）；另 2 败明细未见，不排除与本票无关的既有红，请以 run_integration_tests 台账全量清单核对归属。
3. **`SANDBAR_METRICS_DIR` 引用面扩大（迁移票欠账注记，非本票违规）**：该 env 是 TS 侧既有根链（HEAD~1 已在 metrics.ts），本票 Python 侧新增引用是为写读同根一致的兼容读；发现 2 修复后它成为两侧链中段一环，未来专门迁移票退役该 env 时须两侧同批摘除（建议登记 KI 或入迁移票清单）。
4. **engine L1 pytest 本环境不可独立复跑**（系统 python3 无 pytest 模块，环境限制非代码问题）：其覆盖面（目录 env 链/聚合口径/幂等 keep-old/软降级/接线兼容）已由本走查 L3 旅程 W1–W7 断言独立覆盖；L1 独立绿以 developer 自报与后续可跑环境为准。
5. **真实闭单票的生产端到端**：快照语义自本票部署后首个 settle 才开始产生存量，「真实闭单票面板=快照值」的生产实证待部署后首票自然达成（当前由 W1 写+R1 读的跨组件链路覆盖）；重开票增量交付不可见为契约成文已知边界（快照 reason 的 squash_commit 可发现）。

## 参考 docs（本段读过）

- `docs/README.md`（目录对表，判定相关面）
- `docs/design/metrics-api契约v1.md`（增补段全文+周边块；走查基准）
- `notes/discussions/260904-metrics-data-audit.md`（KI-017/040 背景，只读）
- 仓库根 `CLAUDE.md`（硬规则⑤命名红线、硬规则①console 红线；只读）
