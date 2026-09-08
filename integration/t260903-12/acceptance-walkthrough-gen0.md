# t260903-12 acceptance_walkthrough 验收报告（integration，gen0）

工单：sandbar M2-D 前半——workbench 构建链复活（依赖装齐 + tsdown 重建 bundle + 全量 JS 绿 + VERSION 0.2.0-rc）。
走查方式：不预设「测试已全过」，全部关键声明由 integration 亲手独立复跑/复解析，与 developer 自报、机械集成测试（8/8）三源交叉。

## 结论

**status=ok（可进入人审合并），附两条必须知悉的保留项**：

1. 「全量 JS UT+smoke 修到全绿」**未按字面达成**（UT 28/31、smoke 23/25），但 5 条红经独立归因
   全部为 **suyou→sandbar 搬迁前置债**：与本票改动零交集（五测试文件本票零改动、零消费
   lib bundle、main 侧同证必红）、修复面全在写集外、强修必踩本票自带红线（改测试语义凑绿 /
   造 suyou 产品数据）。详见「5 条红归因」。此为**方案窄化未显式申报**（create_plan gen1 步骤 3
   承诺 `fail=0` 无保留条款），非 developer 实现问题——developer 如实上报未凑绿，处置正确。
2. 『并行期 UI 呈现』隔离台实拍证据缺失（capture-lane 环境债），本票零渲染改动故检查项按
   不适用处理，间接证据链在案。详见「UI 检查项」。

## 逐场景结论（走查清单）

| # | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 依赖装齐（只装不升级，锁 tsdown ^0.22.2） | **过** | `node_modules/.pnpm/tsdown@0.22.14` 在场（∈^0.22.2）；pnpm-lock.yaml 不在本票 diff（22 文件清单核对，零 diff 实证） |
| 2 | tsdown 重建 bundle | **过** | lib/client.{cjs,js} 各 1835177B、产物集恰两文件；closure-factory 外衣首行 `window.__ModuleLoader__.load({id:"suyou-workbench"...` 与尾行 `return module.exports; } });` 完整（实读首尾 400/200 字节） |
| 3 | bundle 新鲜度 | **过** | mtime lib=1788421761 > src_max=1788420025；i03_build_contract（「忘记重建」护栏，重建前 RED by design）本轮 PASS |
| 4 | bundle 新鲜度护栏配置自证 | **过** | merge-checks.yaml 在场；integration 独立按 3.5 节形状重解析=恰 1 对、无坏行、src/out 前缀皆仓内真实目录（isdir 实证）；sc_merge_checks_pairs 6/6 |
| 5 | VERSION 0.2.0-rc + version.py 联动 | **过** | VERSION=`'0.2.0-rc\n'` 恰一行；_SEMVER_RE 含 prerelease 段（核心段与 rc.N 同禁前导零）；parse_semver 取 groups()[:3]（prerelease 不进三元组，下游零感知）；sc_ver_semver_rc 独立复跑 21/21（正例 5+负例 12+读回 4） |
| 6 | 版本展示单源化（用户可感知） | **过** | doctor/upgrade 两场景独立复跑 PASS（断言锚=动态读仓根 VERSION，dsh 已验证点 0.1.1-rc.2 字面量保留） |
| 7 | 全量 JS UT | **保留**（28/31） | 亲手复跑 ran=31 pass=28 fail=3；3 红归因见下，全部前置债非本票回归 |
| 8 | smoke 家族 | **保留**（23/25） | 亲手逐个跑 pass=23 fail=2（epics-status / stage-parts）；2 红归因见下 |
| 9 | lib 消费用例全绿（重建无损核心证据） | **过** | grep 实证直接消费 lib/client.js 恰 8 例（tests 4 + smoke 4），与本轮跑测逐一比对全 PASS：i03_build_contract、rework-banner-ui、t01_merged_diff_bounded、t03_donut_empty / approve-note、evidence-lightbox、hero、ticket-switch |
| 10 | 机械集成测试（run_scenarios.py） | **过** | 注入结果 8/8；integration 另独立全量复跑一遍（含 4 条重点场景逐条亲跑），绿 |

## 5 条红归因定位（只定位不修复，逐条亲手取证）

| 文件 | 失败环节（归因） | 前置性证据 |
| --- | --- | --- |
| tests/capture-stale-banner.mjs | 拉起隔离台 `dsh --profile suyou`（临时端口/临时 HOME，不碰 3099）子进程 exit=1→fetch 连接拒绝；suyou profile 插件族（suyou-providers 等）在 sandbar 无从物化，profile/node_modules 现仅 suyou-workbench 软链（implement 环境级补的一层） | 不消费 lib；本票零改动；main 侧 node_modules 全缺，红得更早 |
| tests/epic-status-enum.mjs | B 段普查 `notes/epics` 真目录并断言 9 张 suyou 立项单（coding-games 等）→sandbar notes/ 仅搬迁交接文档，listEpics=0→byCode['coding-games'] TypeError | `git ls-tree main notes/` 同样无 epics/→main 必红；造数=伪造 suyou 产品数据（红线） |
| smoke/epics-status.mjs | F 段同一 notes/epics 存量迁移断言（≥7 张、逐张状态/备注）→实得 0，7 断言红 | 同上；本票零改动 |
| smoke/stage-parts.mjs | B 段 route.handler→node.ts `callTool('workflow')`→`runAdminCli`→**admin.py call**；sandbar 无 server/admin.py（实证：ls 无、~/Documents/suyou/server/admin.py 有）→handler 抛错，GET 非 200 | handler 链实读 node.ts:331/529-535；五模版 yaml 在 sandbar 全在（server/workflows/），非模版缺 |
| tests/verify-lane-config.mjs | F9 断言仓根 verify.yaml 声明 app/src/+app/smoke/ 白名单——suyou 仓形状（suyou 有 app/）；sandbar 无 app/ 目录，verify.yaml 天然不含 | 断言注释自述「declares this repo's own shape」但锚死 suyou 形状，缺 per-repo 感知；verify.yaml 本票未动 |

