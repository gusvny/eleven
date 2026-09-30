#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_surface_plan_query.py —— t260930-02 变更面查询的端到端行为（灰盒 L3，黑盒驱动）。

intent（用户可感知行为；真源=票面冻结契约「恰好一行 JSON，退出码恒 0，判定在
mode/reason 里」）：在**真仓树**上以真子进程跑 `integration/run_scenarios.py
--print-surface-plan <改动清单>`，锁查询面自身的对外状态机——
  A. 插件改动（真注册表）：`server/plugins/workbench/src/client/theme.ts` →
     mode=targeted/reason=ok/surfaces=["workbench-ui"]；名单排序去重、每条都在册、
     非平凡但**严格窄于全量**；`always` 全量守卫一条不少；`expected==len(names)`；
  B. **产物派生（欠近似缺口的端到端钉）**：同一改动下，只加载构建产物、从不起控制台的
     场景（`t260903-13-workbench-bundle-loads` / `t260902-05-t06-ui-build-gate`）仍在
     名单里，且情报行点名派生产物前缀——「改 src 连带改 lib/」这半面不吃 console 判据；
  C. 非 console 面（`server/plugins/watchdog/`）→ 仍是 targeted，但**明显窄于** console
     面的计划，且控制台族（如 capture 链）不被拖进来（console 判据的负向对照）；
  D. `integration/run_scenarios.py`（场景资产=共享面）→ full，names=[]，
     reason=unclassified-path:integration/run_scenarios.py；
  E. 未声明路径（`verify.yaml`）→ full + 具名 reason（绝不因「看着无关」收窄）；
  F. 空清单 → full + no-changed-files；
  G. 声明面缺席（env 覆盖指向不存在文件）→ full + surface-doc-missing；
  H. 声明面畸形（坏 JSON）→ full + surface-doc-malformed；
  I. 选择器名不在册（夹具声明面：always 含假名）→ full + unknown-selector；
  J. 只读面纪律：不占同泳道单飞锁（锁档零落盘）、不起任何场景（无规范行/无汇总行）、
     两次同输入逐字节同输出（幂等）。

分层与 intent 分工（防重复，与既有资产不互替）：
  · 执行器侧纯函数与计划组装的全部真值分支（路径归属/三态加载/空名单/词表自证）
    → L1 `server/engine/tests/test_t260930_02_surface_plan_query.py`（白盒），本场景不重测；
  · 引擎侧回执解析与 activity 四态回全量、接线结构锁
    → `server/engine/tests/test_t260930_02_surface_plan.py`（同票并行件），本场景不重测；
  · 引擎侧「面计划并进快反馈轮、收口全量跑不动」的泳道行为 → 该票引擎侧场景/单测，
    本场景只锁执行器侧的查询出口。

安全红线：零 docker、零 Temporal、零端口、零浏览器；**永不接触 3099**；夹具声明面只落
本场景私有临时目录（finally 回收）；单飞锁档路径 `SANDBAR_INTEG_RUN_LOCK_PATH` 指到临时区，
并断言查询跑完**锁档零落盘**。三态：python3/被测文件缺席（判据面不在）=ENV_FAIL exit 2；
断言不符=FAIL exit 1。
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t260930-02-surface-plan-query"
RUNNER = "integration/run_scenarios.py"
DOC_REL = "integration/scenario-surfaces.json"

PASS_N = FAIL_N = NA_N = 0
_TMP = None
_RECLAIMED = False


def ok(cond, label, detail=""):
    global PASS_N, FAIL_N
    if cond:
        PASS_N += 1
        print("  ok " + label, flush=True)
    else:
        FAIL_N += 1
        print("  FAIL " + label + (" | " + str(detail)[:600] if detail else ""), flush=True)


def na(label, reason):
    global NA_N
    NA_N += 1
    print("  N/A: %s（%s）" % (label, str(reason)[:400]), flush=True)


