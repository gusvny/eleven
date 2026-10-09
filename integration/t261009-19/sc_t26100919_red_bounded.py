#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100919_red_bounded.py —— t261009-19 红的定界与可用性面（灰盒 L3，离线秒级）。

intent（用户可感知行为；真源=票面 (c)(d)(e) + docs/design/develop-buffer-v1.md
goals 9/10/24）：buffer 红了，代价有界、归属诚实、冻结只咬内容红——
  R. 定界阶梯按序走（next_red_action 一步一步答）：
     第一步 同一候选修订先重跑一次——没重跑过 ⇒ 答案是 ('rerun', None)，搜索
       范围这一步根本不会被指到（便宜的 flake 判别器先走）；
     第二步 各泳道自己的场景结果做免费第一滤——重跑仍红后，唯一命中的那条
       landing ⇒ ('isolated', 那条)，范围搜索仍零消耗；
     第三步 范围只剩一条 landing 时算术即可孤立即 isolated；多 landing 且滤
       不窄 ⇒ ('search', landings)，搜完把 range_key 记成 searched 变更行；
       已搜过的范围再遇同键 ⇒ AlreadySearchedError 按名拒（goal 10：搜过的
       范围绝不搜第二遍）；
     边界诚实：搜不窄时的诚实答案就是 BOUNDARY_VALUE 原文「boundary, culprit
       not isolated」——这句话必须说得出口、可落账（attribution 变更行的 value）。
  F. 冻结只咬内容红：点名 landing 的红 ⇒ 冻结 episode（id/line/cause 指向
     认证），本体上没有 state/culprit/closure——它们是 keyed 变更行，不是
     可改字段（d）；should_freeze 只在归属真实点名内容时为真。
  E. 跑不成 ≠ 红：run 头缺席/没跑任何东西 ⇒ CouldNotRun 按名，不是红；
     could_not_run_row 落范围涨大记录（下一轮认证的活多了，且被记录），
     不开冻结、线照常干活（goal 24 / (e)）。
  M. 畸形输入响亮：red_cert 不是认证、lane_reds 垃圾形状 ⇒ CertifyError
     按名；复述 verdict 的认证行 append 按名拒（绝不静默绿）。

分层与 intent 分工（防重复）：
  · 阶梯/守卫/派生全量真值表与单元角 → developer L1
    （integration/tests/test_t261009_19_certify.py），本场景只锁旅程面；
  · 认证旅程（每 tick 一次/引用不复述/范围推导/前缀可落）→ 同票
    sc_t26100919_certify_once.py（L3）；
  · 失败分类词表与采信边界 → failure-classification-protocol-v1 家族，正交。

安全红线：交付账目录经 SANDBAR_DELIVERY_LEDGER_DIR 与显式 path 双路投到
私有临时目录（真账零写入）；零 docker、零 Temporal、零端口、零控制台
（永不接触 3099）；临时目录 finally+atexit 双路回收。纯 stdlib 恒可跑。

实现面未落地 = FAIL 点名（TDD 红属预期，arbitrate/merge 必须绿）；
python3 缺失 = ENV_FAIL exit 2。
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261009-19-red-bounded"
MODULE = REPO / "server" / "engine" / "develop_certify.py"

sys.path.insert(0, str(REPO / "integration"))
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

_TMP = None
_RECLAIMED = False


def _cleanup():
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)


# ---------------------------------------------------------------- 夹具

_SHA = {i: ("%s%d" % ("a" * 38, i)).ljust(40, "0") for i in range(1, 5)}
_FP = "b" * 64
_LINE = "main"
_AT = 1791506200000


def _repos(sha):
    return [{"repo": "sandbar", "revision": sha}]


def _landing(i, seq):
    return {"kind": "landing", "id": "ldg-%04d" % i, "ticket": "t-x-%d" % i,
            "line": _LINE, "repos": _repos(_SHA[i]), "actor": "lane",
            "at": _AT, "seq": seq}


def _cert(i, seq, sha, run="run-" + "0" * 26, at=None):
    return {"kind": "certification", "id": "cert-%04d" % i, "line": _LINE,
            "repos": _repos(sha), "run": run, "booked_red": "inv-x",
            "judged_by": "integration-scenario",
            "at": at or (_AT + i * 100), "seq": seq}


class _Line:
    def candidate(self):
        return {"sandbar": _SHA[1]}


