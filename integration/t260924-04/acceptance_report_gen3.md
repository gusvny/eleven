# t260924-04 票1 验收走查报告（integration，acceptance_walkthrough gen3）

结论：**仍不通过（status=failed）**——D4/D5 一字级回归修复全部验证有效（收窄守卫
35/35 绿、场景① 33/33 绿、UT 72 passed、worker 已能带外置模板拉起），但真舞台
首个激活即暴露缺陷 #6：外置模板任务在 worker 激活期参数解码失败
（temporalio 沙箱受限 `sys.modules` 缺 `shared`），票永不推进——passthrough 只
放行了外置模块自身，没放行它注解引用的引擎模块。

## 做了什么（本轮回）

1. 核实 D4：`worker.py` 两处 `WorkflowSandboxRestrictions` → `SandboxRestrictions`
   ＋公开面四名注释；journey 实证 **worker 带外置模板成功拉起且存活**（gen2 的
   ImportError 消失，`A1 worker 已拉起 ok`）。
2. 核实 D5：`client.py` 收括号恢复全角；收窄守卫全段复跑 **35/35 绿**（移交命令
   实证，A 段 4 断言转绿、F 段保持）。
3. 新公开面锁 `test_d4_worker_sandbox_public_face` 核过（锁符号可导入＋
   with_passthrough_modules 可用——上轮漏锁补齐，属契约精确化）。
4. journey 独立复跑（272s，可复现）→ 缺陷 #6，逐帧取证如下。

## 缺陷 #6（阻断级）：外置模板任务激活期解码失败，票永不推进

worker 日志（`$TMPDIR/t26092404-journey-0574a527/worker-t26092404a-*.log`）：

```
WARNING ... Failed activation on workflow JourneyTwoStepWorkflow (t26092404a)
  File converter.py … get_type_hints(hint)
  File typing.py … sys.modules[base.__module__].__dict__
  File workflow_sandbox/_importer.py:431 __getitem__ → KeyError: 'shared'
RuntimeError: Failed decoding arguments
```

机理：worker 的 passthrough 集只含 `sandbar_ext_*` 装载名——外置模块因此在沙箱内
**不重执行**（直接复用外层模块）；但它的 `run(self, inp: TicketInput)` 注解解析
（激活期 payload 解码）要查沙箱受限 `sys.modules['shared']`，而 `shared` 从未在
沙箱命名空间内被导入 → KeyError → 该工作流任务反复 Failed activation，票停在
受理态到 420s 超时。内置 dev-lane 不受影响（其模块在沙箱内重执行时顺带把
`shared` 导入沙箱命名空间）——本缺陷仅打外置模板，且**任何照加载口文档 §二
示例形状（注解 `TicketInput`）写的外置模板必现**。

对照需求②「合并进同一注册表」的可用语义：注册成功＋worker 起来＋票受理，但
一激活就炸＝功能仍不可用。fail-closed 面本身没坏（任务失败不外溢、worker 不死
——隔离比 gen2 进步），但可用性未达成。

修复方向（供 developer 参考，两行级）：worker 与加载口 `_sandbox_validate` 的
passthrough 集在 `sandbar_ext_*` 之外**补 `shared`、`base`**（外置模板文档明示
仅许 import 这两个引擎模块；passthrough 后与外层同一模块对象，确定性规约不损）；
或改注解纪律（文档禁用类注解）——前者不动用户形状，优先。修后 journey 真跑
验证（离线 prepare_workflow 过≠激活期解码过，本轮即教训）。

## 测试资产变更审查（对照打回轮）

- developer 侧：D4 符号修正＋注释钉公开面、D5 一字恢复、新增公开面锁 UT——
  无弱化；「完整 Worker 构造归 journey 首验」的口径与实证一致（本轮恰是 journey
  抓到下一层）。
- 仲裁侧：journey 场景微调 6 行（读面次序，gen2 已核）。
- 走查侧：本轮零资产改动（F 段上轮已修绿）。

## 逐场景结论

| 场景 | 结论 |
|---|---|
| ①登记即加载＋隔离拒收（离线契约面） | **过**（33/33） |
| t260904-08 收窄守卫 | **过**（35/35，移交实证） |
| ②journey 真舞台 | **不过**——缺陷 #6（worker 存活但外置票激活失败，超时未到 closed） |
| UI/泳道图渲染 | 不适用：本票无 UI 改动 |

## 收口两问（留痕）

- **doc_sediment**：`want=true`——上轮建议（§五补 passthrough 符号实名）仍有效；
  本轮追加：§五「sandbox 兼容双层防线」段宜补**「passthrough 集须含外置模块
  引用的引擎模块（shared/base）——只放行外置模块自身会在激活期解码注解时
  KeyError」**。两条都是「不写必再踩」的 temporalio 沙箱契约事实。
  target=docs/design/项目外置工作流模板加载口v1.md §五。
- **doc_conflicts**：本轮实际读 docs/README.md、加载口文档 v1——文档 §二示例
  （`run(self, inp: TicketInput)` 注解形状）本身没问题，问题在引擎侧 passthrough
  不全；无既有主张被推翻。历史 pending-doc-sync 条目均已闭环。

## 遗留与风险

- 缺陷 #6 修复后 journey 仍是唯一真验证面（本轮连续三轮证明：离线面全绿≠
  真舞台绿），务必真跑；
- journey 移交命令上轮超时（>900s）是 runner 全量语义＋台竞争所致，直呼脚本
  ~272s 可完成；
- 环境红（台竞争/孤儿台告警）与本票无关。
