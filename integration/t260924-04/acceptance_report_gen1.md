# t260924-04 票1 验收走查报告（integration，acceptance_walkthrough gen1）

结论：**仍不通过（status=failed）**——打回 D1/D2 修复有效（场景① 33/33 全绿、四表
同源实证），但真舞台全链暴露新缺陷 #3：外置模板类一进 worker，temporalio sandbox
按模块名重执行定义模块时找不到 `sandbar_ext_*` 别名模块，**worker 进程整体启动
失败**——好模板也炸、拖垮同项目其他模板与别项目，直接违反需求④「坏模板不注册、
不拖垮同项目其他模板与别项目」的隔离语义（此处连好模板都拖垮）。

## 做了什么（本轮回）

1. 核实打回修复：`shared.py project_template_scan` 先占方改用 `_PT_BUILTIN_KEYS`
   快照过滤表（D1 根因修复正确）；新增回归用例
   `test_d1_regression_names_glue_no_self_collision`（生产时序子进程，三断言含
   「畸形标签不被自撞掩盖」=D2 精度要求）。UT 12 passed（含新回归）。
2. 独立探针复验（引擎 venv、生产 env-先于-import 时序、四个隔离注册表）：
   - 好模板：names/display/TEMPLATE_CLASSES/ALL_WORKFLOWS_V2 四表同现
     `projx-good`，零拒收（缺陷 #1 已愈）；
   - 缺 STAGES：拒收 `{check: 畸形, detail: 缺 STAGES（段定义缺失，无法驱动）}`
     ——点名精确（缺陷 #2 已愈）；
   - 撞名 dev-lane：`撞名 id，占用方=dev-lane（内置模板）；来件方=projc/…`，
     内置注册不被覆盖（A3a 语义保持）；
   - import 即炸模块：fail-closed 不注册（「模板类不可辨」/「加载失败」按形状归层）。
3. 场景①全量复跑：**33/33 全绿**（上轮 4 项红确系测试资产漂移，仲裁已修正探针，
   本轮复核修正后的断言面真实有效，见「测试资产变更审查」）。
4. 场景②（journey）真舞台两轮实证（全量跑 2×438s，worker 日志逐行读）→ 缺陷 #3。
5. 测试资产同步（写集内）：journey 场景已入
   `integration/batch_stage_exceptions.json`（pool=main、pattern `t260924-04-*`、
   自起舞台理由与 grep 证据）——守卫 `sc_batch_manifest_contract` 6/6 全绿
   （修前报「pool=main 未声明例外=C1 形态」）。

## 缺陷 #3（阻断级）：外置模板类使 worker 整体启动失败，隔离语义破面

机理：加载器用 `importlib.util.spec_from_file_location("sandbar_ext_<key>_<mod>", …)`
把外置模块装进宿主进程并记入 sys.modules；temporalio 的 workflow sandbox 在
`Worker` 构造期**按 `@workflow.defn` 类的 `__module__` 名重新 import 定义模块**
（sandbox 受限 importer 不复用宿主 sys.modules），找不到 `sandbar_ext_*` →

```
ModuleNotFoundError: No module named 'sandbar_ext_jn_good_journey_two_step'
→ RuntimeError: Failed validating workflow JourneyTwoStepWorkflow
（worker.py main → Worker(__init__) 即炸，进程退出）
```

证据：journey 运行 worker 日志
`$TMPDIR/t26092404-journey-dp9unfkk/worker-t26092404a-*.log`（两轮独立复现，
`A1 worker 已拉起 FAIL` ＋「超时未等到 A1 closed」同因）。深检（venv importlib）
在沙箱外，故场景①全绿无法暴露此面——只有真 Worker 校验期才炸。

后果：worker 起不来 → 该机所有模板（含内置 dev-lane）、所有项目全部不可跑；
需求④「坏模板不拖垮同行」与 KI-113「在途票由老类跑完」同时破面（一个坏登记=
全机停摆，比「凿门」前更脆）。

