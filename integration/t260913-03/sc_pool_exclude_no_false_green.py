#!/usr/bin/env python3
"""t260913-03 场景③：排除不得吞在册红，被跳池红不得计成通过（红线对抗子用例，真闸，灰盒 L2）。

intent（用户可感知）：红线的机械面——「不得以少跑冒充通过」。
  ①在册条目红 + 被跳池条目红 → 闸必须红，且红名单点名**在册**那条；
    被跳池那条既不出现在明细、也不得被计成 pass（它不在本轮在册）；
  ②只有被跳池条目红 → 本轮不判它（交给每日巡检），但**必须点名**「少 N 条」，
    且汇总把排除数如实写在案（缩围可见，不是静默通过）。
  intent 与 developer 的 L1 电池不同面：彼测计数/退出码形状，本条测「红面的诚实性 + 缩围可见性」。

high-level steps：造两条最小真泳道（一条在册红+被跳红、一条仅被跳红）——
  先直跑执行器断言点名行与汇总键（不依赖闸，先跑）；再经真闸 apply 断言红名单归属与在册计数。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_pool_exclude_lane as F  # noqa: E402

C = F.Checker("t260913-03-scenario-3-no-false-green")

MIXED = [
    ("mini-ro-ok", "ro", True),
    ("mini-ro-bad", "ro", False),          # 在册红（必须拦）
    ("mini-engine-ok", "engine", True),
    ("mini-engine-bad", "engine", False),  # 被跳池红（本轮不判，但必须点名排除数）
]
ONLY_EXCLUDED_RED = [
    ("mini-ro-ok", "ro", True),
    ("mini-ro-ok2", "ro", True),
    ("mini-engine-bad", "engine", False),
]
OUT_COUNT_MIXED = 2
OUT_COUNT_SECOND = 1
DISJOINT_WS = ["server/engine/dev_lane.py"]


with F.tmpdir() as td:
    lane1 = F.build_lane(td / "mixed", MIXED)["lane"]
    lane2 = F.build_lane(td / "only-excluded", ONLY_EXCLUDED_RED)["lane"]

    # ---------------- 直跑面（不依赖闸，先跑）：红态也必须点名 ----------------
    p1 = F.run_executor(lane1, env={"SANDBAR_SCENARIO_EXCLUDE_POOLS": F.EXCLUDE_VALUE})
    i1 = F.integ_summary(p1.stdout)
    counts1 = F.summary_counts(p1.stdout)
    C.check(bool(F.named_exclude_line(p1.stdout, ("engine", "exclusive"), OUT_COUNT_MIXED)),
            "G5 红态仍点名「少 %d 条」" % OUT_COUNT_MIXED,
            "stdout=%s" % p1.stdout[-300:])
    C.check(counts1 is not None and counts1["ran"] == 2 and counts1["fail"] == 1
            and i1 is not None and i1.get("excluded_count") == OUT_COUNT_MIXED
            and i1.get("expected") == 2,
            "G6 红态汇总：ran/expected=在册 2、fail=1、排除数如实",
            "counts=%s SUM=%s" % (counts1, i1))

    p2 = F.run_executor(lane2, env={"SANDBAR_SCENARIO_EXCLUDE_POOLS": F.EXCLUDE_VALUE})
    i2 = F.integ_summary(p2.stdout)
    C.check(bool(F.named_exclude_line(p2.stdout, ("engine", "exclusive"), OUT_COUNT_SECOND))
            and i2 is not None and i2.get("excluded_count") == OUT_COUNT_SECOND,
            "G9 缩围可见：点名「少 %d 条」+ 汇总排除数在案（不是静默通过）" % OUT_COUNT_SECOND,
            "INTEG_SUMMARY=%s" % i2)
    C.check(i2 is not None and i2.get("fail") == 0 and i2.get("pass") == 2,
            "G10 被跳池红既不计 fail 也不计 pass（不在本轮在册数）", "INTEG_SUMMARY=%s" % i2)

    # ---------------- 契约面前置：闸的消费参数必须在工具 schema 声明 ----------------
    _key, _err = F.gate_apply_contract()
    C.check(_key is not None, "P0 闸消费参数已在 verify_lane TOOL schema 声明（契约面）", _err)

    if _key is not None:
        # ------------- ①在册红不被吞 + 被跳红不计成通过 -------------
        g1 = F.call_gate(lane1, apply=True, write_set=DISJOINT_WS)
        r1 = g1.get("result") or {}
        C.check(r1.get("err") is None, "G1 真闸无 err", "err=%s" % r1.get("err"))
        C.check(r1.get("fail") == 1 and "mini-ro-bad" in F.blockers_of(r1),
                "G2 在册红被拦且红名单点名在册条目 mini-ro-bad（少跑不吞红）",
                "fail=%s blockers=%s green=%s" % (r1.get("fail"), F.blockers_of(r1), r1.get("green")))
        C.check("mini-engine-bad" not in F.case_names(r1)
                and "mini-engine-bad" not in F.scenario_names(r1)
                and "mini-engine-bad" not in F.blockers_of(r1),
                "G3 被跳池红不在本轮明细/红名单（不被计成 pass，也不冒充失败）",
                "cases=%s" % F.case_names(r1))
        C.check(r1.get("ran") == 2, "G4 ran=本轮在册 2（排除数不掺进 ran）", "ran=%s" % r1.get("ran"))

        # ------------- ②只有被跳池红：本轮判定面不含它，但缩围必须可见 -------------
        g2 = F.call_gate(lane2, apply=True, write_set=DISJOINT_WS)
        r2 = g2.get("result") or {}
        C.check(r2.get("err") is None and r2.get("fail") == 0 and r2.get("env_fail") == 0
                and not F.blockers_of(r2),
                "G7 被跳池红不进本轮红面（本轮判定面=在册）",
                "fail=%s env_fail=%s blockers=%s green=%s" % (r2.get("fail"), r2.get("env_fail"),
                                                              F.blockers_of(r2), r2.get("green")))
        C.check(r2.get("ran") == 2 and "mini-engine-bad" not in F.scenario_names(r2),
                "G8 被跳池红零执行痕迹且 ran=在册 2",
                "ran=%s names=%s" % (r2.get("ran"), F.scenario_names(r2)))

sys.exit(C.finish())
