#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100921_waiting_freeze.py —— t261009-21 等待与冻结的旅程面（灰盒 L3，离线秒级）。

intent（用户可感知行为；真源=票面 (a)(b)(c)(d) + docs/design/develop-buffer-v1.md
goals 8/14/15/16/17）：一张只在等的票手里什么都没占，红也绝不挟持已被证明的部分——
  A. 已认证前缀恒可落（goal 8 / 票面 (b)）：三张票落账，第三张被红认证点名，
     冻结开着；前两张（被绿认证盖住的内容）仍答「可落」，第三张不答——
     红把线冻住，冻的是「往后落」，不是「已证明的往前推」。
  B. 等待可见、有时刻、有着落（goal 14/16 / 票面 (c)）：票面上「waiting」与
     「red_implicated / certified」长得不一样；waiting_since 来自 landing 的
     at（记录序，不靠时钟赛跑）；等过声明的 bound 会被点名（overdue），
     不是被默默忍下。
  C. 等待不是工作（goal 14/15 / 票面 (a)）：已落账的票任何一张脸都不占并发位
     ——若等待占位，一个 tick 就钉死整个机队，这正是本设计要拆的堵点；
     调度器不认识的脸被点名拒绝，绝不默认进（或出）容量。结构豁免
     （goal 16/17）：冻结线上只有 fix 类工作可落，这是「工作怎么开的」
     这条记录事实，不是票能自己给自己打的标。
  D. 肇事范围是推导出来的（票面 (d)）：红点名的是「本线上一份认证之后落下的
     landing」，从记录序算——绝不写进 landing 行的字段，也绝不被夹在共享
     seq 空间里的另一条线的 landing 撑大。

分层与 intent 分工（防重复）：
  · 真值表/畸形输入矩阵全量 → developer L1（integration/tests/test_t261009_21_certify.py）；
  · 认证每 tick 至多一次/引用不复述 → t261009-19-certify-once；
  · 红的定界阶梯本体 → t261009-19-red-bounded，本条只消费一份红认证 + 一份
    attribution 变更行作冻结夹具，不重锁阶梯；
  · run 头契约 → t261009-11 家族，本条只经真实 scenario_ledger 造绿/红各一
    份真 run 头作被引 run。

安全红线：交付账本经 SANDBAR_DELIVERY_LEDGER_DIR 投到本场景私有临时目录
（真账零写入）；run 头经真实 scenario_ledger 写进临时 SANDBAR_SCENARIO_LEDGER_DIR；
零 docker、零 Temporal、零端口、零控制台（永不接触 3099）；临时目录
finally+atexit 双路回收。纯 stdlib 恒可跑。

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
NAME = "t261009-21-waiting-freeze"
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

_C = "c" * 40   # 已认证前缀的修订
_D = "d" * 40   # 被红点名的第三张票的修订
_FP = "b" * 64
_AT = 1791506300000
_LINE = "main"


def _repos(sha):
    return [{"repo": "sandbar", "revision": sha}]


def _landing(i, sha, line=_LINE, at=None):
    return {"kind": "landing", "id": "ldg-%04d" % i, "ticket": "t-x-%d" % i,
            "line": line, "repos": _repos(sha),
            "actor": "lane", "at": at if at is not None else _AT + i * 10}


import scenario_ledger as _sl_mod  # noqa: E402  (schema version for fakes)


def sl_run_v():
    return _sl_mod.RUN_HEADER_V


def _run_header(rid, verdict, at):
    failed = 0 if verdict == "green" else 2
    return {"v": sl_run_v(), "id": rid, "repos": _repos(_C), "suite": "full",
            "source": "lane:t261009-21", "env_fp": _FP, "conc_width": 1,
            "pool": "ro", "started_at": at, "duration_s": 1.5,
            "cases": {"ran": 2, "passed": 2 - failed, "failed": failed,
                      "env_failed": 0},
            "verdict": verdict}


def _call(fn, *a, **k):
    try:
        return (None, None, fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, e, None)


# ---------------------------------------------------------------- 主程序

