#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101123_faces_agree_on_range.py — t261011-23 「一把尺子，两个面」旅程面
（灰盒 L3，离线秒级）。

intent（用户可感知行为；真源=票面四性质 + KI-01M4N5ASATAVWP6E38NSPECCAT 回归行）：
一轮绿认证盖住的是「上一份认证之后长出来的整个区间」，不是一张票——等待面
（ticket_wait_state / landable）必须按同一条区间规则作答，且在两把尺子共用的
形状上与结局面（ticket_outcome.certified_by）给出同一个答案。宿主的实测事故：
t261009-80 的落地（非区间头）在线头前进后在等待面永远等不到，而结局面已读
certified——本条守的是这个事故不再以任何极性复现。

  A. 区间内的非头 landing（正是 t261009-80 的形状：L1、L2 两票落下，一轮绿
     认证盖住两票、候选=线头 revB）→ 等待面答 certified 且 covered_by 点名
     那份认证；landable=True（绿覆盖已证明内容）。
  B. 两面一致（性质 4，两把尺子共用的形状）：头的 landing 两面都答 certified
     且点名同一份认证；线头之后的新 landing 两面都答「未被覆盖」（等待 /
     certified_by=None）——没有假绿，两面说同一句话。
  C. 结局面为 certified ⇒ 等待面必答 certified（通用方向，任何实现下都必须
     成立——旧尺子与新区间尺在这里重合）。
  D. 遗留缺口按名钉住（fallback (b)，与本票登记的 residual 一致）：非头
     landing 在结局面今日读不到 certified_by（develop_promote 的 certified_by
     仍锚 per-repo 相等，写集扩展未授）——这个分歧只允许存在于这一类，别的
     任何 landing 出现分歧即红。
  E. 红不挟持（性质 2 不变）：L3 落进红认证区间 → red_implicated（不是
     certified 也不是 waiting），已覆盖的 L1/L2 不被翻案。

分层与 intent 分工（防重复）：
  · 四性质真值表、边界 seq、畸形输入、is_green 拒绝矩阵 → developer L1
    （server/engine/tests/test_t261011_23_range_coverage.py）；
  · 等待/冻结旅程、overdue、needs_slot、跨线隔离 → t261009-21（本条不复锁）；
  · 线轮 tick/守卫/红阶梯本体 → t261009-30/-41/-50；
  · 本条独占：非头 landing 的两面一致性旅程 + KI 回归的 L3 连贯回执。

安全红线：交付账本经 SANDBAR_DELIVERY_LEDGER_DIR 投到本场景私有临时目录
（真账零写入）；run 头夹具为进程内字典（run 头契约归 t261009-11 家族，
is_green 是公开注入的读面）；零 docker、零 Temporal、零端口、零控制台
（永不接触 3099）；临时目录 finally+atexit 双路回收。纯 stdlib 恒可跑。

实现面未落地 = FAIL 点名（TDD 红属预期，arbitrate/merge 必须绿）；
python3 缺失 = ENV_FAIL exit 2。
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261011-23-faces-agree-on-range"
DC = REPO / "server" / "engine" / "develop_certify.py"
DP = REPO / "server" / "engine" / "develop_promote.py"

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

_REV_A = "a" * 40   # L1（非头，t261009-80 形状）的修订
_REV_B = "b" * 40   # L2（区间头/线头）的修订
_REV_C = "c" * 40   # L3（认证之后落下的修订）
_AT = 1791600000000
_LINE = "develop-buffer"


def _repos(sha):
    return [{"repo": "sandbar", "revision": sha}]


def _landing(i, sha, at=None):
    return {"kind": "landing", "id": "ldg-t23-%04d" % i,
            "ticket": "t-fix-%d" % i, "line": _LINE, "repos": _repos(sha),
            "actor": "lane", "at": at if at is not None else _AT + i * 10}


def _run_header(rid):
    """进程内 run 头夹具：绿/红由 is_green 读面按 id 区分（run 头契约本身归
    t261009-11 家族，这里不复锁）。"""
    return {"id": rid, "repos": _repos(_REV_B), "suite": "full",
            "source": "lane:t261011-23", "conc_width": 1, "pool": "ro",
            "started_at": _AT, "duration_s": 1.0,
            "cases": {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0},
            "verdict": "green" if "green" in rid else "red"}