修复方向（供 developer 参考）：① 让 sandbox 能重执行外置模块——把外置模块目录
挂进 worker 的 workflow sandbox passthrough（temporalio
`SandboxRunner` 的 passthrough_modules / restrictions 配置），或改以模块真名＋
sys.path 装载使受限 importer 可寻址；② 兜底隔离——Worker 构造前逐外置类在沙箱
内做实例化自检，失败者按既有三态拒收撤下（「坏模板不注册」在 worker 侧闭环），
绝不许一个模板炸掉整个 Worker。

## 测试资产变更审查（对照打回轮）

- developer 侧：仅新增回归用例＋selfcheck_pause 过期断言保鲜（对齐 t260915-12
  真源），无绿灯捷径；D1 修复体小而准，独立探针复核通过。
- 仲裁侧（上轮→本轮间）：场景①探针三处取数修正（读 `shared.PROJECT_TEMPLATE_
  REJECTIONS`、PROBE_FULL 先 import workflows_v2 再快照两表、broken 夹具补
  TEMPLATE_ID＋defn 类形以抵达真「加载失败」深检路径）——逐处核实为**契约精确化**
  而非弱化：修正后 33 条断言全部真实断言到公开真源，L0 红绿自证仍在。
- 本轮走查侧：batch_stage_exceptions.json 增 journey 条目（守卫契约要求的显式
  例外通道，非豁免断言）；修后守卫 6/6 绿。

## 逐场景结论

| 场景 | 结论 |
|---|---|
| ①登记即加载＋隔离拒收（离线契约面） | **过**（33/33＋独立探针四态复核） |
| ②A1 全链/续跑（真舞台） | **不过**——缺陷 #3，worker 起不来，全链不可达 |
| ②A3/A7 建票拒收面（stdlib 探针部分） | 过：坏模块拒收面可观测、点名 RuntimeError＋文件 |
| CLI ticket.py create 面 | fail-closed 成立；但外置**好**模板经该口报「模板不存在 …yaml」而非受理——快照属项目仓（gen_workflows_doc 已排除）与 CLI create 的 yaml 校验是既有缝，本票需求未定义该口须受理外置模板，记遗留观察不判红 |
| UI/泳道图渲染 | 不适用：本票无 UI 改动 |

## 收口两问（留痕）

- **doc_sediment**：`want=true` 建议——target=`docs/design/项目外置工作流模板加载口v1.md`
  §五「clean-module 约束」段，补一行事实：**外置模板模块除模块自身约束外，还须
  能被 temporalio workflow sandbox 按其 `__module__` 名重执行；加载口文档 §三
  拒收表宜增「沙箱重执行失败」一态**（本票缺陷 #3 的教训，对下一棒/nusuyou 接入
  者是必知契约）。reason=本票两轮验收实证该面在离线深检之外、仅真 Worker 校验期
  可暴露，属「不写必再踩」的坑。
- **doc_conflicts**：实际读过 docs/README.md 与加载口文档 v1（本轮）——加载口
  文档 §一.1「与内置合并进同一注册表」在类面已成立（探针实证），无被推翻主张；
  上轮登记的 pending-doc-sync 矛盾条目（合并注册 claim vs 自撞名 actual）随 D1
  修复**已消解**，可转正闭环。

## 遗留与风险

- 缺陷 #3 打回后，场景②是真舞台唯一可暴露面，修复后必须真跑补证（A1 全链＋续跑
  ＋A3/A7 建票面全套）；
- t260904-08 收窄守卫 F 段本轮未跑（闸拦面，docker/台竞争），交机械闸;
- 本轮 `run_scenarios.py` 两次触发全量跑（374 场景）非本走查意图，属 runner 参数
  语义（单场景入参仍全跑），环境红 53 条为台竞争所致与本票无关， journey 两次
  FAIL 同因可复现、非环境噪声。