def finish():
    if NA_N and PASS_N == 0 and FAIL_N == 0:
        print("FAIL [%s] exit=1\n    全部子用例 N/A=无可验对象（设计/覆盖问题）" % NAME,
              flush=True)
        sys.exit(1)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS_N, FAIL_N, NA_N), flush=True)
    sys.exit(1 if FAIL_N else 0)


def env_fail(reason):
    print("ENV_FAIL [%s] exit=2\n    %s" % (NAME, reason), flush=True)
    sys.exit(2)


def _cleanup():
    """终态回收（幂等）：夹具临时目录。"""
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    try:
        if _TMP is not None:
            shutil.rmtree(str(_TMP), ignore_errors=True)
    except Exception:          # noqa: BLE001 —— 回收面不抛（残留交清扫器）
        pass


atexit.register(_cleanup)


# ---------------------------------------------------------------- 夹具与驱动

def _registry():
    """注册表真源=被测树内执行器的 SCENARIOS（按文件位装载，防手抄漂移）。

    这不是「白盒实现断言」：本场景的断言全落在查询的对外输出上，注册表只当
    「名字是否在册」的**判据源**（与 t260921-06 的机械取册同族）。"""
    spec = importlib.util.spec_from_file_location("_rs_oracle_t260930_02", HERE.parent / "run_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _query(arg, extra_env=None, timeout=180):
    """黑盒驱动：真入口、CWD=仓根、单飞锁档投临时区；返回 (rc, 行列表, stderr)。"""
    env = dict(os.environ)
    env["SANDBAR_INTEG_RUN_LOCK_PATH"] = str(_TMP / "run.lock")
    for k in ("SANDBAR_SCENARIO_ONLY", "SANDBAR_SCENARIO_EXCLUDE_POOLS"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in (extra_env or {}).items()})
    cmd = [sys.executable, RUNNER, "--print-surface-plan"] + ([arg] if arg is not None else [])
    try:
        p = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        return -9, [], "查询超时：%s" % (e,)
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    return p.returncode, lines, (p.stderr or "")


def _plan(arg, extra_env=None):
    """跑一次查询并解析单行 JSON → (plan, rc, lines, stderr)；解析不了给 None。"""
    rc, lines, err = _query(arg, extra_env)
    plan = None
    if len(lines) == 1:
        try:
            plan = json.loads(lines[0])
        except ValueError:
            plan = None
    return plan, rc, lines, err


def _decl():
    return json.loads((REPO / DOC_REL).read_text(encoding="utf-8"))


def _write_doc(obj, name):
    p = _TMP / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- 主程序

