# t260924-04 票1 验收走查报告（integration，acceptance_walkthrough gen2）

结论：**仍不通过（status=failed）**——D3 双层防线方向正确且加载口侧已实证生效
（场景① 33/33 绿、UT 20 passed、建票明细面生产时序实证正确），但真舞台暴露两处
**一行级代码失误**，均在「最后一公里」把功能打回不可用/守卫破面：

- **缺陷 #4（阻断级）**：`worker.py` 引用不存在的符号
  `WorkflowSandboxRestrictions`——本仓 temporalio 1.18.2 实名
  `SandboxRestrictions`。外置模板在场时 worker 启动即
  `ImportError`（worker 日志实证），整个工人进程崩——比缺陷 #3 换了条路同样
  「坏一个模板炸全机」。修一行即可（对照 venv API 实证
  `SandboxRestrictions.default.with_passthrough_modules(...)` 存在且可用）。
- **缺陷 #5（守卫破面，1 字符）**：`client.py` 未知模板文案收括号由全角 `）`
  改成半角 `)`（对照 c55bd82 原句 `（可用：%s）`）——t260904-08 收窄守卫 A 段
  4 条断言判 `seg == "dev-lane）"` 全红。文案形状属既有锁面，恢复原宽即可。

## 做了什么（本轮回）

1. 核实 D3 修复体：加载口 `_sandbox_validate`（worker 同款 restrictions＋临时
   event loop，temporalio 缺席跳过）与 `worker.py` passthrough 注入双层结构成立；
   场景① 全量复跑 **33/33 绿**（含 v2 类面＝预校验真跑过的路径：好模板过预校验
   进四表）；UT `test_t260924_04 + test_ticket_pause` **20 passed**（含 D3 隔离
   回归、D1 回归保持）。
2. 建票明细面生产时序独立实证（env 先于进程、一次性 CLI）：
   `create workflow=no-such-tpl`（项目含撞名模块）→ 报错附
   「项目模板拒收明细：[pj/mods/collide.py] 撞名 id：…占用方=dev-lane（内置模板）；
   来件方=…」——需求④建票 fail-closed 且可见原因成立。
3. journey 真舞台跑（272s）：worker 日志抓到缺陷 #4（`worker.py:334 ImportError`）。
4. 测试资产修正（写集内，非弱化）：`t260904-08` F 段探针把
   `SANDBAR_PROJECTS_DIR` 设定移到 `load_ticket_tool()` **之前**（shared 模块级
   glue 在装载时现读注册根，env 后设＝拒收清单恒空＝结构性假红）；修后 F 段
   4/4 绿。同轮核对该场景夹具与断言已自洽（rejpatch.py 在场、patch 撞
   dev-lane-review-gate）。

## 测试资产变更审查（对照打回轮）

- developer 侧：D3 双层修复＋D3 回归用例＋跨用例污染夹具（autouse 快照恢复）——
  均为契约精确化，无绿灯捷径；曾连带红的 test_ticket_pause 复绿实证。
- 仲裁侧：F 段夹具补 rejpatch.py（断言与夹具对齐）。
- 走查侧（本轮）：F 段 env 时序修正一处（理由如上，属「探针取数先于被测态建立」
  的次序契约，修正后断言面更严：明细锚逐字在场）。

## 逐场景结论

| 场景 | 结论 |
|---|---|
| ①登记即加载＋隔离拒收（离线契约面） | **过**（33/33＋独立探针/UT 复核） |
| ②journey 真舞台 | **不过**——缺陷 #4，worker 启动 ImportError |
| t260904-08 收窄守卫 | C/E/F 段过（F 经资产修正）；A 段 4 红＝缺陷 #5（client.py 括号宽度回归） |
| UI/泳道图渲染 | 不适用：本票无 UI 改动 |

## 收口两问（留痕）

- **doc_sediment**：`want=true`——上轮建议仍成立且已被 implement 落实一半
  （加载口 v1 §五新增「sandbox 兼容双层防线」段）；剩余建议：同段补一句
  **「passthrough 符号名以 `temporalio.worker.workflow_sandbox.SandboxRestrictions`
  为准（1.18.2 无 WorkflowSandboxRestrictions 别名）」**，把缺陷 #4 的坑写进
  契约，防下一棒/外置接入者复踩。target=docs/design/项目外置工作流模板加载口v1.md §五。
- **doc_conflicts**：本轮实际读 docs/README.md、加载口文档 v1（§五新版）——
  「sandbox 兼容双层防线」主张与代码一致；无新的被推翻主张。前两轮 pending-doc-sync
  条目（合并注册 claim）已闭环。

## 遗留与风险

- 缺陷 #4/#5 均一行修；修复后 journey 必须真跑补证（A1 全链/续跑/A3A7 建票面
  全套）——缺陷 #4 修掉后 passthrough 路径才第一次真正被执行到，预校验绿≠
  worker 侧绿；
- 本轮 `run_scenarios.py` 单场景入参再次触发全量跑（runner 参数语义），journey
  独立耗时 ~272s，后续移交命令建议直呼场景脚本：
  `python3 -B integration/t260924-04/sc_project_template_ticket_journey.py`；
- 环境红（台竞争）与本票无关，journey 两 FAIL 均代码可复现非环境噪声。
