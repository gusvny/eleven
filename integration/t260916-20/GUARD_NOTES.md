# 嵌套仓守卫说明（t260916-20，票内守卫文档）

> 定位：本票改动面（server/engine/ + integration/）内的守卫语义速查。引擎机制主档
> （docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md）的
> 「泳道内禁建成员仓」守卫语义段**不在本票写集内**，留宿主授权另票/扩权落档（gen1
> review R1 结论）；本文是其票内暂存位。

## 事故与根因（一句话版）

nusuyou t260916-08：票在泳道内从零 `git init` 成员仓 `content/`（600 件两次提交），
父仓记成 gitlink(160000) 后三连缺口——写集误诊「越界写」、squash 无处可搬、拆道
`worktree remove --force` 连带销毁子仓对象库——全程无告警，不可恢复。根因=引擎多仓
机制只服务项目根下已存在的成员仓，「泳道内从零建仓」无对应机制。

## 本票落地的四道闸（全部 fail-closed，判定同源不造第二真源）

| # | 闸 | 站点 | 触发条件 | 行为 |
|---|---|---|---|---|
| 1 | settle 早期闸 (a) | `_settle_worktree_lane` add -A 前；`settle_conflict_resolution` add -A 前 | 判脏清单含 untracked 目录折叠形态（尾 `/`）且目录内存在 `.git`（目录或文件）——0 提交嵌套仓防被 `add -A` 整目录吞成普通文件错形入库 | 拒绝代落盘；note 内嵌 `path_gate_reason=gitlink_nested_repo`（is_gate_refusal 据此改判 failed → blocked）；结构化 refusal（reason_code/files/next_action/evidence）；**现场保留**（不 commit、不 reset、不删除）；重试同拒（幂等红灯） |
| 2 | settle 早期闸 (b) | 同两站点，add -A 后 commit 前 | `git diff --cached --raw`（quotepath off）出现模式 160000——带提交子仓 gitlink 形态 | 同上 |
| 3 | 合并双红灯 (D2) | `merge_check`（新检查项 `no_gitlink`，插在 verify_lane 项之前=checks[:-1] 内）+ `_squash_merge` 步骤 0.6（`git merge --squash` 前，只读判 `--raw base...branch`） | 泳道分支差集含 160000 | merge_check：红灯点名、`conflict=False`（blocked 交人工，绝不进自动消解回路，KI-047 位置契约）；squash：`failed(reason=gitlink_present)`，主树未动、泳道不拆（取舍 b）；判定只读、Temporal 重试安全（取舍 d） |
| 4 | 拆除守卫 (C) | `teardown_lane`（check-ref-format 校验窗后、任何破坏性命令前）+ `_squash_merge` 内联清理（defer_teardown=False 老票唯一拆道通道；仅容器趟） | 泳道树内未注册嵌套仓（`unregistered_nested_repos` BFS：含 `.git` 目录=「repo」对象库在泳道内拆除不可恢复；`.git` 文件=「worktree」形态；在册成员树/协调目录/符号链接跳过） | teardown：`failed` 点名清单，一物不拆；内联：落账已完成但停拆、泳道保留=对象库可抢救（对象库不可恢复性 > 收口回执整洁；重复 merge 幂等安全补账）。守卫自身 IO 故障 → 同样 failed 点名「守卫自身故障」，绝不静默放拆；容器已不在=空清单放行（幂等重跑维持） |

判定纯函数（agent_activities.py）：`staged_gitlinks`（--raw 解析 160000，畸形行丢弃
不猜）、`gitlink_risk_from_dirty`（判脏清单 × .git 探测）、
`unregistered_nested_repos`（BFS 扫描）。人话文案单点：`_gitlink_refusal_note`。

## 出路（人话，写进每道闸的拒绝文案）

**成员仓必须在项目根下诞生**：把嵌套仓搬到项目根（复制保留对象库）→ 按普通多仓票
登记 `meta.repo_worktrees` → 仓内改造走正常票。**勿摘 gitlink 绕行**——事故正是
「摘掉 gitlink 让 merge_check 转绿」之后静默丢失的。真正支持「泳道内建仓」（方案 E：
复制到项目根+登记 meta 的引擎自动化）属大设计，留宿主定稿。

## 验收对照（工单 ①-⑤）

- ① settle 早期闸（两站点）fail-closed 人话可断言——建票时刻无判据（写集新目录与
  「打算建仓」不可区分，gen0/gen1 已论证），落点后移到开工后第一次落盘；
- ② 真值表 UT：`test_t26091620_write_set_gitlink_truth.py`（43 用例）；
- ③ 拆道 blocked 点名不销毁：UT + 场景 TD 子用例；
- ④ merge_check gitlink 红灯点名：UT + 场景 MD 子用例（真 merge_check 全调用）；
- ⑤ 既有 multirepo 全链场景零回归：server/engine/tests 全量 1266 passed（260916 实测）
  + t260913-05 / t260910-03 场景复跑。

## 已知残缺口（本票写集外，交宿主）

1. `server/tools/verify_lane.py` `_in_write_set` 的 `==` 子用例未剥条目尾斜杠——gitlink
   路径 × 带尾斜杠写集条目在该处判假，即事故「越界写: content」误诊文案真源。闸 3
   的权威红灯位次在其之前，误诊文案已降级为并存噪声；一行归一 + UT 建议另票/扩权。
2. KI 候选（按纪律由 integration 岗位登记）：FM-1 冲突消解 settle 吞 0 提交嵌套仓
   （本票步骤 2 已修引擎侧）；FM-2 verify_lane == 子用例误诊（写集外待宿主）。
3. 引擎机制主档守卫语义段：待宿主授权另票/扩权落档。