def main():
    global _TMP
    if shutil.which(sys.executable) is None and shutil.which("python3") is None:
        env_fail("python3 缺席：判据面（真入口子进程）不可达")
    if not (REPO / RUNNER).is_file():
        env_fail("被测执行器缺席：%s" % (REPO / RUNNER))
    if not (REPO / DOC_REL).is_file():
        env_fail("变更面声明面缺席：%s（查询会 fail-closed，但本场景的判据面无从判定）"
                 % (REPO / DOC_REL))
    _TMP = Path(tempfile.mkdtemp(prefix="t260930-02-surface-"))
    rs = _registry()
    total = len(rs.SCENARIOS)
    known = [e[0] for e in rs.SCENARIOS]
    known_set = set(known)
    always = list(_decl()["always"])

    def _names_sane(plan, label):
        names = plan.get("names") or []
        ok(names == sorted(set(names)), "%s 名单排序去重" % label, names[:5])
        bad = [n for n in names if n not in known_set]
        ok(bad == [], "%s 名单每条都在册" % label, bad[:5])
        ok(plan.get("expected") == len(names),
           "%s expected==len(names)（消费方可对账在册数）" % label,
           (plan.get("expected"), len(names)))

    # ---------------- A/B 插件改动：定点 + 产物派生 ----------------
    plugin_change = "server/plugins/workbench/src/client/theme.ts"
    planA, rcA, linesA, errA = _plan(plugin_change)
    ok(rcA == 0 and planA is not None,
       "A1 插件改动：退出码 0 且 stdout 恰一行 JSON（冻结契约）",
       (rcA, len(linesA), errA[-300:], linesA[:1]))
    if planA is None:
        finish()
    ok(planA.get("mode") == "targeted" and planA.get("reason") == "ok",
       "A2 插件改动=targeted/ok（不因 server/plugins/ 恒全量）",
       (planA.get("mode"), planA.get("reason")))
    ok(planA.get("surfaces") == ["workbench-ui"],
       "A3 命中面点名 workbench-ui（留痕面，供人审）", planA.get("surfaces"))
    _names_sane(planA, "A4")
    nA = len(planA["names"])
    ok(20 <= nA < total,
       "A5 名单非平凡且**严格窄于**全量（经济性主张：%d < 在册 %d）" % (nA, total),
       (nA, total))
    missing_always = [n for n in always if n not in set(planA["names"])]
    ok(missing_always == [],
       "A6 always 全仓守卫一条不少（%d 条）" % len(always), missing_always[:5])
    ok("workbench-ui" in (planA.get("surfaces") or [])
       and any("lib/" in n for n in (planA.get("notes") or [])),
       "B1 情报行点名派生产物前缀（产物派生这半面在场，不静默）",
       planA.get("notes"))
    for bundle_consumer in ("t260903-13-workbench-bundle-loads",
                            "t260902-05-t06-ui-build-gate"):
        ok(bundle_consumer in set(planA["names"]),
           "B2 只加载产物的场景仍在名单：%s（**欠近似缺口**的端到端钉）" % bundle_consumer,
           planA["names"][:8])
    planA2, rcA2, linesA2, _ = _plan(plugin_change)
    ok(rcA2 == 0 and linesA2 == linesA,
       "A7 幂等：同输入两次查询逐字节同输出（无隐藏状态漂移）",
       (linesA[:1], linesA2[:1]))

    # ---------------- C 非 console 面：仍定点、且明显更窄（负向对照） ----------------
    planC, rcC, _, errC = _plan("server/plugins/watchdog/src/x.ts")
    ok(rcC == 0 and planC is not None and planC.get("mode") == "targeted",
       "C1 非 console 插件面（watchdog）仍给定点计划", (rcC, errC[-200:]))
    if planC is not None:
        ok(planC.get("surfaces") == ["watchdog"],
           "C2 命中面点名 watchdog（不含 console 面）", planC.get("surfaces"))
        ok(len(planC["names"]) < nA,
           "C3 console=false 的负向对照：明显窄于 console 面的计划（%d < %d）"
           % (len(planC["names"]), nA), (len(planC["names"]), nA))
        ok(not any(n.startswith("capture-") for n in planC["names"]),
           "C4 控制台族（capture 链）不被拖进非 console 面",
           [n for n in planC["names"] if n.startswith("capture-")])
        _names_sane(planC, "C5")

    # ---------------- D/E/F 全量三态：场景资产 / 未声明路径 / 空清单 ----------------
    for label, arg, reason in (
            ("D1 场景资产（integration/**=共享面）", RUNNER,
             "unclassified-path:" + RUNNER),
            ("E1 未声明路径（声明面之外的改动）", "verify.yaml",
             "unclassified-path:verify.yaml"),
            ("F1 空清单（无改动不放窄也不空跑）", None, "no-changed-files")):
        plan, rc, lines, err = _plan(arg)
        ok(rc == 0 and plan is not None and plan.get("mode") == "full"
           and plan.get("reason") == reason and plan.get("names") == [],
           "%s ⇒ full + 具名 reason + names=[]" % label,
           (rc, plan.get("mode") if plan else None,
            plan.get("reason") if plan else None, err[-200:]))
        if plan is not None:
            ok(plan.get("expected") == total,
               "%s full 计划 expected=在册总数（消费方可对账）" % label,
               (plan.get("expected"), total))

    # ---------------- G/H/I 声明面三态：缺席 / 畸形 / 未知选择器名 ----------------
    plan, rc, _, err = _plan(plugin_change,
                             {"SANDBAR_SCENARIO_SURFACES": str(_TMP / "nope.json")})
    ok(rc == 0 and plan is not None and plan.get("mode") == "full"
       and plan.get("reason") == "surface-doc-missing",
       "G1 声明面缺席 ⇒ full + surface-doc-missing（绝不回落默认面）",
       (rc, plan.get("reason") if plan else None, err[-200:]))
    broken = _TMP / "broken.json"
    broken.write_text("{ not json at all", encoding="utf-8")
    plan, rc, _, _ = _plan(plugin_change, {"SANDBAR_SCENARIO_SURFACES": str(broken)})
    ok(rc == 0 and plan is not None and plan.get("mode") == "full"
       and plan.get("reason") == "surface-doc-malformed",
       "H1 声明面畸形 ⇒ full + surface-doc-malformed（半张表不可信）",
       (rc, plan.get("reason") if plan else None))
    fixture = dict(_decl())
    fixture["always"] = list(fixture["always"]) + ["no-such-scenario-in-registry"]
    path = _write_doc(fixture, "unknown-selector.json")
    plan, rc, _, _ = _plan(plugin_change, {"SANDBAR_SCENARIO_SURFACES": path})
    ok(rc == 0 and plan is not None and plan.get("mode") == "full"
       and plan.get("reason") == "unknown-selector",
       "I1 always 含不在册选择器名 ⇒ full + unknown-selector（绝不静默跳过）",
       (rc, plan.get("reason") if plan else None))
    fixture2 = dict(_decl())
    fixture2["surfaces"] = [dict(s) for s in fixture2["surfaces"]]
    fixture2["surfaces"][5] = dict(fixture2["surfaces"][5],
                                   names=["no-such-scenario-in-registry"])
    path2 = _write_doc(fixture2, "unknown-surface-name.json")
    plan, rc, _, _ = _plan(plugin_change, {"SANDBAR_SCENARIO_SURFACES": path2})
    ok(rc == 0 and plan is not None and plan.get("mode") == "full"
       and plan.get("reason") == "unknown-selector",
       "I2 **未命中面**的 names 含错名同样判 full（配置缺陷不因无人用而静默）",
       (rc, plan.get("reason") if plan else None))
    fixture3 = dict(_decl())
    fixture3["surfaces"] = [dict(s) for s in fixture3["surfaces"]]
    fixture3["surfaces"][5] = {k: v for k, v in fixture3["surfaces"][5].items()
                               if k != "artifacts"}
    path3 = _write_doc(fixture3, "missing-artifacts.json")
    plan, rc, _, _ = _plan(plugin_change, {"SANDBAR_SCENARIO_SURFACES": path3})
    ok(rc == 0 and plan is not None and plan.get("mode") == "full"
       and plan.get("reason") == "surface-doc-malformed",
       "I3 有 paths 但缺 artifacts 键 ⇒ 畸形 ⇒ full（产物面判不出绝不静默放过）",
       (rc, plan.get("reason") if plan else None))

    # ---------------- J 只读面纪律：不占锁、不起场景 ----------------
    lock = _TMP / "run.lock"
    ok(not lock.exists(), "J1 只读查询面**不占同泳道单飞锁**（锁档零落盘）",
       "lock=%s exists=%s" % (lock, lock.exists()))
    joined = "\n".join(linesA)
    ok("PASS [" not in joined and "FAIL [" not in joined
       and "INTEG_SUMMARY" not in joined and "SCENARIOS ran=" not in joined,
       "J2 只读查询面不起任何场景（无规范行/无汇总行）",
       linesA[:2])
    plan_empty, rc_empty, _, _ = _plan("")
    ok(rc_empty == 0 and plan_empty is not None,
       "J3 空入参也给合法单行 JSON（退出码恒 0，判定在 mode/reason）", rc_empty)


if __name__ == "__main__":
    try:
        main()
    finally:
        _cleanup()
    finish()          # 早退档（env_fail/finish）自行 exit；正常返回后才收口
