#!/usr/bin/env python3
"""t260913-03 场景①：池排除开关的消费形态矩阵（真闸 + 真执行器，灰盒 L2）。

intent（用户可感知）：集测道开关在三/四种消费形态下的行为契约——
  A 形态：声明面打开 + 每票段传入 apply → 被跳池条目**不在本轮在册**（不计 ran/pass/fail），
         汇总**点名**「本轮跳过池=engine,exclusive（少 N 条）」，INTEG_SUMMARY 的 ran==expected==在册；
  E 形态：声明面**在场**但消费点不传 apply（巡检 / 手动 / 老回放形态）→ **恒全跑**（本开关不得外溢）；
  B 形态：声明面缺省 → 与现状一致的全跑，且汇总**零新增键**（不假造排除面）。
断言面=真入口 `admin.py call verify_lane` 的公开回执 + 执行器末行/汇总行契约，不锚内部实现。

high-level steps：造两条最小真泳道（真 verify.yaml / 真解析器 / 真 run_scenarios.py + mini 注册表），
  ①直跑执行器注 env → 断言点名行/计数/条件键（不依赖闸，先跑）；
  ②闸消费参数契约面在场后：经真闸 apply → 断言在册数、被跳条目零出现、回执点名；
  ③经真闸不传 apply → 断言全跑；④无声明泳道 + apply → 断言全跑且无排除面。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_pool_exclude_lane as F  # noqa: E402

C = F.Checker("t260913-03-scenario-1-switch-forms")

SPEC = [
    ("mini-main", "main", True),
    ("mini-ro", "ro", True),
    ("mini-engine", "engine", True),
    ("mini-engine2", "engine", True),
    ("mini-excl", "exclusive", True),
]
EXCLUDED_POOLS = ("engine", "exclusive")
ALL_NAMES = [n for n, _, _ in SPEC]
IN_NAMES = [n for n, p, _ in SPEC if p not in EXCLUDED_POOLS]
OUT_NAMES = [n for n, p, _ in SPEC if p in EXCLUDED_POOLS]
N_OUT = len(OUT_NAMES)


def _diag(res):
    r = res.get("result") or {}
    return "ok=%s err=%s ran=%s names=%s pool_exclude=%s" % (
        res.get("ok"), r.get("err"), r.get("ran"), F.scenario_names(r),
        r.get("pool_exclude"))


with F.tmpdir() as td:
    declared = F.build_lane(td / "declared", SPEC)
    plain = F.build_lane(td / "plain", SPEC, declare=False)

    # ---------------- A 形态①：执行器直跑（点名行 + 计数 + 条件键） ----------------
    p = F.run_executor(declared["lane"], env={"SANDBAR_SCENARIO_EXCLUDE_POOLS": F.EXCLUDE_VALUE})
    counts = F.summary_counts(p.stdout)
    isumm = F.integ_summary(p.stdout)
    C.check(p.returncode == 0, "A1 直跑 rc=0（被跳池不参与本轮红绿）",
            "rc=%s tail=%s" % (p.returncode, p.stdout[-300:]))
    C.check(counts is not None and counts["ran"] == len(IN_NAMES),
            "A2 末行 ran==本轮在册 %d（被跳条目不计入）" % len(IN_NAMES), "counts=%s" % counts)
    C.check(bool(F.named_exclude_line(p.stdout, EXCLUDED_POOLS, N_OUT)),
            "A3 汇总点名「本轮跳过池=engine,exclusive（少 %d 条）」" % N_OUT,
            "named_pools=%s" % F.excluded_named_pools(p.stdout))
    C.check(isumm is not None and isumm.get("ran") == isumm.get("expected") == len(IN_NAMES),
            "A4 INTEG_SUMMARY ran==expected==本轮在册 %d（不缺不假）" % len(IN_NAMES),
            "INTEG_SUMMARY=%s" % isumm)
    C.check(isumm is not None and isumm.get("excluded_count") == N_OUT
            and set(isumm.get("excluded_pools") or []) == set(EXCLUDED_POOLS),
            "A5 汇总条件键点名池与条数（excluded_pools/excluded_count）",
            "INTEG_SUMMARY=%s" % isumm)
    C.check(all(("PASS [%s]" % n) not in p.stdout for n in OUT_NAMES)
            and all(("PASS [%s]" % n) in p.stdout for n in IN_NAMES),
            "A6 被跳条目零执行痕迹、在册条目全执行", "stdout=%s" % p.stdout[-400:])

    # ---------------- B 形态（直跑面，恒跑）：缺省全跑 + 零新增键 ----------------
    p3 = F.run_executor(plain["lane"])
    i3 = F.integ_summary(p3.stdout)
    C.check(i3 is not None and "excluded_pools" not in i3 and "excluded_count" not in i3
            and i3.get("expected") == len(SPEC),
            "B4 缺省路径 INTEG_SUMMARY 零新增键且 expected=在册全量", "INTEG_SUMMARY=%s" % i3)
    C.check(F.named_exclude_line(p3.stdout, EXCLUDED_POOLS, N_OUT) is None,
            "B5 缺省路径无点名行（不假造排除面）", "stdout=%s" % p3.stdout[-300:])

    # ---------------- 契约面前置：闸的消费参数必须在工具 schema 声明 ----------------
    _key, _err = F.gate_apply_contract()
    C.check(_key is not None, "P0 闸消费参数已在 verify_lane TOOL schema 声明（契约面）", _err)

    if _key is not None:
        # ------------- A 形态②：经真闸（回执面） -------------
        g = F.call_gate(declared["lane"], apply=True, write_set=["server/engine/dev_lane.py"])
        r = g.get("result") or {}
        C.check(r.get("err") is None, "A7 真闸无 err（声明被真解析器接受）", _diag(g))
        C.check(r.get("ran") == len(IN_NAMES) and set(F.scenario_names(r)) == set(IN_NAMES),
                "A8 真闸 ran 与明细=本轮在册 %d，被跳条目零出现" % len(IN_NAMES), _diag(g))
        pe = r.get("pool_exclude") or {}
        C.check(pe.get("applied") is True, "A9 回执点名 applied=true（少跑必须点名到消费面）", _diag(g))
        C.check("engine" in str(pe.get("declared")) and "exclusive" in str(pe.get("declared")),
                "A10 回执 declared 携带声明池名", "pool_exclude=%s" % pe)

        # ------------- E 形态：声明在场 + 不传 apply → 恒全跑 -------------
        g2 = F.call_gate(declared["lane"])
        r2 = g2.get("result") or {}
        C.check(r2.get("err") is None, "E1 真闸无 err", _diag(g2))
        C.check(r2.get("ran") == len(SPEC) and set(F.scenario_names(r2)) == set(ALL_NAMES),
                "E2 不传 apply（巡检/手动/老回放形态）恒全跑 %d 条" % len(SPEC), _diag(g2))
        C.check(not (r2.get("pool_exclude") or {}).get("applied"),
                "E3 未 apply 时回执无生效排除面（开关不外溢）", "pool_exclude=%s" % r2.get("pool_exclude"))

        # ------------- B 形态（闸面）：声明缺省 + apply → 全跑 -------------
        g3 = F.call_gate(plain["lane"], apply=True)
        r3 = g3.get("result") or {}
        C.check(r3.get("err") is None and r3.get("ran") == len(SPEC)
                and set(F.scenario_names(r3)) == set(ALL_NAMES),
                "B1 无声明泳道 + apply → 全跑 %d 条（apply 单独不足以开开关）" % len(SPEC), _diag(g3))
        C.check(not (r3.get("pool_exclude") or {}).get("applied"),
                "B2 缺省路径回执无生效排除面", "pool_exclude=%s" % r3.get("pool_exclude"))
        C.check(r3.get("ran") == len(SPEC) and set(F.scenario_names(r3)) == set(ALL_NAMES),
                "B3 缺省路径明细=全量条目", _diag(g3))

sys.exit(C.finish())
