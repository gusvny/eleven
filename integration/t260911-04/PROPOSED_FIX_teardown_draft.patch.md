多仓泳道拆道三清——草拟补丁（DRAFT，未套用未验证）
=====================================================

> 状态：**草拟补丁，未套用到产品、未跑任何测试**（本票写集红线=integration/）。
> 供修复票或扩权裁定直接取用；套用后必须：跑 server/engine 既有 L1/selfcheck +
> 本票守卫场景（预期 SUMMARY pass=27 fail=0，见 PROPOSED_FIX_teardown_multirepo.md）。
> 基线：gen3 时点的 server/engine/agent_activities.py teardown_lane（L3438-3470）与
> server/engine/dev_lane.py 收口三步（archive→teardown 调用点）。行号以当时为准。

设计要点（与 PROPOSED_FIX_teardown_multirepo.md 一致）：
- 拆道判定与 merge 落账同源：复用 `_lane_scopes(wt, branch)`（清单损坏=RuntimeError
  不静默回落；单仓=1 条目即旧行为，零回归面）；
- 逐仓对**各自仓**执行 `worktree remove --force <tree>` + `branch -D <branch>`；
- warn 保留（残留=可回收垃圾不阻断收口的既有取舍），但逐仓点名；
- workflow 侧无需改：teardown_lane 自己从 args.worktree/branch 反推 scopes，
  MergeArgs 零新增字段（避免 workflow 改动面与在途票兼容问题）。

--- a/server/engine/agent_activities.py
+++ b/server/engine/agent_activities.py
@@ teardown_lane（原 L3438 起）
 async def teardown_lane(args: MergeArgs) -> MergeResult:
-    repo = REPO_ROOT
+    """（docstring 保留原文，末尾补一句：多仓泳道按 _lane_scopes 逐仓三清——
+    worktree remove / branch -D 对各自仓执行，warn 逐仓点名；单仓=1 条目即旧路径。）"""
     wt = Path(args.worktree) if args.worktree else REPO_ROOT
     if not wt.is_absolute():
         wt = REPO_ROOT / wt
     branch = args.branch
-    # Input guard, same as _squash_merge step 0 (branch comes from external meta)
-    p = _git(["check-ref-format", "--branch", branch], repo)
-    if p.returncode != 0:
-        return MergeResult(ok=False, action="failed",
-                           error="branch %r 非法（check-ref-format 拒绝）：%s"
-                                 % (branch, (p.stderr or "").strip()[-200:]))
+    # 拆道判定与 merge 落账同源（t260911-04 守卫实证：单仓硬编码 repo=REPO_ROOT
+    # 时项目各仓的注册/分支/目录完全够不着，三清一条没执行）。
+    try:
+        scopes = _lane_scopes(wt, branch)
+    except RuntimeError as e:
+        # 清单损坏=人工处置（与 merge/merge_check 同语义），不静默回落单仓锚
+        return MergeResult(ok=False, action="failed", error=str(e)[:400])
     warns: List[str] = []
-    p = _git(["worktree", "remove", "--force", str(wt)], repo, timeout=60)
-    if p.returncode != 0:
-        warns.append("worktree remove 失败: %s" % (p.stderr or "").strip()[-200:])
-    p = _git(["branch", "-D", branch], repo, timeout=30)
-    if p.returncode != 0:
-        warns.append("branch -D 失败: %s" % (p.stderr or "").strip()[-200:])
+    for sc in scopes:
+        repo = Path(str(sc["repo"]))
+        tree = Path(str(sc["tree"]))
+        br = str(sc["branch"])
+        tag = str(sc.get("repo_rel") or "") or "root"
+        p = _git(["check-ref-format", "--branch", br], repo)
+        if p.returncode != 0:
+            warns.append("[%s] branch %r 非法（check-ref-format 拒绝）：%s"
+                         % (tag, br, (p.stderr or "").strip()[-160:]))
+            continue
+        p = _git(["worktree", "remove", "--force", str(tree)], repo, timeout=60)
+        if p.returncode != 0:
+            warns.append("[%s] worktree remove 失败: %s"
+                         % (tag, (p.stderr or "").strip()[-160:]))
+        p = _git(["branch", "-D", br], repo, timeout=30)
+        if p.returncode != 0:
+            warns.append("[%s] branch -D 失败: %s" % (tag, (p.stderr or "").strip()[-160:]))
     return MergeResult(ok=True, action="teardown",
                        merge_commit="", error="；".join(warns))

套用注意（修复票必读）：
1. `worktree remove --force` 移除根树（tree=泳道容器）后，成员树目录会随之消失吗？
   ——不会：成员树是**各自成员仓**的已注册 worktree（目录在泳道容器内但 git 元数据
   挂在成员仓 .git/worktrees），必须逐仓 remove（这正是缺陷本质）；逐仓 remove 后
   泳道容器目录内只余根树自身的注册随根仓 remove 消失，容器壳目录若仍存在（引擎
   只 remove worktree 注册不删目录），需补 `shutil.rmtree(wt)` 兜底删目录——本票
   守卫 T3d-目录 断言盯的就是这一面（修复者请按场景红实测决定是否需要）。
2. 单仓回归面：单仓泳道清单缺失时 _lane_scopes 回落 1 条目（repo=_lane_repo_root(wt)，
   branch=传入 branch）——与旧路径语义等价，但 repo 从 REPO_ROOT 修正为真实项目仓，
   这本身就是对单仓形态的顺带修复（旧代码对引擎仓执行 remove/-D 必 warn，属静默
   假成功）；如有单仓用例断言过旧行为请随修对齐。
3. 跑绿标准：server/engine L1/selfcheck 全绿 + 本票守卫 SUMMARY pass=27 fail=0。
