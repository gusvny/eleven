# t260904-09 验收走查报告（acceptance_walkthrough gen1，integration）

工单：收口出仓快照——settle 时刻冻结 token+交付（squash 真身）到项目级账本，metrics 读侧优先消费。
本段=打回轮（gen0 两缺陷）修复后的复验走查。gen0 报告见同目录 `acceptance_walkthrough_gen0.md`。

## 结论：通过（status=ok）

gen0 两个打回缺陷均已正确修复，独立复验全绿；未发现新的代码问题与测试弱化。

| gen0 缺陷 | 修复方式（复核） | 复验证据 |
|-----------|------------------|----------|
| W8 票号路径防穿缺失 | `_freeze_settle_snapshot` 落盘前对 ticket_id 过 `PROJECT_KEY_RE`（`^[a-z0-9][a-z0-9-]{0,40}$`，**全锚定**）白名单，非法 fail-closed 跳过快照+note，不阻塞 merge | 写旅程 W8 绿（16/16）；`../escape` 与 `t09/../evil` 两形态均被 `$` 尾锚+字符集（无 `.` `/`）挡死 |
| R6 测试缝读写分叉 | `metrics.ts resolveMetricsCacheDir` 的 settleDir 根链补 `SANDBAR_SETTLE_SNAPSHOT_DIR` 头，与引擎 `_settle_snapshot_dir` 严格同序；缓存 dir 不受 SETTLE env 影响（只在 settle 链头） | 读旅程 R6 绿（17/17）；L1 新增 4 断言钉链头生效/缓存不受染/替代根有快照读出·无快照不可见 |

## 做了什么

1. 逐行复核 rework 提交（64c8867，6 文件）：W8 修复、R6 修复、契约增补段防呆语义补句、两侧 L1 新用例、worker_meta 测试环境隔离改动。
2. 三个防回归关键点核查：①白名单**尾锚定**（`re.match` 只锚开头，若正则无 `$` 则 `t09/../evil` 前缀匹配仍可穿——实测正则带 `$` 且字符集排除 `.`/`/`，穿越面关死）；②两侧根链**严格同序**（引擎 `perkey_projects_root`=SANDBAR_PROJECTS_DIR??home，与 TS 新链末两环一致；空串语义差异为 shared.py 成文的既有有意差异，非本票引入）；③`settleDirOf` 改为无参闭包后，legacy 分支与非 legacy 分支**都**走新链，无残留旧调用（旧 `settleDirOf(root)` 调用点已全部替换）。
3. 独立实跑全部回归面（不复用机械结果）：写旅程 16/16、读旅程 17/17、workbench L1 四件套（t260904_09 26/26、delivery-recovery 50/50、donut-render-dispatch 23/23、terminate-universe 9/9）全绿。
4. 测试资产变更审查（见下节）。
5. 红线复查：rework 新增行 5 处 suyou 字样全为存量 legacy env 兼容引用（`SUYOU_WORKER_META` 测试清场 ×2、`SUYOU_METRICS_DIR` 根链中段 ×2、`SUYOU_PROJECTS_YAML` 存量 reason 文案 ×1）——零新造 suyou 命名；console（3099）零触碰；契约 schema 未破（增补段内补句，无字段变更）。

## 怎么验证的（逐场景结论）

