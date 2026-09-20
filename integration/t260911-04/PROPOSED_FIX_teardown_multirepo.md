# 产品修复提案：多仓泳道拆道三清（teardown_lane 逐仓化）

> 状态：**提案，未应用**（本票写集红线=integration/，禁改产品；本文件供修复票/扩权裁定直接取用）。
> 来源：工单 t260911-04 全链多仓旅程守卫 `sc_t260911_04_multirepo_fullchain_landing.py` 稳定复现的 3 红
> （T3a'/T3d/T3d'），仲裁 verdict=code-fault，双跑收敛同形。
> 修复落地后以本场景 3 红转绿为回归锚（登记口径同 t260910-08「arbitrate/merge 期必须绿」）。

## 缺陷（归因到行，agent_activities.py）

1. **teardown_lane 单仓硬编码**（L3462 起）：`repo = REPO_ROOT`——`worktree remove` / `branch -D`
   都对**引擎仓**执行，项目根仓与成员仓里的 worktree 注册和 lane 分支根本够不着。
2. **拆道看不见多仓明细**：`MergeArgs` 只带单 `(worktree, branch)`；merge 已按 `_lane_scopes`
   逐仓循环落账（L3199-3220），teardown 没跟着多仓化。
3. **失败静默吞**：L3466-3470 失败仅追加 warns、`ok=True` 恒返——workflow 收口不阻断、
   残留不可见（时间线仅一条「泳道拆除告警」）。

## 修复方向（与仲裁建议一致，逐仓化 + 逐仓点名）

- **数据面**：`MergeArgs` 增可选 `scopes`（或直接 `repo_worktrees` 明细），workflow 侧把
  `meta.repo_worktrees`（teardown 时仍存活于 meta）传入 teardown_lane；空=单仓形态走旧路径
  （零回归面，在途旧票兼容约定）。
- **执行面**：teardown_lane 按 scopes 逐仓循环——对**该仓自己**执行
  `git -C <repo> worktree remove --force <tree>` + `git -C <repo> branch -D <branch>`；
  根树条目（repo=""）的仓=泳道容器父项目的根仓。参照 merge 的逐仓化（同源 `_lane_scopes`
  判定），不另造第二真源。
- **语义面**：warn 保留（残留=可回收垃圾，不阻断收口的既有取舍 d），但**逐仓点名**进回执
  `error` 字段（现状是笼统一条）；建议同时给 dev_lane 的「泳道拆除告警」时间线行附带
  逐仓明细，让残留可被巡检消费。
- **顺带**：teardown_lane 顶部 `check-ref-format` 同样按逐仓 branch 校验。

## 验收口径（修后必跑）

```
server/engine/.venv/bin/python integration/t260911-04/sc_t260911_04_multirepo_fullchain_landing.py
```

预期 SUMMARY **pass=27 fail=0 env_fail=0**（T3a' 成员仓 lane 分支已删、T3d 两仓 worktree
list 无 lane 路径、T3d' 根仓 lane 分支已删、T3d-目录 泳道目录不存在四红转绿——目录面断言由
仲裁段 gen2 补回；单仓零回归面由既有单仓对照子用例守卫）。
