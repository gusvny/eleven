# t260924-04 票1 验收走查报告（integration，acceptance_walkthrough gen4）

结论：**仍不通过（status=failed）**——D6 修复实证生效（workflow 已能启动并推进到
外置段 j_one/running），但真舞台随即暴露缺陷 #7：外置模板 agent 段的驱动
activity 从未注册（引擎 `AGENT_STAGE_IDS` 写死），`j_one` 活动不存在 →
NotFoundError 无限重试，票永阻在第一段。登记→加载→合并→worker→建票→段启动
全链已通，差最后一段驱动活动接线。

## 做了什么（本轮回）

1. 核实 D6：worker 日志实证 passthrough 全集
   `['activities','agent_activities','base','dev_lane','sandbar_ext_…','shared','workflows','workflows_v2']`
   ——gen3 的 `KeyError: 'shared'` 消失，外置 workflow 成功启动：
   `[t26092404a] j_one/awaiting adopt v2（模版=journey-two-step，stages=['j_one','j_two']）`
   → `j_one/running 进入本段（kind=agent，第 1 次）`。
2. journey 独立复跑（可复现）→ 缺陷 #7，worker 日志逐帧取证（下）。
3. 归属定位：`agent_activities.py:1360 AGENT_STAGE_IDS` 硬编码枚举 + `:6254
   AGENT_STAGE_ACTIVITIES = [_make_stage_activity(s) for s in AGENT_STAGE_IDS]`
   在模块 import 期生成——外置模板的段 id 不在枚举内，其段驱动 activity 永不
   存在。夹具 fx_step_one/fx_step_two 能跑恰因它被写死在枚举里（t260908-01），
   外置模板没有这条引擎内后门。

## 缺陷 #7（阻断级）：外置模板 agent 段驱动 activity 未注册，票永阻

worker 日志（`$TMPDIR/t26092404-journey-12otljka/worker-t26092404a-*.log`）：

```
ApplicationError: NotFoundError: Activity function j_one for workflow
t26092404a is not registered on this worker, available activities:
acceptance_walkthrough, …, fx_step_one, fx_step_two, …（无 j_one/j_two）
→ [t26092404a] j_one/blocked agent 活动故障（已重试）
```

每 2s 重试一次直至场景 420s 超时；票终态非 closed。fail-closed 面不破（worker
存活、别的票不受扰、无静默改名），但需求②「合并进同一注册表」的可用语义仍差
最后一环：**注册表里有了模板，段驱动面没跟上**。任何外置模板的 agent 段
（role=developer/integration 等）都会撞此面。

修复方向（供 developer 参考）：类面合并后（worker 启动时）按已接受外置模板的
`STAGES` 动态补造段驱动 activity（复用 `_make_stage_activity`，仅 agent 门类段；
human/machine-qc 段走既有通用面）并并入 Worker 的 activities 注册；隔离语义照旧
——某模板段造 activity 失败＝该模板按既有三态拒收，不炸 worker。注意
`AGENT_STAGE_ACTIVITIES` 是 import 期快照，补造须发生在 Worker 构造前且不回写
模块级元组（防双装载裂变）。

## 测试资产变更审查（对照打回轮）

- developer 侧：D6 passthrough 全集（外置装载名 ∪ 引擎依赖顶层名）＋两处同款
  restrictions 构造——契约精确化，journey 行为面前三段全部转绿实证；合并期
  冲突消解与受影响面复验（73 passed）无异动。
- 走查侧/仲裁侧：本轮零资产改动。
- 自我迭代备忘（developer 已提，本岗附议）：D3-D7 五连全在「真 Worker 行为面」
  才可暴露——建议打回轮把 journey 的 A1 全链纳入 developer 段 venv 级冒烟
  （fake client 或拆 Worker 参数组装纯函数），否则此类红只能在闸上逐层剥。

## 逐场景结论

| 场景 | 结论 |
|---|---|
| ①登记即加载＋隔离拒收（离线契约面） | **过**（本轮机械结果 exit 0） |
| t260904-08 收窄守卫 | 过（上轮 35/35 实证，本轮无相关改动） |
| ②journey 真舞台 | **不过**——缺陷 #7（workflow 启动＋段推进 ok，段驱动 activity 缺席致票永阻） |
| UI/泳道图渲染 | 不适用：本票无 UI 改动 |

## 收口两问（留痕）

- **doc_sediment**：`want=true`——前两轮建议（§五补 SandboxRestrictions 实名＋
  passthrough 须含 shared/base）已被 D4/D6 落实；本轮追加一条：加载口文档 §二
  「接口形状」或 §六「实现锚点」宜补一句**「外置模板段驱动 activity 由引擎按
  STAGES 自动接线（不要求项目自写 activity 函数）」**——把缺陷 #7 的引擎侧义务
  写成契约，防需求方误以为要在项目模块里自带 activity。target=加载口文档 §二/§六。
- **doc_conflicts**：本轮实际读 docs/README.md、加载口文档 v1（implement 复验段
  引用的三篇中本岗未新读契约 v1 全文，不计）——文档「同 fixture_two_step 惯例」
  的表述与实际接线义务的差距由上条 sediment 吸收，非推翻性矛盾。

## 遗留与风险

- 缺陷 #7 修复后 journey 仍须真跑全套（A1/续跑/A3A7/分项目可见面——续跑与
  建票面至今未真正跑到过，前面轮次全被 A1 拦截）；
- 环境红（孤儿台/台竞争）与本票无关；journey 直呼脚本 ~272s 稳定可复现。
