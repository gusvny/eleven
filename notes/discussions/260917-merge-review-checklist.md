# 合并审查清单（integration 看门人用）—— 260917 初稿

> 起草人：integration 岗位（sandbar 项目会话）
> 起因：260917 审 t260917-01 时漏掉「patched 门」检查，它落 main 后导致在飞票
> t260916-19 / -21 爆 `NondeterminismError`（各 360+ 条，无限重试），紧急票 t260917-04 收尾。
> 状态：草稿（待宿主定稿）；本清单是**机械检查之外的补充**——merge_check 全绿 ≠ 可以签。

## 一、先问三句（任何票都要过）

1. **它改的东西，是它该改的吗？**（写集 vs 实际 diff：越界文件一律打回）
2. **它改的期望值/守卫，该由它改吗？**（共享守卫与期望值**只许 main 侧改**）
3. **它有没有改闸本身来让自己变绿？**（改 `lint_tests.py` / `path_gates.py` / verify 配置等
   自证类文件 = 高危，必须逐行看理由）

## 二、引擎类票（改动落在 server/engine/）额外必查

| # | 检查项 | 为什么 | 查法 |
|---|---|---|---|
| E1 | **workflow 代码变更是否过 `patched()` 门** | Temporal 确定性：改 workflow 代码不加门 → **在飞 workflow 重放必崩**（`NondeterminismError`），且不可逆地打断所有在跑的票 | `git diff main -- server/engine/dev_lane.py server/engine/shared.py \| grep -nE "patched\|_enter\|@workflow"`，对照新增分支逐个确认有门 |
| E2 | 新增/修改 activity 是否影响历史重放 | 同上（活动签名/参数形状变更也破坏确定性） | 看 `execute_activity` 调用点的签名与参数 |
| E3 | 是否动 `shared.py` 的公共常量/白名单 | 影响面覆盖所有项目与所有票 | 看 diff 的影响点 |
| E4 | 引擎类改动是否有 UT + 场景双覆盖 | 引擎行为零覆盖是历史空白（t260904 起反复） | 看 `server/engine/tests/` 与 `integration/<票号>/` |

**E1 是踩过的坑**：t260917-01 在 `dev_lane.py` 仲裁路径加分支未加门 → 落 main 后
-19/-21 重放崩。**引擎票签字前，E1 必查。**

## 三、测试/集成类票额外必查

| # | 检查项 | 为什么 |
|---|---|---|
| T1 | 断言是否落**终态**（不落中间态） | `docs/testing-guide.md`：中间态断言是抖动之源 |
| T2 | 失败分类是否正确（真败 vs 环境红） | 环境红冒充真败 → 把 agent 带去改共享资产（260917 实证） |
| T3 | 是否自开豁免（`DEREGISTERED` 等白名单加自己的文件） | 票内自开豁免 = 在闸上开洞；豁免应由 main 侧统一维护 |
| T4 | 共享守卫锚随实现改名更新时，是否保留契约语义 | KI-051：锚字面量×实现改名脱钩 → 永红 |
| T5 | 场景是否登记、是否进闸（或理由充分的不进闸） | 孤儿场景检查（L5） |

## 四、放行前最后一遍（签字的动作面）

1. **泳道是否跟上 main**（`git merge-base --is-ancestor main HEAD`）：落后会让 agent 去修 main
   已修的东西 → 越界 → 闸死结（260917 实证 -20/-21/-29，解法=合 main 进泳道）；
2. **工作区是否干净**（无未提交改动、无越界文件残留）；
3. **merge_check 结论逐条读**（不只看「绿」）；
4. **签字备注写授权出处**（谁、何时、原话），代签必须可查证。

## 五、已知会导致「闸死结」的三类形态（见到即按方处理）

| 形态 | 症状 | 处理 |
|---|---|---|
| 泳道落后 main | agent 改共享资产被闸拒 → 每轮复判同红 | **合 main 进泳道**（治本） |
| 共享期望值过期 | 实现改了 7→8 处，守卫断言仍写 7 | main 侧统一改（不得泳道内改） |
| 环境红冒充真败 | 隔离台/venv/桩签名过期 → 逐条 `:败` | 归环境面，修供给或机械分类 |

## 六、本次新增的跟踪项（待开票）

- **E1 补充（260918 实证）：t260917-04 的回放闸锁登记表是「双向精确相等」且键里嵌了调用点文本**——
  `test_t260917_04_replay_gate_lock.py::test_c9_real_workflow_files_clean_or_registered` 拿
  `BRANCH_REGISTRY` 与源码扫描结果做**集合双向比对**（新增未登记=红，登记而分支消失=stale=红），
  而键形如 `dev_lane.py#run#await self._blocked_over_limit(route.split(':', 1)[1])#0`。后果：任何票只要
  **改写这两处调用点的参数表达式**，就同时触发 unknown + stale 双红，必须连登记表一起改。
  t260917-09 即因此卡在合并检查（新增两处 `_blocked_over_limit(tests_exempt_cap_blocked_text(...))`
  命令面分支）。**处置**：属真代码红，打回实现段；两种合法修法=①补 `workflow.patched` 门（先例
  `LANE_DSH_BLOCK_PATCH_ID` / `ARBITRATE_REFUSAL_PATCH_ID`）②登记 + 写回放兼容说明。
  **建议**：把该守卫锚点从「精确参数文本」放宽到「分支形态」，否则每张动这段代码的票都要交一次
  登记表税，且极易被误读成环境红。
- 260917-01 引入的 patched 门缺陷（t260917-04 处理中）→ 收口后回看本清单 E1 是否够用；
- 260917-01 的 `DEREGISTERED` 自加豁免（已进 main）→ 是否需收紧为「仅 main 侧可加」；
- 套件三处环境红（隔离台 namespace 就绪 / run_scenarios 借 venv / 旧桩补 caller）→ 建议开票。