- **W0–W8 写旅程（真仓真 merge）16/16 绿**：快照出仓/schema/squash_commit=merge 回执/token 只加总 message（999 哨兵不计）/模型归因/delivery=真身 numstat+base/幂等不双算/篡改保旧件/无会话与撕裂帧软降级/零变更不吸他票账/**W8 注入票 id 不落 settle 目录之外**（本轮转绿）。
- **R0–R6 读旅程 17/17 绿**：快照优先级（交付=快照值 101+9、token=500+120）/归档收窄 12 非 62+reason 标口径/v1 宽口径存量被 bump 治愈/donut 四桶互斥 Σ=票数/坏 JSON 不炸面板留人话 reason/**R6 SETTLE env 覆盖根被读侧消费**（本轮转绿）。
- **生产真值锚（承 gen0，归档收窄代码路径本轮未动）**：真 git 史 t260904-05 前缀唯一命中 455320d=5658 行，他账 33+1+83+8=125，宽口径=5783——与派单规格逐字吻合。
- **机械口径**：101 跑 / 101 过 / 0 败（注入上下文）；其中 gen0 的 4 败归属全闭合——2 败=本票双旅程代码缺陷（本轮已修），另 2 败=仲裁按 tests-fault 修正落盘（0ab4067：t260904-02 槽位断言从 any-slot 收窄为契约本义的「本槽可复抢」、stale-cache-heal 同批健壮性修正）。
- **temporal-poc L1 pytest**：本环境无 pytest 模块不可复跑（承 gen0 环境限制）；本轮通过读码复核新增 W8 用例（断言「形状非法」note+不落盘+rglob 无 escape 残留，断言面向正确），且 L3 旅程已独立覆盖同面；developer 自报全量 121 passed。

### 测试资产变更审查

**结论：无绿灯捷径。**

- `test_t260904_09_settle_snapshot.py` +6 行：新增 W8 fail-closed 用例（note 点名形状非法+断言零文件残留），加严。
- `t260904_09_settle_snapshot.mjs` +12 行：新增 R6 回归 4 断言（链头生效/缓存目录不受染/替代根无快照不可见/有快照读出），加严且正好钉住打回面。
- `test_t260904_02_worker_meta.py` +4 行：**跨票测试改动，逐行核过**——仅在用例开头 `os.environ.pop("SUYOU_WORKER_META")` 清场（泳道内 supervisor 注入导致「前台=不写」分支误红的环境依赖缺陷）；随后 daemon/ticket 两分支断言逐字未动、ticket 分支自设该 env 且 finally 清理，**断言零放宽**。定性=环境隔离修复，正当。
- 契约增补段「失败软降级」条补防呆语义一句：与实现一致（fail-closed 跳过+note 不阻塞），文档零漂移。

### UI 呈现检查项：不适用

rework 改动全部在引擎（agent_activities.py）、host 数据层（metrics.ts）、测试与契约文档；本票无 UI 组件/泳道图渲染改动，donut 渲染由既有基线场景 metrics-donut-dom（机械 exit 0）覆盖不回归。

## 遗留与风险

1. **非阻塞小疵（hardening nit，不构成打回）**：Python `re.match` 的 `$` 在尾随换行前也匹配——ticket_id 形如 `"t260904-09\n"` 可过白名单，产出文件名带字面换行的快照（仍落 settle 目录**内**，无穿越可能，字符集无 `.`/`/`）。后续随手票改 `re.fullmatch` 更严，不急。
2. **白名单fail-closed 的形状取舍**：票 id 现被钉在 `^[a-z0-9][a-z0-9-]{0,40}$`（与 PROJECT_KEY_RE 共用）。未来若出现带下划线/大写/更长的合法票号形状，会被跳过快照（软降级+note 可发现，不卡交付）——契约增补段已成文该语义，属已知边界非缺陷。
3. **SUYOU_METRICS_DIR 迁移欠账（承 gen0 注记）**：该存量 env 现为两侧根链中段一环（TS+Python），专门迁移票退役时须两侧同批摘除。
4. **生产端到端首票**：快照语义自部署后首个真实 settle 起产生存量，「真实闭单票面板=快照值」的生产实证待自然达成（当前由 W1 写+R1 读跨组件链路覆盖）。

## 参考 docs（本段读过）

- docs/design/metrics-api契约v1.md（增补段 rework 补句复核；走查基准）
- docs/README.md（目录对表）
- 仓库根 CLAUDE.md（硬规则⑤/①红线；只读）
- notes/discussions/260904-metrics-data-audit.md（背景，承 gen0）