class _RunReader:
    def __init__(self, header):
        self._header = header

    def header(self, run_id):
        return self._header


def _call(fn, *a, **k):
    try:
        return (None, None, fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, e, None)


# ---------------------------------------------------------------- 主程序

def main():
    global _TMP
    tmp = Path(tempfile.mkdtemp(prefix="t261009-19-red-"))
    _TMP = tmp
    dled = tmp / "delivery"
    dled.mkdir()
    os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = str(dled)

    if not MODULE.is_file():
        ok(False, "Z0 认证模块在位",
           "not landed: %s missing (TDD-phase red expected)" % MODULE)
        finish(NAME)

    sys.path.insert(0, str(REPO / "server" / "engine"))
    exc, e, dc = _call(__import__, "develop_certify")
    if exc or not (dc and callable(getattr(dc, "next_red_action", None))):
        ok(False, "Z1 develop_certify 阶梯面在位",
           "%s: %s / not landed (TDD-phase red expected)" % (exc, e))
        finish(NAME)

    led_path = dled / dc.MAIN_NAME
    landings = [_landing(1, 1), _landing(2, 2), _landing(3, 3)]

    # ---------------- R 定界阶梯 ----------------
    def _fmt(act):
        return (act[0], [x.get("id") for x in act[1]]
                if isinstance(act[1], list)
                else (act[1].get("id") if act[1] else None))

    red = _cert(10, 10, _SHA[1])
    rows = landings + [red]
    act = dc.next_red_action(rows, _LINE, red, None)
    ok(act == ("rerun", None),
       "R1 红后无同候选重跑 ⇒ 答案是先重跑（flake 判别器先于任何搜索）",
       "act=%r" % (act,))
    rerun = dict(red)
    rerun.update({"id": "cert-0011", "seq": 11, "run": "run-" + "1" * 26,
                  "at": red["at"] + 100})
    rows_rr = rows + [rerun]
    act = dc.next_red_action(rows_rr, _LINE, red, ["ldg-0001"])
    ok(act[0] == "isolated" and act[1]["id"] == "ldg-0001",
       "R2 泳道结果唯一命中 ⇒ 免费第一滤直接点名（搜索零消耗）",
       "act=%r" % (_fmt(act),))
    solo = [_landing(2, 2)]
    solo_red = _cert(12, 3, _SHA[2])
    rows_solo = solo + [solo_red, dict(solo_red, id="cert-0013", seq=4,
                                       run="run-" + "2" * 26,
                                       at=solo_red["at"] + 100)]
    act = dc.next_red_action(rows_solo, _LINE, solo_red, None)
    ok(act[0] == "isolated" and act[1]["id"] == "ldg-0002",
       "R3 重跑已做、范围只剩一条 landing ⇒ 算术孤立即 isolated",
       "act=%r" % (_fmt(act),))
    multi = [_landing(2, 2), _landing(3, 3)]
    red_m = _cert(14, 14, _SHA[3])
    rows_m = multi + [red_m, dict(red_m, id="cert-0015", seq=15,
                                  run="run-" + "3" * 26, at=red_m["at"] + 100)]
    act = dc.next_red_action(rows_m, _LINE, red_m, None)
    ok(act == ("search", multi),
       "R4 重跑仍红、滤不出、范围多条 ⇒ 才轮到搜索（第三级真的会走）",
       "act=%r" % (_fmt(act),))
    key = dc.range_key(["ldg-0003", "ldg-0002"])
    ok(key == "ldg-0002,ldg-0003",
       "R6 range_key 规范化（排序拼接——键与书写顺序无关）", "key=%r" % (key,))
    searched_row = dc.freeze_change_row(
        "frz-" + "0" * 26, "searched", "integration-scenario",
        "range search executed", value=key, at_ms=_AT + 500, line=_LINE)
    searched_row["seq"] = 20
    rows_s = rows_m + [searched_row]
    exc, e, _ = _call(dc.next_red_action, rows_s, _LINE, red_m, None)
    ok(exc == "AlreadySearchedError" and "already_searched" in str(e),
       "R7 已搜过的范围再遇同键 ⇒ AlreadySearchedError 按名拒（goal 10）",
       "%s: %s" % (exc, e))
    ok(dc.BOUNDARY_VALUE == "boundary, culprit not isolated",
       "R8 边界那句诚实原文存在且可落账（attribution 变更行 value）",
       "BOUNDARY_VALUE=%r" % dc.BOUNDARY_VALUE)
    attr = dc.freeze_change_row("frz-" + "0" * 26, "attribution",
                                "integration-scenario", "search exhausted",
                                value=dc.BOUNDARY_VALUE, at_ms=_AT + 600,
                                line=_LINE)
    clean, why = dc.validate_row(attr)
    ok(clean is not None and not why,
       "R9 boundary 归属作为变更行过校验（真相可入账，不必编元凶）",
       "why=%r" % (why,))

    # ---------------- F 冻结只咬内容红 ----------------
    ep = dc.open_freeze_rows(red_m, at_ms=_AT + 400)[0]
    ok(str(ep.get("id", "")).startswith("frz-") and ep.get("line") == _LINE
       and ep.get("cause") == red_m["id"],
       "F1 点名内容红的认证 ⇒ 冻结 episode，cause 指向那份认证",
       "ep=%r" % (ep,))
    banned = [k for k in ("state", "closure", "culprit", "landings",
                          "resolved", "attributed") if k in ep]
    ok(not banned,
       "F2 状态/元凶/闭合不在 episode 本体上（keyed 变更行，非可改字段）",
       "banned=%s" % banned)
    ok(dc.should_freeze("isolated:ldg-0002") is True
       and dc.should_freeze(None) is False,
       "F3 冻结判据=归属真实点名内容；无归属不冻结",
       "true-for-isolated / false-for-none")

    # ---------------- E 跑不成 ≠ 红 ----------------
    exc, e, _ = _call(dc.build_certification, _repos(_SHA[1]), None,
                      "inv-x", "integration-scenario", at_ms=_AT)
    ok(exc == "CouldNotRun" and "header" in str(e).lower(),
       "E1 run 头缺席（中断的一轮）⇒ CouldNotRun 按名，绝不冒充红",
       "%s: %s" % (exc, e))
    empty = {"id": "run-" + "9" * 26, "cases": {"ran": 0, "passed": 0,
                                                "failed": 0, "env_failed": 0},
             "verdict": "green"}
    exc, e, _ = _call(dc.build_certification, _repos(_SHA[1]), empty,
                      "inv-x", "integration-scenario", at_ms=_AT)
    ok(exc == "CouldNotRun" and "nothing" in str(e),
       "E2 什么都没跑的绿 ⇒ CouldNotRun（ran:0 永非证明）",
       "%s: %s" % (exc, e))
    growth = dc.could_not_run_row(_LINE, "env:runner dead", at_ms=_AT + 700)
    ok(growth.get("kind") == "range_growth" and growth.get("reason"),
       "E3 跑不成落范围涨大记录（下一轮认证的活多了，且被记录）",
       json.dumps(growth)[:200])
    clean, why = dc.validate_row(growth)
    ok(clean is not None and not why, "E4 涨大记录过校验可入账",
       "why=%r" % (why,))
    dc.append_rows([growth], led_path)
    rows_g, bad_g = dc.read_rows(led_path)
    ok(not bad_g and any(r.get("kind") == "range_growth" for r in rows_g)
       and not any(r.get("kind") == "freeze" for r in rows_g),
       "E5 缺勤入账但零冻结行：线照常干活（跑不成不咬住线）",
       "kinds=%s" % sorted({r.get("kind") for r in rows_g}))

    # ---------------- M 畸形输入响亮 ----------------
    exc, e, _ = _call(dc.next_red_action, rows_rr, _LINE, {"kind": "landing"},
                      None)
    ok(exc == "CertifyError" and "certification" in str(e),
       "M1 red_cert 不是认证 ⇒ CertifyError 按名（绝不静默走阶梯）",
       "%s: %s" % (exc, e))
    exc, e, _ = _call(dc.next_red_action, rows_rr, _LINE, red, [42])
    ok(exc == "CertifyError" and "lane_reds" in str(e),
       "M2 lane_reds 垃圾形状 ⇒ CertifyError 按名（免费滤不猜）",
       "%s: %s" % (exc, e))
    thief = dict(red_m)
    thief["verdict"] = "red"
    clean, why = dc.validate_row(thief)
    ok(clean is None and "restates" in why,
       "M3 认证行复述 verdict ⇒ 校验按名拒（引用而不复述是 schema 级）",
       "why=%r" % (why,))

    finish(NAME)


if __name__ == "__main__":
    try:
        main()
    finally:
        _cleanup()
