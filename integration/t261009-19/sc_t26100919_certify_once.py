#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100919_certify_once.py —— t261009-19 认证步骤的旅程面（灰盒 L3，离线秒级）。

intent（用户可感知行为；真源=票面 (a)(b)(d) + docs/design/develop-buffer-v1.md
goals 6/7/8）：buffer 线上的重证明每个调度 tick 至多跑一次，落一份引用 run 的
认证记录；「这张能不能落」从此由记录回答，不靠人的记忆——
  A. 每 tick 至多一次：变更触发且守卫空闲 → 判认证；守卫被持（in flight）
     ⇒ 一律不判；guard_acquire 第二次拿不到令牌（at most once per tick）。
  B. 引用而不复述：认证记录带候选修订集（repo→revision 列表，今天一个成员）、
     所引 run id、当时生效的 expected-red 库存版本（booked_red）、judged_by、
     时刻；记录本体没有 counts/verdict——而且 restating 是 schema 违例，
     append 按名拒（record models §A；票面 (a) 原文）。
  C. 覆盖范围从记录序推导：认证覆盖「上一次认证之后落下的 landing」（seq 严格
     大于）；更早的 landing 不在覆盖内；landing 与认证 seq 相同时不覆盖
     （序定界，不靠时钟赛跑）；stored covered_range 只是投影、derive_range
     是唯一权威（(b)：范围 DERIVED，绝不 stored on the landing）。
  D. 最大已认证前缀恒可落：线上红了（后面挂着红认证），已被绿认证盖住的
     landing 仍答「可落」——红绝不拿已证明内容当人质（goal 8 / (d)）。

分层与 intent 分工（防重复）：
  · 纯函数真值表/守卫令牌单元细节/畸形矩阵全量 → developer L1
    （integration/tests/test_t261009_19_certify.py），本场景只锁旅程面；
  · 红的定界阶梯、冻结面、could-not-run → 同票 sc_t26100919_red_bounded.py；
  · hatch 的认证债清除 → t261009-13 家族；run 记录库面 → t261009-11 家族，
    本条只消费一个真绿头作被引 run。

安全红线：交付账目录经 SANDBAR_DELIVERY_LEDGER_DIR 与显式 path 双路投到
本场景私有临时目录（真账零写入）；run 头经真实 scenario_ledger 写进临时
SANDBAR_SCENARIO_LEDGER_DIR；零 docker、零 Temporal、零端口、零控制台
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
NAME = "t261009-19-certify-once"
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

_C = "a" * 40
_B = "b" * 40
_FP = "b" * 64
_LINE = "main"


def _repos(sha):
    return [{"repo": "sandbar", "revision": sha}]


def _landing(i, sha, at=1791506200000):
    return {"kind": "landing", "id": "ldg-%04d" % i, "ticket": "t-x-%d" % i,
            "line": _LINE, "repos": _repos(sha), "actor": "lane", "at": at}


def _call(fn, *a, **k):
    try:
        return (None, None, fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, e, None)


# ---------------------------------------------------------------- 主程序

