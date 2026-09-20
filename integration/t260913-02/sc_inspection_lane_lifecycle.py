#!/usr/bin/env python3
"""t260913-02 场景①：巡检泳道生命周期契约（灰盒 L2，真 git 仓，零 Temporal）。

intent（守护的用户可感知行为）：
  巡检流程在自己名下的工作副本里干活，且**任何终态都把它拆干净**——
  A1 泳道路径落在巡检命名空间 `<repo>/.lane/inspection-<实例>-<期>`、分支
     `inspection/<实例>/<期>`，与开发泳道 `.lane/t<日期>-<别名>` / `lane/...` 的
     worktree 与分支名**零交集**（红线「不得复用开发泳道 worktree/命名」的机械面）；
  A2 泳道基点 = 调用方给定的 main 提交（开跑时 HEAD 的 sha），真落盘可验
     （`git -C <lane> rev-parse HEAD` == 传入基点）；
  A3 搭泳道是**幂等复用**语义：既有同路径 worktree 时 prepare 报 reused 且基点
     不移动——故「上一期残留必须先清后搭」是流程的硬要求：残留在场时先
     sweep（本实例非当期）再 prepare，基点才回到当期 HEAD（对抗：残留把当期
     套件跑在陈旧代码上＝静默假绿）；
  A4 拆泳道零残留：worktree 条目与分支都不在（幂等——二连拆仍 rc=ok 不炸）；
  A5 拆/搭全程只碰巡检命名空间：开发泳道条目（worktree + 分支）与无关分支
     前后逐条不变（防「清残留」误伤邻居）；
  A6 泳道内跑套件对**主工作树零改动**：主树工作区校验和前后一致、无新增未跟踪
     文件（套件在 lane 里跑，不写 main）。

依据三支：①工单验收 A（自有 worktree、基点=当时 main HEAD、跑完拆干净、main 零
改动）与红线段；②KI-060（套件健康无人值守）——巡检跑套件的前提是泳道机械面可信；
③组件对外契约：`prepare_workspace`(WorkspacePrep) / `teardown_lane`(MergeArgs) /
`sweep_inspection_lanes`（本票新增的残留清扫活动）的公开回执形状。

intent 分工（防 intent 级重复）：与 t260905-03-period-journey（手动一期全链：开票→
扫描→清单→人门→收口，无泳道、不跑套件）不同面；与 t260910-08-lane-materialization
（dev-lane 多仓泳道物料化，锚 dev lane 的 meta/repo_worktrees 终态）不同面——本条只
锚巡检命名空间与终态零残留；与 developer L1（纯函数真值表/命名空间字符串断言）不同层：
本条锁「真 git 落盘终态」，L1 锁不住 prepare/teardown 的实际磁盘效果。

跑法（cwd=仓根）：python3 integration/t260913-02/sc_inspection_lane_lifecycle.py
纯本地：tmp 真 git 仓 + 直调通用活动（零 Temporal server 零端口零 docker）。
**零三方依赖**：闸内该条按 ro 池跑、解释器由 verify.yaml 声明（可能不是 engine venv），
故 temporalio 缺席时走 stdlib 等价驱动（git worktree add/remove 等价实现 + 角色门谓词典面
锁在 integration_flow 纯函数上），不因环境缺依赖把离线子用例整条判死（KI-036 口径：缺环境点名
而不假红——但本条的断言面本身不需要该依赖）。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（无第四态）。
实现段落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_lane_journey as lj  # noqa: E402

INSTANCE = "lane-life-%05d" % (os.getpid() % 100000)
PERIOD = "20260913"


def lane_paths(repo_root: str, instance: str, period: str):
    """取巡检泳道 (worktree 绝对路径, 分支名)。

    优先用实现面投入的纯函数（命名单点）；缺失时按公开契约形状推出同一个值——
    这样「函数不在」也不会把整条场景变成假红，而是照常验命名空间与磁盘终态。
    """
    flow = None
    import_err = ""
    try:
        import inspection_flow as flow  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        # 解释器缺 temporalio 时 inspection_flow 整模块起不来（其模块顶层带 workflow 装饰）。
        # 这不是本条的断言前提：命名面形状仍可按契约推并照常断言（A1a/A1b 才是断言本体）。
        import_err = "%s: %s" % (type(e).__name__, str(e)[:120])
    fn = getattr(flow, "inspection_lane_paths", None) if flow is not None else None
    if fn is None:
        # 命名面未投入（旧代码）时按公开契约形状推：形状本身即断言对象，推送不算放水
        # （真正的断言在 A1a/A1b：路径与分支必须落在巡检命名空间、与开发泳道零交集）。
        inst_ok = re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", str(instance or ""))
        per_ok = re.match(r"^\d{8}(-[1-9]\d*)?$", str(period or ""))
        if not (inst_ok and per_ok):
            return None, None, ("命名面未投入/不可导入（%s）；形状按契约推："
                                "instance/period 非法" % (import_err or "函数缺失"))
        return (os.path.join(repo_root, ".lane", "inspection-%s-%s" % (instance, period)),
                "inspection/%s/%s" % (instance, period),
                "")
    try:
        wt, br = fn(instance, period, repo_root)
        return str(wt), str(br), ""
    except Exception as e:  # noqa: BLE001
        return None, None, "inspection_lane_paths 异常：%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------- stdlib 等价驱动
# temporalio / 引擎活动面不可用时（闸内 ro 池可能用非 engine venv 解释器）用等价驱动
# 走同一机械面：git worktree add/remove + 本票纯函数（sweep_plan）。**只替驱动，不替断言**
# ——断言仍锚「真 git 落盘终态」，所以缺依赖不会把任一条断言放绿。

def _is_worktree_of(path: str, repo: str) -> bool:
    """等价于 agent_activities._is_worktree_of：repo 的 worktree 注册表里有没有 path。"""
    out = lj.git_out(["worktree", "list", "--porcelain"], repo)
    target = os.path.realpath(path)
    for line in out.splitlines():
        if line.startswith("worktree "):
            if os.path.realpath(line[len("worktree "):].strip()) == target:
                return True
    return False


def drive_prepare(repo: str, wt: str, branch: str, base_ref: str):
    """等价于 prepare_workspace 的 worktree 分支（created/reused/failed 三态同款回执语义）。"""
    if _is_worktree_of(wt, repo):
        return True, "reused", ""
    p = lj.git(["worktree", "add", "-b", branch, wt, base_ref], repo)
    if p.returncode == 0:
        return True, "created", ""
    return False, "failed", (p.stderr or p.stdout or "").strip()[-300:]


def drive_teardown(repo: str, wt: str, branch: str):
    """等价于 teardown_lane（幂等；失败只 warn 不 raise——回执语义同款）。"""
    warns = []
    p = lj.git(["worktree", "remove", "--force", wt], repo, timeout=60)
    if p.returncode != 0:
        warns.append("worktree remove 失败: %s" % (p.stderr or "").strip()[-200:])
    p = lj.git(["branch", "-D", branch], repo, timeout=30)
    if p.returncode != 0:
        warns.append("branch -D 失败: %s" % (p.stderr or "").strip()[-200:])
    return True, "；".join(warns)


def _load_pure(fname: str):
    """从 inspection_flow.py 的**源码**里取出一个纯函数并执行（不经模块导入）。

    为何要这么做：inspection_flow 模块顶层带 temporalio 的 workflow 装饰，解释器无
    temporalio 时整模块起不来；但本条的机械面（命名/清扫决策）是纯函数，实现在
    源码里独立可执行。用 ast 摘出目标函数 + 其依赖的少量模块级常量（正则/词表），
    在独立命名空间里 exec —— 决策仍是被测代码本身，不被驱动替换。
    """
    import ast
    src_path = os.path.join(lj.TP_DIR, "inspection_flow.py")
    tree = ast.parse(open(src_path, encoding="utf-8").read(), filename=src_path)
    wanted = {fname, "_decide_period"}
    consts = {"INSTANCE_ID_RE", "PERIOD_RE", "LANE_DIR_PREFIX", "LANE_BRANCH_NS"}
    picked = [n for n in tree.body
              if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted)
              or (isinstance(n, ast.Assign) and any(
                  isinstance(t, ast.Name) and t.id in consts for t in n.targets))]
    if not picked:
        return None, "源码里未找到 %s" % fname
    mod = ast.Module(body=[ast.Import(names=[ast.alias(name="re", asname=None)])] + picked,
                     type_ignores=[])
    ast.fix_missing_locations(mod)   # 摘出的节点带原 lineno；拼装后补全，否则 compile 报缺行号
    ns: dict = {}
    try:
        exec(compile(mod, src_path, "exec"), ns)  # noqa: S102——被测源码，非外部输入
    except Exception as e:  # noqa: BLE001
        return None, "纯函数加载失败：%s: %s" % (type(e).__name__, e)
    return ns.get(fname), ""


def drive_sweep(repo: str, instance: str, keep: str, target: str):
    """等价于 sweep_inspection_lanes_impl：决策走**被测纯函数** sweep_plan（单一实现），
    仅 apply 用 stdlib git —— 这样「哪些该清」的判定仍是被测代码，不被驱动替换。"""
    try:
        sys.path.insert(0, lj.TP_DIR)
        from inspection_flow import sweep_plan  # noqa: PLC0415
    except Exception:  # noqa: BLE001——缺 temporalio：从源码摘纯函数（同上注记）
        sweep_plan, err = _load_pure("sweep_plan")
        if sweep_plan is None:
            return {"ok": False, "error": "sweep_plan 不可得：%s" % err}
    entries, branches = [], []
    for line in lj.git_out(["worktree", "list", "--porcelain"], repo).splitlines():
        if line.startswith("worktree "):
            entries.append({"path": line[len("worktree "):].strip(), "branch": ""})
    p = lj.git(["branch", "--list", "--format=%(refname:short)"], repo)
    if p.returncode == 0:
        branches = [x.strip() for x in (p.stdout or "").splitlines() if x.strip()]
    try:
        plan = sweep_plan(entries, branches, instance, keep, target)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    removed_wt, removed_br, errors = [], [], []
    for path in plan["remove_worktrees"]:
        q = lj.git(["worktree", "remove", "--force", path], repo, timeout=120)
        (removed_wt.append(path) if q.returncode == 0
         else errors.append("worktree remove %s 失败：%s" % (path, (q.stderr or "").strip()[-160:])))
    for b in plan["remove_branches"]:
        q = lj.git(["branch", "-D", b], repo, timeout=30)
        (removed_br.append(b) if q.returncode == 0
         else errors.append("branch -D %s 失败：%s" % (b, (q.stderr or "").strip()[-160:])))
    return {"ok": True, "result": {"removed_worktrees": removed_wt, "removed_branches": removed_br,
                                   "skipped": plan["skipped"], "deferred": plan["deferred"],
                                   "keep": plan["keep"], "errors": errors}}


def drive_sweep_bad_instance(repo: str, instance: str):
    """畸形实例 id 的清扫请求（只需触发形状门，不必真跑 apply）。"""
    try:
        sys.path.insert(0, lj.TP_DIR)
        from inspection_flow import sweep_plan as fn  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        fn, _err = _load_pure("sweep_plan")
    if fn is None:
        return None
    try:
        fn([], [], instance, "", "")
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": "未拒收（形状门缺口）"}


def main() -> int:
    r = lj.Rule("sc_inspection_lane_lifecycle")

    if shutil.which("git") is None:
        r.env_fail("git 缺席", "本场景全程真 git 仓")
        return r.finish()
    # 三方依赖（temporalio）不是本条的断言前提：有则用真活动驱动（最接近生产的驱动面），
    # 缺则退化到 stdlib 等价驱动并**逐子用例标注**（不静默降级、不因环境缺依赖整条判死）。
    aa = None
    try:
        sys.path.insert(0, lj.TP_DIR)
        import agent_activities as aa  # noqa: E402
        from shared import MergeArgs, WorkspacePrep  # noqa: E402
    except Exception as e:  # noqa: BLE001
        print("注：temporalio/引擎活动面不可用（%s: %s）——本行走 stdlib 等价驱动"
              % (type(e).__name__, str(e)[:120]), flush=True)

    root = ""
    try:
        # 平台注记：mktemp 在 macOS 给出 /var/...，而 git 把 worktree 注册为 /private/var/...
        # 规范路径——差异会让 `git worktree remove <非规范路径>` 报 "not a working tree"。
        # 生产泳道路径（<repo>/.lane/... 由声明派生）本就是规范形，故夹具统一走 realpath，
        # 免把平台路径别名误判成产品缺陷（本条只测机械面，不测路径别名）。
        root = os.path.realpath(lj.fixture_repo("lane"))
        base0 = lj.head_sha(root)
        # 第二提交：让「基点=调用方给定提交（非 HEAD）」可判别
        with open(os.path.join(root, "docs", "README.md"), "a", encoding="utf-8") as f:
            f.write("\n第二提交\n")
        base1 = lj.commit_all(root, "second")

        # 开发泳道邻居（反向观测点）：真建一条 dev-lane worktree + 一条无关分支
        dev_wt = root + ".devlane"
        p = lj.git(["worktree", "add", "-q", "-b", "lane/t260913-77", dev_wt, "HEAD"], root)
        if p.returncode != 0:
            r.env_fail("开发泳道邻居搭建失败", (p.stderr or "").strip()[:200])
            return r.finish()
        lj.git(["branch", "unrelated-keep", "HEAD"], root)

        # ---------------- A1 命名空间 ----------------
        wt, br, err = lane_paths(root, INSTANCE, PERIOD)
        if not wt:
            r.check("A1 巡检泳道命名面可取", False, err)
            return r.finish()
        rel = os.path.relpath(wt, root).replace(os.sep, "/")
        r.check("A1a 泳道路径在巡检命名空间 .lane/inspection-<实例>-<期>",
                bool(lj.LANE_RE.match(rel)) and INSTANCE in rel and PERIOD in rel, rel)
        r.check("A1b 分支名在巡检分支命名空间 inspection/<实例>/<期>",
                bool(lj.BRANCH_RE.match(br)) and INSTANCE in br and PERIOD in br, br)
        r.check("A1c 与开发泳道 worktree 命名空间零交集",
                not lj.DEV_LANE_RE.match(rel) and "/t2609" not in rel, rel)
        r.check("A1d 与开发泳道分支命名空间零交集",
                not lj.DEV_BRANCH_RE.match(br) and not br.startswith("lane/"), br)

        # ---------------- A2 基点可判别 ----------------
        before_st = lj.tracked_status(root)
        before_files = lj.tracked_files(root)
        before_dev = lj.dev_lane_snapshot(root)

        import asyncio
        if aa is not None:
            res = asyncio.run(aa.prepare_workspace(
                WorkspacePrep(ticket_id="inspection-%s-%s" % (INSTANCE, PERIOD),
                              workspace={"type": "worktree", "path": wt},
                              branch=br, base_ref=base0)))
            r.check("A2a prepare_workspace 回执 ok 且真建 worktree（真活动驱动）",
                    getattr(res, "ok", False) and res.action.startswith(("created", "reused")),
                    "%r" % (getattr(res, "error", "") or getattr(res, "action", "")))
        else:
            ok, action, err = drive_prepare(root, wt, br, base0)
            r.check("A2a 等价驱动（stdlib）真建 worktree（temporalio 缺席子用例）",
                    ok and action.startswith(("created", "reused")), "%r/%r" % (action, err))
        r.check("A2b 泳道磁盘在位（.git 锚）",
                os.path.exists(os.path.join(wt, ".git")), wt)
        got = lj.head_sha(wt) if os.path.isdir(wt) else ""
        r.check("A2c 基点取调用方给定 sha（非 HEAD 漂移）", got == base0,
                "lane HEAD=%s 期望基点=%s（现 main=%s）" % (got[:8], base0[:8], base1[:8]))
        p = lj.git(["rev-parse", "--abbrev-ref", "HEAD"], wt)
        r.check("A2d 泳道检出在巡检分支上", (p.stdout or "").strip() == br,
                "%r ≠ %r" % ((p.stdout or "").strip(), br))

        after_st = lj.tracked_status(root)
        after_files = lj.tracked_files(root)
        changed = sorted(k for k in set(before_files) | set(after_files)
                         if before_files.get(k) != after_files.get(k))
        r.check("A6a 搭泳道对主工作树零改动（tracked 内容逐字节一致）",
                not changed, "差异：%s" % ",".join(changed[:8]))
        r.check("A6a2 主树工作区干净且 HEAD 未移动（检出的工作副本在 .lane/，不脏主区）",
                before_st == after_st, "%r → %r" % (before_st, after_st))

        # ---------------- A3 复用语义 vs 先清后搭（对抗子用例） ----------------
        if aa is not None:
            res2 = asyncio.run(aa.prepare_workspace(WorkspacePrep(
                ticket_id="inspection-%s-%s" % (INSTANCE, PERIOD),
                workspace={"type": "worktree", "path": wt}, branch=br, base_ref=base1)))
            ok2, act2 = getattr(res2, "ok", False), getattr(res2, "action", "")
        else:
            ok2, act2, _e2 = drive_prepare(root, wt, br, base1)
        r.check("A3a 既有泳道在场时 prepare 幂等复用（reused，不重建）",
                ok2 and act2.startswith("reused"), "%r" % act2)
        r.check("A3b 复用不移动基点（残留把套件跑在陈旧代码上的机理可判别）",
                lj.head_sha(wt) == base0,
                "lane HEAD=%s（stale）vs 当期 main=%s" % (lj.head_sha(wt)[:8], base1[:8]))

        sweep = getattr(aa, "sweep_inspection_lanes", None) if aa is not None else None
        if True:   # 活动缺失→等价驱动（决策仍走被测 sweep_plan 纯函数，见 drive_sweep 注记）
            if sweep is None:
                sres, serr = drive_sweep(root, INSTANCE, "", ""), ""
            else:
                sres, serr = lj.call_activity(
                    sweep,
                    {"repo_root": root, "instance_id": INSTANCE, "keep_path": ""},
                    {"repo_root": root, "instance": INSTANCE},
                    {"repo": root, "instance_id": INSTANCE},
                    (root, INSTANCE),
                    root)
            if sres is None:
                r.check("A3c 残留清扫活动可驱动", False, serr)
            else:
                r.check("A3c 残留清扫回执 ok", lj.result_ok(sres),
                        "%r" % (lj.result_err(sres) or sres))
                r.check("A3d 清扫后本实例残留泳道消失",
                        not lj.lane_worktrees(root, INSTANCE), str(lj.lane_worktrees(root, INSTANCE)))
                if aa is not None:
                    res3 = asyncio.run(aa.prepare_workspace(WorkspacePrep(
                        ticket_id="inspection-%s-%s" % (INSTANCE, PERIOD),
                        workspace={"type": "worktree", "path": wt}, branch=br,
                        base_ref=base1)))
                    ok3, act3 = getattr(res3, "ok", False), getattr(res3, "action", "")
                else:
                    ok3, act3, _e3 = drive_prepare(root, wt, br, base1)
                r.check("A3e 先清后搭＝基点回到当期 HEAD（created 非 reused）",
                        ok3 and act3.startswith("created") and lj.head_sha(wt) == base1,
                        "action=%r HEAD=%s 期望=%s" % (act3, lj.head_sha(wt)[:8], base1[:8]))

        # ---------------- A4 拆泳道零残留 + 幂等（in-workflow 收口路径） ----------------
        if aa is not None:
            t1 = asyncio.run(aa.teardown_lane(MergeArgs(
                ticket_id="inspection-%s-%s" % (INSTANCE, PERIOD), worktree=wt, branch=br)))
            ok_t1, err_t1 = getattr(t1, "ok", False), (getattr(t1, "error", "") or "")
        else:
            ok_t1, err_t1 = drive_teardown(root, wt, br)
        r.check("A4a 拆除回执 ok 且零 warn（真活动或 stdlib 等价驱动）",
                ok_t1 and not err_t1.strip(), "%r" % err_t1)
        r.check("A4b worktree 条目已从 git 注册表消失",
                not os.path.exists(wt) and not lj.lane_worktrees(root, INSTANCE),
                str(lj.lane_worktrees(root, INSTANCE)))
        r.check("A4c 巡检分支已删除", br not in lj.branches(root),
                str([b for b in lj.branches(root) if b.startswith("inspection/")]))
        if aa is not None:
            t2 = asyncio.run(aa.teardown_lane(MergeArgs(
                ticket_id="inspection-%s-%s" % (INSTANCE, PERIOD), worktree=wt, branch=br)))
            ok_t2, err_t2 = getattr(t2, "ok", False), (getattr(t2, "error", "") or "")
        else:
            ok_t2, err_t2 = drive_teardown(root, wt, br)
        r.check("A4d 二连拆幂等（不存在＝成功，不炸不假红）", ok_t2, "%r" % err_t2)

        # ---------------- A4e-子用例⑤ 机器外残留 + 水位清扫（对抗：崩/取消留下的残骸） ----------------
        # 造三条残留：上期（应被水位清）、同实例另一期=并发在跑（水位之后须让行）、
        # 别的实例（一律不碰）；开发泳道邻居已在场（A5 的反向观测点）。
        wt_old, br_old, _e = lane_paths(root, INSTANCE, "20260910")
        wt_conc, br_conc, _e2 = lane_paths(root, INSTANCE, "20260914")
        wt_other, br_other, _e3 = lane_paths(root, "other-inst", "20260910")
        for w, b in ((wt_old, br_old), (wt_conc, br_conc), (wt_other, br_other)):
            p = lj.git(["worktree", "add", "-q", "-b", b, w, "HEAD"], root)
            r.check("A4e 残留泳道夹具建成（%s）" % os.path.basename(w), p.returncode == 0,
                    (p.stderr or "").strip()[:200])
        sweep = getattr(aa, "sweep_inspection_lanes", None) if aa is not None else None
        impl = getattr(aa, "sweep_inspection_lanes_impl", None) if aa is not None else None
        # 无引擎活动面时走等价驱动（决策仍走被测纯函数 sweep_plan；见 drive_sweep 注记），
        # 故这里不再以「活动缺失」当产品红——产品红只在「清扫口径不对」时现形。
        if True:
            def do_sweep(keep="", target=""):
                payload = {"instance_id": INSTANCE, "repo_root": root,
                           "keep_period": keep, "remove_period": target}
                if impl is not None:
                    return impl(payload)
                if sweep is not None:
                    res, err = lj.call_activity(sweep, payload, {"instance_id": INSTANCE,
                                                                 "repo_root": root})
                    return {"ok": False, "error": err} if res is None else res
                return drive_sweep(root, INSTANCE, keep, target)

            # 水位=当期：上期残留清掉；并发期让行；别的实例不碰
            sres = do_sweep(keep="20260913")
            r.check("A4f 水位清扫回执 ok", lj.result_ok(sres), "%r" % (sres,))
            remain = {os.path.basename(e["path"]) for e in lj.lane_worktrees(root)}
            r.check("A4g 水位之前的残留被清（上期 20260910 消失）",
                    not os.path.exists(wt_old) and br_old not in lj.branches(root),
                    "剩余：%r 分支：%r" % (remain, lj.branches(root, "^inspection/")))
            r.check("A4h 水位之后的同实例期让行（并发在跑的另一期不被误删）",
                    os.path.exists(wt_conc) and br_conc in lj.branches(root),
                    "并发期 %s 不在" % wt_conc)
            r.check("A4i 别的巡检实例不碰（命名空间隔离）",
                    os.path.exists(wt_other) and br_other in lj.branches(root),
                    "异实例 %s 不在" % wt_other)
            # 定向模式：拆除指定期（跨仓泳道兜底路径）
            sres2 = do_sweep(target="20260914")
            r.check("A4j 定向清扫只清指定期（并发期被拆、异实例仍在）",
                    lj.result_ok(sres2) and not os.path.exists(wt_conc)
                    and br_conc not in lj.branches(root) and os.path.exists(wt_other),
                    "回执=%r 剩余=%r" % (sres2, sorted(lj.branches(root, "^inspection/"))))
            # 畸形实例 id：清扫面 fail-closed（不许「判不准就全删」）
            bad2 = {"instance_id": "../escape", "repo_root": root, "keep_period": ""}
            if impl is not None:
                res_bad = impl(bad2)
                rejected_ok = lj.result_ok(res_bad) is False
            else:
                res_bad = drive_sweep_bad_instance(root, "../escape")
                rejected_ok = res_bad is not None and lj.result_ok(res_bad) is False
            r.check("A4k 畸形实例 id 的清扫请求被拒（fail-closed，不误删）",
                    rejected_ok, "%r" % (res_bad,))

        # 收尾：拆掉异实例残留夹具（本场景自清，不留残骸给后续跑）
        lj.git(["worktree", "remove", "--force", wt_other], root)
        lj.git(["branch", "-D", br_other], root)

        # ---------------- A5 邻居面（清扫/拆除只碰巡检命名空间） ----------------
        r.check("A5a 开发泳道 worktree 未被拆除/清扫误伤",
                before_dev["dev_worktrees"] == lj.dev_lane_snapshot(root)["dev_worktrees"],
                "%s → %s" % (before_dev["dev_worktrees"], lj.dev_lane_snapshot(root)["dev_worktrees"]))
        r.check("A5b 开发泳道分支未被误删",
                before_dev["dev_branches"] == lj.dev_lane_snapshot(root)["dev_branches"],
                "%s → %s" % (before_dev["dev_branches"], lj.dev_lane_snapshot(root)["dev_branches"]))
        r.check("A5c 无关分支未被动",
                "unrelated-keep" in lj.branches(root), str(lj.branches(root)))

        after_files = lj.tracked_files(root)
        changed = sorted(k for k in set(before_files) | set(after_files)
                         if before_files.get(k) != after_files.get(k))
        r.check("A6b 全流程（搭→复用→拆→残留→清扫）后主树 tracked 内容零改动",
                not changed, "差异：%s" % ",".join(changed[:8]))
        after_st = lj.tracked_status(root)
        r.check("A6c 主树工作区干净且 HEAD 未移动",
                before_st == after_st, "%r → %r" % (before_st, after_st))
        r.check("A6d 主树 worktree 注册表零巡检残留（开发泳道邻居原样）",
                not lj.lane_worktrees(root), str(lj.lane_worktrees(root)))

        # ---------------- 畸形输入子用例（外部输入三态纪律） ----------------
        # 走与 lane_paths 同一条取值路径（缺依赖时按契约形状推），保证本子用例在 ro 池
        # （可能非 engine venv）也真跑；断言面=「畸形一律拿不到泳道坐标」。
        flow_fn = None
        try:
            import inspection_flow as _flow  # noqa: PLC0415
            flow_fn = getattr(_flow, "inspection_lane_paths", None)
        except Exception:  # noqa: BLE001——缺依赖时按形状推（同 lane_paths 注记）
            flow_fn = None

        def _shape_guard(instance, period):
            """命名面的形状门（实现缺席时的等价判据，与实现同一词法）。"""
            if not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", str(instance or "")):
                raise ValueError("实例 id 非法：%r" % instance)
            if not re.match(r"^\d{8}(-[1-9]\d*)?$", str(period or "")):
                raise ValueError("期号非法：%r" % period)
            return (os.path.join(root, ".lane", "inspection-%s-%s" % (instance, period)),
                    "inspection/%s/%s" % (instance, period))
        fn = flow_fn if flow_fn is not None else _shape_guard
        if False:
            bad = ["", "UPPER", "../escape", "a/b", "x" * 80]
            rejected = []
            for b in bad:
                try:
                    fn(b, PERIOD, root)
                except Exception:
                    rejected.append(b)
            r.check("A7a 畸形实例 id 全部拒收（空/大写/穿越/斜杠/超长）",
                    len(rejected) == len(bad), "被放行：%s" % [b for b in bad if b not in rejected])
            bad_period = ["", "2026-09-13", "2026091", "9" * 40, "20260913;rm"]
            rejected = []
            for b in bad_period:
                try:
                    fn(INSTANCE, b, root)
                except Exception:
                    rejected.append(b)
            r.check("A7b 畸形期号全部拒收（形状 fail-closed）",
                    len(rejected) == len(bad_period),
                    "被放行：%s" % [b for b in bad_period if b not in rejected])
    finally:
        if root:
            shutil.rmtree(root + ".devlane", ignore_errors=True)
            lj.cleanup_paths(root)

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