共性根因：**suyou 血统测试假设 suyou 仓资产在场**（notes/epics 产品数据、admin.py 运行时、profile 插件族、verify.yaml 形状），sandbar 搬迁未带这些资产 → 在 sandbar 泳道内结构性必红；且 verify.yaml 自动跑点不含 JS UT/smoke（developer 自我迭代建议已提），故能存活至今。**建议按 KI 登记**（登记权在 integration 岗位，本报告即上报件）：模式=「血统测试的仓资产假设」，触发条件=任一 suyou 血统 JS 用例在 sandbar 泳道执行；什么样的改动会踩=任何让 JS UT 进自动跑点的入轨动作会立刻引爆 5 红。

## 测试资产变更审查（对照打回轮次：review_plan gen0→gen1 的 R1/R2/R3/R4）

本票 integration/ 侧 5 处变更逐处核实，**均为契约精确化，无绿灯捷径**：

1. `sc_ver_semver_rc.py`（新建）：intent=VERSION 单源 semver fail-closed 守护；正例 5+负例 12
   锚**正则行为契约**而非当前版本值，仓根读回零字面量锚（升版不触红）；异常类型断言
   （非 VersionError 也算红）封住 parse_semver 放宽时 TypeError 冒充 fail-closed 的缝。
   设计合格，无弱化。
2. `sc_merge_checks_pairs.py`（新建）：intent=bundle 护栏配置与仓实况对齐；第 4 步 isdir
   断言正堵 3.5 节「src 前缀无改动→continue 降噪」导致的路径写错静默失效（t260827-02
   假上线复燃形态）。解析器为文档化形状的最小镜像（灰盒，绑文档不绑私有代码）。合格。
3. `sc_sandbar_doctor_compat_matrix.py`：`"0.1.0" in blob` → 动态读仓根 VERSION。
   intent 不变（自报版本=单源），去掉的是**易朽字面量**；`0.1.1-rc.2` 字面量保留——它是
   ⑧-1 列举制真源（固定值语义），保留正确。精确化 ✓。
4. `sc_sandbar_upgrade_contract.py`：同上模式 ✓。
5. `run_scenarios.py`：两处描述去字面量化 + 两新场景注册，与上同步 ✓。

负向核实：workbench tests/ 与 smoke/ 在本票 diff 中零改动（grep 计数=0）——不存在「改测试凑绿」面；5 条红被如实保留红灯即是未凑绿的直接证据。

## 『并行期 UI 呈现』检查项

**适用性：不适用（本票零渲染改动）**——本票 diff 不含 src/client/ 任一文件，仅重建产物 lib/；
「并行分叉期步骤条双边同亮 + ∥ 标记 + 状态行『并行分叉中』」的渲染行为未被本票触碰
（状态行文案在 src/client/index.tsx:1251 `并行分叉中：${names.join(' ∥ ')}`，原样）。

重建无损 UI 的间接证据（在案）：lane-parallel-states F4「implement ∥ design_integration_tests
双高亮」推导语义断言 PASS；arbitrate ∥ acceptance_walkthrough 双亮断言 PASS；上述 8 个直接
消费 lib/client.js 的用例全绿（含 hero 反接管静态断言、i03 横幅锚——均为对产物内容的断言）。

**证据缺口如实记录**：隔离台实拍通道本轮不可用——capture-lane 退出码 1（legacy
~/.dsh/.credentials.yaml 凭据弃用窗 + chat 态种子门旗，只读红线禁造数）；6 张尽力视图已归档。
此为 capture 环境债（凭据迁移+种子门旗传递），非本票产品缺陷；若人审需要实拍，须先修
capture-lane 环境层再补拍。

## 遗留与风险

1. **5 条 JS 红 + installer tests 观测红（test_repo_version_is_010 硬编码 0.1.0 等 3 处）为
   真实守护缺口**，需独立票承接：JS 侧=血统测试 per-repo 感知化或 suyou 资产迁移（每条都触
   「改测试语义」红线边界，须逐条拍板，不许顺手凑绿）；installer 侧=`0.1.0-rc.1` 负例转正是
   本票语义变更的应期联动，属断言更新非造假。该测试族无自动跑点，短期不挡 merge。
2. **verify.yaml 不跑 JS UT/smoke/run_scenarios**——本票 5 条前置红存活至今的缝隙，建议
   M2-D 后半收进自动跑点（收前须先清 5 红，否则入轨即红）。
3. workbench/package.json `version` 仍 0.1.0（npm 包元数据）：与仓根 VERSION 单源是两个口径，
   未发现消费方，本票不动合理；留观。
4. capture-lane 环境债（凭据弃用窗、种子门旗、profile 插件族缺失）导致 UI 实拍证据通道不可用，
   建议独立环境票。
5. 走查与仲裁并行，本报告不预设仲裁结论；若仲裁判 tests-fault/code-fault，本轮作废重走。