def _call(fn, *a, **k):
    try:
        return (None, None, fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, e, None)


def _outcome_certified_by(dp, rows, ticket, g):
    _, _, out = _call(dp.ticket_outcome, rows, ticket, g)
    if out is None:
        return None, None, "ticket_outcome raised"
    return out.get("certified_by"), out.get("certified_at"), None


# ---------------------------------------------------------------- 主程序

def main():
    global _TMP
    if not DC.is_file() or not DP.is_file():
        ok(False, "Z0 引擎模块在位",
           "not landed: %s / %s (TDD-phase red expected)" % (DC, DP))
        finish(NAME)
    tmp = Path(tempfile.mkdtemp(prefix="t261011-23-faces-"))
    _TMP = tmp
    dled = tmp / "delivery"
    dled.mkdir()
    os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = str(dled)

    sys.path.insert(0, str(REPO / "server" / "engine"))
    dc_exc, dc_e, dc = _call(__import__, "develop_certify")
    dp_exc, dp_e, dp = _call(__import__, "develop_promote")
    faces = ("ticket_wait_state", "landable", "build_certification",
             "append_rows", "read_rows", "derive_range")
    missing = [f for f in faces
               if dc_exc or not callable(getattr(dc, f, None))]
    # develop_promote 拖带引擎依赖（temporalio 经 agent_activities）——依赖缺失
    # 是环境红（ENV_FAIL exit 2），不是「未落地」的 FAIL。
    if dp_exc and isinstance(dp_e, ImportError):
        env_fail(NAME, "develop_promote unimportable (deps missing): %s" % dp_e)
    if missing or dp_exc:
        ok(False, "Z1 公共面在位",
           "develop_certify=%r/%r missing=%s; develop_promote=%r/%r "
           "(not landed, TDD-phase red expected)"
           % (dc_exc, dc_e, missing, dp_exc, dp_e))
        finish(NAME)

    led_path = dled / dc.MAIN_NAME
    green_run = _run_header("run-green-t23")

    # 真写入面：两票落账（L1 非头 + L2 线头），一轮绿认证盖住整个区间，
    # 候选=线头 revB——builder 的真实形状（candidate_set 取每仓 HEAD）。
    dc.append_rows([_landing(1, _REV_A), _landing(2, _REV_B)], led_path)
    cert = dc.build_certification(_repos(_REV_B), green_run, "inv-x",
                                  "integration-scenario", at_ms=_AT + 100,
                                  line=_LINE)
    dc.append_rows([cert], led_path)
    # L3 在认证之后落下（线头前进的那一刻——事故的触发点）。
    dc.append_rows([_landing(3, _REV_C, at=_AT + 200)], led_path)
    rows, bad = dc.read_rows(led_path)
    ok(not bad and len(rows) == 4,
       "A0 夹具经真账本写入/读回（2 landing + 绿认证 + 1 landing）",
       "n=%d bad=%r" % (len(rows), bad))
    by_id = {r["id"]: r for r in rows if r.get("id")}
    l1, l2, l3 = by_id["ldg-t23-0001"], by_id["ldg-t23-0002"], by_id["ldg-t23-0003"]
    g = lambda rid: rid == "run-green-t23"  # noqa: E731

    rng = dc.derive_range(rows, _LINE)
    ok("ldg-t23-0003" in {x["id"] for x in rng["covered_landings"]}
       and rng["covered_landings"] != [],
       "A1 线头前进后，认证之后的 L3 落进未判区间（事故的触发形状成立）",
       "covered=%r" % ([x["id"] for x in rng["covered_landings"]],))

    # ---------------- A 非头 landing 被绿区间盖住（性质 3 / KI 核心）--------
    w1, w1e, ws1 = _call(dc.ticket_wait_state, rows, _LINE, l1, g, _AT + 300)
    ok(w1e is None and ws1.get("state") == "certified"
       and ws1.get("covered_by") == cert["id"],
       "A2 非头 landing 答 certified 且点名覆盖它的认证——不再永远等"
       "（t261009-80 形状，性质 3）",
       "state=%r err=%r" % (ws1, w1e))
    ok(dc.landable(rows, _LINE, l1, is_green=g) is True,
       "A3 landable 对非头 landing 答真——绿覆盖已证明内容，不按精确相等锁死",
       "landable(L1)=%r" % (dc.landable(rows, _LINE, l1, is_green=g),))

    # ---------------- B 两面一致（性质 4，共用形状）-------------------------
    cb_head, _, cb_err = _outcome_certified_by(dp, rows, l2["ticket"], g)
    wh, whe, wsh = _call(dc.ticket_wait_state, rows, _LINE, l2, g, _AT + 300)
    ok(cb_err is None and whe is None
       and cb_head == cert["id"] and wsh.get("state") == "certified"
       and wsh.get("covered_by") == cert["id"],
       "B1 头的 landing：结局面与等待面给出同一个答案、同一份认证 id",
       "certified_by=%r wait=%r err=%r/%r" % (cb_head, wsh, cb_err, whe))
    cb_wait, _, cw_err = _outcome_certified_by(dp, rows, l3["ticket"], g)
    w3, w3e, ws3 = _call(dc.ticket_wait_state, rows, _LINE, l3, g, _AT + 300)
    ok(cw_err is None and w3e is None and cb_wait is None
       and ws3.get("state") == "waiting" and ws3.get("covered_by") is None,
       "B2 认证之后的新 landing：两面都说「还没被覆盖」——无假绿（性质 1）",
       "certified_by=%r wait=%r" % (cb_wait, ws3))

    # ---------------- C 通用一致方向：结局面 certified ⇒ 等待面 certified ---
    all_ok = True
    detail = []
    for ldg in (l1, l2, l3):
        cb, _, e = _outcome_certified_by(dp, rows, ldg["ticket"], g)
        _, _, st = _call(dc.ticket_wait_state, rows, _LINE, ldg, g, _AT + 300)
        if e or st is None:
            all_ok, _d = False, "outcome error for %s" % ldg["id"]
            detail.append(_d)
        elif cb is not None and st.get("state") != "certified":
            all_ok = False
            detail.append("%s: certified_by=%r but wait=%r"
                          % (ldg["id"], cb, st.get("state")))
    ok(all_ok,
       "C1 对线上每张落地：结局面答 certified ⇒ 等待面必答 certified"
       "（两面不许再说两套话）",
       "; ".join(detail))

    # ---------------- D 遗留缺口按名钉住（fallback (b) 的 residual）--------
    cb_nonhead, _, _ = _outcome_certified_by(dp, rows, l1["ticket"], g)
    ok(cb_nonhead is None,
       "D1 非头 landing 的结局面分歧仍按名在册（develop_promote 未进本票写集，"
       "KI-01M4N5ASATAVWP6E38NSPECCAT residual，fallback (b)）——"
       "分歧若扩大到头的 landing 由 B1/C1 判红",
       "certified_by(L1)=%r" % (cb_nonhead,))

    # ---------------- E 红不挟持（性质 2 不变）------------------------------
    red_run = _run_header("run-red-t23")
    red = dc.build_certification(_repos(_REV_C), red_run, "inv-x",
                                 "integration-scenario", at_ms=_AT + 250,
                                 line=_LINE)
    dc.append_rows([red], led_path)
    rows, bad = dc.read_rows(led_path)
    by_id = {r["id"]: r for r in rows if r.get("id")}
    l1, l2, l3 = by_id["ldg-t23-0001"], by_id["ldg-t23-0002"], by_id["ldg-t23-0003"]
    ok(not bad and len(rows) == 5, "E0 红认证落账", "n=%d bad=%r" % (len(rows), bad))
    w4, w4e, ws4 = _call(dc.ticket_wait_state, rows, _LINE, l3, g, _AT + 300)
    ok(w4e is None and ws4.get("state") == "red_implicated"
       and ws4.get("waiting_for") == red["id"],
       "E1 红区间里的 landing 答 red_implicated——不被新区间规则翻成别的脸"
       "（性质 2 不变）",
       "state=%r err=%r" % (ws4, w4e))
    w5, w5e, ws5 = _call(dc.ticket_wait_state, rows, _LINE, l1, g, _AT + 300)
    ok(w5e is None and ws5.get("state") == "certified",
       "E2 红认证不翻案已被绿区间覆盖的内容——冻住的是往后落，不是已证明的",
       "state=%r" % (ws5,))

    finish(NAME)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        _cleanup()
        raise