def main():
    global _TMP
    tmp = Path(tempfile.mkdtemp(prefix="t261009-19-cert-"))
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
    if exc or not (dc and callable(getattr(dc, "should_certify", None))
                   and callable(getattr(dc, "build_certification", None))):
        ok(False, "Z1 develop_certify 公共面在位",
           "%s: %s / not landed (TDD-phase red expected)" % (exc, e))
        finish(NAME)

    import scenario_ledger as sl  # noqa: E402
    led_path = dled / dc.MAIN_NAME

    # 真 run 头（被引 run）：计数可从行重数对证的两行 pass + 一份绿头，
    # 经真实 scenario_ledger 写进临时目录（t261009-11 契约）。
    green_run = sl.mint_run_id()
    sl.append_records(
        [{"ts": "2026-10-09T00:00:00+00:00", "commit": _C, "env_fp": _FP,
          "conc_width": 1, "pool": "ro", "scenario": "c%d" % i,
          "verdict": "pass", "wall_s": 0.01, "source": "baseline",
          "ticket": "", "run": green_run} for i in range(2)],
        path=sled / "scenario-results.jsonl")
    try:
        rec = sl.append_run_header({
            "v": sl.RUN_HEADER_V, "id": green_run,
            "repos": [{"repo": "sandbar", "revision": _C}],
            "suite": "full", "source": "lane:t261009-19", "env_fp": _FP,
            "conc_width": 1, "pool": "ro", "started_at": 1791506200000,
            "duration_s": 1.5,
            "cases": {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0},
            "verdict": "green",
        })
        w, whys = rec.get("written", 0), [
            r.get("reason", "") for r in rec.get("rejected", ())]
    except Exception as ex:  # noqa: BLE001
        w, whys = 0, ["%s: %s" % (type(ex).__name__, ex)]
    if w != 1 or whys:
        ok(False, "Z2 真 run 头夹具落盘", "written=%s why=%s" % (w, whys))
        finish(NAME)
    header = sl.rows_for_run(green_run).get("header")

    cert_row = dc.build_certification(
        _repos(_C), header, "inv-" + _FP[:16], "integration-scenario",
        at_ms=1791506200100, line=_LINE)

    # ---------------- A 每 tick 至多一次 ----------------
    rows0, bad = dc.read_rows(led_path)
    ok(not bad and rows0 == [], "A0 空账即空读（缺席不造行）",
       "rows=%r bad=%r" % (rows0, bad))
    dc.append_rows([_landing(1, _C)], led_path)  # 线上有了未认证内容
    rows0, _ = dc.read_rows(led_path)
    go, why = dc.should_certify("change", rows0, _LINE, False)
    ok(go is True and why == "range_non_empty",
       "A1 线上有未认证内容 + 守卫空闲 → 判认证（变更触发）",
       "go=%r why=%r" % (go, why))
    guard = dc.guard_acquire(str(led_path), "t261009-19")
    ok(isinstance(guard, dict) and guard.get("held") is True,
       "A2 令牌可获取（in-flight 标记落盘）", "guard=%r" % (guard,))
    go2, why2 = dc.should_certify("change", rows0, _LINE, True)
    ok(go2 is False and why2 == "guard_held",
       "A3 守卫被持（本 tick 已在认证）⇒ 再触发不判（at most once per tick）",
       "go=%r why=%r" % (go2, why2))
    guard2 = dc.guard_acquire(str(led_path), "second-claimant")
    ok(guard2 is None, "A4 第二次 acquire 拿不到令牌（本 tick 无人再开证明）",
       "guard2=%r" % (guard2,))
    dc.guard_release(str(led_path))
    go3, why3 = dc.should_certify("change", rows0, _LINE, False)
    ok(go3 is True, "A5 释放后仍可判（守卫挡的是并发，不是内容）",
       "go=%r why=%r" % (go3, why3))

    # ---------------- B 引用而不复述 ----------------
    wrec = dc.append_rows([cert_row], led_path)
    ok(wrec.get("written") == 1 and len(wrec.get("seqs", ())) == 1,
       "B1 认证记录落账、拿共享 seq", json.dumps(wrec)[:200])
    rows, bad = dc.read_rows(led_path)
    cert = [r for r in rows if r.get("kind") == "certification"][0]
    ok(cert.get("run") == green_run and cert.get("judged_by")
       and cert.get("booked_red") == "inv-" + _FP[:16]
       and isinstance(cert.get("at"), int),
       "B2 记录带所引 run、judged_by、库存版本、时刻",
       json.dumps({k: cert.get(k) for k in
                   ("run", "judged_by", "booked_red", "at")})[:220])
    ok(isinstance(cert.get("repos"), list) and len(cert["repos"]) == 1
       and cert["repos"][0] == {"repo": "sandbar", "revision": _C},
       "B3 候选=修订集合（repo→revision，今天一个成员）",
       "repos=%r" % (cert.get("repos"),))
    banned = [k for k in ("counts", "cases", "verdict", "passed", "failed",
                          "ran", "env_failed") if k in cert]
    ok(not banned, "B4 记录本体零 counts/verdict（属于它引用的 run）",
       "banned=%s" % banned)
    thief = dict(cert_row)
    thief["id"] = "cert-" + "Z" * 26
    thief["verdict"] = "green"
    wrec2 = dc.append_rows([thief], led_path)
    why_t = (wrec2.get("rejected") or [{}])[0].get("reason", "")
    ok(wrec2.get("written") == 0 and "restates" in why_t,
       "B5 复述 counts/verdict 的认证按名拒写（schema 违例，不是惯例缺席）",
       json.dumps(wrec2)[:220])

    # ---------------- C 覆盖范围从记录序推导 ----------------
    dc.append_rows([_landing(2, _C), _landing(3, _B)], led_path)
    rows, bad = dc.read_rows(led_path)
    rng = dc.derive_range(rows, _LINE)
    covered = [l["id"] for l in rng["covered_landings"]]
    ok("ldg-0002" in covered and "ldg-0003" in covered,
       "C1 上一次认证之后落下的 landing 在覆盖内（从记录序推导）",
       "covered=%s" % covered)
    ok(rng["previous_certification"]["id"] == cert["id"]
       and rng["certified_prefix"] == _repos(_C),
       "C2 derive_range 交出前一次认证与最大已认证修订集",
       json.dumps(rng)[:220])
    seq_of_cert = cert["seq"]
    tie = _landing(9, _C)
    tie["seq"] = seq_of_cert  # 与认证同 seq：序上不算「之后」
    rng_tie = dc.derive_range(rows + [tie], _LINE)
    ok("ldg-0009" not in [l["id"] for l in rng_tie["covered_landings"]],
       "C3 landing 与认证同 seq ⇒ 不在覆盖内（seq 定界，时钟不参赛）",
       "covered=%s" % [l["id"] for l in rng_tie["covered_landings"]])
    projected = dict(cert)
    projected["covered_range"] = ["ldg-0002"]
    ok(dc.validate_row(projected)[0] is not None,
       "C4 stored covered_range 是合法投影（derive_range 仍是唯一权威）",
       "row=covered_range list")

    # ---------------- D 最大已认证前缀恒可落 ----------------
    # t261011-23 仲裁迭代：覆盖从「修订相等」改为「绿区间成员」（票面一把尺子），
    # 所以「被绿认证盖住」的判据必须落在账本里拿得到 seq 的那行 landing 上
    # （ldg-0001 在绿认证之前落账、内容=绿认证候选 _C）——账外的裸行没有 seq，
    # 不在任何区间内，这不是覆盖面的语义。
    rows_by_id = {r["id"]: r for r in rows if r.get("id")}
    prefix_landing = rows_by_id["ldg-0001"]  # 内容=绿认证盖住的那份修订
    ok(dc.landable(rows, _LINE, prefix_landing,
                   is_green=lambda r: True) is True,
       "D1 绿认证盖住的 landing 答「可落」", "landable=True")
    # 红认证：引用另一轮 run 的认证行（红面细节由
    # sc_t26100919_red_bounded.py 锁，本条只用它撑「线上红了」的状态）。
    red_header = dict(header)
    red_header["id"] = sl.mint_run_id()
    red_header["cases"] = {"ran": 3, "passed": 2, "failed": 1,
                           "env_failed": 0}
    red_header["verdict"] = "red"
    red_cert = dc.build_certification(
        _repos(_B), red_header, "inv-" + _FP[:16], "integration-scenario",
        at_ms=1791506200200, line=_LINE)
    wrec_r = dc.append_rows([red_cert], led_path)
    if wrec_r.get("written") != 1:
        ok(False, "D2 红认证夹具落账", json.dumps(wrec_r)[:200])
        finish(NAME)
    rows2, _ = dc.read_rows(led_path)
    rng2 = dc.derive_range(rows2, _LINE)
    ok(rng2["certified_prefix"] == _repos(_B),
       "D2 前缀面照实答最大已认证修订集（最后一份认证=红的那份——面诚实）",
       "prefix=%r" % (rng2["certified_prefix"],))
    rows2_by_id = {r["id"]: r for r in rows2 if r.get("id")}
    prefix_landing = rows2_by_id["ldg-0001"]
    ok(dc.landable(rows2, _LINE, prefix_landing,
                   is_green=lambda r: r == green_run) is True,
       "D3 绿认证盖住的 landing 在红认证在账时仍答「可落」——"
       "可落性键在绿认证上（goal 8：红不挟持已证明内容）", "landable=True")
    fresh = _landing(4, "c" * 40)
    ok(dc.landable(rows2, _LINE, fresh,
                   is_green=lambda r: r == green_run) is False,
       "D4 没有绿认证盖住的 landing 不答「可落」（证明不可假装）",
       "landable=False")

    finish(NAME)


if __name__ == "__main__":
    try:
        main()
    finally:
        _cleanup()