def main():
    global _TMP
    tmp = Path(tempfile.mkdtemp(prefix="t261009-21-wait-"))
    _TMP = tmp
    dled = tmp / "delivery"
    dled.mkdir()
    os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = str(dled)
    sled = tmp / "runs"
    sled.mkdir()
    os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = str(sled)

    if not MODULE.is_file():
        ok(False, "Z0 认证模块在位",
           "not landed: %s missing (TDD-phase red expected)" % MODULE)
        finish(NAME)

    sys.path.insert(0, str(REPO / "server" / "engine"))
    exc, e, dc = _call(__import__, "develop_certify")
    faces = ("ticket_wait_state", "needs_slot", "may_land", "freeze_state",
             "landable", "derive_range", "build_certification",
             "open_freeze_rows", "freeze_change_row")
    missing = [f for f in faces
               if exc or not callable(getattr(dc, f, None))]
    if missing:
        ok(False, "Z1 等待/冻结公共面在位",
           "%s: %s / missing=%s (not landed, TDD-phase red expected)"
           % (exc, e, missing))
        finish(NAME)

    import scenario_ledger as sl  # noqa: E402
    led_path = dled / dc.MAIN_NAME

    # 真 run 头：绿/红各一份，经真实 scenario_ledger 写进临时目录
    # （t261009-11 契约），认证引用它们而不是复述它们。
    runs = {}
    for rid, verdict, at in (("run-green", "green", _AT + 90),
                             ("run-red", "red", _AT + 290)):
        sl.append_records(
            [{"ts": "2026-10-09T00:00:00+00:00", "commit": _C, "env_fp": _FP,
              "conc_width": 1, "pool": "ro", "scenario": "c%d" % i,
              "verdict": "pass" if verdict == "green" else "fail",
              "wall_s": 0.01, "source": "baseline", "ticket": "",
              "run": rid} for i in range(2)],
            path=sled / "scenario-results.jsonl")
        rec = sl.append_run_header(_run_header(rid, verdict, at))
        if rec.get("written", 0) != 1 or rec.get("rejected"):
            ok(False, "Z2 真 run 头夹具落盘（%s）" % rid,
               "written=%s rejected=%r" % (rec.get("written"),
                                           rec.get("rejected")))
            finish(NAME)
        runs[rid] = sl.rows_for_run(rid)["header"]

    green = dc.build_certification(_repos(_C), runs["run-green"], "inv-x",
                                   "integration-scenario", at_ms=_AT + 100,
                                   line=_LINE)
    red = dc.build_certification(_repos(_D), runs["run-red"], "inv-x",
                                 "integration-scenario", at_ms=_AT + 300,
                                 line=_LINE)

    # ---------------- A 已认证前缀恒可落；D 推导不存储 ----------------
    dc.append_rows([_landing(1, _C), _landing(2, _C)], led_path)
    dc.append_rows([green], led_path)
    dc.append_rows([_landing(3, _D),
                    # (d)：另一条线的 landing 夹在共享 seq 空间里
                    _landing(4, "e" * 40, line="other")], led_path)
    dc.append_rows([red], led_path)
    rows, bad = dc.read_rows(led_path)
    ok(not bad and len(rows) == 6, "A0 夹具落账（4 landing + 绿/红认证各 1）",
       "n=%d bad=%r" % (len(rows), bad))
    by_id = {r["id"]: r for r in rows if r.get("id")}
    g = lambda r: r == "run-green"  # noqa: E731

    ok(dc.landable(rows, _LINE, by_id["ldg-0001"], is_green=g) is True
       and dc.landable(rows, _LINE, by_id["ldg-0002"], is_green=g) is True,
       "A1 冻结线下，绿认证盖住的前两张仍答「可落」（goal 8：红不挟持已证明内容）",
       "landable(L1,L2)=(True,True)")
    ok(dc.landable(rows, _LINE, by_id["ldg-0003"], is_green=g) is False,
       "A2 被红点名的第三张不答「可落」（证明不可假装）", "landable(L3)=False")

    ep = dc.open_freeze_rows(red, at_ms=_AT + 400)[0]
    dc.append_rows([ep,
                    dc.freeze_change_row(ep["id"], "attribution", "ladder",
                                         "unique lane red",
                                         value="isolated:ldg-0003",
                                         at_ms=_AT + 410, line=_LINE)], led_path)
    rows, _ = dc.read_rows(led_path)
    st, serr, s = _call(dc.freeze_state, rows, _LINE)
    ok(serr is None and s.get("frozen") is True and s.get("cause") == red["id"]
       and s.get("culprit") == "isolated:ldg-0003",
       "A3 冻结态从记录答出：frozen、cause=红认证、culprit=归属句原文",
       "state=%r err=%r" % (s, serr))

    rng_other = dc.derive_range(rows, "other")
    ok(json_ids(rng_other["covered_landings"]) <= {"ldg-0004"},
       "D1 邻线自己的覆盖只含自己的 landing——反方向也绝不越线",
       "other=%r" % (json_ids(rng_other["covered_landings"]),))
    rng_main = dc.derive_range(rows, _LINE)
    ok("ldg-0004" not in json_ids(rng_main["covered_landings"]),
       "D2 主线的覆盖不被夹在中间的邻线 landing 撑大（票面 (d)）",
       "main=%r" % (json_ids(rng_main["covered_landings"]),))
    ok(all(not any(k in l for k in ("culprit", "range", "wait", "waiting_since",
                                    "state"))
           for l in rows if l.get("kind") == "landing"),
       "D3 任何 landing 行都不带肇事/范围/等待字段——全是推导，不是存储",
       "landing keys clean")

    # ---------------- B 等待可见、有时刻、有着落；C 等待不占位 ----------------
    w1, w1e, ws = _call(dc.ticket_wait_state, rows, _LINE, by_id["ldg-0003"],
                        g, _AT + 500)
    ok(w1e is None and ws.get("state") == "red_implicated",
       "B1 被红点名的票答 red_implicated，不答 waiting（三张脸不混）",
       "state=%r err=%r" % (ws, w1e))
    covered, _ce, cs = _call(dc.ticket_wait_state, rows, _LINE,
                             by_id["ldg-0001"], g, _AT + 500)
    ok(_ce is None and cs.get("state") == "certified"
       and cs.get("covered_by") == green["id"],
       "B2 被绿认证盖住的票答 certified 并点名是哪份认证盖的（已到站，不是在等）",
       "state=%r" % (cs,))

    # 未被任何认证盖住的 landing：waiting，且带时刻与等着谁
    dc.append_rows([_landing(5, "f" * 40, at=_AT + 450)], led_path)
    rows, _ = dc.read_rows(led_path)
    by_id = {r["id"]: r for r in rows if r.get("id")}
    w2, w2e, wt = _call(dc.ticket_wait_state, rows, _LINE, by_id["ldg-0005"],
                        g, _AT + 500)
    ok(w2e is None and wt.get("state") == "waiting"
       and wt.get("waiting_since") == by_id["ldg-0005"]["at"],
       "B3 没等到覆盖认证的票答 waiting，waiting_since=landing 的 at（记录序）",
       "state=%r err=%r" % (wt, w2e))
    ok(w2e is None and wt.get("waiting_for") == red["id"],
       "B4 票面有 waiting_for（排队 behind 线上最新一份认证——不猜、不空说）",
       "waiting_for=%r" % (wt.get("waiting_for"),))
    w3, _, w3s = _call(dc.ticket_wait_state, rows, _LINE, by_id["ldg-0005"],
                       g, _AT + 450 + 1000, wait_bound_ms=1000)
    w4, _, w4s = _call(dc.ticket_wait_state, rows, _LINE, by_id["ldg-0005"],
                       g, _AT + 450 + 999, wait_bound_ms=1000)
    ok(w3s.get("overdue") is True and w4s.get("overdue") is False,
       "B5 等过声明 bound 的等待被点名（overdue=True），没过就不点名——"
       "不被默默忍下（票面 (c)）",
       "overdue=(%r,%r)" % (w3s.get("overdue"), w4s.get("overdue")))

    # ---------------- C 等待不是工作；冻结里只有 fix 可落 ----------------
    ok(dc.needs_slot(wt) is False and dc.needs_slot(ws) is False
       and dc.needs_slot(cs) is False,
       "C1 已落账的票任何一张脸都不占并发位（goal 14/15：一个 tick 不钉死机队）",
       "needs_slot=(False,False,False)")
    unk, unke, _ = _call(dc.needs_slot, {"state": "working"})
    ok(unk == "CertifyError",
       "C2 调度器不认识的脸被点名拒绝——绝不默认进（或出）容量",
       "err=%s" % (unk,))

    mf1e, _, m_fix = _call(dc.may_land, rows, _LINE, dc.FREEZE_EXEMPT_KIND)
    mc1e, _, m_chore = _call(dc.may_land, rows, _LINE, "chore")
    ok(mf1e is None and m_fix is True,
       "C3 冻结线上，结构豁免的 fix 类工作可落（goal 16：豁免否则死锁）",
       "may_land(fix)=%r err=%r" % (m_fix, mf1e))
    ok(mc1e is None and m_chore is False,
       "C4 冻结线上，其它类工作不落（landings stop）", "may_land(chore)=False")
    mo1e, _, m_open = _call(dc.may_land, [], _LINE, "chore")
    ok(mo1e is None and m_open is True,
       "C5 线没冻时任何类都可落（冻的是红线，不是常态）",
       "may_land(unfrozen)=%r" % (m_open,))
    self_made = _call(dc.may_land, rows, _LINE, "self-declared-exempt")
    ok(self_made[0] == "CertifyError",
       "C6 未知工作类被点名拒绝——豁免是记录事实，不是票能自己打的标（goal 17）",
       "err=%s" % (self_made[0],))

    # ---------------- M 畸形输入点名失败（旅程位抽查，全量在 L1） --------
    bad_shape = _call(dc.ticket_wait_state, rows, _LINE, "not-a-dict", g,
                      _AT + 500)
    ok(bad_shape[0] == "CertifyError",
       "M1 非 landing 形状点名拒绝，绝不猜成 waiting", "err=%s" % (bad_shape[0],))
    no_inj = _call(dc.ticket_wait_state, rows, _LINE, by_id["ldg-0005"], None,
                   _AT + 500)
    ok(no_inj[0] == "CertifyError",
       "M2 线上有认证而不注入 is_green 的调用者被点名拒绝——"
       "绝不默认每份认证都绿（假绿是本设计明令禁止的证明）",
       "err=%s" % (no_inj[0],))

    finish(NAME)


def json_ids(landings):
    out = set()
    for l in landings:
        out.add(l["id"] if isinstance(l, dict) else str(l))
    return out


if __name__ == "__main__":
    try:
        main()
    finally:
        _cleanup()
